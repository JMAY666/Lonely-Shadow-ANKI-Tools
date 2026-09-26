# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Local, reversible observations of recall; independent of native scheduling."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from .weak_review_store import RecallStore, digest


def begin_visit(value: dict, schedule: str, slots: list[str]) -> dict:
    """A scheduling visit counts once, even across rerenders and restarts."""
    if value.get("visit") == schedule:
        return value
    value = dict(value)
    value.setdefault("session", schedule)
    counts = dict(value.get("attempts", {}))
    tested = [key for key in slots if key not in value["known"]]
    for key in tested:
        counts[key] = counts.get(key, 0) + 1
    value.update(visit=schedule, attempts=counts, tested=tested)
    return value


def burden(attempts: dict[str, int], known: list[str]) -> dict:
    counts = list(attempts.values())
    if not counts:
        return {"score": 0, "peak": 0, "mean": 0}
    mean, peak = sum(counts) / len(counts), max(counts)
    # This is a transparent local heuristic, not an FSRS difficulty estimate.
    score = round(100 * min(1, 0.6 * (mean - 1) / 3 + 0.4 * (peak - 1) / 3))
    return {
        "score": score,
        "peak": peak,
        "mean": round(mean, 2),
    }


def level(score: float) -> str:
    return "重点" if score >= 0.6 else "留意" if score >= 0.25 else "普通"


def slot_scores(events: list[dict], slots: list[str]) -> dict[str, dict]:
    """One sample per recall round; a good new round can retire an old weakness."""
    rounds: dict[str, dict] = {}
    for event in events:
        rounds[event["session"]] = event
    result = {}
    for key in slots:
        score = 0.0
        samples: list[int] = []
        for event in rounds.values():
            count = event["attempts"].get(key, 0)
            if not count:
                continue
            sample = min(1.0, (count - 1) / 3)
            if key not in event["known"]:
                sample = max(sample, 0.65)
            score = sample if not samples else 0.65 * sample + 0.35 * score
            samples.append(count)
        result[key] = {
            "score": round(score, 4),
            "level": level(score),
            "rounds": len(samples),
            "last_attempts": samples[-1] if samples else 0,
            "total_attempts": sum(samples),
        }
    return result


def practice_interval(score: float, remembered: bool, previous: int = 0) -> int:
    if not remembered:
        return 10 * 60
    initial = 86400 if score >= 0.6 else 3 * 86400
    return min(30 * 86400, max(initial, previous * 2))


class InsightStore(RecallStore):
    def _connect(self):
        db = super()._connect()
        db.executescript(
            "create table if not exists recall_catalog (card integer primary key, "
            "source text, manifest text, metadata text);"
            "create table if not exists recall_events (revlog integer primary key, "
            "card integer, source text, manifest text, data text);"
            "create index if not exists recall_event_card on recall_events(card);"
            "create table if not exists recall_assets (hash text primary key, data text);"
            "create table if not exists recall_practice (id integer primary key, "
            "card integer, source text, manifest text, slot text, data text);"
            "create table if not exists recall_reports (id text primary key, data text);"
        )
        return db

    def catalog(
        self,
        card: int,
        source: str,
        manifest: str,
        metadata: dict,
        asset: tuple[str, str] | None = None,
    ) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "insert or replace into recall_catalog values(?,?,?,?)",
                (card, source, manifest, json.dumps(metadata)),
            )
            if asset:
                db.execute("insert or ignore into recall_assets values(?,?)", asset)

    def asset(self, key: str) -> str | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "select data from recall_assets where hash=?", (key,)
            ).fetchone()
        return row[0] if row else None

    def record(
        self, card: int, source: str, manifest: str, revlog: int, data: dict
    ) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "insert or replace into recall_events values(?,?,?,?,?)",
                (revlog, card, source, manifest, json.dumps(data)),
            )

    def events(
        self, card: int, source: str, manifest: str, valid_ids: set[int]
    ) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "select revlog,data from recall_events where card=? and source=? "
                "and manifest=? order by revlog",
                (card, source, manifest),
            ).fetchall()
        # Undo removes the native revlog; redo restores it. Do not erase local
        # evidence, and never count an undone native answer in a report.
        return [json.loads(data) for revlog, data in rows if revlog in valid_ids]

    def catalogs(self) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "select card,source,manifest,metadata from recall_catalog"
            ).fetchall()
        return [
            dict(card=c, source=s, manifest=m, **json.loads(data))
            for c, s, m, data in rows
        ]

    def practices(self, card: int, source: str, manifest: str, key: str) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "select data from recall_practice where card=? and source=? and manifest=? "
                "and slot=? order by id",
                (card, source, manifest, key),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def practice(self, item: dict, remembered: bool, now: int) -> int:
        previous = self.practices(
            item["card"], item["source"], item["manifest"], item["key"]
        )
        interval = practice_interval(
            item["score"], remembered, previous[-1]["interval"] if previous else 0
        )
        data = {
            "at": now,
            "remembered": remembered,
            "interval": interval,
            "due": now + interval,
        }
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "insert into recall_practice(card,source,manifest,slot,data) values(?,?,?,?,?)",
                (
                    item["card"],
                    item["source"],
                    item["manifest"],
                    item["key"],
                    json.dumps(data),
                ),
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    def undo_practice(self, row_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute("delete from recall_practice where id=?", (row_id,))

    def save_report(self, snapshot: dict, text: str, model: str) -> None:
        row = {"snapshot": snapshot, "text": text, "model": model}
        with closing(self._connect()) as db, db:
            db.execute(
                "insert or replace into recall_reports values(?,?)",
                (digest(snapshot), json.dumps(row)),
            )

    def reports(self) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "select data from recall_reports order by rowid desc limit 100"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]


def collect_items(
    col: Any,
    store: InsightStore,
    deck_ids: set[int],
    now: int,
    day: tuple[int, int] | None = None,
) -> list[dict]:
    from .weak_review import card_identity

    start = (
        datetime.fromtimestamp(now, timezone.utc)
        .astimezone()
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    daily_window = day or (
        int(start.timestamp()),
        int((start + timedelta(days=1)).timestamp()),
    )
    items = []
    for catalog in store.catalogs():
        cid = catalog["card"]
        # Deleted cards, changed content, filtered/suspended cards must not be
        # silently resurrected as independent practice targets.
        row = col.db.first("select did,odid,queue from cards where id=?", cid)
        if not row or row[0] not in deck_ids or row[1] or row[2] < 0:
            continue
        card = col.get_card(cid)
        if card_identity(card) != catalog["source"]:
            continue
        valid = set(col.db.list("select id from revlog where cid=?", cid))
        events = store.events(cid, catalog["source"], catalog["manifest"], valid)
        if day is not None:
            events = [event for event in events if event["at"] < day[1]]
        keys = [slot["key"] for slot in catalog["slots"]]
        scores = slot_scores(events, keys)
        for slot in catalog["slots"]:
            key = slot["key"]
            relevant = [e for e in events if key in e.get("tested", [])]
            today = [
                e for e in relevant if daily_window[0] <= e["at"] < daily_window[1]
            ]
            stats = scores[key]
            practices = store.practices(
                cid, catalog["source"], catalog["manifest"], key
            )
            if day is not None:
                practices = [p for p in practices if p["at"] < day[1]]
            daily_practices = [
                p for p in practices if daily_window[0] <= p["at"] < daily_window[1]
            ]
            if day is not None and not today and not daily_practices:
                continue
            # Fold only exercises after the latest native observation. A later
            # native recall replaces that older local exercise evidence.
            score = stats["score"]
            last_native = max((e["at"] for e in relevant), default=0)
            successes = 0
            for practice in practices:
                if practice["at"] > last_native:
                    score = 0.35 * score + (0 if practice["remembered"] else 0.65)
                    successes = successes + 1 if practice["remembered"] else 0
            score = round(score, 4)
            latest = max(relevant, key=lambda e: e["at"], default={"at": now})
            if practices and practices[-1]["at"] > last_native:
                due = practices[-1]["due"]
            else:
                due = latest["at"] + (600 if score >= 0.6 else 6 * 3600)
            # Daily reports retain today's struggled items even when later
            # learning in the day improved their current score.
            daily_failed = sum(key not in e["known"] for e in today)
            practice_failed = sum(not p["remembered"] for p in daily_practices)
            pending_confirmation = bool(
                practices and practices[-1]["at"] > last_native and successes < 2
            )
            if (
                score < 0.25
                and not pending_confirmation
                and not (day is not None and (daily_failed or practice_failed))
            ):
                continue
            items.append(
                {
                    **slot,
                    **stats,
                    "score": score,
                    "level": level(score),
                    "card": cid,
                    "source": catalog["source"],
                    "manifest": catalog["manifest"],
                    "deck": col.decks.name(card.did),
                    "asset": catalog.get("asset"),
                    "day_attempts": len(today),
                    "day_misses": daily_failed,
                    "day_practices": len(daily_practices),
                    "day_practice_misses": practice_failed,
                    "pending_confirmation": pending_confirmation,
                    "round_quality": events[-1].get("quality")
                    if events and events[-1].get("completed")
                    else None,
                    "card_next_days": events[-1].get("next_days")
                    if events and events[-1].get("completed")
                    else None,
                    "due": due,
                    "overdue": due <= now,
                }
            )
    return sorted(
        items, key=lambda item: (-item["score"], item["due"], item["card"], item["key"])
    )


def report_batches(items: list[dict], limit: int = 14000) -> list[list[dict]]:
    """Include every selected slot, with no silent top-N truncation."""
    batches: list[list[dict]] = []
    batch: list[dict] = []
    size, images = 0, 0
    for item in items:
        public = {
            k: item[k]
            for k in (
                "card",
                "key",
                "deck",
                "answer",
                "context",
                "score",
                "level",
                "last_attempts",
                "total_attempts",
                "rounds",
                "day_attempts",
                "day_misses",
            )
        }
        public["image_region"] = bool(item.get("asset"))
        public["day_practices"] = item.get("day_practices", 0)
        public["day_practice_misses"] = item.get("day_practice_misses", 0)
        public["round_quality"] = item.get("round_quality")
        public["card_next_days"] = item.get("card_next_days")
        count = len(json.dumps(public, ensure_ascii=False))
        if batch and (size + count > limit or images + bool(item.get("asset")) > 4):
            batches.append(batch)
            batch, size, images = [], 0, 0
        batch.append(public)
        size += count
        images += bool(item.get("asset"))
    if batch:
        batches.append(batch)
    return batches
