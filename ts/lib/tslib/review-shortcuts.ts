// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { bridgeCommand } from "./bridgecommand";

export function installReviewShortcutGuard(enabled: () => boolean, side: () => string): void {
    const installed = new WeakSet<Document>();
    const composing = new WeakSet<Document>();
    const observedFrames = new WeakSet<HTMLIFrameElement>();

    function editable(element: Element | null): boolean {
        return !!element?.closest(
            "input, textarea, select, [contenteditable]:not([contenteditable=false]), [role=textbox], [role=combobox], [data-wr-key]",
        );
    }

    function allowed(doc: Document): boolean {
        if (composing.has(doc)) {
            return false;
        }
        const modal = Array.from(doc.querySelectorAll("dialog[open], [aria-modal=true]"))
            .some(element => element.getClientRects().length > 0);
        if (modal) {
            return false;
        }
        let element = doc.activeElement;
        while (element?.shadowRoot?.activeElement) {
            element = element.shadowRoot.activeElement;
        }
        if (editable(element)) {
            return false;
        }
        if (element?.tagName === "IFRAME") {
            try {
                const child = (element as HTMLIFrameElement).contentDocument;
                return !!child && allowed(child);
            } catch {
                return false;
            }
        }
        return true;
    }

    function attach(doc: Document): void {
        if (installed.has(doc)) {
            return;
        }
        installed.add(doc);
        doc.addEventListener("compositionstart", () => composing.add(doc), true);
        doc.addEventListener("compositionend", () => composing.delete(doc), true);
        const keyHandler = (event: KeyboardEvent): void => {
            if (!enabled() || event.isComposing || event.keyCode === 229 || !allowed(doc)) {
                return;
            }
            if (
                (event.key === " " || event.key === "Enter") && !event.ctrlKey && !event.altKey && !event.metaKey
                && !event.shiftKey
            ) {
                event.preventDefault();
                event.stopImmediatePropagation();
                if (event.type === "keydown" && !event.repeat && side() === "question") {
                    bridgeCommand("reviewShortcut:show");
                }
            }
        };
        doc.addEventListener("keydown", keyHandler, true);
        doc.addEventListener("keyup", keyHandler, true);
        const frames = (): void => {
            for (const frame of doc.querySelectorAll("iframe")) {
                const childReady = (): void => {
                    try {
                        if (frame.contentDocument) {
                            attach(frame.contentDocument);
                        }
                    } catch { /* Cross-origin frames cannot dispatch review shortcuts. */ }
                };
                if (!observedFrames.has(frame)) {
                    observedFrames.add(frame);
                    frame.addEventListener("load", childReady);
                }
                childReady();
            }
        };
        new MutationObserver(frames).observe(doc, { childList: true, subtree: true });
        frames();
    }
    attach(document);
    Object.assign(window, {
        ankiReviewShortcutAllowed: () => enabled() && document.hasFocus() && allowed(document),
    });
}
