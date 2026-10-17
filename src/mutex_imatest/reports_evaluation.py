"""Shared, offline result interpretation for every HTML and PDF report.

The evaluator is deliberately run on the saved measurements at export time.
This keeps old result files useful and never rewrites the measured inputs.
"""
from __future__ import annotations

import html
import math

from .evaluation import STATUS_COLORS, evaluate_result


def _escape(value):
    return html.escape(str(value), quote=True)


def _number(value):
    if value is None or not isinstance(value, (float, int)) or not math.isfinite(value):
        return '—'
    return f'{value:.6g}'


def _channel_lines(channel):
    """Keep coverage and the weakest measurement beside the central value."""
    valid, total = channel.get('valid', 0), channel.get('total', 0)
    unit = channel.get('unit', '')
    lines = [f"{channel.get('channel', '—')} · {channel.get('label', '无法评价')}：{channel.get('text', '')}",
             f"有效覆盖 {valid}/{total}（{channel.get('coverage_pct', 0):.1f}%）；中位数 {_number(channel.get('median'))} {unit}；"
             f"P10–P90 {_number(channel.get('p10'))}–{_number(channel.get('p90'))} {unit}；"
             f"最差值 {_number(channel.get('worst'))} {unit}；范围 {_number(channel.get('min'))}–{_number(channel.get('max'))} {unit}。"]
    if channel.get('worst') is None and valid:
        lines.append('该项目没有统一的最差方向；请结合定义和逐点结果判断。')
    lines.extend(f'限制：{note}（{count} 点）' for note, count in channel.get('limitations', {}).items())
    return lines


def _reference_lines(reference):
    labels = [('reference', '参考值'), ('criteria', '评价标准'), ('prerequisites', '适用前提'),
              ('action', '建议'), ('basis', '依据性质')]
    lines = [(label, str(reference.get(key, '未记录'))) for key, label in labels]
    sources = reference.get('sources', [])
    lines.append(('依据来源', '；'.join(source.get('title', '') +
                                    ('：' + source['url'] if source.get('url') else '')
                                    for source in sources) or '本项目测量定义'))
    return lines


def html_evaluations(result, metrics=None, unit=None):
    """Return a self-contained section; URLs are plain text, never external hrefs."""
    data = evaluate_result(result, metrics, unit)
    details, unavailable = [], []
    for item in data['items']:
        reference = item['reference']
        refs = '<dl>' + ''.join(f'<dt>{label}</dt><dd>{_escape(value)}</dd>'
                                for label, value in _reference_lines(reference)) + '</dl>'
        channels = item['channels']
        rows = []
        for channel in channels:
            text = '<br>'.join(_escape(line) for line in _channel_lines(channel))
            color = STATUS_COLORS.get(channel.get('status'), '#586e7c')
            rows.append(f'<div class="evaluation-channel" style="border-left-color:{color}">{text}</div>')
        values = ''.join(rows)
        name = _escape(item['name'])
        if any(channel.get('valid') for channel in channels):
            details.append(f'<article class="evaluation-item" data-evaluation-metric="{_escape(item["metric"])}">'
                           f'<h3>{name}</h3>{values}{refs}</article>')
        else:
            reason = item.get('reason') or '没有可评价测点；未测得不填零，也不评价为通过。'
            unavailable.append(f'<details class="evaluation-unavailable" data-evaluation-metric="{_escape(item["metric"])}">'
                               f'<summary>{name} · 无法评价：{_escape(reason)}</summary>{values}{refs}</details>')
    inactive = ('<h3>无可评价数据的项目</h3><p>保留原因；展开可查看参考值、标准及所需前提。</p>' + ''.join(unavailable)) if unavailable else ''
    return f'''<section class="result-evaluations" id="evaluation-results">
<style>.result-evaluations{{border-top:2px solid #d4e4e8;margin-top:28px;padding-top:12px;overflow-wrap:anywhere}}
.result-evaluations h3{{font-size:16px;margin:18px 0 8px}}.evaluation-item{{border-top:1px solid #dae5e9;padding-top:6px;margin-top:18px}}
.evaluation-channel{{background:#f3f7f8;border-left:4px solid #58717d;padding:10px 12px;margin:8px 0;font-size:13px}}
.result-evaluations dl{{font-size:13px;margin:8px 0 18px}}.result-evaluations dt{{font-weight:bold;margin-top:6px}}.result-evaluations dd{{margin:0 0 5px 0}}
.evaluation-unavailable{{font-size:12px;margin:5px 0;border:1px solid #dce5e8;padding:7px}}
.result-evaluations summary{{cursor:pointer}}@media print{{.result-evaluations{{break-before:page}}.evaluation-item{{break-inside:auto}}
.evaluation-channel{{break-inside:avoid}}.evaluation-unavailable{{break-inside:auto}}.result-evaluations dd{{overflow-wrap:anywhere}}}}</style>
<h2>结果评价、参考值与标准</h2><p>{_escape(data['note'])}</p>
<p>评价版本：{_escape(data['version'])}。有效覆盖按可评价测点统计；中位数、P10 / P90 与最差值共同显示，均值不替代逐点评价。无效或缺失测量不填零。</p>
{''.join(details)}{inactive}</section>'''


def append_pdf_evaluations(writer, painter, result, metrics=None, unit=None):
    """Append flowing pages to an active painter, breaking long text by line.

    No-data projects share a compact list, rather than allocating a page per
    project. Device-aware QTextLayout also wraps long source URLs and filenames.
    The caller keeps ownership of the painter and its earlier page footers.
    """
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QTextLayout, QTextOption

    data = evaluate_result(result, metrics, unit)
    width, height = writer.width(), writer.height()
    margin = 35
    content, bottom = width - 2 * margin, height - 48
    page, y = 0, 0.

    def footer():
        font = QFont('Microsoft YaHei', 8)
        painter.setFont(font)
        painter.setPen(QColor('#617886'))
        value = f'MUTEX · 结果评价与参考标准 · 附录 {page}'
        painter.drawText(QRectF(margin, height - 28, content, 23),
                         int(Qt.AlignmentFlag.AlignVCenter), value)

    def new_page():
        nonlocal page, y
        if page:
            footer()
        if not writer.newPage():
            raise OSError('Cannot append evaluation PDF page')
        page += 1
        font = QFont('Microsoft YaHei', 15)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor('#124c59'))
        painter.drawText(QRectF(margin, 15, content, 45),
                         int(Qt.AlignmentFlag.AlignVCenter), '结果评价、参考值与标准' + ('（续）' if page > 1 else ''))
        y = 76.

    def ensure(height_needed):
        if y + height_needed > bottom:
            new_page()

    def paragraph(value, size=9, bold=False, color='#193343', gap=6):
        nonlocal y
        font = QFont('Microsoft YaHei', size)
        font.setBold(bold)
        for raw_line in str(value).split('\n'):
            layout = QTextLayout(raw_line or ' ', font, writer)
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(option)
            lines = []
            layout.beginLayout()
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(content)
                line.setPosition(QPointF(0, 0))
                lines.append(line)
            layout.endLayout()
            for line in lines:
                ensure(line.height() + 3)
                painter.setFont(font)
                painter.setPen(QColor(color))
                line.draw(painter, QPointF(margin, y))
                y += line.height() + 1
        y += gap

    new_page()
    paragraph(data['note'], 9, color='#805d2b')
    paragraph(f"评价版本：{data['version']}。有效覆盖按可评价测点统计；缺失不填零。中位数、P10 / P90 和最差值并列，均值不替代逐点评价。", 9)
    inactive = []
    for item in data['items']:
        if not any(channel.get('valid') for channel in item['channels']):
            inactive.append(item)
            continue
        ensure(100)
        paragraph(item['name'], 11, True)
        for channel in item['channels']:
            for line in _channel_lines(channel):
                paragraph(line, 9, color=STATUS_COLORS.get(channel.get('status'), '#586e7c'), gap=3)
        for label, value in _reference_lines(item['reference']):
            paragraph(label + '：' + value, 8 if label == '依据来源' else 9, gap=4)
        y += 12
    if inactive:
        ensure(90)
        paragraph('无可评价数据的项目', 11, True)
        paragraph('以下项目未获得可评价测点，保留原因，不给通过结论。完整参考定义可查看 HTML 报告或软件中的项目说明。', 9)
        for item in inactive:
            reason = item.get('reason') or '没有可评价测点；请检查图案、质量标志和标定。'
            paragraph(item['name'] + '：' + reason, 8, color='#61717c', gap=4)
    footer()
    return page
