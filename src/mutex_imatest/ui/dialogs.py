from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QSpinBox,QDoubleSpinBox,QLineEdit,
 QComboBox,QDialogButtonBox,QTableWidget,QTableWidgetItem,QLabel,QFileDialog,QPushButton,QMessageBox,QCheckBox)
from ..config import AnalysisConfig

class PerformanceDialog(QDialog):
    def __init__(self,config,parent=None):
        super().__init__(parent);self.setWindowTitle("资源与解码设置");self.resize(480,440)
        self.original=config;layout=QVBoxLayout(self);form=QFormLayout()
        self.memory=QSpinBox();self.memory.setRange(0,65536);self.memory.setSingleStep(512);self.memory.setSuffix(" MiB");self.memory.setSpecialValueText("自动：40% RAM，最多 8 GiB");self.memory.setValue(config.memory_mb)
        self.cache=QDoubleSpinBox();self.cache.setRange(1,1024);self.cache.setSuffix(" GiB");self.cache.setValue(config.cache_gb)
        self.tile=QSpinBox();self.tile.setRange(16,4096);self.tile.setSuffix(" MiB");self.tile.setValue(config.tile_cache_mb)
        self.path=QLineEdit(str(config.cache_path()))
        self.demosaic=QComboBox();self.demosaic.addItems(["AHD","VNG"]);self.demosaic.setCurrentText(config.demosaic)
        self.pixel=QDoubleSpinBox();self.pixel.setRange(0,100);self.pixel.setDecimals(3);self.pixel.setSpecialValueText("未标定");self.pixel.setSuffix(" µm");self.pixel.setValue(config.sensor_pixel_um)
        self.mapper=QLineEdit(config.mtf_mapper_path)
        form.addRow("RAW 内存预算",self.memory);form.addRow("解码缓存上限",self.cache);form.addRow("显示瓦片缓存",self.tile);form.addRow("缓存目录",self.path)
        form.addRow("Bayer 去马赛克",self.demosaic);form.addRow("传感器像元间距",self.pixel);form.addRow("MTF Mapper 可执行文件",self.mapper)
        layout.addLayout(form)
        note=QLabel("逐个文件分析以控制峰值内存。预算依据解码尺寸估算；大压缩 RAW 可先外部转为线性 16-bit TIFF。X-Trans 使用 VNG。MTF Mapper 作为独立复核工具运行。")
        note.setWordWrap(True);layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def accept(self):
        data=self.original.to_dict()
        data.update(memory_mb=self.memory.value(),cache_gb=self.cache.value(),tile_cache_mb=self.tile.value(),
                    cache_dir=self.path.text(),demosaic=self.demosaic.currentText(),sensor_pixel_um=self.pixel.value(),
                    mtf_mapper_path=self.mapper.text())
        try:self.config=AnalysisConfig.from_dict(data).validate()
        except Exception as exc:QMessageBox.warning(self,"设置错误",str(exc));return
        super().accept()

class FocusSetupDialog(QDialog):
    def __init__(self,entries,metric="mtf50",parent=None):
        super().__init__(parent);self.setWindowTitle("焦位 / 扫描仪垫高序列");self.resize(750,570);self.entries=entries
        layout=QVBoxLayout(self)
        note=QLabel("至少 5 个不同焦位，推荐 7–11 个；最高值两侧各需至少 2 个采样。\n未输入实际高度时使用相对序号；相对序号不会换算成机械倾角。")
        note.setWordWrap(True);layout.addWidget(note)
        form=QHBoxLayout();self.unit=QComboBox()
        self.unit.addItem("相对序号","index");self.unit.addItem("毫米 mm","mm");self.unit.addItem("微米 µm","um")
        units={e["result"].focus_unit for e in entries}
        if len(units)==1:self.unit.setCurrentIndex(self.unit.findData(next(iter(units))))
        self.metric_selector=QComboBox()
        for label,value in [("整卡多频率调焦评分","usaf_focus_score"),("已确认分辨率（离散）","resolution_limit"),("斜边 MTF50","mtf50"),("斜边 MTF50P","mtf50p"),("星图 / USAF 固定频率对比度","contrast_at_frequency"),("CTF50","ctf50")]:self.metric_selector.addItem(label,value)
        if any(e['result'].optical_summary for e in entries):metric='usaf_focus_score'
        idx=self.metric_selector.findData(metric);self.metric_selector.setCurrentIndex(max(0,idx))
        self.channel=QComboBox();self.channel.addItems(["ALL","G","R","B","Y","Y_align"])
        self.objective=QComboBox()
        for label,value in [("优先改善较弱区域","balanced"),("全幅平均","mean"),("中心优先","center")]:self.objective.addItem(label,value)
        form.addWidget(self.unit);form.addWidget(self.metric_selector);form.addWidget(self.channel);form.addWidget(self.objective);layout.addLayout(form)
        self.height_calibrated=QCheckBox("高度为图卡 / 载台实测轴向位移（与图卡尺寸一起用于表观倾角）")
        self.height_calibrated.setChecked(all(Path(e["path"]).name.startswith("synthetic_") for e in entries))
        layout.addWidget(self.height_calibrated)
        self.table=QTableWidget(len(entries),3);self.table.setHorizontalHeaderLabels(["图像","焦位 / 高度","有效 ROI"])
        self.table.horizontalHeader().setStretchLastSection(True)
        for row,e in enumerate(entries):
            r=e["result"];name=QTableWidgetItem(Path(r.image.path).name);name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row,0,name);self.table.setItem(row,1,QTableWidgetItem(str(r.focus_position if r.focus_position is not None else row)))
            count=QTableWidgetItem(str(sum(m.valid for m in r.measurements)));count.setFlags(count.flags() & ~Qt.ItemFlag.ItemIsEditable);self.table.setItem(row,2,count)
        self.table.resizeColumnsToContents();layout.addWidget(self.table,1)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("拟合焦位与场曲")
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def accept(self):
        try:
            values=[float(self.table.item(row,1).text()) for row in range(len(self.entries))]
            if len(set(values))<5:raise ValueError("需要至少 5 个不同焦位")
            for value in values:
                if not __import__("math").isfinite(value):raise ValueError("焦位必须是有限数值")
            self.positions=values
        except (ValueError,AttributeError) as exc:QMessageBox.warning(self,"焦位错误",str(exc));return
        super().accept()

