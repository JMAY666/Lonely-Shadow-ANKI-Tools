# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from anki.collection import Collection
from aqt.builtin_features.passfail2 import remap_answer
from aqt.builtin_features.weak_review import WeakReview, card_identity
from aqt.builtin_features.weak_review_ai import summarize
from aqt.builtin_features.weak_review_insights import (
    InsightStore,
    begin_visit,
    burden,
    collect_items,
    practice_interval,
    report_batches,
    slot_scores,
)
from aqt.builtin_features.weak_review_report import render_report
from aqt.qt import QApplication


def test_four_blanks_count_only_unmastered_slots_and_survive_restart(tmp_path):
    keys = ["s0", "s1", "s2", "s3"]
    store = InsightStore(tmp_path / "weak-review.sqlite3")
    value = {"known": [], "history": []}
    for schedule, known in [
        ("one", []),
        ("two", ["s0", "s1"]),
        ("three", ["s0", "s1", "s2"]),
        ("four", keys),
    ]:
        value = begin_visit(value, schedule, keys)
        assert begin_visit(value, schedule, keys) == value
        value["known"] = known
        store.save(1, schedule, "source", "manifest", value)
        value = InsightStore(store.path).load(1, schedule, "source", "manifest")
    assert value["attempts"] == {"s0": 2, "s1": 2, "s2": 3, "s3": 4}
    assert burden(value["attempts"], keys)["rating"] == 2
    assert store.load(1, "two", "source", "manifest")["attempts"] == dict.fromkeys(
        keys, 2
    )
    next_round = begin_visit({"known": [], "history": []}, "later", keys)
    assert next_round["attempts"] == dict.fromkeys(keys, 1)
    assert burden(next_round["attempts"], keys)["rating"] == 3


def test_difficulty_can_reverse_and_old_weakness_can_retire():
    keys = ["s0", "s1"]
    events = [{"session": "first", "attempts": {"s0": 4, "s1": 1}, "known": keys}]
    assert slot_scores(events, keys)["s0"]["level"] == "重点"
    events.append({"session": "second", "attempts": {"s0": 1, "s1": 4}, "known": keys})
    scores = slot_scores(events, keys)
    assert scores["s1"]["score"] > scores["s0"]["score"]
    assert scores["s0"]["level"] == "留意"
    events.append(
        {"session": "third", "attempts": dict.fromkeys(keys, 1), "known": keys}
    )
    assert slot_scores(events, keys)["s0"]["level"] == "普通"
    assert slot_scores(events, keys)["s0"]["total_attempts"] == 6


def test_temporary_template_change_does_not_overwrite_original_visit(tmp_path):
    store = InsightStore(tmp_path / "weak.sqlite3")
    original = {"known": ["s0"], "history": [[]], "attempts": {"s0": 2}}
    store.save(1, "same-schedule", "source", "original", original)
    store.save(1, "same-schedule", "source", "changed", {"known": [], "history": []})
    assert store.load(1, "same-schedule", "source", "original") == original


def test_each_round_contributes_once_instead_of_counting_cumulative_snapshots():
    events = [
        {"session": "same", "attempts": {"s0": n}, "known": []} for n in (1, 2, 3, 4)
    ]
    score = slot_scores(events, ["s0"])["s0"]
    assert score["rounds"] == 1
    assert score["total_attempts"] == 4


@pytest.fixture
def collection(tmp_path):
    col = Collection(str(tmp_path / "collection.anki2"))
    deck = col.decks.id("Synthetic::Child")
    note = col.new_note(
        next(m for m in col.models.all() if m["type"] == 1 and len(m["flds"]) == 2)
    )
    note.fields[0] = "Synthetic context {{c1::answer}}"
    col.add_note(note, deck)
    card = note.cards()[0]
    yield col, card
    col.close()


def test_native_undo_filters_reports_and_practice_never_writes_native_history(
    collection, tmp_path
):
    col, card = collection
    store = InsightStore(tmp_path / "weak.sqlite3")
    source = card_identity(card)
    store.catalog(
        card.id,
        source,
        "m",
        {"slots": [{"key": "s0", "context": "Context [blank]", "answer": "answer"}]},
    )
    card.start_timer()
    col.decks.select(card.did)
    col.sched.get_queued_cards()
    answer = col.sched.build_answer(
        card=card, states=col._backend.get_scheduling_states(card.id), rating=0
    )
    col.sched.answer_card(answer)
    revlog = col.db.scalar("select max(id) from revlog where cid=?", card.id)
    store.record(
        card.id,
        source,
        "m",
        revlog,
        {
            "session": "round",
            "attempts": {"s0": 1},
            "known": [],
            "tested": ["s0"],
            "at": 1000,
        },
    )
    deck_ids = {card.did}
    items = collect_items(col, store, deck_ids, 90000, (0, 86400))
    assert len(items) == 1 and items[0]["day_misses"] == 1
    assert collect_items(col, store, deck_ids, 90000)[0]["day_misses"] == 0
    assert collect_items(col, store, {999}, 90000) == []
    assert collect_items(col, store, deck_ids, 90000, (86400, 172800)) == []
    before = col.db.all("select * from cards"), col.db.all("select * from revlog")
    exercise = store.practice(items[0], True, 90000)
    pending = collect_items(col, store, deck_ids, 90001)
    assert pending[0]["pending_confirmation"] and pending[0]["score"] < 0.25
    assert pending[0]["due"] == 176400
    second = store.practice(items[0], True, 176401)
    assert collect_items(col, store, deck_ids, 176402) == []
    store.undo_practice(second)
    assert (
        col.db.all("select * from cards"),
        col.db.all("select * from revlog"),
    ) == before
    store.undo_practice(exercise)
    assert len(collect_items(col, store, deck_ids, 90001)) == 1
    col.undo()
    assert collect_items(col, store, deck_ids, 90001) == []
    col.redo()
    assert len(collect_items(col, store, deck_ids, 90001)) == 1
    note = card.note()
    note.fields[0] = "Changed {{c1::new}}"
    col.update_note(note)
    assert collect_items(col, store, deck_ids, 90001) == []


@pytest.mark.parametrize(
    "score,remembered,previous,expected",
    [
        (1, False, 259200, 600),
        (1, True, 0, 86400),
        (0.3, True, 0, 259200),
        (1, True, 86400, 172800),
        (0.5, True, 2592000, 2592000),
    ],
)
def test_practice_intervals_follow_outcomes_and_are_bounded(
    score, remembered, previous, expected
):
    assert practice_interval(score, remembered, previous) == expected


def item(index=0, image=False):
    return {
        "card": 1,
        "source": "src",
        "manifest": "m",
        "key": f"s{index}",
        "deck": "Synthetic",
        "context": "Context with [blank]",
        "answer": "Answer",
        "score": 0.75,
        "level": "重点",
        "last_attempts": 4,
        "total_attempts": 5,
        "rounds": 2,
        "day_attempts": 3,
        "day_misses": 2,
        "due": 180000,
        "asset": "image" if image else None,
    }


def test_report_batches_include_every_slot_and_limit_image_attachments():
    items = [item(i, True) for i in range(19)]
    batches = report_batches(items, 2000)
    assert [row["key"] for batch in batches for row in batch] == [
        f"s{i}" for i in range(19)
    ]
    assert max(len(batch) for batch in batches) <= 4


def test_ai_summary_covers_entire_subset_and_preserves_batch_details():
    calls = []

    def request(settings, messages):
        calls.append(messages)
        return "Analysis " + str(len(calls))

    items = [item(i, True) for i in range(9)]
    result = summarize(
        {},
        {
            "items": items,
            "scope": "Synthetic",
            "day": "2026-09-26",
            "kind": "子集全面总结",
        },
        {},
        request,
    )
    assert len(calls) == 4
    assert "s8" in calls[2][-1]["content"]
    assert all("Analysis " + str(i) in result for i in range(1, 5))
    with pytest.raises(RuntimeError, match="offline"):
        summarize(
            {},
            {"items": items, "scope": "Synthetic", "day": "today", "kind": "daily"},
            {},
            Mock(side_effect=RuntimeError("offline")),
        )


@pytest.fixture
def app():
    return QApplication.instance() or QApplication(
        ["weak-insights-tests", "-platform", "offscreen"]
    )


def test_report_escapes_card_html_and_excludes_remote_ai_images(app):
    record = item()
    record["answer"] = "<script>alert('x')</script> & answer"
    rendered = render_report(
        {
            "items": [record],
            "day": "2026-09-26",
            "scope": "Synthetic",
            "kind": "每日总结",
        },
        "# Analysis\n![bad](https://example.invalid/x.png)\n<script>x</script>",
        "test",
    )
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "example.invalid" not in rendered
    assert all(
        label in rendered
        for label in ("上下文", "答案", "AI 分析", "累计次数", "近期难度")
    )


def test_canceling_report_stops_before_sending_more_batches():
    calls = []

    def request(settings, messages):
        calls.append(messages)
        return "done"

    snapshot = {
        "items": [item(i, True) for i in range(9)],
        "scope": "Synthetic",
        "day": "today",
        "kind": "daily",
    }
    with pytest.raises(InterruptedError):
        summarize({}, snapshot, {}, request, lambda: bool(calls))
    assert len(calls) == 1


def auto_controller(tmp_path):
    controller = WeakReview.__new__(WeakReview)
    controller.mw = SimpleNamespace(
        pm=SimpleNamespace(profileFolder=lambda: str(tmp_path), profile={})
    )
    controller.card_id, controller.schedule, controller.source, controller.manifest = (
        1,
        "s",
        "n",
        "m",
    )
    (
        controller.token,
        controller.full,
        controller.auto_pending,
        controller.auto_rating,
    ) = "t", False, None, False
    controller.slots = ["s0", "s1"]
    controller.value = {"known": [], "history": [], "attempts": {"s0": 2, "s1": 4}}
    controller.current = Mock(return_value=True)
    controller.publish = Mock()
    controller.reviewer = SimpleNamespace(
        state="answer", _states_mutated=True, _answerCard=Mock()
    )
    return controller


def test_final_mark_submits_one_adaptive_rating_and_stale_timer_cannot_repeat(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("aqt.builtin_features.weak_review.tooltip", Mock())
    monkeypatch.setattr("aqt.builtin_features.weak_review.QTimer.singleShot", Mock())
    controller = auto_controller(tmp_path)
    controller.change(["s0", "s1"])
    pending = controller.auto_pending
    controller.submit_auto(pending)
    controller.submit_auto(pending)
    controller.reviewer._answerCard.assert_called_once_with(2)


@pytest.mark.parametrize("cancel", ["unmark", "full", "stale", "disabled"])
def test_auto_rating_is_canceled_by_new_user_state(tmp_path, monkeypatch, cancel):
    monkeypatch.setattr("aqt.builtin_features.weak_review.tooltip", Mock())
    monkeypatch.setattr("aqt.builtin_features.weak_review.QTimer.singleShot", Mock())
    controller = auto_controller(tmp_path)
    controller.change(["s0", "s1"])
    pending = controller.auto_pending
    if cancel == "unmark":
        controller.change(["s0"])
    elif cancel == "full":
        controller.full = True
    elif cancel == "disabled":
        controller.mw.pm.profile["weakReviewAutoPass"] = False
    else:
        controller.current.return_value = False
    controller.submit_auto(pending)
    controller.reviewer._answerCard.assert_not_called()


def test_pass_fail_mode_preserves_only_explicit_automatic_rating():
    reviewer = SimpleNamespace(
        weak_review=SimpleNamespace(auto_rating=True), _defaultEase=lambda: 3
    )
    assert remap_answer((True, 2), reviewer, {"enabled": True}) == (True, 2)
    reviewer.weak_review.auto_rating = False
    assert remap_answer((True, 2), reviewer, {"enabled": True}) == (True, 3)


def test_auto_rating_waits_for_custom_scheduler_without_requiring_another_click(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("aqt.builtin_features.weak_review.tooltip", Mock())
    monkeypatch.setattr("aqt.builtin_features.weak_review.QTimer.singleShot", Mock())
    controller = auto_controller(tmp_path)
    controller.change(["s0", "s1"])
    pending = controller.auto_pending
    controller.reviewer._states_mutated = False
    controller.submit_auto(pending)
    controller.reviewer._answerCard.assert_not_called()
    assert controller.auto_pending == pending
    controller.reviewer._states_mutated = True
    controller.submit_auto(pending)
    controller.reviewer._answerCard.assert_called_once_with(2)
