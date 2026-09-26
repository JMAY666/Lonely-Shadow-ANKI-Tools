# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Scheduling owned by the partial-recall round, committed as one native answer."""

from __future__ import annotations

import math

from anki.scheduler_pb2 import CardAnswer, SchedulingState

from .weak_review_insights import burden, slot_scores

POLICY_VERSION = 2


def round_plan(
    value: dict,
    slots: list[str],
    events: list[dict],
    now: int,
    maximum_days: int = 36500,
    native_baseline: dict | None = None,
) -> dict:
    counts = value.get("attempts", {})
    effort = burden(counts, value["known"])
    current = {
        "session": value.get("session", "current"),
        "attempts": counts,
        "known": slots,
    }
    scores = slot_scores(events + [current], slots)
    risks = [row["score"] for row in scores.values()]
    recent = 0.6 * sum(risks) / len(risks) + 0.4 * max(risks) if risks else 0
    quality = (
        round(0.75 * (100 - effort["score"]) + 0.25 * (100 - 100 * recent))
        if counts
        else 50
    )
    previous = next(
        (
            event
            for event in reversed(events)
            if event.get("completed") and event.get("next_days", 0) > 0
        ),
        native_baseline,
    )
    days = 3 if quality >= 90 else 2 if quality >= 70 else 1
    if previous:
        interval = previous["next_days"]
        factor = (
            2.0
            if quality >= 90
            else 1.5
            if quality >= 70
            else 1.0
            if quality >= 40
            else 0.6
        )
        # Repeated/early self-tests cannot inflate an interval without a delayed
        # retrieval. Failures can still shorten it.
        if now - previous["at"] < max(86400, interval * 86400 * 0.7):
            factor = min(1, factor)
        days = max(1, math.floor(interval * factor + 0.5))
        # Widespread forgetting starts a short consolidation interval again.
        # An isolated hard blank can instead be handled by focused slot practice.
        retried = sum(count > 1 for count in counts.values())
        if slots and retried * 2 >= len(slots):
            days = min(days, 1 if quality < 40 else 3)
    return {
        "policy_version": POLICY_VERSION,
        "quality": max(0, min(100, quality)),
        "next_days": min(max(1, maximum_days), days),
        "loop_seconds": 60 * min(5, max(1, math.ceil(effort["peak"] / 2))),
        "peak": effort["peak"],
        "mean": effort["mean"],
        "completed": bool(slots) and set(value["known"]) == set(slots),
    }


def _review_basis(
    state: SchedulingState, initial_ease: float
) -> SchedulingState.Review:
    kind = state.normal.WhichOneof("kind")
    review = SchedulingState.Review(ease_factor=initial_ease)
    if kind == "review":
        review.CopyFrom(state.normal.review)
    elif kind == "relearning":
        review.CopyFrom(state.normal.relearning.review)
    return review


def _memory(state: SchedulingState):
    kind = state.normal.WhichOneof("kind")
    owner = (
        state.normal.relearning.learning
        if kind == "relearning"
        else getattr(state.normal, kind or "learning")
    )
    return (
        owner.memory_state
        if "memory_state" in owner.DESCRIPTOR.fields_by_name
        and owner.HasField("memory_state")
        else None
    )


def apply_round_schedule(
    answer: CardAnswer, plan: dict, initial_ease: float = 2.5
) -> None:
    """Preserve the scheduler's current-state token, memory evidence and undo.

    Good/Again are only storage-compatible success/failure outcomes. This policy,
    not those button intervals or the deck's learning steps, chooses when to return.
    """
    if (
        answer.current_state.WhichOneof("kind") != "normal"
        or answer.new_state.WhichOneof("kind") != "normal"
    ):
        raise ValueError("当前调度状态不支持逐空评分，请使用完整测试。")
    original = SchedulingState()
    original.CopyFrom(answer.new_state)
    next_state = SchedulingState()
    if original.HasField("custom_data"):
        next_state.custom_data = original.custom_data
    memory = _memory(original)
    if plan["completed"]:
        if answer.rating != CardAnswer.GOOD:
            raise ValueError("逐空完成应只提交一次完成记录。")
        basis = _review_basis(original, initial_ease)
        if original.normal.WhichOneof("kind") not in ("review", "relearning"):
            basis = _review_basis(answer.current_state, initial_ease)
        basis.scheduled_days = plan["next_days"]
        basis.elapsed_days = 0
        basis.leeched = False
        if memory is not None:
            basis.memory_state.CopyFrom(memory)
        next_state.normal.review.CopyFrom(basis)
    else:
        if answer.rating != CardAnswer.AGAIN:
            raise ValueError("还有未记住的空，请继续本轮。")
        learning = SchedulingState.Learning(
            remaining_steps=1, scheduled_secs=plan["loop_seconds"]
        )
        if memory is not None:
            learning.memory_state.CopyFrom(memory)
        kind = answer.current_state.normal.WhichOneof("kind")
        if kind in ("review", "relearning"):
            basis = _review_basis(original, initial_ease)
            if original.normal.WhichOneof("kind") not in ("review", "relearning"):
                basis = _review_basis(answer.current_state, initial_ease)
            next_state.normal.relearning.review.CopyFrom(basis)
            next_state.normal.relearning.learning.CopyFrom(learning)
        else:
            next_state.normal.learning.CopyFrom(learning)
    answer.new_state.CopyFrom(next_state)
