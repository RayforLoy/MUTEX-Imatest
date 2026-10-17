"""Thumbnail selection shared by the main window and template manager."""
from pathlib import Path
from collections import Counter
from PySide6.QtCore import Qt,QSize
from PySide6.QtGui import QPixmap,QIcon
from PySide6.QtWidgets import QComboBox,QWidget,QVBoxLayout,QLabel

KINDS={'edge':'斜边','star':'星图','wedge':'楔形','usaf':'USAF','grid':'棋盘格','flat':'均匀块','color':'色块','step':'灰阶','point':'点像','texture':'纹理'}


def chart_details(chart):
    counts=Counter(r.kind for r in chart.regions if r.enabled)
    kinds=' · '.join(f'{KINDS.get(k,k)} {n}' for k,n in counts.items()) or '尚无测量区域'
    size=' × '.join(f'{v:g}' for v in chart.physical_size_mm)+' mm' if chart.physical_size_mm else '未提供尺寸'
    return kinds+'\n'+size+' · '+('实物尺寸已校准' if chart.calibrated else '实物尺寸未确认')


def thumbnail(chart):
    if chart.preview and Path(chart.preview).is_file():return QPixmap(str(chart.preview))
    return QPixmap()


class TemplateComboBox(QComboBox):
    def __init__(self,parent=None):
        super().__init__(parent);self.setIconSize(QSize(60,44));self.setMaxVisibleItems(9)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(16);self.view().setMinimumWidth(410)
        self.setToolTip('选择图卡；列表缩略图与下方预览用于核对图案和覆盖范围')
    def add_chart(self,chart):
        pixmap=thumbnail(chart)
        self.addItem(QIcon(pixmap.scaled(72,54,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)) if not pixmap.isNull() else QIcon(),chart.name,chart.id)
        self.setItemData(self.count()-1,chart_details(chart),Qt.ItemDataRole.ToolTipRole)


class TemplatePreview(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(4)
        self.image=QLabel('暂无预览');self.image.setAlignment(Qt.AlignmentFlag.AlignCenter);self.image.setMinimumHeight(100);self.image.setMaximumHeight(145)
        self.image.setStyleSheet('background:white;border:1px solid #dce4ec;border-radius:5px;padding:3px;')
        self.info=QLabel('');self.info.setWordWrap(True);self.info.setObjectName('subtitle')
        layout.addWidget(self.image);layout.addWidget(self.info);self.original=QPixmap()
    def set_chart(self,chart):
        self.original=thumbnail(chart);self.info.setText(chart_details(chart));self.setToolTip(chart.name);self._fit()
    def _fit(self):
        if self.original.isNull():self.image.clear();self.image.setText('暂无预览 · 可在模板编辑器导入图卡');return
        self.image.setPixmap(self.original.scaled(max(80,self.image.width()-8),135,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    def resizeEvent(self,event):
        super().resizeEvent(event);self._fit()
