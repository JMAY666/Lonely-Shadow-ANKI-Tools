// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

(() => {
    "use strict";
    if (window.ankiWeakReview) { return; }
    const child = window !== window.top;
    let config = null;
    let entries = [];
    let known = new Set();
    let difficulty = {};
    let revealed = new Set();
    let cleanup = [];
    let manifest = "";
    let active = false;
    let activeFrame = null;
    let full = false;
    let queued = false;
    let observer = null;
    let originalImage = null;
    let imageValidated = false;
    let inlineSource = null;
    let inlineHost = null;
    let localBinding = null;
    let currentRequest = null;
    let requestSequence = 0;
    let activeMark = null;
    let hoveredEntry = null;
    let hideMarkTimer = null;
    const requestPrefix = Math.random().toString(36).slice(2);
    const TYPE = "anki-weak-review-v1";
    const allowedOrigin = (origin) => origin === location.origin || origin === "https://kyxz288.com";
    const frame = () => document.querySelector("iframe#receiver");
    const notify = (payload) => {
        const data = { ...payload, token: config?.token };
        if (data.kind === "manifest" && data.request === undefined) {
            currentRequest = `${requestPrefix}:${++requestSequence}`;
            data.details = slotDetails(data);
        }
        if (data.request === undefined) { data.request = currentRequest; }
        if (child) { window.parent.postMessage({ type: TYPE, command: data }, "*"); }
        else if (typeof window.pycmd === "function") { window.pycmd("weakReview:" + JSON.stringify(data)); }
    };
    const plain = html => {
        const root = new DOMParser().parseFromString(html || "", "text/html");
        root.querySelectorAll("script,style,template,.anki-wr-mark").forEach(el => el.remove());
        return root.body.textContent.replace(/\s+/g, " ").trim();
    };
    function slotDetails(data) {
        const parts = data.slots.map(slot => JSON.parse(slot));
        const answers = parts.map(part =>
            data.adapter === "mumu-svg-v1" ? "" : plain(part[data.adapter === "enhanced-cloze-v1" ? 2 : 1])
        );
        const heading = plain(document.querySelector(".flex-q-clz, #qa .question")?.innerHTML || "").slice(0, 1600);
        return parts.map((part, i) => {
            const marker = `【待回忆空格 ${i + 1}】`;
            let context = heading;
            if (data.adapter === "mumu-text-v1") {
                context += "\n"
                    + data.identity[3].map((p, index) =>
                        typeof p === "string" ? plain(p) : index === part[0] ? marker : plain(p[0])
                    ).join("");
            } else if (data.adapter === "mumu-table-v1") {
                const [r, c] = part[0], rows = data.identity[3];
                context += `\n行：${plain(rows[r][0])}；列：${plain(rows[0][c])}；${marker}\n同一行：`
                    + rows[r].map((cell, col) => col === c ? marker : plain(cell)).join(" | ");
            } else if (data.adapter === "native-cloze-v1") {
                const root = new DOMParser().parseFromString(config.question, "text/html");
                root.querySelectorAll("span.cloze[data-cloze]").forEach((el, j) =>
                    el.textContent = j === i ? marker : answers[j]
                );
                context = plain(root.body.innerHTML);
            } else if (data.adapter === "aswk-v1" || data.adapter === "enhanced-cloze-v1") {
                const host = document.querySelector(
                    data.adapter === "aswk-v1" ? "#qa .answers .content" : "#qa #enhanced-clozes",
                )?.cloneNode(true);
                if (host) {
                    host.querySelectorAll(data.adapter === "aswk-v1" ? ".aswk" : ".genuine-cloze").forEach((el, j) =>
                        el.textContent = j === i ? marker : answers[j]
                    );
                    context += "\n" + plain(host.innerHTML);
                }
            }
            const position = context.indexOf(marker);
            const start = Math.max(0, position - 1600);
            const excerpt = context.slice(start, start + 4000);
            return {
                key: `s${i}`,
                answer: answers[i],
                context: excerpt,
                context_excerpt: excerpt.length < context.length,
                region: data.adapter === "mumu-svg-v1" ? part : null,
            };
        });
    }
    function restore() {
        observer?.disconnect();
        observer = null;
        hideMark();
        hoveredEntry = null;
        for (const undo of cleanup.reverse()) { undo(); }
        cleanup = [];
        entries = [];
        active = false;
        manifest = "";
        originalImage = null;
        imageValidated = false;
        inlineSource = null;
        inlineHost = null;
        localBinding = null;
        currentRequest = null;
    }
    function style() {
        if (document.getElementById("anki-wr-style")) { return; }
        const el = document.createElement("style");
        el.id = "anki-wr-style";
        el.textContent = `
            .anki-wr-mark { display:none;position:fixed;inset:auto;margin:0;
              align-items:center;justify-content:center;box-sizing:border-box;
              width:max-content;height:26px;padding:0 8px;white-space:nowrap;
              font:12px/1 sans-serif;border:1px solid #608876;border-radius:7px;
              background:#f3fff8;color:#235c3d;cursor:pointer; }
            .anki-wr-mark:popover-open { display:inline-flex; }
            .anki-wr-mark::backdrop { pointer-events:none; }
            .anki-wr-mark[aria-pressed="true"] { background:#286c49;color:white; }
            .anki-wr-mark[data-wr-level="留意"] { border:2px solid #b58113; }
            .anki-wr-mark[data-wr-level="重点"] { border:2px solid #b84727; }
            .anki-wr-mark:disabled { visibility:hidden; }
            .anki-wr-mark:focus-visible { outline:2px solid #328be0;outline-offset:2px; }
            [data-wr-hidden="true"] { background:#bed8cd!important;border:1px solid #648c7d!important;
              color:transparent!important;cursor:pointer; }
            [data-wr-hidden="false"] { background:transparent!important;border-color:transparent!important; }
            [data-wr-known="true"]:not([data-wr-hidden]) { text-decoration:underline;
              text-decoration-color:#75a68d;text-decoration-thickness:1px;text-underline-offset:3px; }
            [data-wr-known="true"][data-wr-hidden] { box-shadow:inset 0 -1px #75a68d; }
        `;
        document.head.appendChild(el);
    }
    function listen(target, name, action, capture = false) {
        target.addEventListener(name, action, capture);
        cleanup.push(() => target.removeEventListener(name, action, capture));
    }
    function hideMark() {
        clearTimeout(hideMarkTimer);
        hideMarkTimer = null;
        if (activeMark?.button.matches(":popover-open")) { activeMark.button.hidePopover(); }
        activeMark = null;
    }
    function positionMark() {
        if (!activeMark) { return; }
        const { el, button } = activeMark;
        const rects = [...el.getClientRects()];
        const rect = rects[rects.length - 1];
        const width = document.documentElement.clientWidth;
        const height = document.documentElement.clientHeight;
        if (!rect || rect.bottom <= 0 || rect.top >= height || rect.right <= 0 || rect.left >= width) {
            hideMark();
            return;
        }
        const box = button.getBoundingClientRect();
        const left = Math.max(4, Math.min(rect.right - box.width, width - box.width - 4));
        const top = Math.max(
            4,
            Math.min(
                rect.top >= box.height + 8 ? rect.top - box.height - 4 : rect.bottom + 4,
                height - box.height - 4,
            ),
        );
        for (const [key, value] of Object.entries({ left: `${left}px`, top: `${top}px` })) {
            if (button.style[key] !== value) { button.style[key] = value; }
        }
    }
    function showMark(entry) {
        if (!active || entry.button.disabled || !entry.el.isConnected) { return; }
        clearTimeout(hideMarkTimer);
        if (activeMark !== entry) {
            hideMark();
            activeMark = entry;
            // The top layer escapes clipped tables and transformed SVG containers,
            // while the DOM position preserves Tab order immediately after the answer.
            entry.button.showPopover();
        }
        positionMark();
    }
    function deferHideMark() {
        clearTimeout(hideMarkTimer);
        hideMarkTimer = setTimeout(() => {
            if (
                activeMark && !activeMark.button.matches(":hover,:focus-visible")
                && !activeMark.el.matches(":hover,:focus-visible")
            ) { hideMark(); }
        }, 180);
    }
    function markButton(entry) {
        const button = document.createElement("button");
        button.className = "anki-wr-mark";
        button.type = "button";
        button.popover = "manual";
        button.textContent = "✓ 记住";
        button.dataset.wrKey = entry.key;
        button.setAttribute("aria-label", `空格 ${entry.index + 1}：本轮已记住`);
        button.addEventListener("click", event => {
            event.preventDefault();
            event.stopImmediatePropagation();
            if (!active || button.disabled) { return; }
            // Mouse marks must hand Space back to the reviewer, including when
            // the control lives in a card iframe. Keyboard activation stays local.
            if (event.detail > 0) {
                button.blur();
                hideMark();
                if (child) { window.parent.focus(); }
            }
            button.disabled = true;
            notify({ kind: "mark", key: entry.key, known: !known.has(entry.key) });
        });
        // Space/Enter operate the control, never the reviewer's rating shortcut.
        button.addEventListener("keydown", event => event.stopPropagation());
        const tabindex = entry.el.getAttribute("tabindex");
        entry.el.tabIndex = 0;
        cleanup.push(() => {
            if (tabindex === null) { entry.el.removeAttribute("tabindex"); }
            else { entry.el.setAttribute("tabindex", tabindex); }
        });
        listen(entry.el, "mouseenter", () => {
            hoveredEntry = entry;
            showMark(entry);
        });
        listen(entry.el, "mouseleave", () => {
            if (hoveredEntry === entry) { hoveredEntry = null; }
            deferHideMark();
        });
        listen(entry.el, "focus", () => showMark(entry));
        listen(entry.el, "blur", deferHideMark);
        if (!entry.inline) {
            listen(entry.el, "keydown", event => {
                if ((event.key === " " || event.key === "Enter") && !event.repeat) {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                    entry.el.click();
                }
            }, true);
        }
        listen(button, "mouseenter", () => clearTimeout(hideMarkTimer));
        listen(button, "mouseleave", deferHideMark);
        listen(button, "focus", () => showMark(entry));
        listen(button, "blur", deferHideMark);
        if (entry.index === 0) {
            listen(document, "scroll", positionMark, true);
            listen(window, "resize", positionMark);
            listen(window, "blur", () => {
                hoveredEntry = null;
                hideMark();
            });
            listen(document, "pointerdown", event => {
                if (activeMark && !activeMark.el.contains(event.target) && !activeMark.button.contains(event.target)) {
                    hoveredEntry = null;
                    hideMark();
                }
            }, true);
            listen(document, "keydown", event => {
                if (event.key === "Escape" && activeMark) {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                    hoveredEntry = null;
                    hideMark();
                }
            }, true);
        }
        cleanup.push(() => button.remove());
        entry.button = button;
        return button;
    }
    function render() {
        if (!active) { return; }
        for (const entry of entries) {
            const remembered = known.has(entry.key);
            const visible = config.side === "answer" || (!full && remembered) || revealed.has(entry.key);
            if (entry.local) {
                entry.local.paint(entry.el, visible);
                entry.el.dataset.wrConcealed = String(!visible);
                entry.el.dataset.wrKnown = String(remembered && !full);
            } else if (entry.region) {
                entry.el.dataset.wrHidden = String(!visible);
                entry.el.dataset.wrKnown = String(remembered && !full);
            } else {
                entry.el.innerHTML = visible ? entry.answer : entry.question;
                entry.el.dataset.wrKnown = String(remembered && !full);
                if (entry.inline) {
                    entry.el.dataset.wrConcealed = String(!visible);
                    entry.el.style.color = visible ? "#EB9D27" : "#9fc5e8";
                    entry.el.setAttribute(
                        "aria-label",
                        `空格 ${entry.index + 1}：${visible ? "已显示答案" : "查看答案"}`,
                    );
                }
            }
            entry.button.disabled = !visible;
            entry.button.setAttribute("aria-pressed", String(remembered));
            const label = remembered ? "✓ 已记住" : "✓ 记住";
            if (entry.button.textContent !== label) { entry.button.textContent = label; }
            entry.button.title = remembered ? "已记住；点击重新加入复习" : "标记为本轮已记住";
            const info = difficulty[entry.key];
            if (info) {
                entry.button.dataset.wrLevel = info.level;
                entry.button.title += `；${info.level} · 本轮 ${info.attempts} 次 · 近期难度 ${
                    Math.round(info.score * 100)
                }/100`;
            }
            entry.button.setAttribute("aria-label", `空格 ${entry.index + 1}：${entry.button.title}`);
        }
        if (activeMark?.button.disabled) { hideMark(); }
        const focused = entries.find(entry => entry.el === document.activeElement);
        if (hoveredEntry || focused) { showMark(hoveredEntry || focused); }
        positionMark();
    }
    function activateNative() {
        if (document.querySelector("#qa #enhanced-cloze-content, #qa .answers span.aswk")) { return false; }
        const question = new DOMParser().parseFromString(config.question, "text/html");
        const source = [...question.querySelectorAll("span.cloze[data-cloze]")];
        const targets = [...document.querySelectorAll("#qa span.cloze[data-ordinal]")];
        // Nested/mirrored/custom clozes need an explicit adapter, not text guessing.
        if (
            !source.length || source.length !== targets.length
            || source.some((el, i) =>
                el.dataset.ordinal !== targets[i].dataset.ordinal || el.querySelector(".cloze")
                || /<(?:img|svg|script|iframe|audio|video)\b|\\[([]/.test(el.dataset.cloze)
                || (config.side === "answer" && targets[i].innerHTML !== el.dataset.cloze)
            )
        ) { return false; }
        entries = targets.map((el, index) => ({
            el,
            index,
            key: `s${index}`,
            answer: source[index].dataset.cloze,
            question: source[index].innerHTML,
            original: el.innerHTML,
        }));
        const slots = entries.map((entry, i) =>
            JSON.stringify([source[i].dataset.ordinal, entry.answer, entry.question])
        );
        notify({ kind: "manifest", adapter: "native-cloze-v1", slots });
        for (const entry of entries) {
            const button = markButton(entry);
            entry.el.after(button);
            button.disabled = true;
            listen(entry.el, "click", event => {
                if (!active || config.side === "answer") { return; }
                event.preventDefault();
                event.stopImmediatePropagation();
                if (revealed.has(entry.key)) { revealed.delete(entry.key); }
                else { revealed.add(entry.key); }
                render();
            }, true);
            cleanup.push(() => {
                entry.el.innerHTML = entry.original;
                delete entry.el.dataset.wrKnown;
            });
        }
        return true;
    }
    function localTextIsReady(html) {
        return typeof html === "string" && html.length <= 18000
            && !/≯#|#≮|<(?:img|svg|script|iframe|audio|video|canvas|input)\b|\\[([]/.test(html);
    }
    function studioDescription() {
        const qa = document.getElementById("qa");
        if (!qa?.querySelector(".answers .content")) { return null; }
        const source = new DOMParser().parseFromString(config.question, "text/html");
        const original = source.querySelector("template#ak-front")?.content || source;
        if (!original.querySelector("#showButton")) { return null; }
        const declared = [...original.querySelectorAll(".answers .content span.aswk")];
        const targets = [...qa.querySelectorAll(".answers .content span.aswk")];
        if (qa.querySelector(".answers .content img, .answers .content svg, .answers .content iframe")) { return null; }
        if (
            !targets.length || declared.length !== targets.length
            || targets.some((el, i) =>
                !localTextIsReady(el.innerHTML) || el.querySelector(".aswk")
                || el.innerHTML !== declared[i].innerHTML
            )
        ) { return null; }
        const methods = ["replaceAndScroll", "resetButton", "restoreAndScroll"];
        if (config.side === "question" && methods.some(name => typeof window[name] !== "function")) { return null; }
        return {
            adapter: "aswk-v1",
            targets,
            slots: declared.map((el, i) => JSON.stringify([i, el.innerHTML])),
            identity: "aswk-current-content",
            methods,
            shown: el => el.classList.contains("show"),
            paint: (el, visible) => el.classList.toggle("show", visible),
        };
    }
    function enhancedDescription() {
        const root = document.querySelector("#qa #enhanced-clozes");
        const content = document.querySelector("#qa #enhanced-cloze-content");
        const data = window.enhancedClozesData;
        if (!root || !content || !data || typeof window.toggleCloze !== "function") { return null; }
        if (
            content.querySelector("img, svg, iframe, audio, video, canvas") || /\\[([]/.test(content.innerHTML)
        ) { return null; }
        const parsed = [...content.innerHTML.matchAll(/\{\{c(\d+)::([\s\S]*?)(?:::([\s\S]*?))?\}\}/g)]
            .map(match => [match[1], match[2], match[3] || ""]);
        if (
            !parsed.length || parsed.length > 2048
            || !["clozeId", "answers", "hints"].every(key =>
                Array.isArray(data[key]) && data[key].length === parsed.length
            )
        ) { return null; }
        if (
            parsed.some((part, i) =>
                part[0] !== String(data.clozeId[i])
                || part[1] !== data.answers[i] || part[2] !== data.hints[i]
                || !localTextIsReady(part[1]) || !localTextIsReady(part[2])
            )
        ) { return null; }
        const expected = parsed.flatMap((part, i) => Number(part[0]) === config.ordinal ? [i] : []);
        const targets = [...root.querySelectorAll("span.genuine-cloze[index][cid]")];
        if (
            !targets.length || targets.length !== expected.length
            || targets.some((el, i) =>
                el.getAttribute("index") !== String(expected[i]) || Number(el.getAttribute("cid")) !== config.ordinal
            )
        ) { return null; }
        const toggle = localBinding?.wrappedToggle === window.toggleCloze
            ? localBinding.nativeToggle
            : window.toggleCloze;
        return {
            adapter: "enhanced-cloze-v1",
            targets,
            toggle,
            slots: expected.map(index => JSON.stringify([index, ...parsed[index]])),
            identity: [config.ordinal, parsed, content.innerHTML],
            shown: el => el.getAttribute("show-state") === "answer",
            paint: (el, visible) => {
                const side = visible ? "answer" : "hint";
                if (el.getAttribute("show-state") !== side) { toggle(el, side); }
            },
        };
    }
    function replaceLocalMethod(name, replacement) {
        const original = window[name];
        if (typeof original !== "function") { return; }
        window[name] = replacement;
        cleanup.push(() => {
            if (window[name] === replacement) { window[name] = original; }
        });
    }
    function bindLocalTemplate(found) {
        const signature = JSON.stringify([found.adapter, found.slots, found.identity]);
        if (localBinding?.signature === signature && found.targets.every((el, i) => entries[i]?.el === el)) { return; }
        restore();
        revealed.clear();
        localBinding = { signature };
        entries = found.targets.map((el, index) => ({ el, index, key: `s${index}`, local: found }));
        for (const entry of entries) {
            const shown = found.shown(entry.el);
            if (shown && config.side === "question" && !full) { revealed.add(entry.key); }
            const button = markButton(entry);
            button.disabled = true;
            entry.el.after(button);
            cleanup.push(() => {
                found.paint(entry.el, shown);
                delete entry.el.dataset.wrConcealed;
                delete entry.el.dataset.wrKnown;
            });
            if (found.adapter === "aswk-v1") {
                listen(entry.el, "click", event => {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                    if (revealed.has(entry.key)) { revealed.delete(entry.key); }
                    else { revealed.add(entry.key); }
                    render();
                }, true);
            }
        }
        if (found.adapter === "aswk-v1") {
            const next = () => {
                const entry = entries.find(item => !revealed.has(item.key) && (full || !known.has(item.key)));
                if (entry) { revealed.add(entry.key); }
                render();
            };
            const hide = () => {
                const last = [...entries].reverse().find(item => revealed.has(item.key));
                if (last) { revealed.delete(last.key); }
                render();
            };
            const reset = () => {
                revealed.clear();
                render();
            };
            for (
                const [name, action] of [
                    ["replaceAndScroll", next],
                    ["resetButton", reset],
                    ["restoreAndScroll", hide],
                    ["userJs1", next],
                    ["userJs2", reset],
                    ["userJs3", hide],
                ]
            ) { replaceLocalMethod(name, action); }
        } else {
            const wrapped = function(element, option) {
                const target = element?.closest?.(".genuine-cloze") || element;
                const entry = entries.find(item => item.el === target);
                if (!entry) { return found.toggle.apply(this, arguments); }
                if (option === "answer" || (option === "toggle" && !found.shown(target))) { revealed.add(entry.key); }
                else if (option === "hint" || option === "toggle") { revealed.delete(entry.key); }
                render();
            };
            localBinding.nativeToggle = found.toggle;
            localBinding.wrappedToggle = wrapped;
            replaceLocalMethod("toggleCloze", wrapped);
        }
        notify({ kind: "manifest", adapter: found.adapter, slots: found.slots, identity: found.identity });
        observeLocal();
    }
    function discoverLocal() {
        if (!config?.enabled || activeFrame) { return false; }
        const found = enhancedDescription() || studioDescription();
        if (found) {
            bindLocalTemplate(found);
            return true;
        }
        if (localBinding) {
            restore();
            notify({ kind: "unsupported" });
        }
        return false;
    }
    function observeLocal() {
        observer = new MutationObserver(() => {
            if (queued) { return; }
            queued = true;
            requestAnimationFrame(() => {
                queued = false;
                discoverLocal();
            });
        });
        observer.observe(document.getElementById("qa") || document.body, {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: ["class", "show-state"],
        });
    }
    function inlineDescription() {
        const matches = [];
        for (const rich of document.querySelectorAll("uni-rich-text")) {
            // This adapter reads the inspected template's authoritative slot array.
            // It never changes Vue state, and declines unknown component versions.
            let component = rich.__vueParentComponent;
            for (let depth = 0; component && depth < 12; depth++, component = component.parent) {
                if (component.type?.name !== "mu-aarea") { continue; }
                const answer = component.props?.card?.answer;
                if (
                    answer?.type === 1 && Array.isArray(answer.A)
                    && component.props.flip === (config.side === "answer" ? 1 : 0)
                ) {
                    matches.push({ rich, parts: answer.A });
                }
                break;
            }
        }
        if (matches.length !== 1) { return null; }
        const { rich, parts } = matches[0];
        if (
            parts.some(part =>
                typeof part !== "string" && !(Array.isArray(part)
                    && part.length === 3 && typeof part[0] === "string" && typeof part[1] === "string"
                    && [0, 1].includes(part[2]) && part[0].length + part[1].length <= 18000)
            )
        ) { return null; }
        const normalized = parts.map(part => typeof part === "string" ? part : part.slice(0, 2));
        const slots = parts.flatMap((part, index) =>
            Array.isArray(part) ? [{ index, answer: part[0], hint: part[1], revealed: part[2] }] : []
        );
        if (!slots.length || slots.length > 512 || JSON.stringify(normalized).length > 100000) { return null; }
        const identityHost = rich.closest("[cardid][card]");
        if (!identityHost) { return null; }
        const identity = [
            identityHost.getAttribute("cardid"),
            identityHost.getAttribute("card"),
            document.querySelector(".flex-q-clz")?.innerHTML || "",
            normalized,
        ];
        return { rich, parts, slots, identity, signature: JSON.stringify(identity) };
    }
    function inlineMarkup(parts) {
        // The original rich-text renderer sanitizes HTML. Keep that boundary when
        // rendering a scoped copy: only inert text formatting is supported here.
        const template = document.createElement("template");
        template.innerHTML = parts.map((part, index) =>
            typeof part === "string"
                ? part
                : `<span data-wr-inline="${index}" class="mumu-font-14">${part[1]}</span>`
        ).join("");
        const allowed = new Set([
            "P",
            "DIV",
            "SPAN",
            "STRONG",
            "B",
            "EM",
            "I",
            "U",
            "S",
            "BR",
            "SUB",
            "SUP",
            "FONT",
            "UL",
            "OL",
            "LI",
        ]);
        const safeStyle =
            /^(?:color|background-color|font-size|font-family|font-weight|font-style|text-decoration|text-align|line-height|white-space|margin(?:-(?:top|right|bottom|left))?|padding(?:-(?:top|right|bottom|left))?)$/;
        for (const node of template.content.querySelectorAll("*")) {
            if (!allowed.has(node.tagName)) { return null; }
            for (const attr of node.attributes) {
                if (!["style", "class", "color", "size", "face", "data-wr-inline"].includes(attr.name)) { return null; }
            }
            for (const property of node.style) {
                if (
                    !safeStyle.test(property) || /url\s*\(|expression\s*\(/i.test(node.style.getPropertyValue(property))
                ) { return null; }
            }
        }
        return template.content;
    }
    function tableDescription() {
        const matches = [];
        for (const rich of document.querySelectorAll(".mumu-table")) {
            let component = rich.__vueParentComponent;
            for (let depth = 0; component && depth < 12; depth++, component = component.parent) {
                if (component.type?.name !== "mu-aarea") { continue; }
                const answer = component.props?.card?.answer;
                if (
                    answer?.type === 2 && Array.isArray(answer.A)
                    && component.props.flip === (config.side === "answer" ? 1 : 0)
                ) { matches.push({ rich, rows: answer.A }); }
                break;
            }
        }
        if (matches.length !== 1) { return null; }
        const { rich, rows } = matches[0];
        if (
            rows.length < 2 || rows.length > 513 || !Array.isArray(rows[0]) || rows[0].length < 2
            || (rows.length - 1) * (rows[0].length - 1) > 512
            || rows.some(row =>
                !Array.isArray(row) || row.length !== rows[0].length
                || row.some(cell =>
                    !cell || !localTextIsReady(cell.text) || cell.text.length > 18000
                    || ![0, 1].includes(cell.show) || !inlineMarkup([cell.text])
                )
            )
        ) { return null; }
        const normalized = rows.map(row => row.map(cell => cell.text));
        if (JSON.stringify(normalized).length > 100000) { return null; }
        const tables = rich.querySelectorAll("table");
        if (tables.length !== 1) { return null; }
        // The inspected renderer emits an empty row after the column headings.
        // Match actual cells to the authoritative grid, never by answer text alone.
        const rendered = [...tables[0].rows].filter(row => row.cells.length);
        if (rendered.length !== rows.length) { return null; }
        const slots = [];
        for (let r = 0; r < rows.length; r++) {
            const cells = [...rendered[r].cells];
            if (cells.length !== rows[r].length) { return null; }
            for (let c = 0; c < cells.length; c++) {
                const cell = cells[c], data = rows[r][c];
                const header = r === 0 || c === 0;
                const spans = cell.querySelectorAll("span.mumu-font-14");
                if (
                    cell.tagName !== (header ? "TH" : "TD") || cell.rowSpan !== 1 || cell.colSpan !== 1
                    || !cell.classList.contains(header ? "mumu-table-th" : "mumu-table-td")
                    || spans.length !== 1 || (!header && spans[0].parentElement !== cell)
                ) { return null; }
                const expected = document.createElement("span");
                expected.innerHTML = header || config.side === "answer" || data.show ? data.text : "(填空)";
                if (spans[0].innerHTML !== expected.innerHTML) { return null; }
                if (!header) {
                    slots.push({ index: [r, c], answer: data.text, hint: "(填空)", revealed: data.show });
                }
            }
        }
        const identityHost = rich.closest("[cardid][card]");
        if (!identityHost) { return null; }
        const identity = [
            identityHost.getAttribute("cardid"),
            identityHost.getAttribute("card"),
            document.querySelector(".flex-q-clz")?.innerHTML || "",
            normalized,
        ];
        return { rich, slots, identity, signature: JSON.stringify(identity), table: true };
    }
    function discoverInline(found) {
        if (manifest === found.signature && inlineSource === found.rich && inlineHost?.isConnected) { return; }
        const fragment = found.table ? found.rich.cloneNode(true) : inlineMarkup(found.parts);
        const targets = fragment
            ? [...fragment.querySelectorAll(found.table ? "td.mumu-table-td > span.mumu-font-14" : "[data-wr-inline]")]
            : [];
        if (
            !fragment || targets.length !== found.slots.length
            || (!found.table && targets.some((el, i) => el.dataset.wrInline !== String(found.slots[i].index)))
        ) {
            restore();
            notify({ kind: "unsupported" });
            return;
        }
        // Validate answer markup as well as hints before any content is replaced.
        if (found.slots.some(slot => !inlineMarkup([slot.answer]))) {
            restore();
            notify({ kind: "unsupported" });
            return;
        }
        restore();
        revealed.clear();
        manifest = found.signature;
        inlineSource = found.rich;
        // Clone the wrapper after restore(), so a refreshed table never inherits
        // the display:none that was hiding the previous native view.
        inlineHost = found.rich.cloneNode(false);
        inlineHost.classList.add(found.table ? "anki-wr-table-host" : "anki-wr-inline-host");
        const scopes = [...found.rich.attributes].filter(attr => /^data-v-/.test(attr.name));
        for (const el of fragment.querySelectorAll("*")) {
            for (const attr of scopes) { el.setAttribute(attr.name, attr.value); }
        }
        if (found.table) {
            while (fragment.firstChild) { inlineHost.appendChild(fragment.firstChild); }
        } else { inlineHost.appendChild(fragment); }
        const display = found.rich.style.getPropertyValue("display");
        const priority = found.rich.style.getPropertyPriority("display");
        const host = inlineHost;
        found.rich.style.setProperty("display", "none", "important");
        found.rich.after(host);
        cleanup.push(() => {
            host.remove();
            if (display) { found.rich.style.setProperty("display", display, priority); }
            else { found.rich.style.removeProperty("display"); }
        });
        entries = targets.map((el, index) => ({
            el,
            index,
            key: `s${index}`,
            inline: true,
            answer: found.slots[index].answer,
            question: found.slots[index].hint,
        }));
        for (const entry of entries) {
            if (found.slots[entry.index].revealed && !full) { revealed.add(entry.key); }
            entry.el.dataset.wrKey = `blank-${entry.key}`;
            entry.el.tabIndex = 0;
            entry.el.setAttribute("role", "button");
            entry.el.style.cursor = "pointer";
            entry.el.style.padding = "0 2px";
            const button = markButton(entry);
            entry.el.after(button);
            button.disabled = true;
            const reveal = event => {
                if (!active || event.target.closest(".anki-wr-mark")) { return; }
                event.preventDefault();
                event.stopImmediatePropagation();
                if (revealed.has(entry.key)) { revealed.delete(entry.key); }
                else { revealed.add(entry.key); }
                render();
            };
            listen(found.table ? entry.el.parentElement : entry.el, "click", reveal);
            listen(entry.el, "keydown", event => {
                if ((event.key === " " || event.key === "Enter") && !event.repeat) { reveal(event); }
            });
        }
        const next = !found.table && found.rich.closest(".text-left")?.querySelector(".showanswer");
        if (next) {
            listen(next, "click", event => {
                if (!active) { return; }
                event.preventDefault();
                event.stopImmediatePropagation();
                const entry = entries.find(item => !revealed.has(item.key) && (full || !known.has(item.key)));
                if (entry) { revealed.add(entry.key); }
                render();
            }, true);
        }
        notify({
            kind: "manifest",
            adapter: found.table ? "mumu-table-v1" : "mumu-text-v1",
            identity: found.identity,
            slots: found.slots.map(slot => JSON.stringify([slot.index, slot.answer, slot.hint])),
        });
        observeRegions();
    }
    function regionDescription() {
        const containers = document.querySelectorAll(".svg_answer_parent");
        if (containers.length !== 1) { return null; }
        const container = containers[0];
        const imageHost = container.querySelector(".svg_background-image");
        const img = imageHost?.querySelector("img");
        // Some diagrams retain an empty drawing point between real rectangles.
        // It hides no answer and must not disable the card or consume a slot.
        // Keep all other geometry in the validation below, including malformed
        // rectangles and regions with only one zero dimension.
        const masks = [...container.querySelectorAll(":scope > .svg_mask, :scope > .svg_mask_show")].filter(el =>
            parseFloat(el.style.width) !== 0 || parseFloat(el.style.height) !== 0
        );
        if (!img?.complete || !img.naturalWidth || !masks.length) { return null; }
        const width = parseFloat(imageHost.style.width) || imageHost.clientWidth;
        const height = parseFloat(imageHost.style.height) || imageHost.clientHeight;
        if (!(width > 0 && height > 0)) { return null; }
        const slots = masks.map(el => {
            const values = ["left", "top", "width", "height"].map((key, index) =>
                Number((parseFloat(el.style[key]) / (index % 2 ? height : width)).toFixed(5))
            );
            return values;
        });
        if (
            slots.some(v =>
                v.some(n => !Number.isFinite(n)) || v[0] < 0 || v[1] < 0 || v[2] <= 0 || v[3] <= 0
                || v[0] + v[2] > 1.01 || v[1] + v[3] > 1.01
            )
        ) { return null; }
        const image = originalImage?.url || img.currentSrc || img.src;
        const identityHost = document.querySelector("[cardid][card]");
        const identity = identityHost
            ? [
                identityHost.getAttribute("cardid"),
                identityHost.getAttribute("card"),
                document.querySelector(".flex-q-clz")?.innerHTML || "",
            ]
            : [];
        return { container, imageHost, img, masks, slots, image, identity };
    }
    function discoverRegions() {
        if (!config?.enabled) { return; }
        const inline = inlineDescription() || tableDescription();
        if (inline) {
            discoverInline(inline);
            return;
        }
        if (inlineHost) {
            restore();
            notify({ kind: "unsupported" });
            return;
        }
        const found = regionDescription();
        if (!found) { return; }
        const signature = JSON.stringify([found.slots, found.image, found.identity]);
        if (signature === manifest) {
            positionMark();
            return;
        }
        restore();
        manifest = signature;
        const { container, imageHost, img, masks, slots, image, identity } = found;
        const originalSrc = img.getAttribute("src");
        const background = imageHost.querySelector("div");
        const originalBackground = background?.style.backgroundImage;
        originalImage = { img, background, url: image };
        cleanup.push(() => {
            img.setAttribute("src", originalSrc);
            if (background) { background.style.backgroundImage = originalBackground; }
        });
        entries = masks.map((el, index) => ({ el, index, key: `s${index}`, region: true }));
        for (const entry of entries) {
            const button = markButton(entry);
            button.classList.add("anki-wr-region-mark");
            entry.el.after(button);
            button.disabled = true;
            listen(entry.el, "click", event => {
                if (!active) { return; }
                event.preventDefault();
                event.stopImmediatePropagation();
                if (revealed.has(entry.key)) { revealed.delete(entry.key); }
                else { revealed.add(entry.key); }
                render();
            }, true);
            cleanup.push(() => {
                delete entry.el.dataset.wrHidden;
                delete entry.el.dataset.wrKnown;
            });
        }
        // Preserve the template's "reveal next" affordance, with no mark side effect.
        const revealNext = event => {
            if (!active || event.target.closest(".anki-wr-mark,.svg_mask,.svg_mask_show")) { return; }
            event.preventDefault();
            event.stopImmediatePropagation();
            const next = entries.find(entry => !revealed.has(entry.key) && (full || !known.has(entry.key)));
            if (next) { revealed.add(next.key); }
            render();
        };
        listen(container, "click", revealNext, true);
        const nextButton = container.parentElement.querySelector(".showanswer");
        if (nextButton) { listen(nextButton, "click", revealNext, true); }
        notify({ kind: "manifest", adapter: "mumu-svg-v1", slots: slots.map(s => JSON.stringify(s)), image, identity });
        observeRegions();
    }
    function observeRegions() {
        observer = new MutationObserver(() => {
            if (queued) { return; }
            queued = true;
            requestAnimationFrame(() => {
                queued = false;
                discoverRegions();
            });
        });
        observer.observe(document.body, {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: ["style", "src"],
        });
    }
    function start(value) {
        restore();
        config = value;
        known = new Set();
        difficulty = {};
        revealed = new Set();
        full = value.full;
        activeFrame = null;
        if (child) {
            if (value.enabled) {
                style();
                discoverRegions();
                if (!observer) { observeRegions(); }
            }
        } else {
            const remote = frame();
            if (remote) { sendConfig(remote.contentWindow); }
            else if (value.enabled) {
                style();
                // Protected templates may decrypt/render after Anki's update hook.
                // Observe their actual supported structure instead of ending detection early.
                if (!discoverLocal() && !activateNative()) { observeLocal(); }
            }
        }
    }
    function sendConfig(target) {
        if (config && target) {
            target.postMessage({
                type: TYPE,
                config: {
                    token: config.token,
                    side: config.side,
                    enabled: config.enabled,
                    full: config.full,
                },
            }, "*");
        }
    }
    async function apply(value) {
        if (value.token !== config?.token) { return; }
        if (!child && activeFrame) {
            activeFrame.postMessage({ type: TYPE, state: value }, "*");
            return;
        }
        if (value.request !== currentRequest) { return; }
        if (full !== value.full) { revealed.clear(); }
        // Rejoining a remembered slot immediately masks it again on the question.
        for (const key of known) { if (!value.known.includes(key)) { revealed.delete(key); } }
        full = value.full;
        known = new Set(value.known);
        difficulty = value.difficulty || {};
        if (value.image && originalImage) {
            const probe = new Image();
            const loaded = await new Promise(resolve => {
                probe.onload = () => resolve(probe.naturalWidth > 0 && probe.naturalHeight > 0);
                probe.onerror = () => resolve(false);
                probe.src = value.image;
            });
            if (value.token !== config?.token || value.request !== currentRequest || !originalImage) { return; }
            if (!loaded) {
                notify({ kind: "unsupported" });
                restore();
                return;
            }
            // Display the exact bytes whose hash binds the saved regions. This also
            // invalidates a replacement image published under the same URL.
            originalImage.img.src = value.image;
            if (originalImage.background) { originalImage.background.style.backgroundImage = `url("${value.image}")`; }
            imageValidated = true;
        }
        if (originalImage && !imageValidated) { return; }
        active = true;
        render();
    }
    function stop(token) {
        if (config?.token !== token) { return; }
        if (!child && activeFrame) { activeFrame.postMessage({ type: TYPE, stop: token }, "*"); }
        config.enabled = false;
        restore();
    }
    window.addEventListener("message", event => {
        const value = event.data;
        if (!value || value.type !== TYPE) { return; }
        if (child) {
            if (event.source !== window.parent) { return; }
            if (value.config) { start(value.config); }
            else if (value.state) { apply(value.state); }
            else if (value.stop) { stop(value.stop); }
            else if (config?.enabled && value.dismiss === config.token) {
                hoveredEntry = null;
                hideMark();
            }
        } else {
            if (event.source !== frame()?.contentWindow || !allowedOrigin(event.origin)) { return; }
            if (value.ready) { sendConfig(event.source); }
            else if (value.command?.token === config?.token) {
                activeFrame = event.source;
                notify(value.command);
            }
        }
    });
    if (!child) {
        // Hovering an embedded answer does not move keyboard focus into its
        // frame. Escape must still dismiss that frame's contextual action.
        window.addEventListener("keydown", event => {
            if (event.key === "Escape" && config?.enabled && activeFrame) {
                activeFrame.postMessage({ type: TYPE, dismiss: config.token }, "*");
            }
        }, true);
    }
    window.ankiWeakReview = { start, apply, stop };
    if (child) { window.parent.postMessage({ type: TYPE, ready: true }, "*"); }
})();
