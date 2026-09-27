/* Copyright: Ankitects Pty Ltd and contributors
 * License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html */

$(init);

let filterDeckDirectory: (() => void) | undefined;
let deckSelectionTimer: ReturnType<typeof setTimeout> | undefined;
let pendingDeckId: string | undefined;

function highlightDeck(id: string): void {
    document.querySelectorAll<HTMLElement>("tr.deck").forEach((row) => {
        const selected = row.id === id;
        row.classList.toggle("current", selected);
        row.querySelector("a.deck")?.setAttribute("aria-current", String(selected));
    });
}

function _deckSelectionPending(id: string): void {
    pendingDeckId = id;
    clearTimeout(deckSelectionTimer);
    highlightDeck(id);
    document.querySelector(".deck-main")?.setAttribute("aria-busy", "true");
    document.querySelectorAll<HTMLButtonElement>(
        ".deck-main button:not(.deck-selection-retry), .deck-scope-info button",
    ).forEach((button) => {
        button.disabled = true;
    });
    const retry = document.querySelector<HTMLButtonElement>(".deck-selection-retry");
    if (retry) { retry.hidden = true; }
    const status = document.querySelector<HTMLElement>(".deck-selection-status");
    if (status) { status.textContent = "今天的学习，从这里开始。"; }
    deckSelectionTimer = setTimeout(() => {
        const name = document.getElementById(id)?.querySelector("a.deck")?.textContent || "所选牌组";
        if (status) { status.textContent = `正在切换到「${name}」…`; }
    }, 300);
}

function _deckSelectionFailed(message: string): void {
    clearTimeout(deckSelectionTimer);
    document.querySelector(".deck-main")?.setAttribute("aria-busy", "false");
    const status = document.querySelector<HTMLElement>(".deck-selection-status");
    if (status) { status.textContent = `切换未完成，请重试或选择其他牌组。${message}`; }
    const retry = document.querySelector<HTMLButtonElement>(".deck-selection-retry");
    if (retry) { retry.hidden = false; }
}

function _retryDeckSelection(): void {
    if (pendingDeckId) { pycmd(`select:${pendingDeckId}`); }
}

function _setDeckCollapsed(id: string, collapsed: boolean): void {
    const row = document.getElementById(id);
    if (!row) { return; }
    row.dataset.collapsed = collapsed ? "1" : "0";
    const control = row.querySelector("a.collapse");
    if (control) {
        control.textContent = collapsed ? "+" : "−";
        control.setAttribute("aria-expanded", String(!collapsed));
    }
    filterDeckDirectory?.();
}

function _updateDeckSelection(html: string): void {
    const next = new DOMParser().parseFromString(html, "text/html");
    const workspace = document.querySelector<HTMLElement>(".deck-workspace");
    const incoming = next.querySelector<HTMLElement>(".deck-workspace");
    if (!workspace || !incoming) { return; }
    clearTimeout(deckSelectionTimer);
    pendingDeckId = undefined;
    for (const selector of [".deck-selected-path", ".deck-main", ".deck-scope-info"]) {
        const replacement = next.querySelector(selector);
        if (replacement) { document.querySelector(selector)?.replaceWith(replacement); }
    }
    Object.assign(workspace.dataset, incoming.dataset);
    highlightDeck(incoming.dataset.selectedDeck || "");
}

function init() {
    setupDeckWorkspace();
    $("tr.deck").draggable({
        scroll: false,

        // can't use "helper: 'clone'" because of a bug in jQuery 1.5
        helper: function(_event) {
            // A cloned table row loses its column sizing outside its table.
            return $("<div class='deck-drag-helper'></div>").text($(this).attr("data-path") || "");
        },
        appendTo: "body",
        delay: 200,
        opacity: 0.7,
    });
    $("tr.deck").droppable({
        drop: handleDropEvent,
        hoverClass: "drag-hover",
    });
    $("tr.top-level-drag-row").droppable({
        drop: handleDropEvent,
        hoverClass: "drag-hover",
    });
}

function setupDeckWorkspace() {
    const workspace = document.querySelector<HTMLElement>(".deck-workspace");
    const search = document.querySelector<HTMLInputElement>("#deck-search");
    const scroll = document.querySelector<HTMLElement>(".deck-tree-scroll");
    if (!workspace || !search || !scroll) { return; }
    const rows = Array.from(document.querySelectorAll<HTMLTableRowElement>("tr.deck"));
    const byId = new Map(rows.map((row) => [row.id, row]));
    const key = "anki-deck-directory";
    let previous: { query?: string; scroll?: number; auxiliary?: boolean; widgets?: boolean; width?: number } = {};
    try {
        previous = JSON.parse(sessionStorage.getItem(key) || "{}") || {};
    } catch { /* A previous page may have stored invalid state. */ }
    search.value = previous.query || "";
    const auxiliary = document.querySelector<HTMLDetailsElement>(".deck-auxiliary")!;
    const widgets = document.querySelector<HTMLDetailsElement>(".deck-global-widgets")!;
    auxiliary.open = previous.auxiliary ?? true;
    widgets.open = previous.widgets ?? true;
    let directoryWidth = typeof previous.width === "number" && Number.isFinite(previous.width) ? previous.width : 250;

    function save() {
        try {
            sessionStorage.setItem(
                key,
                JSON.stringify({
                    query: search!.value,
                    scroll: scroll!.scrollTop,
                    auxiliary: auxiliary.open,
                    widgets: widgets.open,
                    width: directoryWidth,
                }),
            );
        } catch { /* The layout remains usable when storage is unavailable. */ }
    }
    setupDeckSplitter(workspace, directoryWidth, (width) => {
        directoryWidth = width;
        save();
    });
    function filter() {
        const query = search!.value.trim().toLocaleLowerCase();
        const matches = new Set<string>();
        rows.forEach((row) => {
            if ((row.dataset.path || "").toLocaleLowerCase().includes(query)) {
                matches.add(row.id);
                (row.dataset.ancestors || "").split(",").forEach((id) => matches.add(id));
            }
        });
        rows.forEach((row) => {
            const ancestors = (row.dataset.ancestors || "").split(",").filter(Boolean);
            row.hidden = query
                ? !matches.has(row.id)
                : ancestors.some((id) => byId.get(id)?.dataset.collapsed === "1");
            const link = row.querySelector<HTMLAnchorElement>("a.deck");
            if (link) {
                link.textContent = query ? row.dataset.path! : row.dataset.path!.split("::").pop()!;
            }
        });
        document.querySelector<HTMLElement>("#deck-no-match")!.hidden = rows.some((row) => !row.hidden);
    }
    filter();
    filterDeckDirectory = filter;
    scroll.scrollTop = previous.scroll || 0;
    if (!search.value) {
        document.querySelector<HTMLElement>("tr.current:not([hidden])")?.scrollIntoView({ block: "nearest" });
    }
    search.addEventListener("input", () => {
        filter();
        save();
    });
    search.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            search.value = "";
            filter();
            save();
        }
        if (event.key === "Enter") {
            const match = rows.find((row) =>
                !row.hidden
                && (row.dataset.path || "").toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())
            );
            if (match) { pycmd("select:" + match.id); }
        }
    });
    scroll.addEventListener("scroll", save);
    auxiliary.addEventListener("toggle", save);
    widgets.addEventListener("toggle", save);
    workspace.dataset.ready = "true";
}

function setupDeckSplitter(workspace: HTMLElement, initialWidth: number, save: (width: number) => void) {
    const splitter = workspace.querySelector<HTMLElement>(".deck-splitter");
    const directory = workspace.querySelector<HTMLElement>(".deck-directory");
    if (!splitter || !directory) { return; }
    let preferredWidth = Math.max(190, Math.min(480, initialWidth));
    let currentWidth = preferredWidth;
    let maximum = 480;
    let drag: { pointer: number; x: number; width: number } | undefined;

    function applyWidth() {
        const style = getComputedStyle(workspace);
        const available = workspace.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        maximum = Math.max(190, Math.min(480, available - 320 - splitter!.offsetWidth));
        currentWidth = Math.round(Math.max(190, Math.min(maximum, preferredWidth)));
        workspace.style.setProperty("--deck-directory-width", `${currentWidth}px`);
        splitter!.setAttribute("aria-valuemax", String(Math.floor(maximum)));
        splitter!.setAttribute("aria-valuenow", String(currentWidth));
        splitter!.setAttribute("aria-valuetext", `${currentWidth} 像素`);
    }
    function finish() {
        if (!drag) { return; }
        const pointer = drag.pointer;
        drag = undefined;
        document.body.classList.remove("deck-resizing");
        if (splitter!.hasPointerCapture(pointer)) { splitter!.releasePointerCapture(pointer); }
        save(preferredWidth);
    }
    splitter.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || !event.isPrimary || !splitter.offsetWidth) { return; }
        event.preventDefault();
        splitter.focus({ preventScroll: true });
        drag = { pointer: event.pointerId, x: event.clientX, width: currentWidth };
        splitter.setPointerCapture(event.pointerId);
        document.body.classList.add("deck-resizing");
    });
    splitter.addEventListener("pointermove", (event) => {
        if (drag?.pointer !== event.pointerId) { return; }
        const direction = getComputedStyle(workspace).direction === "rtl" ? -1 : 1;
        preferredWidth = Math.max(190, Math.min(maximum, drag.width + direction * (event.clientX - drag.x)));
        applyWidth();
    });
    splitter.addEventListener("pointerup", finish);
    splitter.addEventListener("pointercancel", finish);
    splitter.addEventListener("lostpointercapture", finish);
    window.addEventListener("blur", finish);
    splitter.addEventListener("keydown", (event) => {
        const step = (event.shiftKey ? 40 : 10) * (getComputedStyle(workspace).direction === "rtl" ? -1 : 1);
        let width: number;
        switch (event.key) {
            case "ArrowLeft":
                width = currentWidth - step;
                break;
            case "ArrowRight":
                width = currentWidth + step;
                break;
            case "Home":
                width = 190;
                break;
            case "End":
                width = maximum;
                break;
            default:
                return;
        }
        event.preventDefault();
        preferredWidth = Math.max(190, Math.min(maximum, width));
        applyWidth();
        save(preferredWidth);
    });
    splitter.addEventListener("dblclick", () => {
        preferredWidth = 250;
        applyWidth();
        save(preferredWidth);
    });
    let previousContainerWidth = workspace.clientWidth;
    new ResizeObserver(() => {
        if (workspace.clientWidth === previousContainerWidth) { return; }
        previousContainerWidth = workspace.clientWidth;
        // Apply in the next frame so wrapping/scrollbars cannot cause a resize loop.
        requestAnimationFrame(() => {
            if (!splitter.offsetWidth) { finish(); }
            applyWidth();
        });
    }).observe(workspace);
    applyWidth();
}

function handleDropEvent(event, ui) {
    const draggedDeckId = ui.draggable.attr("id");
    const ontoDeckId = $(this).attr("id") || "";

    pycmd("drag:" + draggedDeckId + "," + ontoDeckId);
}
