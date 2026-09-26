# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Profile-local partial recall; never writes to the Anki collection."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf8")
    ).hexdigest()


def continues_round(state: Any) -> bool:
    # Follow the scheduler's actual result, including custom scheduling/FSRS.
    if state.WhichOneof("kind") != "normal":
        return False
    return state.normal.WhichOneof("kind") in ("learning", "relearning")


class RecallStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.execute(
            "create table if not exists rounds (card integer, schedule text, "
            "source text, manifest text, value text, primary key(card,schedule))"
        )
        db.execute(
            "create table if not exists recall_visits (card integer, schedule text, "
            "source text, manifest text, value text, primary key(card,schedule,source,manifest))"
        )
        return db

    def load(self, card: int, schedule: str, source: str, manifest: str) -> dict:
        with closing(self._connect()) as db:
            row = db.execute(
                "select source,manifest,value from recall_visits where card=? and schedule=? and source=? and manifest=?",
                (card, schedule, source, manifest),
            ).fetchone()
            if row is None:
                row = db.execute(
                    "select source,manifest,value from rounds where card=? and schedule=?",
                    (card, schedule),
                ).fetchone()
        if row and row[:2] == (source, manifest):
            value = json.loads(row[2])
            if (
                isinstance(value, dict)
                and isinstance(value.get("known"), list)
                and all(isinstance(key, str) for key in value["known"])
                and isinstance(value.get("history"), list)
                and all(
                    isinstance(step, list) and all(isinstance(key, str) for key in step)
                    for step in value["history"]
                )
            ):
                return value
            raise ValueError("逐空标记文件格式异常")
        return {"known": [], "history": []}

    def save(
        self, card: int, schedule: str, source: str, manifest: str, value: dict
    ) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "insert into recall_visits values(?,?,?,?,?) on conflict(card,schedule,source,manifest) "
                "do update set value=excluded.value",
                (card, schedule, source, manifest, json.dumps(value)),
            )
            # Native undo/redo restores the old schedule key and thus the old round.
            # Keep more versions than Anki's undo limit, without growing indefinitely.
            db.execute(
                "delete from recall_visits where card=? and rowid not in "
                "(select rowid from recall_visits where card=? order by rowid desc limit 64)",
                (card, card),
            )

    def advance(
        self,
        card: int,
        schedule: str,
        source: str,
        manifest: str,
        value: dict,
        continuing: bool,
    ) -> None:
        self.save(
            card,
            schedule,
            source,
            manifest,
            value if continuing else {"known": [], "history": []},
        )
