# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Per-renderer recall controls with a separate, local persistence boundary."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from aqt.qt import QCursor, QMenu, QWebEngineScript
from aqt.utils import showWarning, tooltip

from .weak_review_store import RecallStore, continues_round, digest

IMAGE_HOST = "mumu-anki-pic.oss-cn-hangzhou.aliyuncs.com"
SETTING = "weakReviewEnabled"
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

    @property
    def enabled(self) -> bool:
        return bool(self.mw.pm.profile.get(SETTING, True))

    @property
    def store(self) -> RecallStore:
        return RecallStore(Path(self.mw.pm.profileFolder()) / "weak-review.sqlite3")

    def show(self) -> None:
        reviewer = self.reviewer
        card = reviewer.card
        if not card:
            return
        schedule = schedule_identity(card, self.mw.col)
        if (self.card_id, getattr(self, "schedule", None)) != (card.id, schedule):
            self.full = False
            self.asset_cache.clear()
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
        self.status = "此卡未识别到支持的空格，保持原复习方式"
        config = {
            "token": self.token,
            "side": reviewer.state,
            "enabled": self.enabled and not card.odid,
            "full": self.full,
            "question": card.question(),
        }
        if card.odid:
            self.status = "筛选牌组暂不启用逐空标记"
        reviewer.web.eval(
            f"_queueAction(() => window.ankiWeakReview?.start({json.dumps(config)}));"
        )
        self.update_button()

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
            if len(command) > 300_000:
                return
            data = json.loads(command)
            if not isinstance(data, dict) or not self.current(data.get("token", "")):
                return
            kind = data.get("kind")
            if kind == "manifest":
                self.accept_manifest(data)
            elif kind == "mark":
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
            adapter not in ("mumu-svg-v1", "mumu-text-v1", "native-cloze-v1")
            or not isinstance(slots, list)
            or not 1 <= len(slots) <= 512
            or not all(isinstance(slot, str) and len(slot) <= 20000 for slot in slots)
        ):
            return
        pending = digest(data)
        if pending == self.pending_manifest:
            return
        self.pending_manifest = pending
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
                self.publish(asset[1] if asset else None)
            except STORAGE_ERRORS as exc:
                self.fail(str(exc))

        if adapter in ("native-cloze-v1", "mumu-text-v1"):
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

    def change(self, known: list[str]) -> None:
        if known == self.value["known"]:
            return
        value = {
            "known": known,
            "history": (self.value["history"] + [self.value["known"]])[-30:],
        }
        self.store.save(self.card_id, self.schedule, self.source, self.manifest, value)
        self.value = value
        self.publish()
        if len(known) == len(self.slots):
            tooltip("本轮空格已全部记住，请按实际表现正常评分。", parent=self.mw)

    def publish(self, image: str | None = None) -> None:
        payload = {
            "token": self.token,
            "known": self.value["known"],
            "full": self.full,
            "image": image,
        }
        self.reviewer.web.eval(f"window.ankiWeakReview?.apply({json.dumps(payload)});")
        self.status = f"本轮已记住 {len(self.value['known'])}/{len(self.slots)}；查看答案不等于记住"
        self.update_button()

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
            self.full = full
            if full and self.reviewer.state == "answer":
                self.reviewer._showQuestion()
            else:
                self.publish()

    def undo_mark(self) -> None:
        if self.current(self.token, action=True) and self.value["history"]:
            value = {
                "known": self.value["history"][-1],
                "history": self.value["history"][:-1],
            }
            try:
                self.store.save(
                    self.card_id, self.schedule, self.source, self.manifest, value
                )
                self.value = value
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
            self.store.advance(
                self.card_id,
                schedule_identity(card, self.mw.col),
                self.source,
                self.manifest,
                self.value,
                continues_round(answer.new_state),
            )
        except STORAGE_ERRORS as exc:
            showWarning(
                "评分已成功；逐空标记保存失败，下次将完整测试。\n" + str(exc),
                parent=self.mw,
            )

    def help(self) -> None:
        from aqt.utils import showInfo

        showInfo(
            "先点遮挡查看答案，再点答案旁的 ✓ 标记本轮已记住；再次点击可加入复习。\n\n"
            "支持标准文字挖空，以及思维导图 V3 网页中的点击文字填空、SVG 矩形遮挡。普通图片、"
            "原生图片遮挡和其它自定义模板暂时保持原流程；普通图片需先用编辑器明确标注区域。\n\n"
            "重来／困难／良好／简单均仍使用原调度：评分后若处于学习或重学，保留本轮标记；"
            "毕业到正常间隔复习则结束本轮。普通复习的困难一般也会结束本轮；无重学步骤时重来也可能直接结束。"
            "关闭软件、跨天、切卡不清空；撤销评分恢复对应轮次。完整测试只临时忽略标记。\n\n"
            "标记只保存在当前账户的 weak-review.sqlite3，不随 Anki 同步，不改变原卡、模板或学习记录。"
            "内容、区域或图片版本改变后重新测试。筛选牌组暂不支持。",
            parent=self.mw,
        )


def button() -> str:
    return '<button id="weak-review" title="逐空标记与薄弱项复习" onclick="pycmd(\'weakReviewMenu\');">逐空</button>'
