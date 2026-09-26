set windows-shell := ["pwsh", "-NoLogo", "-NoProfileLoadTime", "-Command"]

mod release

# Show available commands
default:
    @just --list

focus-music-assets:
    & "out/pyenv/Scripts/python.exe" scripts/focus_music_assets.py

focus-tools-test:
    $env:QT_QPA_PLATFORM="offscreen"; $env:PYTHONPATH="qt;pylib;out/qt;out/pylib"; & "out/pyenv/Scripts/pytest.exe" -p no:cacheprovider qt/tests/test_focus_tools.py

focus-tools-smoke run_name:
    $env:QT_QPA_PLATFORM="offscreen"; & "out/pyenv/Scripts/python.exe" scripts/focus_tools_smoke.py {{run_name}}

focus-tools-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix scripts/focus_music_assets.py scripts/focus_tools_smoke.py qt/tests/test_focus_tools.py
    & "out/pyenv/Scripts/ruff.exe" format scripts/focus_music_assets.py scripts/focus_tools_smoke.py qt/tests/test_focus_tools.py

weak-review-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/builtin_features/weak_review.py qt/aqt/builtin_features/weak_review_store.py qt/aqt/reviewer.py qt/tests/test_weak_review.py scripts/weak_review_smoke.py scripts/weak_review_package_check.py scripts/weak_review_fixtures.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/builtin_features/weak_review.py qt/aqt/builtin_features/weak_review_store.py qt/aqt/reviewer.py qt/tests/test_weak_review.py scripts/weak_review_smoke.py scripts/weak_review_package_check.py scripts/weak_review_fixtures.py
    & "node_modules/.bin/dprint.cmd" fmt qt/aqt/builtin_features/weak_review.js README.md docs/WEAK-REVIEW.md

weak-review-test:
    $env:QT_QPA_PLATFORM="offscreen"; $env:PYTHONPATH="qt;pylib;out/qt;out/pylib"; & "out/pyenv/Scripts/pytest.exe" -p no:cacheprovider qt/tests/test_weak_review.py qt/tests/test_review_undo.py qt/tests/test_review_shortcuts.py qt/tests/test_review_layout.py qt/tests/test_dual_review_api.py

weak-insights-test:
    $env:QT_QPA_PLATFORM="offscreen"; $env:PYTHONPATH="qt;pylib;out/qt;out/pylib"; & "out/pyenv/Scripts/pytest.exe" -p no:cacheprovider qt/tests/test_weak_review_schedule.py qt/tests/test_weak_review_insights.py qt/tests/test_weak_review.py qt/tests/test_ai_images.py qt/tests/test_review_undo.py qt/tests/test_review_shortcuts.py qt/tests/test_dual_review_api.py

weak-insights-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/builtin_features/weak_review*.py qt/aqt/builtin_features/passfail2/__init__.py qt/tests/test_weak_review*.py scripts/weak_insights_smoke.py scripts/weak_insights_export.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/builtin_features/weak_review*.py qt/aqt/builtin_features/passfail2/__init__.py qt/tests/test_weak_review*.py scripts/weak_insights_smoke.py scripts/weak_insights_export.py
    & "node_modules/.bin/dprint.cmd" fmt qt/aqt/builtin_features/weak_review.js README.md docs/WEAK-REVIEW.md

weak-insights-smoke run_name:
    $env:QT_QPA_PLATFORM="offscreen"; & "out/pyenv/Scripts/python.exe" scripts/weak_insights_smoke.py {{run_name}}
    $env:QT_QPA_PLATFORM="offscreen"; & "out/pyenv/Scripts/python.exe" scripts/weak_insights_smoke.py {{run_name}} verify

weak-insights-export source_name output_name:
    & "out/pyenv/Scripts/python.exe" scripts/weak_insights_export.py {{source_name}} {{output_name}}

weak-review-smoke run_name:
    $env:QT_QPA_PLATFORM="offscreen"; & "out/pyenv/Scripts/python.exe" scripts/weak_review_smoke.py {{run_name}}
    $env:QT_QPA_PLATFORM="offscreen"; & "out/pyenv/Scripts/python.exe" scripts/weak_review_smoke.py {{run_name}} verify

weak-review-package-check run_name:
    & "out/pyenv/Scripts/python.exe" scripts/weak_review_package_check.py {{run_name}}

ai-images-test:
    $env:QT_QPA_PLATFORM="offscreen"; $env:PYTHONPATH="qt;pylib;out/qt;out/pylib"; & "out/pyenv/Scripts/pytest.exe" -p no:cacheprovider qt/tests/test_ai_images.py
    & "out/pyenv/Scripts/python.exe" scripts/builtin_tests.py test_ai_and_removal.py

ai-images-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/reviewer.py qt/tests/test_ai_images.py scripts/ai_images_smoke.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/reviewer.py qt/tests/test_ai_images.py scripts/ai_images_smoke.py
    & "out/pyenv/Scripts/ruff.exe" check --no-force-exclude --select E9,F,I --fix qt/aqt/builtin_features/synapsepro/ai_images.py
    & "out/pyenv/Scripts/ruff.exe" format --no-force-exclude qt/aqt/builtin_features/synapsepro/ai_images.py

ai-images-smoke run_name:
    $env:QT_QPA_PLATFORM="offscreen"; & "out/pyenv/Scripts/python.exe" scripts/ai_images_smoke.py {{run_name}}

ai-images-native-smoke run_name:
    $env:QT_QPA_PLATFORM="windows"; $env:ANKI_AI_NATIVE_CAPTURE="1"; & "out/pyenv/Scripts/python.exe" scripts/ai_images_smoke.py {{run_name}}

review-undo-test:
    $env:PYTHONPATH="qt;pylib;out/qt;out/pylib"; & "out/pyenv/Scripts/pytest.exe" -p no:cacheprovider qt/tests/test_review_undo.py

review-undo-smoke run_name:
    $env:QT_QPA_PLATFORM="offscreen"; & "out/pyenv/Scripts/python.exe" scripts/review_undo_smoke.py {{run_name}}

review-undo-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/reviewer.py qt/tests/test_review_undo.py scripts/review_undo_smoke.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/reviewer.py qt/tests/test_review_undo.py scripts/review_undo_smoke.py
    & "node_modules/.bin/dprint.cmd" fmt README.md docs/REVIEW-UNDO.md

dual-review-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/tests/test_dual_review_api.py scripts/dual_review_package_check.py
    & "out/pyenv/Scripts/ruff.exe" format qt/tests/test_dual_review_api.py scripts/dual_review_package_check.py qt/aqt/builtin_features/desktop_tools/__init__.py qt/aqt/toolbar.py qt/tests/test_toolbar.py
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/builtin_features/dual_review.py qt/aqt/reviewer.py qt/aqt/review_shortcuts.py qt/aqt/mediasrv.py qt/tests/test_review_shortcuts.py scripts/dual_review_smoke.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/builtin_features/dual_review.py qt/aqt/reviewer.py qt/aqt/review_shortcuts.py qt/aqt/mediasrv.py qt/aqt/main.py qt/aqt/editcurrent.py qt/aqt/editcurrent_legacy.py qt/aqt/builtin_features/learning/workspace.py qt/aqt/builtin_features/learning/review_layout.py qt/aqt/builtin_features/review_tools/feedback.py qt/aqt/builtin_features/review_tools/config.py qt/aqt/builtin_features/passfail2/__init__.py qt/tests/test_experience.py qt/tests/test_review_shortcuts.py scripts/dual_review_smoke.py
    {{ ninja }} format:rust

dual-review-smoke run_name:
    $env:QT_QPA_PLATFORM="offscreen"; & "out/pyenv/Scripts/python.exe" scripts/dual_review_smoke.py {{run_name}}

dual-review-test:
    {{ ninja }} check:rust_test
    $env:PYTHONPATH="qt;pylib;out/qt;out/pylib"; & "out/pyenv/Scripts/pytest.exe" -p no:cacheprovider qt/tests/test_dual_review_api.py qt/tests/test_review_shortcuts.py qt/tests/test_review_layout.py qt/tests/test_experience.py qt/tests/test_toolbar.py

dual-review-package-check run_name:
    & "out/pyenv/Scripts/python.exe" scripts/dual_review_package_check.py {{run_name}}

deck-workspace-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix scripts/deck_workspace_smoke.py qt/aqt/builtin_features/learning/deck_page.py
    & "out/pyenv/Scripts/ruff.exe" format scripts/deck_workspace_smoke.py qt/aqt/builtin_features/learning/deck_page.py
    & "node_modules/.bin/dprint.cmd" fmt qt/aqt/data/web/js/deckbrowser.ts README.md docs/DECK-WORKSPACE-LAYOUT.md

deck-workspace-smoke run_name mode="write":
    & "out/pyenv/Scripts/python.exe" scripts/deck_workspace_smoke.py {{run_name}} {{mode}}

desktop-tools-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/builtin_features/desktop_tools qt/tests/test_desktop_tools.py scripts/desktop_tools_smoke.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/builtin_features/desktop_tools qt/tests/test_desktop_tools.py scripts/desktop_tools_smoke.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/about.py qt/aqt/main.py
    & "node_modules/.bin/dprint.cmd" fmt qt/aqt/builtin_features/desktop_tools/SOURCE.md docs/DESKTOP-TOOLS.md README.md BUILTIN-FEATURES.md

desktop-tools-test:
    $env:PYTHONPATH="qt;pylib;out/qt;out/pylib"; & "out/pyenv/Scripts/pytest.exe" -p no:cacheprovider qt/tests/test_desktop_tools.py

desktop-tools-check:
    & "out/pyenv/Scripts/ruff.exe" check qt/aqt/builtin_features/desktop_tools qt/tests/test_desktop_tools.py scripts/desktop_tools_smoke.py
    & "out/pyenv/Scripts/mypy.exe" --follow-imports=silent qt/aqt/builtin_features/desktop_tools

desktop-tools-smoke run_name mode="write":
    & "out/pyenv/Scripts/python.exe" scripts/desktop_tools_smoke.py {{run_name}} {{mode}}

experience-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix scripts/experience_soundcloud.py
    & "out/pyenv/Scripts/ruff.exe" format scripts/experience_soundcloud.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/builtin_features/passfail2/__init__.py
    & "out/pyenv/Scripts/ruff.exe" format --no-force-exclude qt/aqt/builtin_features/synapsepro/quick_switches.py
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/reviewer.py qt/aqt/deckbrowser.py qt/aqt/builtin_features/learning/workspace.py qt/aqt/builtin_features/synapsepro/quick_switches.py qt/tests/test_experience.py scripts/experience_smoke.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/reviewer.py qt/aqt/deckbrowser.py qt/aqt/builtin_features/learning/workspace.py qt/aqt/builtin_features/synapsepro/quick_switches.py qt/tests/test_experience.py scripts/experience_smoke.py
    & "node_modules/.bin/dprint.cmd" fmt ts/reviewer/index.ts qt/aqt/data/web/js/deckbrowser.ts scripts/soundcloud_test.cjs

experience-test:
    $env:PYTHONPATH="qt;pylib;out/qt;out/pylib"; & "out/pyenv/Scripts/pytest.exe" -p no:cacheprovider qt/tests/test_experience.py qt/tests/test_review_shortcuts.py qt/tests/test_review_layout.py
    node scripts/soundcloud_test.cjs

experience-smoke run_name mode="write":
    & "out/pyenv/Scripts/python.exe" scripts/experience_smoke.py {{run_name}} {{mode}}

experience-soundcloud run_name:
    & "out/pyenv/Scripts/python.exe" scripts/experience_soundcloud.py {{run_name}}

# Built-in features run inside this source tree's Anki, without ANKIDEV.
builtin-run *args: build
    & "out/pyenv/Scripts/python.exe" scripts/run_builtin.py {{args}}

builtin-test:
    & "out/pyenv/Scripts/python.exe" scripts/builtin_tests.py

review-shortcuts-test:
    $env:PYTHONPATH="qt;pylib;out/qt;out/pylib"; & "out/pyenv/Scripts/pytest.exe" -p no:cacheprovider qt/tests/test_review_shortcuts.py

review-shortcuts-smoke run_name:
    & "out/pyenv/Scripts/python.exe" scripts/review_shortcuts_smoke.py {{run_name}}

review-shortcuts-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/review_shortcuts.py qt/aqt/reviewer.py qt/aqt/main.py qt/aqt/preferences.py qt/aqt/builtin_features/passfail2/__init__.py qt/aqt/builtin_features/review_tools/settings.py qt/aqt/builtin_features/review_tools/i18n.py qt/tests/test_review_shortcuts.py scripts/review_shortcuts_smoke.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/review_shortcuts.py qt/aqt/reviewer.py qt/aqt/main.py qt/aqt/preferences.py qt/aqt/builtin_features/passfail2/__init__.py qt/aqt/builtin_features/review_tools/settings.py qt/aqt/builtin_features/review_tools/i18n.py qt/tests/test_review_shortcuts.py scripts/review_shortcuts_smoke.py
    & "node_modules/.bin/dprint.cmd" fmt ts/lib/tslib/review-shortcuts.ts ts/lib/tslib/review-shortcuts.test.ts ts/reviewer/index.ts qt/aqt/data/web/js/reviewer-bottom.ts

review-tools-test:
    & "out/pyenv/Scripts/python.exe" scripts/builtin_tests.py test_review_tools.py

review-tools-locale-check:
    node scripts/verify_review_locale.cjs

review-tools-smoke run_name mode="write":
    & "out/pyenv/Scripts/python.exe" scripts/review_tools_smoke.py {{run_name}} {{mode}}

review-tools-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/builtin_features/review_tools qt/aqt/builtin_features/__init__.py qt/aqt/builtin_features/storage.py qt/aqt/builtin_features/learning/workspace.py qt/aqt/reviewer.py scripts/review_tools_smoke.py tests/test_review_tools.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/builtin_features/review_tools qt/aqt/builtin_features/__init__.py qt/aqt/builtin_features/storage.py qt/aqt/builtin_features/learning/workspace.py qt/aqt/reviewer.py scripts/review_tools_smoke.py tests/test_review_tools.py

review-tools-check:
    & "out/pyenv/Scripts/ruff.exe" check qt/aqt/builtin_features/review_tools qt/aqt/builtin_features/__init__.py qt/aqt/builtin_features/storage.py qt/aqt/builtin_features/learning/workspace.py qt/aqt/reviewer.py scripts/review_tools_smoke.py tests/test_review_tools.py
    & "out/pyenv/Scripts/mypy.exe" --follow-imports=silent qt/aqt/builtin_features/review_tools qt/aqt/builtin_features/learning/workspace.py qt/aqt/reviewer.py

navigation-test:
    & "out/pyenv/Scripts/python.exe" scripts/builtin_tests.py test_navigation.py

navigation-smoke run_name mode="write":
    & "out/pyenv/Scripts/python.exe" scripts/navigation_smoke.py {{run_name}} {{mode}}

review-layout-smoke run_name mode="verify":
    & "out/pyenv/Scripts/python.exe" scripts/review_layout_smoke.py {{run_name}} {{mode}}

review-layout-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/builtin_features/learning/review_layout.py qt/aqt/builtin_features/learning/workspace.py qt/aqt/reviewer.py qt/aqt/toolbar.py qt/tests/test_review_layout.py qt/tests/test_toolbar.py scripts/review_layout_smoke.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/builtin_features/learning/review_layout.py qt/aqt/builtin_features/learning/workspace.py qt/aqt/reviewer.py qt/aqt/toolbar.py qt/tests/test_review_layout.py qt/tests/test_toolbar.py scripts/review_layout_smoke.py

navigation-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/builtin_features/learning qt/aqt/builtin_features/passfail2 qt/aqt/builtin_features/storage.py qt/aqt/builtin_features/__init__.py qt/aqt/deckbrowser.py qt/aqt/toolbar.py qt/aqt/reviewer.py scripts/navigation_smoke.py scripts/learning_smoke.py scripts/builtin_tests.py tests/test_navigation.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/builtin_features/learning qt/aqt/builtin_features/passfail2 qt/aqt/builtin_features/storage.py qt/aqt/builtin_features/__init__.py qt/aqt/deckbrowser.py qt/aqt/toolbar.py qt/aqt/reviewer.py scripts/navigation_smoke.py scripts/learning_smoke.py scripts/builtin_tests.py tests/test_navigation.py

navigation-check:
    & "out/pyenv/Scripts/ruff.exe" check qt/aqt/builtin_features/learning qt/aqt/builtin_features/passfail2 qt/aqt/builtin_features/storage.py qt/aqt/builtin_features/__init__.py qt/aqt/deckbrowser.py qt/aqt/toolbar.py qt/aqt/reviewer.py scripts/navigation_smoke.py scripts/learning_smoke.py scripts/builtin_tests.py tests/test_navigation.py
    & "out/pyenv/Scripts/mypy.exe" --follow-imports=silent qt/aqt/builtin_features/learning qt/aqt/builtin_features/passfail2 qt/aqt/builtin_features/storage.py qt/aqt/builtin_features/__init__.py qt/aqt/deckbrowser.py qt/aqt/toolbar.py qt/aqt/reviewer.py

learning-smoke run_name mode="write":
    & "out/pyenv/Scripts/python.exe" scripts/learning_smoke.py {{run_name}} {{mode}}

learning-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/builtin_features/learning qt/aqt/builtin_features/protected_secrets.py scripts/learning_smoke.py tests/test_learning_workspace.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/builtin_features/learning qt/aqt/builtin_features/protected_secrets.py scripts/learning_smoke.py tests/test_learning_workspace.py

learning-check:
    & "out/pyenv/Scripts/ruff.exe" check qt/aqt/builtin_features/learning qt/aqt/builtin_features/protected_secrets.py scripts/learning_smoke.py tests/test_learning_workspace.py
    & "out/pyenv/Scripts/mypy.exe" --follow-imports=silent qt/aqt/builtin_features/learning qt/aqt/builtin_features/protected_secrets.py

learning-assets-check:
    & "out/pyenv/Scripts/python.exe" scripts/verify_web_runtime.py out/qt/_aqt/data/web/sveltekit

builtin-browser-smoke run_name:
    & "out/pyenv/Scripts/python.exe" scripts/browser_smoke.py {{run_name}}

builtin-browser-restart run_name:
    & "out/pyenv/Scripts/python.exe" scripts/browser_restart.py {{run_name}}

builtin-smoke run_name mode="write":
    & "out/pyenv/Scripts/python.exe" scripts/builtin_smoke.py {{run_name}} {{mode}}

builtin-package template output: wheels
    & "out/pyenv/Scripts/python.exe" scripts/build_builtin_distribution.py "{{template}}" "{{output}}"

builtin-format:
    & "out/pyenv/Scripts/ruff.exe" check --select I --fix qt/aqt/builtin_features/__init__.py qt/aqt/builtin_features/storage.py scripts/run_builtin.py scripts/builtin_smoke.py tests/test_builtin_storage.py
    & "out/pyenv/Scripts/ruff.exe" format qt/aqt/builtin_features/__init__.py qt/aqt/builtin_features/storage.py scripts/run_builtin.py scripts/builtin_smoke.py tests/test_builtin_storage.py

# Build the project
build:
    {{ ninja }} pylib qt

# Build and run Anki in development mode
run *args:
    {{ run_script }} {{ args }}

# Build and run Anki in optimized (release) mode
run-optimized *args:
    {{ if os() == "windows" { "$env:RELEASE='1'; .\\run.bat" } else { "RELEASE=1 ./run" } }} {{ args }}

# Watch web sources and rebuild/reload Anki's web stack on change (macOS/Linux)
web-watch:
    ./tools/web-watch

# Rebuild and reload Anki's web stack without restarting (macOS/Linux)
rebuild-web:
    ./tools/rebuild-web

# Build wheels (needed for some platforms)
wheels:
    {{ ninja }} wheels

# Build and run all checks (lint + test) - lets ninja handle dependencies
check:
    {{ ninja }} pylib qt check

# Run all tests (Rust, Python, TypeScript). Pass --coverage to enforce coverage, and --html to include HTML reports.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test coverage='' html='':
    just {{ if coverage == "--coverage" { "coverage " + html } else { "_test" } }}

# Run coverage for all test stacks. Pass --html to also generate HTML reports.
[arg("html", long="html", value="--html")]
coverage html='':
    just _coverage-rust {{ html }}
    just _coverage-py {{ html }}
    just _coverage-ts {{ html }}

# Run Rust tests. Pass --coverage to enforce Rust coverage, and --html to include an HTML report.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-rust coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-rust " + html } else { "_test-rust" } }}

# Run Python tests (pylib + qt). Pass --coverage to enforce coverage, and --html to include HTML reports.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-py coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-py " + html } else { "_test-py" } }}

# Run TypeScript/Svelte Vitest tests. Pass --coverage to enforce coverage, and --html to include an HTML report.
[arg("coverage", long="coverage", value="--coverage")]
[arg("html", long="html", value="--html")]
test-ts coverage='' html='':
    just {{ if coverage == "--coverage" { "_coverage-ts " + html } else { "_test-ts" } }}

# Run Playwright end-to-end tests. Pass --ui to open the interactive UI.
[arg("ui", long="ui", value="--ui")]
test-e2e ui='': _install-playwright-browsers
    {{ ninja }} pyenv ts:generated pylib qt
    {{ playwright_env }} {{ yarn }} test:e2e {{ ui }}

[private]
_test:
    {{ ninja }} check:rust_test check:pytest check:vitest

[private]
_test-rust:
    {{ ninja }} check:rust_test

[private]
_test-py:
    {{ ninja }} check:pytest

[private]
_test-ts:
    {{ ninja }} check:vitest

[private]
_coverage-rust html='':
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-rust" } else { "tools/coverage/coverage-rust" } }} {{ html }}

[private]
_coverage-py html='':
    {{ ninja }} pylib qt
    just _coverage-py-pylib {{ html }}
    just _coverage-py-qt {{ html }}

[private]
_coverage-py-pylib html='':
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-py" } else { "tools/coverage/coverage-py" } }} pylib {{ html }}

[private]
_coverage-py-qt html='':
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-py" } else { "tools/coverage/coverage-py" } }} qt {{ html }}

[private]
_coverage-ts html='':
    {{ ninja }} node_modules ts:generated
    {{ if os_family() == "windows" { "tools\\coverage\\coverage-ts" } else { "tools/coverage/coverage-ts" } }} {{ html }}

[private]
_install-playwright-browsers:
    {{ ninja }} node_modules
    {{ playwright_env }} {{ yarn }} playwright install chromium

# Check formatting (fast, no build needed)
fmt:
    {{ ninja }} check:format

# Fix formatting
fix-fmt:
    {{ ninja }} format

# Run linting and type checking (requires build outputs)
lint:
    {{ ninja }} \
        check:clippy \
        check:mypy \
        check:ruff \
        check:eslint \
        check:svelte \
        check:typescript

# Fix auto-fixable lint issues (ruff + eslint)
fix-lint:
    {{ ninja }} fix:ruff fix:eslint

# Run minilints (copyright, contributors, licenses)
minilints:
    {{ ninja }} check:minilints

# Fix minilints (update licenses.json)
fix-minilints:
    {{ ninja }} fix:minilints

# Sync translation files
ftl-sync:
    {{ ninja }} ftl-sync

# Deprecate translation strings
ftl-deprecate:
    {{ ninja }} ftl-deprecate

# Build documentation site
docs:
    {{ uv }} run --group docs sphinx-build -b html docs out/docs/html
    @echo "Docs built at out/docs/html/index.html"

# Build and serve documentation site
docs-serve:
    {{ uv }} run --group docs sphinx-autobuild docs out/docs/html --host 127.0.0.1 --port 8000

# Build Rust API docs
docs-rust:
    cargo doc --open

# Dispatch CI workflow on a given branch or tag
ci branch:
    gh workflow run ci.yml --ref {{ branch }}

# Run Complexipy in regression-only mode
complexipy-diff:
    {{ ninja }} complexipy-diff

# Remove build outputs from out/ (pass keep-env to keep node_modules/pyenv); macOS/Linux
clean *args:
    ./tools/clean {{ args }}

# Helpers to get the right commands for the platform

ninja := if os() == "windows" { "tools\\ninja" } else { "./ninja" }
run_script := if os() == "windows" { ".\\run.bat" } else { "./run" }
playwright_env := if os() == "windows" { "set PLAYWRIGHT_BROWSERS_PATH=out\\playwright-browsers&&" } else { "PLAYWRIGHT_BROWSERS_PATH=out/playwright-browsers" }
yarn := if os() == "windows" { "out\\extracted\\node\\yarn.cmd" } else { "out/extracted/node/bin/yarn" }
uv := env("UV_BINARY", if os() == "windows" { "out\\extracted\\uv\\uv" } else { "out/extracted/uv/uv" })
export UV_PROJECT_ENVIRONMENT := if os() == "windows" { "out\\pyenv" } else { "out/pyenv" }
