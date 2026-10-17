"""Report export choices; constructing or cancelling this dialog writes nothing."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,
    QComboBox,QCheckBox,QLabel,QPushButton,QFileDialog,QDialogButtonBox)
from ..export_plan import ExportOptions,default_basename,next_available_folder


class ExportDialog(QDialog):
    def __init__(self,image_path,parent=None,*,directory=None,options=None):
        super().__init__(parent);self.setWindowTitle('导出报告');self.resize(630,470)
        self.options=None;name=default_basename(image_path)
        initial=options or ExportOptions(directory or Path(image_path).parent/'reports',name,title=name+' · 光学测量报告')
        layout=QVBoxLayout(self);form=QFormLayout()
        self.directory=QLineEdit(str(initial.directory));self.directory.setObjectName('exportDirectory')
        browse=QPushButton('选择文件夹');browse.clicked.connect(self.browse_directory)
        row=QHBoxLayout();row.addWidget(self.directory,1);row.addWidget(browse);form.addRow('保存位置',row)
        self.basename=QLineEdit(initial.basename);self.basename.setObjectName('exportBasename');self.basename.setMaxLength(105)
        self.basename.setToolTip('不含路径的文件名；扩展名根据报告格式自动添加。也用于本次导出的文件夹名称。')
        form.addRow('报告文件名',self.basename)
        self.title=QLineEdit(initial.title);self.title.setObjectName('exportTitle');self.title.setMaxLength(80)
        form.addRow('报告显示标题',self.title)
        self.format=QComboBox();self.format.setObjectName('exportFormat')
        for label,value in [('HTML 和 PDF','both'),('仅 HTML（离线自包含）','html'),('仅 PDF','pdf')]:self.format.addItem(label,value)
        self.format.setCurrentIndex(max(0,self.format.findData(initial.format)));form.addRow('报告格式',self.format)
        layout.addLayout(form)
        self.include_detail=QCheckBox('附完整测量与曲线报告（所选项目汇总之外的详细报告）')
        self.include_detail.setObjectName('exportDetail');self.include_detail.setChecked(initial.include_detail)
        self.include_data=QCheckBox('附原始结果、测量表和序列参数（JSON / CSV）')
        self.include_data.setObjectName('exportData');self.include_data.setChecked(initial.include_data)
        self.include_images=QCheckBox('附可单独使用的热力图 PNG')
        self.include_images.setObjectName('exportImages');self.include_images.setChecked(initial.include_images)
        for check in [self.include_detail,self.include_data,self.include_images]:layout.addWidget(check)
        note=QLabel('报告内始终包含所需图像。所有文件都放入本次报告文件夹；名称重复时自动新建编号文件夹。')
        note.setWordWrap(True);layout.addWidget(note)
        self.destination=QLabel();self.destination.setObjectName('exportDestination');self.destination.setWordWrap(True)
        self.destination.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);layout.addWidget(self.destination)
        self.error=QLabel();self.error.setObjectName('exportError');self.error.setStyleSheet('color:#a03124');self.error.setWordWrap(True);layout.addWidget(self.error)
        layout.addStretch()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('导出')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for edit in [self.directory,self.basename]:edit.textChanged.connect(self.update_destination)
        self.update_destination()

    def browse_directory(self):
        directory=QFileDialog.getExistingDirectory(self,'选择报告保存位置',self.directory.text())
        if directory:self.directory.setText(directory)

    def selected_options(self):
        return ExportOptions(self.directory.text(),self.basename.text(),self.format.currentData(),self.title.text(),
                             self.include_data.isChecked(),self.include_images.isChecked(),self.include_detail.isChecked()).validate()

    def update_destination(self):
        try:
            options=self.selected_options()
            self.destination.setText('本次报告文件夹：'+str(next_available_folder(options.directory,options.basename)))
            self.error.clear()
        except ValueError as exc:self.destination.setText('本次报告文件夹：请填写合法文件名和目录');self.error.setText(str(exc))

    def accept(self):
        try:self.options=self.selected_options()
        except ValueError as exc:self.options=None;self.error.setText(str(exc));return
        super().accept()

    def reject(self):
        self.options=None
        super().reject()
