"""Reviewable, unit-bearing acceptance goals; never implicit industry grades."""
import copy
import html
import json
from pathlib import Path
import math
from PySide6.QtCore import QLocale
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QComboBox,
    QCheckBox,QTextBrowser,QPushButton,QLabel,QLineEdit,QFileDialog,QMessageBox)
from ..analysis_catalog import METRICS
from ..evaluation_catalog import REFERENCES, REFERENCE_VERSION, reference_for
from ..evaluation import validate_limits, STATUS_COLORS, channel_text, RULE_NOTE
from ..resolution import FREQUENCY_METRICS


def reference_html(key, reference=None, evaluation=None):
    from .i18n import current_language
    if current_language()=='en':return english_reference_html(key,reference,evaluation)
    esc=lambda value:html.escape(str(value),quote=True)
    ref=reference or reference_for(key)
    sections=[f'<h3>{esc(ref["name"])}</h3>']
    if evaluation:
        color=STATUS_COLORS.get(evaluation['status'],'#5a6c7a')
        sections.append(f'<p style="color:{color}"><b>{esc(evaluation["label"])}</b></p><p>{esc(channel_text(evaluation)).replace(chr(10),"<br>")}</p>')
    for title,field in [('参考值','reference'),('评价标准','criteria'),('依据类型','basis'),('适用条件','prerequisites'),('建议操作','action')]:
        sections.append(f'<p><b>{title}</b><br>{esc(ref[field])}</p>')
    sections.append('<p>'+esc(RULE_NOTE)+'</p><p>规则版本：'+esc(REFERENCE_VERSION)+'</p><p><b>定义出处（不代表来源认可工程分档）</b></p>')
    for source in ref['sources']:
        title=esc(source['title']);url=esc(source['url'])
        sections.append(f'<p><a href="{url}">{title}</a></p>' if url else '<p>'+title+'</p>')
    return ''.join(sections)


def english_channel_text(evaluation):
    from .i18n import tr
    label=tr(evaluation.get('label',''),'en')
    lines=[f"{label}: {evaluation.get('valid',0)}/{evaluation.get('total',0)} valid measurements."]
    if evaluation.get('median') is not None:
        lines.append(f"Median {evaluation['median']:.6g}; range {evaluation['min']:.6g}–{evaluation['max']:.6g} {evaluation['unit']}; valid coverage {evaluation.get('coverage_pct',0):.1f}%.")
    status=evaluation.get('status')
    if status=='informational':lines.append('Compare only matching patterns, methods, channels and directions; this is not an absolute equipment grade.')
    elif status in {'good','watch','poor'}:lines.append('MUTEX engineering guidance is a project suggestion, not an industry acceptance criterion.')
    elif status in {'pass','fail'}:lines.append('This assessment applies only to the explicitly configured user target.')
    elif status=='needs_target':lines.append('Set a unit-bearing acceptance target for your application; no universal passing value is assumed.')
    from ..analysis_audit import reason_description
    for code,count in evaluation.get('missing_reasons',{}).items():lines.append(f"Missing: {reason_description(code,'en')} ({count}).")
    for text,count in evaluation.get('limitations',{}).items():lines.append(f"Limitation: {tr(text,'en')} ({count}).")
    return '\n'.join(lines)


def english_reference_summary(key,reference=None):
    ref=reference or reference_for(key);bands=ref.get('bands');unit=ref.get('unit','')
    if ref.get('goal'):
        goal=ref['goal'];bounds=[]
        if 'min' in goal:bounds.append(f"≥ {goal['min']:.6g}")
        if 'max' in goal:bounds.append(f"≤ {goal['max']:.6g}")
        target_unit=ref.get('goal_unit') or (goal.get('unit') if goal.get('unit')!='native' else unit) or unit
        return 'User target: '+('|value| ' if goal.get('absolute',ref.get('absolute',False)) else '')+' and '.join(bounds)+' '+target_unit+'. Each valid measurement is checked; missing or limited data cannot establish an overall pass.'
    if bands:
        good,watch=bands;symbol='≥' if ref.get('mode')=='high' else '≤'
        quantity='|value|' if ref.get('absolute') else '|value − 100|' if ref.get('mode')=='distance100' else 'value'
        return f'MUTEX guidance: {quantity} {symbol} {good:g} {unit} good; {symbol} {watch:g} {unit} watch; otherwise review. Not an industry pass/fail limit.'
    if key in FREQUENCY_METRICS:return 'Nyquist reference: 0.5 cy/px. Response thresholds define the metric; they are not acceptance limits.'
    if key=='clipping_fraction':return 'Unclipped reference: 0 (ratio 0–1). The configured maximum_clip_fraction determines rejection.'
    return 'No universal acceptance limit. Compare like-for-like measurements or configure an explicit user target.'


def english_reference_html(key,reference=None,evaluation=None):
    from .i18n import metric_label,metric_description,tr
    esc=lambda value:html.escape(str(value),quote=True)
    ref=reference or reference_for(key)
    sections=[f'<h3>{esc(metric_label(key,"en"))}</h3>']
    if evaluation:sections.append('<p><b>'+esc(tr(evaluation['label'],'en'))+'</b></p><p>'+esc(english_channel_text(evaluation)).replace('\n','<br>')+'</p>')
    sections.extend([
        '<p><b>Reference</b><br>'+esc(english_reference_summary(key,ref))+'</p>',
        '<p><b>Method and prerequisites</b><br>'+esc(metric_description(key,'en'))+'</p>',
        '<p><b>Assessment criteria</b><br>Check measurement validity first. Compare the same pattern, method, channel and direction. Missing values are not zero; chart-limited results are measured lower bounds. Engineering bands are project guidance. A user-defined target takes precedence.</p>',
        '<p><b>Recommended checks</b><br>Inspect native-pixel profiles, registration, clipping, input transfer, aliasing and calibration. Use sufficient response coverage and a focus sequence when an axial optimum is required.</p>',
        '<p>Unknown transfer functions give input-signal response. Square-wave CTF and sinusoidal MTF must be interpreted separately. Physical units require appropriate calibration. These results do not establish ISO, FADGI or manufacturer certification.</p>',
        '<p>Rule version: '+esc(REFERENCE_VERSION)+'</p><p><b>Definition sources</b></p>'])
    for source in ref.get('sources',[]):
        title='MUTEX · Project measurement definitions and engineering guidance' if source['title'].startswith('MUTEX') else source['title']
        sections.append(f'<p><a href="{esc(source["url"])}">{esc(title)}</a></p>' if source.get('url') else '<p>'+esc(title)+'</p>')
    return ''.join(sections)


class GoalNumber(QLineEdit):
    """Preserve an imported target exactly until the user actually edits it."""
    def __init__(self):
        super().__init__();validator=QDoubleValidator(self);validator.setLocale(QLocale.c())
        validator.setNotation(QDoubleValidator.Notation.ScientificNotation);self.setValidator(validator)
        self.setPlaceholderText('例如 0.25 或 1e-7');self.setValue(0)

    def setValue(self,value):
        self._original=value;self._original_text=repr(value);self.setText(self._original_text)

    def value(self):
        if self.text()==self._original_text:return self._original
        try:value=float(self.text().strip())
        except ValueError:raise ValueError('请输入有限数值；可使用小数或科学计数法') from None
        if not math.isfinite(value):raise ValueError('目标不能为无穷或非数值')
        return value


class EvaluationDialog(QDialog):
    def retranslate_ui(self):
        if self._key:self.reference.setHtml(reference_html(self._key))
    def __init__(self,config,key=None,parent=None):
        super().__init__(parent);self.setWindowTitle('评价参考与自定义目标');self.resize(880,760)
        self.limits=copy.deepcopy(config.evaluation_limits);self._key=None;self._loading=False
        layout=QVBoxLayout(self)
        note=QLabel('默认工程建议用于定位问题；自定义目标用于你的验收要求。修改评价不重测原像素，应用后重新导出报告即可。')
        note.setWordWrap(True);layout.addWidget(note)
        self.engineering=QCheckBox('启用明确标注的 MUTEX 工程分档（非行业合格线）');self.engineering.setChecked(config.evaluation_engineering);layout.addWidget(self.engineering)
        self.metric_selector=QComboBox()
        for name,k in METRICS:self.metric_selector.addItem(name,k)
        layout.addWidget(self.metric_selector)
        self.reference=QTextBrowser();self.reference.setOpenExternalLinks(True);layout.addWidget(self.reference,1)
        form=QFormLayout();self.mode=QComboBox()
        for name,value in [('默认参考（不设置验收目标）','default'),('不低于下限','minimum'),('不高于上限','maximum'),('允许区间（含边界）','range')]:self.mode.addItem(name,value)
        form.addRow('该项目验收方式',self.mode)
        self.lower,self.upper=GoalNumber(),GoalNumber()
        self.lower.setObjectName('evaluationMinimum');self.upper.setObjectName('evaluationMaximum')
        form.addRow('下限',self.lower);form.addRow('上限',self.upper)
        self.unit=QComboBox();form.addRow('目标单位（独立于预览）',self.unit)
        self.absolute=QCheckBox('对绝对值应用目标；保留实测值的正负方向');form.addRow('',self.absolute)
        self.note=QLineEdit();self.note.setMaxLength(1000);self.note.setPlaceholderText('例如：本次翻拍要求 / 客户目标 / 标准条款及适用条件')
        form.addRow('目标说明',self.note);layout.addLayout(form)
        buttons=QHBoxLayout()
        for name,callback in [('恢复此项默认',self.reset_current),('导入目标…',self.import_limits),('导出目标…',self.export_limits)]:
            b=QPushButton(name);b.clicked.connect(callback);buttons.addWidget(b)
        buttons.addStretch();apply=QPushButton('应用到当前结果与后续分析');apply.setObjectName('primary');apply.clicked.connect(self.accept);buttons.addWidget(apply)
        close=QPushButton('取消');close.clicked.connect(self.reject);buttons.addWidget(close);layout.addLayout(buttons)
        self.metric_selector.currentIndexChanged.connect(self.change_metric);self.mode.currentIndexChanged.connect(self.mode_changed)
        self.metric_selector.setCurrentIndex(max(0,self.metric_selector.findData(key)));self.change_metric()

    def remember(self):
        if not self._key or self._loading:return
        mode=self.mode.currentData()
        if mode=='default':self.limits.pop(self._key,None);return
        goal={'unit':self.unit.currentData(),'absolute':self.absolute.isChecked(),'note':self.note.text().strip()}
        if mode in {'minimum','range'}:goal['min']=self.lower.value()
        if mode in {'maximum','range'}:goal['max']=self.upper.value()
        self.limits[self._key]=goal

    def change_metric(self):
        try:self.remember()
        except ValueError as exc:
            QMessageBox.warning(self,'评价目标无效',str(exc));self.metric_selector.blockSignals(True)
            self.metric_selector.setCurrentIndex(self.metric_selector.findData(self._key));self.metric_selector.blockSignals(False);return
        self._loading=True;self._key=self.metric_selector.currentData()
        spec=REFERENCES[self._key];goal=self.limits.get(self._key,{})
        self.reference.setHtml(reference_html(self._key));self.unit.clear()
        if self._key in FREQUENCY_METRICS:
            for unit in ['cy/px','lp/mm','DPI','LW/PH','LP/PH']:self.unit.addItem(unit,unit)
        elif self._key in {'best_focus','focus_offset'}:
            for name,unit in [('沿用序列单位','native'),('mm','mm'),('um','um'),('index','index')]:self.unit.addItem(name,unit)
        else:self.unit.addItem((spec.unit or {'mtf_area':'ratio','usaf_focus_score':'ratio','information_capacity_1d':'bits/px'}.get(self._key,'原生单位'))+'（原生）','native')
        self.unit.setCurrentIndex(max(0,self.unit.findData(goal.get('unit','cy/px' if self._key in FREQUENCY_METRICS else 'native'))))
        mode='range' if 'min' in goal and 'max' in goal else 'minimum' if 'min' in goal else 'maximum' if 'max' in goal else 'default'
        self.mode.setCurrentIndex(self.mode.findData(mode));self.lower.setValue(goal.get('min',0));self.upper.setValue(goal.get('max',spec.bands[0] if spec.bands else 1))
        self.absolute.setChecked(goal.get('absolute',spec.absolute));self.note.setText(goal.get('note',''))
        self._loading=False;self.mode_changed()

    def mode_changed(self):
        mode=self.mode.currentData();self.lower.setEnabled(mode in {'minimum','range'});self.upper.setEnabled(mode in {'maximum','range'})
        for widget in (self.unit,self.absolute,self.note):widget.setEnabled(mode!='default')

    def reset_current(self):
        self.mode.setCurrentIndex(0);self.limits.pop(self._key,None)

    def accept(self):
        try:self.remember();validate_limits(self.limits)
        except ValueError as exc:QMessageBox.warning(self,'评价目标无效',str(exc));return
        super().accept()

    def import_limits(self):
        path,_=QFileDialog.getOpenFileName(self,'导入带单位的评价目标','','MUTEX 目标 (*.json)')
        if not path:return
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if data.get('format')!='MUTEX evaluation goals' or data.get('version')!=1:raise ValueError('未知评价目标格式')
            limits=validate_limits(data['limits']);self._key=None;self.limits=limits;self.change_metric()
            self.engineering.setChecked(data.get('engineering_enabled',True))
        except (OSError,ValueError,KeyError) as exc:QMessageBox.warning(self,'导入目标失败',str(exc))

    def export_limits(self):
        try:self.remember();validate_limits(self.limits)
        except ValueError as exc:QMessageBox.warning(self,'评价目标无效',str(exc));return
        path,_=QFileDialog.getSaveFileName(self,'导出评价目标','MUTEX-evaluation-goals.json','MUTEX 目标 (*.json)')
        if path:
            from ..utils import atomic_json
            atomic_json(path,{'format':'MUTEX evaluation goals','version':1,'rule_version':REFERENCE_VERSION,
                              'engineering_enabled':self.engineering.isChecked(),'limits':self.limits})
