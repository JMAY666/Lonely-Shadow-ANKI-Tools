# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from __future__ import annotations

import html
import json
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

import aqt
import aqt.operations
from anki.collection import Collection, OpChanges
from anki.decks import DeckCollapseScope, DeckId, DeckTreeNode
from anki.scheduler.v3 import Scheduler as V3Scheduler
from aqt import AnkiQt, gui_hooks
from aqt.deckoptions import display_options_for_deck_id
from aqt.operations import CollectionOp, QueryOp
from aqt.operations.deck import (
    add_deck_dialog,
    remove_decks,
    rename_deck,
    reparent_decks,
    set_current_deck,
    set_deck_collapsed,
)
from aqt.qt import *
from aqt.sound import av_player
from aqt.toolbar import BottomBar
from aqt.utils import getOnlyText, openLink, shortcut, showInfo, tr


class DeckBrowserBottomBar:
    def __init__(self, deck_browser: DeckBrowser) -> None:
        self.deck_browser = deck_browser


@dataclass
class RenderData:
    """Data from collection that is required to show the page."""

    tree: DeckTreeNode
    current_deck_id: DeckId
    studied_today: str
    sched_upgrade_required: bool
    current_deck: dict


@dataclass
class DeckBrowserContent:
    """Stores sections of HTML content that the deck browser will be
    populated with.

    Attributes:
        tree {str} -- HTML of the deck tree section
        stats {str} -- HTML of the stats section
    """

    tree: str
    stats: str
    auxiliary: str = ""


@dataclass
class RenderDeckNodeContext:
    current_deck_id: DeckId


class DeckBrowser:
    _render_data: RenderData

    def __init__(self, mw: AnkiQt) -> None:
        self.mw = mw
        self.web = mw.web
        self.bottom = BottomBar(mw, mw.bottomWeb)
        self.scrollPos = QPoint(0, 0)
        self._refresh_needed = False
        self._selection_revision = 0
        self._starting_review = False
        self._render_revision = 0
        self._selection_request: tuple[int, DeckId] | None = None
        self._selection_busy = False
        self._selection_error = False
        self._counts_cached_at = 0.0

    def show(self) -> None:
        self._selection_revision += 1
        self._selection_request = None
        self._selection_error = False
        av_player.stop_and_clear_queue()
        self.web.set_bridge_command(self._linkHandler, self)
        # redraw top bar for theme change
        self.mw.toolbar.redraw()
        self.refresh()

    def refresh(self) -> None:
        self._counts_cached_at = 0.0
        self._renderPage()
        self._refresh_needed = False

    def refresh_if_needed(self) -> None:
        if self._refresh_needed:
            self.refresh()

    def op_executed(
        self, changes: OpChanges, handler: object | None, focused: bool
    ) -> bool:
        if changes.study_queues and handler is not self:
            self._counts_cached_at = 0.0
            self._refresh_needed = True

        if focused:
            self.refresh_if_needed()

        return self._refresh_needed

    # Event handlers
    ##########################################################################

    def _linkHandler(self, url: str) -> Any:
        if ":" in url:
            (cmd, arg) = url.split(":", 1)
        else:
            cmd = url
            arg = ""
        if self.selection_pending and cmd in (
            "open",
            "overview",
            "statistics",
            "browse-deck",
        ):
            return False
        if cmd == "open":
            if (
                self.mw.state == "deckBrowser"
                and int(arg) != self._render_data.current_deck_id
            ):
                return False
            self.start_review(DeckId(int(arg)))
        elif cmd == "opts":
            self._showOptions(arg)
        elif cmd == "shared":
            self._onShared()
        elif cmd == "import":
            self.mw.onImport()
        elif cmd == "create":
            self._on_create()
        elif cmd == "drag":
            source, target = arg.split(",")
            self._handle_drag_and_drop(DeckId(int(source)), DeckId(int(target or 0)))
        elif cmd == "collapse":
            self._collapse(DeckId(int(arg)))
        elif cmd == "v2upgrade":
            self._confirm_upgrade()
        elif cmd == "v2upgradeinfo":
            if self.mw.col.sched_ver() == 1:
                openLink("https://faqs.ankiweb.net/the-anki-2.1-scheduler.html")
            else:
                openLink("https://faqs.ankiweb.net/the-2021-scheduler.html")
        elif cmd == "select":
            self.set_current_deck(DeckId(int(arg)))
        elif cmd == "overview":
            self.mw.onOverview()
        elif cmd == "statistics":
            self.mw.onStats()
        elif cmd == "browse-deck":
            from aqt.builtin_features.learning.metrics import scope_query

            aqt.dialogs.open("Browser", self.mw).search_for(
                scope_query(self.mw.col, int(self.mw.col.decks.selected()), True)
            )
        return False

    def set_current_deck(self, deck_id: DeckId) -> None:
        if self._starting_review or self.mw.state != "deckBrowser":
            return
        self._selection_revision += 1
        revision = self._selection_revision
        self._render_revision += 1  # Reject renders requested before this selection.
        self._selection_request = (revision, deck_id)
        self._selection_error = False
        self.web.eval(f"_deckSelectionPending('{int(deck_id)}');")
        QTimer.singleShot(40, self._select_pending_deck)

    @property
    def selection_pending(self) -> bool:
        return bool(
            self._selection_request or self._selection_busy or self._selection_error
        )

    def _selection_is_current(self, revision: int) -> bool:
        return (
            self._selection_request is not None
            and self._selection_request[0] == revision
            and self.mw.state == "deckBrowser"
        )

    def _select_pending_deck(self) -> None:
        if self._selection_busy or not self._selection_request:
            return
        if self.mw.state != "deckBrowser":
            self._selection_request = None
            return
        revision, deck_id = self._selection_request
        self._selection_busy = True

        def select(col: Collection) -> OpChanges:
            # Requests waiting behind another database task must not save old choices.
            if not self._selection_is_current(revision):
                return OpChanges()
            return col.decks.set_current(deck_id)

        def selected(_: OpChanges) -> None:
            if self._selection_is_current(revision):
                self._renderPage(selection_only=True, selection_revision=revision)
            else:
                self._selection_finished(revision)

        CollectionOp(parent=self.mw, op=select).without_progress().success(
            selected
        ).failure(lambda exc: self._selection_failed(revision, exc)).run_in_background(
            initiator=self
        )

    def _selection_finished(self, revision: int, rendered: bool = False) -> None:
        self._selection_busy = False
        if rendered and self._selection_is_current(revision):
            self._selection_request = None
            self._selection_error = False
        # At most one selection/read cycle is active; keep only the latest request.
        self._select_pending_deck()

    def _selection_failed(self, revision: int, exc: Exception) -> None:
        self._selection_busy = False
        if self._selection_is_current(revision):
            self._selection_request = None
            self._selection_error = True
            self.web.eval(f"_deckSelectionFailed({json.dumps(str(exc))});")
        else:
            self._select_pending_deck()

    def start_review(self, deck_id: DeckId) -> None:
        if self.selection_pending:
            return
        if self._starting_review or self.mw.state == "review":
            return
        if not self.mw.col.v3_scheduler():
            showInfo("请先使用牌组页面的原生入口升级调度器。", parent=self.mw)
            return
        if not self.mw.col.decks.get(deck_id, default=False):
            showInfo("该牌组已不存在，请重新选择。", parent=self.mw)
            self.refresh()
            return
        self._starting_review = True

        def fail(exc: Exception) -> None:
            self._starting_review = False
            showInfo(str(exc), parent=self.mw)

        def ready(has_cards: bool) -> None:
            self._starting_review = False
            if (
                self.mw.state not in ("deckBrowser", "overview")
                or self.mw.col.decks.selected() != deck_id
            ):
                return
            if not has_cards:
                self.mw.moveToState("deckBrowser")
                showInfo(
                    "当前牌组及其子牌组暂无可学习／复习的卡片。可能尚未到期、达到每日限额，或卡片已暂停／搁置。",
                    parent=self.mw,
                )
                return
            self.mw.col.startTimebox()
            self.mw.moveToState("review")

        def selected(_: Any) -> None:
            QueryOp(
                parent=self.mw,
                op=lambda col: bool(
                    cast(V3Scheduler, col.sched).get_queued_cards(fetch_limit=1).cards
                ),
                success=ready,
            ).failure(fail).run_in_background()

        set_current_deck(parent=self.mw, deck_id=deck_id).success(selected).failure(
            fail
        ).run_in_background(initiator=self)

    # HTML generation
    ##########################################################################

    _body = """
<center>
<table cellspacing=0 cellpadding=3>
%(tree)s
</table>

<br>
%(stats)s
</center>
"""

    def _renderPage(
        self,
        reuse: bool = False,
        selection_only: bool = False,
        selection_revision: int | None = None,
    ) -> None:
        if not reuse:
            self._render_revision += 1
            revision = self._render_revision

            cached = getattr(self, "_render_data", None)
            counts_at = self._counts_cached_at

            def get_data(col: Collection) -> RenderData | None:
                nonlocal counts_at
                if selection_revision is not None and not self._selection_is_current(
                    selection_revision
                ):
                    return None
                use_cache = (
                    selection_only
                    and cached
                    and counts_at == self._counts_cached_at
                    and time.monotonic() - counts_at < 2
                )
                if use_cache and cached is not None:
                    tree = cached.tree
                    studied = cached.studied_today
                else:
                    tree = col.sched.deck_due_tree()
                    studied = col.studied_today()
                    counts_at = time.monotonic()
                return RenderData(
                    tree=tree,
                    current_deck_id=col.decks.get_current_id(),
                    studied_today=studied,
                    sched_upgrade_required=not col.v3_scheduler(),
                    current_deck=col.decks.current(),
                )

            def success(output: RenderData | None) -> None:
                if (
                    output is None
                    or revision != self._render_revision
                    or self.mw.state != "deckBrowser"
                    or (
                        self._selection_request is not None
                        and selection_revision != self._selection_request[0]
                    )
                ):
                    if selection_revision is not None:
                        self._selection_finished(selection_revision)
                    return
                previous = getattr(self, "_render_data", None)
                self._render_data = output
                self._counts_cached_at = counts_at
                self._selection_error = False
                if (
                    selection_only
                    and previous
                    and self._same_deck_directory(previous.tree, output.tree)
                ):
                    # Keep the directory, focus, drag handlers and account widgets alive.
                    from aqt.builtin_features.learning.deck_page import render_page

                    page = render_page(self, DeckBrowserContent(tree="", stats=""))
                    self.web.eval(f"_updateDeckSelection({json.dumps(page)});")
                else:
                    self.__renderPage(None)
                if selection_revision is not None:
                    self._selection_finished(selection_revision, rendered=True)

            def failed(exc: Exception) -> None:
                if selection_revision is not None:
                    self._selection_failed(selection_revision, exc)
                else:
                    showInfo(str(exc), parent=self.mw)

            QueryOp(
                parent=self.mw,
                op=get_data,
                success=success,
            ).failure(failed).run_in_background()
        else:
            self.web.evalWithCallback("window.pageYOffset", self.__renderPage)

    @staticmethod
    def _same_deck_directory(left: DeckTreeNode, right: DeckTreeNode) -> bool:
        """Count changes do not require rebuilding the directory/account widgets."""
        return (
            (left.deck_id, left.name, left.collapsed, left.filtered)
            == (right.deck_id, right.name, right.collapsed, right.filtered)
            and len(left.children) == len(right.children)
            and all(
                DeckBrowser._same_deck_directory(a, b)
                for a, b in zip(left.children, right.children)
            )
        )

    def __renderPage(self, offset: int | None) -> None:
        data = self._render_data
        content = DeckBrowserContent(
            tree=self._renderDeckTree(data.tree),
            stats=self._renderStats(),
        )
        gui_hooks.deck_browser_will_render_content(self, content)
        from aqt.builtin_features.learning.deck_page import render_page

        self.web.stdHtml(
            self._v1_upgrade_message(data.sched_upgrade_required)
            + render_page(self, content),
            css=["css/deckbrowser.css"],
            js=[
                "js/vendor/jquery.min.js",
                "js/vendor/jquery-ui.min.js",
                "js/deckbrowser.js",
            ],
            context=self,
        )
        self._drawButtons()
        if offset is not None:
            self._scrollToOffset(offset)
        gui_hooks.deck_browser_did_render(self)

    def _scrollToOffset(self, offset: int) -> None:
        self.web.eval("window.scrollTo(0, %d, 'instant');" % offset)

    def _renderStats(self) -> str:
        return '<div id="studiedToday"><span>{}</span></div>'.format(
            self._render_data.studied_today
        )

    def _renderDeckTree(self, top: DeckTreeNode) -> str:
        buf = """
<tr><th colspan=5 align=start>{}</th>
<th class=count>{}</th>
<th class=count>{}</th>
<th class=count>{}</th>
<th class=optscol></th></tr>""".format(
            tr.decks_deck(),
            tr.actions_new(),
            tr.decks_learn_header(),
            tr.decks_review_header(),
        )
        buf += self._topLevelDragRow()

        ctx = RenderDeckNodeContext(current_deck_id=self._render_data.current_deck_id)

        for child in top.children:
            buf += self._render_deck_node(child, ctx)

        return buf

    def _render_deck_node(
        self,
        node: DeckTreeNode,
        ctx: RenderDeckNodeContext,
        path: str = "",
        ancestors: tuple[int, ...] = (),
    ) -> str:
        if node.collapsed:
            prefix = "+"
        else:
            prefix = "−"

        def indent() -> str:
            return "&nbsp;" * 6 * (node.level - 1)

        if node.deck_id == ctx.current_deck_id:
            klass = "deck current"
        else:
            klass = "deck"

        path = f"{path}::{node.name}" if path else node.name
        full_path = html.escape(path, quote=True)
        buf = f"<tr class='{klass}' id='{node.deck_id}' data-path='{full_path}' data-ancestors='{','.join(map(str, ancestors))}' data-collapsed='{int(node.collapsed)}'>"
        # deck link
        if node.children:
            collapse = (
                "<a class=collapse href=# aria-label='展开或折叠牌组' aria-expanded='%s' onclick='return pycmd(\"collapse:%d\")'>%s</a>"
                % (str(not node.collapsed).lower(), node.deck_id, prefix)
            )
        else:
            collapse = "<span class=collapse></span>"
        if node.filtered:
            extraclass = "filtered"
        else:
            extraclass = ""
        buf += """

        <td class=decktd colspan=5>%s%s<a class="deck %s"
        href=# title="%s" aria-current="%s" onclick="return pycmd('select:%d')">%s</a></td>""" % (
            indent(),
            collapse,
            extraclass,
            full_path,
            "true" if node.deck_id == ctx.current_deck_id else "false",
            node.deck_id,
            html.escape(node.name),
        )

        # due counts
        def nonzeroColour(cnt: int, klass: str) -> str:
            if not cnt:
                klass = "zero-count"
            return f'<span class="{klass}">{cnt}</span>'

        review = nonzeroColour(node.review_count, "review-count")
        learn = nonzeroColour(node.learn_count, "learn-count")

        buf += ("<td align=end>%s</td>" * 3) % (
            nonzeroColour(node.new_count, "new-count"),
            learn,
            review,
        )
        # options
        buf += (
            "<td align=center class=opts><a href='#' aria-label='牌组操作' onclick='return pycmd(\"opts:%d\");'>"
            "<img src='/_anki/imgs/gears.svg' class=gears></a></td></tr>" % node.deck_id
        )
        # children
        for child in node.children:
            buf += self._render_deck_node(child, ctx, path, (*ancestors, node.deck_id))
        return buf

    def _topLevelDragRow(self) -> str:
        return "<tr class='top-level-drag-row'><td colspan='6'>&nbsp;</td></tr>"

    # Options
    ##########################################################################

    def _showOptions(self, did: str) -> None:
        m = QMenu(self.mw)
        a = m.addAction(tr.actions_rename())
        assert a is not None
        qconnect(a.triggered, lambda b, did=did: self._rename(DeckId(int(did))))
        a = m.addAction(tr.actions_export())
        assert a is not None
        qconnect(a.triggered, lambda b, did=did: self._export(DeckId(int(did))))
        a = m.addAction(tr.actions_delete())
        assert a is not None
        qconnect(a.triggered, lambda b, did=did: self._delete(DeckId(int(did))))
        gui_hooks.deck_browser_will_show_options_menu(m, int(did))
        m.popup(QCursor.pos())

    def _export(self, did: DeckId) -> None:
        self.mw.onExport(did=did)

    def _rename(self, did: DeckId) -> None:
        def prompt(name: str) -> None:
            new_name = getOnlyText(
                tr.decks_new_deck_name(), default=name, title=tr.actions_rename()
            )
            if not new_name or new_name == name:
                return
            else:
                rename_deck(
                    parent=self.mw, deck_id=did, new_name=new_name
                ).run_in_background()

        QueryOp(
            parent=self.mw, op=lambda col: col.decks.name(did), success=prompt
        ).run_in_background()

    def _options(self, did: DeckId) -> None:
        display_options_for_deck_id(did)

    def _collapse(self, did: DeckId) -> None:
        def failed(exc: Exception) -> None:
            self.refresh()
            showInfo(str(exc), parent=self.mw)

        node = self.mw.col.decks.find_deck_in_tree(self._render_data.tree, did)
        if node:
            self._render_revision += 1
            revision = self._render_revision
            node.collapsed = not node.collapsed

            def saved(_: Any) -> None:
                # A collapse can invalidate an in-flight deck selection render.
                # Reconcile the final saved state without rebuilding the directory.
                if revision == self._render_revision and self.mw.state == "deckBrowser":
                    self._renderPage(selection_only=True)

            set_deck_collapsed(
                parent=self.mw,
                deck_id=did,
                collapsed=node.collapsed,
                scope=DeckCollapseScope.REVIEWER,
            ).success(saved).failure(failed).run_in_background(initiator=self)
            self.web.eval(
                f"_setDeckCollapsed('{int(did)}', {json.dumps(node.collapsed)});"
            )

    def _handle_drag_and_drop(self, source: DeckId, target: DeckId) -> None:
        reparent_decks(
            parent=self.mw, deck_ids=[source], new_parent=target
        ).run_in_background()

    def _delete(self, did: DeckId) -> None:
        deck = self.mw.col.decks.find_deck_in_tree(self._render_data.tree, did)
        assert deck is not None
        deck_name = deck.name
        remove_decks(
            parent=self.mw, deck_ids=[did], deck_name=deck_name
        ).run_in_background()

    # Top buttons
    ######################################################################

    drawLinks: list[list[str]] = []

    def _drawButtons(self) -> None:
        if not self.drawLinks:
            self.mw.bottomWeb.clear()
            return
        buf = ""
        drawLinks = deepcopy(self.drawLinks)
        for b in drawLinks:
            if b[0]:
                b[0] = tr.actions_shortcut_key(val=shortcut(b[0]))
            buf += """
<button title='%s' onclick='pycmd(\"%s\");'>%s</button>""" % tuple(b)
        self.bottom.draw(
            buf=buf,
            link_handler=self._linkHandler,
            web_context=DeckBrowserBottomBar(self),
        )

    def _onShared(self) -> None:
        openLink(f"{aqt.appShared}decks/")

    def _on_create(self) -> None:
        if op := add_deck_dialog(
            parent=self.mw, default_text=self.mw.col.decks.current()["name"]
        ):
            op.run_in_background()

    ######################################################################

    def _v1_upgrade_message(self, required: bool) -> str:
        if not required:
            return ""

        update_required = tr.scheduling_update_required().replace("V2", "v3")

        return f"""
<center>
<div class=callout>
    <div>
      {update_required}
    </div>
    <div>
      <button onclick='pycmd("v2upgrade")'>
        {tr.scheduling_update_button()}
      </button>
      <button onclick='pycmd("v2upgradeinfo")'>
        {tr.scheduling_update_more_info_button()}
      </button>
    </div>
</div>
</center>
"""

    def _confirm_upgrade(self) -> None:
        if self.mw.col.sched_ver() == 1:
            self.mw.col.mod_schema(check=True)
            self.mw.col.upgrade_to_v2_scheduler()
        self.mw.col.set_v3_scheduler(True)

        showInfo(tr.scheduling_update_done())
        self.refresh()
