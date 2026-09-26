# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Deck-scoped reports and local single-slot exercises."""

from __future__ import annotations

import base64
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtSvg import QSvgRenderer

from anki.decks import DeckId
from aqt import gui_hooks
from aqt.qt import (
    QByteArray,
    QColor,
    QComboBox,
    QDate,
    QDateEdit,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QImage,
    QLabel,
    QPainter,
    QPen,
    QPixmap,
    QPushButton,
    QRectF,
    QSplitter,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTimer,
    QVBoxLayout,
)
from aqt.utils import showWarning

from .weak_review import STORAGE_ERRORS, card_identity
from .weak_review_insights import (
    InsightStore,
    collect_items,
    practice_interval,
    report_batches,
)


def region_image(store: InsightStore, item: dict, reveal: bool) -> QImage:
    uri = store.asset(item["asset"])
    if not uri:
        raise ValueError("原图快照不可用，请先回到原卡复习以更新图片。")
    header, payload = uri.split(",", 1)
    raw = QByteArray(base64.b64decode(payload, validate=True))
    if "image/svg+xml" in header:
        renderer = QSvgRenderer(raw)
        if not renderer.isValid():
            raise ValueError("图片快照无效。")
        size = renderer.defaultSize()
        if size.isEmpty():
            raise ValueError("图片没有有效尺寸。")
        size.scale(1800, 1800, Qt.AspectRatioMode.KeepAspectRatio)
        image = QImage(size, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
    else:
        image = QImage.fromData(raw)
        if image.isNull():
            raise ValueError("图片快照无法显示。")
        image = image.scaled(
            1800,
            1800,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    region = item.get("region")
    if (
        not isinstance(region, list)
        or len(region) != 4
        or any(type(v) not in (float, int) for v in region)
    ):
        raise ValueError("此区域缺少可靠坐标，请使用原卡复习。")
    x, y, width, height = region
    if not (
        0 <= x < 1
        and 0 <= y < 1
        and width > 0
        and height > 0
        and x + width <= 1.01
        and y + height <= 1.01
    ):
        raise ValueError("此区域坐标无效。")
    rect = QRectF(
        x * image.width(),
        y * image.height(),
        width * image.width(),
        height * image.height(),
    )
    painter = QPainter(image)
    if not reveal:
        painter.fillRect(rect, QColor("#bed8cd"))
    painter.setPen(QPen(QColor("#bf581f"), 3))
    painter.drawRect(rect)
    painter.end()
    return image


def still_current(mw, store: InsightStore, item: dict) -> bool:
    row = (
        mw.col.db.first("select queue,odid from cards where id=?", item["card"])
        if mw.col
        else None
    )
    return bool(
        row
        and row[0] >= 0
        and not row[1]
        and card_identity(mw.col.get_card(item["card"])) == item["source"]
        and any(
            c["card"] == item["card"] and c["manifest"] == item["manifest"]
            for c in store.catalogs()
        )
    )


class PracticeDialog(QDialog):
    def __init__(self, parent, items: list[dict]) -> None:
        super().__init__(parent)
        self.mw, self.store = parent.mw, parent.store
        self.items = items
        self.position = 0
        self.undo_stack: list[tuple[int, int]] = []
        self.revealed = False
        self.setWindowTitle("单空专项练习")
        self.resize(900, 760)
        layout = QVBoxLayout(self)
        self.progress = QLabel()
        layout.addWidget(self.progress)
        self.context = QTextBrowser()
        layout.addWidget(self.context, 1)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.picture, 2)
        self.answer = QTextBrowser()
        self.answer.setMaximumHeight(150)
        layout.addWidget(self.answer)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.reveal_button = QPushButton("显示这个空的答案")
        self.reveal_button.clicked.connect(self.reveal)
        row.addWidget(self.reveal_button)
        self.fail_button = QPushButton("没记住 · 10 分钟后")
        self.fail_button.clicked.connect(lambda: self.grade(False))
        row.addWidget(self.fail_button)
        self.pass_button = QPushButton("记住了")
        self.pass_button.clicked.connect(lambda: self.grade(True))
        row.addWidget(self.pass_button)
        self.undo_button = QPushButton("撤销上一次专项评分")
        self.undo_button.clicked.connect(self.undo)
        layout.addWidget(self.undo_button)
        note = QLabel("专项练习有独立的本机到期时间；原卡仍按 Anki 的整卡计划复习。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.load_item()

    def load_item(self) -> None:
        self.revealed = False
        self.undo_button.setEnabled(bool(self.undo_stack))
        self.fail_button.setEnabled(False)
        self.pass_button.setEnabled(False)
        self.picture.clear()
        self.answer.clear()
        while self.position < len(self.items) and not still_current(
            self.mw, self.store, self.items[self.position]
        ):
            self.position += 1
        if self.position >= len(self.items):
            self.progress.setText("本组专项练习已完成")
            self.context.setPlainText(
                "已更新每个空的专项复习时间。可关闭窗口，或撤销刚才的评分。"
            )
            self.reveal_button.setEnabled(False)
            return
        item = self.items[self.position]
        self.progress.setText(
            f"{self.position + 1}/{len(self.items)} · {item['deck']} · 空格 {int(item['key'][1:]) + 1}"
        )
        self.context.setPlainText(
            item["context"] or "根据原图上下文，回忆橙色框内的内容。"
        )
        self.reveal_button.setEnabled(True)
        interval = practice_interval(item["score"], True)
        previous = self.store.practices(
            item["card"], item["source"], item["manifest"], item["key"]
        )
        if previous:
            interval = practice_interval(item["score"], True, previous[-1]["interval"])
        self.pass_button.setText(f"记住了 · {interval // 86400} 天后")
        if item.get("asset"):
            try:
                self.paint_image(False)
            except (ValueError, RuntimeError) as exc:
                self.context.append(str(exc))
                self.reveal_button.setEnabled(False)

    def paint_image(self, reveal: bool) -> None:
        image = region_image(self.store, self.items[self.position], reveal)
        pixmap = QPixmap.fromImage(image).scaled(
            840,
            420,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.picture.setPixmap(pixmap)

    def reveal(self) -> None:
        if self.position >= len(self.items):
            return
        item = self.items[self.position]
        if not still_current(self.mw, self.store, item):
            self.load_item()
            return
        try:
            if item.get("asset"):
                self.paint_image(True)
            self.answer.setPlainText(item["answer"] or "请核对原图橙色框内的答案。")
            self.revealed = True
            self.fail_button.setEnabled(True)
            self.pass_button.setEnabled(True)
            self.reveal_button.setEnabled(False)
        except (ValueError, RuntimeError) as exc:
            showWarning(str(exc), parent=self)

    def grade(self, remembered: bool) -> None:
        if not self.revealed or self.position >= len(self.items):
            return
        item = self.items[self.position]
        if not still_current(self.mw, self.store, item):
            self.load_item()
            return
        try:
            key = self.store.practice(item, remembered, int(time.time()))
            self.undo_stack.append((key, self.position))
            self.position += 1
            self.load_item()
        except STORAGE_ERRORS as exc:
            showWarning(str(exc), parent=self)

    def undo(self) -> None:
        if self.undo_stack:
            key, position = self.undo_stack[-1]
            try:
                self.store.undo_practice(key)
                self.undo_stack.pop()
                self.position = position
                self.load_item()
            except STORAGE_ERRORS as exc:
                showWarning(str(exc), parent=self)


class InsightDialog(QDialog):
    def __init__(self, mw, store: InsightStore) -> None:
        super().__init__(mw)
        self.mw, self.store = mw, store
        self.profile = Path(mw.pm.profileFolder())
        self.items: list[dict] = []
        self.report_text = ""
        self.display_snapshot: dict = {}
        self.display_ai = ""
        self.display_model = ""
        self.busy = False
        self.closed = False
        self.cancel_generation = threading.Event()
        self.setWindowTitle("逐空薄弱项 · 总结与专项练习")
        self.resize(1080, 780)
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        layout.addLayout(filters)
        self.deck = QComboBox()
        for entry in mw.col.decks.all_names_and_ids():
            self.deck.addItem(entry.name, int(entry.id))
        owner = getattr(mw, "dual_review", None)
        current_deck = (
            owner.active.deck.currentData()
            if owner and owner.managed and owner.active
            else mw.col.decks.get_current_id()
        )
        self.deck.setCurrentIndex(self.deck.findData(int(current_deck)))
        filters.addWidget(self.deck, 2)
        self.kind = QComboBox()
        self.kind.addItems(["每日总结", "子集全面总结"])
        filters.addWidget(self.kind)
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        filters.addWidget(self.day)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh)
        filters.addWidget(self.refresh_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter, 1)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                "牌组 / 空格",
                "近期难度",
                "最近轮次数",
                "累计次数",
                "当日未记住",
                "专项到期",
            ]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.table)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(False)
        splitter.addWidget(self.details)
        self.table.itemSelectionChanged.connect(self.select_item)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.practice_button = QPushButton("单独练习选中空格")
        self.practice_button.clicked.connect(self.practice_selected)
        actions.addWidget(self.practice_button)
        self.due_button = QPushButton("练习本牌组全部到期薄弱空格")
        self.due_button.clicked.connect(self.practice_due)
        actions.addWidget(self.due_button)
        self.ai_button = QPushButton("生成 AI 总结")
        self.ai_button.clicked.connect(self.generate)
        actions.addWidget(self.ai_button)
        export = QPushButton("导出整份报告…")
        export.clicked.connect(self.export)
        actions.addWidget(export)
        self.history = QComboBox()
        self.history.addItem("查看已保存的 AI 总结", None)
        for report in store.reports():
            snap = report["snapshot"]
            self.history.addItem(
                f"{snap['day']} · {snap['scope']} · {snap['kind']} · {report['model']}",
                report,
            )
        self.history.currentIndexChanged.connect(self.show_history)
        layout.addWidget(self.history)
        info = QLabel(
            "含子牌组。次数按已评分的实际测试统计，揭示/翻面/刷新不增加次数。点击生成才会将当前列表中的答案、上下文及图像区域发送给默认 AI。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        for signal in (
            self.deck.currentIndexChanged,
            self.kind.currentIndexChanged,
            self.day.dateChanged,
        ):
            signal.connect(self.refresh)
        gui_hooks.profile_will_close.append(self.profile_closing)
        self.finished.connect(self.dispose)
        self.refresh()

    def profile_closing(self) -> None:
        self.closed = True
        self.cancel_generation.set()
        QTimer.singleShot(0, self.close)

    def dispose(self, *args) -> None:
        self.closed = True
        self.cancel_generation.set()
        gui_hooks.profile_will_close.remove(self.profile_closing)

    def deck_ids(self) -> set[int]:
        did = self.deck.currentData()
        return (
            set(self.mw.col.decks.deck_and_child_ids(DeckId(did)))
            if did is not None
            else set()
        )

    def refresh(self, *args) -> None:
        if self.closed or self.busy or not self.mw.col:
            return
        try:
            date = datetime.strptime(self.day.date().toString("yyyy-MM-dd"), "%Y-%m-%d")
            day = (
                (int(date.timestamp()), int((date + timedelta(days=1)).timestamp()))
                if self.kind.currentIndex() == 0
                else None
            )
            self.day.setEnabled(day is not None)
            self.items = collect_items(
                self.mw.col, self.store, self.deck_ids(), int(time.time()), day
            )
            self.table.setRowCount(len(self.items))
            for row, item in enumerate(self.items):
                values = [
                    f"{item['deck']} · {int(item['key'][1:]) + 1}",
                    f"{item['level']} {round(item['score'] * 100)}/100",
                    item["last_attempts"],
                    item["total_attempts"],
                    item["day_misses"],
                    datetime.fromtimestamp(item["due"]).strftime("%m-%d %H:%M"),
                ]
                for column, value in enumerate(values):
                    self.table.setItem(row, column, QTableWidgetItem(str(value)))
            batches = len(report_batches(self.items))
            self.ai_button.setText(f"生成 AI 总结（{batches} 批）")
            self.ai_button.setEnabled(bool(self.items))
            self.practice_button.setEnabled(bool(self.items))
            self.status.setText(
                f"{self.deck.currentText()}及子牌组 · {len(self.items)} 个薄弱空格；难度按最近轮次更新，旧难点可以降级。未升级前的次数没有记录，不能追溯。"
            )
            self.report_text = self.local_report()
            self.display_snapshot = self.snapshot()
            self.display_ai = self.display_model = ""
            self.preview_report()
        except STORAGE_ERRORS as exc:
            showWarning(str(exc), parent=self)

    def local_report(self) -> str:
        lines = [
            f"# {self.day.date().toString('yyyy-MM-dd')} · {self.kind.currentText()}",
            f"范围：{self.deck.currentText()}及子牌组；{len(self.items)} 个薄弱空格。",
            "难度分为本地近期表现指标，不是记忆概率。",
        ]
        for item in self.items:
            lines += [
                f"\n## {item['deck']} · 卡片 {item['card']} / {item['key']}",
                f"{item['level']} {round(item['score'] * 100)}/100；最近轮测试 {item['last_attempts']} 次，累计 {item['total_attempts']} 次；当日测试 {item['day_attempts']} 次，未记住 {item['day_misses']} 次。",
                "上下文：" + item["context"],
                "答案：" + (item["answer"] or "图像区域，请查看原图"),
                "上下文为目标附近节选。" if item.get("context_excerpt") else "",
            ]
        return "\n\n".join(lines)

    def snapshot(self) -> dict:
        return {
            "scope": self.deck.currentText() + "及子牌组",
            "deck_id": self.deck.currentData(),
            "day": self.day.date().toString("yyyy-MM-dd"),
            "kind": self.kind.currentText(),
            "created_at": int(time.time()),
            "items": self.items,
        }

    def preview_report(self) -> None:
        from .weak_review_report import render_report

        self.details.setHtml(
            render_report(self.display_snapshot, self.display_ai, self.display_model)
        )

    def select_item(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.items):
            item = self.items[row]
            self.details.setPlainText(
                f"{item['deck']} · {item['card']} / {item['key']}\n\n{item['context']}\n\n答案：{item['answer'] or '图像区域，请点击专项练习查看原图'}"
            )

    def practice_selected(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.items):
            PracticeDialog(self, [self.items[row]]).exec()
            self.refresh()

    def practice_due(self) -> None:
        try:
            items = collect_items(
                self.mw.col, self.store, self.deck_ids(), int(time.time())
            )
            due = [item for item in items if item["overdue"]]
            if not due:
                self.status.setText(
                    "当前牌组及子牌组没有到期的专项薄弱空格。可选中某个空格提前练习。"
                )
                return
            PracticeDialog(self, due).exec()
            self.refresh()
        except STORAGE_ERRORS as exc:
            showWarning(str(exc), parent=self)

    def generate(self) -> None:
        if self.busy or not self.items:
            return
        from .synapsepro import ai_assistant as ai
        from .synapsepro.ai_images import prepare_image
        from .weak_review_ai import summarize

        settings = ai._load_settings()
        if not settings["model"] or not ai._is_configured(
            settings["provider"], settings["apiKey"]
        ):
            showWarning("请先在现有 AI 询问设置中配置默认模型与密钥。", parent=self)
            return
        images = {}
        try:
            for item in self.items:
                if not still_current(self.mw, self.store, item):
                    self.refresh()
                    return
                if item.get("asset"):
                    images[f"{item['card']}:{item['key']}"] = prepare_image(
                        region_image(self.store, item, True)
                    )
        except (ValueError, RuntimeError) as exc:
            showWarning(str(exc), parent=self)
            return
        if (
            images
            and settings["provider"] == "deepseek"
            and settings["model"]
            in ("deepseek-chat", "deepseek-reasoner", "deepseek-v4-pro")
        ):
            showWarning(
                "当前列表包含图像区域，请在现有 AI 询问设置中选择支持图片的模型。",
                parent=self,
            )
            return
        snapshot = self.snapshot()
        self.busy = True
        for widget in (
            self.deck,
            self.kind,
            self.day,
            self.refresh_button,
            self.ai_button,
            self.practice_button,
            self.due_button,
        ):
            widget.setEnabled(False)
        self.status.setText(
            f"正在使用 {settings['provider']} / {settings['model']} 分析全部 {len(self.items)} 个空格…"
        )

        def finished(future) -> None:
            try:
                text = future.result()
                if (
                    self.closed
                    or not self.mw.col
                    or Path(self.mw.pm.profileFolder()) != self.profile
                ):
                    return
                model = settings["provider"] + " / " + settings["model"]
                self.store.save_report(snapshot, text, model)
                self.display_snapshot, self.display_ai, self.display_model = (
                    snapshot,
                    text,
                    model,
                )
                self.preview_report()
                self.history.addItem(
                    f"{snapshot['day']} · {snapshot['scope']} · {snapshot['kind']}",
                    {"snapshot": snapshot, "text": text, "model": model},
                )
                self.status.setText("AI 总结已保存到本机，可从下方历史列表查看或导出。")
            except Exception as exc:
                if not self.closed:
                    self.status.setText(
                        "AI 总结失败；本地统计和之前的报告保留，可重试。"
                    )
                    showWarning(
                        ai._classify_error(exc, settings["provider"]), parent=self
                    )
            finally:
                self.busy = False
                if not self.closed:
                    for widget in (
                        self.deck,
                        self.kind,
                        self.refresh_button,
                        self.ai_button,
                        self.practice_button,
                        self.due_button,
                    ):
                        widget.setEnabled(True)
                    self.day.setEnabled(self.kind.currentIndex() == 0)

        self.mw.taskman.run_in_background(
            lambda: summarize(
                settings, snapshot, images, cancelled=self.cancel_generation.is_set
            ),
            finished,
            uses_collection=False,
        )

    def show_history(self, index: int) -> None:
        if report := self.history.itemData(index):
            snapshot = report["snapshot"]
            self.display_snapshot, self.display_ai, self.display_model = (
                snapshot,
                report["text"],
                report["model"],
            )
            self.preview_report()

    def export(self) -> None:
        path, selected = QFileDialog.getSaveFileName(
            self,
            "导出逐空报告",
            "逐空总结-" + self.display_snapshot["day"] + ".pdf",
            "PDF (*.pdf);;HTML (*.html);;Markdown (*.md)",
        )
        if path:
            try:
                suffix = (
                    ".pdf"
                    if selected.startswith("PDF")
                    else ".html"
                    if selected.startswith("HTML")
                    else ".md"
                )
                destination = Path(path)
                if destination.suffix.lower() != suffix:
                    destination = destination.with_suffix(suffix)
                self.export_to(destination)
                self.status.setText("报告已导出：" + str(destination))
            except (OSError, ValueError, RuntimeError) as exc:
                showWarning(str(exc), parent=self)

    def export_to(self, path: Path) -> None:
        from .synapsepro.ai_images import prepare_image
        from .weak_review_report import render_report, write_pdf

        snapshot = self.display_snapshot
        pictures = {
            f"{item['card']}:{item['key']}": prepare_image(
                region_image(self.store, item, True)
            )["dataUrl"]
            for item in snapshot["items"]
            if item.get("asset")
        }
        content = render_report(snapshot, self.display_ai, self.display_model, pictures)
        if path.suffix.lower() == ".pdf":
            write_pdf(path, content, snapshot["day"] + " · " + snapshot["kind"])
        elif path.suffix.lower() == ".html":
            path.write_text(content, encoding="utf8")
        elif path.suffix.lower() == ".md":
            lines = [
                f"# {snapshot['day']} · {snapshot['kind']}",
                f"范围：{snapshot['scope']}",
                "近期难度为本地启发式指标，不是记忆概率。",
            ]
            for item in snapshot["items"]:
                lines += [
                    f"\n## {item['deck']} · {item['card']} / {item['key']}",
                    f"难度 {round(item['score'] * 100)}/100；最近轮 {item['last_attempts']} 次；累计 {item['total_attempts']} 次；当日未记住 {item['day_misses']} 次。",
                    item["context"],
                    "答案：" + (item["answer"] or "见图像区域"),
                ]
                if picture := pictures.get(f"{item['card']}:{item['key']}"):
                    lines.append(f"![目标区域]({picture})")
            if self.display_ai:
                lines += [
                    "\n# AI 分析（推断与建议）",
                    "模型：" + self.display_model,
                    self.display_ai,
                ]
            path.write_text("\n\n".join(lines), encoding="utf8")
        else:
            raise ValueError("请选择 PDF、HTML 或 Markdown 格式。")
