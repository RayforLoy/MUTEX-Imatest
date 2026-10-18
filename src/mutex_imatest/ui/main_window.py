from __future__ import annotations
from pathlib import Path
from dataclasses import asdict
from collections import Counter
import copy,json,time,uuid
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QAction,QColor,QFont,QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,
 QSplitter,QFrame,QListWidget,QListWidgetItem,QFileDialog,QMessageBox,QTabWidget,QTableWidget,
 QTableWidgetItem,QHeaderView,QFormLayout,QCheckBox,QDoubleSpinBox,QSpinBox,QScrollArea,QGroupBox,
 QProgressBar,QPlainTextEdit,QSlider,QInputDialog,QAbstractItemView,QToolButton,QTextBrowser)
from .. import __version__
from ..config import load_config,save_config,AnalysisConfig
from ..models import AnalysisResult,ImageMetadata,IMAGE_EXTENSIONS,Measurement
from ..templates import available_charts,builtin_chart,load_chart,auto_edge_chart,library_dir,save_chart
from ..workers import WorkerManager
from ..watcher import SettledWatcher
from ..storage import Session
from ..heatmap import STOPS
from ..resolution import FREQUENCY_METRICS,MULTI_METRICS,CHANNEL_LABELS,view_result,metric_key,PAIRED_SHIFT_METRICS,RGB_SHIFT_METRICS
from ..capabilities import metric_availability
from ..chart_library import consolidate,recognizes,family_key
from ..analysis_catalog import METRICS,METRIC_LABELS,SEQUENCE_METRICS,RGB_METRICS,required_channels
from ..analysis_plan import summarize_selected
from ..preview_orientation import PreviewOrientation,orientation_from_homography
from .viewer import ImageViewer
from .style import STYLE
from .template_editor import TemplateEditor
from .template_widgets import TemplateComboBox,TemplatePreview
from .dialogs import PerformanceDialog,FocusSetupDialog
from .availability import configure_availability,set_availability
from .metric_checklist import MetricChecklist
from .evaluation_dialog import EvaluationDialog,reference_html
from ..evaluation import (evaluate_result,assess_channel,selected_rows,effective_reference,
                          channel_text,measurement_text,STATUS_COLORS)

FLAG_NAMES={"invalid_edge":"斜边角度 / 位置不合适","low_contrast":"对比度不足","clipped":"信号剪切",
 "aliasing_risk":"混叠风险","mtf50_above_nyquist":"MTF50 高于奈奎斯特","roi_outside":"区域越界",
 "transfer_unknown":"传递曲线未知","missing_frequency":"频率或标定不足","fit_failed":"拟合失败",
 "relative_response":"相对响应","edge_angle_advisory":"斜边角度需检查","single_frame_spatial_noise":"单帧空间噪声"}
FLAG_NAMES.update({"bars_not_separated":"三条暗线未完全分离","missing_reference":"缺少实测参考值","missing_calibration":"缺少适用标定",
 "sharpening_or_ringing":"锐化 / 振铃迹象","edge_fit_residual":"边缘拟合残差偏大","finite_target_size":"点源尺寸影响结果",
 "not_optical_mtf":"纹理频谱，非光学 MTF","target_geometry_affects_result":"图卡几何误差也会影响结果","clipping_advisory":"剪切需检查","registration_failed":"单元定位未通过"})
METRIC_NAMES={"mtf50":"MTF50","mtf50p":"MTF50P","mtf20":"MTF20","mtf10":"MTF10","ctf":"CTF","ctf50":"CTF50",
 "contrast":"两侧对比度","contrast_at_frequency":"指定频率对比度","target_frequency":"靶频率","clipping_fraction":"剪切比例",
 "ca_r_g_px":"R−G 法向位移","ca_b_g_px":"B−G 法向位移","edge_angle_deg":"斜边角度","edge_fit_rms_px":"拟合 RMS",
 "overshoot_pct":"过冲","undershoot_pct":"下冲","mean":"平均信号","std":"空间标准差","spatial_snr_db":"空间 SNR",
 "uniformity_pct":"不均匀性","delta_e_2000":"ΔE2000","resolved":"达到阈值且三线分离","detected_bar_count":"可见暗条数"}
METRIC_NAMES.update({key:name for name,key in METRICS})
METRIC_NAMES.update({'resolution_limit_lp_mm':'已确认分辨率 lp/mm','resolution_limit_dpi':'等效分辨 DPI','resolution_limit_lw_ph':'分辨率 LW/PH','resolution_upper_bound':'首个未通过频率','reference_ctf':'低频参考 CTF'})
FLAG_NAMES.update({'template_occluded':'模板文字遮挡','target_limited':'受图卡频率限制（下界）','invalid_ctf_reference':'低频参考不足','frequency_gap':'频率覆盖有间隔','derived_bilinear_resampling':'派生灰度：双线性重采样','rgb_alignment_failed':'RGB 对齐未通过'})
FLAG_NAMES.update({'target_mismatch':'图案 / 预期条纹未通过核验','star_geometry_invalid':'星图投影几何不适用',
 'reference_frequency_approximate':'楔形频率来自参考栅格估计','wedge_aliasing_detected':'部分频率存在条纹混叠 / 伪分辨风险',
 'resolution_chart_limited':'受图卡频率范围限制（下界）'})
FLAG_NAMES['star_frequency_mismatch']='部分星图频率的预期基频失配；阈值仅采用连续有效段'
FLAG_NAMES.update({'bar_geometry_mismatch':'暗条间距 / 位置与靶频率不符','ctf_noise_limited':'内部条纹起伏不足以超过噪声'})
FLAG_NAMES['ctf_segment_after_clipping']='CTF 交点采用剪切频点之后的未剪切连续段'
FLAG_NAMES['strict_clipping_limits_curve']='剪切限制已确认分辨率的连续通过范围'
METRIC_NAMES.update({'roi_contrast':'区域整体对比度（含外白底，非 CTF）','ctf_gap_min':'较弱内部间隙 CTF',
                     'ctf_gap_max':'较强内部间隙 CTF','bar_spacing_error':'条纹间距相对误差','profile_noise_sigma':'平均剖面噪声估计'})
METRIC_NAMES.update({'halo_overshoot_pct':'可检出亮侧光晕','halo_undershoot_pct':'可检出暗侧光晕','halo_noise_floor_pct':'光晕检测下限',
                     'halo_element_count':'参与光晕检测的元素数','halo_edge_count':'光晕检测边缘数'})
FLAG_NAMES['halo_insufficient_evidence']='低频边缘证据不足，不能判断锐化 / 振铃'
FLAG_NAMES['directional_resolution_incomplete']='双向连续分辨率证据不完整'
FLAG_NAMES['outside_image']='图像未覆盖该单元'
FLAG_NAMES['insufficient_contiguous_support']='连续有效频率证据不足'

def label(text,name=None):
    widget=QLabel(text)
    if name:widget.setObjectName(name)
    return widget
def button(text,callback,primary=False):
    b=QPushButton(text);b.clicked.connect(callback)
    if primary:b.setObjectName("primary")
    return b
def plot_widget(xlabel="cy/px",ylabel="响应"):
    widget=pg.PlotWidget(background="w")
    widget.showGrid(x=True,y=True,alpha=.15);widget.setLabel("bottom",xlabel);widget.setLabel("left",ylabel)
    for axis in ["bottom","left"]:
        widget.getAxis(axis).setPen(pg.mkPen("#9babb6"));widget.getAxis(axis).setTextPen("#657986")
        widget.getAxis(axis).enableAutoSIPrefix(False)
    return widget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle("MUTEX Imatest · 扫描仪 / 翻拍调焦");self.resize(1500,980)
        from ..fonts import configure_fonts
        configure_fonts()
        self.setMinimumSize(1100,760);self.setStyleSheet(STYLE)
        self.config=load_config();self.entries=[];self.jobs={};self.focus_data=None;self.session=None;self.persist_preferences=True
        self.charts=available_charts();self.current_index=-1;self.professional=False;self.compare_index=None;self.selected_region=None
        self.worker=WorkerManager(self);self.worker.event.connect(self.job_event);self.worker.idle.connect(self.jobs_idle)
        self.watcher=SettledWatcher(self);self.watcher.file_ready.connect(self.watch_file);self.watcher.error.connect(self.log_error)
        self.build_ui();self.build_menu();self.restore_settings()
        self.chart_combo.currentIndexChanged.connect(self.chart_changed)
        self.chart_changed(preserve_registration=True)
        self.setAcceptDrops(True)
        self.add_log("就绪。导入图像 → 选择图卡 → 检查配准 → 分析 → 比较焦位。")
    def build_ui(self):
        root=QWidget();self.setCentralWidget(root);outer=QVBoxLayout(root);outer.setContentsMargins(20,15,20,12);outer.setSpacing(10)
        header=QHBoxLayout();brand=QVBoxLayout();brand.addWidget(label("MUTEX Imatest","brand"));brand.addWidget(label("扫描仪 / 翻拍调焦 · 原精度光学测量","subtitle"));header.addLayout(brand);header.addStretch()
        self.state=label("离线 · 就绪","pill");header.addWidget(self.state)
        self.mode=QComboBox();self.mode.addItems(["简易模式","专业模式"]);self.mode.currentIndexChanged.connect(self.set_mode);header.addWidget(self.mode)
        outer.addLayout(header)
        toolbar=QHBoxLayout()
        self.import_button=button("＋ 导入图像",self.import_dialog);toolbar.addWidget(self.import_button)
        toolbar.addWidget(button("合成示例",self.open_demo))
        self.analyze_button=button("分析选中图像",self.analyze_selected,True);toolbar.addWidget(self.analyze_button)
        toolbar.addWidget(button("分析全部",self.analyze_all))
        toolbar.addWidget(button("整卡多频率 / RGB",self.analyze_whole_card))
        self.focus_button=button("焦位 / 垫高序列",self.setup_focus);toolbar.addWidget(self.focus_button)
        self.watch_button=button("监视文件夹",self.toggle_watch);toolbar.addWidget(self.watch_button)
        self.templates_button=QToolButton();self.templates_button.setText('图卡模板 ▾');self.templates_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.templates_button.setStyleSheet('QToolButton {background:white;border:1px solid #d8e2ea;border-radius:6px;padding:8px 12px;} QToolButton::menu-indicator {image:none;}')
        toolbar.addWidget(self.templates_button)
        toolbar.addStretch();self.export_button=button("导出报告",self.export_current);toolbar.addWidget(self.export_button)
        outer.addLayout(toolbar)
        self.main_splitter=QSplitter(Qt.Orientation.Horizontal);outer.addWidget(self.main_splitter,1)
        sidebar=QFrame();sidebar.setObjectName("sidebar");side=QVBoxLayout(sidebar);side.setContentsMargins(9,12,12,6)
        sidebar.setMinimumWidth(300)
        self.sidebar_split=QSplitter(Qt.Orientation.Vertical)
        queue_panel=QWidget();queue_layout=QVBoxLayout(queue_panel);queue_layout.setContentsMargins(0,0,0,0)
        queue_layout.addWidget(label("图像队列","section"));queue_layout.addWidget(label("支持 RAW · RGB 16-bit TIFF","subtitle"))
        self.images=QListWidget();self.images.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.images.currentRowChanged.connect(self.select_entry);queue_layout.addWidget(self.images,1)
        self.sidebar_split.addWidget(queue_panel)
        analysis_panel=QWidget();analysis_layout=QVBoxLayout(analysis_panel);analysis_layout.setContentsMargins(0,6,0,0)
        analysis_layout.addWidget(label('分析项目','section'))
        selection_buttons=QHBoxLayout();selection_buttons.addWidget(button('全选可用',lambda:self.metric_selector.set_all_checked(True)));selection_buttons.addWidget(button('清空',lambda:self.metric_selector.set_all_checked(False)));analysis_layout.addLayout(selection_buttons)
        self.analysis_selection_note=label('勾选后一次分析；点击项目查看结果','subtitle');self.analysis_selection_note.setWordWrap(True);analysis_layout.addWidget(self.analysis_selection_note)
        self.metric_selector=MetricChecklist()
        for text,value in METRICS:self.metric_selector.addItem(text,value)
        self.metric_selector.currentIndexChanged.connect(self.metric_view_changed);self.metric_selector.checkedChanged.connect(self.analysis_selection_changed)
        analysis_layout.addWidget(self.metric_selector,1);self.sidebar_split.addWidget(analysis_panel);self.sidebar_split.setSizes([180,580]);side.addWidget(self.sidebar_split,1)
        self.compare=QComboBox();self.compare.addItem("比较：未选择",None);self.compare.currentIndexChanged.connect(self.change_compare);side.addWidget(self.compare)
        side.addWidget(button("保存 / 打开会话",self.session_dialog))
        self.main_splitter.addWidget(sidebar)
        middle=QWidget();center=QVBoxLayout(middle);center.setContentsMargins(2,0,2,0);center.setSpacing(8)
        controls=QHBoxLayout();self.metric_title=label('从左侧选择分析项目','section');controls.addWidget(self.metric_title,2)
        self.channel=QComboBox();self.channel.addItems(["G","R","B","Y","Y_align"]);self.channel.currentIndexChanged.connect(self.update_visuals);controls.addWidget(self.channel)
        configure_availability(self.channel)
        for i in range(self.channel.count()):self.channel.setItemData(i,CHANNEL_LABELS[self.channel.itemText(i)],Qt.ItemDataRole.ToolTipRole)
        self.usaf_direction=QComboBox()
        for name,value in [("USAF 双向","both"),("USAF 竖线","vertical"),("USAF 横线","horizontal")]:self.usaf_direction.addItem(name,value)
        self.usaf_direction.setToolTip("按条纹方向查看和导出；原始分析结果保留两个方向")
        self.usaf_direction.currentIndexChanged.connect(self.update_visuals);controls.addWidget(self.usaf_direction)
        self.unit=QComboBox();self.unit.addItems(["cy/px","lp/mm","LW/PH"]);self.unit.currentIndexChanged.connect(self.update_visuals);controls.addWidget(self.unit)
        self.overlay=QCheckBox("热力图");self.overlay.setChecked(True);self.overlay.toggled.connect(self.update_visuals);controls.addWidget(self.overlay)
        controls.addWidget(button("适合窗口",lambda:self.viewer.fit_image()));controls.addWidget(button("100%",lambda:self.viewer.native_zoom()))
        center.addLayout(controls)
        orientation_row=QHBoxLayout();orientation_row.setSpacing(5)
        self.rotate_left=button('↶ 90°',lambda:self.viewer.rotate_preview(-1))
        self.rotate_right=button('↷ 90°',lambda:self.viewer.rotate_preview(1))
        self.flip_vertical=button('上下镜像',lambda:self.viewer.mirror_preview('vertical'))
        self.flip_horizontal=button('左右镜像',lambda:self.viewer.mirror_preview('horizontal'))
        self.quick_orientation=button('快速对齐模板',self.align_preview_to_template)
        self.reset_orientation_button=button('原始方向',lambda:self.viewer.reset_orientation())
        self.orientation_buttons=[self.rotate_left,self.rotate_right,self.flip_vertical,self.flip_horizontal,self.quick_orientation,self.reset_orientation_button]
        for b in self.orientation_buttons:
            b.setStyleSheet('padding: 5px 7px;');b.setEnabled(False);orientation_row.addWidget(b)
        self.rotate_left.setToolTip('预览逆时针旋转 90°')
        self.rotate_right.setToolTip('预览顺时针旋转 90°')
        self.flip_vertical.setToolTip('按当前画面上下镜像')
        self.flip_horizontal.setToolTip('按当前画面左右镜像')
        self.quick_orientation.setToolTip('根据模板配准恢复方向，限 90° 步进及必要镜像，再适合窗口')
        self.orientation_label=label('0°','subtitle');self.orientation_label.setToolTip('只改变预览；位置与 RGB 位移仍以原图坐标为准')
        orientation_row.addWidget(self.orientation_label);orientation_row.addStretch();center.addLayout(orientation_row)
        coverage_row=QHBoxLayout()
        self.coverage_notice=label('','subtitle');self.coverage_notice.setWordWrap(True)
        self.coverage_notice.setStyleSheet('background: #fff6e4; color: #77500f; border-left: 3px solid #c99b3b; padding: 6px;')
        self.coverage_notice.hide();coverage_row.addWidget(self.coverage_notice,1)
        self.resolution_map_button=button('查看已确认分辨率热力图',lambda:self.metric_selector.setCurrentIndex(self.metric_selector.findData('resolution_limit')))
        self.resolution_map_button.setToolTip('保留当前分析结果，切换到有明确三条纹判定的分辨率地图；不填补缺失的 CTF 交点。')
        self.resolution_map_button.hide();coverage_row.addWidget(self.resolution_map_button);center.addLayout(coverage_row)
        frequency_row=QHBoxLayout();frequency_row.addWidget(label('单频 CTF 频率'))
        self.usaf_frequency=QComboBox();self.usaf_frequency.setMinimumWidth(210);self.usaf_frequency.currentIndexChanged.connect(self.update_visuals);frequency_row.addWidget(self.usaf_frequency)
        self.gray_note=label('Y：对齐前灰度　Y_align：对齐后灰度；G 为位移参考','subtitle');frequency_row.addWidget(self.gray_note);frequency_row.addStretch();center.addLayout(frequency_row)
        self.vertical_split=QSplitter(Qt.Orientation.Vertical)
        self.viewer=ImageViewer();self.viewer.region_selected.connect(self.select_region);self.viewer.zoom_changed.connect(self.on_zoom);self.viewer.anchors_done.connect(self.set_anchors);self.viewer.error.connect(self.add_log)
        self.viewer.orientation_changed.connect(self.preview_orientation_changed)
        self.image_split=QSplitter(Qt.Orientation.Horizontal)
        self.image_split.addWidget(self.viewer)
        self.reference_viewer=ImageViewer();self.image_split.addWidget(self.reference_viewer);self.reference_viewer.hide()
        self.viewer.view_changed.connect(lambda state:self.sync_view(self.reference_viewer,state))
        self.reference_viewer.view_changed.connect(lambda state:self.sync_view(self.viewer,state))
        self.vertical_split.addWidget(self.image_split)
        self.legend=label("蓝 → 绿 → 黄 → 红  ·  数值从低到高  ·  白点为实测位置","subtitle")
        center.addWidget(self.legend)
        self.tabs=QTabWidget()
        self.tabs.setStyleSheet('QTabBar::tab { padding: 9px 10px; }')
        curves=QWidget();curve_layout=QHBoxLayout(curves);curve_layout.setContentsMargins(5,6,5,6)
        plot_column=QVBoxLayout();self.curve_selector=QComboBox()
        for name,key in [("主响应（按图案选择）","auto"),("整卡 CTF 原始对比度","ctf"),("整卡 CTF 归一化包络","ctf_response"),("斜边 SFR","sfr"),("边缘扩散 ESF","esf"),("线扩散 LSF","lsf"),("USAF 剖面","profile"),("星图响应","star"),("星图调制度","star_contrast"),("扫描行残差","line"),("1D 噪声功率谱","nps_1d"),("包围能量","encircled"),("纹理频谱","texture_spectrum")]:self.curve_selector.addItem(name,key)
        for name,key in [('星图基频一致性','star_coherence'),('楔形 CTF 响应','wedge'),('楔形原始对比度','wedge_contrast'),('楔形基频一致性','wedge_coherence'),('楔形条纹分离检查','wedge_separation'),('楔形检测暗条数','wedge_bar_count'),('楔形预期暗条数','wedge_expected_bars')]+[(f'星图扇区 {i+1}',f'star_sector_{i}') for i in range(8)]:self.curve_selector.addItem(name,key)
        self.curve_selector.addItem('棋盘格角点残差','grid_residual')
        from ..reports_curves import CURVE_NAMES
        for key in ['oecf','linear_response','scene_snr','radial_nps','illumination_grid','radial_distortion','radial_residual','texture_response','log_frequency_response','edge_nps','ring_profile']:
            self.curve_selector.addItem(CURVE_NAMES[key],key)
        self.curve_selector.currentIndexChanged.connect(self.change_curve)
        configure_availability(self.curve_selector)
        plot_column.addWidget(self.curve_selector)
        self.curve=plot_widget();self.curve.setMinimumHeight(150);plot_column.addWidget(self.curve,1);curve_layout.addLayout(plot_column,3)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMaximumWidth(285);curve_layout.addWidget(self.detail,1)
        self.tabs.addTab(curves,"CTF / SFR / 剖面")
        self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(["区域","图案","通道","指标","置信度","状态","位置 px","结果评价"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.cellClicked.connect(self.table_selected);self.tabs.addTab(self.table,"测量明细")
        focus_tab=QWidget();focus_layout=QHBoxLayout(focus_tab)
        self.focus_plot=plot_widget("焦位 / 高度","归一化评分");focus_layout.addWidget(self.focus_plot,2)
        self.focus_detail=QPlainTextEdit();self.focus_detail.setReadOnly(True);focus_layout.addWidget(self.focus_detail,1);self.tabs.addTab(focus_tab,"最佳焦位 / 场曲")
        self.logs=QPlainTextEdit();self.logs.setReadOnly(True);self.logs.setMaximumBlockCount(4000);self.tabs.addTab(self.logs,"日志")
        self.logs.setFont(QFont('Consolas',10));self.logs.setStyleSheet('QPlainTextEdit{background:#122a3a;color:#b9ecdf;border:1px solid #284b5c;padding:8px;}')
        self.optical_detail=QPlainTextEdit();self.optical_detail.setReadOnly(True);self.tabs.addTab(self.optical_detail,'整卡 / RGB 汇总')
        self.batch_table=QTableWidget(0,11);self.batch_table.setHorizontalHeaderLabels(['分析项目','通道','有效 / 总数','均值','最大值','单位','状态','中位数','最差值','结果评价','参考值 / 标准'])
        self.batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.batch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_table.cellClicked.connect(self.batch_result_selected);self.tabs.addTab(self.batch_table,'所选分析结果')
        self.evaluation_detail=QTextBrowser();self.evaluation_detail.setOpenExternalLinks(True)
        self.tabs.addTab(self.evaluation_detail,'评价与参考')
        self.vertical_split.addWidget(self.tabs);self.vertical_split.setSizes([580,230]);center.insertWidget(2,self.vertical_split,1)
        self.main_splitter.addWidget(middle)
        settings=QWidget();right=QVBoxLayout(settings);right.setContentsMargins(10,3,0,0)
        self.summary_card=QFrame();self.summary_card.setObjectName("card");card=QVBoxLayout(self.summary_card)
        card.addWidget(label("当前画面","section"));self.summary_value=label("—","bigValue");card.addWidget(self.summary_value)
        self.summary_label=label("等待有效测量","subtitle");self.summary_label.setWordWrap(True);card.addWidget(self.summary_label)
        self.evaluation_badge=button('查看评价与参考',lambda:self.tabs.setCurrentWidget(self.evaluation_detail));card.addWidget(self.evaluation_badge)
        self.summary_info=label("导入 48 位 TIFF 或相机 RAW");self.summary_info.setWordWrap(True);card.addWidget(self.summary_info);right.addWidget(self.summary_card)
        scroll=QScrollArea();scroll.setWidgetResizable(True);form_widget=QWidget();form_layout=QVBoxLayout(form_widget);form_layout.setContentsMargins(1,8,1,5)
        form_layout.addWidget(label("图卡与测量","section"))
        self.chart_combo=TemplateComboBox();self.refresh_charts();form_layout.addWidget(self.chart_combo)
        self.template_preview=TemplatePreview();form_layout.addWidget(self.template_preview);self.template_preview.set_chart(self.current_chart())
        form_layout.addWidget(button("编辑 / 导入图卡模板",self.edit_chart))
        registration_row=QHBoxLayout()
        registration_row.addWidget(button("四点配准",self.begin_anchors));registration_row.addWidget(button("恢复全幅",self.reset_anchors));form_layout.addLayout(registration_row)
        self.reg_note=label("默认图卡铺满画面；留白 / 裁切时使用四点配准。","subtitle");self.reg_note.setWordWrap(True);form_layout.addWidget(self.reg_note)
        form_layout.addWidget(button("寻找斜边候选",self.detect_edges))
        form=QFormLayout();self.transfer=QComboBox()
        for text,value in [("未知曲线（需检查）","unknown"),("线性 / 16-bit 原始输出","linear"),("sRGB 曲线","srgb"),("指定 Gamma","gamma"),("标定 OECF","oecf")]:self.transfer.addItem(text,value)
        self.analysis_channels=QComboBox();self.analysis_channels.addItems(["G","RGBY","RGB","R","B","Y"]);self.analysis_channels.setToolTip('RGBY：R / G / B / 对齐前灰度 / 对齐后灰度，五通道分别测量')
        self.analysis_channels.currentIndexChanged.connect(lambda:self.sync_metric_choices(result=self.entries[self.current_index]['result'] if 0<=self.current_index<len(self.entries) else None))
        self.clipping_policy=QComboBox()
        self.clipping_policy.addItem("严格排除剪切测点",True)
        self.clipping_policy.addItem("相对调焦：保留数值及剪切提示",False)
        self.clipping_policy.setToolTip("保留模式仅用于相对调焦比较；不会恢复剪切丢失的信息。更改后需重新分析。")
        form.addRow("输入曲线",self.transfer);form.addRow("测量通道",self.analysis_channels)
        form.addRow("剪切处理",self.clipping_policy)
        self.device=QComboBox();self.device.addItem("扫描仪","scanner");self.device.addItem("相机翻拍","camera");form.addRow("设备类型",self.device)
        form_layout.addLayout(form)
        self.warning=label("单张图像可观察位置差异；诊断倾斜 / 场曲需要焦位序列。","subtitle");self.warning.setWordWrap(True);form_layout.addWidget(self.warning)
        self.relative_focus_button=button("按相对调焦重新分析",self.analyze_relative_focus)
        self.relative_focus_button.hide();form_layout.addWidget(self.relative_focus_button)
        self.advanced=QGroupBox("专业设置");advanced_layout=QVBoxLayout(self.advanced);advanced_form=QFormLayout()
        self.gamma=QDoubleSpinBox();self.gamma.setRange(.1,5);self.gamma.setSingleStep(.1);self.gamma.setDecimals(2)
        self.oversampling=QComboBox();self.oversampling.addItems(["4","8"])
        self.window=QComboBox();self.window.addItems(["hamming","hann"])
        self.edge_fit=QComboBox();self.edge_fit.addItem("直线","linear");self.edge_fit.addItem("二次曲线","quadratic")
        self.ctf=QDoubleSpinBox();self.ctf.setRange(.01,.99);self.ctf.setSingleStep(.05);self.ctf.setDecimals(2)
        self.frequency=QDoubleSpinBox();self.frequency.setRange(.01,.49);self.frequency.setSingleStep(.01);self.frequency.setDecimals(3)
        self.threshold_mode=QComboBox();self.threshold_mode.addItem('相对低频 CTF','relative');self.threshold_mode.addItem('绝对输入对比度','absolute')
        self.picture_height=QSpinBox();self.picture_height.setRange(0,1000000);self.picture_height.setSpecialValueText('使用当前图像高度');self.picture_height.setSuffix(' px')
        self.rgb_max_shift=QDoubleSpinBox();self.rgb_max_shift.setRange(.1,128);self.rgb_max_shift.setSuffix(' px')
        self.registration=QComboBox()
        for text,value in [("全幅模板","template"),("整卡 / 局部自动配准","auto_chart"),("USAF 矢量配准","usaf"),("特征匹配（需检查）","features"),("四点锚定","anchors")]:self.registration.addItem(text,value)
        self.clip=QCheckBox("剪切过量的区域无效")
        self.clipping_policy.currentIndexChanged.connect(lambda:self.clip.setChecked(self.clipping_policy.currentData()))
        self.clip.toggled.connect(lambda checked:self.clipping_policy.setCurrentIndex(self.clipping_policy.findData(checked)))
        self.interpolation=QCheckBox("测试区域之间插值，并延伸至区域边界")
        self.interpolation.setToolTip('勾选：区域之间线性插值，外缘延续到有效测试区域边界；明显大空洞透明。\n取消：仅在各测试区域内显示该区域数值。')
        self.alpha=QSlider(Qt.Orientation.Horizontal);self.alpha.setRange(0,100);self.alpha.valueChanged.connect(self.update_visuals)
        self.scan_direction=QComboBox();self.scan_direction.addItems(["y","x"])
        for text,widget in [("Gamma",self.gamma),("ESF 过采样",self.oversampling),("LSF 窗",self.window),("边缘拟合",self.edge_fit),("CTF 判读阈值",self.ctf),("星图评分 cy/px",self.frequency),("配准方法",self.registration),("扫描方向",self.scan_direction),("叠加透明度",self.alpha)]:advanced_form.addRow(text,widget)
        advanced_layout.addLayout(advanced_form);advanced_layout.addWidget(self.clip);advanced_layout.addWidget(self.interpolation)
        advanced_form.addRow('USAF 阈值模式',self.threshold_mode);advanced_form.addRow('LW/PH 参考高度',self.picture_height);advanced_form.addRow('RGB 位移搜索上限',self.rgb_max_shift)
        advanced_layout.addWidget(button('导出对齐前 / 后灰度 TIFF',self.export_gray))
        advanced_layout.addWidget(button("导入 OECF 标定曲线",self.select_oecf));advanced_layout.addWidget(button("资源 / 解码设置",self.performance_settings))
        advanced_layout.addWidget(button("使用 MTF Mapper 复核",self.run_mapper))
        self.advanced.setVisible(False);form_layout.addWidget(self.advanced);form_layout.addStretch()
        scroll.setWidget(form_widget);right.addWidget(scroll,1);self.main_splitter.addWidget(settings)
        self.main_splitter.setSizes([310,850,290])
        footer=QHBoxLayout();self.status_text=label("就绪","subtitle");footer.addWidget(self.status_text,1)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);self.progress.setTextVisible(False);self.progress.setFixedWidth(220);footer.addWidget(self.progress)
        self.cancel_button=button("取消任务",self.cancel_jobs);self.cancel_button.setEnabled(False);footer.addWidget(self.cancel_button)
        self.zoom_label=label("预览缩放：—","subtitle");self.zoom_label.setToolTip('当前图像预览的缩放比例；100% 时一个原图像素对应一个显示像素。不是分析完成进度。')
        footer.addWidget(self.zoom_label);footer.addWidget(label(f"v{__version__}","subtitle"));outer.addLayout(footer)
    def build_menu(self):
        filemenu=self.menuBar().addMenu("文件")
        for title,callback in [("导入图像",self.import_dialog),("导入分析 JSON",self.open_result),("打开会话",self.open_session),("保存会话",self.save_session),("导出报告",self.export_current),("资源设置",self.performance_settings)]:
            action=QAction(title,self);action.triggered.connect(callback);filemenu.addAction(action)
        self.template_menu=self.menuBar().addMenu('图卡模板');self.templates_button.setMenu(self.template_menu)
        for title,callback in [('模板管理…',self.manage_templates),('新建 / 导入 SVG、PDF…',self.new_chart),('编辑当前模板…',self.edit_chart),('导入模板包…',self.import_chart_package),('导出当前模板（加密）…',self.export_chart_package)]:
            action=QAction(title,self);action.triggered.connect(callback);self.template_menu.addAction(action)
        self.official_chart_action=QAction('Imatest / 标准图卡兼容设置…',self)
        self.official_chart_action.triggered.connect(self.setup_official_chart);self.template_menu.addAction(self.official_chart_action)
        quality_menu=self.menuBar().addMenu('图像质量')
        self.workbench_action=QAction('图像质量工作台…',self);self.workbench_action.triggered.connect(self.open_workbench);quality_menu.addAction(self.workbench_action)
        quality_menu.addAction(self.official_chart_action)
        ccm_action=QAction('应用色彩矩阵 CCM…',self);ccm_action.triggered.connect(self.select_ccm);quality_menu.addAction(ccm_action)
        clear_ccm=QAction('清除当前 CCM',self);clear_ccm.triggered.connect(self.clear_ccm);quality_menu.addAction(clear_ccm)
        self.evaluation_action=QAction('评价参考与自定义目标…',self);self.evaluation_action.triggered.connect(self.edit_evaluation_goals);quality_menu.addAction(self.evaluation_action)
        helpmenu=self.menuBar().addMenu("帮助")
        action=QAction("测量限制与兼容性",self);action.triggered.connect(self.show_help);helpmenu.addAction(action)
        helpmenu.addAction(self.evaluation_action)
        self.logs_action=QAction('打开本次分析日志目录',self);self.logs_action.triggered.connect(self.open_diagnostics_folder);helpmenu.addAction(self.logs_action)
        self.ui_logs_action=QAction('打开界面错误日志目录',self);self.ui_logs_action.triggered.connect(self.open_ui_logs);helpmenu.addAction(self.ui_logs_action)
    def restore_settings(self):
        c=self.config
        self.transfer.setCurrentIndex(max(0,self.transfer.findData(c.transfer)));self.analysis_channels.setCurrentText(c.channels)
        self.device.setCurrentIndex(max(0,self.device.findData(c.device_mode)));self.gamma.setValue(c.gamma)
        self.oversampling.setCurrentText(str(c.oversampling));self.window.setCurrentText(c.window)
        self.edge_fit.setCurrentIndex(max(0,self.edge_fit.findData(c.edge_fit)));self.ctf.setValue(c.ctf_threshold)
        self.frequency.setValue(c.target_frequency);self.clip.setChecked(c.reject_clipping);self.interpolation.setChecked(c.interpolate)
        self.threshold_mode.setCurrentIndex(self.threshold_mode.findData(c.usaf_threshold_mode));self.picture_height.setValue(c.picture_height_px);self.rgb_max_shift.setValue(c.rgb_max_shift_px)
        self.clipping_policy.setCurrentIndex(self.clipping_policy.findData(c.reject_clipping))
        self.registration.setCurrentIndex(max(0,self.registration.findData(c.registration)));self.alpha.setValue(round(c.heatmap_alpha*100));self.scan_direction.setCurrentText(c.scan_direction)
        self.chart_combo.blockSignals(True)
        self.chart_combo.setCurrentIndex(next((i for i,chart in enumerate(self.charts) if recognizes(chart,c.chart_id)),0))
        self.chart_combo.blockSignals(False)
        self.sync_metric_choices(chart=self.current_chart())
        self.metric_selector.setCurrentIndex(max(0,self.metric_selector.findData(c.metric)))
        self.metric_selector.set_checked_keys(c.analysis_metrics)
        self.update_analysis_selection_note()
    def snapshot_config(self):
        data=self.config.to_dict()
        data.update(transfer=self.transfer.currentData(),channels=self.analysis_channels.currentText(),
          device_mode=self.device.currentData(),gamma=self.gamma.value(),oversampling=int(self.oversampling.currentText()),
          window=self.window.currentText(),edge_fit=self.edge_fit.currentData(),ctf_threshold=self.ctf.value(),
          target_frequency=self.frequency.value(),reject_clipping=self.clip.isChecked(),interpolate=self.interpolation.isChecked(),
          registration=self.registration.currentData(),heatmap_alpha=self.alpha.value()/100,
          metric=self.metric_selector.currentData(),analysis_metrics=self.metric_selector.checked_keys(),chart_id=self.chart_combo.currentData(),scan_direction=self.scan_direction.currentText())
        data.update(usaf_threshold_mode=self.threshold_mode.currentData(),picture_height_px=self.picture_height.value(),rgb_max_shift_px=self.rgb_max_shift.value())
        return AnalysisConfig.from_dict(data).validate()
    def set_mode(self,index):
        self.professional=index==1;self.advanced.setVisible(self.professional)
        if self.selected_region and hasattr(self,"tabs") and self.tabs.currentIndex()==0:self.select_region(self.selected_region)
    def refresh_charts(self,selected=None):
        self.charts=consolidate(self.charts)
        self.chart_combo.blockSignals(True)
        self.chart_combo.clear()
        for chart in self.charts:self.chart_combo.add_chart(chart)
        if selected:
            idx=next((i for i,chart in enumerate(self.charts) if recognizes(chart,selected)),0);self.chart_combo.setCurrentIndex(idx)
        self.chart_combo.blockSignals(False)
        if hasattr(self,'template_preview') and self.chart_combo.currentIndex()>=0:self.template_preview.set_chart(self.current_chart())
    def current_chart(self):return self.charts[self.chart_combo.currentIndex()]
    def chart_changed(self,*args,preserve_registration=False):
        chart=self.current_chart()
        self.template_preview.set_chart(chart)
        vector=any(isinstance(f,dict) and f.get("kind")=="usaf" for f in chart.fiducials)
        if vector and (not preserve_registration or self.registration.currentData() in {"template","usaf"}):
            self.registration.setCurrentIndex(self.registration.findData("usaf"))
            self.reg_note.setText("已选择 USAF 矢量配准；逐单元定位后测量原像素。")
        elif not vector and self.registration.currentData()=="usaf":
            self.registration.setCurrentIndex(self.registration.findData("template"))
        if not vector:
            reference=bool(not chart.id.startswith('mutex-synthetic') and chart.preview and Path(chart.preview).is_file() and any(r.enabled and r.kind in {'edge','star','wedge','grid'} for r in chart.regions))
            if reference and (not preserve_registration or self.registration.currentData() in {'template','auto_chart'}):
                self.registration.setCurrentIndex(self.registration.findData('auto_chart'))
                self.reg_note.setText('自动匹配整卡或局部；只分析可见且定位通过的区域。')
            elif not reference and self.registration.currentData()=='auto_chart':self.registration.setCurrentIndex(self.registration.findData('template'))
        self.sync_metric_choices(chart=chart)
        self.update_preview_controls()
        if self.current_index>=0:self.update_visuals()
    def sync_metric_choices(self,result=None,chart=None):
        # Metric compatibility is about available measurements, not validity:
        # clipped or failed results must retain their applicable metric and flags.
        available,full=metric_availability(chart or self.current_chart(),result,self.focus_data,self.analysis_channels.currentText(),planning=True)
        metadata=self.entries[self.current_index].get('metadata') if 0<=self.current_index<len(self.entries) else None
        if metadata and metadata.channels<3:
            for key in RGB_METRICS:available[key]='源图像不包含三个颜色通道'
        current=self.metric_selector.currentData()
        self.metric_selector.blockSignals(True);self.metric_selector.model().blockSignals(True)
        for i in range(self.metric_selector.count()):
            key=self.metric_selector.itemData(i);item=self.metric_selector.model().item(i)
            reason=available.get(key,'当前模板没有配置这种图案或测量所需参考值')
            name=METRIC_LABELS[key]
            if key in PAIRED_SHIFT_METRICS:
                name+='（二维幅值）' if full else '（斜边法向）'
            set_availability(self.metric_selector,i,key in available and not reason,reason,name)
        if current not in available or available[current]:
            preferred=['resolution_limit'] if full else ['mtf50','ctf50','contrast_at_frequency','mean','delta_e_2000','projective_residual_rms_px']
            fallback=next((key for key in preferred+[key for _,key in METRICS] if key in available and not available[key]),None)
            if fallback:self.metric_selector.setCurrentIndex(self.metric_selector.findData(fallback))
        if self.metric_selector.automatic_checks and not any(self.metric_selector.itemData(i) in (self.metric_selector.preferred_checks or set()) and self.metric_selector.model().item(i).isEnabled() for i in range(self.metric_selector.count())):
            self.metric_selector.preferred_checks={self.metric_selector.currentData()}
        self.metric_selector.apply_checks()
        summaries={item['metric']:item for item in (result.analysis_summary.get('items',[]) if result else [])}
        for i in range(self.metric_selector.count()):
            key=self.metric_selector.itemData(i);item=self.metric_selector.model().item(i)
            if not item.isEnabled():status=item.toolTip()
            elif key in SEQUENCE_METRICS:status='序列结果 · 使用上方“焦位 / 垫高序列”运行'
            elif key in summaries:
                rec=summaries[key];status=f"已生成 · {len(rec['channels'])} 通道 / {sum(c['valid'] for c in rec['channels'])} 测点" if rec['status']=='complete' else '已分析 · '+rec['reason']
            elif result and not result.analysis_summary:status='已有测量数据 · 勾选可纳入本轮汇总'
            else:status='本轮未勾选' if result else '待分析'
            self.metric_selector.set_status(i,status)
        self.metric_selector.model().blockSignals(False);self.metric_selector.blockSignals(False)
        self.metric_selector.viewport().update()
        self.metric_title.setText(self.metric_selector.currentText());self.update_analysis_selection_note()
        self.refresh_analysis_activity()
    def refresh_analysis_activity(self):
        if not 0<=self.current_index<len(self.entries):self.metric_selector.set_activity();return
        active=self.worker.current;pending={uid for uid,payload in self.worker.pending}
        chart=self.current_chart()
        candidates=[(uid,info) for uid,info in self.jobs.items() if info.get('index')==self.current_index and info.get('action')=='analyze' and (not info.get('chart_id') or recognizes(chart,info['chart_id']))]
        current=next(((uid,info) for uid,info in reversed(candidates) if active and uid==active['id'] and info.get('state') not in {'done','error','cancelled'}),None)
        current=current or next(((uid,info) for uid,info in reversed(candidates) if uid in pending),None)
        if current:
            uid,info=current;state='cancelling' if info.get('state')=='cancelling' else 'running' if active and uid==active['id'] else 'queued'
            self.metric_selector.set_activity(info.get('metrics',[]),state,info.get('progress'),info.get('message',''));return
        terminal=next((info for uid,info in reversed(candidates) if info.get('state') in {'error','cancelled'}),None)
        if terminal and self.entries[self.current_index].get('status') in {'需检查','已取消'}:
            self.metric_selector.set_activity(terminal.get('metrics',[]),terminal['state'],message=terminal.get('message',''))
        else:self.metric_selector.set_activity()
    def metric_view_changed(self,*args):
        self.metric_title.setText(self.metric_selector.currentText());self.update_evaluation();self.update_visuals()
    def update_analysis_selection_note(self):
        keys=self.metric_selector.checked_keys()
        self.analysis_selection_note.setText(f'已勾选 {len(keys)} 项 · 一次分析全部生成\n点击项目切换显示；灰色项不可选')
        self.analyze_button.setEnabled(bool(keys))
    def analysis_selection_changed(self):
        mode=required_channels(self.analysis_channels.currentText(),self.metric_selector.checked_keys())
        if mode!=self.analysis_channels.currentText():
            self.analysis_channels.setCurrentText(mode)
            self.add_log('已按勾选项目补齐测量通道：'+mode)
        self.update_analysis_selection_note()
    def populate_analysis_results(self,result):
        requested=result.analysis_summary.get('requested_metrics') or result.settings.get('analysis_metrics') or self.metric_selector.checked_keys()
        summary=summarize_selected(result,requested)
        self.batch_table.setRowCount(0)
        for rec in summary.get('items',[]):
            for ch in rec['channels'] or [{}]:
                row=self.batch_table.rowCount();self.batch_table.insertRow(row)
                texts=[rec['name'],ch.get('channel','—'),f"{ch.get('valid',0)} / {ch.get('total',0)}",
                       f"{ch['mean']:.5g}" if ch.get('mean') is not None else '—',f"{ch['max']:.5g}" if ch.get('max') is not None else '—',ch.get('unit',''),
                       '已生成' if ch.get('valid') else rec['reason'] or '无有效数据']
                assessment=ch.get('evaluation',{});ref=rec.get('reference',{})
                texts += [f"{assessment[k]:.5g}" if assessment.get(k) is not None else '—' for k in ['median','worst']]
                texts += [assessment.get('label','无法评价'),ref.get('reference','')]
                for col,text in enumerate(texts):
                    item=QTableWidgetItem(text);item.setData(Qt.ItemDataRole.UserRole,(rec['metric'],ch.get('channel')))
                    if col==9:
                        item.setForeground(QColor(STATUS_COLORS.get(assessment.get('status'),'#798793')))
                        item.setToolTip(channel_text(assessment) if assessment else rec['reason'])
                    if col==10:item.setToolTip(ref.get('reference','')+'\n'+ref.get('criteria','')+'\n'+ref.get('basis',''))
                    self.batch_table.setItem(row,col,item)
        self.batch_table.resizeColumnsToContents();self.batch_table.horizontalHeader().setStretchLastSection(True)
        self.batch_table.setColumnWidth(10,330)

    def update_evaluation(self,result=None,key=None,channel=None):
        if not hasattr(self,'evaluation_detail'):return
        key=key or self.metric_selector.currentData()
        if not key:return
        if result is None and 0<=self.current_index<len(self.entries):
            result=self.direction_result(self.entries[self.current_index].get('result'))
        assessment=None;ref=None
        if result:
            rows=selected_rows(result,key);channel=channel or self.channel.currentText()
            assessment=assess_channel(result,key,[m for m in rows if m.channel==channel],self.unit.currentText() if key in FREQUENCY_METRICS else None)
            ref=effective_reference(result,key)
            self.evaluation_badge.setText(assessment['label']+' · 查看依据')
            self.evaluation_badge.setToolTip(channel_text(assessment))
            color=STATUS_COLORS[assessment['status']]
            self.evaluation_badge.setStyleSheet(f'QPushButton {{ color:{color};border:1px solid {color};background:white;padding:6px;text-align:left; }}')
        else:
            self.evaluation_badge.setText('查看评价与参考');self.evaluation_badge.setStyleSheet('')
        self.evaluation_detail.setHtml(reference_html(key,ref,assessment))

    def edit_evaluation_goals(self):
        dialog=EvaluationDialog(self.config,self.metric_selector.currentData(),self)
        if not dialog.exec():return
        self.config.evaluation_limits=copy.deepcopy(dialog.limits)
        self.config.evaluation_engineering=dialog.engineering.isChecked()
        self.config.validate()
        if self.persist_preferences:save_config(self.config)
        if self.focus_data:
            from ..evaluation import evaluate_focus
            self.focus_data['evaluation_summary']=evaluate_focus(self.focus_data,self.config.to_dict())
        if 0<=self.current_index<len(self.entries):
            entry=self.entries[self.current_index];result=entry.get('result')
            if result:
                result.settings.update(evaluation_limits=copy.deepcopy(dialog.limits),evaluation_engineering=dialog.engineering.isChecked())
                result.evaluation_summary=evaluate_result(result,result.analysis_summary.get('requested_metrics'))
                if result.analysis_summary:result.analysis_summary=summarize_selected(result)
                if entry.get('result_path'):result.save(entry['result_path'])
                self.populate_analysis_results(result);self.update_visuals()
        self.update_evaluation();self.add_log('已更新评价参考与自定义目标；原始测量未重算，报告重新导出后生效。')
    def batch_result_selected(self,row,col):
        key,ch=self.batch_table.item(row,0).data(Qt.ItemDataRole.UserRole)
        self.metric_selector.setCurrentIndex(self.metric_selector.findData(key))
        if ch and self.channel.isEnabled():self.channel.setCurrentText(ch)
        self.update_visuals()
    def analyze_relative_focus(self):
        self.clipping_policy.setCurrentIndex(self.clipping_policy.findData(False))
        self.add_log("相对调焦：保留剪切数值和警告，定位失败仍无效；输入曲线保持当前设置。")
        self.analyze_selected()
    def analyze_whole_card(self):
        try:
            from ..vector_usaf import detect_svg_usaf
            from ..analysis.usaf_multifrequency import is_multifrequency
            chart=self.current_chart()
            if not any(r.enabled and r.kind=='usaf' for r in chart.regions) and any(r.enabled and r.kind in {'star','wedge','edge','grid'} for r in chart.regions):
                self.analysis_channels.setCurrentText('RGBY')
                available,_=metric_availability(chart,configured_channels='RGBY',planning=True)
                metrics=[key for _,key in METRICS if key not in SEQUENCE_METRICS and available.get(key,None)=='']
                self.metric_selector.set_checked_keys(metrics)
                preferred=next((key for key in ['resolution_limit','mtf50','projective_residual_rms_px'] if key in metrics),metrics[0])
                self.metric_selector.setCurrentIndex(self.metric_selector.findData(preferred))
                self.analysis_selection_changed()
                self.add_log('混合图卡：一次分析全部可用单图项目与 RGBY，仅使用实际可见且通过质量检查的区域。输入曲线和剪切策略保持当前设置。')
                self.analyze_selected();return
            if not is_multifrequency(chart):
                chart=copy.deepcopy(chart)
                if not chart.source_path:raise ValueError('先在模板编辑器导入 SVG，或载入已含多频率 ROI 的模板')
                generated,chart.fiducials,chart.physical_size_mm=detect_svg_usaf(chart.source_path,all_frequencies=True)
                chart.regions=generated+[r for r in chart.regions if r.kind!='usaf']
                chart.name=chart.name.split(' · 整卡多频率')[0]
                save_chart(chart,library_dir()/(chart.id+'.json'));self.chart_saved(chart)
            self.analysis_channels.setCurrentText('RGBY');self.clipping_policy.setCurrentIndex(self.clipping_policy.findData(False))
            self.metric_selector.setCurrentIndex(self.metric_selector.findData('resolution_limit'))
            self.metric_selector.set_checked_keys(['resolution_limit','ctf50','ctf20','ctf10','sharpening_halo_pct','ca_r_g_px','ca_b_g_px','alignment_gain_pct'])
            self.analysis_selection_changed()
            self.add_log('整卡：所有可识别频率、双向、RGB + 两种灰度；保留剪切提示，输入传递曲线保持当前设置。')
            self.analyze_selected()
        except Exception as exc:self.message_error(exc)
    def add_log(self,message):self.logs.appendPlainText(time.strftime("%H:%M:%S")+"  "+str(message))
    def log_error(self,message):self.add_log("错误："+str(message));self.status_text.setText(str(message));self.state.setText("任务需检查")
    def message_error(self,message):
        if isinstance(message,Exception):
            from ..diagnostics import background_error
            path=background_error(message,{'action':'gui-operation','current_index':self.current_index})
            self.add_log('界面错误日志：'+path)
        self.log_error(message);QMessageBox.warning(self,"请检查",str(message))
    def open_diagnostics_folder(self):
        folder=Path(getattr(self,'last_log_folder',self.config.cache_path()/'jobs'))
        folder.mkdir(parents=True,exist_ok=True);QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
    def open_ui_logs(self):
        import platformdirs
        folder=Path(platformdirs.user_log_dir('MUTEX Imatest','MUTEX'));folder.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
    def import_dialog(self):
        paths,_=QFileDialog.getOpenFileNames(self,"导入图像","","图像 (*.tif *.tiff *.arw *.nef *.raf *.cr2 *.cr3 *.dng *.rw2 *.orf *.pef *.jpg *.jpeg *.png);;所有文件 (*)")
        self.import_paths(paths)
    def folder_for_job(self):
        folder=self.config.cache_path()/"jobs"/uuid.uuid4().hex;folder.mkdir(parents=True,exist_ok=True);return str(folder)
    def import_paths(self,paths,analyze=False,snapshot=False):
        for path in paths:
            path=str(Path(path).resolve())
            if Path(path).suffix.lower() not in IMAGE_EXTENSIONS:continue
            if not snapshot and any(e["path"]==path for e in self.entries):continue
            entry={"path":path,"preview":None,"metadata":None,"result":None,"result_path":None,"focus_position":None,"focus_unit":None,"status":"等待导入","snapshot":snapshot}
            self.entries.append(entry);item=QListWidgetItem(Path(path).name+"\n等待导入");item.setToolTip(path);self.images.addItem(item)
            index=len(self.entries)-1
            try:self.submit_image(index,"analyze" if analyze else "preview")
            except Exception as exc:self.message_error(exc);return
        if self.images.currentRow()<0 and self.entries:self.images.setCurrentRow(0)
        self.refresh_compare()
    def submit_image(self,index,action):
        entry=self.entries[index];config=self.snapshot_config()
        if action=='analyze':
            if not config.analysis_metrics:raise ValueError('请先勾选至少一个分析项目')
            config.channels=required_channels(config.channels,config.analysis_metrics)
            self.analysis_channels.setCurrentText(config.channels)
        if action=="preview" and entry["result"]:
            # Measurement settings travel with a result; cache locations and
            # memory limits belong to the host currently opening it.
            resources={k:config.to_dict()[k] for k in ['cache_dir','memory_mb','cache_gb','tile_cache_mb','workers','mtf_mapper_path']}
            config=AnalysisConfig.from_dict(dict(entry["result"].settings,**resources)).validate()
        payload={"action":action,"path":entry["path"],"config":config.to_dict(),"folder":self.folder_for_job()}
        self.last_log_folder=payload['folder']
        entry["config"]=config.to_dict()
        if action=="preview" and entry["result"]:payload["expected_fingerprint"]=entry["result"].image.fingerprint
        if action=="analyze":payload.update(chart=self.current_chart().to_dict(),focus_position=entry["focus_position"],focus_unit=entry.get("focus_unit"))
        if entry.get("snapshot"):
            stat=Path(entry["path"]).stat();payload.update(snapshot=True,expected_stat=[stat.st_size,stat.st_mtime_ns])
        uid=self.worker.submit(payload);self.jobs[uid]={"index":index,"action":action,'chart_id':payload.get('chart',{}).get('id'),'metrics':list(config.analysis_metrics or []),'state':'running' if self.worker.current and self.worker.current['id']==uid else 'queued','progress':0}
        entry["status"]="等待分析" if action=="analyze" else "等待导入";self.update_item(index)
        self.cancel_button.setEnabled(True)
        self.refresh_analysis_activity()
    def analyze_selected(self):
        if not self.metric_selector.checked_keys():self.status_text.setText('请先在左侧勾选至少一个分析项目');return
        indices=[self.images.row(i) for i in self.images.selectedItems()]
        if not indices and self.current_index>=0:indices=[self.current_index]
        for index in indices:
            try:self.submit_image(index,"analyze")
            except Exception as exc:self.message_error(exc);return
    def analyze_all(self):
        if not self.metric_selector.checked_keys():self.status_text.setText('请先在左侧勾选至少一个分析项目');return
        for index in range(len(self.entries)):
            try:self.submit_image(index,"analyze")
            except Exception as exc:self.message_error(exc);return
    def job_event(self,uid,event):
        info=self.jobs.get(uid,{})
        index=info.get("index")
        if event["type"]=="started":
            if event.get('payload',{}).get('folder'):self.last_log_folder=event['payload']['folder']
            if info.get('action')=='analyze':self.tabs.setCurrentWidget(self.logs)
            info['state']='running';info['progress']=0
            self.state.setText("离线 · 处理中");self.cancel_button.setEnabled(True)
            self.refresh_analysis_activity()
        elif event["type"]=="progress":
            info['progress']=event['value'];info['message']=event['message']
            self.progress.setValue(event["value"]);self.status_text.setText(event["message"])
            self.refresh_analysis_activity()
        elif event['type']=='log':self.add_log(event['message'])
        elif event["type"]=="preview" and index is not None:
            entry=self.entries[index];entry["preview"]=event["preview"];entry["metadata"]=ImageMetadata(**event["metadata"])
            entry["native_cache"]=event.get("native_cache")
            if info.get("action")=="analyze":entry["result"]=None;entry["result_path"]=None
            if entry.get("snapshot"):
                entry["capture_original"]=entry["path"];entry["path"]=entry["metadata"].path;entry["snapshot"]=False
            if index==self.current_index:self.display_entry(index)
        elif event["type"]=="done":
            info['state']='done'
            if 'preview_orientation' in event:
                entry=self.entries[index]
                if info.get('view_revision')!=entry.get('preview_view_revision',0) or info.get('chart')!=self.current_chart().to_dict() or info.get('fingerprint')!=entry['metadata'].fingerprint:
                    self.orientation_feedback='预览或模板已改变，未应用旧的自动方向结果'
                else:
                    matched=event['preview_orientation'];entry['preview_orientation']=matched['orientation']
                    self.orientation_feedback='预览已按模板恢复方向：'+PreviewOrientation.from_dict(matched['orientation']).description()
                    if index==self.current_index:self.viewer.set_orientation(matched['orientation'])
                    self.add_log(self.orientation_feedback+f"；缩略图匹配相关性 {matched['correlation']:.3f}")
            elif 'exported' in event:self.add_log('已导出：'+event['exported'])
            elif "demo_paths" in event:
                chart=load_chart(event["chart"]);self.charts.append(chart);self.refresh_charts(chart.id)
                self.chart_changed()
                self.transfer.setCurrentIndex(self.transfer.findData("linear"));self.analysis_channels.setCurrentText("RGB")
                self.import_paths(event["demo_paths"],analyze=True);self.add_log("合成示例仅用于验证软件，不代表任何设备的实测。")
            elif "focus" in event:
                self.focus_data=json.loads(Path(event["focus"]).read_text(encoding="utf-8"));self.focus_path=event["focus"];self.show_focus()
                if self.session:self.session.save_state("focus",self.focus_data)
            elif index is not None:
                entry=self.entries[index]
                if "result" in event:
                    entry["result_path"]=event["result"];entry["result"]=AnalysisResult.load(event["result"]);entry["metadata"]=entry["result"].image
                    entry["focus_position"]=entry["result"].focus_position;entry["focus_unit"]=entry["result"].focus_unit;entry["status"]="已分析"
                    if self.session:self.session.add(entry["result"])
                    if entry['result'].analysis_summary:self.add_log(f"一次分析完成 {entry['result'].analysis_summary['completed']} 项；详情见“所选分析结果”。")
                else:
                    entry["metadata"]=ImageMetadata(**event["metadata"]);entry["status"]="已分析" if entry["result"] else "已导入"
                entry["preview"]=event["preview"];self.update_item(index)
                if index==self.current_index:self.display_entry(index)
                if index==self.current_index and 'result' in event and entry['result'].analysis_summary:self.tabs.setCurrentWidget(self.batch_table)
                self.refresh_compare()
        elif event["type"]=="error":
            info['state']='error';info['message']=event['message']
            if info.get('action')=='preview_orientation':
                self.orientation_feedback='自动方向未应用：'+event['message'];self.add_log(self.orientation_feedback);self.status_text.setText(self.orientation_feedback);return
            self.log_error(event["message"])
            if "log" in event:self.add_log("诊断日志："+event["log"])
            if index is not None:self.entries[index]["status"]="需检查";self.update_item(index)
        elif event["type"]=="cancelled":
            info['state']='cancelled'
            self.add_log("任务已取消")
            if index is not None and info.get('action')!='preview_orientation':self.entries[index]["status"]="已取消";self.update_item(index)
        self.refresh_analysis_activity()
    def jobs_idle(self):
        self.progress.setValue(100);self.cancel_button.setEnabled(False);self.state.setText("离线 · 就绪");self.status_text.setText(getattr(self,'orientation_feedback',None) or '任务完成');self.orientation_feedback=None
        self.refresh_analysis_activity()
    def cancel_jobs(self):
        for uid,info in self.jobs.items():
            if info.get('action')=='analyze' and info.get('state') in {'queued','running'}:
                info['state']='cancelling' if self.worker.current and uid==self.worker.current['id'] else 'cancelled'
                if info['state']=='cancelled' and info.get('index') is not None:self.entries[info['index']]['status']='已取消';self.update_item(info['index'])
        self.worker.cancel_all();self.add_log("正在取消已排队和当前任务");self.refresh_analysis_activity()
    def update_item(self,index):
        e=self.entries[index];r=e["result"];extra=e["status"]
        if r:
            rows=view_result(r,'resolution_limit').measurements if r.optical_summary else r.measurements
            rows=[m for m in rows if m.channel=='G'] if r.optical_summary else rows
            extra+=f" · {sum(m.valid and (not r.optical_summary or m.metric('resolution_limit') is not None) for m in rows)}/{len(rows)} {'单元' if r.optical_summary else '有效'}"
        self.images.item(index).setText(Path(e["path"]).name+"\n"+extra)
    def select_entry(self,index):
        if not 0<=index<len(self.entries):return
        self.current_index=index;self.display_entry(index)
        self.refresh_analysis_activity()
    def display_entry(self,index):
        e=self.entries[index]
        if not e["metadata"] or not e["preview"]:return
        reader_config=AnalysisConfig.from_dict(e.get("config",self.config.to_dict()))
        self.viewer.load(e["preview"],e["metadata"],reader_config,e.get("native_cache"),e.get('preview_orientation'))
        self.update_preview_controls()
        self.summary_info.setText(f"{e['metadata'].width:,} × {e['metadata'].height:,}\n{e['metadata'].bits_per_sample}-bit × {e['metadata'].channels} · {e['metadata'].file_bytes/2**20:.1f} MiB")
        if e["result"]:
            self.populate_analysis_results(e['result'])
            indices=e['result'].optical_summary.get('frequency_indices',[])
            self.usaf_frequency.blockSignals(True);self.usaf_frequency.clear()
            for k in indices:self.usaf_frequency.addItem(f'组 {k//6} / 元素 {k%6+1} · {2**(k/6):.3g} lp/mm',k)
            self.usaf_frequency.setCurrentIndex(max(0,self.usaf_frequency.findData(22)));self.usaf_frequency.blockSignals(False)
            self.viewer.result=self.direction_result(e['result']);self.update_visuals()
            first=next((m.region_id for m in self.direction_result(e["result"]).measurements if m.valid and m.channel==self.channel.currentText()),None)
            if first:self.select_region(first)
        else:
            self.batch_table.setRowCount(0);self.sync_metric_choices()
            self.update_evaluation()
            self.curve.clear();self.table.setRowCount(0);self.summary_value.setText("—");self.summary_label.setText("选择模板后分析")
            self.reg_note.setText("先检查模板和输入曲线，再开始分析。")
    def preview_orientation_changed(self,state):
        self.orientation_label.setText(PreviewOrientation.from_dict(state).description())
        if 0<=self.current_index<len(self.entries):
            entry=self.entries[self.current_index]
            if entry.get('preview_orientation')!=state:entry['preview_view_revision']=entry.get('preview_view_revision',0)+1
            entry['preview_orientation']=dict(state)
    def preview_registration(self):
        if not 0<=self.current_index<len(self.entries):return None
        result=self.entries[self.current_index].get('result');chart=self.current_chart()
        if self.registration.currentData()=='anchors' and self.config.anchors:
            import cv2
            return cv2.getPerspectiveTransform(np.array([[0,0],[1,0],[1,1],[0,1]],np.float32),np.asarray(self.config.anchors,np.float32))
        if result and (recognizes(chart,result.chart_id) or (result.template and family_key(chart)==family_key(type(chart).from_dict(result.template)))):
            if result.registration.get('method') not in {None,'full_frame_scale','generic_detected_targets'}:return result.registration.get('homography')
        return None
    def update_preview_controls(self):
        ready=0<=self.current_index<len(self.entries) and bool(self.entries[self.current_index].get('metadata') and self.entries[self.current_index].get('preview'))
        for b in self.orientation_buttons:b.setEnabled(ready)
        chart=self.current_chart()
        reference=any(p and Path(p).is_file() for p in [chart.preview,chart.source_path])
        self.quick_orientation.setEnabled(ready and (reference or self.preview_registration() is not None))
        self.quick_orientation.setToolTip('根据模板配准恢复方向，限 90° 步进及必要镜像，再适合窗口' if self.quick_orientation.isEnabled() else '需要图像预览和模板缩略图或有效配准；也可先做四点配准')
    def align_preview_to_template(self):
        if not 0<=self.current_index<len(self.entries):return
        entry=self.entries[self.current_index]
        if not entry.get('preview') or not entry.get('metadata'):return
        try:
            H=self.preview_registration()
            if H is not None:
                orientation=orientation_from_homography(H);self.viewer.set_orientation(orientation)
                message='预览已按模板恢复方向：'+orientation.description()
                self.status_text.setText(message);self.add_log(message+'；使用已有配准，测量像素和结果保持原坐标。');return
            chart=self.current_chart().to_dict()
            payload={'action':'preview_orientation','preview':entry['preview'],'chart':chart,'config':self.snapshot_config().to_dict(),'folder':self.folder_for_job()}
            uid=self.worker.submit(payload)
            self.jobs[uid]={'index':self.current_index,'action':'preview_orientation','chart':chart,'fingerprint':entry['metadata'].fingerprint,'view_revision':entry.get('preview_view_revision',0)}
            self.cancel_button.setEnabled(True);self.add_log('通过模板缩略图匹配预览方向；只在点击快速对齐时应用。')
        except Exception as exc:self.status_text.setText(str(exc));self.add_log('自动预览方向未应用：'+str(exc))
    def update_visuals(self,*args):
        if self.current_index<0:return
        entry=self.entries[self.current_index]
        if entry['result']:self.sync_metric_choices(result=entry['result'])
        result=self.direction_result(entry["result"])
        if not result:
            self.coverage_notice.hide();self.resolution_map_button.hide();return
        if self.metric_selector.currentData() in {'best_focus','focus_offset'} and self.focus_data:
            result=self.focus_overlay_result(entry['result'],self.metric_selector.currentData())
        metric=self.metric_selector.currentData()
        channels={m.channel for m in result.measurements if m.metric(metric) is not None} or {m.channel for m in result.measurements}
        self.channel.blockSignals(True)
        for i in range(self.channel.count()):
            ch=self.channel.itemData(i,Qt.ItemDataRole.UserRole) or ['G','R','B','Y','Y_align'][i]
            set_availability(self.channel,i,ch in channels,'该通道没有当前指标；更改测量通道后重新分析',ch)
        if metric in PAIRED_SHIFT_METRICS:
            self.channel.setCurrentIndex(self.channel.findText(PAIRED_SHIFT_METRICS[metric]))
        elif metric in {'rgb_shift_px','rgb_shift_x_px','rgb_shift_y_px'} and getattr(self,'last_visual_metric',None) not in {'rgb_shift_px','rgb_shift_x_px','rgb_shift_y_px'} and self.channel.currentText()=='G':
            self.channel.setCurrentText('R' if 'R' in channels else 'B' if 'B' in channels else 'G')
        if channels and self.channel.currentText() not in channels:self.channel.setCurrentText("G" if "G" in channels else sorted(channels)[0])
        self.channel.blockSignals(False)
        self.channel.setEnabled(metric not in PAIRED_SHIFT_METRICS)
        self.channel.setToolTip('该指标已固定 R−G 或 B−G；选择另一通道对请切换指标。' if metric in PAIRED_SHIFT_METRICS else 'Y：对齐前灰度；Y_align：对齐后灰度。G 为位移参考。')
        self.last_visual_metric=metric
        metric=self.metric_selector.currentData();channel=self.channel.currentText();unit=self.unit.currentText()
        self.update_metric_units(metric)
        unit=self.unit.currentText()
        self.viewer.result=result
        limits=None;compare_result=None
        if self.compare_index is not None and self.compare_index<len(self.entries):compare_result=self.direction_result(self.entries[self.compare_index]["result"])
        if compare_result:
            key=metric_key(metric,unit)
            v=[m.metric(key) for r in [result,compare_result] for m in r.measurements if m.channel==channel and m.valid and m.metric(key) is not None]
            if v:limits=(min(v),max(v))
        self.viewer.selected_metric=metric;self.viewer.channel=channel;self.viewer.unit=unit;self.viewer.alpha=self.alpha.value()/100
        self.viewer.interpolate=self.interpolation.isChecked()
        data=self.viewer.refresh_overlay(self.overlay.isChecked(),limits)
        if compare_result and self.reference_viewer.isVisible():
            self.reference_viewer.set_result(compare_result,metric,channel,unit,self.alpha.value()/100,self.interpolation.isChecked())
            self.reference_viewer.refresh_overlay(self.overlay.isChecked(),limits)
        values=data["values"] if data else []
        notice=data.get('notice','') if data else ''
        self.coverage_notice.setText(notice);self.coverage_notice.setVisible(bool(notice))
        self.resolution_map_button.setVisible(bool(notice and metric in {'ctf50','ctf20','ctf10'} and entry['result'].optical_summary and
            any(m.valid and m.channel==channel and m.metric('resolution_limit') is not None for m in entry['result'].measurements if m.kind=='usaf_summary' and m.direction_deg is None)))
        self.summary_value.setText(f"{np.mean(values):.3f}" if len(values) else "—")
        metric_name=self.metric_selector.currentText()
        self.summary_label.setText(f"平均 {metric_name} · {unit}\n有效测点 {len(values)}")
        self.update_evaluation(result,metric,channel)
        coverage_note='仅相邻有效区域间插值 · 外缘至区域边界' if self.interpolation.isChecked() else '各测试区域内填色'
        self.legend.setText(f"蓝 → 绿 → 黄 → 红   {data['limits'][0]:.3g} — {data['limits'][1]:.3g} {unit}    · 白点：实测 · 灰色斜线：未测得 · {coverage_note}" if data and len(values) else "该指标没有有效数值；灰色斜线标记未测得区域，不代表零分辨率。")
        self.reg_note.setText(result.registration.get("warning",""))
        selected=[m for m in result.measurements if m.channel==channel]
        clipped=sum("clipped" in m.flags for m in selected)
        advisory=sum("clipping_advisory" in m.flags for m in selected)
        failed=sum("registration_failed" in m.flags for m in selected)
        notes=[f"当前 {channel}：{len(values)}/{len(selected)} 个测点参与热力图。"]
        if clipped:notes.append(f"{clipped} 点因信号剪切被严格排除；可按相对调焦重新分析，保留数值和警告。")
        if advisory:notes.append(f"相对调焦：{advisory} 点保留剪切提示；结果受剪切影响。")
        if failed:notes.append(f"{failed} 点定位未通过，继续排除。")
        from ..analysis_audit import reason_for,REASONS
        missing=Counter(reason_for(entry['result'],m,metric) for m in selected if not m.valid or m.metric(metric) is None)
        if missing:notes.append('缺失原因：'+'；'.join(f'{REASONS.get(k,k)} {n}' for k,n in missing.items()))
        if result.settings.get("transfer")=="unknown" and not result.image.is_linear:
            notes.append("输入曲线未知：显示输入信号响应。USAF 对比度不能当作光学 MTF。")
        if metric in PAIRED_SHIFT_METRICS:
            notes.append('固定通道对：'+channel+'−G；'+('显示二维位移幅值，右 / 下分量见测量明细。' if entry['result'].optical_summary else '显示斜边法向的有符号投影。'))
        self.warning.setText("\n".join(notes))
        if entry['result'].optical_summary:
            from ..reports_usaf import summary_text
            self.optical_detail.setPlainText(summary_text(entry['result']))
            self.usaf_frequency.setEnabled(metric not in MULTI_METRICS and metric not in RGB_SHIFT_METRICS and metric!='sharpening_halo_pct')
            if metric=='resolution_limit':self.summary_label.setText(f'已确认分辨率 · {unit}\n有效单元 {len(values)}；双向取较弱方向\n最高 {max(values):.4g}' if len(values) else '尚无可用分辨率')
        self.relative_focus_button.setVisible(bool(clipped and selected and all(m.kind=="usaf" for m in selected)))
        self.table.setRowCount(len(selected))
        for row,m in enumerate(selected):
            value=m.metric(data["metric"]) if data else None
            state=", ".join(FLAG_NAMES.get(f,f) for f in m.flags) or "有效"
            if not m.valid or value is None:state=REASONS.get(reason_for(entry['result'],m,metric),'未测得')+'；'+state
            texts=[m.label,m.kind,m.channel,f"{value:.5g}" if value is not None else "—",f"{m.confidence:.2f}",state,f"{m.position[0]:.0f}, {m.position[1]:.0f}",measurement_text(result,m,metric,unit if metric in FREQUENCY_METRICS else None).split('：')[0]]
            for col,text in enumerate(texts):
                item=QTableWidgetItem(text);item.setData(Qt.ItemDataRole.UserRole,m.region_id)
                if not m.valid:item.setForeground(QColor("#ad704d"))
                if col==7:item.setToolTip(measurement_text(result,m,metric,unit if metric in FREQUENCY_METRICS else None))
                self.table.setItem(row,col,item)
        self.table.resizeColumnsToContents();self.table.horizontalHeader().setStretchLastSection(True)
        if self.compare_index is not None:self.add_compare_note()
        if self.selected_region not in {m.region_id for m in result.measurements}:
            self.selected_region=next((m.region_id for m in result.measurements if m.valid and m.channel==channel),None)
        if self.selected_region:
            current_tab=self.tabs.currentIndex();self.select_region(self.selected_region);self.tabs.setCurrentIndex(current_tab)
    def direction_result(self,result):
        direction=self.usaf_direction.currentData()
        if result and result.optical_summary:
            return view_result(result,self.metric_selector.currentData(),direction,self.usaf_frequency.currentData())
        if result and self.metric_selector.currentData() in PAIRED_SHIFT_METRICS:
            filtered=copy.copy(result);ch=PAIRED_SHIFT_METRICS[self.metric_selector.currentData()]
            filtered.measurements=[m for m in result.measurements if m.channel==ch];return filtered
        if result is None or direction=="both":return result
        filtered=copy.copy(result)
        angle=0 if direction=="vertical" else 90
        filtered.measurements=[m for m in result.measurements if m.kind!="usaf" or m.direction_deg==angle]
        filtered.settings=dict(result.settings,report_usaf_direction=direction)
        return filtered
    def select_region(self,region_id):
        if self.current_index<0:return
        result=self.entries[self.current_index]["result"]
        if not result:return
        self.selected_region=region_id
        measurements=[m for m in result.measurements if m.region_id==region_id]
        if self.metric_selector.currentData() in RGB_SHIFT_METRICS or self.metric_selector.currentData()=='sharpening_halo_pct':
            measurements=[m for m in self.direction_result(result).measurements if m.region_id==region_id]
        curve_keys={key for m in measurements for key in m.curves}
        if any(m.kind=='usaf_summary' for m in measurements):curve_keys.update({'ctf','ctf_response'})
        self.curve_selector.blockSignals(True)
        for i in range(self.curve_selector.count()):
            key=self.curve_selector.itemData(i)
            set_availability(self.curve_selector,i,key=='auto' or key in curve_keys,'当前测量区域没有此类曲线')
        if self.curve_selector.currentData()!='auto' and self.curve_selector.currentData() not in curve_keys:self.curve_selector.setCurrentIndex(0)
        self.curve_selector.blockSignals(False)
        self.curve.setLogMode(x=False,y=False)
        self.curve.clear();colors={"R":"#db5b5b","G":"#168886","B":"#5d79c8","Y":"#988047","Y_align":"#8e5ead"}
        if result.optical_summary and any(m.kind=='usaf_summary' for m in measurements):
            self.plot_usaf_unit(result,region_id,measurements,colors);return
        selected=None
        for m in measurements:
            choice=self.curve_selector.currentData()
            curve=(m.curves.get("sfr") or m.curves.get("star") or m.curves.get("profile") or next(iter(m.curves.values()),None)) if choice=="auto" else m.curves.get(choice)
            if curve:
                self.curve.plot(curve["x"],curve["y"],pen=pg.mkPen(colors[m.channel],width=2),name=m.channel)
                ylabel=curve.get("y_unit","")
                if m.kind=="usaf" and result.settings.get("transfer")=="unknown" and not result.image.is_linear:ylabel="input signal"
                self.curve.setLabel("bottom",curve.get("x_unit",""));self.curve.setLabel("left",ylabel)
            if m.channel==self.channel.currentText():selected=m
        if self.compare_index is not None:
            compare=self.entries[self.compare_index]["result"]
            if compare:
                for m in compare.measurements:
                    if m.region_id==region_id and m.channel==self.channel.currentText():
                        curve=(m.curves.get("sfr") or m.curves.get("star")) if self.curve_selector.currentData()=="auto" else m.curves.get(self.curve_selector.currentData())
                        if curve:self.curve.plot(curve["x"],curve["y"],pen=pg.mkPen("#8b90a6",width=2,style=Qt.PenStyle.DashLine))
        if selected:
            visible={k:v for k,v in selected.values.items() if self.professional or k in METRIC_NAMES}
            self.detail.setPlainText(selected.label+" · "+selected.channel+"\n\n"+"\n".join(f"{METRIC_NAMES.get(k,k)}: {v:.5g} {selected.units.get(k,'')}" for k,v in visible.items() if v is not None and isinstance(v,(float,int)))+
              "\n\n状态："+(", ".join(FLAG_NAMES.get(f,f) for f in selected.flags) or "有效")+"\n\n置信度 "+f"{selected.confidence:.2f}")
            self.detail.appendPlainText('\n'+measurement_text(result,selected,self.metric_selector.currentData(),self.unit.currentText() if self.metric_selector.currentData() in FREQUENCY_METRICS else None))
            if self.professional and selected.diagnostics:
                self.detail.appendPlainText('\n几何 / 缺陷诊断：\n'+json.dumps(selected.diagnostics,ensure_ascii=False,indent=2)[:16000])
        self.tabs.setCurrentIndex(0)
    def change_curve(self,*args):
        if self.selected_region:self.select_region(self.selected_region)
    def plot_usaf_unit(self,result,region_id,measurements,colors):
        unit_id=region_id.split('-horizontal-summary')[0].split('-vertical-summary')[0].split('-combined-summary')[0]
        record=next((u for u in result.optical_summary['units'] if u['unit_id']==unit_id),None)
        if not record:return
        if self.metric_selector.currentData()=='sharpening_halo_pct':
            self.curve.setLogMode(x=False,y=False)
            direction='vertical' if '-vertical-' in region_id else 'horizontal' if '-horizontal-' in region_id else None
            records=record.get('sharpening',{}) if direction is None else {ch:r.get('sharpening',{}) for ch,r in record['directions'].get(direction,{}).items()}
            for ch,rec in records.items():
                c=rec.get('curve',{})
                if c.get('x'):self.curve.plot(c['x'],c['y'],pen=pg.mkPen(colors[ch],width=2),name=ch)
            self.curve.setLabel('bottom','bar periods');self.curve.setLabel('left','input signal')
            chosen=next((m for m in measurements if m.channel==self.channel.currentText()),None)
            lines=[unit_id,'低频内部边缘：亮 / 暗光晕相对于局部阶跃高度。','锐化与光学 / 图卡振铃不能仅凭单张图像区分。']
            if chosen:
                lines += [f'{METRIC_NAMES.get(k,k)}: {v:.5g} {chosen.units.get(k,"")}' for k,v in chosen.values.items() if isinstance(v,(int,float))]
                lines += ['状态：'+', '.join(FLAG_NAMES.get(f,f) for f in chosen.flags),measurement_text(result,chosen,'sharpening_halo_pct','%')]
            self.detail.setPlainText('\n'.join(lines));self.tabs.setCurrentIndex(0);return
        raw=self.curve_selector.currentData()=='ctf';unit=self.unit.currentText()
        dirs=['vertical'] if '-vertical-' in region_id else ['horizontal'] if '-horizontal-' in region_id else ['vertical','horizontal']
        for direction in dirs:
            for ch,rec in record['directions'].get(direction,{}).items():
                c=rec.get('curve',{});x=c.get('frequency_lp_mm') if unit=='lp/mm' else c.get('frequency',[])
                if not x or any(v is None for v in x):x=c.get('frequency',[])
                factor=50.8 if unit=='DPI' else 2*result.optical_summary['picture_height_px'] if unit=='LW/PH' else result.optical_summary['picture_height_px'] if unit=='LP/PH' else 1
                if unit=='DPI':x=[v*50.8 for v in c.get('frequency_lp_mm',[]) if v is not None]
                elif factor!=1:x=[v*factor for v in x]
                y=c.get('ctf',[]) if raw else c.get('ctf_envelope',c.get('envelope',[]))
                if len(x)!=len(y):continue
                support=c.get('ctf_support',c.get('sequence_valid',[True]*len(y)))
                y=np.array([np.nan if v is None or (not raw and not valid) else v for v,valid in zip(y,support)],dtype=float)
                self.curve.plot(x,y,connect='finite',pen=pg.mkPen(colors[ch],width=2,style=Qt.PenStyle.SolidLine if direction=='vertical' else Qt.PenStyle.DashLine),name=ch+' '+direction)
        self.curve.setLogMode(x=True,y=False);self.curve.setLabel('bottom',unit if unit in {'lp/mm','DPI','LW/PH','LP/PH'} else 'cy/px');self.curve.setLabel('left','CTF' if raw else 'CTF / low frequency')
        self.curve.getAxis('bottom').setStyle(maxTextLevel=0)
        chosen=next((m for m in measurements if m.channel==self.channel.currentText()),None)
        lines=[unit_id,'实线：竖线 / 横向细节；虚线：横线 / 纵向细节','红 R · 绿 G · 蓝 B · 黄 Y · 紫 Y_align']
        if chosen:
            lines += [f'{METRIC_NAMES.get(k,k)}: {v:.5g} {chosen.units.get(k,"")}' for k,v in chosen.values.items() if v is not None and isinstance(v,(float,int)) and (self.professional or k in METRIC_NAMES)]
            lines+=['状态：'+', '.join(FLAG_NAMES.get(f,f) for f in chosen.flags)]
            lines+=['',measurement_text(result,chosen,self.metric_selector.currentData(),self.unit.currentText() if self.metric_selector.currentData() in FREQUENCY_METRICS else None)]
        if 'ctf' in result.optical_summary.get('definitions',{}):lines+=['CTF 取三黑条之间的内部明暗起伏，排除外侧白底；只在相邻有效频点之间插值。',
            '剪切频点不参与；后续未剪切连续段仍可提供交点。缺线、信噪比不足或频率断档后停止，已确认分辨率仍要求自低频连续通过。']
        lines+=['低频归一化 CTF 为输入响应；未知曲线、剪切、图卡印刷均影响结果。','CTF 曲线不能直接称为光学 MTF。']
        self.detail.setPlainText('\n'.join(lines));self.tabs.setCurrentIndex(0)
    def table_selected(self,row,col):
        item=self.table.item(row,0)
        if item:self.select_region(item.data(Qt.ItemDataRole.UserRole))
    def refresh_compare(self):
        current=self.compare.currentData();self.compare.blockSignals(True);self.compare.clear();self.compare.addItem("比较：未选择",None)
        for index,e in enumerate(self.entries):
            if e["result"]:self.compare.addItem(Path(e["path"]).name,index)
        i=self.compare.findData(current);self.compare.setCurrentIndex(max(0,i));self.compare.blockSignals(False)
    def change_compare(self,index):
        self.compare_index=self.compare.currentData()
        show=self.compare_index is not None and self.compare_index!=self.current_index
        self.reference_viewer.setVisible(show)
        if show:
            entry=self.entries[self.compare_index]
            if entry["preview"] and entry["metadata"]:
                self.reference_viewer.load(entry["preview"],entry["metadata"],AnalysisConfig.from_dict(entry.get("config",self.config.to_dict())),entry.get("native_cache"),self.viewer.orientation.to_dict())
                self.image_split.setSizes([500,500])
                self.viewer.fit_image()
        self.update_visuals()
    def sync_view(self,target,state):
        if self.reference_viewer.isVisible():target.apply_view_state(state)
    def update_metric_units(self,metric):
        if metric in FREQUENCY_METRICS:choices=["cy/px","lp/mm","DPI","LW/PH","LP/PH"]
        elif metric in {'best_focus','focus_offset'}:choices=[self.focus_data["unit"] if self.focus_data else "index"]
        elif metric.endswith("_px"):choices=["px"]
        elif metric=="spatial_snr_db":choices=["dB"]
        elif metric=="delta_e_2000":choices=["ΔE2000"]
        elif metric=='delta_e_76':choices=['ΔE76']
        elif metric=='information_capacity_1d':choices=['bits/px (1D model)']
        elif metric.endswith('_stops'):choices=['stops']
        elif metric.endswith('_ev'):choices=['EV']
        elif metric.endswith('_count'):choices=['count']
        elif metric.startswith('sampling_dpi'):choices=['PPI']
        elif metric.endswith('_pct'):choices=['%']
        else:choices=["ratio"]
        current=self.unit.currentText()
        existing=[self.unit.itemText(i) for i in range(self.unit.count())]
        if existing!=choices:
            self.unit.blockSignals(True);self.unit.clear();self.unit.addItems(choices)
            self.unit.setCurrentText(current if current in choices else choices[0]);self.unit.blockSignals(False)
        self.unit.setEnabled(len(choices)>1)
    def focus_overlay_result(self,base,metric='best_focus'):
        result=copy.copy(base);result.measurements=[];result.optical_summary={};result.analysis_summary={};result.settings=dict(base.settings)
        result.evaluation_summary={}
        result.settings["algorithm_version"]="focus-series-quadratic-v1"
        result.settings["series_fingerprints"]=self.focus_data["image_fingerprints"]
        result.warnings=list(self.focus_data["warnings"])
        result.focus_position=None;result.focus_unit=self.focus_data["unit"]
        for peak in self.focus_data["peaks"]:
            if metric=='focus_offset' and peak['channel'] not in {'R','B'}:continue
            match=next((m for m in base.measurements if m.region_id==peak["region_id"]),None)
            if match:
                value=peak['peak'];uncertainty=peak.get('uncertainty');valid=value is not None and peak['confidence']>.1 and not peak['flags']
                if metric=='focus_offset':
                    records=self.focus_data.get('rgb_focus_offsets',{}).get(peak['channel']+'-G',{}).get('regions',[])
                    offset=next((r for r in records if r['region_id']==peak['region_id']),None)
                    value=offset['offset'] if offset else None;uncertainty=offset.get('uncertainty') if offset else None
                    valid=valid and bool(offset)
                result.measurements.append(Measurement(peak["region_id"],match.label,"focus",peak["channel"],match.position,match.box_pixels,
                   values={metric:value},units={metric:self.focus_data["unit"]},confidence=peak["confidence"],method="focus-sequence-quadratic",
                   flags=[] if valid else ['fit_failed',*peak['flags']],diagnostics={'uncertainty':uncertainty}))
        result.evaluation_summary=evaluate_result(result,[metric])
        return result
    def add_compare_note(self):
        if self.compare_index==self.current_index:return
        r1=self.entries[self.current_index]["result"];r2=self.entries[self.compare_index]["result"]
        if not r1 or not r2:return
        if r1.chart_id!=r2.chart_id:self.status_text.setText("比较图像使用不同模板；曲线区域可能不对应")
        else:self.status_text.setText("比较已启用：热力图范围一致；曲线中虚线为参考图像")
    def begin_anchors(self):
        self.viewer.begin_anchors();self.status_text.setText("依次点击图卡：左上 → 右上 → 右下 → 左下（Esc 取消）")
    def set_anchors(self,points):
        self.config.anchors=points;self.registration.setCurrentIndex(self.registration.findData("anchors"));self.reg_note.setText("四点已记录。重新分析以应用配准。");self.update_preview_controls()
    def reset_anchors(self):self.config.anchors=None;self.viewer.cancel_anchors();self.registration.setCurrentIndex(self.registration.findData("template"));self.reg_note.setText("已恢复全幅模板。");self.update_preview_controls()
    def edit_chart(self):
        from ..template_library import user_chart_path
        chart=copy.deepcopy(self.current_chart())
        if user_chart_path(chart) is None:chart.id='user-'+uuid.uuid4().hex;chart.aliases=[];chart.name+=' · 副本'
        dialog=TemplateEditor(chart,self);dialog.chart_saved.connect(self.chart_saved);dialog.exec()
    def new_chart(self):
        dialog=TemplateEditor(parent=self);dialog.chart_saved.connect(self.chart_saved);dialog.exec()
    def setup_official_chart(self):
        from .iq_workbench import ProfileDialog
        path=self.entries[self.current_index]['path'] if 0<=self.current_index<len(self.entries) else ''
        dialog=ProfileDialog(self.snapshot_config(),path,self);dialog.chart_saved.connect(self.chart_saved);dialog.exec()
    def open_workbench(self):
        from .iq_workbench import WorkbenchDialog
        paths=[self.entries[self.current_index]['path']] if 0<=self.current_index<len(self.entries) else []
        WorkbenchDialog(self.snapshot_config(),paths,self).exec()
    def select_ccm(self):
        path,_=QFileDialog.getOpenFileName(self,'选择色彩标定矩阵（取消保留当前设置）','','CCM JSON (*.json)')
        if path:
            try:
                from ..analysis.tone_color import apply_color_matrix
                apply_color_matrix(np.zeros((1,1,3)),json.loads(Path(path).read_text(encoding='utf-8-sig')))
                self.config.color_matrix_path=path;save_config(self.config);self.add_log('已应用 CCM；重新分析色块以生效：'+path)
            except (ValueError,KeyError,OSError) as exc:self.message_error(exc)
    def clear_ccm(self):
        self.config.color_matrix_path='';save_config(self.config);self.add_log('已清除 CCM；重新分析色块以生效。')
    def manage_templates(self):
        from .template_manager import TemplateManager
        dialog=TemplateManager(self.current_chart(),self);dialog.chart_selected.connect(self.chart_saved);dialog.library_changed.connect(self.reload_templates);dialog.exec()
    def reload_templates(self):
        selected=self.current_chart().id;self.charts=available_charts();self.refresh_charts(selected);self.chart_changed()
    def import_chart_package(self):
        try:
            from .template_manager import import_template_dialog
            chart=import_template_dialog(self)
            if chart:self.chart_saved(chart);self.add_log('模板已导入本机图卡库：'+chart.name)
        except Exception as exc:self.message_error(exc)
    def export_chart_package(self):
        try:
            from .template_manager import export_template_dialog
            path=export_template_dialog(self.current_chart(),self)
            if path:self.status_text.setText('加密模板已导出：'+str(path));self.add_log(self.status_text.text())
        except Exception as exc:self.message_error(exc)
    def chart_saved(self,chart):
        if (library_dir()/(chart.id+'.json')).is_file():self.charts=available_charts()
        else:self.charts=[c for c in self.charts if c.id!=chart.id]+[chart]
        self.refresh_charts(chart.id)
        self.chart_changed()
    def detect_edges(self):
        if self.current_index<0:return
        e=self.entries[self.current_index]
        if not e["preview"]:return
        from PIL import Image
        from ..detection import suggest_edges
        from ..models import Region,ChartDefinition
        boxes=suggest_edges(np.asarray(Image.open(e["preview"]).convert("RGB")))
        if not boxes:self.message_error("未找到合适的斜边候选；可以在模板编辑器手动框选");return
        chart=ChartDefinition(uuid.uuid4().hex,"自动斜边候选",[
            Region(f"auto-{i}","edge",box,f"候选 {i+1}") for i,box in enumerate(boxes)],preview=e["preview"],notes="候选区域需要人工检查")
        self.chart_saved(chart);self.add_log(f"找到 {len(boxes)} 个候选，请在模板编辑器检查。")
    def open_demo(self):
        config=self.snapshot_config()
        payload={"action":"demo","config":config.to_dict(),"folder":self.folder_for_job()}
        uid=self.worker.submit(payload);self.jobs[uid]={"action":"demo"};self.cancel_button.setEnabled(True)
    def setup_focus(self):
        entries=[e for e in self.entries if e["result"]]
        if len(entries)<5:self.message_error("先分析至少 5 张不同焦位的图像。合成示例提供 9 张样本。");return
        dialog=FocusSetupDialog(entries,self.metric_selector.currentData(),self)
        if not dialog.exec():return
        for e,z in zip(entries,dialog.positions):
            e["focus_position"]=z;e["focus_unit"]=dialog.unit.currentData();e["result"].focus_position=z;e["result"].focus_unit=dialog.unit.currentData()
            e["result"].save(e["result_path"])
            if self.session:self.session.add(e["result"])
        payload={"action":"focus","config":self.snapshot_config().to_dict(),"folder":self.folder_for_job(),
                 "results":[e["result_path"] for e in entries],"metric":dialog.metric_selector.currentData(),
                 "channel":dialog.channel.currentText(),"objective":dialog.objective.currentData()}
        payload["height_calibrated"]=dialog.height_calibrated.isChecked()
        uid=self.worker.submit(payload);self.jobs[uid]={"action":"focus"};self.cancel_button.setEnabled(True)
    def show_focus(self):
        f=self.focus_data;self.focus_plot.clear()
        curve=f["objective_curve"]
        if curve:self.focus_plot.plot(curve["x"],curve["y"],pen=pg.mkPen("#137e80",width=3))
        for peak in f["peaks"]:
            if peak["peak"] is not None:
                samples=np.asarray(peak["samples"]);self.focus_plot.plot(samples[:,0],samples[:,1]/samples[:,1].max(),pen=pg.mkPen("#a7bec8",width=1))
        recommended=f["recommended_position"]
        if recommended is not None:self.focus_plot.addItem(pg.InfiniteLine(recommended,angle=90,pen=pg.mkPen("#ec9a45",width=2,style=Qt.PenStyle.DashLine)))
        text=f"综合推荐：{recommended:.4f} {f['unit']}\n" if recommended is not None else "综合推荐：采样不足或峰值未包围\n"
        valid=sum(p["peak"] is not None for p in f["peaks"]);text+=f"有效峰值：{valid}/{len(f['peaks'])}\n指标：{f['metric']} · {f['channel']}\n"
        model=f["field_model"]
        if model:
            text+=f"\n场面拟合 RMS：{model['rms']:.4g} {f['unit']}\n系数：{np.array(model['coefficients']).round(5)}\n"
            if "apparent_tilt_deg" in model:text+=f"表观倾斜：{model['apparent_tilt_deg']:.4f}°\n"
        text+="\n"+"\n".join(f["warnings"]);self.focus_detail.setPlainText(text);self.tabs.setCurrentIndex(2)
        if f.get('channel_results'):
            extra='\n各通道最佳焦位：\n'
            for ch,rec in f['channel_results'].items():extra+=f"{CHANNEL_LABELS.get(ch,ch)}: {rec.get('recommended_position')} {f['unit']}\n"
            for key,rec in f.get('rgb_focus_offsets',{}).items():extra+=f"{key} 焦位差中位数：{rec['median']} {f['unit']}，匹配区域 {rec['count']}\n"
            self.focus_detail.appendPlainText(extra)
        from ..evaluation import evaluate_focus
        evaluation=evaluate_focus(f,self.config.to_dict())
        self.focus_detail.appendPlainText('\n评价与参考：\n'+evaluation['sequence_note'])
        for item in evaluation['items']:
            self.focus_detail.appendPlainText(item['name']+'：'+item['reference']['reference'])
            for ch in item['channels']:self.focus_detail.appendPlainText(ch['channel']+' · '+channel_text(ch))
        for ch,rec in evaluation['channel_spans'].items():
            self.focus_detail.appendPlainText(f"{ch} 有效峰值覆盖 {rec['valid']}/{rec['total']}；场间跨度 "+(f"{rec['span']:.5g} {rec['unit']}" if rec['span'] is not None else '未测得'))
        self.add_log("焦位拟合完成："+text.split("\n")[0])
        self.metric_selector.setCurrentIndex(self.metric_selector.findData("best_focus"))
    def toggle_watch(self):
        if self.watcher.folder:self.watcher.stop();self.watch_button.setText("监视文件夹");self.add_log("已停止监视");return
        path=QFileDialog.getExistingDirectory(self,"监视采集文件夹")
        if path:self.watcher.start(path);self.watch_button.setText("停止监视");self.add_log("监视文件夹："+path+"（新文件稳定且关闭后自动分析）")
    def watch_file(self,path):self.import_paths([path],analyze=True,snapshot=True)
    def select_oecf(self):
        path,_=QFileDialog.getOpenFileName(self,"encoded/linear 数组 JSON","","标定曲线 (*.json)")
        if path:self.config.oecf_path=path;self.transfer.setCurrentIndex(self.transfer.findData("oecf"))
    def performance_settings(self):
        dialog=PerformanceDialog(self.config,self)
        if dialog.exec():self.config=dialog.config;self.add_log("资源设置已更新；应用于后续任务")
    def run_mapper(self):
        if self.current_index<0:return
        from ..mtfmapper import run_mapper
        try:
            directory=QFileDialog.getExistingDirectory(self,"MTF Mapper 独立输出目录")
            if not directory:return
            pid=run_mapper(self.config.mtf_mapper_path,self.entries[self.current_index]["path"],directory)
            self.add_log(f"MTF Mapper 独立复核已启动，PID {pid}；结果目录：{directory}")
        except Exception as exc:self.message_error(exc)
    def export_current(self):
        if self.current_index<0 or not self.entries[self.current_index]["result"]:self.message_error("先分析一张图像");return
        from .export_dialog import ExportDialog
        e=self.entries[self.current_index]
        dialog=ExportDialog(e['path'],self,directory=getattr(self,'report_directory',None))
        if not dialog.exec():return
        try:
            from ..export_plan import export_report
            exported=self.focus_overlay_result(e["result"],self.metric_selector.currentData()) if self.metric_selector.currentData() in {'best_focus','focus_offset'} and self.focus_data else e["result"]
            if not exported.optical_summary and not exported.analysis_summary:exported=self.direction_result(exported)
            else:
                exported=copy.copy(exported);exported.settings=dict(exported.settings,report_usaf_direction=self.usaf_direction.currentData(),report_frequency_index=self.usaf_frequency.currentData())
            folder=export_report(exported,e['preview'],dialog.options,self.metric_selector.currentData(),self.channel.currentText(),self.unit.currentText(),focus_data=self.focus_data)
            self.report_directory=dialog.options.directory
            message='报告已导出：'+str(folder);self.add_log(message);self.status_text.setText(message)
        except Exception as exc:self.message_error(exc)
    def export_gray(self):
        if self.current_index<0 or not self.entries[self.current_index]['result']:return
        entry=self.entries[self.current_index]
        if not entry['result'].optical_summary:self.message_error('先执行整卡多频率 / RGB 分析');return
        folder=QFileDialog.getExistingDirectory(self,'导出原尺寸 16-bit 灰度 TIFF、对齐有效掩码及参数')
        if not folder:return
        payload={'action':'gray_export','config':entry['result'].settings,'folder':self.folder_for_job(),'result':entry['result_path'],'destination':folder}
        uid=self.worker.submit(payload);self.jobs[uid]={'action':'gray_export'};self.cancel_button.setEnabled(True)
    def session_dialog(self):
        choice=QMessageBox(self);choice.setWindowTitle("会话");choice.setText("保存当前测量或打开已有会话目录")
        save=choice.addButton("保存当前会话",QMessageBox.ButtonRole.AcceptRole);open_=choice.addButton("打开会话",QMessageBox.ButtonRole.ActionRole);choice.addButton("取消",QMessageBox.ButtonRole.RejectRole)
        choice.exec()
        if choice.clickedButton()==save:self.save_session()
        elif choice.clickedButton()==open_:self.open_session()
    def save_session(self):
        folder=QFileDialog.getExistingDirectory(self,"保存会话到目录")
        if not folder:return
        try:
            if self.session:self.session.close()
            self.session=Session(folder)
            for e in self.entries:
                if e["result"]:self.session.add(e["result"])
            self.session.save_state("config",self.snapshot_config().to_dict())
            if self.focus_data:self.session.save_state("focus",self.focus_data)
            self.add_log("会话已保存："+folder)
        except Exception as exc:self.message_error(exc)
    def open_session(self):
        folder=QFileDialog.getExistingDirectory(self,"打开会话目录")
        if not folder:return
        try:
            if not (Path(folder)/"session.sqlite").is_file():raise ValueError("此目录不是 MUTEX 会话")
            session=Session(folder);results=session.load_results()
            for r in results:self.add_result(r)
            if self.session:self.session.close()
            self.session=session
            focus=session.state("focus")
            if focus:self.focus_data=focus;self.show_focus()
            self.add_log("已打开会话："+folder)
        except Exception as exc:self.message_error(exc)
    def open_result(self):
        paths,_=QFileDialog.getOpenFileNames(self,"打开分析结果","","MUTEX 分析结果 (*.json)")
        for path in paths:
            try:self.add_result(AnalysisResult.load(path),path)
            except Exception as exc:self.message_error(exc)
    def add_result(self,result,result_path=None):
        if any(e["path"]==result.image.path and e["result"] is not None for e in self.entries):return
        if not self.entries and result.template:
            from ..models import ChartDefinition
            chart=ChartDefinition.from_dict(result.template)
            existing=next((c for c in self.charts if recognizes(c,chart.id) or family_key(c)==family_key(chart)),None)
            if existing:chart=existing
            else:self.charts.append(chart)
            self.refresh_charts(chart.id)
            resources={k:self.config.to_dict()[k] for k in ['cache_dir','memory_mb','cache_gb','tile_cache_mb','workers','mtf_mapper_path']}
            self.config=AnalysisConfig.from_dict(dict(result.settings,chart_id=chart.id,**resources))
            self.restore_settings();self.chart_changed(preserve_registration=True)
        if not result_path:
            folder=Path(self.folder_for_job());result_path=str(folder/"result.json");result.save(result_path)
        entry={"path":result.image.path,"result":result,"metadata":result.image,"result_path":result_path,
               "preview":None,"focus_position":result.focus_position,"focus_unit":result.focus_unit,"status":"已分析"}
        self.entries.append(entry);self.images.addItem(QListWidgetItem());index=len(self.entries)-1;self.update_item(index)
        if Path(result.image.path).is_file():self.submit_image(index,"preview")
        else:self.add_log("源文件路径不存在，测量数据仍可查看："+result.image.path)
        if self.current_index<0:self.images.setCurrentRow(index)
        self.refresh_compare()
    def show_help(self):
        QMessageBox.information(self,"测量限制与兼容性",
          "支持 LibRaw 可解码的 ARW / NEF / RAF / CR2 / CR3 以及 RGB 16-bit TIFF。\n"
          "公开样本已解码验证：Sony A7R IV、Nikon Z8 无损、GFX100、Canon 5D IV / R5。SVG 与 8-bit RGB 扫描样本已完成原像素 USAF 流程检查；V850 实际 48-bit 输出和焦位序列仍待验收；Z8 HE/HE★ 首版不支持。\n\n"
          "本软件为工程测量，未声称 ISO/FADGI 认证。USAF / 二值星图为 CTF，斜边为 SFR；RAW 为线性相机 RGB。"
          "未知传递曲线、印刷误差、照明、混叠与机内处理都会影响数值。\n\n"
          "GPL-3.0-or-later；用户源图卡和私有内置资产许可独立。合成示例卡 CC0。")
    def on_zoom(self,percent):self.zoom_label.setText(f"预览缩放：{percent:.1f}%")
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():event.acceptProposedAction()
    def dropEvent(self,event):self.import_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.viewer.cancel_anchors();self.status_text.setText("已取消四点配准")
        else:super().keyPressEvent(event)
    def closeEvent(self,event):
        try:
            if self.persist_preferences:save_config(self.snapshot_config())
        except Exception:pass
        self.metric_selector.set_activity()
        self.watcher.stop();self.worker.close();self.viewer.close_reader();self.reference_viewer.close_reader()
        if self.session:self.session.close()
        event.accept()

