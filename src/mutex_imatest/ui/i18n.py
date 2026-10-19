"""Runtime presentation translation without mutating charts or measurement data.

The application historically constructs Chinese display strings directly.
This adapter translates widget presentation at explicit refresh boundaries;
stable item data, editable text, paths and chart names remain unchanged.
"""
from __future__ import annotations
import html
import re
import weakref
from functools import lru_cache
from PySide6.QtCore import QObject,Signal,QEvent,QTimer,QLocale,Qt,QLibraryInfo,QTranslator
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication,QWidget,QDialog,QMenu,QLabel,QAbstractButton,
    QGroupBox,QComboBox,QTabWidget,QTableWidget,QListWidget,QLineEdit,
    QPlainTextEdit,QTextBrowser,QAbstractSpinBox,QDialogButtonBox,QFileDialog)
from .preferences import UiPreferences,load_preferences,save_preferences
from .i18n_catalog import TEXT_EN,METRICS_EN

_language='zh_CN'
_controller=None
_protected_names=set()
_ITEM_TRANSLATION_ROLE=int(Qt.ItemDataRole.UserRole)+6110
_CJK=re.compile(r'[\u3400-\u9fff]')
# Keep user paths and filenames byte-for-byte even within surrounding messages.
_PROTECTED=re.compile(r'(?:[A-Za-z]:[\\/][^\n<>]*|[^\s<>"\']+\.(?:tiff?|jpe?g|png|bmp|webp|svg|pdf|arw|nef|raf|cr[23]|dng|json|mchart|mxtpl|mxasset|log|csv|zip|7z))',re.I)


def resolve_language(preference='system',locale_name=None):
    if preference not in {'system','zh_CN','en'}:
        raise ValueError('Invalid UI language')
    if preference!='system':return preference
    name=locale_name or QLocale.system().name()
    return 'zh_CN' if name.lower().startswith('zh') else 'en'


def current_language():return _language


@lru_cache(maxsize=1)
def _catalog():
    from ..analysis_catalog import METRIC_LABELS,METRIC_DESCRIPTIONS
    result=dict(TEXT_EN)
    for key,(name,description) in METRICS_EN.items():
        result[METRIC_LABELS[key]]=name
        result[METRIC_DESCRIPTIONS[key]]=description
    from ..analysis_audit import REASONS,REASONS_EN
    result.update({description:REASONS_EN[key] for key,description in REASONS.items() if key in REASONS_EN})
    from .main_window import METRIC_NAMES
    abbreviations={'ctf':'CTF','mtf':'MTF','rgb':'RGB','dpi':'DPI','ppi':'PPI','lw':'LW','ph':'PH','lp':'LP',
                   'rms':'RMS','esf':'ESF','lsf':'LSF','snr':'SNR','px':'px','mm':'mm','pct':'%'}
    for key,label in METRIC_NAMES.items():
        if label not in result:
            parts=key.split('_')
            result[label]=' '.join(abbreviations.get(part,part.capitalize() if i==0 else part) for i,part in enumerate(parts))
    return result


@lru_cache(maxsize=1)
def _replacement_pattern():
    return re.compile('|'.join(re.escape(key) for key in sorted(_catalog(),key=len,reverse=True) if _CJK.search(key)))


def _translate_plain(text,language):
    catalog=_catalog()
    if language=='zh_CN':
        # This also localizes Qt's standard English button captions when a
        # platform does not ship its own Qt translation catalogue.
        standard={'OK':'确定','Cancel':'取消','Save':'保存','Open':'打开','Close':'关闭',
                  'Yes':'是','No':'否','Apply':'应用','Reset':'重置','Help':'帮助',
                  'Discard':'放弃','Restore Defaults':'恢复默认'}
        return standard.get(text,text)
    if text in catalog:return catalog[text]
    if not _CJK.search(text):return text
    match=re.fullmatch(r'已勾选\s*(\d+)\s*项 · 一次分析全部生成\n点击项目切换显示；灰色项不可选',text)
    if match:return f'Checked {match[1]} analyses · One run generates all selected results\nClick an analysis to view it; unavailable items are disabled'
    match=re.fullmatch(r'USAF 矢量定位：(\d+)/(\d+) 单元通过原像素局部拟合。重复图案的绝对单元编号仍需核对标尺；未重采样测量像素。',text)
    if match:return f'USAF registration: {match[1]}/{match[2]} units passed native-pixel local fitting. Verify absolute IDs against the scale on repeated charts. Measurement pixels were not resampled.'
    # Longest phrase first prevents short labels from damaging a full help
    # sentence. Replacements stay within presentation text nodes only.
    return _replacement_pattern().sub(lambda match:catalog[match.group()],text)


def tr(text,language=None):
    """Translate a display string; never pass editable user content here."""
    if not isinstance(text,str) or not text:return text
    lang=language or _language
    if lang=='system':lang=resolve_language(lang)
    if lang not in {'zh_CN','en'}:raise ValueError('Invalid UI language')
    if text in _protected_names:return text
    if text in _catalog():return _translate_plain(text,lang)
    protected={}
    for index,value in enumerate(sorted(_protected_names,key=len,reverse=True)):
        if value and value in text:
            marker=f'\ue000MUTEX{index}\ue001';protected[marker]=value;text=text.replace(value,marker)
    if '<' in text and '>' in text:
        chunks=re.split(r'(<[^>]*>)',text)
        result=''.join(chunk if index%2 else _translate_protected(chunk,lang) for index,chunk in enumerate(chunks))
    else:result=_translate_protected(text,lang)
    for marker,value in protected.items():result=result.replace(marker,value)
    return result


def _translate_protected(text,language):
    output=[];position=0
    for match in _PROTECTED.finditer(text):
        output.append(_translate_plain(text[position:match.start()],language));output.append(match.group());position=match.end()
    output.append(_translate_plain(text[position:],language))
    return ''.join(output)


def metric_label(key,language=None):
    from ..analysis_catalog import METRIC_LABELS
    return METRICS_EN.get(key,(key,''))[0] if (language or _language)=='en' else METRIC_LABELS.get(key,key)


def metric_description(key,language=None):
    from ..analysis_catalog import METRIC_DESCRIPTIONS
    return METRICS_EN.get(key,('', 'View measurements and quality flags.'))[1] if (language or _language)=='en' else METRIC_DESCRIPTIONS.get(key,'查看该分析的测量结果和质量标志。')


class UiController(QObject):
    changed=Signal(str,str)

    def __init__(self,app,window,preferences=None):
        super().__init__(window)
        self.app=app;self.window=window
        self.preferences=preferences if preferences is not None else load_preferences()
        self.preferences.validate()
        self._sources=weakref.WeakKeyDictionary()
        self._models=weakref.WeakSet();self._dirty_models=weakref.WeakSet()
        self._pending=False;self._refreshing=False;self._force=False
        self._qt_translator=None;self._language=None;self._theme=None
        self._dialog_connections=weakref.WeakSet()
        self._disposed=False
        self._system_scheme=app.styleHints().colorScheme()
        self._updating_scheme=False
        app.installEventFilter(self)
        app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs,True)
        app.styleHints().colorSchemeChanged.connect(self._system_theme_changed)
        self.set_language(self.preferences.language,persist=False)
        self.set_theme(self.preferences.theme,persist=False)

    @property
    def language(self):return self._language

    @property
    def theme(self):return self._theme

    def _persist(self):
        if getattr(self.window,'persist_preferences',True):save_preferences(self.preferences)

    def set_language(self,language,persist=True):
        global _language
        effective=resolve_language(language)
        self.preferences.language=language;self._language=effective;_language=effective
        self.app.setProperty('mutexLanguage',effective)
        if self._qt_translator is not None:
            self.app.removeTranslator(self._qt_translator);self._qt_translator=None
        if effective=='zh_CN':
            translator=QTranslator(self)
            directory=QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
            if translator.load('qtbase_zh_CN',directory):
                self.app.installTranslator(translator);self._qt_translator=translator
        if persist:self._persist()
        self.translate_tree(self.window,force=True)
        for top in self.app.topLevelWidgets():
            if isinstance(top,QDialog) and top.isVisible():
                if hasattr(top,'retranslate_ui'):top.retranslate_ui()
                self.translate_tree(top,force=True)
        self.changed.emit(self.preferences.language,self.preferences.theme)

    def _resolve_theme(self,preference):
        if preference!='system':return preference
        self._updating_scheme=True
        try:
            self.app.styleHints().setColorScheme(Qt.ColorScheme.Unknown)
            self._system_scheme=self.app.styleHints().colorScheme()
        finally:self._updating_scheme=False
        return 'dark' if self._system_scheme==Qt.ColorScheme.Dark else 'light'

    def set_theme(self,theme,persist=True):
        from .style import apply_dark_theme,apply_light_theme,apply_widget_theme
        if theme not in {'system','light','dark'}:raise ValueError('Invalid UI theme')
        effective=self._resolve_theme(theme)
        self.preferences.theme=theme;self._theme=effective
        self._updating_scheme=True
        try:
            (apply_dark_theme if effective=='dark' else apply_light_theme)(self.app)
            # Let subsequent operating-system changes through while retaining
            # our complete readable palette and stylesheet for the current mode.
            if theme=='system':self.app.styleHints().setColorScheme(Qt.ColorScheme.Unknown)
        finally:self._updating_scheme=False
        apply_widget_theme(self.window,effective)
        for top in self.app.topLevelWidgets():
            if isinstance(top,QDialog) and top.isVisible():apply_widget_theme(top,effective)
        if persist:self._persist()
        self.changed.emit(self.preferences.language,self.preferences.theme)

    def _system_theme_changed(self,scheme):
        if self._updating_scheme or self._disposed:return
        self._system_scheme=scheme
        if self.preferences.theme=='system':
            QTimer.singleShot(0,lambda:self.set_theme('system',persist=False) if not self._disposed else None)

    def dispose(self,reset_locale=True):
        """Release application-wide hooks when their owning window closes."""
        global _controller,_language,_protected_names
        if self._disposed:return
        self._disposed=True;self._pending=False
        self.app.removeEventFilter(self)
        try:self.app.styleHints().colorSchemeChanged.disconnect(self._system_theme_changed)
        except (RuntimeError,TypeError):pass
        if self._qt_translator is not None:
            self.app.removeTranslator(self._qt_translator);self._qt_translator=None
        if _controller is self:
            _controller=None
            if reset_locale:_language='zh_CN';_protected_names=set()

    def _set(self,obj,key,getter,setter):
        current=getter()
        if not isinstance(current,str) or not current:return
        record=self._sources.setdefault(obj,{})
        old=record.get(key)
        source=old[0] if old and current==old[1] else current
        translated=tr(source,self._language)
        if key=='html' and self._theme:
            from .style import themed_stylesheet
            translated=themed_stylesheet(translated,self._theme)
        record[key]=(source,translated)
        if translated!=current:setter(translated)

    def refresh(self,force=False):
        """Coalesce refresh requests; table cells are revisited only if dirty."""
        self._force=self._force or force
        if self._pending or self._refreshing or self._disposed:return
        self._pending=True
        QTimer.singleShot(0,self._flush)

    def _flush(self):
        self._pending=False
        if self._disposed:return
        try:
            force=self._force;self._force=False
            self.translate_tree(self.window,force=force)
        except RuntimeError:
            # The owning window may have been deleted before this queued turn.
            return

    def eventFilter(self,watched,event):
        if self._disposed:return False
        if watched is self.window and event.type()==QEvent.Type.Close:
            self.dispose();return False
        if event.type()==QEvent.Type.Show and isinstance(watched,(QDialog,QMenu)):
            from .style import apply_widget_theme
            if isinstance(watched,QDialog):apply_widget_theme(watched,self._theme or 'light')
            self.translate_tree(watched,force=True)
            if isinstance(watched,QDialog):self._connect_dialog_updates(watched)
        return False

    def _connect_dialog_updates(self,dialog):
        from PySide6.QtWidgets import QProgressBar
        ref=weakref.ref(dialog)
        def changed(*_):
            def update():
                widget=ref()
                try:
                    if not self._disposed and widget is not None and widget.isVisible():self.translate_tree(widget)
                except RuntimeError:pass
            QTimer.singleShot(0,update)
        for widget in dialog.findChildren(QWidget):
            if widget in self._dialog_connections:continue
            signal=(widget.clicked if isinstance(widget,QAbstractButton) else
                    widget.currentIndexChanged if isinstance(widget,QComboBox) else
                    widget.valueChanged if isinstance(widget,QProgressBar) else
                    widget.textChanged if isinstance(widget,QLineEdit) else None)
            if signal is not None:signal.connect(changed);self._dialog_connections.add(widget)

    def _track_model(self,model):
        if model in self._models:return
        self._models.add(model);self._dirty_models.add(model)
        ref=weakref.ref(model)
        def dirty(*_):
            value=ref()
            if value is not None:self._dirty_models.add(value)
        model.dataChanged.connect(dirty);model.modelReset.connect(dirty);model.rowsInserted.connect(dirty)

    def _table(self,table,force):
        model=table.model();self._track_model(model)
        if not force and model not in self._dirty_models:return
        previous=model.blockSignals(True)
        try:
            for col in range(table.columnCount()):
                item=table.horizontalHeaderItem(col)
                if item:self._item(item,('header',col))
            # User-editable cells contain chart labels, filenames, JSON and
            # acceptance goals. They are data, never translation targets.
            readonly=table.editTriggers()==table.EditTrigger.NoEditTriggers
            if readonly:
                for row in range(table.rowCount()):
                    for col in range(table.columnCount()):
                        item=table.item(row,col)
                        if item:self._item(item,('cell',row,col),table=table,column=col)
        finally:model.blockSignals(previous)
        self._dirty_models.discard(model)

    def _item(self,item,key,table=None,column=None):
        # QTableWidgetItems have Python wrappers with lifetimes managed by Qt;
        # store source on the item, avoiding a persistent full-table copy.
        record=item.data(_ITEM_TRANSLATION_ROLE) or {}
        current=item.text();old=record.get('text')
        source=old[0] if old and current==old[1] else current
        if table is not None and column==0:
            # First-column region and file labels are user-defined. Metric
            # summary tables carry exact catalogue labels and can be localized.
            from ..analysis_catalog import METRIC_LABELS
            if source not in METRIC_LABELS.values():return
        translated=tr(source,self._language)
        if current!=translated:item.setText(translated)
        record['text']=(source,translated)
        tooltip=item.toolTip()
        old=record.get('tip')
        source=old[0] if old and tooltip==old[1] else tooltip
        translated=tr(source,self._language)
        if tooltip!=translated:item.setToolTip(translated)
        record['tip']=(source,translated)
        from PySide6.QtGui import QStandardItem
        if isinstance(item,QStandardItem):item.setData(record,_ITEM_TRANSLATION_ROLE)
        else:item.setData(_ITEM_TRANSLATION_ROLE,record)

    def translate_tree(self,window=None,force=False):
        if self._refreshing or self._disposed:return
        self._refreshing=True
        try:self._translate_tree(window or self.window,force)
        finally:self._refreshing=False

    def _translate_tree(self,window,force):
        global _protected_names
        from pathlib import Path
        names={str(c.name) for c in getattr(self.window,'charts',[]) if c.name}
        names.update(Path(e['path']).name for e in getattr(self.window,'entries',[]) if e.get('path'))
        names.update(str(g.get('note')) for g in getattr(getattr(self.window,'config',None),'evaluation_limits',{}).values() if isinstance(g,dict) and g.get('note'))
        _protected_names=names
        from .style import themed_stylesheet
        objects=[window,*window.findChildren(QWidget),*window.findChildren(QAction)]
        from .metric_checklist import STATUS_ROLE
        for obj in objects:
            if obj.property('keepUiText'):continue
            if isinstance(obj,QAction):
                self._set(obj,'text',obj.text,obj.setText)
                self._set(obj,'tip',obj.toolTip,obj.setToolTip)
                self._set(obj,'status',obj.statusTip,obj.setStatusTip)
                continue
            self._set(obj,'title',obj.windowTitle,obj.setWindowTitle)
            if obj.__class__.__name__!='TemplatePreview':self._set(obj,'tip',obj.toolTip,obj.setToolTip)
            self._set(obj,'status',obj.statusTip,obj.setStatusTip)
            if isinstance(obj,(QLabel,QAbstractButton)):
                self._set(obj,'text',obj.text,obj.setText)
            if isinstance(obj,QGroupBox):self._set(obj,'group',obj.title,obj.setTitle)
            if isinstance(obj,QLineEdit):self._set(obj,'placeholder',obj.placeholderText,obj.setPlaceholderText)
            if isinstance(obj,QAbstractSpinBox):
                if hasattr(obj,'specialValueText'):self._set(obj,'special',obj.specialValueText,obj.setSpecialValueText)
            if isinstance(obj,QTabWidget):
                for i in range(obj.count()):
                    self._set(obj,('tab',i),lambda i=i:obj.tabText(i),lambda value,i=i:obj.setTabText(i,value))
            if isinstance(obj,QComboBox):
                skip=obj.__class__.__name__=='TemplateComboBox'
                previous=obj.blockSignals(True)
                try:
                    for i in range(obj.count()):
                        if not skip and (obj.objectName()!='languageChoice' or obj.itemData(i)=='system'):
                            self._set(obj,('choice',i),lambda i=i:obj.itemText(i),lambda value,i=i:obj.setItemText(i,value))
                        self._set(obj,('choice-tip',i),lambda i=i:obj.itemData(i,Qt.ItemDataRole.ToolTipRole),lambda value,i=i:obj.setItemData(i,value,Qt.ItemDataRole.ToolTipRole))
                finally:obj.blockSignals(previous)
            if obj.__class__.__name__=='MetricChecklist':
                model=obj.model();previous=model.blockSignals(True)
                try:
                    for i in range(model.rowCount()):
                        item=model.item(i);self._item(item,('metric',i))
                finally:model.blockSignals(previous)
                obj.viewport().update()
            if isinstance(obj,QListWidget):
                # Chart-manager list items are chart names. Image-queue labels
                # put the filename on line 1 and generated state on later lines.
                for i in range(obj.count()):
                    item=obj.item(i);text=item.text()
                    record=item.data(_ITEM_TRANSLATION_ROLE) or {};old=record.get('text')
                    source=old[0] if old and text==old[1] else text
                    first,separator,rest=source.partition('\n')
                    translated=first+separator+tr(rest,self._language) if separator else first
                    if translated!=text:item.setText(translated)
                    record['text']=(source,translated);item.setData(_ITEM_TRANSLATION_ROLE,record)
            if isinstance(obj,QTableWidget):self._table(obj,force)
            if isinstance(obj,QPlainTextEdit) and obj.isReadOnly() and obj is not getattr(self.window,'logs',None):
                self._set(obj,'plain',obj.toPlainText,obj.setPlainText)
            # Read-only HTML references and assessments preserve markup and
            # original numeric values, units, links and user goals.
            if isinstance(obj,QTextBrowser):self._set(obj,'html',obj.toHtml,obj.setHtml)
            if hasattr(obj,'getPlotItem') and hasattr(obj,'getAxis'):
                for name in ['bottom','left','top','right']:
                    axis=obj.getAxis(name)
                    self._set(axis,'plot-label',lambda a=axis:a.labelText,
                              lambda value,a=axis:a.setLabel(text=value,units=a.labelUnits,**a.labelStyle))
            if self._theme:
                current=obj.styleSheet();record=getattr(obj,'_mutex_style_source',None)
                if record is None or current!=record[1]:record=(current,current)
                transformed=themed_stylesheet(record[0],self._theme)
                if current!=transformed:obj.setStyleSheet(transformed)
                obj._mutex_style_source=(record[0],transformed)


def install_ui(app,window,preferences=None):
    """Install once per window; the supplied preference object is kept by reference."""
    global _controller
    existing=getattr(window,'ui_controller',None)
    if isinstance(existing,UiController) and not existing._disposed:return existing
    if _controller is not None:_controller.dispose(reset_locale=False)
    controller=UiController(app,window,preferences)
    window.ui_controller=controller;_controller=controller
    return controller


def translate_tree(window=None,force=False):
    controller=getattr(window,'ui_controller',None) if window is not None else _controller
    if controller is not None:controller.translate_tree(window,force=force)


def set_language(language):
    if _controller is None:raise RuntimeError('UI controller is not installed')
    _controller.set_language(language)


def set_theme(theme):
    if _controller is None:raise RuntimeError('UI controller is not installed')
    _controller.set_theme(theme)
