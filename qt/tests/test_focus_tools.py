# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import hashlib
import json
from pathlib import Path

import pytest

from aqt.builtin_features.synapsepro import background_music, constants, pomodoro


@pytest.fixture
def timer(monkeypatch):
    for key, value in {
        "current_state": constants.STATE_IDLE,
        "previous_state": constants.STATE_IDLE,
        "intended_next_state": constants.STATE_WORK,
        "pomodoros_completed_cycle": 0,
        "pomodoros_target": 4,
        "work_duration": 2700,
        "short_break_duration": 300,
        "long_break_duration": 900,
        "time_remaining": 2700,
        "sound_work_end": "",
        "sound_break_end": "",
        "_update_ui_callback": None,
        "mw": None,
    }.items():
        monkeypatch.setattr(pomodoro, key, value)
    monkeypatch.setattr(pomodoro, "record_pomodoro_completed", lambda: None)
    return pomodoro


def test_cycle_progress_follows_work_break_and_long_break(timer):
    assert timer.get_cycle_progress() == (constants.STATE_WORK, 1, 4)
    for round_number in range(1, 5):
        timer.current_state = constants.STATE_WORK
        assert timer.get_cycle_progress() == (constants.STATE_WORK, round_number, 4)
        timer.handle_state_transition(finished_state=constants.STATE_WORK)
        next_phase = (
            constants.STATE_SHORT_BREAK
            if round_number < 4
            else constants.STATE_LONG_BREAK
        )
        # Includes waiting for the user to start the break, even after the work
        # counter has already been reset for the final long break.
        assert timer.get_cycle_progress() == (next_phase, round_number, 4)
        timer.handle_state_transition(finished_state=next_phase)
    assert timer.get_cycle_progress() == (constants.STATE_WORK, 1, 4)


@pytest.mark.parametrize(
    "phase,completed,expected",
    [
        (constants.STATE_WORK, 2, 3),
        (constants.STATE_SHORT_BREAK, 2, 2),
        (constants.STATE_LONG_BREAK, 0, 4),
    ],
)
def test_paused_phase_keeps_its_round_without_mutating_counts(
    timer, phase, completed, expected
):
    timer.current_state = constants.STATE_PAUSED
    timer.previous_state = phase
    timer.pomodoros_completed_cycle = completed
    assert timer.get_cycle_progress() == (phase, expected, 4)
    assert timer.current_state == constants.STATE_PAUSED
    assert timer.pomodoros_completed_cycle == completed


@pytest.mark.parametrize("target", [1, 6, 10])
def test_progress_uses_configured_target_and_reset_returns_to_first_round(
    timer, target
):
    timer.pomodoros_target = target
    timer.pomodoros_completed_cycle = target - 1
    timer.current_state = constants.STATE_WORK
    assert timer.get_cycle_progress() == (constants.STATE_WORK, target, target)
    timer.handle_state_transition(skipped_state=constants.STATE_WORK)
    assert timer.get_cycle_progress() == (constants.STATE_LONG_BREAK, target, target)
    timer.reset_action()
    assert timer.get_cycle_progress() == (constants.STATE_WORK, 1, target)


def test_added_music_is_complete_attributed_and_preserves_existing_ids():
    media = Path(background_music.__file__).parent / "media"
    tracks = background_music.BUILTIN_TRACKS
    assert [t[0] for t in tracks[:6]] == [
        "alpha_waves.mp3",
        "beta_waves.mp3",
        "library_sounds.mp3",
        "jazz.mp3",
        "rain.mp3",
        "cozy.mp3",
    ]
    assert len(tracks) == len({t[0] for t in tracks}) == 18
    catalog = json.loads((media / "focus/catalog.json").read_text(encoding="utf8"))
    assert {"focus/" + t["file"] for t in catalog} == {t[0] for t in tracks[6:]}
    for filename, _title, cover in tracks:
        assert (media / filename).is_file()
        assert (media / cover).is_file()
    credits = (media / "focus/CREDITS.html").read_text(encoding="utf8")
    for track in catalog:
        assert (
            hashlib.sha256((media / "focus" / track["file"]).read_bytes()).hexdigest()
            == track["sha256"]
        )
        assert track["author"] in credits
        assert track["license_url"] in credits
