# 架构与数据约定

v0.6.0：`official_charts` 提供型号/图案配置，`reference_io` 按编号绑定 CSV/CGATS；元数据存放于已有 fiducials 的 compatibility_profile 条目，图卡包格式不变。`analysis/quality.py`、`tone_color.py`、`geometry.py`、`sensor.py` 扩充统一引擎；Measurement.diagnostics 保存模型约定与污点位置等证据。`lab.py` 编排多图任务，temporal/simulation 提供时间序列/仿真，`test_manager.py` 存储独立计划历史。GUI 与 CLI 共用工作流，GUI 通过原有 spawn 工作者执行并取消。当前范围见 [对照调研](IMATEST_GAP_ANALYSIS.md)。

## 技术实现

测量与评价分开：`evaluation_catalog.py` 保存 64 项参考、适用条件、出处和显式工程建议，`evaluation.py` 只读解释有效测量及带单位的用户目标。`AnalysisConfig.evaluation_limits` 与 `evaluation_engineering` 随测量设置保存，`AnalysisResult.evaluation_summary` / `FocusResult.evaluation_summary` 保存规则快照。`analysis_plan`、主界面与 HTML/PDF 共享同一评价器，旧结果导出时动态重评；`reports_evaluation` 按实际 PDF 设备分页。`lab_evaluation` 独立覆盖工作台 13 类任务的主要输出。它们不会改动原像素、原始数值或测量有效性标志，也不会把工程建议标为标准认证。

Windows x64 / Python 3.12 / PySide6 Widgets。GUI 负责交互、图像显示和曲线；解码、测量与焦位拟合在 multiprocessing spawn 子进程中运行。批量任务串行，避免同时解码多个大 RAW。停止任务可取消 Python 循环；无法及时退出的原生解码仅终止本软件创建的子进程。

ImageSource：tifffile 检查头信息，未压缩 TIFF 使用只读 memmap；压缩 TIFF 交给 libvips 随机块读取；rawpy / LibRaw 解码 RAW。Native ROI → float64 线性化 → 分析器 → Measurement → AnalysisResult。16-bit 源像素不会先缩成 8-bit 或整图浮点数组。uint16 RAW RGB 和 CFA 缓存为只读 NPY。

显示：QGraphicsView 的缩略图、512 显示瓦片、ROI 和热力图是独立图层。TileReader 后台线程读显示区域；RAW 瓦片复用分析进程准备的缓存，避免 GUI 再次去马赛克。瓦片和缩略图从不参与测量。同步比较按归一化画幅位置关联平移与缩放，统一热力图范围，虚线代表参考曲线。

预览方向：preview_orientation 定义严格的 90° 旋转与屏幕轴镜像。ImageViewer 使用统一的相机变换，不修改场景原像素坐标；点选与锚定通过 mapToScene 反变换，瓦片等级、缩放和比较同步使用变换列向量的长度。快速恢复方向优先读取当前模板配准的局部坐标轴，缺少配准时通过 preview_orientation 子进程匹配两个缩略图；方向只保存在队列的显示状态，和 AnalysisConfig / AnalysisResult 独立。过期结果、低相关或方向歧义均不应用。

分析器：斜边 SFR、USAF CTF、二值/正弦星图、均匀块/频谱、色块、阶梯块、棋盘格几何、点扩散与纹理。分析模块不依赖窗口状态，可从 CLI 和测试直接使用。

混合图卡：chart_targets 生成完整星图与单边候选、保留手工区域和精确频率定义。auto_chart 用 SIFT + 鲁棒投影拟合匹配参考缩略图和图像预览，支持镜像、旋转和局部覆盖；原生 ROI 才进入测量。配准失败时，仅带通用检测标记的模板可独立检测本图中的星图 / 斜边，返回动态模板快照并清除物理标定。被裁区域、参考失配和非适用星图几何保留失败标志。楔形沿原像素的已知投影横截线取样，以预期暗条数、基频一致性和从低频连续通过的区间约束阈值分辨率；诊断曲线保留混叠段，不把回升当成新分辨率。

公开模板：template/manifest.json 与 definitions / originals / previews / licenses 独立于用户库，源码及便携程序从根目录加载；上游原字节、衍生版本与署名一同分发。私有导入保存在用户目录，与公开资产不混放。模板准备通过 prepare_targets 子进程运行，换源/关闭取消，完成时核对源身份，避免过期结果覆盖编辑状态。

模板管理：TemplateComboBox 在选择列表显示图像，TemplatePreview 展示当前模板及图案 / 标定信息。TemplateManager 通过 template_library 完成用户副本、改名、归档和重复导入检查；公开目录保持只读。chart_package 生成 ZIP level 1 的 .mxtpl，Scrypt + AES-256-GCM 加密 ROI 与重新编码的栅格参考，不封装源 SVG/PDF。导入完整认证后才写栅格缓存；JSON 工作定义和旧 .mchart 读取仍保留兼容。

分析状态：提交时保存项目与模板编号快照，MetricChecklist 只显示当前图片及匹配模板的任务。活动角色独立于复选状态和已有结果；80 ms QTimer 绘制旋转指示与共用测量进度，不为每个指标另建分析进程。排队 / 取消 / 错误 / 完成分别处理，频繁进度事件不会重置动画时钟。

报告：ExportDialog 收集选项不产生文件，export_plan 校验 Windows 文件名并分配唯一子文件夹；reports 共用原结果、所选汇总及完整曲线渲染 HTML / PDF，可选数据与 PNG 附件。失败只回收本次新分配文件夹。界面的选项不会更改源图与分析记录。analysis_catalog 统一定义名称、介绍、通道依赖和序列边界，MetricChecklist 将介绍与当前可用性原因组合为悬停说明。

整卡 USAF：vector_usaf 从矢量条纹几何展开全频率，渲染仅用于检查模板墨迹遮挡和保存无遮挡取样带。usaf_multifrequency 每单元读取原像素，RGB ECC 平移配准，对五通道 / 两方向逐频率测量。元素 Measurement 和每单元方向 / 合并 Measurement 一起保留；optical_summary 保存完整曲线、位移、阈值定义、最高当前清晰度位置与覆盖统计。resolution.view_result 选择适用的视图，不替换原始数据。RGB 原通道不做几何插值，对齐灰度单独标注派生重采样。

热力图：heatmap 保留测点中心之间的线性网格；通过局部有效三角形 / 短连边与其 ROI 角点的包络，将显示范围扩展至真实测试区域外缘，不用全局 ROI 凸包跨越大空洞。网格外侧延续最近网格边界的值；单点 / 共线点也可显示。关闭插值时只在各 ROI 内填色。同位置重叠测点只在显示场中取均值，原值和测点编号保留。heatmap_coverage 从模板及保存的局部配准恢复 USAF 汇总 / RGB / 焦位单元范围，兼容历史 4 px 占位框；投影信息缺失时退回原像素元素边界。预览、比较、PNG / HTML / PDF 共用 heatmap_rgba，边界扩展不进入光学测量或灰度对齐算法。

焦位：同模板、同解码、同分辨率、同测量参数下按 ROI / channel 分组。重复焦位先取中位数，局部五点二次拟合；只接受包围、凹峰、变化充分且拟合稳定的样本。场面使用置信度加权的 z=c0+cx*x+cy*y+cr*(x²+y²)，重新降低异常点权重。标定图卡尺寸和 mm/um 焦位才计算表观倾斜角。默认综合目标最大化归一化 ROI 分数的第 20 百分位。

存储：版本化 JSON 图卡/结果、SQLite 会话索引、重建式文件缓存。结果记录 SHA-256、图卡完整快照、算法版本、参数、解码器、线性化方式、配准矩阵、质量标志和物理尺度。相同图像/模板/设置的会话结果更新，不同测量设置保留独立记录。打开结果时检查原文件指纹，不用变化后的图像冒充旧测量预览。

## 目录

- src/mutex_imatest/imaging.py：源图像与显示/ROI 读取
- analysis/sfr.py：独立斜边实现
- analysis/targets.py：USAF 与星图
- vector_usaf.py / analysis/usaf_multifrequency.py：全频率模板预检、原像素 CTF 与分辨率边界
- analysis/rgb_registration.py：G 参考的二维通道平移、独立对齐灰度
- resolution.py / gray_export.py / reports_usaf.py：单位 / 方向视图、分条带灰度 TIFF、整卡 HTML/PDF 与曲线 CSV
- analysis/extra.py：额外光学/成像统计
- analysis/engine.py：统一执行、RGB 法向位移、单位和质量标志
- detection.py：自动斜边候选、ORB / 四点配准、局部物理尺度
- templates.py：用户模板、SVG/PDF 缩略图、二进制图卡包读取
- chart_package.py / template_library.py：口令加密的栅格模板包、用户模板副本 / 改名 / 归档 / 去重
- ui/template_widgets.py / ui/template_manager.py：模板缩略图选择、管理和加密导入 / 导出窗口
- analysis_catalog.py / analysis_plan.py：分析项目目录、RGB 依赖与单次测量的所选结果汇总；选择快照保存在 AnalysisResult.analysis_summary
- ui/metric_checklist.py：独立的勾选计划与当前查看项目，重启恢复勾选；序列结果保留独立入口
- reports_selected.py：全部所选项目的离线 HTML / PDF、汇总 CSV / JSON 和各通道统一色标 PNG
- chart_library.py：同源同尺寸模板合并、完整备份与旧模板编号别名；保留手工 ROI 与结果内原始快照
- capabilities.py / ui/availability.py：图案与测量前提决定选项可用性，显式区分可用 / 灰色禁用样式，失败测量保留质量标志
- focus.py / heatmap.py / heatmap_coverage.py：焦位序列、测试区域包络与边界延续的显示插值
- workers.py / watcher.py：隔离任务、显示线程、稳定文件监视
- ui/：Qt 界面与模板编辑
- storage.py / reports.py / cli.py：会话、报告与批处理
- private_tools/：私有资产打包器，不在 Git 或便携版/源码分发中
- samples/private/：开发时下载的 CC0 RAW 验证样本，不包含在分发中

## 内存与失败行为

自动 RAW 预算为物理 RAM 的 40%，最多 8 GiB；可手工修改。解包前按原始尺寸估算约 32 B/像素；它是保守预算，不是系统级硬限制。每个 ROI 再按通道和算法临时缓冲估算，太大时明确拒绝。libvips 内存缓存 64 MiB，GUI 瓦片默认 256 MiB。RAW 缓存上限默认 32 GiB；只清理带 MUTEX_CACHE 标记、以 SHA-256 命名的本软件目录。作业报告缓存另在 jobs 目录，作为待保存结果保留。

默认设置不能保证任意解码器、任何异常 TIFF 都绝不超过预算。实际测试的格式、像素数量和峰值见 VALIDATION.md。超高像素 RAW 可先用外部软件输出无锐化、无降噪、已知传递曲线的 16-bit TIFF，再分块分析。

## 边界

原生坐标：不根据 EXIF Orientation 旋转测量数据；读取时提示，避免隐式插值。配准只改变 ROI 定位与局部物理尺度，在原像素上测量，不先拉正整图。强透视导致边缘/星图几何不适合时，需改善拍摄姿态或手工调整 ROI。

斜边 RGB 色散是同一斜边法向的 R−G、B−G 位移投影；不是单一斜边就能确定的二维色散矢量。整卡模块使用含两方向的低频图案拟合二维平移，仍含靶材、扫描与相机处理影响。原始相机 RGB 没有相机色彩标定，禁止据此输出 ΔE。二值星图/USAF 是 CTF，不自动换算为 MTF。

整卡 R−G / B−G 固定通道对视图直接从逐单元 RGB 配准记录生成，其有效性独立于 CTF 分辨率判读；使用相同 Measurement / heatmap 接口而不改写原始结果。混合模板额外的非 USAF 区域继续交给对应分析器，使用最近 USAF 单元的局部配准并标记 nearby_unit_registration；最近单元定位失败时不借用远处单元冒充有效结果。

该版本没有硬件控制、商业 Imatest 代码、ISO/FADGI 认证、Moiré 自动消除、自动机械矫正、三维非球面诊断或已认证的动态范围报告。


监视导入在工作进程中复制稳定源文件为采集快照，检查复制前后签名；支持同名输出反复覆盖。结果保存 original_path 与快照 SHA-256。旧事件在排队期间若文件已更新会拒绝，避免把新采集误当成旧帧。
物理倾角除图卡尺寸、mm/um 单位外，还要求 height_calibrated 声明该参数为图卡/载台实测轴向位移。
