"""Render a saved synthetic report without changing review data or calling AI."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / part) for part in ("qt", "pylib", "out/qt", "out/pylib")]
source, destination = (ROOT / "runtime" / value for value in sys.argv[1:3])
assert source.resolve().parent == (ROOT / "runtime").resolve()
assert destination.resolve().parent == source.resolve().parent
assert (source / ".builtin-test").read_text() == "synthetic data only"
assert not destination.exists()
destination.mkdir()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = str(
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
)

from aqt.builtin_features.weak_review_insights import InsightStore
from aqt.builtin_features.weak_review_report import render_report, write_pdf
from aqt.qt import QApplication

app = QApplication(["report-export", "-platform", "offscreen"])
store = InsightStore(source / "Recall-Test/weak-review.sqlite3")
report = store.reports()[0]
content = render_report(report["snapshot"], report["text"], report["model"])
write_pdf(
    destination / "weak-review-report.pdf", content, "合成数据 · 逐空复习报告样例"
)
(destination / "weak-review-report.html").write_text(content, encoding="utf8")
print(destination, flush=True)
