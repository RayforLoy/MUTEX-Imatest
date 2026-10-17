# 功能、开源来源与后续范围

**v0.6.0 更新**：下面保留 v0.5.0 历史验收。OECF/图卡动态范围、CCM、畸变/内参标定、PTC、暗平场、坏点/污点、视频、采集、测试计划和官方图卡入口已新增。当前状态以 [逐项调研](IMATEST_GAP_ANALYSIS.md) 和 [工作台指南](IQ_WORKBENCH.md) 为准，不再将下表对应项目理解为全部未实现。

v0.5.1 是可运行的本地测量版本。下表按实际实现区分，不把路线图当成现有功能。

| 功能 | 本版状态 | 限制 |
|---|---|---|
| RGB 16-bit TIFF，未压缩 / Deflate / LZW、planar separate | 已实现并测试 | V850 实际软件输出样本仍待验收 |
| ARW / NEF / RAF / CR2 / CR3 | LibRaw 0.22.2，7 个公开 RAW 样本已解码验收 | 不代表同机全部压缩、固件和像素合并模式 |
| 原精度 ROI、缩略图、缩放瓦片 | 已实现 | 原生 Orientation 坐标 |
| 斜边 ESF/LSF/SFR，MTF50/50P/20/10、Nyquist、锐化过冲 | 已实现；Gaussian 真值测试 | 工程实现，无标准认证 |
| USAF 全频率、双向 CTF 曲线、已确认分辨率 / CTF50/20/10 | 已实现；镜像 / 模板文字遮挡真值测试 | 从 SVG 几何推导编号；不做印刷文字 OCR，未知曲线为输入响应 |
| 二值 / 正弦西门子星圆环、八方向曲线、CTF50/20/10、阈值分辨率与方向比 | 已实现；连续基频检查和周期失配反例测试 | 完整可见圆环；二值 CTF 不冒充 MTF；正弦 MTF 需参考调制度 |
| 已知几何楔形连续频率 CTF、分离异常比例、条数 / 基频诊断 | 已实现；连续可信段之外不确认分辨率 | 需要正确频率参数；参考 PDF 栅格估计附近似提示，未知楔形不自动推断标准刻度 |
| RGB 边缘法向位移、物方 lp/mm、LW/PH | 已实现 | 一条边是投影位移，不是完整二维 CA |
| 整卡二维 RGB 位移、五通道分辨率、对齐前 / 后灰度 | 已实现并测试；含原尺寸 16-bit 派生 TIFF 与有效掩码 | G 参考局部平移；灰度插值影响高频，未作色度亮度校准 |
| 五通道最佳焦位、R−G / B−G 轴向焦差 | 已实现；已知焦位差测试 | 至少 5 个包围峰值的焦位；单帧不输出最佳焦位 |
| 分辨率与最佳焦位热力图 | 已实现 | 区域间插值，外缘延续至有效测试区域边界，区域外及大空洞透明 |
| 焦位/垫高序列、ROI 峰值、平面/径向场曲、综合推荐 | 已实现并测试 | 高度与图卡尺寸标定才产生物理角度 |
| 同步双图比较、同尺度热力图、参考曲线 | 已实现 | 要用对应模板；透视/移动需先配准 |
| SVG/PDF 用户模板、ROI 编辑、四点 / ORB 配准 | 已实现并测试 | 自动斜边只给候选，重复图案可能错配 |
| 整卡 / 局部参考配准、旋转与镜像、通用星图 / 斜边独立检测 | 已实现；已知裁切和镜像真值、真实手机局部照片回归 | 完整 ROI 才测量；不能确定原卡位置时禁用原卡物理尺度 |
| 6 套公开 SVG/PDF 图卡、定义及许可证 | 已实现并随软件分发 | 含棋盘格；CC0 / CC BY-SA 3.0 分别保留；原创 ISO12233 风格工程图无标准认证 |
| 模板缩略图、管理和加密导入 / 导出 | 已实现 | .mxtpl 使用快速 ZIP 和口令加密，分享栅格参考 / ROI，不含源 SVG/PDF |
| 左侧分析进度动画、预览缩放说明 | 已实现 | 动画按提交时的勾选快照显示本图共用测量进度，支持排队 / 取消 / 失败 |
| 私有内置图卡二进制包读取 | 已实现；私有打包工具单独保留 | 二进制不保证原文件无法提取；真实私有图卡不进入公开分发 |
| 均匀块、单帧空间 SNR、扫描方向带纹、1D NPS | 已实现 | 图卡、照明与传感器混合贡献 |
| 重复帧时间噪声、固定图案与 PRNU 近似 | CLI 已实现并测试 | 需匹配受控暗/平场；未完成完整 PTC/电子增益标定 |
| D65/sRGB 色块 ΔE2000 | 已实现 | RAW 相机 RGB 明确拒绝；完整色彩矩阵标定尚未实现 |
| 灰阶块、已标定 OECF 导入 | 已实现 | 自动完整 OECF、动态范围报告仍待实现 |
| 棋盘格 projective residual | 已实现 | 内置可打印 CC0 棋盘格，63 内角点；含图卡误差，完整 k1/k2 标定与镜头畸变报告仍待实现 |
| 点像质心、二阶宽度、包围能量 | 已实现 | 有限点源影响结果；点源/靶材需足够小 |
| 纹理频谱、高频能量 | 已实现 | 不把纹理/噪声频谱叫光学 MTF |
| 会话、指纹、CSV/JSON/PNG/PDF、CLI、稳定文件监视 | 已实现并测试 | 不含硬件采集控制 |
| 报告格式 / 文件名 / 标题 / 附件选项，全部所选项目和原生曲线 | 已实现；离线 HTML 和可打印 PDF | 每次导出独立文件夹；仅附当前实际测得曲线与原因 |
| 左侧多选、悬停介绍与明显的禁用状态；预览镜像和 90° 旋转 | 已实现并测试 | 默认原始方向；显示变换不改源图及测量坐标 |
| MTF Mapper 独立复核入口 | 已实现启动适配器 | 本机未安装其可执行文件；尚无数值对齐/结果解析验收 |
| 简易 / 专业模式、Windows 便携版本 | 已实现 | 需按最终便携包验证结果记录 |
| 光谱/眩光、完整 FADGI/ISO 合规、PRNU/DSNU/PTC 全协议 | 后续范围 | 需要专用参考靶、照明与完整校准流程 |

## 市场与开源调研

本次混合图卡扩展参考 [ISO12233 图卡差异](https://www.imatest.com/imaging/iso-12233/)、[星图模块](https://docs.imatest.com/25.2/starchart) 和 [斜边 / 星图对输入处理的敏感性](https://www.imatest.com/imaging/slanted-edge-versus-siemens-star/)，实现星图方向响应、楔形分离与混叠诊断，以及斜边奈奎斯特响应、过冲 / 下冲和拟合残差。已有黑白旧版高对比图卡没有实测灰阶 / 色彩 / 照度参考，因此没有把商业软件依赖额外图案的色差、完整噪声或信息容量指标伪装成这张图可直接测得的结果。详细前提见 [混合图卡说明](MIXED_TARGETS.md)。

- [Imatest 成像质量因素](https://www.imatest.com/imaging/iqfactors/)：参考其锐度、色彩、噪声、动态范围、几何与不均匀性分类。未包含任何商业 Imatest 的代码、商标素材、认证声明或商业测试靶源文件。
- [iQ-Analyzer-X 官方手册](https://wiki.image-engineering.de/doku.php?id=en:iq-analyzerx:product_manual)：参考其模块化图卡、可配置工作流和结果报告。
- [Quick MTF 官方介绍](https://www.quickmtf.com/overview.html)：参考聚焦斜边、RGB 响应与清晰度的简易工作流。
- [MTF Mapper 官方项目](https://sourceforge.net/projects/mtfmapper/) / [作者博客](https://mtfmapper.blogspot.com/)：独立斜边和 CA 测试参考，提供可执行文件入口。BSD 项目不自动等于已对齐测量；需相同原始解码、边缘/窗函数设置和验证数据。
- [OpenDICE / FADGI 官方](https://www.digitizationguidelines.gov/guidelines/digitize-OpenDice.html)：参考数字化的 SFR、OECF、色彩、噪声报告分类和参考文件要求。尚未包含其协议实现或认证。
- [ImageJ MTF 插件](https://imagej.net/ij/plugins/mtf.html) / [许可](https://imagej.net/licensing/)：可用 CSV、原始 ROI 与报告进行独立比较；没有复制未知许可证插件代码。
- [LibRaw 支持相机](https://www.libraw.org/supported-cameras) / [0.22.2 下载及修订](https://www.libraw.org/download)：真实 RAW 解码基础。Nikon Z8 标准压缩支持不意味着 HE/HE★ 支持。
- [rawpy](https://github.com/letmaik/rawpy) / [Params](https://letmaik.github.io/rawpy/api/rawpy.Params.html)：Python 接口，明确关闭自动增亮、机内白平衡、额外降噪与色差调整，输出 camera RGB / 16-bit。
- [tifffile](https://github.com/cgohlke/tifffile) / [libvips 大图读取](https://www.libvips.org/API/current/how-it-opens-files.html)：保留 TIFF 精度、映射/分块读取与显示性能。
- [Colour Science](https://www.colour-science.org/)：有适当输入空间和参考值的 ΔE2000。
- [OpenCV 几何文档](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html)：特征、单应矩阵和棋盘格。
- [ISO 12233:2024 官方条目](https://www.iso.org/standard/88626.html)：标准名称/现行版参考；本版独立 SFR 算法并非完整标准符合性声明。
- [Qt 许可](https://doc.qt.io/qt-6/licensing.html)：PySide6 动态库及相关许可证随包提供，软件自身 GPL-3.0-or-later。
- [prysm](https://prysm.readthedocs.io/en/stable/)：后续衍射、PSF、瞳面与理论模型候选，未假称已集成。
- sfrmat5：未能在本轮确认完整授权和可获得源码；目前仅作算法验证候选，未复制其实现。

## 分期

P0 的核心本地闭环已经实现。下一轮以用户实际图卡和 RAW/48-bit V850 样本完成布局识别、有效 ROI 门控与真实焦位重复性验收，再决定默认参数。

P1：USAF 印刷编号 OCR、正弦星图参考与几何中心自动修正、完整几何/色彩/暗平场/OECF/PTC 校准、MTF Mapper 数值对齐，以及更严格的报告规范。SVG 几何推导全频率与整组判读已在 v0.2.0 实现。

P2：专用 PSF/眩光、衍射/理论模型、完整 FADGI/ISO 流程、设备采集适配、实时视频预览等。标准与认证必须有完整图卡、参考值、照明和程序依据。

