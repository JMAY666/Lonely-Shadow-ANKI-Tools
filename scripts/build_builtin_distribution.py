"""Assemble one Windows application from this project's wheels and Qt runtime."""

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
template = Path(sys.argv[1]).resolve()
destination = (root / "dist" / sys.argv[2]).resolve()
assert destination.parent == (root / "dist").resolve()
assert not destination.exists(), "Use a new output name; existing builds are preserved"
assert (template / "Anki.exe").is_file()
wheels = sorted((root / "out/wheels").glob("*.whl"))
assert len(wheels) == 2 and {p.name.split("-")[0] for p in wheels} == {"anki", "aqt"}


def ignore_replaced_packages(directory, names):
    if Path(directory).resolve() == template / "app_packages":
        return [
            n for n in names
            if n in ("aqt", "_aqt", "anki")
            or (n.startswith(("anki-", "aqt-")) and n.endswith(".dist-info"))
        ]
    return [n for n in names if n == "__pycache__"]


shutil.copytree(template, destination, ignore=ignore_replaced_packages)
packages = destination / "app_packages"
for wheel in wheels:
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            target = (packages / member.filename).resolve()
            assert target.is_relative_to(packages)
        archive.extractall(packages)
required = [
    "aqt/builtin_features/weak_review.py",
    "aqt/builtin_features/weak_review_store.py",
    "aqt/builtin_features/weak_review.js",
    "aqt/builtin_features/dual_review.py",
    "aqt/builtin_features/synapsepro/media/dual_review.svg",
    "aqt/builtin_features/desktop_tools/__init__.py",
    "aqt/builtin_features/desktop_tools/renderer.py",
    "aqt/builtin_features/desktop_tools/LICENSE",
    "aqt/builtin_features/desktop_tools/SOURCE.md",
    "aqt/main.py", "aqt/builtin_features/__init__.py",
    "aqt/builtin_features/synapsepro/chat_ui.html",
    "aqt/builtin_features/fsrs_helper/locale/zh_CN.json",
    "aqt/builtin_features/fsrs_helper/python_i18n/i18n/__init__.py",
    "aqt/builtin_features/learning/workspace.py",
    "aqt/builtin_features/learning/provider.py",
    "aqt/builtin_features/protected_secrets.py",
    "aqt/builtin_features/learning/deck_select.py",
    "aqt/builtin_features/learning/review_layout.py",
    "aqt/builtin_features/passfail2/__init__.py",
    "aqt/review_shortcuts.py",
    "aqt/builtin_features/synapsepro/quick_switches.py",
    "aqt/builtin_features/synapsepro/media/quick_switches.svg",
    "_aqt/data/web/js/reviewer-shortcuts.js",
    "aqt/builtin_features/passfail2/LICENSE",
    "aqt/builtin_features/review_tools/__init__.py",
    "aqt/builtin_features/review_tools/SOURCE.md",
    "aqt/builtin_features/review_tools/pace_graph/model.py",
    "aqt/builtin_features/review_tools/search_stats/stats.min.js",
    "aqt/builtin_features/review_tools/search_stats/locale/zh_CN.ftl",
    "aqt/builtin_features/review_tools/search_stats/LICENSE",
    "aqt/builtin_features/review_tools/advanced/LICENSE",
    "aqt/builtin_features/review_tools/LICENSE-answer-feedback",
]
for name in required:
    assert (packages / name).is_file(), name
from verify_web_runtime import verify

verify(packages / "_aqt/data/web/sveltekit")
assert not (destination / "addons21").exists()
manifest = {
    "weak_review": "2: local per-slot recall for native clozes, supported click-to-reveal text and SVG rectangle templates; native learning/relearning boundaries, undo, full test and restart persistence",
    "dual_review": "1: two native review panels, shared scheduler and revlog, exclusive reservations, active-pane shortcuts and audio, global undo, compact tabs",
    "desktop_tools": "Minimize to Tray 2 0.2; AnkiPenDown 1.1; native lifecycle and Simplified Chinese settings",
    "edition": "Anki 26.8.1 with built-in SynapsePro, FSRS Helper and Pass/Fail 2",
    "synapsepro": "1.6.0-local, d7b6c5e20 (DeepSeek changes from 4eed59734)",
    "fsrs_helper": "26.05.08, prepared checkout 85ad582; runtime c7219f5",
    "passfail2": "0.3.0, AnkiWeb archive fb4c98a63d76384204b59cea75702939cc23b6e7f4eb6c73c307b2a810573c4f; native/two-grade mode switching",
    "learning_workspace": "3: resizable deck directory, responsive information cards below study panel, direct native review, searchable statistics scope and confirmed daily DeepSeek suggestions",
    "review_layout": "1: persistent resizable card viewport, legacy iframe resizing and content-sized review controls",
    "review_shortcuts": "1: question-only Space/Enter, two-grade 1=Fail/2=Pass, scoped input and stale-event protection",
    "experience_fixes": "2026-09-12: quick switches, optional review toolbar, visible-card audio gating, incremental deck interactions, SoundCloud playlist-loop API handling (live end-to-end playback unverified)",
    "review_tools": "2026-09-11: Pace Graph, Button Colours, Search Stats Extended, Advanced Review Bottom Bar 3.6.1, Show Answer Button Pressed, Confident But Wrong; exact archive hashes in review_tools/SOURCE.md",
    "wheels": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in wheels},
    "runtime": "Existing Anki 26.8.1 Windows Python/Qt launcher and dependencies",
}
(destination / "INTEGRATED-BUILD.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8")
print(destination, flush=True)
