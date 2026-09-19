# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from anki.collection import Collection
from anki.scheduler_pb2 import SchedulingState
from aqt.builtin_features.weak_review import (
    WeakReview,
    card_identity,
    image_snapshot,
    schedule_identity,
)
from aqt.builtin_features.weak_review_store import RecallStore, continues_round


def test_marks_survive_restart_and_do_not_mix_cards_or_slots(tmp_path):
    path = tmp_path / "weak-review.sqlite3"
    store = RecallStore(path)
    store.save(1, "learning", "source", "ten", {"known": ["s0"], "history": [[]]})
    restarted = RecallStore(path)
    assert restarted.load(1, "learning", "source", "ten")["known"] == ["s0"]
    assert restarted.load(2, "learning", "source", "ten")["known"] == []
    assert restarted.load(1, "learning", "edited", "ten")["known"] == []
    assert restarted.load(1, "learning", "source", "changed-image")["known"] == []


def test_learning_carries_but_graduation_resets_and_undo_recovers(tmp_path):
    store = RecallStore(tmp_path / "marks.sqlite3")
    value = {"known": ["s0", "s3"], "history": [[], ["s0"]]}
    store.save(1, "first", "source", "ten", value)
    store.advance(1, "learning", "source", "ten", value, True)
    store.advance(1, "review", "source", "ten", value, False)
    assert store.load(1, "learning", "source", "ten") == value
    assert store.load(1, "review", "source", "ten")["known"] == []
    assert store.load(1, "first", "source", "ten") == value


@pytest.mark.parametrize(
    "kind,expected",
    [("new", False), ("learning", True), ("relearning", True), ("review", False)],
)
def test_round_boundary_follows_actual_scheduling_state(kind, expected):
    state = SchedulingState()
    getattr(state.normal, kind).SetInParent()
    assert continues_round(state) is expected


def test_filtered_preview_does_not_inherit_normal_learning_marks():
    state = SchedulingState()
    state.filtered.preview.scheduled_secs = 30
    assert not continues_round(state)


@pytest.fixture
def collection(tmp_path):
    col = Collection(str(tmp_path / "collection.anki2"))
    model = next(m for m in col.models.all() if m["type"] == 1 and len(m["flds"]) == 2)
    note = col.new_note(model)
    note.fields[0] = (
        "<table>"
        + "".join(f"<tr><td>{{{{c1::answer {i}}}}}</td></tr>" for i in range(10))
        + "</table>"
    )
    col.add_note(note, col.decks.get_current_id())
    yield col, note.cards()[0]
    col.close()


def test_identity_ignores_window_and_flags_but_invalidates_note_edits(collection):
    col, card = collection
    before = card_identity(card), schedule_identity(card, col)
    card.flags = 1
    col.update_card(card)
    assert (card_identity(card), schedule_identity(card, col)) == before
    note = card.note()
    note.fields[0] += " {{c1::new content}}"
    col.update_note(note)
    assert card_identity(card) != before[0]


@pytest.mark.parametrize("ease", [1, 2, 3, 4])
def test_real_native_answer_and_undo_keep_one_revlog_and_restore_round(
    collection, tmp_path, ease
):
    col, card = collection
    store = RecallStore(tmp_path / "recall.sqlite3")
    source, before = card_identity(card), schedule_identity(card, col)
    value = {"known": ["s0"], "history": [[]]}
    store.save(card.id, before, source, "ten", value)
    assert col.db.scalar("select count(*) from revlog") == 0
    card.start_timer()
    col.sched.get_queued_cards()
    answer = col.sched.build_answer(
        card=card, states=col._backend.get_scheduling_states(card.id), rating=ease - 1
    )
    col.sched.answer_card(answer)
    card.load()
    after = schedule_identity(card, col)
    store.advance(
        card.id, after, source, "ten", value, continues_round(answer.new_state)
    )
    assert store.load(card.id, after, source, "ten")["known"] == (
        ["s0"] if continues_round(answer.new_state) else []
    )
    assert col.db.scalar("select count(*) from revlog") == 1
    col.undo()
    card.load()
    assert schedule_identity(card, col) == before
    assert store.load(card.id, before, source, "ten") == value
    assert col.db.scalar("select count(*) from revlog") == 0


def test_mark_reset_and_local_undo_never_answer_or_modify_collection(tmp_path):
    controller = WeakReview.__new__(WeakReview)
    controller.mw = SimpleNamespace(
        pm=SimpleNamespace(profileFolder=lambda: str(tmp_path))
    )
    controller.card_id, controller.schedule, controller.source, controller.manifest = (
        1,
        "s",
        "n",
        "m",
    )
    controller.token = "current"
    controller.slots = [f"s{i}" for i in range(10)]
    controller.value = {"known": [], "history": []}
    controller.publish = Mock()
    controller.current = Mock(return_value=True)
    controller.change(["s0"])
    controller.change(["s0", "s1", "s2", "s3"])
    assert controller.value["known"] == ["s0", "s1", "s2", "s3"]
    controller.reset()
    assert controller.value["known"] == []
    controller.undo_mark()
    assert controller.value["known"] == ["s0", "s1", "s2", "s3"]
    assert not hasattr(controller.mw, "col")


@pytest.mark.parametrize(
    "url",
    [
        "file:///collection.anki2",
        "http://127.0.0.1/private",
        "https://example.com/a.svg",
        "https://mumu-anki-pic.oss-cn-hangzhou.aliyuncs.com.evil.test/card-pic/a.svg",
        "https://mumu-anki-pic.oss-cn-hangzhou.aliyuncs.com/card-pic/a.svg?token=secret",
    ],
)
def test_remote_adapter_cannot_fetch_arbitrary_resources(url):
    with pytest.raises(ValueError):
        image_snapshot(url)


def test_stale_frame_commands_do_not_mutate_marks():
    controller = WeakReview.__new__(WeakReview)
    controller.current = Mock(return_value=False)
    controller.change = Mock()
    controller.receive('{"kind":"mark","token":"old-card","key":"s0","known":true}')
    controller.change.assert_not_called()


def test_all_marked_only_prompts_for_normal_rating(tmp_path, monkeypatch):
    controller = WeakReview.__new__(WeakReview)
    controller.mw = SimpleNamespace(
        pm=SimpleNamespace(profileFolder=lambda: str(tmp_path))
    )
    controller.card_id, controller.schedule, controller.source, controller.manifest = (
        1,
        "s",
        "n",
        "m",
    )
    controller.slots = ["s0"]
    controller.value = {"known": [], "history": []}
    controller.publish = Mock()
    prompt = Mock()
    monkeypatch.setattr("aqt.builtin_features.weak_review.tooltip", prompt)
    controller.change(["s0"])
    prompt.assert_called_once()
    assert "正常评分" in prompt.call_args.args[0]
    assert controller.store.load(1, "s", "n", "m")["known"] == ["s0"]


def test_custom_text_manifest_restores_individual_marks_without_image_fetch(tmp_path):
    controller = WeakReview.__new__(WeakReview)
    controller.mw = SimpleNamespace(
        pm=SimpleNamespace(profileFolder=lambda: str(tmp_path))
    )
    controller.card_id, controller.schedule, controller.source = 1, "s", "n"
    controller.token, controller.pending_manifest = "t", ""
    controller.current = Mock(return_value=True)
    controller.publish = Mock()
    manifest = {
        "adapter": "mumu-text-v1",
        "slots": ['[1,"same","hint"]', '[3,"same","hint"]'],
        "identity": ["question", "version 1"],
    }
    controller.accept_manifest(manifest)
    controller.change(["s1"])
    controller.pending_manifest = ""
    controller.accept_manifest(manifest)
    assert controller.value["known"] == ["s1"]
    controller.accept_manifest(manifest | {"identity": ["question", "version 2"]})
    assert controller.value["known"] == []
