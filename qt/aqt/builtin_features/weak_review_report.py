# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Portable report layout shared by the preview, HTML and paginated PDF."""

from __future__ import annotations

import html
import math
import re
from datetime import datetime
from pathlib import Path

from aqt.qt import (
    QFont,
    QMarginsF,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QRectF,
    QSizeF,
    Qt,
    QTextDocument,
    QTextFormat,
    QTextTable,
)


def escaped(value) -> str:
    return html.escape(str(value)).replace("\n", "<br>")


def markdown_body(text: str) -> str:
    doc = QTextDocument()
    doc.setMarkdown(
        text,
        QTextDocument.MarkdownFeature.MarkdownDialectGitHub
        | QTextDocument.MarkdownFeature.MarkdownNoHTML,
    )
    body = doc.toHtml().split("<body", 1)[-1].split(">", 1)[-1].rsplit("</body>", 1)[0]
    # Reports embed only the explicitly supplied local image snapshots below.
    body = re.sub(r"<img\b[^>]*>", "", body, flags=re.I)
    return re.sub(r"</?a\b[^>]*>", "", body, flags=re.I)


def render_report(
    snapshot: dict,
    ai_text: str = "",
    model: str = "",
    images: dict[str, str] | None = None,
) -> str:
    images = images or {}
    items = snapshot["items"]
    counts = {
        name: sum(item["level"] == name for item in items)
        for name in ("重点", "留意", "普通")
    }
    table = "".join(
        "<tr>"
        f"<td>{i + 1}</td><td>{escaped(item['deck'])}<br>空格 {int(item['key'][1:]) + 1}</td>"
        f"<td>{item['level']}<br>{round(item['score'] * 100)}/100</td>"
        f"<td>{item['last_attempts']}</td><td>{item['total_attempts']}</td><td>{item['day_misses']}</td></tr>"
        for i, item in enumerate(items)
    )
    sections = []
    for index, item in enumerate(items):
        picture = images.get(f"{item['card']}:{item['key']}")
        sections.append(
            "<table width='100%' cellspacing='0' cellpadding='0' style='page-break-inside:avoid'><tr><td style='border:0'>"
            f"<h3>{index + 1:02d} · {escaped(item['deck'])} · 空格 {int(item['key'][1:]) + 1}</h3>"
            f"<p class='meta'>卡片 {item['card']} / {item['key']} · {item['rounds']} 轮记录 · 专项到期 {datetime.fromtimestamp(item['due']).strftime('%Y-%m-%d %H:%M')}</p>"
            f"<p class='meta'>当日专项练习 {item.get('day_practices', 0)} 次，其中未记住 {item.get('day_practice_misses', 0)} 次。</p>"
            f"<p><b>上下文</b><br>{escaped(item['context'])}</p>"
            + (
                "<p class='meta'>显示目标附近的上下文节选。</p>"
                if item.get("context_excerpt")
                else ""
            )
            + f"<p class='answer'><b>答案</b><br>{escaped(item['answer'] or '见原图橙色框内区域')}</p>"
            + (f"<p><img src='{picture}' width='400'></p>" if picture else "")
            + "</td></tr></table>"
        )
    analysis = (
        "<table width='100%' cellspacing='0' cellpadding='0'><tr><td style='border:0'><h2>03 · AI 分析</h2><p class='meta'>模型："
        + escaped(model)
        + " · 以下为推断与学习建议</p>"
        + markdown_body(ai_text)
        + "</td></tr></table>"
        if ai_text
        else ""
    )
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>逐空薄弱项报告</title>"
        "<style>body{font-family:'Microsoft YaHei','Noto Sans CJK SC',sans-serif;color:#26373a;font-size:11pt;line-height:1.65;margin:0 auto;max-width:960px;padding:30px}"
        "h1{font-size:25pt;color:#215e53;margin-bottom:8px}h2{font-size:16pt;color:#215e53;margin-top:28px}h3{font-size:12pt;color:#215e53;margin-top:24px;page-break-after:avoid}"
        ".meta{color:#657a7b;font-size:9pt}.answer{background:#edf4f0;padding:12px}"
        "table{border-collapse:collapse;width:100%;font-size:10pt}th{background:#e6f0ec;color:#215e53;text-align:left}td,th{padding:8px;border-bottom:1px solid #dbe5e0}"
        "thead{display:table-header-group}tr{page-break-inside:avoid}img{max-width:100%;height:auto}.summary{background:#edf4f0;padding:16px}"
        "@media print{body{padding:0;max-width:none}a{color:inherit}}</style></head><body>"
        "<p class='meta'>ANKI · 逐空复习记录</p>"
        f"<h1>{escaped(snapshot['kind'])}</h1><p>{escaped(snapshot['day'])} · {escaped(snapshot['scope'])}</p>"
        f"<table width='100%' bgcolor='#edf4f0' cellpadding='10'><tr><td><b>{len(items)} 个复盘空格</b>　重点 {counts['重点']}　留意 {counts['留意']}　已改善 / 待巩固 {counts['普通']}</td></tr></table>"
        "<p class='meta'>近期难度随新轮次更新；统计基于本机升级后的已评分记录。次数不等于点击次数，难度分不是记忆概率。</p>"
        "<h2>01 · 薄弱项概览</h2><table width='100%' cellspacing='0' cellpadding='6'><thead><tr><th>#</th><th>牌组 / 空格</th><th>近期难度</th><th>最近轮次数</th><th>累计次数</th><th>当日未记住</th></tr></thead>"
        f"<tbody>{table or '<tr><td colspan=6>当前范围暂无薄弱项记录。</td></tr>'}</tbody></table>"
        "<h2>02 · 上下文与答案</h2>"
        + "".join(sections)
        + analysis
        + "<hr><p class='meta'>数据保存在当前账户本机，不随 Anki 同步。专项练习与整卡调度分别记录。报告可能含个人学习内容。</p></body></html>"
    )


def write_pdf(path: Path, content: str, title: str) -> None:
    writer = QPdfWriter(str(path))
    writer.setResolution(144)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(18, 16, 18, 16), QPageLayout.Unit.Millimeter)
    writer.setTitle(title)
    writer.setCreator("Anki · 逐空薄弱项")
    rect = writer.pageLayout().paintRectPixels(writer.resolution())
    document = QTextDocument()
    document.documentLayout().setPaintDevice(writer)
    document.setDefaultFont(QFont("Microsoft YaHei", 11))
    document.setDocumentMargin(0)
    document.setHtml(content)
    width, height = rect.width(), rect.height() - 80
    document.setPageSize(QSizeF(width, height))
    layout = document.documentLayout()
    # Qt's rich-text engine ignores CSS page-break-inside. Keep a complete
    # one-row context block together using native frame pagination instead.
    for frame in document.rootFrame().childFrames():
        document.size()
        bounds = layout.frameBoundingRect(frame)
        remaining = height - (bounds.top() % height)
        if (
            isinstance(frame, QTextTable)
            and bounds.height() <= height
            and bounds.height() > remaining
            and remaining < height - 1
        ):
            fmt = frame.format()
            fmt.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
            frame.setFormat(fmt)
    pages = max(1, math.ceil(document.size().height() / height))
    painter = QPainter(writer)
    if not painter.isActive():
        raise OSError("无法创建 PDF，请检查文件是否被其他软件占用。")
    try:
        for page in range(pages):
            if page and not writer.newPage():
                raise OSError("无法写入 PDF 页面。")
            painter.setFont(QFont("Microsoft YaHei", 8))
            painter.drawText(QRectF(0, 0, width, 30), Qt.AlignmentFlag.AlignLeft, title)
            painter.drawText(
                QRectF(0, height + 50, width, 30),
                Qt.AlignmentFlag.AlignRight,
                f"{page + 1} / {pages} · Anki 逐空复习",
            )
            painter.save()
            painter.translate(0, 40 - page * height)
            painter.setClipRect(QRectF(0, page * height, width, height))
            document.drawContents(painter, QRectF(0, page * height, width, height))
            painter.restore()
    finally:
        painter.end()
    if not path.is_file() or path.stat().st_size < 100:
        raise OSError("PDF 未成功写入。")
