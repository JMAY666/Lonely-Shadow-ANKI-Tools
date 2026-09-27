# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import aqt
from anki.collection import OpChanges
from anki.decks import DeckId, DeckTreeNode
from aqt.deckbrowser import DeckBrowser
from aqt.main import AnkiQt
from aqt.operations import CollectionOp


@pytest.fixture
def selection(monkeypatch):
    jobs, timers, saved = [], [], []
    clock = [100.0]
    current = [1]
    tree = DeckTreeNode(
        children=[
            DeckTreeNode(deck_id=i, name=f"Deck {i}", new_count=i) for i in range(1, 5)
        ]
    )
    col = Mock()
    col.decks.get_current_id.side_effect = lambda: DeckId(current[0])
    col.decks.current.side_effect = lambda: {
        "id": current[0],
        "name": f"Deck {current[0]}",
    }
    col.sched.deck_due_tree.side_effect = lambda: tree
    col.studied_today.return_value = "today"
    col.v3_scheduler.return_value = True
    col.op_made_changes.return_value = False

    def save(did):
        saved.append(did)
        current[0] = did
        return OpChanges(config=True)

    col.decks.set_current.side_effect = save
    taskman = Mock()
    taskman.run_in_background.side_effect = lambda op, done, **kwargs: jobs.append(
        (op, done)
    )
    mw = SimpleNamespace(
        col=col,
        taskman=taskman,
        web=Mock(),
        bottomWeb=Mock(),
        state="deckBrowser",
        _increase_background_ops=Mock(),
        _decrease_background_ops=Mock(),
        update_undo_actions=Mock(),
    )
    monkeypatch.setattr(aqt, "mw", mw)
    monkeypatch.setattr("aqt.deckbrowser.BottomBar", Mock())
    monkeypatch.setattr(
        "aqt.deckbrowser.QTimer.singleShot", lambda ms, fn: timers.append(fn)
    )
    monkeypatch.setattr("aqt.deckbrowser.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "aqt.builtin_features.learning.deck_page.render_page",
        lambda browser, content: str(browser._render_data.current_deck_id),
    )
    hook = Mock()
    monkeypatch.setattr(aqt.gui_hooks, "operation_did_execute", hook)
    browser = DeckBrowser(mw)
    browser._DeckBrowser__renderPage = Mock()
    mw.deckBrowser = browser

    def run_job():
        op, done = jobs.pop(0)
        future = Future()
        try:
            future.set_result(op())
        except Exception as exc:
            future.set_exception(exc)
        done(future)

    def fire_timers():
        while timers:
            timers.pop(0)()

    def drain():
        for _ in range(20):
            fire_timers()
            if not jobs:
                return
            run_job()
        pytest.fail("selection queue did not settle")

    browser.refresh()
    drain()
    col.sched.deck_due_tree.reset_mock()
    col.studied_today.reset_mock()
    return SimpleNamespace(
        browser=browser,
        mw=mw,
        col=col,
        jobs=jobs,
        saved=saved,
        clock=clock,
        tree=tree,
        hook=hook,
        run_job=run_job,
        fire_timers=fire_timers,
        drain=drain,
    )


def test_fast_clicks_save_only_the_latest_choice_without_a_modal(selection):
    s = selection
    for did in (2, 3, 4):
        s.browser.set_current_deck(DeckId(did))
    s.drain()
    assert s.saved == [4]
    assert s.browser._render_data.current_deck_id == 4
    assert not s.browser.selection_pending
    s.mw.taskman.with_progress.assert_not_called()
    s.hook.assert_called_once_with(OpChanges(config=True), s.browser)
    s.col.sched.deck_due_tree.assert_not_called()
    s.col.studied_today.assert_not_called()


def test_clicks_while_database_is_busy_do_not_accumulate_or_save_stale_choices(
    selection,
):
    s = selection
    s.browser.set_current_deck(DeckId(2))
    s.fire_timers()
    for did in (3, 2, 4):
        s.browser.set_current_deck(DeckId(did))
        s.fire_timers()
    assert len(s.jobs) == 1
    s.drain()
    assert s.saved == [4]
    assert s.browser._render_data.current_deck_id == 4


def test_old_read_cannot_replace_the_latest_panel(selection):
    s = selection
    s.browser.set_current_deck(DeckId(2))
    s.fire_timers()
    s.run_job()  # mutation complete, read queued
    s.browser.set_current_deck(DeckId(3))
    s.run_job()  # old read must not update UI
    assert s.browser._render_data.current_deck_id == 1
    s.drain()
    assert s.browser._render_data.current_deck_id == 3


@pytest.mark.parametrize("fail_read", [False, True])
def test_failed_switch_disables_study_and_can_be_retried(selection, fail_read):
    s = selection
    if fail_read:
        s.col.decks.current.side_effect = RuntimeError("read unavailable")
    else:
        original = s.col.decks.set_current.side_effect
        s.col.decks.set_current.side_effect = RuntimeError("save unavailable")
    s.browser.set_current_deck(DeckId(2))
    s.drain()
    assert s.browser.selection_pending
    assert "_deckSelectionFailed" in s.mw.web.eval.call_args.args[0]
    s.browser.start_review(DeckId(1))
    assert not s.browser._starting_review
    if fail_read:
        s.col.decks.current.side_effect = lambda: {"id": 2, "name": "Deck 2"}
    else:
        s.col.decks.set_current.side_effect = original
    s.browser.set_current_deck(DeckId(2))
    s.drain()
    assert not s.browser.selection_pending
    assert s.browser._render_data.current_deck_id == 2


def test_navigation_cancels_a_queued_selection(selection):
    s = selection
    s.browser.set_current_deck(DeckId(2))
    s.fire_timers()
    s.mw.state = "review"
    s.drain()
    assert s.saved == []
    assert not s.browser.selection_pending


def test_pending_selection_blocks_study_shortcut_and_old_panel_actions(selection):
    s = selection
    s.browser.set_current_deck(DeckId(2))
    s.mw.moveToState = Mock()
    AnkiQt.onStudyKey(s.mw)
    s.mw.moveToState.assert_not_called()
    s.browser.start_review = Mock()
    s.browser._linkHandler("open:1")
    s.browser.start_review.assert_not_called()


def test_expired_counts_refresh_without_rebuilding_the_directory(selection):
    s = selection
    s.clock[0] += 3
    s.col.sched.deck_due_tree.side_effect = lambda: DeckTreeNode(
        children=[
            DeckTreeNode(deck_id=i, name=f"Deck {i}", new_count=9) for i in range(1, 5)
        ]
    )
    s.browser._DeckBrowser__renderPage.reset_mock()
    s.browser.set_current_deck(DeckId(2))
    s.drain()
    assert s.browser._render_data.tree.children[1].new_count == 9
    s.col.sched.deck_due_tree.assert_called_once()
    s.browser._DeckBrowser__renderPage.assert_not_called()


def test_study_changes_invalidate_cached_counts(selection):
    s = selection
    s.browser.op_executed(OpChanges(study_queues=True), None, False)
    s.browser.set_current_deck(DeckId(2))
    s.drain()
    s.col.sched.deck_due_tree.assert_called_once()


def test_directory_changes_require_a_full_render(selection):
    s = selection
    s.clock[0] += 3
    s.col.sched.deck_due_tree.side_effect = lambda: DeckTreeNode(
        children=[DeckTreeNode(deck_id=2, name="Renamed")]
    )
    s.browser._DeckBrowser__renderPage.reset_mock()
    s.browser.set_current_deck(DeckId(2))
    s.drain()
    s.browser._DeckBrowser__renderPage.assert_called_once()


def test_other_collection_operations_keep_their_progress_dialog(selection):
    s = selection
    CollectionOp(s.mw, lambda col: OpChanges()).run_in_background()
    s.mw.taskman.with_progress.assert_called_once()


def test_late_study_click_cannot_reopen_the_previous_deck(selection):
    s = selection
    s.browser.set_current_deck(DeckId(2))
    s.drain()
    s.browser.start_review = Mock()
    s.browser._linkHandler("open:1")
    s.browser.start_review.assert_not_called()
    s.browser._linkHandler("open:2")
    s.browser.start_review.assert_called_once_with(DeckId(2))


def test_full_refresh_recovers_after_a_failed_selection(selection):
    s = selection
    s.col.decks.set_current.side_effect = RuntimeError("save unavailable")
    s.browser.set_current_deck(DeckId(2))
    s.drain()
    assert s.browser.selection_pending
    s.browser.refresh()
    s.drain()
    assert not s.browser.selection_pending
    assert s.browser._render_data.current_deck_id == 1
