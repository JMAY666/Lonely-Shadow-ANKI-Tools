"""Actual reviewer/WebEngine acceptance with synthetic data and no external requests."""

import base64
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

from weak_review_fixtures import enhanced_html, studio_html, table_html

ROOT = Path(__file__).resolve().parents[1]
if package := os.environ.get("ANKI_BUILTIN_PACKAGE_ROOT"):
    sys.path.insert(0, str(Path(package) / "app_packages"))
else:
    sys.path[:0] = [str(ROOT / part) for part in ("qt", "pylib", "out/qt", "out/pylib")]
name = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "write"
assert name and Path(name).name == name and name not in (".", "..")
BASE = ROOT / "runtime" / name
if mode == "write":
    assert not BASE.exists(), "Use a fresh synthetic run name"
    BASE.mkdir(parents=True)
    (BASE / ".builtin-test").write_text("synthetic data only")
else:
    assert (BASE / ".builtin-test").read_text() == "synthetic data only"
os.environ.pop("ANKIDEV", None)
os.environ["ANKI_SINGLE_INSTANCE_KEY"] = "weak-review-" + name
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
os.environ["QT_QPA_FONTDIR"] = str(
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
)
results = {"checks": {}, "errors": [], "mode": mode}


def check(label, result):
    print("CHECK", label, bool(result), flush=True)
    results["checks"][label] = bool(result)
    assert result, label


def wait(predicate, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        if results["errors"]:
            raise AssertionError(results["errors"][-1])
        time.sleep(0.015)
    raise TimeoutError(str(predicate))


def js(web, source, *, in_frame=False):
    received = []
    target = web.page().mainFrame().children()[0] if in_frame else web.page()
    target.runJavaScript(source, received.append)
    wait(lambda: bool(received))
    return received[0]


def ready(reviewer):
    return (
        not mw._background_op_count
        and reviewer.card
        and reviewer.weak_review.manifest
        and reviewer.state in ("question", "answer")
        and reviewer._states_mutated
        and reviewer.controls_active()
        and reviewer.weak_review.current(reviewer.weak_review.token)
        and js(reviewer.web, "!!window.ankiWeakReview")
    )


def mark(reviewer, index):
    before = len(reviewer.weak_review.value["known"])
    js(reviewer.web, f"document.querySelector('[data-wr-key=s{index}]').click()")
    wait(lambda: len(reviewer.weak_review.value["known"]) != before)


def mouse_point(reviewer, selector, *, in_frame=False, owner=False):
    point = js(
        reviewer.web,
        """(([selector, owner]) => {
            let target = document.querySelector(selector);
            if (owner) target = target.previousElementSibling;
            target.scrollIntoView({block: 'center'});
            const rect = target.getBoundingClientRect();
            return [rect.x + rect.width / 2, rect.y + rect.height / 2];
        })("""
        + json.dumps([selector, owner])
        + ")",
        in_frame=in_frame,
    )
    if in_frame:
        outer = js(
            reviewer.web,
            "{const frame=document.querySelector('#receiver');"
            "frame.scrollIntoView({block:'start'});const rect=frame.getBoundingClientRect();"
            "[rect.x + frame.clientLeft, rect.y + frame.clientTop]}",
        )
        point = [point[i] + outer[i] for i in range(2)]
    zoom = reviewer.web.zoomFactor()
    return QPoint(round(point[0] * zoom), round(point[1] * zoom))


def mouse_move(reviewer, selector, *, in_frame=False, owner=False):
    mw.activateWindow()
    reviewer.web.setFocus()
    target = reviewer.web.focusProxy() or reviewer.web
    target.setMouseTracking(True)
    point = mouse_point(reviewer, selector, in_frame=in_frame, owner=owner)
    # Offscreen Qt has no window-system cursor motion. Deliver the same mouse
    # move through the actual WebEngine widget instead of a synthetic DOM event.
    QApplication.sendEvent(
        target,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(point),
            QPointF(target.mapToGlobal(point)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def mouse_click(reviewer, selector, *, in_frame=False):
    mw.activateWindow()
    reviewer.web.setFocus()
    wait(lambda: reviewer.shortcuts.available())
    if js(
        reviewer.web,
        f"document.querySelector({json.dumps(selector)}).matches('.anki-wr-mark')",
        in_frame=in_frame,
    ):
        mouse_move(reviewer, selector, in_frame=in_frame, owner=True)
        wait(
            lambda: js(
                reviewer.web,
                f"document.querySelector({json.dumps(selector)}).getClientRects().length > 0",
                in_frame=in_frame,
            )
        )
        mouse_move(reviewer, selector, in_frame=in_frame)
    QTest.mouseClick(
        reviewer.web.focusProxy() or reviewer.web,
        Qt.MouseButton.LeftButton,
        pos=mouse_point(reviewer, selector, in_frame=in_frame),
    )


def press_space(reviewer):
    results["last_space"] = {
        "available": reviewer.shortcuts.available(),
        "focus": type(app.focusWidget()).__name__,
        "dom": js(
            reviewer.web,
            "({allowed: ankiReviewShortcutAllowed(), focused: document.hasFocus(), "
            "active: document.activeElement.tagName})",
        ),
    }
    QTest.keyClick(app.focusWidget(), Qt.Key.Key_Space)


def cross_origin_frame(reviewer):
    previous_request = reviewer.weak_review.request
    js(
        reviewer.web,
        "{const frame=document.querySelector('#receiver'),url=new URL(frame.src);"
        "url.hostname='localhost';frame.src=url.href}",
    )
    wait(lambda: reviewer.weak_review.request != previous_request)
    assert js(
        reviewer.web, "document.querySelector('#receiver').contentDocument === null"
    )


def hidden(reviewer):
    return js(
        reviewer.web,
        "[...document.querySelectorAll('#qa .cloze')].filter(e=>e.innerText==='[...]').length",
    )


def show_question(reviewer):
    reviewer._showQuestion()
    wait(lambda: ready(reviewer))


def show_answer(reviewer):
    reviewer._showAnswer()
    wait(lambda: ready(reviewer) and reviewer.state == "answer")
    wait(
        lambda: js(
            reviewer.web,
            "[...document.querySelectorAll('.anki-wr-mark')].every(b=>!b.disabled)",
        )
    )


def snapshot():
    return mw.col.db.all("select * from cards order by id"), mw.col.db.all(
        "select * from revlog order by id"
    )


def image_bytes(revision=0):
    if revision == 2:
        return b"invalid synthetic image"
    rows = "".join(
        f'<text x="{25 + (i % 2) * 240}" y="{45 + (i // 2) * 70}" font-size="18">答案 {i + 1}</text>'
        for i in range(10)
    )
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="400"><rect width="480" height="400" fill="white"/>{rows}<text x="5" y="395">版本 {revision}</text></svg>'.encode()


def data_url(data):
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode()


def frame_html():
    # The inspected green diagram includes an invisible 0 x 0 region between
    # real masks. It must neither disable the card nor consume a recall slot.
    empty = '<uni-view id="empty-region" class="svg_mask" style="left:18px;top:160px;width:0px;height:0px"></uni-view>'
    masks = "".join(
        (empty if i == 4 else "")
        + f'<uni-view id="region-{i}" class="svg_mask" style="left:{20 + (i % 2) * 240}px;top:{22 + (i // 2) * 70}px;width:180px;height:30px"></uni-view>'
        for i in range(10)
    )
    return f'''<html><style>body{{margin:8px}}.svg_answer_parent{{position:relative;width:480px;height:400px}}.svg_mask,.svg_mask_show{{position:absolute;box-sizing:border-box}}.svg_mask{{background:#c6b882}}.svg_background-image{{display:block}}.svg_background-image img{{width:100%;height:100%}}</style>
<body><div cardid="synthetic" card="table"><div class="svg_answer_parent"><uni-image class="svg_background-image" style="width:480px;height:400px"><div></div><img src="{data_url(image_bytes())}"></uni-image>{masks}</div><div class="showanswer">点击逐空查看答案</div></div>
<script>document.querySelectorAll('.svg_mask').forEach(el=>{{if(location.search.includes('answer'))el.className='svg_mask_show';el.onclick=()=>el.classList.toggle('svg_mask_show')}});</script></body></html>'''


def text_frame_html():
    # Synthetic form of the inspected component contract, never personal material.
    parts = ["<p>合成标题：<strong style='color:red'>重复答案</strong></p>"]
    for index in range(9):
        parts[-1] += f"<p>条目 {index + 1}："
        parts.extend(
            [["相同答案" if index % 2 == 0 else "另一答案", "(填空)", 0], "</p>"]
        )
    return """<html><style>body{font:18px sans-serif}p{margin:4px 0}uni-rich-text{display:block}</style>
<body><div cardid="synthetic-text" card="text"><div class="flex-q-clz">合成文字卡</div><div class="text-left"><div><uni-rich-text class="mumu-font-14" data-v-synthetic></uni-rich-text></div><div class="showanswer">点击逐空查看答案</div></div></div>
<script>
window.testParts=PARTS;
const rich=document.querySelector('uni-rich-text');
const answerSide=location.search.includes('answer');
window.testComponent={type:{name:'mu-aarea'},props:{flip:answerSide?1:0,card:{answer:{type:1,A:testParts}}},parent:null};
rich.__vueParentComponent={type:{name:'uni-rich-text'},parent:testComponent};
window.renderNative=()=>{rich.innerHTML='<div>'+testParts.map((p,i)=>typeof p==='string'?p:answerSide?'<span style="color:#EB9D27">'+p[0]+'</span>':'<a href="blankIndex:'+i+'">'+(p[2]?p[0]:p[1])+'</a>').join('')+'</div>'};
rich.addEventListener('click',e=>{const a=e.target.closest('a');if(a){e.preventDefault();const i=Number(a.getAttribute('href').split(':')[1]);testParts[i][2]=1-testParts[i][2];renderNative()}});
document.querySelector('.showanswer').onclick=()=>{const p=testParts.find(p=>Array.isArray(p)&&!p[2]);if(p)p[2]=1;renderNative()};
renderNative();
</script></body></html>""".replace("PARTS", json.dumps(parts, ensure_ascii=False))


try:
    from anki.collection import Collection
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager

    set_lang("en_US")
    profile = BASE / "Recall-Test"
    if mode == "write":
        pm = ProfileManager(str(BASE))
        pm.setupMeta()
        pm.meta.update(defaultLang="zh_CN", firstRun=False, updates=False)
        pm.create("Recall-Test")
        pm.load("Recall-Test")
        pm.profile.update(autoSync=False, syncKey=None, syncMedia=False)
        pm.save()
        pm.db.close()
        settings = profile / "SynapsePro_Data/addon_settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {"onboarding_completed": True, "gamification_popups_enabled": False}
            )
        )
        col = Collection(str(profile / "collection.anki2"))
        deck = col.decks.id("逐空合成测试")
        image_deck = col.decks.id("图片区域合成测试")
        text_deck = col.decks.id("网页文字填空合成测试")
        table_deck = col.decks.id("网页表格填空合成测试")
        studio_deck = col.decks.id("灰色遮挡合成测试")
        enhanced_deck = col.decks.id("增强挖空合成测试")
        note = col.new_note(col.models.by_name("Cloze"))
        note["Text"] = (
            "<table style='margin:auto'><tr><th>来源</th><th>答案</th></tr>"
            + "".join(
                f"<tr><td>来源 {i}</td><td>{{{{c1::答案 {i}}}}}</td></tr>"
                for i in range(10)
            )
            + "</table>"
        )
        col.add_note(note, deck)
        native_id = note.cards()[0].id
        web_model = col.models.by_name("Basic")
        # The real custom template has one iframe per face, without FrontSide.
        web_model["tmpls"][0]["afmt"] = "{{Back}}"
        col.models.update_dict(web_model)
        image_note = col.new_note(web_model)
        image_note["Front"] = (
            '<iframe id="receiver" src="/_anki/weak-review-synthetic?question" style="width:100%;height:480px;border:0"></iframe>'
        )
        image_note["Back"] = (
            '<iframe id="receiver" src="/_anki/weak-review-synthetic?answer" style="width:100%;height:480px;border:0"></iframe>'
        )
        col.add_note(image_note, image_deck)
        text_note = col.new_note(col.models.by_name("Basic"))
        text_note["Front"] = (
            '<iframe id="receiver" src="/_anki/weak-review-text-synthetic?question" style="width:100%;height:480px;border:0"></iframe>'
        )
        text_note["Back"] = (
            '<iframe id="receiver" src="/_anki/weak-review-text-synthetic?answer" style="width:100%;height:480px;border:0"></iframe>'
        )
        col.add_note(text_note, text_deck)
        table_note = col.new_note(web_model)
        for field, face in (("Front", "question"), ("Back", "answer")):
            table_note[field] = (
                f'<iframe id="receiver" src="/_anki/weak-review-table-synthetic?{face}" style="width:100%;height:480px;border:0"></iframe>'
            )
        col.add_note(table_note, table_deck)
        for target_deck, render in (
            (studio_deck, studio_html),
            (enhanced_deck, enhanced_html),
        ):
            local_note = col.new_note(web_model)
            local_note["Front"], local_note["Back"] = render(), render(True)
            col.add_note(local_note, target_deck)
        (Path(col.media.dir()) / "_recall_test.html").write_text(
            frame_html(), encoding="utf8"
        )
        col.decks.select(deck)
        col.close()
        expected = {
            "deck": deck,
            "image_deck": image_deck,
            "native_id": native_id,
            "text_deck": text_deck,
            "table_deck": table_deck,
            "studio_deck": studio_deck,
            "enhanced_deck": enhanced_deck,
        }
        (BASE / "expected.json").write_text(json.dumps(expected))
    else:
        expected = json.loads((BASE / "expected.json").read_text())

    from PyQt6.QtTest import QTest

    import aqt
    import aqt.builtin_features.weak_review as feature
    from aqt import mediasrv
    from aqt.progress import ProgressDialog
    from aqt.qt import (
        QApplication,
        QEvent,
        QLabel,
        QMouseEvent,
        QPoint,
        QPointF,
        Qt,
        QTimer,
    )

    revision = 0

    # Substitute only the accepted remote origin in this isolated process. The
    # second loopback hostname exercises real cross-origin focus without fetching
    # a vendor page or weakening the production origin check.
    original_init = feature.WeakReview.__init__

    def init_with_synthetic_origin(self, reviewer):
        original_init(self, reviewer)
        scripts = reviewer.web.page().scripts()
        (script,) = scripts.find("anki-weak-review")
        source = script.sourceCode()
        original = 'origin === "https://kyxz288.com"'
        assert original in source
        scripts.remove(script)
        script.setSourceCode(
            source.replace(original, 'origin === "http://localhost:" + location.port')
        )
        scripts.insert(script)

    feature.WeakReview.__init__ = init_with_synthetic_origin

    def synthetic_image_snapshot(url):
        assert url.startswith("data:image/svg+xml;base64,"), (
            "No real image fetch is allowed in tests"
        )
        data = image_bytes(revision)
        return hashlib.sha256(data).hexdigest(), data_url(data)

    feature.image_snapshot = synthetic_image_snapshot
    mediasrv.app.add_url_rule(
        "/_anki/weak-review-synthetic", "weak_review_synthetic", frame_html
    )
    mediasrv.app.add_url_rule(
        "/_anki/weak-review-text-synthetic",
        "weak_review_text_synthetic",
        text_frame_html,
    )
    mediasrv.app.add_url_rule(
        "/_anki/weak-review-table-synthetic", "weak_review_table_synthetic", table_html
    )
    app = aqt._run(
        ["anki", "-b", str(BASE), "-p", "Recall-Test", "--safemode", "-l", "zh_CN"],
        exec=False,
    )
    mw = aqt.mw

    def record_exception(kind, value, tb):
        results["errors"].append("".join(traceback.format_exception(kind, value, tb)))

    sys.excepthook = record_exception

    def dialog_guard():
        modal = QApplication.activeModalWidget()
        if modal and not isinstance(modal, ProgressDialog):
            results["errors"].append(
                " | ".join(label.text() for label in modal.findChildren(QLabel))
            )
            modal.reject()

    guard = QTimer()
    guard.timeout.connect(dialog_guard)
    guard.start(200)
    wait(lambda: mw.col and mw.state == "deckBrowser" and mw.learning_workspace.store)
    wait(lambda: sys.modules["aqt.builtin_features.synapsepro"]._daily_maintenance_done)
    mw.resize(1200, 850)
    mw.activateWindow()
    mw.col.decks.select(expected["deck"])
    mw.moveToState("review")
    reviewer = mw.reviewer
    wait(lambda: ready(reviewer))
    check(
        "ten independent native clozes detected", len(reviewer.weak_review.slots) == 10
    )

    if mode == "write":
        before = snapshot()
        check(
            "unrevealed marks occupy no space and cannot receive focus",
            js(
                reviewer.web,
                "[...document.querySelectorAll('.anki-wr-mark')].every(b=>b.disabled && !b.getClientRects().length)",
            ),
        )
        js(reviewer.web, "document.querySelector('#qa .cloze').click()")
        wait(lambda: hidden(reviewer) == 9)
        check(
            "revealing an answer never marks it",
            reviewer.weak_review.value["known"] == [],
        )
        mw.activateWindow()
        reviewer.web.setFocus()
        table_bounds = js(
            reviewer.web,
            "JSON.stringify(document.querySelector('#qa table').getBoundingClientRect())",
        )
        js(reviewer.web, "document.querySelector('#qa .cloze').focus()")
        check(
            "keyboard focus exposes one control without moving the table",
            js(
                reviewer.web,
                "document.querySelectorAll('.anki-wr-mark:popover-open').length",
            )
            == 1
            and js(
                reviewer.web,
                "JSON.stringify(document.querySelector('#qa table').getBoundingClientRect())",
            )
            == table_bounds,
        )
        QTest.keyClick(reviewer.web.focusProxy() or reviewer.web, Qt.Key.Key_Tab)
        wait(
            lambda: js(reviewer.web, "document.activeElement.matches('.anki-wr-mark')")
        )
        press_space(reviewer)
        check(
            "keyboard-focused marking control remains protected from review shortcuts",
            js(reviewer.web, "ankiReviewShortcutAllowed()") is False
            and reviewer.state == "question"
            and snapshot() == before,
        )
        mouse_click(reviewer, "[data-wr-key=s0]")
        wait(lambda: reviewer.weak_review.value["known"] == ["s0"])
        press_space(reviewer)
        wait(
            lambda: (
                reviewer.state == "answer"
                and ready(reviewer)
                and reviewer.weak_review.value["known"] == ["s0"]
                and hidden(reviewer) == 0
            )
        )
        check(
            "Space after a mouse mark reveals the native answer without rating",
            reviewer.weak_review.value["known"] == ["s0"] and snapshot() == before,
        )
        show_question(reviewer)
        wait(lambda: hidden(reviewer) == 9)
        check(
            "one marked slot stays visible with the table intact",
            js(reviewer.web, "document.querySelectorAll('#qa table tr').length") == 11,
        )
        show_answer(reviewer)
        for index in (1, 2, 3):
            mark(reviewer, index)
        show_question(reviewer)
        wait(lambda: hidden(reviewer) == 6)
        reviewer.weak_review.toggle_full(True)
        wait(lambda: hidden(reviewer) == 10)
        check(
            "full test preserves saved marks",
            len(reviewer.weak_review.value["known"]) == 4,
        )
        reviewer.weak_review.toggle_full(False)
        wait(lambda: hidden(reviewer) == 6)
        reviewer.weak_review.reset()
        wait(lambda: hidden(reviewer) == 10)
        reviewer.weak_review.undo_mark()
        wait(lambda: hidden(reviewer) == 6)
        check("marks and resets never change cards or revlog", snapshot() == before)
        mw.resize(620, 720)
        wait(lambda: hidden(reviewer) == 6)
        check(
            "resizing retains slot identity",
            reviewer.weak_review.value["known"] == ["s0", "s1", "s2", "s3"],
        )
        mw.resize(1200, 850)
        reviewer.weak_review.toggle(False)
        wait(
            lambda: (
                js(reviewer.web, "document.querySelectorAll('.anki-wr-mark').length")
                == 0
            )
        )
        check("disabled feature restores ordinary clozes", hidden(reviewer) == 10)
        reviewer.weak_review.toggle(True)
        wait(lambda: ready(reviewer) and hidden(reviewer) == 6)
        show_answer(reviewer)
        reviewer.weak_review.toggle_full(True)
        wait(
            lambda: (
                ready(reviewer)
                and reviewer.state == "question"
                and hidden(reviewer) == 10
            )
        )
        check(
            "full test from the answer immediately retests every target",
            len(reviewer.weak_review.value["known"]) == 4,
        )
        reviewer.weak_review.toggle_full(False)
        wait(lambda: hidden(reviewer) == 6)
        show_answer(reviewer)
        reviewer._answerCard(1)
        wait(
            lambda: (
                ready(reviewer)
                and reviewer.state == "question"
                and hidden(reviewer) == 6
            )
        )
        check(
            "again submits one native review and carries marks",
            mw.col.db.scalar("select count(*) from revlog") == 1,
        )
        mw.undo()
        wait(lambda: not mw._background_op_count)
        reviewer.refresh_if_needed()
        wait(
            lambda: (
                ready(reviewer) and mw.col.db.scalar("select count(*) from revlog") == 0
            )
        )
        check(
            "native undo restores marked round",
            len(reviewer.weak_review.value["known"]) == 4,
        )
        if reviewer.state == "question":
            show_answer(reviewer)
        reviewer._answerCard(1)
        wait(
            lambda: (
                ready(reviewer)
                and reviewer.state == "question"
                and hidden(reviewer) == 6
            )
        )
        mw.grab().save(str(BASE / "native.png"))

        owner = mw.dual_review
        owner.toggle()
        left, right = owner.panels
        wait(lambda: not left.pending and not right.pending)
        right.deck.setCurrentIndex(right.deck.findData(expected["image_deck"]))
        owner.activate(left, focus=True)
        wait(lambda: not right.pending and ready(right.reviewer))
        image_reviewer = right.reviewer
        check(
            "custom image regions detected in other pane",
            len(image_reviewer.weak_review.slots) == 10,
        )
        check("background manifest does not steal active pane", owner.active is left)
        owner.activate(right, focus=True)

        def frame_js(source):
            return js(image_reviewer.web, source, in_frame=True)

        wait(
            lambda: (
                frame_js("document.querySelectorAll('[data-wr-hidden=true]').length")
                == 10
            )
        )
        frame_js("document.querySelector('.svg_mask').click()")
        wait(
            lambda: (
                frame_js("document.querySelectorAll('[data-wr-hidden=true]').length")
                == 9
            )
        )
        check(
            "local image reveal does not mark",
            image_reviewer.weak_review.value["known"] == [],
        )
        frame_js(
            "{const c=document.querySelector('.svg_answer_parent');window.originalDiagramStyle=c.style.cssText;c.style.transform='scale(.75)';c.style.transformOrigin='top left';c.style.overflow='hidden';document.querySelector('#region-0').focus()}"
        )
        check(
            "floating image control escapes scaled clipped diagrams and stays reachable",
            frame_js(
                "{const b=document.querySelector('.anki-wr-mark:popover-open'),r=b?.getBoundingClientRect();!!r && r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight && document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===b}"
            ),
        )
        frame_js(
            "document.querySelector('.svg_answer_parent').style.cssText=originalDiagramStyle"
        )
        frame_js("document.querySelector('[data-wr-key=s0]').click()")
        wait(lambda: image_reviewer.weak_review.value["known"] == ["s0"])
        show_question(image_reviewer)
        wait(
            lambda: (
                frame_js("document.querySelectorAll('[data-wr-hidden=true]').length")
                == 9
            )
        )
        check(
            "image keeps complete context and verified pixels",
            frame_js(
                "document.querySelector('.svg_background-image img').src.startsWith('data:image/svg+xml;base64,')"
            ),
        )
        check(
            "empty image region consumes no recall slot",
            frame_js(
                "document.querySelectorAll('.anki-wr-region-mark').length===10 && "
                "!document.querySelector('#empty-region').hasAttribute('data-wr-hidden')"
            ),
        )
        frame_js("document.querySelector('#region-4').click()")
        frame_js("document.querySelector('[data-wr-key=s4]').click()")
        wait(lambda: image_reviewer.weak_review.value["known"] == ["s0", "s4"])
        show_question(image_reviewer)
        check(
            "region after empty placeholder remembers the correct answer",
            frame_js(
                "document.querySelector('#region-4').dataset.wrHidden==='false' && "
                "document.querySelector('#region-5').dataset.wrHidden==='true' && "
                "document.querySelectorAll('[data-wr-hidden=true]').length===8"
            ),
        )
        frame_js("document.querySelector('[data-wr-key=s4]').click()")
        wait(lambda: image_reviewer.weak_review.value["known"] == ["s0"])
        before_resize = image_reviewer.weak_review.manifest
        mw.resize(1050, 700)
        wait(lambda: ready(image_reviewer))
        check(
            "image marks survive window resizing",
            image_reviewer.weak_review.manifest == before_resize
            and image_reviewer.weak_review.value["known"] == ["s0"],
        )
        revision = 1
        show_question(image_reviewer)
        wait(
            lambda: (
                frame_js("document.querySelectorAll('[data-wr-hidden=true]').length")
                == 10
            )
        )
        check(
            "replacement bytes at the same image URL invalidate marks",
            image_reviewer.weak_review.value["known"] == [],
        )
        check(
            "other pane's marks remain separate",
            left.reviewer.weak_review.value["known"] == ["s0", "s1", "s2", "s3"],
        )
        revision = 2
        image_reviewer._showQuestion()
        wait(lambda: "空格或图片" in image_reviewer.weak_review.status)
        check(
            "invalid image snapshot restores the original template",
            frame_js(
                "document.querySelectorAll('.anki-wr-mark').length===0 && document.querySelectorAll('.svg_mask').length===11"
            ),
        )
        mw.grab().save(str(BASE / "dual.png"))
        right.deck.setCurrentIndex(right.deck.findData(expected["text_deck"]))
        wait(lambda: not right.pending and ready(image_reviewer))

        def text_hidden():
            return frame_js(
                "document.querySelectorAll('.anki-wr-inline-host [data-wr-concealed=true]').length"
            )

        wait(lambda: text_hidden() == 9)
        cross_origin_frame(image_reviewer)
        wait(lambda: text_hidden() == 9)
        check(
            "unrevealed iframe answers have no visible marking controls",
            frame_js(
                "[...document.querySelectorAll('.anki-wr-mark')].every(b=>!b.getClientRects().length)"
            ),
        )
        before_text_marks = snapshot()
        check(
            "nine custom text slots detected",
            len(image_reviewer.weak_review.slots) == 9,
        )
        frame_js("document.querySelector('[data-wr-inline]').click()")
        wait(lambda: text_hidden() == 8)
        check(
            "custom text reveal does not mark",
            image_reviewer.weak_review.value["known"] == [],
        )
        text_bounds = frame_js(
            "JSON.stringify(document.querySelector('.anki-wr-inline-host').getBoundingClientRect())"
        )
        mw.grab().save(str(BASE / "quiet-text.png"))
        mouse_move(image_reviewer, "[data-wr-key=blank-s0]", in_frame=True)
        wait(
            lambda: frame_js(
                "document.querySelectorAll('.anki-wr-mark:popover-open').length===1"
            )
        )
        check(
            "hover exposes only the revealed answer control without moving text",
            frame_js(
                "JSON.stringify(document.querySelector('.anki-wr-inline-host').getBoundingClientRect())"
            )
            == text_bounds
            and frame_js(
                "document.querySelector('.anki-wr-mark:popover-open').dataset.wrKey==='s0'"
            ),
        )
        mouse_move(image_reviewer, "[data-wr-key=s0]", in_frame=True)
        check(
            "pointer can reach the floating mark across the gap",
            frame_js(
                "document.querySelector('[data-wr-key=s0]').matches(':popover-open')"
            ),
        )
        mw.grab().save(str(BASE / "hover-text.png"))
        mouse_move(image_reviewer, ".flex-q-clz", in_frame=True)
        wait(lambda: frame_js("!document.querySelector('.anki-wr-mark:popover-open')"))
        check("moving away restores uncluttered reading", text_hidden() == 8)
        mouse_click(image_reviewer, "[data-wr-key=s0]", in_frame=True)
        wait(lambda: image_reviewer.weak_review.value["known"] == ["s0"])
        press_space(image_reviewer)
        wait(
            lambda: (
                image_reviewer.state == "answer"
                and ready(image_reviewer)
                and image_reviewer.weak_review.value["known"] == ["s0"]
                and text_hidden() == 0
            )
        )
        check(
            "Space after a mouse mark in a frame reveals only the active pane",
            image_reviewer.weak_review.value["known"] == ["s0"]
            and reviewer.state == "question"
            and snapshot() == before_text_marks,
        )
        show_question(image_reviewer)
        wait(lambda: text_hidden() == 8)
        check(
            "equal text in different slots remains independently hidden",
            frame_js(
                "document.querySelector('[data-wr-inline=\"5\"]').dataset.wrConcealed==='true'"
            ),
        )
        image_reviewer._showAnswer()
        wait(lambda: ready(image_reviewer) and text_hidden() == 0)
        mouse_move(image_reviewer, ".flex-q-clz", in_frame=True)
        wait(lambda: frame_js("!document.querySelector('.anki-wr-mark:popover-open')"))
        check(
            "answer side with many blanks remains free of permanent buttons",
            frame_js(
                "[...document.querySelectorAll('.anki-wr-mark')].every(b=>!b.disabled && !b.getClientRects().length)"
            ),
        )
        mouse_move(image_reviewer, "[data-wr-key=blank-s1]", in_frame=True)
        wait(
            lambda: frame_js(
                "document.querySelector('.anki-wr-mark:popover-open')?.dataset.wrKey==='s1'"
            )
        )
        mouse_move(image_reviewer, "[data-wr-key=blank-s2]", in_frame=True)
        wait(
            lambda: frame_js(
                "document.querySelector('.anki-wr-mark:popover-open')?.dataset.wrKey==='s2'"
            )
        )
        check(
            "moving between answers keeps only one marking action open",
            frame_js(
                "document.querySelectorAll('.anki-wr-mark:popover-open').length===1"
            ),
        )
        QTest.keyClick(
            image_reviewer.web.focusProxy() or image_reviewer.web, Qt.Key.Key_Escape
        )
        wait(lambda: frame_js("!document.querySelector('.anki-wr-mark:popover-open')"))
        check(
            "Escape dismisses the mark without changing recall",
            image_reviewer.weak_review.value["known"] == ["s0"],
        )
        frame_js("document.querySelector('[data-wr-key=s2]').click()")
        wait(lambda: image_reviewer.weak_review.value["known"] == ["s0", "s2"])
        show_question(image_reviewer)
        wait(lambda: text_hidden() == 7)
        check(
            "custom text marks survive flipping and preserve formatting",
            frame_js(
                "document.querySelector('.anki-wr-inline-host strong').style.color==='red' && document.querySelectorAll('.anki-wr-inline-host p').length===10"
            ),
        )
        image_reviewer.weak_review.toggle_full(True)
        wait(lambda: text_hidden() == 9)
        image_reviewer.weak_review.toggle_full(False)
        wait(lambda: text_hidden() == 7)
        frame_js("document.querySelector('[data-wr-key=s0]').click()")
        wait(lambda: text_hidden() == 8)
        check(
            "custom remembered slot can rejoin review without changing equal answer",
            image_reviewer.weak_review.value["known"] == ["s2"],
        )
        image_reviewer.weak_review.undo_mark()
        wait(lambda: text_hidden() == 7)
        check(
            "custom text operations never grade or reschedule",
            snapshot() == before_text_marks,
        )
        image_reviewer.weak_review.toggle(False)
        wait(
            lambda: frame_js(
                "document.querySelectorAll('.anki-wr-inline-host').length===0"
            )
        )
        frame_js("document.querySelector('a[href=\"blankIndex:1\"]').click()")
        check(
            "disabling restores original interactive text renderer",
            frame_js(
                "testParts[1][2]===1 && document.querySelector('uni-rich-text').style.display!== 'none'"
            ),
        )
        image_reviewer.weak_review.toggle(True)
        wait(lambda: ready(image_reviewer) and text_hidden() == 7)
        frame_js(
            "testParts[0]=testParts[0].replace('合成标题','新标题');renderNative()"
        )
        wait(
            lambda: (
                ready(image_reviewer)
                and image_reviewer.weak_review.value["known"] == []
            )
        )
        check(
            "remote text edits invalidate saved marks",
            frame_js(
                "document.querySelector('.anki-wr-inline-host').textContent.includes('新标题')"
            ),
        )
        frame_js("testParts[1][0]='<code>不支持的格式</code>';renderNative()")
        wait(lambda: "空格或图片" in image_reviewer.weak_review.status)
        check(
            "unknown inline markup safely restores original content",
            frame_js(
                "!document.querySelector('.anki-wr-inline-host') && document.querySelector('uni-rich-text').style.display!== 'none'"
            ),
        )
        show_question(image_reviewer)
        wait(lambda: text_hidden() == 7)
        image_reviewer._showAnswer()
        wait(lambda: ready(image_reviewer) and text_hidden() == 0)
        image_reviewer._answerCard(1)
        wait(
            lambda: (
                ready(image_reviewer)
                and image_reviewer.state == "question"
                and text_hidden() == 7
            )
        )
        check(
            "custom text marks carry through actual relearning step",
            mw.col.db.scalar("select count(*) from revlog")
            == len(before_text_marks[1]) + 1,
        )
        right.deck.setCurrentIndex(right.deck.findData(expected["table_deck"]))
        wait(lambda: not right.pending and ready(image_reviewer))

        def table_hidden():
            return frame_js(
                "document.querySelectorAll('.anki-wr-table-host [data-wr-concealed=true]').length"
            )

        wait(lambda: table_hidden() == 9)
        before_table_marks = snapshot()
        check("nine table cells detected", len(image_reviewer.weak_review.slots) == 9)
        frame_js("document.querySelector('.anki-wr-table-host td').click()")
        wait(lambda: table_hidden() == 8)
        check(
            "table reveal does not mark",
            image_reviewer.weak_review.value["known"] == [],
        )
        frame_js("document.querySelector('[data-wr-key=s0]').click()")
        wait(lambda: image_reviewer.weak_review.value["known"] == ["s0"])
        show_question(image_reviewer)
        wait(lambda: table_hidden() == 8)
        check(
            "equal table answers are independent and headers stay unchanged",
            frame_js(
                "document.querySelector('.anki-wr-table-host td:nth-child(3) [data-wr-concealed]').dataset.wrConcealed==='true' && !document.querySelector('.anki-wr-table-host th .anki-wr-mark') && document.querySelectorAll('.anki-wr-table-host th').length===7"
            ),
        )
        image_reviewer._showAnswer()
        wait(lambda: ready(image_reviewer) and table_hidden() == 0)
        frame_js("document.querySelector('[data-wr-key=s2]').click()")
        wait(lambda: image_reviewer.weak_review.value["known"] == ["s0", "s2"])
        check(
            "table answer side preserves formatting and enables every mark",
            frame_js(
                "document.querySelectorAll('.anki-wr-table-host td b').length===3 && document.querySelectorAll('.anki-wr-table-host .anki-wr-mark:not(:disabled)').length===9"
            ),
        )
        show_question(image_reviewer)
        wait(lambda: table_hidden() == 7)
        image_reviewer.weak_review.toggle_full(True)
        wait(lambda: table_hidden() == 9)
        image_reviewer.weak_review.toggle_full(False)
        wait(lambda: table_hidden() == 7)
        frame_js("document.querySelector('[data-wr-key=s0]').click()")
        wait(lambda: table_hidden() == 8)
        image_reviewer.weak_review.undo_mark()
        wait(lambda: table_hidden() == 7)
        image_reviewer.weak_review.reset()
        wait(lambda: table_hidden() == 9)
        image_reviewer.weak_review.undo_mark()
        wait(lambda: table_hidden() == 7)
        check("table controls do not reschedule", snapshot() == before_table_marks)
        frame_js("rebuildNative()")
        wait(lambda: ready(image_reviewer) and table_hidden() == 7)
        check(
            "table rebuild restores marks once",
            frame_js(
                "document.querySelectorAll('.anki-wr-table-host').length===1 && document.querySelectorAll('.anki-wr-mark').length===9"
            ),
        )
        image_reviewer.weak_review.toggle(False)
        wait(lambda: frame_js("!document.querySelector('.anki-wr-table-host')"))
        frame_js("document.querySelector('.mumu-table td').click()")
        check(
            "table disable restores native click and leaves source data intact",
            frame_js(
                "testRows[1][1].show===1 && testRows[1][3].show===0 && document.querySelector('.mumu-table').style.display!=='none'"
            ),
        )
        image_reviewer.weak_review.toggle(True)
        wait(lambda: ready(image_reviewer) and table_hidden() == 7)
        old_request = image_reviewer.weak_review.request
        frame_js("testRows[0][1].text='修改的表头';renderNative()")
        wait(
            lambda: (
                ready(image_reviewer)
                and image_reviewer.weak_review.value["known"] == []
            )
        )
        image_reviewer.weak_review.receive(
            json.dumps(
                {
                    "kind": "mark",
                    "token": image_reviewer.weak_review.token,
                    "request": old_request,
                    "key": "s1",
                    "known": True,
                }
            )
        )
        check(
            "table header edits invalidate marks and reject stale clicks",
            image_reviewer.weak_review.value["known"] == [],
        )
        check(
            "updated table remains visible after replacing its review view",
            frame_js(
                "document.querySelector('.anki-wr-table-host').getBoundingClientRect().width > 0"
            ),
        )
        for kind, change in (
            ("formula", f"testRows[1][1].text={json.dumps(r'\(x^2\)')}"),
            ("media", "testRows[1][1].text='<img src=\"unsupported\">'"),
            ("uneven rows", "testRows[1].pop()"),
        ):
            frame_js(change + ";renderNative()")
            wait(lambda: "空格或图片" in image_reviewer.weak_review.status)
            check(
                kind + " restores original table renderer",
                frame_js(
                    "!document.querySelector('.anki-wr-table-host') && document.querySelector('.mumu-table').style.display!=='none'"
                ),
            )
            show_question(image_reviewer)
            wait(lambda: table_hidden() == 7)
        image_reviewer._showAnswer()
        wait(lambda: ready(image_reviewer) and table_hidden() == 0)
        mw.grab().save(str(BASE / "table-answer.png"))
        image_reviewer._answerCard(1)
        wait(
            lambda: (
                ready(image_reviewer)
                and image_reviewer.state == "question"
                and table_hidden() == 7
            )
        )
        check(
            "table marks carry through actual learning step",
            image_reviewer.weak_review.value["known"] == ["s0", "s2"]
            and mw.col.db.scalar("select count(*) from revlog")
            == len(before_table_marks[1]) + 1,
        )
        mw.grab().save(str(BASE / "table-question.png"))
        for kind, target_deck, count in [
            ("studio", expected["studio_deck"], 6),
            ("enhanced", expected["enhanced_deck"], 7),
        ]:
            right.deck.setCurrentIndex(right.deck.findData(target_deck))
            wait(lambda: not right.pending and ready(image_reviewer))
            local = image_reviewer
            selector = ".aswk" if kind == "studio" else ".genuine-cloze"

            def local_hidden():
                return js(
                    local.web,
                    "document.querySelectorAll('[data-wr-concealed=true]').length",
                )

            wait(lambda: local_hidden() == count)
            baseline = snapshot()
            check(
                kind + " asynchronous template detects only target slots",
                len(local.weak_review.slots) == count
                and js(local.web, "document.querySelectorAll('.anki-wr-mark').length")
                == count,
            )
            js(local.web, f"document.querySelector('{selector}').click()")
            wait(lambda: local_hidden() == count - 1)
            check(
                kind + " native reveal never marks",
                local.weak_review.value["known"] == [],
            )
            mark(local, 0)
            show_question(local)
            wait(lambda: local_hidden() == count - 1)
            check(
                kind + " remembered answer remains visible",
                local.weak_review.value["known"] == ["s0"],
            )
            if kind == "studio":
                js(local.web, "document.getElementById('showButton').click()")
                wait(lambda: local_hidden() == count - 2)
                js(local.web, "document.getElementById('resetButton').click()")
                wait(lambda: local_hidden() == count - 1)
                check(
                    "studio reveal/reset preserves mark and ordinary formatting",
                    js(
                        local.web,
                        "document.querySelector('.content>b').textContent==='普通加粗' && document.querySelectorAll('u').length===1",
                    ),
                )
            else:
                js(local.web, "showTestCloze()")
                wait(lambda: local_hidden() == count - 2)
                check(
                    "enhanced pseudo-clozes retain original behavior",
                    js(
                        local.web,
                        "document.querySelectorAll('.pseudo-cloze[show-state=answer]').length===2 && !document.querySelector('.pseudo-cloze[data-wr-known]')",
                    ),
                )
                js(local.web, "rebuildTestClozes()")
                wait(lambda: ready(local) and local_hidden() == count - 1)
                check(
                    "enhanced DOM rebuild retains individual identity without wrapper recursion",
                    local.weak_review.value["known"] == ["s0"],
                )
            show_answer(local)
            wait(lambda: local_hidden() == 0)
            mark(local, 2)
            show_question(local)
            wait(lambda: local_hidden() == count - 2)
            local.weak_review.toggle_full(True)
            wait(lambda: local_hidden() == count)
            local.weak_review.toggle_full(False)
            wait(lambda: local_hidden() == count - 2)
            mark(local, 0)
            wait(lambda: local_hidden() == count - 1)
            local.weak_review.undo_mark()
            wait(lambda: local_hidden() == count - 2)
            check(
                kind + " equal answers, flip, full test and mark undo stay independent",
                local.weak_review.value["known"] == ["s0", "s2"],
            )
            check(kind + " local actions do not reschedule", snapshot() == baseline)
            local.weak_review.toggle(False)
            wait(
                lambda: (
                    js(local.web, "document.querySelectorAll('.anki-wr-mark').length")
                    == 0
                )
            )
            js(
                local.web,
                "replaceAndScroll()" if kind == "studio" else "showTestCloze()",
            )
            check(
                kind + " disabling restores original template functions",
                js(
                    local.web,
                    "!!document.querySelector('b[data-test-blank]')"
                    if kind == "studio"
                    else "document.querySelectorAll('.genuine-cloze[show-state=answer]').length===1",
                ),
            )
            local.weak_review.toggle(True)
            show_question(local)
            wait(lambda: local_hidden() == count - 2)
            show_answer(local)
            local._answerCard(1)
            wait(
                lambda: (
                    ready(local)
                    and local.state == "question"
                    and local_hidden() == count - 2
                )
            )
            check(
                kind + " rating carries marked slots into learning",
                mw.col.db.scalar("select count(*) from revlog") == len(baseline[1]) + 1,
            )
        owner.toggle()
        wait(lambda: not owner.enabled)
        mw.moveToState("deckBrowser")
        mw.col.decks.select(expected["deck"])
        mw.moveToState("review")
        wait(lambda: ready(mw.reviewer))
    else:
        wait(lambda: hidden(reviewer) == 6)
        check(
            "fresh process restores the unfinished four marks",
            reviewer.weak_review.value["known"] == ["s0", "s1", "s2", "s3"],
        )
        # Keep review open so Anki's ordinary in-review undo remains available.
        # Existing end-of-session dashboard writes can clear native undo history.
        continuation = mw.col.new_note(reviewer.card.note_type())
        continuation.fields[0] = "后续合成卡片 {{c1::继续}}"
        mw.col.add_note(continuation, expected["deck"])
        reviewer.weak_review.toggle_full(True)
        show_answer(reviewer)
        round_manifest = reviewer.weak_review.manifest
        reviewer._answerCard(4)
        wait(lambda: ready(reviewer) and reviewer.card.id != expected["native_id"])
        card = mw.col.get_card(expected["native_id"])
        check("easy graduates through the original scheduler", card.type == 2)
        controller = reviewer.weak_review
        value = controller.store.load(
            card.id,
            feature.schedule_identity(card, mw.col),
            feature.card_identity(card),
            round_manifest,
        )
        check("next normal review starts without saved marks", value["known"] == [])
        mw.undo()
        wait(lambda: not mw._background_op_count)
        reviewer.refresh_if_needed()
        card.load()
        value = controller.store.load(
            card.id,
            feature.schedule_identity(card, mw.col),
            feature.card_identity(card),
            round_manifest,
        )
        check(
            "undo graduation recovers the unfinished round",
            len(value["known"]) == 4,
        )
        mw.moveToState("deckBrowser")
        mw.col.decks.select(expected["text_deck"])
        mw.moveToState("review")
        wait(lambda: ready(reviewer))
        wait(
            lambda: (
                js(
                    reviewer.web,
                    "document.querySelector('#receiver').contentDocument.querySelectorAll('[data-wr-concealed=true]').length",
                )
                == 7
            )
        )
        check(
            "fresh process restores custom text marks",
            reviewer.weak_review.value["known"] == ["s0", "s2"],
        )
        before = snapshot()
        cross_origin_frame(reviewer)
        mouse_click(reviewer, "[data-wr-key=s0]", in_frame=True)
        wait(lambda: reviewer.weak_review.value["known"] == ["s2"])
        press_space(reviewer)
        wait(
            lambda: (
                reviewer.state == "answer"
                and ready(reviewer)
                and reviewer.weak_review.value["known"] == ["s2"]
            )
        )
        check(
            "single-pane Space works after removing a mark inside a remote frame",
            snapshot() == before,
        )
        js(
            reviewer.web,
            "document.querySelector('[data-wr-key=s0]').click()",
            in_frame=True,
        )
        wait(lambda: reviewer.weak_review.value["known"] == ["s0", "s2"])

        mw.moveToState("deckBrowser")
        mw.col.decks.select(expected["table_deck"])
        mw.moveToState("review")
        wait(lambda: ready(reviewer))
        wait(
            lambda: (
                js(
                    reviewer.web,
                    "document.querySelector('#receiver').contentDocument.querySelectorAll('[data-wr-concealed=true]').length",
                )
                == 7
            )
        )
        check(
            "fresh process restores table marks in single review",
            reviewer.weak_review.value["known"] == ["s0", "s2"],
        )

        for kind, target_deck, count in [
            ("studio", expected["studio_deck"], 6),
            ("enhanced", expected["enhanced_deck"], 7),
        ]:
            mw.moveToState("deckBrowser")
            mw.col.decks.select(target_deck)
            mw.moveToState("review")
            wait(lambda: ready(reviewer))
            wait(
                lambda: (
                    js(
                        reviewer.web,
                        "document.querySelectorAll('[data-wr-concealed=true]').length",
                    )
                    == count - 2
                )
            )
            check(
                kind + " fresh process restores marks",
                reviewer.weak_review.value["known"] == ["s0", "s2"],
            )

    if os.environ.get("ANKI_WEAK_INSIGHTS_SMOKE") == "1":
        from weak_insights_smoke import run_checks

        run_checks(globals())

    mw.dual_review.stop()
    mw.learning_workspace.profile_close()
    mw.col.close()
    mw.col = None
except BaseException:
    results["errors"].append(traceback.format_exc())
    print(results["errors"][-1], flush=True)
    if "mw" in globals() and mw:
        if "reviewer" in globals():
            print(
                "DEBUG",
                reviewer.state,
                reviewer.controls_active(),
                reviewer.weak_review.status,
                reviewer.weak_review.value,
                mw.state,
                reviewer._refresh_needed,
                flush=True,
            )
        mw.grab().save(str(BASE / "failure.png"))
finally:
    results["passed"] = bool(results["checks"]) and not results["errors"]
    (BASE / f"results-{mode}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("RESULT", results["passed"], len(results["checks"]), flush=True)
    os._exit(0 if results["passed"] else 1)
