"""Verify the delivered Windows launcher against an already tested synthetic profile."""

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
base = (ROOT / "runtime" / sys.argv[1]).resolve()
assert base.parent == (ROOT / "runtime").resolve()
assert (base / ".builtin-test").read_text() == "synthetic data only"
for mode in ("write", "verify"):
    assert json.loads((base / f"results-{mode}.json").read_text(encoding="utf8"))[
        "passed"
    ]
package = Path(
    os.environ.get(
        "ANKI_BUILTIN_PACKAGE_ROOT",
        str(ROOT / "dist/Anki-weak-review-tables-26.8.1"),
    )
).resolve()
assert "weak_review" in json.loads(
    (package / "INTEGRATED-BUILD.json").read_text(encoding="utf8")
)


def snapshot():
    profile = base / "Recall-Test"
    with closing(
        sqlite3.connect((profile / "collection.anki2").as_uri() + "?mode=ro", uri=True)
    ) as db:
        cards = db.execute(
            "select id,did,queue,type,due,ivl,reps,lapses from cards order by id"
        ).fetchall()
        history = db.execute("select * from revlog order by id").fetchall()
    with closing(
        sqlite3.connect(
            (profile / "weak-review.sqlite3").as_uri() + "?mode=ro", uri=True
        )
    ) as db:
        marks = db.execute("select * from rounds order by card,schedule").fetchall()
    return cards, history, marks


before = snapshot()
diagnostics = base / "builtin_features/startup-diagnostics.json"
previous = diagnostics.stat().st_mtime_ns if diagnostics.exists() else None
env = os.environ.copy()
env.pop("ANKIDEV", None)
env.pop("ANKI_TEST_MODE", None)
env.update(
    ANKI_BUILTIN_DIAGNOSTICS="1",
    ANKI_BUILTIN_DIAGNOSTICS_EXIT="1",
    ANKI_SINGLE_INSTANCE_KEY="recall-package-" + uuid.uuid4().hex,
    QT_QPA_PLATFORM="offscreen",
    QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu",
    QT_QPA_FONTDIR=str(Path(env.get("WINDIR", "C:/Windows")) / "Fonts"),
    PYTHONUTF8="1",
    PYTHONIOENCODING="utf-8",
)
with (base / "executable.log").open("wb") as log:
    result = subprocess.run(
        [
            str(package / "Anki.exe"),
            "-b",
            str(base),
            "-p",
            "Recall-Test",
            "--safemode",
            "-l",
            "zh_CN",
        ],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        timeout=45,
    )
assert result.returncode == 0, result.returncode
assert diagnostics.stat().st_mtime_ns != previous
report = json.loads(diagnostics.read_text(encoding="utf8"))
assert report["ready"] and report["collection_open"] and not report["developer_mode"]
assert not report["legacy_modules_loaded"]
assert Path(report["synapsepro_source"]).is_relative_to(package)
assert snapshot() == before, "Launcher restart changed scheduling, history or marks"
verification = {
    "passed": True,
    "exit_code": result.returncode,
    "cards": len(before[0]),
    "marks": len(before[2]),
}
(base / "executable-results.json").write_text(json.dumps(verification), encoding="utf8")
print(json.dumps(verification), flush=True)
