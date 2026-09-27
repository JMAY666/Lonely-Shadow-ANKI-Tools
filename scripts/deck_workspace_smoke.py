"""Exercise the deck layout in real Qt/WebEngine with synthetic, isolated data."""

import json
import os
import sys
import time
import traceback
from pathlib import Path
from threading import Event
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if package := os.environ.get("ANKI_BUILTIN_PACKAGE_ROOT"):
    sys.path.insert(0, str(Path(package) / "app_packages"))
else:
    sys.path[:0] = [str(ROOT / p) for p in ("qt", "pylib", "out/qt", "out/pylib")]
name, mode = sys.argv[1:3]
assert Path(name).name == name and name not in (".", "..")
assert mode in ("write", "restart", "inspect")
BASE = ROOT / "runtime" / name
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "deck-workspace-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
if mode != "inspect":
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
results = {"checks": {}, "errors": []}


def check(label, value):
    results["checks"][label] = bool(value)
    print("CHECK", label, bool(value), flush=True)
    assert value, label


def wait(predicate, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError(str(predicate))


def js(code):
    response = []
    mw.web.page().runJavaScript(code, response.append)
    wait(lambda: bool(response))
    return response[0]


def settle():
    wait(lambda: not mw._background_op_count)
    deadline = time.monotonic() + 0.25
    wait(lambda: time.monotonic() > deadline)


def ready():
    settle()
    wait(
        lambda: (
            not mw.web.page().isLoading()
            and js(
                "document.querySelector('.deck-workspace')?.dataset.ready === 'true'"
            )
            and js("document.querySelector('.deck-workspace')?.dataset.renderRevision")
            == str(mw.deckBrowser._render_revision)
        )
    )
    settle()


def width():
    return js("document.querySelector('.deck-directory').getBoundingClientRect().width")


def key(code):
    js("document.querySelector('.deck-splitter').focus({preventScroll:true})")
    QTest.keyClick(mw.web.focusProxy(), code)
    settle()


def prepare():
    from anki.collection import Collection
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager

    assert not BASE.exists()
    BASE.mkdir(parents=True)
    (BASE / ".builtin-test").write_text("synthetic data only")
    set_lang("en_US")
    pm = ProfileManager(str(BASE))
    pm.setupMeta()
    pm.meta.update(defaultLang="zh_CN", firstRun=False, updates=False, theme=2)
    pm.create("DeckLayout")
    pm.load("DeckLayout")
    pm.profile.update(autoSync=False, syncKey=None, syncMedia=False)
    pm.save()
    pm.db.close()
    config = BASE / "DeckLayout/SynapsePro_Data/addon_settings.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "onboarding_completed": True,
                "minimal_dashboard_enabled": False,
                "gamification_popups_enabled": False,
                "fact_theme": "medical",
            }
        )
    )
    col = Collection(str(BASE / "DeckLayout/collection.anki2"))
    parent = col.decks.id("合成医学牌组（布局验收）")
    for index in range(40):
        did = col.decks.id(
            f"合成医学牌组（布局验收）::{index:02}生理学长标题测试::细胞的基本功能"
        )
        if index < 2:
            for card in range(6):
                note = col.new_note(col.models.by_name("Basic"))
                note["Front"] = f"合成问题 {index}-{card}"
                note["Back"] = "合成答案"
                col.add_note(note, did)
    col.decks.select(parent)
    col.close()


try:
    if mode == "write":
        prepare()
    assert (BASE / ".builtin-test").read_text() == "synthetic data only"
    from PyQt6.QtTest import QTest

    import aqt
    from aqt.qt import QPoint, Qt

    app = aqt._run(
        ["anki", "-b", str(BASE), "-p", "DeckLayout", "--safemode", "-l", "zh_CN"],
        exec=False,
    )
    mw = aqt.mw
    mw.resize(1400, 900)
    wait(lambda: mw.col and mw.state == "deckBrowser" and mw.learning_workspace.store)
    from aqt.builtin_features import synapsepro as sp

    wait(lambda: sp._daily_maintenance_done)
    ready()
    # Profile restoration can resize the window after _run() initially returns.
    mw.resize(1400, 900)
    settle()
    if mode == "inspect":
        print("INSPECTION READY", flush=True)
        app.exec()
        os._exit(0)
    col = mw.col
    parent = col.decks.id("合成医学牌组（布局验收）")
    child = col.decks.id("合成医学牌组（布局验收）::01生理学长标题测试::细胞的基本功能")
    card_state = col.db.all("select id, did, queue, due, reps from cards order by id")
    for minimal in (False, True):
        sp.addon_settings["minimal_dashboard_enabled"] = minimal
        mw.deckBrowser.refresh()
        ready()
        check(
            f"information below study panel minimal={minimal}",
            js(
                "document.querySelector('.deck-content').contains(document.querySelector('.deck-auxiliary')) && document.querySelector('.deck-auxiliary').getBoundingClientRect().top >= document.querySelector('.deck-main').getBoundingClientRect().bottom"
            ),
        )
        check(
            f"account content rendered minimal={minimal}",
            js(
                "!!document.querySelector('.sp-min-primary')"
                if minimal
                else "document.querySelectorAll('.gamewidget').length === 4 && !!document.querySelector('.fact-widget')"
            ),
        )
        if not minimal:
            check(
                "wide reward cards share a row",
                js(
                    "new Set(Array.from(document.querySelectorAll('.gamewidget')).map(e=>Math.round(e.getBoundingClientRect().top))).size === 1"
                ),
            )
        mw.grab().save(str(BASE / f"dashboard-{minimal}.png"))
        for window_width in (950, 760, 620, 480, 1400):
            mw.resize(window_width, 900)
            settle()
            check(
                f"no horizontal overflow {window_width} minimal={minimal}",
                js("document.documentElement.scrollWidth <= innerWidth + 2"),
            )
            check(
                f"panels and buttons contained {window_width} minimal={minimal}",
                js(
                    "Array.from(document.querySelectorAll('.deck-main, .deck-auxiliary, .gamewidget, .daily-widget, .deck-main button')).filter(e=>e.getBoundingClientRect().width).every(e=>{const r=e.getBoundingClientRect();return r.left >= 0 && r.right <= innerWidth + 2})"
                ),
            )
            check(
                f"splitter follows stacking {window_width} minimal={minimal}",
                js(
                    "(getComputedStyle(document.querySelector('.deck-splitter')).display === 'none') === (innerWidth <= 650)"
                ),
            )
            if window_width in (760, 480):
                mw.grab().save(str(BASE / f"width-{window_width}-{minimal}.png"))
        if minimal:
            js("document.querySelector('[data-sp-min-fact-trigger]').click()")
            wait(
                lambda: js(
                    "document.querySelector('.sp-min-fact-overlay').classList.contains('sp-min-open')"
                )
            )
            QTest.keyClick(mw.web.focusProxy(), Qt.Key.Key_Escape)
            wait(
                lambda: js(
                    "!document.querySelector('.sp-min-fact-overlay').classList.contains('sp-min-open')"
                )
            )
            check("daily fact opens and Escape closes", True)
    sp.addon_settings["minimal_dashboard_enabled"] = False
    mw.deckBrowser.refresh()
    ready()
    js("window.scrollTo(0,0)")
    rect = js(
        "(()=>{const r=document.querySelector('.deck-splitter').getBoundingClientRect();return [r.x+r.width/2,r.top+80]})()"
    )
    start = QPoint(round(rect[0]), round(rect[1]))
    target = mw.web.focusProxy()
    before = width()
    QTest.mousePress(target, Qt.MouseButton.LeftButton, pos=start)
    for delta in (30, 60, 90, 120):
        QTest.mouseMove(target, start + QPoint(delta, 0))
        settle()
        check(f"drag updates while held {delta}", abs(width() - before - delta) <= 2)
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, pos=start + QPoint(120, 0))
    settle()
    check(
        "release ends dragging",
        js("!document.body.classList.contains('deck-resizing')"),
    )
    check(
        "drag shows resize cursor",
        js(
            "getComputedStyle(document.querySelector('.deck-splitter')).cursor === 'col-resize'"
        ),
    )
    key(Qt.Key.Key_End)
    check("upper limit", width() == 480)
    key(Qt.Key.Key_Home)
    check("lower limit", width() == 190)
    key(Qt.Key.Key_Right)
    check("keyboard adjustment", width() == 200)
    key(Qt.Key.Key_End)
    mw.resize(760, 900)
    settle()
    check(
        "narrow window protects study width",
        js("document.querySelector('.deck-main').getBoundingClientRect().width >= 320"),
    )
    mw.resize(1400, 900)
    settle()
    check("widening restores requested width", width() == 480)
    mw.web.setZoomFactor(1.5)
    settle()
    check(
        "zoom remains contained",
        js("document.documentElement.scrollWidth <= innerWidth + 2"),
    )
    mw.web.setZoomFactor(1)
    settle()
    js(
        "window.__accountPanel = document.querySelector('.deck-global-widgets'); window.__directory = document.querySelector('.deck-directory')"
    )
    js(
        "(()=>{const input=document.querySelector('#deck-search');input.value='01生理学';input.dispatchEvent(new Event('input'))})()"
    )
    check("search finds nested deck", js(f"!document.getElementById('{child}').hidden"))
    js(f"document.getElementById('{child}').querySelector('a.deck').click()")
    wait(
        lambda: (
            js("document.querySelector('.deck-workspace').dataset.selectedDeck")
            == str(child)
        )
    )
    ready()
    check(
        "selection preserves width search and widget nodes",
        width() == 480
        and js(
            "document.querySelector('#deck-search').value === '01生理学' && window.__accountPanel === document.querySelector('.deck-global-widgets') && window.__directory === document.querySelector('.deck-directory')"
        ),
    )
    check(
        "selected title and scope agree",
        js(
            "document.querySelector('.deck-main h1').textContent === document.querySelector('.deck-scope-info h3').textContent"
        ),
    )
    # A busy database used to display an application-modal progress dialog.
    # Hold the collection worker while keeping the Qt event loop responsive.
    blocked, release = Event(), Event()

    def hold_database():
        blocked.set()
        release.wait(10)

    calls = []
    save_deck = col.decks.set_current

    def record_selection(did):
        calls.append(int(did))
        return save_deck(did)

    with (
        patch.object(mw.progress, "start", wraps=mw.progress.start) as progress,
        patch.object(col.decks, "set_current", side_effect=record_selection),
    ):
        mw.taskman.run_in_background(hold_database)
        wait(blocked.is_set)
        started = time.monotonic()
        js(f"document.getElementById('{parent}').querySelector('a.deck').click()")
        wait(lambda: time.monotonic() - started > 0.85)
        check(
            "slow selection never opens a modal progress dialog",
            progress.call_count == 0 and not mw.progress.busy(),
        )
        check(
            "slow selection shows inline feedback and disables old study button",
            js(
                "document.querySelector('.deck-start').disabled && document.querySelector('.deck-selection-status').textContent.includes('正在切换')"
            ),
        )
        mw.grab().save(str(BASE / "selection-wait.png"))
        mw.onStudyKey()
        mw.deckBrowser._linkHandler(f"open:{child}")
        check(
            "old study action and shortcut cannot enter the wrong deck",
            mw.state == "deckBrowser",
        )
        for index in range(20):
            target = child if index % 2 == 0 else parent
            mw.deckBrowser.set_current_deck(target)
            app.processEvents()
        released_at = time.monotonic()
        release.set()
        wait(lambda: not mw.deckBrowser.selection_pending)
        results["released_selection_ms"] = round(
            (time.monotonic() - released_at) * 1000
        )
        ready()
        check("twenty queued choices save only the final deck", calls == [int(parent)])
        check(
            "final selection matches database and reenables study",
            col.decks.selected() == parent
            and js(
                f"document.querySelector('.deck-workspace').dataset.selectedDeck === '{parent}' && !document.querySelector('.deck-start').disabled"
            ),
        )
        check(
            "slow selection preserves directory and account nodes",
            js(
                "window.__directory === document.querySelector('.deck-directory') && window.__accountPanel === document.querySelector('.deck-global-widgets')"
            ),
        )

    with patch.object(
        col.decks,
        "set_current",
        side_effect=RuntimeError("synthetic selection failure"),
    ):
        mw.deckBrowser.set_current_deck(child)
        wait(lambda: js("!document.querySelector('.deck-selection-retry').hidden"))
        check(
            "selection failure keeps unsafe actions disabled and offers retry",
            js(
                "document.querySelector('.deck-start').disabled && document.querySelector('.deck-selection-status').textContent.includes('synthetic selection failure')"
            ),
        )
    js("document.querySelector('.deck-selection-retry').click()")
    ready()
    check(
        "retry recovers correct deck without losing the page",
        col.decks.selected() == child
        and js(
            "!document.querySelector('.deck-start').disabled && document.querySelector('.deck-selection-retry').hidden && window.__directory === document.querySelector('.deck-directory')"
        ),
    )
    js(
        "(()=>{const input=document.querySelector('#deck-search');input.value='';input.dispatchEvent(new Event('input'))})()"
    )
    branch = col.decks.id("合成医学牌组（布局验收）::01生理学长标题测试")
    if js(f"document.getElementById('{parent}').dataset.collapsed === '1'"):
        js(f"document.getElementById('{parent}').querySelector('.collapse').click()")
        wait(
            lambda: js(f"document.getElementById('{parent}').dataset.collapsed === '0'")
        )
        ready()
    js(f"document.getElementById('{parent}').querySelector('.collapse').click()")
    wait(
        lambda: js(
            f"document.getElementById('{parent}').dataset.collapsed === '1' && document.getElementById('{branch}').hidden"
        )
    )
    ready()
    js(f"document.getElementById('{parent}').querySelector('.collapse').click()")
    wait(
        lambda: js(
            f"document.getElementById('{parent}').dataset.collapsed === '0' && !document.getElementById('{branch}').hidden"
        )
    )
    check("collapse and expand work after resize", True)
    ready()
    js("document.querySelector('.deck-start').click()")
    wait(lambda: mw.state == "review" and mw.reviewer.card)
    check("study opens native selected deck", mw.reviewer.card.did == child)
    mw.moveToState("deckBrowser")
    ready()
    check("return from study keeps directory width", width() == 480)
    check(
        "learning data unchanged",
        col.db.all("select id, did, queue, due, reps from cards order by id")
        == card_state,
    )
    check(
        "shared builtins remain loaded",
        bool(mw.desktop_tools and mw.learning_workspace and sp.gamification_manager),
    )
    js(
        "document.querySelector('.deck-splitter').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))"
    )
    check("double click restores default width", width() == 250)
    results["dark_layout"] = js(
        "({classes:document.body.className,scroll:document.documentElement.scrollWidth,width:innerWidth})"
    )
    print("DARK LAYOUT", results["dark_layout"], flush=True)
    check(
        "dark theme remains available and contained",
        js(
            "document.body.classList.contains('nightMode') && document.documentElement.scrollWidth <= innerWidth + 2"
        ),
    )
    mw.grab().save(str(BASE / "final.png"))
    mw.form.actionExit.trigger()
    wait(lambda: mw.col is None)
except BaseException:
    results["errors"].append(traceback.format_exc())
    print(results["errors"][-1], flush=True)
    if "mw" in globals() and mw:
        mw.grab().save(str(BASE / f"{mode}-failure.png"))
finally:
    results["passed"] = bool(results["checks"]) and not results["errors"]
    BASE.mkdir(parents=True, exist_ok=True)
    (BASE / f"{mode}-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("RESULT", results["passed"], len(results["checks"]), flush=True)
    os._exit(0 if results["passed"] else 1)
