// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

(() => {
    "use strict";
    if (window.ankiWeakReview) { return; }
    const child = window !== window.top;
    let config = null;
    let entries = [];
    let known = new Set();
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
    const TYPE = "anki-weak-review-v1";
    const allowedOrigin = (origin) => origin === location.origin || origin === "https://kyxz288.com";
    const frame = () => document.querySelector("iframe#receiver");
    const notify = (payload) => {
        const data = { ...payload, token: config?.token };
        if (child) { window.parent.postMessage({ type: TYPE, command: data }, "*"); }
        else if (typeof window.pycmd === "function") { window.pycmd("weakReview:" + JSON.stringify(data)); }
    };
    function restore() {
        observer?.disconnect();
        observer = null;
        for (const undo of cleanup.reverse()) { undo(); }
        cleanup = [];
        entries = [];
        active = false;
        manifest = "";
        originalImage = null;
        imageValidated = false;
    }
    function style() {
        if (document.getElementById("anki-wr-style")) { return; }
        const el = document.createElement("style");
        el.id = "anki-wr-style";
        el.textContent = `
            .anki-wr-mark { display:inline-flex;align-items:center;justify-content:center;
              box-sizing:border-box;width:20px;height:20px;padding:0;margin:0 2px;
              font:13px/1 sans-serif;border:1px solid #608876;border-radius:50%;
              background:#f3fff8;color:#235c3d;vertical-align:middle;cursor:pointer; }
            .anki-wr-mark[aria-pressed="true"] { background:#286c49;color:white; }
            .anki-wr-mark:disabled { opacity:.45;cursor:default; }
            .anki-wr-mark:focus-visible { outline:2px solid #328be0;outline-offset:2px; }
            [data-wr-hidden="true"] { background:#bed8cd!important;border:1px solid #648c7d!important;
              color:transparent!important;cursor:pointer; }
            [data-wr-hidden="false"] { background:transparent!important;border-color:transparent!important; }
            [data-wr-known="true"] { outline:1px dashed #458466;outline-offset:1px; }
            .anki-wr-region-mark { position:absolute;z-index:4;margin:0;opacity:0; }
            .anki-wr-region-mark:focus,
            .anki-wr-region-mark:hover { opacity:1; }
        `;
        document.head.appendChild(el);
    }
    function listen(target, name, action, capture = false) {
        target.addEventListener(name, action, capture);
        cleanup.push(() => target.removeEventListener(name, action, capture));
    }
    function markButton(entry) {
        const button = document.createElement("button");
        button.className = "anki-wr-mark";
        button.type = "button";
        button.textContent = "✓";
        button.dataset.wrKey = entry.key;
        button.setAttribute("aria-label", `空格 ${entry.index + 1}：本轮已记住`);
        button.addEventListener("click", event => {
            event.preventDefault();
            event.stopImmediatePropagation();
            if (!active || button.disabled) { return; }
            button.disabled = true;
            notify({ kind: "mark", key: entry.key, known: !known.has(entry.key) });
        });
        // Space/Enter operate the control, never the reviewer's rating shortcut.
        button.addEventListener("keydown", event => event.stopPropagation());
        cleanup.push(() => button.remove());
        entry.button = button;
        return button;
    }
    function render() {
        if (!active) { return; }
        for (const entry of entries) {
            const remembered = known.has(entry.key);
            const visible = config.side === "answer" || (!full && remembered) || revealed.has(entry.key);
            if (entry.region) {
                entry.el.dataset.wrHidden = String(!visible);
                entry.el.dataset.wrKnown = String(remembered && !full);
            } else {
                entry.el.innerHTML = visible ? entry.answer : entry.question;
                entry.el.dataset.wrKnown = String(remembered && !full);
            }
            entry.button.disabled = !visible;
            entry.button.setAttribute("aria-pressed", String(remembered));
            entry.button.title = remembered ? "已记住；点击重新加入复习" : "标记为本轮已记住";
            entry.button.setAttribute("aria-label", `空格 ${entry.index + 1}：${entry.button.title}`);
        }
    }
    function activateNative() {
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
    function regionDescription() {
        const containers = document.querySelectorAll(".svg_answer_parent");
        if (containers.length !== 1) { return null; }
        const container = containers[0];
        const imageHost = container.querySelector(".svg_background-image");
        const img = imageHost?.querySelector("img");
        const masks = [...container.querySelectorAll(":scope > .svg_mask, :scope > .svg_mask_show")];
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
    function positionButtons(found) {
        for (const entry of entries) {
            const left = parseFloat(entry.el.style.left);
            const right = left + parseFloat(entry.el.style.width) + 2;
            const x = right + 20 <= found.imageHost.clientWidth ? right : Math.max(0, left - 22);
            const changes = { left: `${x}px`, top: entry.el.style.top };
            for (const [key, value] of Object.entries(changes)) {
                if (entry.button.style[key] !== value) { entry.button.style[key] = value; }
            }
        }
    }
    function discoverRegions() {
        if (!config?.enabled) { return; }
        const found = regionDescription();
        if (!found) { return; }
        const signature = JSON.stringify([found.slots, found.image, found.identity]);
        if (signature === manifest) {
            positionButtons(found);
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
            container.appendChild(button);
            button.disabled = true;
            listen(entry.el, "mouseenter", () => button.style.opacity = "1");
            listen(entry.el, "mouseleave", () => button.style.removeProperty("opacity"));
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
        positionButtons(found);
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
                if (!activateNative()) { notify({ kind: "unsupported" }); }
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
        if (full !== value.full) { revealed.clear(); }
        // Rejoining a remembered slot immediately masks it again on the question.
        for (const key of known) { if (!value.known.includes(key)) { revealed.delete(key); } }
        full = value.full;
        known = new Set(value.known);
        if (value.image && originalImage) {
            const probe = new Image();
            const loaded = await new Promise(resolve => {
                probe.onload = () => resolve(probe.naturalWidth > 0 && probe.naturalHeight > 0);
                probe.onerror = () => resolve(false);
                probe.src = value.image;
            });
            if (value.token !== config?.token || !originalImage) { return; }
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
        } else {
            if (event.source !== frame()?.contentWindow || !allowedOrigin(event.origin)) { return; }
            if (value.ready) { sendConfig(event.source); }
            else if (value.command?.token === config?.token) {
                activeFrame = event.source;
                notify(value.command);
            }
        }
    });
    window.ankiWeakReview = { start, apply, stop };
    if (child) { window.parent.postMessage({ type: TYPE, ready: true }, "*"); }
})();
