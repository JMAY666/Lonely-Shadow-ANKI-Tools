# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Per-renderer recall controls with a separate, local persistence boundary."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from aqt.qt import QAction, QCursor, QMenu, QTimer, QWebEngineScript
from aqt.utils import showWarning, tooltip

from .weak_review_insights import InsightStore, begin_visit, burden, level, slot_scores
from .weak_review_schedule import apply_round_schedule, round_plan
from .weak_review_store import RecallStore, continues_round, digest

IMAGE_HOST = "mumu-anki-pic.oss-cn-hangzhou.aliyuncs.com"
SETTING = "weakReviewEnabled"
AUTO_SETTING = "weakReviewAutoPass"
STORAGE_ERRORS = (OSError, ValueError, sqlite3.Error)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("图片地址发生跳转，保留原卡片复习")


def image_snapshot(url: str) -> tuple[str, str]:
    """Only retrieve the original supported template's public image resource."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != IMAGE_HOST
        or not parsed.path.startswith("/card-pic/")
        or parsed.query
        or parsed.fragment
        or not parsed.path.lower().endswith((".svg", ".png", ".jpg", ".jpeg", ".webp"))
    ):
        raise ValueError("当前图片来源不支持逐空标记")
    with build_opener(NoRedirects()).open(Request(url), timeout=15) as response:
        data = response.read(16 * 1024 * 1024 + 1)
        mime = response.headers.get_content_type()
    if len(data) > 16 * 1024 * 1024 or mime not in (
        "image/svg+xml",
        "image/png",
        "image/jpeg",
        "image/webp",
    ):
        raise ValueError("图片过大或格式不支持逐空标记")
    return hashlib.sha256(
        data
    ).hexdigest(), "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")


def card_identity(card: Any) -> str:
    note = card.note(reload=True)
    model = note.note_type()
    return digest(
        [
            note.guid,
            card.nid,
            card.ord,
            note.fields,
            note.tags,
            model["tmpls"],
            model["css"],
            model["flds"],
        ]
    )


def schedule_identity(card: Any, col: Any) -> str:
    return digest(
        [
            col.crt,
            [
                getattr(card, key)
                for key in (
                    "type",
                    "due",
                    "ivl",
                    "reps",
                    "lapses",
                    "left",
                    "odue",
                    "odid",
                )
            ],
            col.db.scalar("select max(id) from revlog where cid=?", card.id),
        ]
    )


class WeakReview:
    def __init__(self, reviewer: Any) -> None:
        self.reviewer = reviewer
        self.mw = reviewer.mw
        self.token = ""
        self.card_id = 0
        self.full = False
        self.manifest = ""
        self.slots: list[str] = []
        self.value: dict = {"known": [], "history": []}
        self.status = "正在识别可独立作答的空格"
        self.asset_cache: dict[str, tuple[str, str]] = {}
        self.pending_manifest = ""
        self.request: str | None = None
        self.auto_pending: tuple | None = None
        self.submitted_plan: dict | None = None
        script = QWebEngineScript()
        script.setName("anki-weak-review")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        script.setSourceCode(
            Path(__file__).with_suffix(".js").read_text(encoding="utf8")
        )
        reviewer.web.page().scripts().insert(script)
        controllers = getattr(self.mw, "_weak_review_controllers", [])
        controllers.append(self)
        self.mw._weak_review_controllers = controllers
        if not getattr(self.mw, "_weak_review_insights_action", None):
            action = QAction("逐空薄弱项 · 总结与专项练习…", self.mw)
            action.triggered.connect(self.dashboard)
            self.mw.form.menuTools.addAction(action)
            self.mw._weak_review_insights_action = action

    @property
    def enabled(self) -> bool:
        return bool(self.mw.pm.profile.get(SETTING, True))

    @property
    def store(self) -> RecallStore:
        return RecallStore(Path(self.mw.pm.profileFolder()) / "weak-review.sqlite3")

    @property
    def insights(self) -> InsightStore:
        return InsightStore(self.store.path)

    @property
    def auto_pass(self) -> bool:
        return bool(self.mw.pm.profile.get(AUTO_SETTING, True))

    def show(self) -> None:
        reviewer = self.reviewer
        card = reviewer.card
        if not card:
            return
        schedule = schedule_identity(card, self.mw.col)
        if (self.card_id, getattr(self, "schedule", None)) != (card.id, schedule):
            self.full = False
            self.asset_cache.clear()
            self.auto_pending = None
        if reviewer.state == "question":
            self.asset_cache.clear()
        self.card_id = card.id
        self.schedule = schedule
        self.source = card_identity(card)
        self.token = uuid.uuid4().hex
        self.manifest = ""
        self.slots = []
        self.value = {"known": [], "history": []}
        self.pending_manifest = ""
        self.request = None
        self.status = "此卡未识别到支持的空格，保持原复习方式"
        config = {
            "token": self.token,
            "side": reviewer.state,
            "enabled": self.enabled and not card.odid,
            "full": self.full,
            "question": card.question(),
            "ordinal": card.ord + 1,
        }
        if card.odid:
            self.status = "筛选牌组暂不启用逐空标记"
        reviewer.web.eval(
            f"_queueAction(() => window.ankiWeakReview?.start({json.dumps(config)}));"
        )
        self.update_button()
        if reviewer.state == "answer":
            reviewer._showEaseButtons()

    def controls_round(self) -> bool:
        card = self.reviewer.card
        return bool(
            self.manifest
            and self.enabled
            and not self.full
            and card
            and card.id == self.card_id
            and not card.odid
        )

    def plan(self) -> dict:
        valid = set(
            self.mw.col.db.list("select id from revlog where cid=?", self.card_id)
        )
        events = self.insights.events(self.card_id, self.source, self.manifest, valid)
        config = self.mw.col.decks.config_dict_for_deck_id(
            self.reviewer.card.current_deck_id()
        )
        card = self.reviewer.card
        baseline = (
            {"next_days": card.ivl, "at": max(valid, default=0) // 1000}
            if card.type == 2 and card.ivl > 0
            else None
        )
        return round_plan(
            self.value,
            self.slots,
            events,
            int(time.time()),
            int(config.get("rev", {}).get("maxIvl", 36500)),
            native_baseline=baseline,
        )

    def normalize_rating(self, ease: int) -> int | None:
        self.submitted_plan = None
        if not self.controls_round():
            return ease
        if not self.current(self.token, action=True):
            return None
        complete = set(self.value["known"]) == set(self.slots)
        if ease != 1 and not complete:
            tooltip("还有未记住的空，请标记掌握项后点击“再练未掌握”。", parent=self.mw)
            return None
        if ease == 1 and complete:
            tooltip("本轮已全部记住；如需重新练习，请先取消对应标记。", parent=self.mw)
            return None
        return 3 if complete else 1

    def prepare_answer(self, answer: Any) -> bool:
        if not self.controls_round():
            return True
        try:
            plan = self.plan()
            config = self.mw.col.decks.config_dict_for_deck_id(
                self.reviewer.card.current_deck_id()
            )
            initial_ease = config.get("new", {}).get("initialFactor", 2500) / 1000
            apply_round_schedule(answer, plan, initial_ease)
            self.submitted_plan = plan
            return True
        except STORAGE_ERRORS as exc:
            showWarning("逐空评分未提交，请重试。\n" + str(exc), parent=self.mw)
            return False

    def answer_buttons(self) -> str | None:
        if not self.controls_round():
            return None
        try:
            plan = self.plan()
        except STORAGE_ERRORS:
            return "<div>逐空评分暂不可用，请重新打开此卡。</div>"
        complete = plan["completed"]
        progress = f"本轮已记住 {len(self.value['known'])}/{len(self.slots)}"
        detail = f"表现分 {plan['quality']}/100" if complete else "标记掌握项后继续"
        time_style = 'style="display:block;position:static;transform:none;font-size:11px;font-weight:normal;line-height:1.4;margin-top:3px;opacity:.8"'
        button_style = (
            'style="height:auto;min-height:44px;padding:6px 12px;line-height:1.3"'
        )
        return (
            '<center><div style="font-size:12px;margin:0 0 5px">'
            f"逐空评分 · {progress} · {detail}"
            '</div><button data-ease="1" onclick="pycmd(\'ease1\');" '
            + button_style
            + " "
            + ("disabled " if complete else "")
            + f">再练未掌握<span {time_style}>约 {plan['loop_seconds'] // 60} 分钟</span></button> "
            + '<button id="defease" data-ease="3" onclick="pycmd(\'ease3\');" '
            + button_style
            + " "
            + ("" if complete else "disabled ")
            + f">完成本轮<span {time_style}>"
            + (f"{plan['next_days']} 天后复习" if complete else "全部勾选后可完成")
            + "</span></button></center>"
        )

    def current(self, token: str, *, action: bool = False) -> bool:
        reviewer = self.reviewer
        if (
            token != self.token
            or self.mw.state != "review"
            or not reviewer.card
            or reviewer.card.id != self.card_id
            or reviewer.state not in ("question", "answer")
            or not self.enabled
            or reviewer.card.odid
            or (
                action
                and (not reviewer.controls_active() or self.mw._background_op_count)
            )
        ):
            return False
        card = self.mw.col.get_card(self.card_id)
        return self.source == card_identity(
            card
        ) and self.schedule == schedule_identity(card, self.mw.col)

    def receive(self, command: str) -> None:
        try:
            if len(command) > 1_000_000:
                return
            data = json.loads(command)
            if not isinstance(data, dict) or not self.current(data.get("token", "")):
                return
            kind = data.get("kind")
            if kind == "manifest":
                self.accept_manifest(data)
            elif kind == "revealComplete":
                if (
                    data.get("request") != self.request
                    or not self.manifest
                    or self.reviewer.state != "question"
                ):
                    return
                if panel := self.reviewer.review_panel():
                    panel.owner.activate(panel)
                if self.current(self.token, action=True):
                    self.reviewer._getTypedAnswer()
            elif kind == "mark":
                if data.get("request") != self.request:
                    return
                if panel := self.reviewer.review_panel():
                    panel.owner.activate(panel)
                if not self.current(self.token, action=True):
                    return
                key, known = data.get("key"), data.get("known")
                if self.manifest and key in self.slots and type(known) is bool:
                    keys = set(self.value["known"])
                    if known:
                        keys.add(key)
                    else:
                        keys.discard(key)
                    self.change(sorted(keys))
            elif kind == "unsupported":
                self.fail("未识别到支持的空格或图片，保持原复习方式")
        except STORAGE_ERRORS as exc:
            self.fail(str(exc))

    def accept_manifest(self, data: dict) -> None:
        slots = data.get("slots")
        adapter = data.get("adapter")
        if (
            adapter
            not in (
                "mumu-svg-v1",
                "mumu-text-v1",
                "mumu-table-v1",
                "native-cloze-v1",
                "aswk-v1",
                "enhanced-cloze-v1",
            )
            or not isinstance(slots, list)
            or not 1 <= len(slots) <= 512
            or not all(isinstance(slot, str) and len(slot) <= 20000 for slot in slots)
        ):
            return
        pending = digest(data)
        if pending == self.pending_manifest:
            return
        self.pending_manifest = pending
        self.request = data.get("request")
        token = self.token

        def finish(asset: tuple[str, str] | None = None) -> None:
            if not self.current(token) or pending != self.pending_manifest:
                return
            try:
                self.manifest = digest(
                    [adapter, slots, data.get("identity"), asset[0] if asset else None]
                )
                self.slots = [f"s{i}" for i in range(len(slots))]
                self.value = self.store.load(
                    self.card_id, self.schedule, self.source, self.manifest
                )
                self.value["known"] = [
                    key for key in self.value["known"] if key in self.slots
                ]
                if not self.full:
                    value = begin_visit(self.value, self.schedule, self.slots)
                    if value != self.value:
                        self.store.save(
                            self.card_id,
                            self.schedule,
                            self.source,
                            self.manifest,
                            value,
                        )
                        self.value = value
                details = data.get("details")
                if (
                    isinstance(details, list)
                    and len(details) == len(slots)
                    and all(
                        isinstance(item, dict)
                        and item.get("key") == self.slots[i]
                        and isinstance(item.get("answer"), str)
                        and isinstance(item.get("context"), str)
                        and len(item["answer"]) <= 20000
                        and len(item["context"]) <= 5000
                        for i, item in enumerate(details)
                    )
                ):
                    metadata = {"slots": details, "asset": asset[0] if asset else None}
                    self.insights.catalog(
                        self.card_id, self.source, self.manifest, metadata, asset
                    )
                self.publish(asset[1] if asset else None)
                if getattr(self, "auto_pending", None):
                    auto_pending = self.auto_pending
                    QTimer.singleShot(450, lambda: self.submit_auto(auto_pending))
            except STORAGE_ERRORS as exc:
                self.fail(str(exc))

        if adapter != "mumu-svg-v1":
            finish()
            return
        url = data.get("image")
        if not isinstance(url, str):
            return
        if url in self.asset_cache:
            finish(self.asset_cache[url])
            return

        def received(future) -> None:
            if not self.current(token) or pending != self.pending_manifest:
                return
            try:
                asset = future.result()
                self.asset_cache[url] = asset
                finish(asset)
            except Exception:
                self.fail("无法验证图片版本，保持原复习方式；可稍后重新打开此卡")

        self.status = "正在验证图片与遮挡区域"
        self.update_button()
        self.mw.taskman.run_in_background(
            lambda: image_snapshot(url), received, uses_collection=False
        )

    def fail(self, message: str) -> None:
        self.status = message
        self.manifest = ""
        self.reviewer.web.eval(
            f"window.ankiWeakReview?.stop({json.dumps(self.token)});"
        )
        self.update_button()
        if self.reviewer.state == "answer":
            self.reviewer._showEaseButtons()

    def change(self, known: list[str]) -> None:
        if known == self.value["known"]:
            return
        value = {
            **self.value,
            "known": known,
            "history": (self.value["history"] + [self.value["known"]])[-30:],
        }
        self.store.save(self.card_id, self.schedule, self.source, self.manifest, value)
        self.value = value
        self.publish()
        if len(known) == len(self.slots):
            self.queue_auto()
        else:
            self.auto_pending = None

    def queue_auto(self) -> None:
        if not self.auto_pass or self.full:
            tooltip(
                "完整测试可按实际表现评分。"
                if getattr(self, "full", False)
                else "本轮空格已全部记住，点击“完成本轮”即可。",
                parent=self.mw,
            )
            return
        pending = (
            self.card_id,
            self.schedule,
            self.source,
            self.manifest,
            3,
            uuid.uuid4().hex,
            time.monotonic() + 15,
        )
        self.auto_pending = pending
        tooltip(
            "全部记住 · 正在完成本轮；可用 Anki 撤销。",
            parent=self.mw,
        )
        if self.reviewer.state == "question":
            self.reviewer._showAnswer()
        else:
            QTimer.singleShot(450, lambda: self.submit_auto(pending))

    def submit_auto(self, pending: tuple) -> None:
        if self.auto_pending != pending:
            return
        if (
            not self.auto_pass
            or self.full
            or not self.current(self.token, action=True)
            or self.reviewer.state != "answer"
            or (self.card_id, self.schedule, self.source, self.manifest) != pending[:4]
            or set(self.value["known"]) != set(self.slots)
        ):
            self.auto_pending = None
            return
        if not self.reviewer._states_mutated:
            if time.monotonic() < pending[6]:
                QTimer.singleShot(100, lambda: self.submit_auto(pending))
            else:
                self.auto_pending = None
                tooltip("调度计算尚未完成，请稍后手动评分。", parent=self.mw)
            return
        self.auto_pending = None
        self.reviewer._answerCard(pending[4])

    def difficulty(self) -> dict:
        valid = set(
            self.mw.col.db.list("select id from revlog where cid=?", self.card_id)
        )
        events = self.insights.events(self.card_id, self.source, self.manifest, valid)
        current = {
            "session": self.value.get("session", self.schedule),
            "attempts": self.value.get("attempts", {}),
            "known": self.value["known"],
        }
        # An unanswered visit is not a failure. Live highlighting adds repeated
        # exposure only; a first display cannot make every blank a weak point.
        current["known"] = self.slots
        native_events = events
        if max(current["attempts"].values(), default=0) > 1:
            events = events + [current]
        scores = slot_scores(events, self.slots)
        for key, stats in scores.items():
            last_native = max(
                (e["at"] for e in native_events if key in e.get("tested", [])),
                default=0,
            )
            for practice in self.insights.practices(
                self.card_id, self.source, self.manifest, key
            ):
                if practice["at"] > last_native:
                    stats["score"] = 0.35 * stats["score"] + (
                        0 if practice["remembered"] else 0.65
                    )
            stats["level"] = level(stats["score"])
            stats["attempts"] = self.value.get("attempts", {}).get(key, 0)
        return scores

    def publish(self, image: str | None = None) -> None:
        payload = {
            "token": self.token,
            "known": self.value["known"],
            "full": self.full,
            "image": image,
            "request": self.request,
            "difficulty": self.difficulty(),
        }
        self.reviewer.web.eval(f"window.ankiWeakReview?.apply({json.dumps(payload)});")
        score = burden(self.value.get("attempts", {}), self.value["known"])
        self.status = f"本轮已记住 {len(self.value['known'])}/{len(self.slots)}；最多测试 {score['peak']} 次 · 本轮负担 {score['score']}/100"
        self.update_button()
        if self.reviewer.state == "answer":
            self.reviewer._showEaseButtons()

    def update_button(self) -> None:
        label = "逐空"
        if not self.enabled:
            label += " · 已关"
        elif self.manifest:
            label += f" {len(self.value['known'])}/{len(self.slots)}"
            if self.full:
                label += " · 完整"
        self.reviewer.bottom.web.eval(
            "{const b=document.getElementById('weak-review');if(b){"
            f"b.textContent={json.dumps(label)};b.title={json.dumps(self.status)};"
            "}}"
        )

    def menu(self) -> None:
        if not self.reviewer.controls_active() or self.reviewer.state not in (
            "question",
            "answer",
        ):
            return
        menu = QMenu(self.mw)
        status = menu.addAction(self.status)
        status.setEnabled(False)
        toggle = menu.addAction("启用逐空标记（仅本机）")
        toggle.setCheckable(True)
        toggle.setChecked(self.enabled)
        toggle.triggered.connect(self.toggle)
        full = menu.addAction("完整测试（保留本轮标记）")
        full.setCheckable(True)
        full.setChecked(self.full)
        full.setEnabled(bool(self.manifest))
        full.triggered.connect(self.toggle_full)
        undo = menu.addAction("撤销上次逐空标记")
        undo.setEnabled(bool(self.manifest and self.value["history"]))
        undo.triggered.connect(self.undo_mark)
        reset = menu.addAction("重置本轮标记")
        reset.setEnabled(bool(self.manifest and self.value["known"]))
        reset.triggered.connect(self.reset)
        menu.addSeparator()
        auto = menu.addAction("全部勾选后自动完成本轮（逐空评分与间隔）")
        auto.setCheckable(True)
        auto.setChecked(self.auto_pass)
        auto.triggered.connect(self.toggle_auto)
        menu.addAction("薄弱项总结与单空专项练习…", self.dashboard)
        menu.addAction("支持范围与轮次说明", self.help)
        menu.exec(QCursor.pos())

    def toggle(self, enabled: bool) -> None:
        self.mw.pm.profile[SETTING] = enabled
        self.mw.pm.save()
        for controller in self.mw._weak_review_controllers:
            if controller.reviewer.card:
                controller.show()

    def toggle_full(self, full: bool) -> None:
        if self.current(self.token, action=True) and self.manifest:
            self.auto_pending = None
            self.full = full
            if full and self.reviewer.state == "answer":
                self.reviewer._showQuestion()
            else:
                self.publish()

    def undo_mark(self) -> None:
        if self.current(self.token, action=True) and self.value["history"]:
            value = {
                **self.value,
                "known": self.value["history"][-1],
                "history": self.value["history"][:-1],
            }
            try:
                self.store.save(
                    self.card_id, self.schedule, self.source, self.manifest, value
                )
                self.value = value
                self.auto_pending = None
                self.publish()
            except STORAGE_ERRORS as exc:
                self.fail(str(exc))

    def reset(self) -> None:
        if self.current(self.token, action=True) and self.manifest:
            try:
                self.change([])
            except STORAGE_ERRORS as exc:
                self.fail(str(exc))

    def after_answer(self, answer: Any) -> None:
        # Only called after the native answer transaction succeeds, in both panes.
        if not self.manifest or answer.card_id != self.card_id:
            return
        try:
            card = self.mw.col.get_card(self.card_id)
            if card_identity(card) != self.source:
                return
            revlog = self.mw.col.db.scalar(
                "select max(id) from revlog where cid=?", self.card_id
            )
            if revlog and self.value.get("attempts") and not self.full:
                self.insights.record(
                    self.card_id,
                    self.source,
                    self.manifest,
                    revlog,
                    {
                        "session": self.value.get("session", self.schedule),
                        "attempts": self.value["attempts"],
                        "tested": self.value.get("tested", []),
                        "known": self.value["known"],
                        "at": int(time.time()),
                        "rating": int(answer.rating),
                        "burden": burden(self.value["attempts"], self.value["known"]),
                        **(self.submitted_plan or {}),
                    },
                )
            self.store.advance(
                self.card_id,
                schedule_identity(card, self.mw.col),
                self.source,
                self.manifest,
                self.value,
                continues_round(answer.new_state),
            )
            if self.submitted_plan and self.submitted_plan["completed"]:
                tooltip(
                    f"本轮已完成 · 表现分 {self.submitted_plan['quality']}/100 · {self.submitted_plan['next_days']} 天后复习",
                    parent=self.mw,
                )
        except STORAGE_ERRORS as exc:
            showWarning(
                "评分已成功；逐空标记保存失败，下次将完整测试。\n" + str(exc),
                parent=self.mw,
            )

    def toggle_auto(self, enabled: bool) -> None:
        self.mw.pm.profile[AUTO_SETTING] = enabled
        self.mw.pm.save()
        for controller in self.mw._weak_review_controllers:
            controller.auto_pending = None

    def dashboard(self) -> None:
        if not self.mw.col:
            return
        from .weak_review_dashboard import InsightDialog

        existing = getattr(self.mw, "_weak_insight_dialog", None)
        if existing and existing.isVisible():
            existing.raise_()
            return
        dialog = InsightDialog(self.mw, self.insights)
        self.mw._weak_insight_dialog = dialog
        dialog.show()

    def help(self) -> None:
        from aqt.utils import showInfo

        showInfo(
            "先点遮挡查看答案，再点答案旁的 ✓ 标记本轮已记住；再次点击可加入复习。\n\n"
            "支持标准文字挖空、Anki Studio 灰色遮挡、Enhanced Cloze 当前编号的填空，"
            "以及思维导图 V3 网页中的点击文字填空、SVG 矩形遮挡。普通图片、"
            "原生图片遮挡和其它自定义模板暂时保持原流程；普通图片需先用编辑器明确标注区域。\n\n"
            "逐空模式使用本轮独立评分：未全部记住时点击“再练未掌握”，保留已有标记；"
            "全部勾选后直接完成本轮，不再继续原来的分钟级学习步骤。下次整卡复习按天安排。"
            "关闭软件、跨天、切卡不清空未完成标记；撤销评分恢复对应轮次。\n\n"
            "整卡间隔结合各空测试次数、近期难度和上次完成间隔计算；首次完成为 1–3 天，"
            "后续随实际表现延长或缩短，同日反复练习不会拉长间隔。难点可提前在专项练习中巩固。"
            "完整测试、关闭逐空或不支持的卡片使用原评分。\n\n"
            "橙色圆环为重点，黄色圆环为留意；悬停显示次数。工具菜单可查看每日/牌组总结并单空练习。"
            "近期难度随新轮次升降；AI 仅在点击生成后读取当前列表中的上下文与原图。\n\n"
            "逐空明细保存在当前账户的 weak-review.sqlite3，不随 Anki 同步；整卡评分与日期通过原生事务保存并可撤销。"
            "内容、区域或图片版本改变后重新测试。筛选牌组暂不支持。",
            parent=self.mw,
        )


def button() -> str:
    return '<button id="weak-review" title="逐空标记与薄弱项复习" onclick="pycmd(\'weakReviewMenu\');">逐空</button>'
