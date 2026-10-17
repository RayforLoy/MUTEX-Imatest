"""Template library, thumbnail browsing and password-encrypted export."""
from pathlib import Path
import copy
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QLabel,QCheckBox,
    QDialogButtonBox,QPushButton,QListWidget,QListWidgetItem,QFileDialog,QMessageBox,QInputDialog)
from ..templates import available_charts,load_chart,library_dir
from ..template_library import install_chart,copy_chart,rename_chart,archive_chart,user_chart_path
from .template_widgets import TemplatePreview,thumbnail,chart_details


class TemplatePasswordDialog(QDialog):
    def __init__(self,parent=None,*,export=False):
        super().__init__(parent);self.setWindowTitle('导出加密模板' if export else '导入加密模板');self.resize(510,230);self.password=None;self.exporting=export
        layout=QVBoxLayout(self);note=QLabel('设置模板包口令，导入时需要同一口令。只导出测量定义与栅格参考，不包含原始 SVG / PDF。' if export else '请输入此模板包的口令。')
        note.setWordWrap(True);layout.addWidget(note);form=QFormLayout()
        self.secret=QLineEdit();self.secret.setObjectName('templatePassword');self.secret.setEchoMode(QLineEdit.EchoMode.Password);self.secret.setMaxLength(1024);form.addRow('口令（至少 8 字符）',self.secret)
        self.confirm=QLineEdit();self.confirm.setObjectName('templatePasswordConfirm');self.confirm.setEchoMode(QLineEdit.EchoMode.Password);self.confirm.setMaxLength(1024)
        if export:form.addRow('再次输入',self.confirm)
        layout.addLayout(form);visible=QCheckBox('显示口令');visible.toggled.connect(lambda shown:[edit.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password) for edit in [self.secret,self.confirm]])
        layout.addWidget(visible);self.error=QLabel('');self.error.setStyleSheet('color:#ad5037');self.error.setWordWrap(True);layout.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('导出' if export else '解密导入');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def accept(self):
        password=self.secret.text()
        if len(password)<8:self.error.setText('口令至少需要 8 个字符');return
        if self.exporting and password!=self.confirm.text():self.error.setText('两次口令不一致');return
        self.password=password;self.secret.clear();self.confirm.clear();super().accept()
    def reject(self):
        self.password=None;self.secret.clear();self.confirm.clear();super().reject()


def load_chart_dialog(path,parent=None):
    if Path(path).suffix.lower()!='.mxtpl':return load_chart(path)
    dialog=TemplatePasswordDialog(parent)
    if not dialog.exec():return None
    try:return load_chart(path,password=dialog.password)
    finally:dialog.password=None


def import_template_dialog(parent=None):
    path,_=QFileDialog.getOpenFileName(parent,'导入图卡模板','','图卡模板 (*.mxtpl *.mchart *.json)')
    if not path:return None
    chart=load_chart_dialog(path,parent)
    return install_chart(chart) if chart is not None else None


def export_template_dialog(chart,parent=None):
    from ..export_plan import default_basename
    path,_=QFileDialog.getSaveFileName(parent,'导出加密模板（不包含源矢量）',default_basename(chart.name)+'.mxtpl','MUTEX 加密模板 (*.mxtpl)')
    if not path:return None
    path=Path(path)
    if path.suffix.lower()!='.mxtpl':path=Path(str(path)+'.mxtpl')
    if path.exists():raise FileExistsError('目标文件已存在，请换一个文件名；加密模板不会覆盖已有文件')
    dialog=TemplatePasswordDialog(parent,export=True)
    if not dialog.exec():return None
    try:
        from ..chart_package import export_chart_package
        return export_chart_package(chart,path,dialog.password)
    finally:dialog.password=None


class TemplateManager(QDialog):
    chart_selected=Signal(object)
    library_changed=Signal()
    def __init__(self,current=None,parent=None):
        super().__init__(parent);self.setWindowTitle('图卡模板管理');self.resize(950,640)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('选择模板可查看预览、测量图案、尺寸和许可。内置 / 公开模板可复制到用户库后编辑。'))
        row=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('按名称或图案搜索');self.search.textChanged.connect(self.filter);row.addWidget(self.search)
        refresh=QPushButton('刷新');refresh.clicked.connect(lambda:self.refresh());row.addWidget(refresh);layout.addLayout(row)
        body=QHBoxLayout();self.list=QListWidget();self.list.currentRowChanged.connect(self.select);body.addWidget(self.list,2)
        right=QVBoxLayout();self.preview=TemplatePreview();self.preview.image.setMinimumHeight(140);right.addWidget(self.preview)
        self.license=QLabel('');self.license.setWordWrap(True);self.license.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);right.addWidget(self.license)
        self.origin=QLabel('');self.origin.setWordWrap(True);right.addWidget(self.origin)
        self.use_button=QPushButton('使用选中模板');self.use_button.setObjectName('primary');self.use_button.clicked.connect(self.use);right.addWidget(self.use_button)
        self.edit_button=QPushButton('编辑 / 校准');self.edit_button.clicked.connect(self.edit);right.addWidget(self.edit_button)
        duplicate=QPushButton('复制到用户库');duplicate.clicked.connect(self.duplicate);right.addWidget(duplicate)
        self.rename_button=QPushButton('重命名');self.rename_button.clicked.connect(self.rename);right.addWidget(self.rename_button)
        self.archive_button=QPushButton('归档用户模板');self.archive_button.setToolTip('仅移走用户库中的定义，保留源文件；备份可从本机图卡库 backups 恢复');self.archive_button.clicked.connect(self.archive);right.addWidget(self.archive_button)
        export=QPushButton('导出加密模板…');export.clicked.connect(self.export);right.addWidget(export);right.addStretch();body.addLayout(right,2);layout.addLayout(body,1)
        bottom=QHBoxLayout()
        for title,callback in [('新建 / 导入 SVG、PDF',self.create),('导入模板包…',self.import_package)]:
            button=QPushButton(title);button.clicked.connect(callback);bottom.addWidget(button)
        bottom.addStretch();close=QPushButton('关闭');close.clicked.connect(self.accept);bottom.addWidget(close);layout.addLayout(bottom)
        self.status=QLabel('');self.status.setWordWrap(True);layout.addWidget(self.status);self.refresh(current.id if current else None)
    def current_chart(self):
        row=self.list.currentRow();return self.charts[row] if 0<=row<len(self.charts) else None
    def refresh(self,selected=None):
        self.charts=available_charts();self.list.blockSignals(True);self.list.clear()
        from PySide6.QtGui import QIcon
        from PySide6.QtCore import QSize
        self.list.setIconSize(QSize(85,62))
        for chart in self.charts:
            item=QListWidgetItem(QIcon(thumbnail(chart)),chart.name);item.setToolTip(chart_details(chart));self.list.addItem(item)
        self.list.blockSignals(False);index=next((i for i,c in enumerate(self.charts) if c.id==selected),0)
        self.list.setCurrentRow(index);self.filter(self.search.text());self.select(index)
    def select(self,row):
        chart=self.current_chart()
        if chart is None:return
        self.preview.set_chart(chart);self.license.setText('许可：'+chart.asset_license)
        user=user_chart_path(chart) is not None
        self.origin.setText('本机用户模板' if user else '公开模板 · 只读原版' if chart.id.startswith('public-') else '软件合成验证模板')
        self.rename_button.setEnabled(user);self.archive_button.setEnabled(user)
    def filter(self,text):
        for i,c in enumerate(getattr(self,'charts',[])):self.list.item(i).setHidden(text.casefold() not in (c.name+' '+chart_details(c)).casefold())
    def use(self):
        chart=self.current_chart()
        if chart:self.chart_selected.emit(chart);self.accept()
    def edited(self,chart):
        self.library_changed.emit();self.refresh(chart.id)
    def edit(self):
        chart=self.current_chart()
        if not chart:return
        from .template_editor import TemplateEditor
        draft=copy.deepcopy(chart)
        if user_chart_path(chart) is None:
            import uuid
            draft.id='user-'+uuid.uuid4().hex;draft.aliases=[];draft.name+=' · 副本'
        dialog=TemplateEditor(draft,self);dialog.chart_saved.connect(self.edited);dialog.exec()
    def create(self):
        from .template_editor import TemplateEditor
        dialog=TemplateEditor(parent=self);dialog.chart_saved.connect(self.edited);dialog.exec()
    def duplicate(self):
        try:self.edited(copy_chart(self.current_chart()))
        except Exception as exc:self.failure(exc)
    def rename(self):
        chart=self.current_chart()
        if not chart:return
        name,ok=QInputDialog.getText(self,'重命名模板','名称',text=chart.name)
        if ok:
            try:self.edited(rename_chart(chart,name))
            except Exception as exc:self.failure(exc)
    def archive(self):
        try:
            destination=archive_chart(self.current_chart());self.library_changed.emit();self.refresh();self.status.setText('已归档，可恢复：'+str(destination))
        except Exception as exc:self.failure(exc)
    def import_package(self):
        try:
            chart=import_template_dialog(self)
            if chart:self.edited(chart);self.status.setText('模板已导入本机图卡库')
        except Exception as exc:self.failure(exc)
    def export(self):
        try:
            path=export_template_dialog(self.current_chart(),self)
            if path:self.status.setText('加密模板已导出：'+str(path))
        except Exception as exc:self.failure(exc)
    def failure(self,exc):QMessageBox.warning(self,'模板操作未完成',str(exc))
