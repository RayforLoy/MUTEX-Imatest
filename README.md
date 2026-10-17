# MUTEX Imatest

测量评价：64 项图卡测量及 13 类工作台任务均提供参考值、评价标准与结果解释。当前画面的彩色标签和「评价与参考」页可查看依据；「图像质量 → 评价参考与自定义目标」设置带单位的上下限。HTML/PDF 同步提供覆盖率、中位数、最差值和限制；数据附件含逐点评价与规则版本。工程建议、定义参考和用户目标分别标注。详见 [测量评价指南](docs/MEASUREMENT_EVALUATION.md) 与 [工作台评价](docs/WORKFLOW_EVALUATION.md)。

离线 Windows 扫描仪 / 翻拍调焦与图像质量工具，v0.7.1。从 [GitHub Releases](https://github.com/RayforLoy/MUTEX-Imatest/releases) 下载 Windows x64 ZIP，完整解压后运行文件夹内的 **MUTEX Imatest.exe**；开发目录也可双击 **启动 MUTEX Imatest.cmd**。不需要联网、账号或上传 RAW/TIFF。第一次点击「合成示例」可走通 9 个焦位的流程。

v0.7.1 精简发布包：删除未使用的 Qt QML/Quick、虚拟键盘和软件 OpenGL 渲染器，文档、许可证与公开模板各保留一份，使用高压缩率 ZIP。绘图库需要的 QtOpenGL 绑定保留。RAW/TIFF、视频、色彩、PDF/SVG、加密模板和全部测量功能继续提供。源码仓库不包含私有图卡、用户照片、分析结果或解码缓存。开发和发布步骤见 [构建指南](docs/BUILDING.md)。

完整 Release 同时提供全部 9 套现有模板：合成验证卡、6 套公开图卡，以及「调焦卡 x1」和「西门子星图 + ISO12233 0.5×」。后两套以 `.mxasset` 测量定义和栅格参考随安装包、模板 ZIP 与完整源码 ZIP 分发，保留私有图卡版权，不包含原 SVG/PDF。空白用户配置也能直接选择。35 项官方兼容配置另在「图像质量」菜单提供；兼容配置不代表随附了其商业图卡原稿。

v0.6.0 增加「图像质量」菜单：35 项官方 / 标准图卡兼容配置、CSV/CGATS 参考、OECF/实测动态范围、CCM、径向畸变与点阵二维色差、坏点/污点和二维噪声谱、参考纹理与对数频率响应。工作台提供 PTC/暗平场、多视图镜头标定、视频 AE/AWB/AF/运动、采集、SSIM/PSNR、仿真、锐度排名、测试计划与 SQLite 判定历史。8 份官方公开示例已跑通。复杂图卡需真实布局和随卡参考；尚未全面等价于商业 Imatest。见 [工作台指南](docs/IQ_WORKBENCH.md) 和 [完整差距调研](docs/IMATEST_GAP_ANALYSIS.md)。

v0.5.1 将所有热力图扩展到有效测试区域的外缘：测点之间仍线性插值，外缘延续最近网格边界的显示值；测试区域外及明显大空洞透明。单区域、单行 / 单列也能填色。整卡汇总、RGB 位移和最佳焦位使用真实单元范围，兼容已有分析记录；预览、比较和 PNG / HTML / PDF 使用相同规则。关闭插值时仅在各测试区域内填色。原始测量数值保持不变。

v0.5.0 增加「图卡模板」菜单和工具栏入口：预览、管理、导入、新建、复制、改名、归档及加密导出。选择列表和当前模板均显示缩略图。导出的 `.mxtpl` 使用快速 ZIP 压缩，口令经 Scrypt 派生密钥，AES-256-GCM 加密测量定义及栅格参考；包内不含 SVG/PDF 原始矢量文件，导入时输入口令。新增可打印的 CC0 棋盘格模板。左侧勾选项目在分析时显示进度动画，右下角明确标注「预览缩放」。

v0.4.0 增加报告导出选项：HTML / PDF / 两者、文件名、显示标题、保存目录与数据 / 图像 / 详细曲线附件；每次导出放在独立文件夹，重名自动编号。左侧全部分析项目提供鼠标悬停说明及不可用原因。新增整卡 / 局部参考配准、混合星图 / 斜边 / 楔形模板、星图八方向 CTF、楔形连续频率 CTF 与条纹分离检查、斜边奈奎斯特响应及过冲 / 下冲。通用模板可独立寻找星图和斜边，未知实物尺度保持未标定。

根目录 [template](template/README.md) 提供 6 套可再分发图卡：4 套原创 CC0 的星图 + 斜边、斜边网格、ISO12233 风格兼容图及棋盘格，以及联网核验许可的 Siemens 星和 USAF1951（CC BY-SA 3.0）。SVG / PDF、ROI 定义、缩略图、许可证、作者与源地址、校验清单均随软件分发。ISO12233 风格模板是原创工程图卡，没有复制官方标准插图或声明标准认证。用户私有源图卡继续只保存在本机。详见 [混合图卡与局部拍摄](docs/MIXED_TARGETS.md)。

v0.3.1 增加预览方向工具：上下 / 左右镜像、顺 / 逆时针 90° 旋转、恢复原始方向，以及按模板快速恢复方向。新导入图像默认 0°、不镜像；底图、瓦片、热力图和测点同步变换，100% 显示及点击保持正确。快速对齐优先使用已有配准，否则仅匹配缓存预览与模板缩略图，不触发全图分析。方向操作不改写源文件或测量结果。

v0.3.0 将分析下拉菜单改为左侧勾选列表：勾选多个项目，点击一次“分析选中图像”，复用同一次原像素测量生成全部所选结果；“所选分析结果”页按项目 / 通道集中显示有效数量、均值、最大值和失败原因。点击左侧项目或汇总行可切换热力图与明细，不重新分析。支持全选可用、清空、自动补齐 RGB / RGBY 通道和重启恢复勾选。焦位地图与焦位差属于序列结果，通过上方“焦位 / 垫高序列”运行后查看。

已实现：48-bit TIFF 和 RAW 原精度 ROI；斜边 ESF/LSF/SFR、MTF50/50P/20/10；USAF / 西门子星 CTF；RGB 位移投影；分辨率与最佳焦位热力图；焦位/垫高拟合及表观倾斜、场曲；同步双图比较；SVG/PDF 模板与四点配准；均匀/噪声、色块、灰阶、棋盘格、点像与纹理；稳定文件监视；会话、CLI 和 CSV/JSON/PNG/HTML/PDF 报告。

简易 / 专业模式共用测量引擎。未知曲线、剪切、低对比度、ROI 越界、混叠风险和峰值未包围均显示质量提示。热力图在区域之间插值，外缘延伸至有效测试区域边界，区域外透明。

新增整卡全频率 USAF 双向分析、CTF 曲线与已确认分辨率热力图。选择 SVG 模板后点「整卡多频率 / RGB」，即分析 R/G/B、对齐前灰度 Y 和对齐后灰度 Y_align；支持 cy/px、lp/mm、等效分辨 DPI、LW/PH、LP/PH，另报几何采样 PPI、二维通道位移、方向差异与对齐后变化。报告保留全部元素原始测量。详见 [整卡使用说明](docs/WHOLE_CARD.md)。

自动检查覆盖分析真值、局部 / 镜像配准、模板库、预览方向、导出选项和界面；最新数量见 [验证记录](docs/VALIDATION.md)。7 个公开 CC0 RAW 文件已完成冷解码、uint16/CFA 保留验收，覆盖 A7R IV、Z8 无损 NEF、GFX100 16-bit lossless RAF、Canon 5D IV CR2 / R5 CR3 与 C-RAW。约 834 MB TIFF 与解压约 834 MB Deflate TIFF 已完成基准。

SVG 导入兼容 CorelDRAW 的标准 SVG 1.1 声明，保留脚本与外部资源限制。模板编辑器的「从 SVG 识别 USAF」可从矩形/多边形条纹生成测量区域；主界面「USAF 矢量配准」支持镜像和裁切的重复图卡，并在原像素中逐单元拟合。USAF 双向/竖线/横线选择同时作用于热力图与报告导出。

v0.2.1 修复了 R−G / B−G 位移选项：整卡模板显示二维位移幅值，自动选择 R / B；斜边模板显示法向有符号投影。下拉菜单以深青色标出可用分析，灰底灰字并附“不可用”标出缺少图案或前提的分析，悬停显示原因。同源、同页和相同物理尺寸的单频 / 双向 / 整卡模板自动合并为一个，保留手工 ROI、标定和旧编号，并先在图卡库 backups 目录备份。

单频 USAF 模板会自动使用固定频率对比度，不适用的 MTF50 和星图 CTF50 会禁用；多频率模板可用 CTF50/20/10。简易模式提供严格剪切排除和相对调焦选择，并列出实际参与热力图、剪切排除与定位失败的测点数。相对调焦保留剪切数值及警告，输入曲线保持用户设置；模板、指标和剪切策略在重启后恢复。

本地用户 SVG 与 8-bit RGB 大幅面扫描样本已完成矢量配准和原像素 USAF 流程检查，私有样本不随软件分发；V850 实际 48-bit 输出和焦位序列仍待验收。Z8 HE/HE★ 本版不支持。本版为工程分析，没有 ISO/FADGI 标准认证声明。

- [使用指南](docs/USER_GUIDE.md)
- [软件架构](docs/ARCHITECTURE.md)
- [功能实现、调研和后续范围](docs/FEATURES_AND_RESEARCH.md)
- [CLI 与构建](docs/CLI.md)
- [图卡资产边界](docs/ASSET_PACKS.md)
- [验证记录](docs/VALIDATION.md)

## 开发与复现

Python 3.12 x64：

    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements-lock.txt
    .venv\Scripts\python.exe -m pip install -e ".[dev,color]"
    .venv\Scripts\python.exe scripts\upgrade_libraw.py
    .venv\Scripts\python.exe -m pytest
    .venv\Scripts\python.exe -m mutex_imatest gui --demo

官方 LibRaw 0.22.2 DLL 的替换过程和哈希在 validation/libraw-upgrade.json；重装 rawpy 会还原 wheel 自带版本，需要重新升级并验收。依赖锁在 requirements-lock.txt。

    .venv\Scripts\python.exe -m mutex_imatest selftest --out validation/selftest
    .venv\Scripts\python.exe scripts/licenses.py
    .venv\Scripts\python.exe -m PyInstaller --noconfirm MUTEX.spec

便携目录内保留两个 EXE、_internal 和许可证文件，不要只复制单个 EXE。MUTEX-CLI.exe 提供 info、analyze、focus、report、gray-export、watch、temporal、demo、selftest。build 下为中间产物，请运行 dist 下的完整目录。

## 许可和名称

代码 GPL-3.0-or-later，依赖通知在 licenses/；合成示例与图标 CC0。私有源图卡、资产和独立旧打包器许可单独管理，private_tools / private_assets 不进入公开源码或便携分发。新界面导出使用口令加密的 `.mxtpl`，仅分享测量定义、缩略图和栅格参考，不含原 SVG/PDF。旧 `.mchart` 仍可读取，属于未加密兼容格式。详见 [图卡资产边界](docs/ASSET_PACKS.md)。

“Imatest” 是现有商业产品名称。本项目为独立实现，与 Imatest LLC 无隶属或授权关系；当前按用户指定名称开发，正式公开发布前建议另定产品名。
