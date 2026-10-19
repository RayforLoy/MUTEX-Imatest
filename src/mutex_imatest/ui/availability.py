"""Explicit available/disabled dropdown rendering, independent of Qt themes."""
from PySide6.QtCore import Qt,QSize
from PySide6.QtGui import QColor,QFont
from PySide6.QtWidgets import QStyledItemDelegate,QStyle,QListView

ENABLED_TEXT='#075f66'
DISABLED_TEXT='#858b94'
ENABLED_BACKGROUND='#ffffff'
DISABLED_BACKGROUND='#eef0f3'
BASE_LABEL_ROLE=int(Qt.ItemDataRole.UserRole)+20


class AvailabilityDelegate(QStyledItemDelegate):
    def paint(self,painter,option,index):
        from .style import chrome_colors
        colors=chrome_colors()
        enabled=bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        selected=enabled and bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.fillRect(option.rect,QColor(colors['selected'] if selected else colors['base'] if enabled else colors['disabled_base']))
        painter.setPen(QColor(colors['enabled'] if enabled else colors['disabled']))
        font=QFont(option.font);font.setBold(enabled);painter.setFont(font)
        painter.drawText(option.rect.adjusted(11,0,-9,0),int(Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft),str(index.data() or ''))
        painter.restore()
    def sizeHint(self,option,index):
        size=super().sizeHint(option,index)
        return QSize(size.width()+30,max(29,size.height()+9))


def configure_availability(combo):
    view=QListView(combo);view.setMouseTracking(True);combo.setView(view)
    combo.setItemDelegate(AvailabilityDelegate(combo))
    combo.setMaxVisibleItems(20)


def set_availability(combo,index,enabled,reason='',label=None):
    from .style import chrome_colors
    colors=chrome_colors()
    item=combo.model().item(index)
    original=label or item.data(BASE_LABEL_ROLE) or item.text().removesuffix('  · 不可用')
    item.setData(original,BASE_LABEL_ROLE)
    item.setText(original if enabled else original+'  · 不可用')
    item.setEnabled(enabled)
    item.setForeground(QColor(colors['enabled'] if enabled else colors['disabled']))
    item.setBackground(QColor(colors['base'] if enabled else colors['disabled_base']))
    item.setToolTip(reason or ('可用' if enabled else '当前模板不支持此分析'))
