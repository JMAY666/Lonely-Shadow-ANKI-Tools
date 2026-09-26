"""Synthetic native review, export, AI boundary, and restart acceptance."""

import json
import os
import runpy
from pathlib import Path


def run_checks(env):
    import time

    from aqt.builtin_features import weak_review_ai
    from aqt.builtin_features.synapsepro import ai_assistant as ai
    from aqt.builtin_features.weak_review import card_identity, schedule_identity
    from aqt.builtin_features.weak_review_dashboard import InsightDialog, PracticeDialog
    from aqt.builtin_features.weak_review_insights import collect_items

    mw, wait, ready, check, js = (
        env[key] for key in ("mw", "wait", "ready", "check", "js")
    )
    base, mode = env["BASE"], env["mode"]
    env["guard"].stop()
    mw.dual_review.stop()
    mw.moveToState("deckBrowser")
    reviewer = mw.reviewer
    if mode == "write":
        deck = mw.col.decks.id("逐空升级验收")
        model = mw.col.models.by_name("Cloze")
        note = mw.col.new_note(model)
        note["Text"] = (
            "<p>四个独立知识点：{{c1::甲概念}}、{{c1::乙概念}}、{{c1::丙概念}}、{{c1::丁概念}}。</p>"
        )
        mw.col.add_note(note, deck)
        card_id = note.cards()[0].id
        mw.col.decks.select(deck)
        mw.moveToState("review")
        wait(lambda: ready(reviewer) and reviewer.card.id == card_id)
        controller = reviewer.weak_review
        check(
            "insights initial visit counts exactly once",
            controller.value["attempts"] == dict.fromkeys(controller.slots, 1),
        )
        manifest = controller.manifest
        controller.show()
        wait(lambda: ready(reviewer))
        check(
            "insights rerender does not count another attempt",
            controller.value["attempts"] == dict.fromkeys(controller.slots, 1),
        )

        def again():
            before = controller.schedule
            if reviewer.state == "question":
                reviewer._showAnswer()
                wait(lambda: ready(reviewer) and reviewer.state == "answer")
            reviewer._answerCard(1)
            wait(
                lambda: (
                    ready(reviewer)
                    and controller.schedule != before
                    and reviewer.card.id == card_id
                )
            )

        def mark(index):
            js(
                reviewer.web,
                f"document.querySelectorAll('#qa .cloze')[{index}].click()",
            )
            wait(
                lambda: js(
                    reviewer.web,
                    f"!document.querySelector('[data-wr-key=s{index}]').disabled",
                )
            )
            js(
                reviewer.web,
                f"document.querySelector('[data-wr-key=s{index}]').click()",
            )

        again()
        mark(0)
        wait(lambda: "s0" in controller.value["known"])
        mark(1)
        wait(lambda: "s1" in controller.value["known"])
        again()
        mark(2)
        wait(lambda: "s2" in controller.value["known"])
        again()
        check(
            "four blanks accumulate 2 2 3 4 attempts",
            controller.value["attempts"] == {"s0": 2, "s1": 2, "s2": 3, "s3": 4},
        )
        check(
            "hardest blank is visibly distinct",
            js(
                reviewer.web,
                "document.querySelector('[data-wr-key=s3]').dataset.wrLevel",
            )
            == "重点",
        )
        mw.grab().save(str(base / "insights-review.png"))
        reviewer._showAnswer()
        wait(lambda: ready(reviewer) and reviewer.state == "answer")
        wait(lambda: "再练未掌握" in js(reviewer.bottom.web, "document.body.innerText"))
        check(
            "round controls disable completion until every blank is marked",
            js(
                reviewer.bottom.web,
                "document.querySelector('[data-ease=\"3\"]').disabled",
            ),
        )
        before_reject = mw.col.db.scalar(
            "select count(*) from revlog where cid=?", card_id
        )
        reviewer._answerCard(3)
        check(
            "legacy passing key cannot finish an incomplete round",
            mw.col.db.scalar("select count(*) from revlog where cid=?", card_id)
            == before_reject,
        )
        js(
            reviewer.bottom.web,
            "window.roundPaintReady=false;requestAnimationFrame(()=>requestAnimationFrame(()=>window.roundPaintReady=true))",
        )
        wait(
            lambda: js(
                reviewer.bottom.web,
                "window.roundPaintReady === true && document.querySelector('[data-ease=\"3\"]')?.disabled === true",
            )
        )
        mw.grab().save(str(base / "round-controls.png"))
        # Keep ordinary review open so native undo remains available.
        extra = mw.col.new_note(model)
        extra["Text"] = "后续卡片 {{c1::保留撤销}}"
        mw.col.add_note(extra, deck)
        mw.passfail2.value["enabled"] = True
        before = mw.col.db.scalar("select count(*) from revlog where cid=?", card_id)
        before_schedule = controller.schedule
        mark(3)
        wait(
            lambda: (
                not mw._background_op_count
                and mw.col.db.scalar("select count(*) from revlog where cid=?", card_id)
                == before + 1
            )
        )
        wait(lambda: ready(reviewer))
        check(
            "last tick commits one completion outcome in pass fail mode",
            mw.col.db.scalar(
                "select ease from revlog where cid=? order by id desc limit 1", card_id
            )
            == 3,
        )
        saved = controller.store.load(
            card_id,
            schedule_identity(mw.col.get_card(card_id), mw.col),
            card_identity(mw.col.get_card(card_id)),
            manifest,
        )
        check(
            "completed round moves to a future review instead of another learning step",
            saved["known"] == []
            and mw.col.get_card(card_id).type == 2
            and mw.col.get_card(card_id).queue == 2
            and mw.col.get_card(card_id).ivl == 1
            and reviewer.card.id != card_id,
        )
        import importlib
        from types import SimpleNamespace
        from unittest.mock import Mock

        disperse = importlib.import_module(
            "aqt.builtin_features.fsrs_helper.schedule.disperse_siblings"
        )
        previous_mw = disperse.mw
        touched = Mock(return_value=False)
        disperse.mw = SimpleNamespace(col=SimpleNamespace(get_config=touched))
        try:
            disperse.disperse_siblings_when_review(
                SimpleNamespace(
                    weak_review=SimpleNamespace(
                        card_id=card_id, submitted_plan={"completed": True}
                    )
                ),
                SimpleNamespace(id=card_id),
                3,
            )
            check(
                "automatic FSRS dispersal cannot overwrite the completed round interval",
                not touched.called,
            )
        finally:
            disperse.mw = previous_mw
        mw.undo()
        wait(lambda: not mw._background_op_count)
        reviewer.refresh_if_needed()
        check(
            "automatic rating has native undo",
            mw.col.db.scalar("select count(*) from revlog where cid=?", card_id)
            == before,
        )
        restored = controller.store.load(
            card_id, before_schedule, card_identity(mw.col.get_card(card_id)), manifest
        )
        check(
            "native undo restores final tick and counts",
            len(restored["known"]) == 4 and restored["attempts"]["s3"] == 4,
        )
        mw.col.redo()
        mw.moveToState("deckBrowser")
        mw.col.decks.select(deck)
        dialog = InsightDialog(mw, controller.insights)
        dialog.show()
        check("daily report includes all four struggled blanks", len(dialog.items) == 4)
        check(
            "report answers and context come from rendered template",
            {item["answer"] for item in dialog.items}
            == {"甲概念", "乙概念", "丙概念", "丁概念"}
            and all("待回忆" in item["context"] for item in dialog.items),
        )
        dialog.resize(1150, 850)
        env["app"].processEvents()
        dialog.grab().save(str(base / "insights-report.png"))
        old_settings, original_summary = ai._load_settings, weak_review_ai.summarize
        calls = []

        def fake_request(settings, messages):
            calls.append(messages)
            return "## 薄弱点分析\n\n丁概念反复测试最多，应结合上下文区别甲、乙、丙概念。\n\n| 知识点 | 建议 |\n| --- | --- |\n| 丁概念 | 隔日独立回忆 |\n\n以上是基于合成记录的测试分析。"

        ai._load_settings = lambda: {
            "provider": "ollama",
            "model": "synthetic",
            "apiKey": "",
        }
        weak_review_ai.summarize = lambda settings, snapshot, images, **kwargs: (
            original_summary(settings, snapshot, images, fake_request, **kwargs)
        )
        dialog.generate()
        wait(lambda: not dialog.busy)
        check(
            "AI report uses existing provider settings and complete subset",
            len(calls) == 1
            and "丁概念" in calls[0][-1]["content"]
            and len(controller.insights.reports()) == 1,
        )
        for suffix in ("pdf", "html", "md"):
            target = base / f"weak-review-report.{suffix}"
            dialog.export_to(target)
            check(
                "export " + suffix + " includes complete report",
                target.stat().st_size > 400,
            )
        before_native = (
            mw.col.db.all("select * from cards"),
            mw.col.db.all("select * from revlog"),
        )
        exercise = PracticeDialog(dialog, [dialog.items[0]])
        exercise.show()
        check(
            "practice does not expose answer before reveal",
            exercise.answer.toPlainText() == ""
            and not exercise.pass_button.isEnabled(),
        )
        exercise.reveal()
        exercise.grade(True)
        check(
            "single blank practice does not reschedule card",
            before_native
            == (
                mw.col.db.all("select * from cards"),
                mw.col.db.all("select * from revlog"),
            ),
        )
        exercise.undo()
        check(
            "single blank practice can be undone",
            exercise.position == 0 and not exercise.revealed,
        )
        exercise.reveal()
        exercise.grade(False)
        exercise.close()
        ai._load_settings, weak_review_ai.summarize = old_settings, original_summary
        (base / "insights-expected.json").write_text(
            json.dumps(
                {
                    "deck": deck,
                    "card": card_id,
                    "source": card_identity(mw.col.get_card(card_id)),
                    "manifest": manifest,
                }
            ),
            encoding="utf8",
        )
        dialog.close()
        # Exercise the user's embedded-webpage path through its real bridge.
        source_id = mw.col.db.scalar(
            "select id from cards where did=? limit 1", env["expected"]["text_deck"]
        )
        source_note = mw.col.get_card(source_id).note()
        frame_note = mw.col.new_note(source_note.note_type())
        frame_note.fields = list(source_note.fields)
        frame_deck = mw.col.decks.id("跨框自动通过验收")
        mw.col.add_note(frame_note, frame_deck)
        frame_id = frame_note.cards()[0].id
        mw.col.decks.select(frame_deck)
        mw.moveToState("review")
        wait(lambda: ready(reviewer) and reviewer.card.id == frame_id)
        env["cross_origin_frame"](reviewer)
        wait(lambda: ready(reviewer) and len(reviewer.weak_review.slots) == 9)
        for index in range(9):
            js(
                reviewer.web,
                f"document.querySelector('[data-wr-key=blank-s{index}]').click()",
                in_frame=True,
            )
            js(
                reviewer.web,
                f"document.querySelector('[data-wr-key=s{index}]').click()",
                in_frame=True,
            )
            if index < 8:
                wait(
                    lambda index=index: (
                        f"s{index}" in reviewer.weak_review.value["known"]
                    )
                )
        wait(
            lambda: (
                not mw._background_op_count
                and mw.col.db.scalar(
                    "select count(*) from revlog where cid=?", frame_id
                )
                == 1
            )
        )
        check(
            "final mark inside cross origin webpage automatically passes once",
            mw.col.db.scalar("select ease from revlog where cid=?", frame_id) == 3,
        )
        # A captured SVG region remains usable in practice and portable exports.
        from aqt.builtin_features.synapsepro.ai_images import prepare_image
        from aqt.builtin_features.weak_review_dashboard import region_image
        from aqt.builtin_features.weak_review_report import render_report, write_pdf

        mw.moveToState("deckBrowser")
        env["revision"] = 0
        mw.col.decks.select(env["expected"]["image_deck"])
        mw.moveToState("review")
        wait(lambda: ready(reviewer) and len(reviewer.weak_review.slots) == 10)
        catalog = next(c for c in controller.insights.catalogs() if c.get("asset"))
        slot = catalog["slots"][0]
        sample = (
            dialog.items[0]
            | slot
            | {
                "card": catalog["card"],
                "source": catalog["source"],
                "manifest": catalog["manifest"],
                "asset": catalog["asset"],
            }
        )
        masked = region_image(controller.insights, sample, False)
        shown = region_image(controller.insights, sample, True)
        check(
            "SVG practice masks only the captured target region",
            not shown.isNull() and masked != shown,
        )
        snapshot = dialog.display_snapshot | {"items": [sample]}
        picture = prepare_image(shown)["dataUrl"]
        content = render_report(
            snapshot, images={f"{sample['card']}:{sample['key']}": picture}
        )
        write_pdf(base / "weak-review-image-report.pdf", content, "合成图像区域报告")
        check(
            "image report embeds its offline image", "data:image/png;base64," in content
        )
        mw.moveToState("deckBrowser")
        # Both panels use the same completion transaction, with separate tokens.
        dual_decks = []
        dual_ids = []
        for label in ("左", "右"):
            did = mw.col.decks.id("逐空完成双栏" + label)
            for index in range(2):
                dual_note = mw.col.new_note(model)
                dual_note.fields[0] = f"{label}{index} {{{{c1::合成答案}}}}"
                mw.col.add_note(dual_note, did)
                if index == 0:
                    dual_ids.append(dual_note.cards()[0].id)
            dual_decks.append(did)
        mw.col.decks.select(dual_decks[0])
        mw.moveToState("review")
        wait(lambda: ready(mw.reviewer))
        mw.dual_review.toggle()
        left, right = mw.dual_review.panels
        wait(lambda: not left.pending and not right.pending)
        right.deck.setCurrentIndex(right.deck.findData(dual_decks[1]))
        mw.dual_review.activate(right, focus=True)
        wait(lambda: not right.pending and ready(right.reviewer))
        right_id, left_id = right.reviewer.card.id, left.reviewer.card.id
        right.reviewer._showAnswer()
        wait(lambda: ready(right.reviewer) and right.reviewer.state == "answer")
        js(right.reviewer.web, "document.querySelector('[data-wr-key=s0]').click()")
        wait(
            lambda: (
                not right.pending
                and ready(right.reviewer)
                and right.reviewer.card.id != right_id
            )
        )
        check(
            "dual pane completion leaves no learning loop and keeps the other card",
            mw.col.get_card(right_id).type == 2 and left.reviewer.card.id == left_id,
        )
        mw.dual_review.stop()
        mw.moveToState("deckBrowser")
    else:
        expected = json.loads(
            (base / "insights-expected.json").read_text(encoding="utf8")
        )
        store = reviewer.weak_review.insights
        reports = store.reports()
        check(
            "AI report persists after process restart",
            len(reports) == 1 and "丁概念" in reports[0]["text"],
        )
        items = collect_items(mw.col, store, {expected["deck"]}, int(time.time()))
        check(
            "adaptive difficulty persists after restart",
            any(item["last_attempts"] == 4 for item in items),
        )
        exercises = store.practices(
            expected["card"], expected["source"], expected["manifest"], "s3"
        )
        check(
            "single blank due time persists after restart",
            len(exercises) == 1 and exercises[0]["interval"] == 600,
        )


if __name__ == "__main__":
    os.environ["ANKI_WEAK_INSIGHTS_SMOKE"] = "1"
    runpy.run_path(
        str(Path(__file__).with_name("weak_review_smoke.py")), run_name="__main__"
    )
