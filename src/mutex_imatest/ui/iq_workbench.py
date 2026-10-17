"""Visible entry points for referenced chart setup and advanced IQ workflows."""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from PySide6.QtCore import Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
                             QLabel, QLineEdit, QPushButton, QFileDialog, QPlainTextEdit,
                             QProgressBar, QCheckBox, QSpinBox, QMessageBox, QWidget, QSplitter)
from ..config import AnalysisConfig
from ..workers import WorkerManager
from ..templates import load_chart, save_chart, library_dir
from ..official_charts import PROFILES
from ..lab import WORKFLOWS
from ..lab_evaluation import WORKFLOW_GUIDANCE, workflow_reference_text, evaluation_text, assess_workflow


class FileField(QWidget):
    def __init__(self, title, filter="所有文件 (*)", directory=False, parent=None):
        super().__init__(parent)
        self.title, self.filter, self.directory = title, filter, directory
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(); layout.addWidget(self.edit, 1)
        button = QPushButton("浏览…"); button.clicked.connect(self.browse); layout.addWidget(button)

    def browse(self):
        if self.directory:
            path = QFileDialog.getExistingDirectory(self, self.title, self.edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, self.title, self.edit.text(), self.filter)
        if path:
            self.edit.setText(path)

    def text(self):
        return self.edit.text().strip()


class ProfileDialog(QDialog):
    chart_saved = Signal(object)

    def __init__(self, config=None, image_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Imatest / 标准图卡兼容设置"); self.resize(820, 700)
        self.config = copy.deepcopy(config or AnalysisConfig())
        self.worker = WorkerManager(self); self.worker.event.connect(self.on_event)
        self.finished.connect(lambda: self.worker.close()); self.job = None
        layout = QVBoxLayout(self); form = QFormLayout()
        self.profile = QComboBox()
        for key, profile in PROFILES.items():
            self.profile.addItem(profile["name"], key)
        form.addRow("图卡型号", self.profile)
        self.description = QLabel(); self.description.setWordWrap(True); form.addRow("", self.description)
        self.image = FileField("选择图卡拍摄图像", "图像 (*.tif *.tiff *.png *.jpg *.jpeg *.arw *.nef *.raf *.dng *.cr2 *.cr3)")
        self.image.edit.setText(image_path); form.addRow("拍摄 / 扫描图像", self.image)
        self.crop = QLineEdit("0, 0, 1, 1"); form.addRow("有效矩形 x,y,w,h（0–1）", self.crop)
        self.rows, self.cols = QSpinBox(), QSpinBox()
        for control in (self.rows, self.cols):
            control.setRange(1, 100)
        grid = QHBoxLayout(); grid.addWidget(self.rows); grid.addWidget(QLabel("行 ×")); grid.addWidget(self.cols); grid.addWidget(QLabel("列"))
        form.addRow("规则色块 / 内角点 / 点阵", grid)
        self.reference = FileField("选择随图卡参考", "CSV / CGATS (*.csv *.txt *.cgats *.cie *.q60);;所有文件 (*)")
        form.addRow("实测参考文件（可选）", self.reference)
        self.layout_file = FileField("选择图卡区域布局", "JSON 布局 (*.json)"); form.addRow("不规则布局 JSON", self.layout_file)
        self.match = QComboBox(); self.match.addItem("按色块编号严格匹配", "id"); self.match.addItem("按参考文件行顺序匹配", "order")
        form.addRow("参考匹配", self.match)
        self.illuminant = QComboBox(); self.illuminant.addItems(["D50", "D65"]); form.addRow("Lab / XYZ 参考白点", self.illuminant)
        self.transmissive = QCheckBox("透射图卡（仅确认后才计算图卡动态范围）"); form.addRow("", self.transmissive)
        layout.addLayout(form)
        layout.addWidget(QLabel("附加区域参数（JSON；例如点阵 asymmetric、星图 cycles、圆环 center_px）"))
        self.parameters = QPlainTextEdit("{}"); self.parameters.setMaximumHeight(100); layout.addWidget(self.parameters)
        note = QLabel("只使用你本机的图卡照片、布局和参考；不包含官方图卡源文件。色差需要已知 sRGB 或已标定 CCM。自动斜边结果请在模板编辑器核对。")
        note.setWordWrap(True); layout.addWidget(note)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        buttons = QHBoxLayout(); self.run_button = QPushButton("创建本机图卡模板"); self.run_button.clicked.connect(self.run)
        cancel = QPushButton("取消任务"); cancel.clicked.connect(self.worker.cancel_all)
        close = QPushButton("关闭"); close.clicked.connect(self.reject)
        buttons.addWidget(self.run_button); buttons.addWidget(cancel); buttons.addStretch(); buttons.addWidget(close); layout.addLayout(buttons)
        self.profile.currentIndexChanged.connect(self.profile_changed); self.profile_changed()

    def profile_changed(self):
        profile = PROFILES[self.profile.currentData()]
        self.description.setText(profile["detail"])
        self.rows.setValue(profile.get("rows", 7)); self.cols.setValue(profile.get("cols", 9))
        enabled = profile["mode"] in {"patches", "grid"}
        self.rows.setEnabled(enabled); self.cols.setEnabled(enabled)

    def run(self):
        try:
            if not Path(self.image.text()).is_file():
                raise ValueError("请选择本地图卡拍摄或扫描图像")
            box = [float(v.strip()) for v in self.crop.text().split(",")]
            if len(box) != 4 or min(box[:2]) < 0 or min(box[2:]) <= 0 or box[0]+box[2] > 1 or box[1]+box[3] > 1:
                raise ValueError("有效矩形必须位于 0–1 范围内")
            parameters = json.loads(self.parameters.toPlainText())
            if not isinstance(parameters, dict):
                raise ValueError("附加参数应为 JSON 对象")
            profile = PROFILES[self.profile.currentData()]
            options = {"box": box, "reference": self.reference.text() or None, "layout": self.layout_file.text() or None,
                       "match": self.match.currentData(), "illuminant": self.illuminant.currentText(),
                       "transmissive": self.transmissive.isChecked(), "parameters": parameters}
            if profile["mode"] in {"grid", "patches"}:
                options.update(rows=self.rows.value(), cols=self.cols.value())
            folder = library_dir()/"compatibility"/uuid.uuid4().hex
            self.job = self.worker.submit({"action": "prepare_profile", "path": self.image.text(), "profile": self.profile.currentData(),
                                           "config": self.config.to_dict(), "options": options, "folder": str(folder)})
            self.run_button.setEnabled(False); self.status.setText("正在准备图卡与参考…")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "图卡设置", str(exc))

    def on_event(self, uid, event):
        if self.job is not None and uid != self.job:
            return
        if event["type"] == "progress":
            self.progress.setValue(event["value"]); self.status.setText(event["message"])
        if event["type"] in {"done", "error", "cancelled"}:
            self.run_button.setEnabled(True); self.job = None
        if event["type"] == "done" and event.get("profile_chart"):
            chart = load_chart(event["profile_chart"])
            save_chart(chart, library_dir()/(chart.id+".json"))
            self.chart_saved.emit(chart); self.progress.setValue(100)
            self.status.setText(f"已创建 {len(chart.regions)} 个区域并保存到图卡库。关闭此窗口后可编辑区域，再运行分析。")
        elif event["type"] == "error":
            self.status.setText(event["message"])
        elif event["type"] == "cancelled":
            self.status.setText("已取消")


HINTS = {
    "compare": "依次选择参考图和被测图；ROI 为原像素 x,y,w,h。比较要求同尺度且已对齐。",
    "ptc": "顺序：暗场，再按曝光级别分组的平场。至少 4 级，每级至少两帧。接受线性单通道 DN TIFF/PNG；RAW 须指定 cfa_site:[0,0] 等周期位置及实际 saturation_dn。",
    "dark_flat": "文件顺序：暗场、平场、待校正图。输出单通道校正 TIFF 和增益/暗电平/有效掩码。",
    "ccm": "选择包含色块均值和参考的 result.json；也可在参数中填写 measured_rgb 与 reference_lab 三元组数组。",
    "oecf": "选择包含灰阶汇总的 result.json；导出表可在主界面输入曲线选项中使用。",
    "calibrate": "至少 5 张不同倾角、距离和画面位置的完整棋盘格/点阵。rows/cols 为内角点数；square_mm 为实测格距。",
    "undistort": "选择待校正图像，并在 calibration 中填写多视图生成的 camera-calibration.json。",
    "video": "选择一个视频；可指定原像素 roi。中性灰 ROI 用于 AWB，真实曝光/对焦阶跃时刻用 step_time 声明。",
    "sequence": "至少 3 张匹配图像。times_seconds 可提供实际时间戳；否则使用 interval_seconds。",
    "simulate": "选择一张线性参考图。显式设置模糊、满阱、读出噪声、PRNU、曝光、Gamma 和量化位数。",
    "capture": "source 可填本地视频路径。使用摄像头时显式填写 camera_index；默认不会打开摄像头。采集最多 1000 帧。",
    "test_plan": "选择测试计划 JSON，或在 plan 中填写路径。缺失测量、无效测点和未通过限值均不能判为通过。",
    "rank": "选择多张图像，在相同 ROI 中按有效 MTF50 排名；无有效斜边时保留相对焦点评分。",
}


class WorkbenchDialog(QDialog):
    def __init__(self, config=None, files=None, parent=None):
        super().__init__(parent); self.setWindowTitle("图像质量工作台"); self.resize(1040, 800)
        self.config = copy.deepcopy(config or AnalysisConfig()); self.job = None; self.report = None
        self.worker = WorkerManager(self); self.worker.event.connect(self.on_event); self.finished.connect(lambda: self.worker.close())
        layout = QVBoxLayout(self); form = QFormLayout()
        self.workflow = QComboBox()
        for key, (name, _) in WORKFLOWS.items():
            self.workflow.addItem(name, key)
        form.addRow("测量任务", self.workflow)
        self.hint = QLabel(); self.hint.setWordWrap(True); form.addRow("", self.hint)
        self.transfer = QComboBox()
        for label, value in [("线性（传感器标定必须）", "linear"), ("sRGB 编码", "srgb"), ("未知输入响应", "unknown")]:
            self.transfer.addItem(label, value)
        self.transfer.setCurrentIndex(max(0, self.transfer.findData(self.config.transfer)))
        form.addRow("输入传递曲线", self.transfer)
        self.destination = FileField("选择报告保存目录", directory=True)
        self.destination.edit.setText(str(Path.cwd()/"output"/"iq-workbench")); form.addRow("输出根目录", self.destination)
        layout.addLayout(form)
        splitter = QSplitter(); left, right = QWidget(), QWidget(); left_layout, right_layout = QVBoxLayout(left), QVBoxLayout(right)
        left_layout.addWidget(QLabel("输入文件（每行一个；保留所列顺序）"))
        self.files = QPlainTextEdit("\n".join(files or [])); left_layout.addWidget(self.files)
        choose = QPushButton("添加图像 / 视频 / 结果文件…"); choose.clicked.connect(self.add_files); left_layout.addWidget(choose)
        right_layout.addWidget(QLabel("测量参数（JSON；坐标为原像素）"))
        self.parameters = QPlainTextEdit(); right_layout.addWidget(self.parameters)
        self.reference = FileField("选择标定 / 测试计划 JSON", "JSON (*.json)")
        right_layout.addWidget(self.reference)
        insert = QPushButton("将此路径填入 calibration / plan / source"); insert.clicked.connect(self.insert_path); right_layout.addWidget(insert)
        splitter.addWidget(left); splitter.addWidget(right); layout.addWidget(splitter, 2)
        self.result = QPlainTextEdit(); self.result.setReadOnly(True); self.result.setPlaceholderText("参考值、评价标准、结果解读和文件位置将在这里显示。")
        layout.addWidget(self.result, 1)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.run_button = QPushButton("运行并生成报告"); self.run_button.setObjectName("primary"); self.run_button.clicked.connect(self.run)
        self.open_button = QPushButton("打开离线报告"); self.open_button.setEnabled(False); self.open_button.clicked.connect(self.open_report)
        self.criteria_button = QPushButton("参考值 / 评价标准"); self.criteria_button.clicked.connect(self.show_criteria)
        cancel = QPushButton("取消任务"); cancel.clicked.connect(self.worker.cancel_all)
        load = QPushButton("读取任务 JSON…"); load.clicked.connect(self.load_spec)
        save = QPushButton("保存任务 JSON…"); save.clicked.connect(self.save_spec)
        close = QPushButton("关闭"); close.clicked.connect(self.reject)
        for b in (self.run_button, self.open_button, self.criteria_button, cancel, load, save, close):
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self.workflow.currentIndexChanged.connect(self.workflow_changed); self.workflow_changed()

    def workflow_changed(self):
        key = self.workflow.currentData()
        self.hint.setText(HINTS[key]+"\n评价提示："+WORKFLOW_GUIDANCE[key])
        self.hint.setToolTip(workflow_reference_text(key))
        self.parameters.setPlainText(json.dumps(WORKFLOWS[key][1], ensure_ascii=False, indent=2))
        self.parameters.setToolTip('可附加 evaluation_targets，例如 {"psnr_db":{"min":40}}；原生单位的用户目标，不是标准规定阈值。')
        self.show_criteria()

    def show_criteria(self):
        self.result.setPlainText(workflow_reference_text(self.workflow.currentData()))

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "按顺序选择输入文件", "", "支持文件 (*.tif *.tiff *.png *.jpg *.jpeg *.arw *.nef *.raf *.dng *.cr2 *.cr3 *.mp4 *.avi *.mov *.mkv *.json);;所有文件 (*)")
        if paths:
            existing = self.files.toPlainText().strip()
            self.files.setPlainText((existing+"\n" if existing else "")+"\n".join(paths))

    def insert_path(self):
        try:
            parameters = json.loads(self.parameters.toPlainText())
            key = self.workflow.currentData()
            field = {"undistort": "calibration", "test_plan": "plan", "capture": "source"}.get(key)
            if not field:
                raise ValueError("当前任务通过左侧文件列表选择输入")
            parameters[field] = self.reference.text(); self.parameters.setPlainText(json.dumps(parameters, ensure_ascii=False, indent=2))
        except ValueError as exc:
            QMessageBox.warning(self, "参数", str(exc))

    def specification(self):
        parameters = json.loads(self.parameters.toPlainText())
        if not isinstance(parameters, dict):
            raise ValueError("测量参数应为 JSON 对象")
        return {"workflow": self.workflow.currentData(), "files": [line.strip() for line in self.files.toPlainText().splitlines() if line.strip()],
                "config": {"transfer": self.transfer.currentData()}, "parameters": parameters}

    def run(self):
        try:
            spec = self.specification()
            root = Path(self.destination.text())
            if not self.destination.text():
                raise ValueError("请选择输出根目录")
            folder = root/(spec["workflow"]+"-"+uuid.uuid4().hex[:12])
            self.job = self.worker.submit({"action": "lab", "config": self.config.to_dict(), "spec": spec, "folder": str(folder)})
            self.run_button.setEnabled(False); self.result.setPlainText("正在测量…"); self.progress.setValue(0)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "工作台", str(exc))

    def on_event(self, uid, event):
        if self.job is not None and uid != self.job:
            return
        if event["type"] == "progress":
            self.progress.setValue(event["value"])
        if event["type"] in {"done", "error", "cancelled"}:
            self.run_button.setEnabled(True); self.job = None
        if event["type"] == "done" and event.get("lab_result"):
            self.report = event["report"]; self.open_button.setEnabled(True)
            data = json.loads(Path(event["lab_result"]).read_text(encoding="utf-8"))
            evaluation = data.get("evaluation") or assess_workflow(data.get("workflow"), data["output"], data.get("specification", {}).get("parameters", {}))
            self.result.setPlainText(evaluation_text(evaluation)+"\n\n原始结果：\n"+json.dumps(data["output"], ensure_ascii=False, indent=2)+"\n\n报告："+self.report)
            self.progress.setValue(100)
        elif event["type"] == "error":
            self.result.setPlainText(event["message"])
        elif event["type"] == "cancelled":
            self.result.setPlainText("已取消")

    def open_report(self):
        if self.report:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.report))

    def load_spec(self):
        path, _ = QFileDialog.getOpenFileName(self, "读取任务", "", "JSON (*.json)")
        if path:
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
                index = self.workflow.findData(data["workflow"])
                if index < 0:
                    raise ValueError("未知任务")
                self.workflow.setCurrentIndex(index); self.files.setPlainText("\n".join(data.get("files", [])))
                self.parameters.setPlainText(json.dumps(data.get("parameters", {}), ensure_ascii=False, indent=2))
                self.transfer.setCurrentIndex(max(0, self.transfer.findData(data.get("config", {}).get("transfer", "linear"))))
            except (ValueError, KeyError) as exc:
                QMessageBox.warning(self, "任务格式", str(exc))

    def save_spec(self):
        try:
            data = self.specification()
            path, _ = QFileDialog.getSaveFileName(self, "保存可复现任务", "iq-task.json", "JSON (*.json)")
            if path:
                from ..utils import atomic_json
                atomic_json(path, data)
        except ValueError as exc:
            QMessageBox.warning(self, "任务格式", str(exc))
