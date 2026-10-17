"""Always-visible analysis checklist; checking a task and viewing a result are separate."""
from PySide6.QtCore import Qt,QSize,Signal,QModelIndex,QTimer,QRectF
from PySide6.QtGui import QStandardItemModel,QStandardItem,QColor,QFont,QPen
from PySide6.QtWidgets import QListView,QStyledItemDelegate,QStyle,QStyleOptionButton,QApplication,QAbstractItemView,QToolTip
from ..analysis_catalog import SEQUENCE_METRICS,METRIC_DESCRIPTIONS
from .availability import ENABLED_TEXT,DISABLED_TEXT,DISABLED_BACKGROUND

STATUS_ROLE=int(Qt.ItemDataRole.UserRole)+21
ACTIVITY_ROLE=STATUS_ROLE+2


class MetricDelegate(QStyledItemDelegate):
    def helpEvent(self,event,view,option,index):
        # Qt can also deliver help events for disabled rows: their prerequisite
        # explanation is especially useful, so do not gate this on item flags.
        if index.isValid() and hasattr(view,'tooltip_text'):
            QToolTip.showText(event.globalPos(),view.tooltip_text(index.row()),view.viewport(),option.rect)
            return True
        return super().helpEvent(event,view,option,index)
    def paint(self,painter,option,index):
        enabled=bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        selected=enabled and bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save();painter.fillRect(option.rect,QColor('#d5efec' if selected else '#ffffff' if enabled else DISABLED_BACKGROUND))
        left=option.rect.left()+30
        if index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            checkbox=QStyleOptionButton();checkbox.rect=option.rect.adjusted(7,13,0,0);checkbox.rect.setSize(QSize(16,16))
            checkbox.state=(QStyle.StateFlag.State_Enabled if enabled else QStyle.StateFlag.State_None) | (QStyle.StateFlag.State_On if index.data(Qt.ItemDataRole.CheckStateRole)==Qt.CheckState.Checked.value else QStyle.StateFlag.State_Off)
            QApplication.style().drawControl(QStyle.ControlElement.CE_CheckBox,checkbox,painter)
        else:left=option.rect.left()+10
        painter.setPen(QColor(ENABLED_TEXT if enabled else DISABLED_TEXT));font=QFont(option.font);font.setBold(enabled);painter.setFont(font)
        activity=index.data(ACTIVITY_ROLE) or {}
        line=option.rect.adjusted(left-option.rect.left(),3,-27 if activity else -7,-21)
        painter.drawText(line,Qt.AlignmentFlag.AlignVCenter,painter.fontMetrics().elidedText(str(index.data() or ''),Qt.TextElideMode.ElideRight,line.width()))
        font.setBold(False);font.setPixelSize(10);painter.setFont(font);painter.setPen(QColor('#617986' if enabled else DISABLED_TEXT))
        line=option.rect.adjusted(left-option.rect.left(),22,-7,-2)
        text=activity.get('text') or index.data(STATUS_ROLE) or ''
        painter.drawText(line,Qt.AlignmentFlag.AlignVCenter,painter.fontMetrics().elidedText(text,Qt.TextElideMode.ElideRight,line.width()))
        state=activity.get('state')
        if state in {'running','cancelling'}:
            painter.setRenderHint(painter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor('#168b90'),2.3));painter.setBrush(Qt.BrushStyle.NoBrush)
            spinner=QRectF(option.rect.right()-21,option.rect.top()+7,12,12)
            phase=getattr(self.parent(),'animation_phase',0)
            painter.drawArc(spinner,int(phase*16),240*16)
            value=activity.get('progress')
            if value is not None:
                bar=QRectF(option.rect.left()+30,option.rect.bottom()-2,max(0,option.rect.width()-38),2)
                painter.fillRect(bar,QColor('#d9eeee'));bar.setWidth(bar.width()*max(0,min(100,value))/100);painter.fillRect(bar,QColor('#168b90'))
        elif state in {'error','cancelled'}:
            painter.setPen(QColor('#ad5037' if state=='error' else '#738795'))
            painter.drawText(option.rect.adjusted(option.rect.width()-24,0,-5,-16),Qt.AlignmentFlag.AlignCenter,'!' if state=='error' else '■')
        painter.restore()
    def sizeHint(self,option,index):return QSize(285,43)


class MetricChecklist(QListView):
    currentIndexChanged=Signal(int)
    checkedChanged=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.setObjectName('analysisChecklist')
        self.setModel(QStandardItemModel(self));self.setItemDelegate(MetricDelegate(self));self.setMouseTracking(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);self.preferred_checks=None;self.automatic_checks=True;self._updating=False
        self.selectionModel().currentChanged.connect(lambda current,previous:self.currentIndexChanged.emit(current.row()))
        self.model().itemChanged.connect(self._item_changed)
        self.animation_phase=0;self.activity_timer=QTimer(self);self.activity_timer.setInterval(80)
        self.activity_timer.timeout.connect(self._animate)
    def _animate(self):
        self.animation_phase=(self.animation_phase+24)%360;self.viewport().update()
    def set_activity(self,keys=(),state=None,progress=None,message=''):
        """Shared job progress; never pretend each metric has an independent pass."""
        keys=set(keys);active_rows=0
        for i in range(self.count()):
            activity=None;item=self.model().item(i)
            if self.itemData(i) in keys and item.isEnabled() and item.isCheckable():
                texts={'queued':'已排队 · 等待测量','running':'分析中 · 共用测量','cancelling':'正在取消','cancelled':'已取消','error':'分析失败'}
                text=texts.get(state,'')
                if state=='running' and progress is not None:text+=f' · {max(0,min(100,int(progress)))}%'
                activity={'state':state,'progress':progress,'text':text,'message':message}
                active_rows+=1
            item.setData(activity,ACTIVITY_ROLE)
        if state in {'running','cancelling'} and active_rows:
            if not self.activity_timer.isActive():self.activity_timer.start()
        else:self.activity_timer.stop()
        self.viewport().update()
    def addItem(self,text,value):
        item=QStandardItem(text);item.setData(value,Qt.ItemDataRole.UserRole);item.setEditable(False)
        item.setCheckable(value not in SEQUENCE_METRICS);item.setCheckState(Qt.CheckState.Unchecked)
        item.setData(item.data(Qt.ItemDataRole.CheckStateRole),STATUS_ROLE+1);self.model().appendRow(item)
    def count(self):return self.model().rowCount()
    def itemData(self,index,role=Qt.ItemDataRole.UserRole):return self.model().item(index).data(role)
    def itemText(self,index):return self.model().item(index).text()
    def findData(self,value):return next((i for i in range(self.count()) if self.itemData(i)==value),-1)
    def currentData(self):return self.currentIndex().data(Qt.ItemDataRole.UserRole)
    def currentText(self):return self.currentIndex().data() or ''
    def setCurrentIndex(self,index):
        index=self.model().index(index,0) if isinstance(index,int) else index
        super().setCurrentIndex(index)
        if index.isValid():self.scrollTo(index,QAbstractItemView.ScrollHint.EnsureVisible)
    def checked_keys(self):
        return [self.itemData(i) for i in range(self.count()) if self.model().item(i).isEnabled() and self.model().item(i).isCheckable() and self.model().item(i).checkState()==Qt.CheckState.Checked]
    def set_checked_keys(self,keys):
        self.automatic_checks=keys is None
        self.preferred_checks={self.currentData()} if keys is None else set(keys);self.apply_checks()
    def apply_checks(self):
        self._updating=True
        wanted=self.preferred_checks if self.preferred_checks is not None else {self.currentData()}
        for i in range(self.count()):
            item=self.model().item(i)
            item.setCheckState(Qt.CheckState.Checked if item.isCheckable() and item.isEnabled() and self.itemData(i) in wanted else Qt.CheckState.Unchecked)
            item.setData(item.data(Qt.ItemDataRole.CheckStateRole),STATUS_ROLE+1)
        self._updating=False
    def set_all_checked(self,checked):
        self.set_checked_keys([self.itemData(i) for i in range(self.count()) if self.model().item(i).isEnabled() and self.model().item(i).isCheckable()] if checked else [])
        self.checkedChanged.emit()
    def _item_changed(self,item):
        if self._updating:return
        # Availability and status updates must not masquerade as a user check.
        if item.data(Qt.ItemDataRole.CheckStateRole)==item.data(STATUS_ROLE+1):return
        item.setData(item.data(Qt.ItemDataRole.CheckStateRole),STATUS_ROLE+1)
        self.automatic_checks=False;self.preferred_checks=set(self.checked_keys());self.checkedChanged.emit()
    def set_status(self,index,status):
        self._updating=True;self.model().item(index).setData(status,STATUS_ROLE);self._updating=False
    def tooltip_text(self,index):
        import html
        esc=lambda value:html.escape(str(value),quote=True)
        item=self.model().item(index);key=self.itemData(index)
        description=METRIC_DESCRIPTIONS.get(key,'查看该分析的测量结果和质量标志。')
        reason=item.toolTip() or ('可用' if item.isEnabled() else '当前模板不支持此分析')
        status=item.data(STATUS_ROLE) or ''
        extra=f'<p>结果状态：{esc(status)}</p>' if status and status!=reason else ''
        activity=item.data(ACTIVITY_ROLE)
        if activity:extra+=f'<p>{esc(activity["text"])}：{esc(activity.get("message", ""))}<br>百分比为本图共用测量作业的进度。</p>'
        from ..evaluation_catalog import reference_text
        extra+='<p>'+esc(reference_text(key)).replace('\n','<br>')+'</p>'
        return f'<qt><b>{esc(item.text())}</b><p>{esc(description)}</p><p>可用条件：{esc(reason)}</p>{extra}</qt>'
