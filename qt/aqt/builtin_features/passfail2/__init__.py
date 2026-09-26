# Copyright (c) 2022 Ashlynn Anderson; adaptations by Anki contributors
# Integration copyright: Ankitects Pty Ltd and contributors
# License: GNU GPL, version 3 or later; http://www.gnu.org/copyleft/gpl.html

"""Pass/Fail 2 0.3.0, integrated with native hooks and reversible mode selection."""

from __future__ import annotations

import html
import re
from typing import Any

from aqt import gui_hooks
from aqt.qt import (
    QAction,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QObject,
    QPushButton,
    QVBoxLayout,
    pyqtSignal,
)

from ..review_tools.i18n import tr as tool_tr

DEFAULTS = {
    "enabled": False,
    "toggle_names_textcolors": "0",
    "again_button_name": "Fail",
    "good_button_name": "Pass",
    "again_button_textcolor": "#000000",
    "good_button_textcolor": "#000000",
}
VERSION = "0.3.0"


def validate(value: dict) -> None:
    if type(value["enabled"]) is not bool or value["toggle_names_textcolors"] not in (
        "0",
        "1",
    ):
        raise ValueError("无效的模式或自定义开关")
    for prefix in ("again", "good"):
        name, color = (
            value[f"{prefix}_button_name"],
            value[f"{prefix}_button_textcolor"],
        )
        # Preserve the original code's strict < 15 limit (including empty names).
        if not isinstance(name, str) or len(name) >= 15:
            raise ValueError("按钮名称必须少于 15 个字符")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("文字颜色须为 # 加六位十六进制数")


def answer_buttons(buttons: tuple, reviewer: Any, value: dict) -> tuple:
    if not value["enabled"]:
        return buttons
    labels = ["失败", "通过"]
    if value["toggle_names_textcolors"] == "1":
        labels = [
            f'<span style="color:{html.escape(value[f"{prefix}_button_textcolor"], quote=True)}">{html.escape(tool_tr(value[f"{prefix}_button_name"]))}</span>'
            for prefix in ("again", "good")
        ]
    return ((1, labels[0]), (reviewer._defaultEase(), labels[1]))


def remap_answer(result: tuple, reviewer: Any, value: dict) -> tuple:
    proceed, ease = result
    if value["enabled"] and ease != 1:
        return (proceed, reviewer._defaultEase())
    return result


class PassFailController(QObject):
    changed = pyqtSignal()

    def __init__(self, mw: Any, storage: Any) -> None:
        super().__init__(mw)
        self.mw, self.storage = mw, storage
        self.value = storage.load_passfail()
        validate(self.value)
        gui_hooks.reviewer_will_init_answer_buttons.append(self.buttons)
        gui_hooks.reviewer_will_answer_card.append(self.answer)
        action = QAction("复习按钮 · 两档评分…", mw)
        action.triggered.connect(lambda: SettingsDialog(self).exec())
        mw.form.menuTools.addAction(action)

    def buttons(self, buttons: tuple, reviewer: Any, card: Any) -> tuple:
        return answer_buttons(buttons, reviewer, self.value)

    def answer(self, result: tuple, reviewer: Any, card: Any) -> tuple:
        return remap_answer(result, reviewer, self.value)

    def save(self, value: dict) -> None:
        from ..storage import write_object

        validate(value)
        write_object(self.storage.passfail_path, value)
        self.value = dict(value)
        self.changed.emit()
        owner = getattr(self.mw, "dual_review", None)
        if owner and owner.managed:
            return
        # Redraw only the controls: keep the card, face, timer and scheduler state.
        reviewer = self.mw.reviewer
        reviewer.shortcuts.invalidate()
        if self.mw.state == "review" and self.mw.bottomWeb.review_controls_active():
            self.mw.clearStateShortcuts()
            self.mw.setStateShortcuts(reviewer._shortcutKeys())
        if self.mw.state == "review" and reviewer.state == "answer":
            reviewer._showEaseButtons()


def install(mw: Any, storage: Any) -> None:
    if getattr(mw, "passfail2", None) is None:
        mw.passfail2 = PassFailController(mw, storage)


def mode_selector(mw: Any) -> QComboBox:
    control: PassFailController = mw.passfail2
    selector = QComboBox()
    selector.setAccessibleName("复习评分模式")
    selector.addItem("常规卡 · 原生四档评分", False)
    selector.addItem("常规卡 · 通过／失败两档评分", True)
    selector.setToolTip(
        "此设置用于完整测试、关闭逐空和未适配的卡片。逐空模式使用“再练未掌握／完成本轮”。"
        "常规两档模式：1=失败；2=通过；3、4 不评分；空格或 Enter 仅在正面显示答案。"
    )

    def sync() -> None:
        selector.blockSignals(True)
        selector.setCurrentIndex(int(control.value["enabled"]))
        selector.blockSignals(False)

    def save() -> None:
        from aqt.utils import showWarning

        try:
            control.save(control.value | {"enabled": bool(selector.currentData())})
        except (OSError, ValueError) as exc:
            sync()
            showWarning(str(exc), parent=mw)

    sync()
    selector.currentIndexChanged.connect(save)
    control.changed.connect(sync)

    def disconnect() -> None:
        try:
            control.changed.disconnect(sync)
        except (TypeError, RuntimeError):
            # The controller may already be destroyed when the main window closes.
            pass

    selector.destroyed.connect(disconnect)
    return selector


def answer_key_hint(reviewer: Any, ease: int, fallback: str) -> str:
    control = getattr(reviewer.mw, "passfail2", None)
    if control and control.value["enabled"]:
        return "1" if ease == 1 else "2" if ease == reviewer._defaultEase() else ""
    return answer_shortcut_keys(reviewer).get(ease) or ""


def answer_shortcut_keys(reviewer: Any) -> dict[int, str | None]:
    control = getattr(reviewer.mw, "passfail2", None)
    if control and control.value["enabled"]:
        return {1: "1", reviewer._defaultEase(): "2"}
    from aqt.review_shortcuts import answer_key_errors

    keys = {ease: reviewer.mw.pm.get_answer_key(ease) for ease in (1, 2, 3, 4)}
    errors = answer_key_errors(reviewer, keys)
    return {ease: key for ease, key in keys.items() if ease not in errors}


class SettingsDialog(QDialog):
    def __init__(self, control: PassFailController) -> None:
        super().__init__(control.mw)
        self.control = control
        self.setWindowTitle(f"复习按钮 · 两档评分 {VERSION}")
        self.resize(580, 500)
        layout = QVBoxLayout(self)
        label = QLabel(
            "两档模式保留原插件的 失败／通过评分映射。设置适用于本机所有账户；保存后生效并在重启后保留。"
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.enabled = QCheckBox("启用 通过／失败两档评分（关闭时使用原生四档）")
        self.enabled.setChecked(control.value["enabled"])
        layout.addWidget(self.enabled)
        self.custom = QCheckBox("启用自定义按钮名称和文字颜色")
        self.custom.setChecked(control.value["toggle_names_textcolors"] == "1")
        layout.addWidget(self.custom)
        form = QFormLayout()
        layout.addLayout(form)
        self.fields: dict[str, QLineEdit] = {}
        self.pickers: list[QPushButton] = []
        self.previews: list[QPushButton] = []
        for prefix, caption in (("again", "失败／重来"), ("good", "通过／良好")):
            name = QLineEdit(tool_tr(control.value[f"{prefix}_button_name"]))
            self.fields[f"{prefix}_button_name"] = name
            form.addRow(caption + " 名称", name)
            row = QHBoxLayout()
            color = QLineEdit(control.value[f"{prefix}_button_textcolor"])
            self.fields[f"{prefix}_button_textcolor"] = color
            row.addWidget(color)
            picker = QPushButton("选择颜色")
            picker.clicked.connect(lambda _, field=color: self.pick_color(field))
            self.pickers.append(picker)
            row.addWidget(picker)
            form.addRow(caption + " 文字颜色", row)
            preview = QPushButton()
            self.previews.append(preview)
        self.custom.toggled.connect(self.toggle_inputs)
        self.toggle_inputs()
        preview_row = QHBoxLayout()
        for preview in self.previews:
            preview_row.addWidget(preview)
        layout.addLayout(preview_row)
        refresh = QPushButton("刷新预览")
        refresh.clicked.connect(self.preview)
        layout.addWidget(refresh)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        layout.addWidget(
            QLabel(
                "原作者：Ashlynn Anderson；Dmitry Mikheev、Rohan Modi。GPL-3.0-or-later。"
            )
        )
        self.preview()

    def toggle_inputs(self) -> None:
        for widget in [*self.fields.values(), *self.pickers]:
            widget.setEnabled(self.custom.isChecked())

    def pick_color(self, field: QLineEdit) -> None:
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            field.setText(color.name())

    def draft(self) -> dict:
        return self.control.value | {
            "enabled": self.enabled.isChecked(),
            "toggle_names_textcolors": "1" if self.custom.isChecked() else "0",
            **{key: field.text() for key, field in self.fields.items()},
        }

    def preview(self) -> None:
        try:
            value = self.draft()
            validate(value)
            for prefix, button in zip(("again", "good"), self.previews):
                button.setText(value[f"{prefix}_button_name"])
                button.setStyleSheet("color: " + value[f"{prefix}_button_textcolor"])
            self.error.clear()
        except ValueError as exc:
            self.error.setText(str(exc))

    def save(self) -> None:
        try:
            self.control.save(self.draft())
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
