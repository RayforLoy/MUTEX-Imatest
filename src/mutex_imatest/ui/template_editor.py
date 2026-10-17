from __future__ import annotations
from pathlib import Path
import copy,json,uuid
from PySide6.QtCore import Qt,QRectF,Signal
from PySide6.QtGui import QPixmap,QPen,QColor,QBrush
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QComboBox,
 QDialogButtonBox,QPlainTextEdit,QGraphicsView,QGraphicsScene,QTableWidget,QTableWidgetItem,
 QPushButton,QFileDialog,QMessageBox,QDoubleSpinBox,QCheckBox,QLabel,QSpinBox,QInputDialog)
from ..models import Region,ChartDefinition
from ..templates import import_source,load_chart,save_chart,library_dir,render_source
from ..workers import WorkerManager
from ..config import AnalysisConfig

KIND_NAMES={"edge":"斜边 SFR","usaf":"USAF 三线对","star":"西门子星","wedge":"分辨率楔形 CTF","flat":"均匀 / 噪声块","step":"灰阶 / OECF 块",
            "color":"色块 ΔE","grid":"棋盘格几何","point":"点像 / PSF","texture":"纹理频谱"}
KIND_NAMES.update({'dot':'点阵畸变 / 二维色差','logf':'对数频率 / 对比度','flare':'遮光陷阱眩光','rings':'同心圆 / 角度参考'})
DEFAULT_PARAMS={"usaf":{"group":1,"element":1,"direction":"vertical"},"star":{"cycles":72,"pattern":"binary"},
                "wedge":{"direction":"vertical","pattern":"binary","frequency_samples":[]},
                "grid":{"rows":7,"cols":9},"color":{"rgb_space":"sRGB","reference_lab":[50,0,0]},
                "step":{"reference_density":1},"point":{"point_diameter_px":.25}}
DEFAULT_PARAMS.update({'dot':{'rows':7,'cols':9},'logf':{'f_start':.01,'f_end':.4,'reference_modulation':.6,'pattern':'sinusoidal','direction':'vertical'},
 'flare':{'dark_box':[.4,.4,.2,.2],'bright_box':[.1,.1,.2,.2],'black_level':0},'rings':{}})
HELP_TEXT={
 "edge":"区域内只保留一条干净斜边，推荐 2°–7°；避免文字、边框和其他线条。",
 "usaf":"框住单个三条线元素；填写组 / 元素编号与方向。lp/mm 需要实际图卡尺寸标定。",
 "star":"cycles 是一圈黑白线对数。binary 得到 CTF；sinusoidal 且提供 reference_modulation 才输出 MTF。",
 "wedge":"框住单个频率渐变楔形。frequency_samples 至少含两组 {t, cycles_across}：t 为沿楔形长度的 0–1 位置，cycles_across 为该处横跨 ROI 宽度的线对数。请按实际图案填写，勿套用其他图卡数值；只有通过条纹分离和质量检查的区间参与 CTF 判读。",
 "flat":"需要无图案的均匀区域。单帧结果含图卡与照明不均，不能直接当成传感器时域噪声。",
 "step":"提供 reference_density 或 reference_luminance；每个灰阶块单独添加 ROI。",
 "color":"必须是已标定 sRGB 线性数据和 D65 Lab 参考值；RAW 相机 RGB 不能直接计算颜色准确度。",
 "grid":"框住完整棋盘格，rows/cols 为内部角点数；残差同时含图卡印刷误差。",
 "point":"point_diameter_px 小于 0.5 时才近似点源。边界需含足够背景。",
 "texture":"输出纹理功率谱；高频能量含噪声和锐化，不能当作光学 MTF。"}
HELP_TEXT.update({'dot':'填写实际点阵行列数；完整阵列用于径向畸变拟合和 RGB 二维质心差。',
 'logf':'f_start/f_end 为当前图像 ROI 的原生 cy/px；参考调制度和方向必须匹配。方波图只输出基频 CTF。',
 'flare':'dark_box/bright_box 是本 ROI 内归一化取样框；暗区必须是真实遮光陷阱。结果为工程比值。',
 'rings':'center_px 是 ROI 内原像素中心，可选 transition_angles_deg 按检出的边界顺序填写。缺少角度只输出像素半径。'})
class RegionDialog(QDialog):
    def __init__(self,region,parent=None):
        super().__init__(parent);self.setWindowTitle("测量区域");self.resize(460,440);self.original=region
        layout=QVBoxLayout(self);form=QFormLayout()
        self.name=QLineEdit(region.label or region.id)
        self.kind=QComboBox()
        for k,v in KIND_NAMES.items():self.kind.addItem(v,k)
        self.kind.setCurrentIndex(self.kind.findData(region.kind))
        self.enabled=QCheckBox("参与分析");self.enabled.setChecked(region.enabled)
        form.addRow("名称",self.name);form.addRow("图案类型",self.kind);form.addRow("",self.enabled)
        layout.addLayout(form)
        self.help=QLabel();self.help.setWordWrap(True);layout.addWidget(self.help)
        layout.addWidget(QLabel("图案参数（JSON）"))
        self.params=QPlainTextEdit(json.dumps(region.params,ensure_ascii=False,indent=2));layout.addWidget(self.params)
        self.kind.currentIndexChanged.connect(self.change_kind);self.change_kind(initial=True)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def change_kind(self,*args,initial=False):
        kind=self.kind.currentData();self.help.setText(HELP_TEXT[kind])
        if not initial:self.params.setPlainText(json.dumps(DEFAULT_PARAMS.get(kind,{}),ensure_ascii=False,indent=2))
    def accept(self):
        try:
            params=json.loads(self.params.toPlainText())
            if not isinstance(params,dict):raise ValueError("参数必须是 JSON 对象")
            self.region=Region(self.original.id,self.kind.currentData(),self.original.box,self.name.text().strip(),params,self.enabled.isChecked())
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,"参数错误",str(exc));return
        super().accept()

class RoiCanvas(QGraphicsView):
    drawn=Signal(tuple)
    def __init__(self,parent=None):
        super().__init__(parent);self.setScene(QGraphicsScene(self));self.start=None;self.rect=None
        self.setBackgroundBrush(QColor("#e5ebf0"));self.setCursor(Qt.CursorShape.CrossCursor)
    def load(self,preview):
        self.scene().clear();self.rect=None;self.start=None
        pixmap=QPixmap(str(preview))
        if pixmap.isNull():pixmap=QPixmap(1000,700);pixmap.fill(QColor("white"))
        self.scene().addPixmap(pixmap);self.scene().setSceneRect(0,0,pixmap.width(),pixmap.height());self.fitInView(self.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)
    def resizeEvent(self,event):
        super().resizeEvent(event);self.fitInView(self.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            p=self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(p):
                self.start=p;self.rect=self.scene().addRect(QRectF(p,p),QPen(QColor("#0d8d8b"),2),QBrush(QColor(20,140,140,30)))
    def mouseMoveEvent(self,event):
        if self.start and self.rect:
            p=self.mapToScene(event.position().toPoint());self.rect.setRect(QRectF(self.start,p).normalized().intersected(self.sceneRect()))
    def mouseReleaseEvent(self,event):
        if not self.start or not self.rect:return
        r=self.rect.rect();s=self.sceneRect();self.scene().removeItem(self.rect);self.rect=None;self.start=None
        if min(r.width(),r.height())>5:self.drawn.emit((r.x()/s.width(),r.y()/s.height(),r.width()/s.width(),r.height()/s.height()))

class TemplateEditor(QDialog):
    chart_saved=Signal(object)
    def __init__(self,chart=None,parent=None):
        super().__init__(parent);self.setWindowTitle("图卡模板编辑器");self.resize(1180,820)
        self.chart=copy.deepcopy(chart) if chart else ChartDefinition(uuid.uuid4().hex,"新图卡",[])
        self.target_worker=WorkerManager(self);self.target_worker.event.connect(self.target_event);self.target_job=None
        self.finished.connect(lambda:self.target_worker.close())
        layout=QVBoxLayout(self)
        top=QHBoxLayout()
        self.name=QLineEdit(self.chart.name);top.addWidget(QLabel("图卡名称"));top.addWidget(self.name,1)
        self.page=QSpinBox();self.page.setRange(1,999);self.page.setValue(self.chart.source_page+1);top.addWidget(QLabel("PDF 页"));top.addWidget(self.page)
        source=QPushButton("导入 SVG / PDF / 图像");source.clicked.connect(self.open_source);top.addWidget(source)
        json_button=QPushButton("读取模板 / 图卡包");json_button.clicked.connect(self.open_json);top.addWidget(json_button)
        layout.addLayout(top)
        calibration=QHBoxLayout()
        self.width=QDoubleSpinBox();self.height=QDoubleSpinBox()
        for spin in [self.width,self.height]:spin.setRange(.001,10000);spin.setDecimals(3);spin.setSuffix(" mm")
        self.width.setValue((self.chart.physical_size_mm or (100,100))[0]);self.height.setValue((self.chart.physical_size_mm or (100,100))[1])
        self.calibrated=QCheckBox("实际尺寸已校准");self.calibrated.setChecked(self.chart.calibrated)
        calibration.addWidget(QLabel("实际宽 × 高"));calibration.addWidget(self.width);calibration.addWidget(self.height);calibration.addWidget(self.calibrated);calibration.addStretch()
        layout.addLayout(calibration)
        info=QLabel("在预览上拖动框选区域。源 SVG / PDF 仅保留本地路径；导出加密模板只包含栅格参考和测量定义。");info.setWordWrap(True);layout.addWidget(info)
        body=QHBoxLayout()
        self.canvas=RoiCanvas();self.canvas.load(self.chart.preview);self.canvas.drawn.connect(self.add_region);body.addWidget(self.canvas,3)
        right=QVBoxLayout()
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(["名称","类型","启用"]);self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.edit_region);right.addWidget(self.table,1)
        self.target_info=QLabel('');self.target_info.setWordWrap(True);right.addWidget(self.target_info)
        self.detect_targets_button=QPushButton('自动识别星图 / 斜边');self.detect_targets_button.clicked.connect(lambda:self.detect_targets());right.addWidget(self.detect_targets_button)
        self.roi_buttons=[]
        for label,callback in [("编辑选中区域",self.edit_region),("复制选中区域",self.duplicate_region),("删除选中区域",self.delete_region),("整卡 USAF · 全频率 / 双向",self.detect_full_usaf),("从 SVG 识别单频 USAF",self.detect_usaf),("生成规则斜边网格",self.add_grid)]:
            button=QPushButton(label);button.clicked.connect(callback);right.addWidget(button);self.roi_buttons.append(button)
        body.addLayout(right,2);layout.addLayout(body,1)
        buttons=QHBoxLayout();buttons.addStretch()
        self.export_button=QPushButton("导出加密模板…");self.export_button.clicked.connect(self.export);buttons.addWidget(self.export_button)
        self.save_button=QPushButton("保存到图卡库");self.save_button.setObjectName("primary");self.save_button.clicked.connect(self.save);buttons.addWidget(self.save_button)
        cancel=QPushButton("关闭");cancel.clicked.connect(self.reject);buttons.addWidget(cancel);layout.addLayout(buttons)
        self.refresh()
    def refresh(self):
        self.table.setRowCount(len(self.chart.regions))
        self.canvas.load(self.chart.preview)
        s=self.canvas.sceneRect()
        for row,r in enumerate(self.chart.regions):
            for col,value in enumerate([r.label,KIND_NAMES[r.kind],"✓" if r.enabled else ""]):self.table.setItem(row,col,QTableWidgetItem(value))
            x,y,w,h=r.box
            self.canvas.scene().addRect(x*s.width(),y*s.height(),w*s.width(),h*s.height(),QPen(QColor("#16a09b"),1.4))
        self.table.resizeColumnsToContents()
    def add_region(self,box):
        if self.target_job:return
        region=Region(uuid.uuid4().hex[:10],"edge",box,f"区域 {len(self.chart.regions)+1}")
        dialog=RegionDialog(region,self)
        if dialog.exec():self.chart.regions.append(dialog.region);self.refresh()
    def edit_region(self,*args):
        if self.target_job:return
        row=self.table.currentRow()
        if row<0:return
        dialog=RegionDialog(self.chart.regions[row],self)
        if dialog.exec():self.chart.regions[row]=dialog.region;self.refresh()
    def duplicate_region(self):
        if self.target_job:return
        row=self.table.currentRow()
        if row<0:return
        r=copy.deepcopy(self.chart.regions[row]);r.id=uuid.uuid4().hex[:10];r.label+=" 副本"
        self.chart.regions.append(r);self.refresh()
    def delete_region(self):
        if self.target_job:return
        row=self.table.currentRow()
        if row>=0:self.chart.regions.pop(row);self.refresh()
    def add_grid(self):
        if self.target_job:return
        rows,ok=QInputDialog.getInt(self,"斜边网格","行数（请先确认图卡排列）",3,1,16)
        if not ok:return
        cols,ok=QInputDialog.getInt(self,"斜边网格","列数",3,1,16)
        if not ok:return
        for iy in range(rows):
            for ix in range(cols):
                self.chart.regions.append(Region(uuid.uuid4().hex[:10],"edge",((ix+.25)/cols,(iy+.25)/rows,.5/cols,.5/rows),f"网格 {iy+1}·{ix+1}"))
        self.refresh()
    def open_source(self):
        path,_=QFileDialog.getOpenFileName(self,"导入本地图卡源","","图卡源 (*.svg *.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if not path:return
        try:
            imported=import_source(path,page=self.page.value()-1)
            self.cancel_target_detection();self.chart=imported;self.name.setText(self.chart.name)
            if self.chart.physical_size_mm:self.width.setValue(self.chart.physical_size_mm[0]);self.height.setValue(self.chart.physical_size_mm[1])
            self.calibrated.setChecked(False);self.refresh()
            if Path(path).suffix.lower()=='.pdf':self.detect_targets(quiet=True)
        except Exception as exc:QMessageBox.warning(self,"图卡导入失败",str(exc))
    def detect_targets(self,quiet=False):
        try:
            if self.target_job:return
            chart=self.updated();config=AnalysisConfig()
            folder=config.cache_path()/'jobs'/uuid.uuid4().hex;folder.mkdir(parents=True,exist_ok=True)
            self.target_source=(chart.id,chart.source_path,chart.source_page)
            self.target_job=self.target_worker.submit({'action':'prepare_targets','chart':chart.to_dict(),'config':config.to_dict(),'folder':str(folder)})
            self.set_target_busy(True)
            self.target_info.setText('正在后台识别星图与斜边；完成后请检查候选区域。关闭编辑器可取消。')
        except Exception as exc:
            self.target_job=None;self.set_target_busy(False)
            self.target_info.setText('未生成自动区域：'+str(exc))
            if not quiet:QMessageBox.warning(self,'图卡识别',str(exc))
    def set_target_busy(self,busy):
        for widget in [self.detect_targets_button,self.canvas,self.table,self.save_button,self.export_button,*self.roi_buttons]:widget.setEnabled(not busy)
    def cancel_target_detection(self):
        if self.target_job:
            self.target_worker.close();self.target_job=None
        self.set_target_busy(False)
    def target_event(self,uid,event):
        if uid!=self.target_job:return
        if event['type']=='progress':self.target_info.setText(event['message']);return
        if event['type'] not in {'done','error','cancelled'}:return
        self.target_job=None;self.set_target_busy(False)
        if self.target_source!=(self.chart.id,self.chart.source_path,self.chart.source_page):
            self.target_info.setText('图卡已改变，未应用旧识别结果');return
        if event['type']=='done':
            prepared=load_chart(event['prepared_chart']);self.chart.regions=prepared.regions;self.chart.notes=prepared.notes
            counts={kind:sum(r.enabled and r.kind==kind for r in self.chart.regions) for kind in ['star','edge','wedge']}
            self.target_info.setText(f"候选区域：星图 {counts['star']}，斜边 {counts['edge']}，楔形 {counts['wedge']}。请检查区域、参数与实际尺寸后保存。")
            self.refresh()
        else:self.target_info.setText('未生成自动区域：'+event.get('message','任务已取消'))
    def detect_usaf(self):
        if self.target_job:return
        if not self.chart.source_path or Path(self.chart.source_path).suffix.lower()!=".svg":
            QMessageBox.information(self,"USAF 矢量识别","请先导入 SVG 图卡源文件");return
        group,ok=QInputDialog.getInt(self,"USAF 矢量识别","组 (Group)",3,-2,9)
        if not ok:return
        element,ok=QInputDialog.getInt(self,"USAF 矢量识别","元素 (Element)",5,1,6)
        if not ok:return
        names=["竖线（横向细节）","横线（纵向细节）","两个方向"]
        choice,ok=QInputDialog.getItem(self,"USAF 矢量识别","测量方向；热力图应比较相同频率和方向",names,0,False)
        if not ok:return
        try:
            from ..vector_usaf import detect_svg_usaf
            regions,fiducials,size=detect_svg_usaf(self.chart.source_path,group,element,["vertical","horizontal","both"][names.index(choice)])
            self.chart.regions=regions;self.chart.fiducials=fiducials;self.chart.physical_size_mm=size
            self.width.setValue(size[0]);self.height.setValue(size[1])
            self.chart.notes=f"SVG 矢量 USAF {group}/{element}；{choice}。需按实物确认尺寸并配准；原图像素参与测量。"
            self.refresh()
            QMessageBox.information(self,"USAF 区域已生成",f"已生成 {len(regions)} 个测量区域。请确认实物尺寸，并在主窗口配准后分析。")
        except Exception as exc:QMessageBox.warning(self,"USAF 识别失败",str(exc))
    def detect_full_usaf(self):
        if self.target_job:return
        try:
            from ..vector_usaf import detect_svg_usaf
            if not self.chart.source_path:raise ValueError('请先导入 SVG 源文件')
            self.chart.regions,self.chart.fiducials,size=detect_svg_usaf(self.chart.source_path,all_frequencies=True)
            self.chart.physical_size_mm=size;self.width.setValue(size[0]);self.height.setValue(size[1])
            self.chart.notes='整卡多频率 USAF，双向 CTF；SVG 可见墨迹预检选择无遮挡取样带。扫描测量仅使用原始像素。'
            self.refresh()
        except Exception as exc:QMessageBox.warning(self,'整卡识别失败',str(exc))
    def open_json(self):
        path,_=QFileDialog.getOpenFileName(self,"读取图卡模板","","图卡模板 (*.mxtpl *.json *.mchart)")
        if not path:return
        try:
            from .template_manager import load_chart_dialog
            imported=load_chart_dialog(path,self)
            if imported is None:return
            self.cancel_target_detection();self.chart=imported;self.name.setText(self.chart.name)
            if self.chart.physical_size_mm:self.width.setValue(self.chart.physical_size_mm[0]);self.height.setValue(self.chart.physical_size_mm[1])
            self.calibrated.setChecked(self.chart.calibrated);self.refresh()
        except Exception as exc:QMessageBox.warning(self,"模板错误",str(exc))
    def updated(self):
        self.chart.name=self.name.text().strip()
        if not self.chart.name:raise ValueError("需要图卡名称")
        self.chart.physical_size_mm=(self.width.value(),self.height.value())
        self.chart.calibrated=self.calibrated.isChecked()
        self.chart.__post_init__()
        return self.chart
    def save(self):
        if self.target_job:return
        try:
            chart=self.updated()
            if chart.id.startswith("mutex-synthetic"):chart.id=uuid.uuid4().hex
            save_chart(chart,library_dir()/(chart.id+".json"))
            self.chart_saved.emit(chart);self.accept()
        except Exception as exc:QMessageBox.warning(self,"保存失败",str(exc))
    def export(self):
        if self.target_job:return
        try:
            from .template_manager import export_template_dialog
            path=export_template_dialog(self.updated(),self)
            if path:self.target_info.setText('加密模板已导出：'+str(path))
        except Exception as exc:QMessageBox.warning(self,"导出失败",str(exc))
