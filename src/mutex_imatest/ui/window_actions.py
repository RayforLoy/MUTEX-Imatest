"""Presentation preferences and editing commands, independent of measurement."""
from pathlib import Path
import json
from PySide6.QtCore import Qt,QUrl,QSignalBlocker
from PySide6.QtGui import QAction,QActionGroup,QDesktopServices,QKeySequence
from PySide6.QtWidgets import QApplication,QFileDialog,QMenu,QListWidgetItem


class WindowActionsMixin:
    def extra_action(self,menu,title,callback,*,key=None,shortcut=None,checkable=False):
        action=QAction(title,self);action.setCheckable(checkable)
        if key:action.setObjectName(key)
        if shortcut:action.setShortcut(shortcut)
        (action.toggled if checkable else action.triggered).connect(callback);menu.addAction(action)
        return action

    def build_presentation_menus(self,help_menu):
        self.edit_menu=QMenu('编辑',self)
        self.display_menu=QMenu('显示',self)
        for menu in [self.edit_menu,self.display_menu]:
            self.menuBar().insertMenu(self.template_menu.menuAction(),menu)
        self.copy_point_action=self.extra_action(self.edit_menu,'复制当前测点结果',self.copy_point_result,key='copyPoint')
        self.copy_table_action=self.extra_action(self.edit_menu,'复制测量表（TSV）',self.copy_measurement_table,key='copyTable')
        self.extra_action(self.edit_menu,'复制当前图像路径',self.copy_image_path,key='copyImagePath')
        self.edit_menu.addSeparator()
        self.extra_action(self.edit_menu,'全选图像',self.images.selectAll,key='selectImages')
        self.remove_images_action=self.extra_action(self.edit_menu,'从队列移除选中图像',self.remove_selected_images,key='removeImages')
        self.remove_images_action.setToolTip('只从当前队列移除，不删除源文件；任务运行时不可用。')
        self.edit_menu.addSeparator()
        self.extra_action(self.edit_menu,'全选可用分析项目',lambda:self.metric_selector.set_all_checked(True),key='selectAnalyses')
        self.extra_action(self.edit_menu,'清空分析选择',lambda:self.metric_selector.set_all_checked(False),key='clearAnalyses')
        self.edit_menu.aboutToShow.connect(self.update_edit_actions)

        self.language_menu=self.display_menu.addMenu('语言')
        self.language_group=QActionGroup(self);self.language_group.setExclusive(True);self.language_actions={}
        for title,value in [('跟随系统','system'),('简体中文','zh_CN'),('English','en')]:
            a=self.extra_action(self.language_menu,title,lambda checked=False,v=value:self.set_ui_language(v) if checked else None,checkable=True)
            a.setData(value);self.language_group.addAction(a);self.language_actions[value]=a
        self.theme_menu=self.display_menu.addMenu('主题')
        self.theme_group=QActionGroup(self);self.theme_group.setExclusive(True);self.theme_actions={}
        for title,value in [('跟随系统','system'),('浅色','light'),('深色','dark')]:
            a=self.extra_action(self.theme_menu,title,lambda checked=False,v=value:self.set_ui_theme(v) if checked else None,checkable=True)
            a.setData(value);self.theme_group.addAction(a);self.theme_actions[value]=a
        self.display_menu.addSeparator()
        self.overlay_action=self.extra_action(self.display_menu,'显示热力图',lambda checked:self.overlay.setChecked(checked),key='showHeatmap',checkable=True)
        self.overlay_action.setChecked(self.overlay.isChecked());self.overlay.toggled.connect(self.overlay_action.setChecked)
        self.annotation_action=self.extra_action(self.display_menu,'显示测点和数值',self.toggle_annotations,key='showAnnotations',checkable=True)
        self.annotation_action.setChecked(True)
        self.sidebar_action=self.extra_action(self.display_menu,'显示图像队列与分析项目',lambda v:self.main_splitter.widget(0).setVisible(v),key='showSidebar',checkable=True)
        self.sidebar_action.setChecked(True)
        self.settings_panel_action=self.extra_action(self.display_menu,'显示测量设置面板',lambda v:self.main_splitter.widget(2).setVisible(v),key='showSettingsPanel',checkable=True)
        self.settings_panel_action.setChecked(True)
        self.display_menu.addSeparator()
        self.extra_action(self.display_menu,'适合窗口',self.viewer.fit_image,shortcut='Ctrl+0')
        self.extra_action(self.display_menu,'原像素 100%',self.viewer.native_zoom,shortcut='Ctrl+1')
        for title,button in [('逆时针旋转 90°',self.rotate_left),('顺时针旋转 90°',self.rotate_right),
                             ('上下镜像',self.flip_vertical),('左右镜像',self.flip_horizontal),
                             ('快速对齐模板',self.quick_orientation),('原始方向',self.reset_orientation_button)]:
            self.extra_action(self.display_menu,title,button.click)
        self.display_menu.addSeparator()
        self.extra_action(self.display_menu,'查看计算日志',lambda:self.tabs.setCurrentWidget(self.logs))
        self.extra_action(self.display_menu,'重置窗口布局',self.reset_window_layout)

        self.settings_menu=QMenu('设置',self);self.menuBar().insertMenu(help_menu.menuAction(),self.settings_menu)
        self.extra_action(self.settings_menu,'分析参数…',self.show_analysis_settings)
        self.extra_action(self.settings_menu,'资源与解码设置…',self.performance_settings)
        self.settings_menu.addAction(self.evaluation_action)
        self.settings_menu.addSeparator()
        self.extra_action(self.settings_menu,'导入分析配置…',self.import_analysis_config)
        self.extra_action(self.settings_menu,'导出当前分析配置…',self.export_analysis_config)
        self.extra_action(self.settings_menu,'恢复默认分析参数',self.reset_analysis_config)
        self.settings_menu.addSeparator()
        self.extra_action(self.settings_menu,'打开设置目录',self.open_settings_directory)

    def setup_presentation(self):
        from .preferences import load_preferences
        from .i18n import install_ui
        self.ui_preferences=self._initial_ui_preferences or load_preferences()
        self.ui_controller=install_ui(QApplication.instance(),self,preferences=self.ui_preferences)
        self.ui_controller.changed.connect(lambda *args:self.sync_presentation_actions())
        self.language_choice.currentIndexChanged.connect(lambda i:self.set_ui_language(self.language_choice.itemData(i)))
        self.sync_presentation_actions()
        self.update_evaluation();self.refresh_presentation()

    def sync_presentation_actions(self):
        if not hasattr(self,'ui_preferences'):return
        language=self.ui_preferences.language;theme=self.ui_preferences.theme
        with QSignalBlocker(self.language_choice):self.language_choice.setCurrentIndex(self.language_choice.findData(language))
        for value,action in self.language_actions.items():
            with QSignalBlocker(action):action.setChecked(value==language)
        for value,action in self.theme_actions.items():
            with QSignalBlocker(action):action.setChecked(value==theme)

    def set_ui_language(self,value):
        if hasattr(self,'ui_controller') and value:
            self.ui_controller.set_language(value);self.sync_presentation_actions()
            if 0<=self.current_index<len(self.entries) and self.entries[self.current_index].get('result'):
                chosen=self.metric_selector.currentData();checked=self.metric_selector.checked_keys()
                self.populate_analysis_results(self.entries[self.current_index]['result'])
                self.metric_selector.set_checked_keys(checked);self.metric_selector.setCurrentIndex(self.metric_selector.findData(chosen))
            self.update_visuals();self.refresh_presentation()
            if self.viewer.metadata:self.on_zoom(self.viewer.zoom_scale()*100)
            if hasattr(self,'sharpening_warning'):self.sharpening_warning.retranslate()

    def set_ui_theme(self,value):
        if hasattr(self,'ui_controller'):
            self.ui_controller.set_theme(value);self.sync_presentation_actions()
            self.update_visuals();self.refresh_presentation()

    def refresh_presentation(self):
        if hasattr(self,'ui_controller'):self.ui_controller.refresh()

    def toggle_annotations(self,visible):
        for viewer in [self.viewer,self.reference_viewer]:
            viewer.show_annotations=visible
            for item in viewer.annotations:item.setVisible(visible)

    def reset_window_layout(self):
        self.sidebar_action.setChecked(True);self.settings_panel_action.setChecked(True)
        self.main_splitter.setSizes([310,850,290]);self.sidebar_split.setSizes([180,580])
        self.vertical_split.setSizes([570,260]);self.image_split.setSizes([1,1])
        self.viewer.fit_image();self.reference_viewer.fit_image()

    def update_edit_actions(self):
        result=self.entries[self.current_index].get('result') if 0<=self.current_index<len(self.entries) else None
        self.copy_point_action.setEnabled(bool(result and self.selected_region))
        self.copy_table_action.setEnabled(bool(self.table.rowCount()))
        self.remove_images_action.setEnabled(bool(self.images.selectedItems()) and not getattr(self.worker,'current',None) and not getattr(self.worker,'pending',None))

    def copy_point_result(self):
        text=self.detail.toPlainText()
        if text:QApplication.clipboard().setText(text)

    def copy_image_path(self):
        if 0<=self.current_index<len(self.entries):QApplication.clipboard().setText(str(self.entries[self.current_index]['path']))

    def copy_measurement_table(self):
        headers=[self.table.horizontalHeaderItem(c).text() if self.table.horizontalHeaderItem(c) else '' for c in range(self.table.columnCount())]
        clean=lambda s:str(s).replace('\t',' ').replace('\r',' ').replace('\n',' ')
        lines=['\t'.join(map(clean,headers))]
        for row in range(self.table.rowCount()):
            lines.append('\t'.join(clean(self.table.item(row,col).text()) if self.table.item(row,col) else '' for col in range(self.table.columnCount())))
        if len(lines)>1:QApplication.clipboard().setText('\n'.join(lines))

    def remove_selected_images(self):
        if getattr(self.worker,'current',None) or getattr(self.worker,'pending',None):
            self.status_text.setText('请等待任务完成，或取消任务后再移除图像');return
        selected={self.images.row(item) for item in self.images.selectedItems()}
        if not selected:return
        old_index=self.current_index
        self.images.blockSignals(True)
        for index in sorted(selected,reverse=True):
            self.entries.pop(index);self.images.takeItem(index)
        self.images.blockSignals(False);self.selected_region=None;self.compare_index=None
        # Jobs are finished here; obsolete row indices must not attach to a new image.
        self.jobs.clear()
        if self.entries:
            index=max(0,min(old_index-sum(i<old_index for i in selected),len(self.entries)-1))
            self.current_index=-1;self.images.setCurrentRow(index);self.select_entry(index)
        else:
            self.current_index=-1
            for viewer in [self.viewer,self.reference_viewer]:viewer.clear_image()
            self.reference_viewer.hide();self.curve.clear();self.table.setRowCount(0);self.batch_table.setRowCount(0)
            self.detail.clear();self.summary_value.setText('—');self.summary_label.setText('选择模板后分析')
            self.summary_info.clear();self.coverage_notice.hide();self.resolution_map_button.hide()
        self.refresh_compare();self.update_edit_actions();self.refresh_presentation()

    def show_analysis_settings(self):
        self.settings_panel_action.setChecked(True);self.mode.setCurrentIndex(1)
        scroll=self.advanced.parentWidget()
        while scroll is not None:
            if hasattr(scroll,'ensureWidgetVisible'):
                scroll.ensureWidgetVisible(self.advanced);break
            scroll=scroll.parentWidget()

    def apply_analysis_config(self,config):
        self.config=config
        if not any(c.id==config.chart_id or config.chart_id in c.aliases for c in self.charts):self.config.chart_id=self.current_chart().id
        self.restore_settings();self.chart_changed(preserve_registration=True);self.refresh_presentation()

    def import_analysis_config(self):
        path,_=QFileDialog.getOpenFileName(self,'导入分析配置','','分析配置 (*.json)')
        if not path:return
        try:
            from ..config import AnalysisConfig
            config=AnalysisConfig.from_dict(json.loads(Path(path).read_text(encoding='utf-8-sig'))).validate()
            self.apply_analysis_config(config);self.add_log('分析配置已导入：'+path)
        except Exception as exc:self.message_error(exc)

    def export_analysis_config(self):
        path,_=QFileDialog.getSaveFileName(self,'导出当前分析配置','mutex-analysis-config.json','分析配置 (*.json)')
        if not path:return
        try:
            from ..utils import atomic_json
            atomic_json(path,self.snapshot_config().to_dict());self.add_log('分析配置已导出：'+path)
        except Exception as exc:self.message_error(exc)

    def reset_analysis_config(self):
        from ..config import AnalysisConfig
        current=self.config.to_dict()
        host={k:current[k] for k in ['cache_dir','memory_mb','cache_gb','tile_cache_mb','workers','mtf_mapper_path']}
        defaults=AnalysisConfig.from_dict(dict(AnalysisConfig().to_dict(),**host,chart_id=self.current_chart().id))
        self.apply_analysis_config(defaults);self.add_log('分析参数已恢复默认；源图像与已有结果保持原样')

    def open_settings_directory(self):
        from ..config import config_file
        path=config_file().parent;path.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
