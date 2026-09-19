"""Actual reviewer/WebEngine acceptance with synthetic data and no external requests."""

import base64
import hashlib
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


def js(web, source):
    received = []
    web.page().runJavaScript(source, received.append)
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
    masks = "".join(
        f'<uni-view class="svg_mask" style="left:{20 + (i % 2) * 240}px;top:{22 + (i // 2) * 70}px;width:180px;height:30px"></uni-view>'
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
        }
        (BASE / "expected.json").write_text(json.dumps(expected))
    else:
        expected = json.loads((BASE / "expected.json").read_text())

    import aqt
    import aqt.builtin_features.weak_review as feature
    from aqt import mediasrv
    from aqt.progress import ProgressDialog
    from aqt.qt import QApplication, QLabel, QTimer

    revision = 0

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
        js(reviewer.web, "document.querySelector('#qa .cloze').click()")
        wait(lambda: hidden(reviewer) == 9)
        check(
            "revealing an answer never marks it",
            reviewer.weak_review.value["known"] == [],
        )
        check(
            "focused marking control keeps Space out of review shortcuts",
            js(
                reviewer.web,
                "{const b=document.querySelector('[data-wr-key=s0]');b.focus();const e=new KeyboardEvent('keydown',{key:' ',bubbles:true,cancelable:true});b.dispatchEvent(e);!e.defaultPrevented}",
            )
            is True,
        )
        mark(reviewer, 0)
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
            return js(
                image_reviewer.web,
                "document.querySelector('#receiver').contentWindow.eval("
                + json.dumps(source)
                + ")",
            )

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
                "document.querySelectorAll('.anki-wr-mark').length===0 && document.querySelectorAll('.svg_mask').length===10"
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
        frame_js("document.querySelector('[data-wr-key=s0]').click()")
        wait(lambda: image_reviewer.weak_review.value["known"] == ["s0"])
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
