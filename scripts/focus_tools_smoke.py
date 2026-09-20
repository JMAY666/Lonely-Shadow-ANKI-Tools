"""Exercise the actual music player and cycle labels in a synthetic Anki profile."""

import faulthandler
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if package := os.environ.get("ANKI_BUILTIN_PACKAGE_ROOT"):
    sys.path.insert(0, str(Path(package) / "app_packages"))
else:
    sys.path[:0] = [str(ROOT / p) for p in ("qt", "pylib", "out/qt", "out/pylib")]
name = sys.argv[1]
assert Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
assert not BASE.exists(), "Use a new synthetic profile name"
BASE.mkdir(parents=True)
(BASE / ".builtin-test").write_text("synthetic data only")
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "focus-tools-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
results = {"checks": {}, "audio": [], "errors": []}
faulthandler.dump_traceback_later(45)


def check(label, value):
    results["checks"][label] = bool(value)
    print("CHECK", label, bool(value), flush=True)
    assert value, label


def wait(predicate, timeout=25):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError(str(predicate))


def js(code):
    response = []
    player.ui_view.page().runJavaScript(code, response.append)
    wait(lambda: bool(response))
    return response[0]


try:
    from anki.collection import Collection
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager

    set_lang("en_US")
    pm = ProfileManager(str(BASE))
    pm.setupMeta()
    pm.meta.update(
        defaultLang="zh_CN",
        firstRun=False,
        check_for_updates=False,
        check_for_addon_updates=False,
    )
    pm.meta["theme"] = 2 if os.environ.get("ANKI_FOCUS_DARK") == "1" else 1
    pm.create("Focus")
    pm.load("Focus")
    pm.profile.update(autoSync=False, syncKey=None, syncMedia=False)
    pm.save()
    pm.db.close()
    settings = BASE / "Focus/SynapsePro_Data/addon_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "onboarding_completed": True,
                "gamification_popups_enabled": False,
                "language": "zh",
            }
        )
    )
    col = Collection(str(BASE / "Focus/collection.anki2"))
    col.close()

    import aqt
    from aqt.qt import QFont, QFontDatabase, QTimer

    app = aqt._run(["anki", "-b", str(BASE), "-p", "Focus", "-l", "zh_CN"], exec=False)
    # Qt's offscreen platform on Windows has no system font discovery.
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and sys.platform == "win32":
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
        app.setFont(QFont("Microsoft YaHei", 9))
    mw = aqt.mw
    mw.resize(1200, 850)
    from aqt.builtin_features import synapsepro as sp
    from aqt.builtin_features.synapsepro import background_music as music
    from aqt.builtin_features.synapsepro import constants, pomodoro

    wait(lambda: mw.col and sp.sidebar_widget_instance and sp._daily_maintenance_done)
    sidebar = sp.sidebar_widget_instance
    pomodoro.sound_work_end = pomodoro.sound_break_end = ""
    pomodoro.showInfo = lambda *args, **kwargs: None
    pomodoro.pomodoros_target = 4
    pomodoro.reset_action()
    check("initial cycle visible", sidebar._timer_cycle_label.text() == "专注\n1/4")
    pomodoro.start_pause_action()
    pomodoro.start_pause_action()
    check(
        "pause retains phase and round",
        sidebar._timer_cycle_label.text() == "专注\n1/4"
        and "已暂停" in sidebar._timer_cycle_label.toolTip(),
    )
    pomodoro.skip_action()
    check(
        "skip advances to matching short break",
        sidebar._timer_cycle_label.text() == "短休息\n1/4",
    )
    pomodoro.skip_action()
    check("next work round visible", sidebar._timer_cycle_label.text() == "专注\n2/4")
    pomodoro.pomodoros_completed_cycle = 3
    pomodoro.handle_state_transition(skipped_state=constants.STATE_WORK)
    check(
        "long break keeps last round",
        sidebar._timer_cycle_label.text() == "长休息\n4/4",
    )
    sidebar.grab().save(str(BASE / "sidebar-long-break.png"))
    pomodoro.skip_action()
    check(
        "cycle restarts after long break",
        sidebar._timer_cycle_label.text() == "专注\n1/4",
    )
    pomodoro.pomodoros_target = 10
    pomodoro.pomodoros_completed_cycle = 9
    pomodoro.intended_next_state = constants.STATE_WORK
    sidebar.update_timer_ui()
    check(
        "custom cycle fits sidebar",
        sidebar._timer_cycle_label.text() == "专注\n10/10"
        and sidebar._timer_cycle_label.fontMetrics().horizontalAdvance("10/10")
        <= sidebar._timer_cycle_label.width(),
    )
    pomodoro.reset_action()
    check("reset refreshes cycle", sidebar._timer_cycle_label.text() == "专注\n1/10")
    pomodoro.pomodoros_target = 4
    pomodoro.reset_action()

    player = music.MiniMusicPlayer(mw)
    player.show()
    # Keep playback silent and inspect decoded buffers as well as the playhead.
    from PyQt6.QtMultimedia import QAudioBufferOutput

    player.audio_output.setMuted(True)
    audio_buffers = QAudioBufferOutput(player)
    player.player.setAudioBufferOutput(audio_buffers)
    decoded = []
    audio_buffers.audioBufferReceived.connect(
        lambda buffer: decoded.append(buffer.frameCount())
    )
    wait(
        lambda: (
            player._ui_ready
            and js("document.querySelectorAll('#grid .tile').length") == 18
        )
    )
    check(
        "18 tracks displayed",
        "18" in js("document.getElementById('lbl-sounds').textContent"),
    )
    covers_ready = "Array.from(document.querySelectorAll('#grid img')).every(i => i.complete && i.naturalWidth > 0)"
    wait(lambda: js(covers_ready))
    check("all covers render", js(covers_ready))
    for track in player._builtin_tracks()[6:]:
        decoded.clear()
        player.select_track(track["id"])
        wait(
            lambda: (
                player._loaded_track == track["id"] and player.player.duration() > 1000
            )
        )
        if not player._want_playing:
            player.play_with_fade()
        wait(lambda: player.player.position() >= 100 and any(decoded))
        results["audio"].append(
            {
                "id": track["id"],
                "duration_ms": player.player.duration(),
                "position_ms": player.player.position(),
                "error": player.player.errorString(),
            }
        )
        check("decodes and plays " + track["id"], not player.player.errorString())
    player.pause_with_fade()
    wait(lambda: not player._want_playing)
    js("document.querySelector('.scroll').scrollTop = 165")
    wait(lambda: js("document.querySelector('.scroll').scrollTop > 0"))
    check(
        "expanded catalog scrolls",
        js(
            "document.querySelector('.scroll').scrollHeight > document.querySelector('.scroll').clientHeight"
        ),
    )
    player.grab().save(str(BASE / "music-expanded.png"))
    # Drive the real JS bridge and dismiss only the synthetic attribution dialog.
    dialogs = []

    def close_credits():
        for widget in app.topLevelWidgets():
            if widget.windowTitle() == "音源与授权":
                dialogs.append(widget.windowTitle())
                widget.accept()

    QTimer.singleShot(500, close_credits)
    js("document.getElementById('btn-credits').click()")
    wait(lambda: bool(dialogs))
    check("source credits accessible", bool(dialogs))
    player.player.stop()
    player.close()
    player.deleteLater()
    mw.form.actionExit.trigger()
    wait(lambda: mw.col is None)
except BaseException:
    results["errors"].append(traceback.format_exc())
    print(results["errors"][-1], flush=True)
finally:
    results["passed"] = bool(results["checks"]) and not results["errors"]
    (BASE / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("RESULT", results["passed"], len(results["checks"]), flush=True)
    os._exit(0 if results["passed"] else 1)
