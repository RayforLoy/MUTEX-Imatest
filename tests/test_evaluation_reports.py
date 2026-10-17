"""Every report explains the saved measurements without changing them."""
import copy
import csv
import json
from html.parser import HTMLParser

import pytest
from PIL import Image

from mutex_imatest.analysis_catalog import METRIC_LABELS
from mutex_imatest.analysis_plan import summarize_selected
from mutex_imatest.evaluation import evaluate_result
from mutex_imatest.models import AnalysisResult, ChartDefinition, ImageMetadata, Measurement, Region
from mutex_imatest.reports import export_bundle, export_html, export_pdf
from mutex_imatest.reports_evaluation import append_pdf_evaluations, html_evaluations


@pytest.fixture
def measurement_result(tmp_path):
    preview = tmp_path / 'preview.png'
    Image.new('RGB', (200, 120), '#e1e6e7').save(preview)
    rows = [Measurement(f'edge-{i}', f'区域 {i}', 'edge', 'R', (35 + i * 40, 60), (20 + i * 40, 40, 30, 40),
                        {'ca_r_g_px': value}, {'ca_r_g_px': 'px'}) for i, value in enumerate([.1, .2, 2.0])]
    rows += [Measurement('invalid', '测量失效区域', 'edge', 'R', (170, 60), (155, 40, 30, 40),
                         {'ca_r_g_px': None}, {'ca_r_g_px': 'px'}, flags=['clipped'])]
    chart = ChartDefinition('reference-test', '评价回归图卡', [Region('edge', 'edge', (.1, .1, .8, .8))])
    image = ImageMetadata('saved-only.tif', 200, 120, 3, 'uint16', 16, 144000, 'a' * 64, is_linear=True, decoder='regression')
    result = AnalysisResult(image, chart.id, chart.name, rows, {'transfer': 'linear', 'algorithm_version': 'regression'}, chart.to_dict())
    return result, preview


def pdf_text(path):
    from PySide6.QtPdf import QPdfDocument
    document = QPdfDocument(None)
    assert document.load(str(path)) == QPdfDocument.Error.None_
    pages = document.pageCount()
    text = '\n'.join(document.getAllText(page).text() for page in range(pages))
    document.close()
    return text, pages


class ParsedReport(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.text = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def test_html_reference_criteria_worst_point_and_missing_coverage_are_offline(measurement_result):
    result, preview = measurement_result
    result.evaluation_summary = {'version': 'obsolete', 'items': []}
    before = copy.deepcopy(result.to_dict())
    target = export_html(result, preview, preview.parent / 'legacy.html', 'ca_r_g_px', 'R')
    doc = ParsedReport()
    doc.feed(target.read_text(encoding='utf-8'))
    text = ''.join(doc.text)
    for value in ['参考值', '评价标准', '适用前提', '建议', '依据来源', 'MUTEX-reference-', '有效覆盖 3/4（75.0%）',
                  '中位数 0.2 px', '最差值 2 px', '建议改善', '无统一合格线']:
        assert value in text
    assert any(tag == 'article' and attrs.get('data-evaluation-metric') == 'ca_r_g_px' for tag, attrs in doc.tags)
    assert len([1 for tag, attrs in doc.tags if attrs.get('data-evaluation-metric')]) == len(METRIC_LABELS)
    assert not any(attrs.get('href') or attrs.get('src', '').startswith('https:') for _, attrs in doc.tags)
    assert result.to_dict() == before


def test_plain_pdf_includes_evaluation_and_does_not_modify_saved_result(measurement_result, qapp):
    result, preview = measurement_result
    before = copy.deepcopy(result.to_dict())
    target = export_pdf(result, preview, preview.parent / 'plain.pdf', 'ca_r_g_px', 'R')
    text, pages = pdf_text(target)
    for value in ['结果评价', '参考值', '评价标准', '适用前提', '依据来源', '有效覆盖', '中位数', '最差值', '建议改善']:
        assert value in text
    assert 3 <= pages < 12
    assert result.to_dict() == before


@pytest.mark.parametrize('selected', [False, True])
def test_report_only_export_embeds_evaluation_without_extra_files(measurement_result, qapp, tmp_path, selected):
    result, preview = measurement_result
    if selected:
        result.analysis_summary = summarize_selected(result, ['ca_r_g_px', 'best_focus'])
    before = copy.deepcopy(result.to_dict())
    folder = export_bundle(result, preview, tmp_path / str(selected), 'ca_r_g_px', 'R',
                           include_data=False, include_images=False, include_detail=False, basename='仅报告')
    assert {file.name for file in folder.iterdir()} == {'仅报告.html', '仅报告.pdf'}
    assert '评价标准' in (folder / '仅报告.html').read_text(encoding='utf-8')
    assert '评价标准' in pdf_text(folder / '仅报告.pdf')[0]
    assert result.to_dict() == before


def test_data_export_preserves_point_evaluations_and_standards(measurement_result, tmp_path):
    result, preview = measurement_result
    result.analysis_summary = summarize_selected(result, ['ca_r_g_px', 'best_focus'])
    before = copy.deepcopy(result.to_dict())
    folder = export_bundle(result, preview, tmp_path / 'data', 'ca_r_g_px', 'R', pdf=False,
                           include_images=False, include_detail=False)
    data = json.loads((folder / 'evaluation-results.json').read_text(encoding='utf-8'))
    item = next(item for item in data['items'] if item['metric'] == 'ca_r_g_px')
    channel = item['channels'][0]
    assert channel['median'] == .2 and channel['worst'] == 2 and channel['coverage_pct'] == 75
    assert channel['status'] == 'poor' and len(channel['point_assessments']) == 4
    assert item['reference']['reference'] and item['reference']['criteria'] and item['reference']['sources']
    with (folder / 'evaluation-results.csv').open(encoding='utf-8-sig', newline='') as file:
        rows = list(csv.DictReader(file))
    rows = [row for row in rows if row['metric'] == 'ca_r_g_px']
    assert {row['region_id'] for row in rows} == {'edge-0', 'edge-1', 'edge-2', 'invalid'}
    assert next(row for row in rows if row['region_id'] == 'invalid')['evaluation'] == '无法评价'
    assert next(row for row in rows if row['region_id'] == 'edge-2')['evaluation'] == '建议改善'
    assert all(row['reference'] and row['criteria'] and row['rule_version'] for row in rows)
    summary = json.loads((folder / 'analysis-results.json').read_text(encoding='utf-8'))
    assert summary['items'][0]['channels'][0]['evaluation']['worst'] == 2
    assert result.to_dict() == before


def test_all_missing_selected_items_share_compact_pages_and_never_pass(measurement_result, tmp_path, qapp):
    result, preview = measurement_result
    result.measurements = []
    result.analysis_summary = summarize_selected(result, list(METRIC_LABELS))
    folder = export_bundle(result, preview, tmp_path / 'no-data', include_data=False,
                           include_images=False, include_detail=False)
    text, pages = pdf_text(folder / 'report.pdf')
    assert pages < 12
    assert '无可评价数据的项目' in text
    assert '符合自定义目标' not in text and '工程参考良好' not in text
    assert '最佳焦位' in text and '未得到' in text
    document = ParsedReport()
    document.feed((folder / 'report.html').read_text(encoding='utf-8'))
    assert len([1 for tag, attrs in document.tags if attrs.get('data-evaluation-metric')]) == len(METRIC_LABELS)


def test_pdf_long_chinese_reference_and_ascii_url_survive_pagination(measurement_result, qapp, tmp_path, monkeypatch):
    import mutex_imatest.reports_evaluation as module
    from PySide6.QtGui import QPainter, QPageSize, QPdfWriter
    result, _ = measurement_result
    data = evaluate_result(result, ['ca_r_g_px'])
    sentinel = '长段落完整终点'
    data['items'][0]['reference']['criteria'] = ('逐点核查结果和适用前提，不用均值隐藏最弱区域。' * 500) + sentinel
    url = 'https://example.invalid/' + 'long-source-' * 180 + 'end-source-marker'
    data['items'][0]['reference']['sources'] = [{'title': '仅用于排版回归的长来源', 'url': url}]
    monkeypatch.setattr(module, 'evaluate_result', lambda *args, **kwargs: copy.deepcopy(data))
    path = tmp_path / 'flow.pdf'
    writer = QPdfWriter(str(path))
    writer.setResolution(120)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    painter = QPainter(writer)
    try:
        appendix_pages = append_pdf_evaluations(writer, painter, result)
    finally:
        painter.end()
    text, pages = pdf_text(path)
    assert pages == appendix_pages + 1 and appendix_pages >= 3
    assert sentinel in text and 'end-source-marker' in text
    doc = ParsedReport()
    doc.feed(html_evaluations(result))
    assert not any(attrs.get('href') for _, attrs in doc.tags)
    assert sentinel in ''.join(doc.text)


def test_html_escapes_custom_reference_goal_text(measurement_result):
    result, _ = measurement_result
    result.settings['evaluation_limits'] = {'ca_r_g_px': {'max': .5, 'unit': 'px', 'note': '<img src="https://bad.invalid/a">'}}
    report = html_evaluations(result, ['ca_r_g_px'])
    doc = ParsedReport()
    doc.feed(report)
    assert not any(tag == 'img' for tag, _ in doc.tags)
    assert '<img src="https://bad.invalid/a">' in ''.join(doc.text)


def test_focus_overlay_reports_explain_focal_positions_without_grading_coordinates(measurement_result, qapp, tmp_path):
    result, preview = measurement_result
    result.focus_unit = 'mm'
    result.measurements = [Measurement('focus-R', '红通道焦位', 'focus', 'R', (70, 60), (40, 30, 60, 60),
                                       {'best_focus': .12, 'focus_offset': .02}, {'best_focus': 'mm', 'focus_offset': 'mm'}),
                           Measurement('focus-G', '绿通道焦位', 'focus', 'G', (130, 60), (100, 30, 60, 60),
                                       {'best_focus': .10}, {'best_focus': 'mm'})]
    before = copy.deepcopy(result.to_dict())
    path = export_html(result, preview, tmp_path / 'focus.html', 'best_focus', 'R', 'mm')
    doc = ParsedReport()
    doc.feed(path.read_text(encoding='utf-8'))
    assert '焦位坐标本身无高低优劣' in ''.join(doc.text)
    path = export_pdf(result, preview, tmp_path / 'focus.pdf', 'best_focus', 'R', 'mm')
    text, _ = pdf_text(path)
    assert '焦位坐标本身无高低优劣' in text and '轴向焦位差' in text
    assert result.to_dict() == before


def test_usaf_html_pdf_use_the_same_reference_section(measurement_result, tmp_path, qapp):
    from mutex_imatest.reports_usaf import export_html as usaf_html, export_pdf as usaf_pdf
    result, preview = measurement_result
    result.template = {'calibrated': True, 'regions': [{'id': 'unit-1', 'kind': 'usaf', 'params': {'multi_frequency': True}}]}
    result.measurements = [Measurement('unit-1-combined-summary', '单元 1', 'usaf_summary', 'G', (100, 60), (60, 25, 80, 70),
                                       {'resolution_limit': .2, 'resolution_limit_lp_mm': 10, 'resolution_limit_dpi': 508},
                                       {'resolution_limit': 'cy/px'}, object_scale_px_per_mm=50)]
    stats = {key: {'count': 1, 'median': value, 'p10': value, 'max': value} for key, value in
             [('resolution_limit', .2), ('resolution_limit_lp_mm', 10), ('resolution_limit_dpi', 508), ('resolution_limit_lw_ph', 48)]}
    result.optical_summary = {'channels': ['G'], 'threshold': .1, 'threshold_mode': 'absolute', 'picture_height_px': 120,
                              'statistics': {'G': stats}, 'units': [{'unit_id': 'unit-1', 'position': [100, 60], 'located': True,
                              'rgb_shifts': {}, 'directions': {}, 'combined': {'G': {'values': {'resolution_limit_lp_mm': 10}}}}]}
    before = copy.deepcopy(result.to_dict())
    path = usaf_html(result, preview, tmp_path / 'usaf.html')
    doc = ParsedReport()
    doc.feed(path.read_text(encoding='utf-8'))
    assert not any(attrs.get('href') for _, attrs in doc.tags)
    assert '参考值' in ''.join(doc.text) and '评价标准' in ''.join(doc.text)
    path = usaf_pdf(result, preview, tmp_path / 'usaf.pdf')
    text, _ = pdf_text(path)
    assert '评价标准' in text and '参考值' in text and '最差值' in text
    assert result.to_dict() == before
