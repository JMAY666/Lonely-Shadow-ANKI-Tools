# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Presentation only: due counts and study queues remain owned by Anki."""

from __future__ import annotations

import html
from typing import Any

from aqt.utils import tr


def render_page(browser: Any, content: Any) -> str:
    data = browser._render_data
    deck = data.current_deck
    did = int(data.current_deck_id)
    name = html.escape(deck["name"])
    node = browser.mw.col.decks.find_deck_in_tree(data.tree, data.current_deck_id)
    counts = (
        (node.new_count, node.learn_count, node.review_count) if node else (0, 0, 0)
    )
    entries = "".join(
        f'<span class="deck-card-count"><span>{label}</span><strong class="{color}">{count}</strong></span>'
        for label, count, color in zip(
            ("新卡", "学习中", "待复习"),
            counts,
            ("new-count", "learn-count", "review-count"),
        )
    )

    def descendant_count(node: Any) -> int:
        return (
            sum(1 + descendant_count(child) for child in node.children) if node else 0
        )

    children = descendant_count(node)
    description = html.escape(deck.get("desc", ""))
    return f"""
<div class="deck-workspace" data-selected-deck="{did}" data-render-revision="{browser._render_revision}">
  <aside id="deck-directory" class="deck-directory" aria-label="牌组目录">
    <h2>牌组</h2>
    <p class="deck-selected-path" aria-label="当前选中的牌组">当前：{name}</p>
    <input id="deck-search" type="search" placeholder="搜索牌组或路径" aria-label="搜索牌组目录">
    <div class="deck-tree-scroll"><table class="deck-tree" cellspacing="0">{content.tree}</table></div>
    <p id="deck-no-match" hidden>没有匹配的牌组</p>
    <div class="deck-directory-actions">
      <button onclick="pycmd('create')">{tr.decks_create_deck()}</button>
      <button onclick="pycmd('shared')">{tr.decks_get_shared()}</button>
    </div>
  </aside>
  <div class="deck-splitter" role="separator" tabindex="0" aria-orientation="vertical"
       aria-label="调整牌组目录宽度" aria-controls="deck-directory" aria-valuemin="190"
       aria-valuemax="480" aria-valuenow="250" title="拖动调整牌组目录宽度；方向键微调，双击恢复默认"></div>
  <main class="deck-content" aria-label="当前牌组内容">
  <section class="deck-main" aria-label="当前牌组学习面板">
    <span class="deck-eyebrow">当前牌组</span><h1>{name}</h1>
    <p class="deck-muted deck-selection-feedback"><span class="deck-selection-status" role="status" aria-live="polite">今天的学习，从这里开始。</span><button class="deck-selection-retry" hidden onclick="_retryDeckSelection()">重试</button></p>
    <button class="deck-study-card" onclick="pycmd('open:{did}')" aria-label="{name}的卡片：直接开始学习" title="从当前牌组及其子牌组的原生队列开始；下列为分类计数"><span class="deck-study-cards">{entries}</span><span class="deck-card-entry">进入本牌组学习 →</span></button>
    <button class="deck-start" onclick="pycmd('open:{did}')">开始学习</button>
    <p class="deck-muted">范围为当前牌组及其子牌组，遵循原生到期时间、每日限额和调度规则。</p>
    <div class="deck-main-actions">
      <button onclick="pycmd('browse-deck')">查看卡片</button>
      <button onclick="pycmd('overview')">牌组工具</button>
      <button onclick="pycmd('statistics')">查看统计</button>
    </div>
    {f'<div class="deck-description">{description}</div>' if description else ""}
  </section>
  <details class="deck-auxiliary" open>
    <summary>辅助信息</summary>
    <section class="deck-scope-info"><h3>{name}</h3><p>{"筛选牌组" if deck.get("dyn") else "普通牌组"} · {children} 个子牌组</p><p>当前队列计数：{sum(counts)} 张</p><button onclick="pycmd('statistics')">统计与牌组选项</button></section>
    <details class="deck-global-widgets"><summary>账户辅助面板 · 全部牌组</summary>{content.auxiliary}{content.stats}</details>
  </details>
  </main>
</div>
"""
