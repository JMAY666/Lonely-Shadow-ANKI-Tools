# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from anki.collection import Collection
from anki.scheduler_pb2 import CardAnswer
from aqt.builtin_features.weak_review import WeakReview
from aqt.builtin_features.weak_review_schedule import apply_round_schedule, round_plan

NOW = 1800000000
KEYS = ["s0", "s1", "s2", "s3"]


def value(counts, known=None):
    return {
        "session": "current",
        "known": KEYS if known is None else known,
        "attempts": dict(zip(KEYS, counts)),
        "history": [],
    }


def previous(days, at):
    return {
        "session": "previous",
        "known": KEYS,
        "attempts": dict.fromkeys(KEYS, 1),
        "completed": True,
        "next_days": days,
        "at": at,
    }


def test_repeat_burden_sets_the_interval_without_reusing_hard_or_good_steps():
    hard = round_plan(value([2, 2, 3, 4]), KEYS, [], NOW)
    moderate = round_plan(value([1, 1, 1, 2]), KEYS, [], NOW)
    easy = round_plan(value([1, 1, 1, 1]), KEYS, [], NOW)
    assert [hard["next_days"], moderate["next_days"], easy["next_days"]] == [1, 2, 3]
    assert hard["quality"] < moderate["quality"] < easy["quality"]
    assert hard["completed"]


def test_delayed_recall_grows_interval_but_repeats_the_same_day_do_not():
    fresh = value([1, 1, 1, 1])
    assert (
        round_plan(fresh, KEYS, [previous(10, NOW - 10 * 86400)], NOW)["next_days"]
        == 20
    )
    assert round_plan(fresh, KEYS, [previous(10, NOW - 60)], NOW)["next_days"] == 10
    assert (
        round_plan(value([4, 4, 4, 4]), KEYS, [previous(10, NOW - 10 * 86400)], NOW)[
            "next_days"
        ]
        == 1
    )


def test_existing_mature_interval_is_retained_without_inventing_slot_history():
    baseline = {"next_days": 30, "at": NOW - 30 * 86400}
    smooth = round_plan(value([1, 1, 1, 1]), KEYS, [], NOW, native_baseline=baseline)
    isolated = round_plan(value([1, 1, 1, 4]), KEYS, [], NOW, native_baseline=baseline)
    forgotten = round_plan(value([2, 2, 2, 2]), KEYS, [], NOW, native_baseline=baseline)
    assert smooth["next_days"] == 60
    assert isolated["next_days"] == 30
    assert forgotten["next_days"] == 3
    assert (
        round_plan(
            value([1, 1, 1, 1]),
            KEYS,
            [previous(10, NOW - 10 * 86400)],
            NOW,
            maximum_days=12,
        )["next_days"]
        == 12
    )


@pytest.mark.parametrize("fsrs", [False, True])
@pytest.mark.parametrize("kind", ["new", "learning", "relearning", "review"])
def test_finishing_a_round_leaves_no_learning_steps_and_is_one_undoable_answer(
    tmp_path, kind, fsrs
):
    col = Collection(str(tmp_path / "collection.anki2"))
    try:
        col.set_config("fsrs", fsrs)
        model = next(
            m for m in col.models.all() if m["type"] == 1 and len(m["flds"]) == 2
        )
        note = col.new_note(model)
        note.fields[0] = "Synthetic {{c1::one}} {{c1::two}} {{c1::three}} {{c1::four}}"
        col.add_note(note, col.decks.get_current_id())
        card = note.cards()[0]
        config = col.decks.config_dict_for_deck_id(card.did)
        config["new"]["delays"] = [1, 10, 60, 1440]
        config["lapse"]["delays"] = [1, 10, 60]
        col.decks.update_config(config)
        if kind in ("review", "relearning"):
            col.sched.set_due_date([card.id], "0")
            card.load()
        if kind in ("learning", "relearning"):
            card.start_timer()
            col.sched.get_queued_cards()
            failure = col.sched.build_answer(
                card=card,
                states=col._backend.get_scheduling_states(card.id),
                rating=CardAnswer.AGAIN,
            )
            col.sched.answer_card(failure)
            card.load()
        before = col.db.first(
            "select type,queue,due,ivl,reps,left,lapses from cards where id=?", card.id
        )
        reviews = col.db.scalar("select count(*) from revlog")
        card.start_timer()
        col.sched.get_queued_cards()
        states = col._backend.get_scheduling_states(card.id)
        answer = col.sched.build_answer(
            card=card, states=states, rating=CardAnswer.GOOD
        )
        plan = round_plan(value([2, 2, 3, 4]), KEYS, [], NOW)
        token = answer.current_state.SerializeToString()
        apply_round_schedule(answer, plan)
        assert answer.current_state.SerializeToString() == token
        assert answer.new_state.normal.WhichOneof("kind") == "review"
        assert answer.new_state.normal.review.HasField("memory_state") is fsrs
        col.sched.answer_card(answer)
        card.load()
        assert card.type == 2 and card.queue == 2 and card.ivl == plan["next_days"]
        assert card.due == col.sched.today + plan["next_days"]
        assert col.db.scalar("select count(*) from revlog") == reviews + 1
        assert not col.sched.get_queued_cards().cards
        col.undo()
        assert (
            col.db.first(
                "select type,queue,due,ivl,reps,left,lapses from cards where id=?",
                card.id,
            )
            == before
        )
        assert col.db.scalar("select count(*) from revlog") == reviews
        col.redo()
        assert col.get_card(card.id).ivl == plan["next_days"]
        assert not col.sched.get_queued_cards().cards
    finally:
        col.close()


def test_incomplete_round_cannot_be_passed_by_a_legacy_grade_key(monkeypatch):
    controller = WeakReview.__new__(WeakReview)
    controller.mw = SimpleNamespace()
    controller.controls_round = Mock(return_value=True)
    controller.current = Mock(return_value=True)
    controller.token = "current"
    controller.slots = KEYS
    controller.value = value([2, 2, 3, 4], known=["s0", "s1"])
    monkeypatch.setattr("aqt.builtin_features.weak_review.tooltip", Mock())
    for ease in (2, 3, 4):
        assert controller.normalize_rating(ease) is None
    assert controller.normalize_rating(1) == 1
    controller.value["known"] = KEYS
    assert controller.normalize_rating(3) == 3
    assert controller.normalize_rating(1) is None
    controller.controls_round.return_value = False
    assert controller.normalize_rating(4) == 4
