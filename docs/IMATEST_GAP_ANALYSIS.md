# Imatest 功能差距与 v0.7.0 实现记录

调研日期：2026-10-17（香港）。对照基准为 [Imatest 当前 26.1 文档](https://docs.imatest.com/docs)。官网产品页仍有 25.2 信息，因此按实际模块比较。“已实现”表示本项目有可执行路径及验证，**不表示算法、数值、自动化程度或标准认证等价**。

## 本次新增

| 商业模块 / 能力 | 原有缺口 | 本次实现 | 适用范围 / 限制 |
|---|---|---|---|
| SFR / 信息量 | 仅常用 SFR 指标 | MTF 面积、边缘两侧 NPS、一维 Shannon 积分 | 均匀输入工程模型；非 Imatest C4/Cmax/NEQ/SNRi |
| SFRplus / eSFR ISO / SFRreg | 无官方型号入口 | 型号配置、自动验证斜边候选、原像素测量 | 色块/灰阶/楔形/几何依赖真实布局和参考；非完整专用定位器 |
| Color/Tone / OECF | 仅逐块统计 | 编码 OECF、Gamma、单调性、场景 SNR、导出线性化表 | 至少四级有效参考；不猜未知输入曲线 |
| 图卡动态范围 | 未实现 | 透射图卡 SNR 1/2/10/20 的连续实测曝光范围，单位 stops | 未跨阈值为下界；最高未剪切参考不等于传感器饱和；反射图卡不报传感器 DR |
| 参考文件 | 手工 JSON | CSV、单列密度、三列 Lab、CGATS Lab/XYZ/密度；编号匹配、SHA-256 | D50/D65；不从未知光谱或未知 RGB 猜参考 |
| 色彩 / 白平衡 | 仅 D65 ΔE2000 | D50/D65、Bradford、ΔE76/2000、ΔL/ΔC、中性块白平衡误差 | 已知 sRGB 输入或适用 CCM；参考需匹配实物 |
| CCM | 未实现 | 加权 3×3/带偏置拟合、Lab 优化、导出/应用/清除 | 拟合块误差不是独立验证，换光源和解码后需重标定 |
| Flatfield | 仅块统计 | 网格照度、四角比例/EV、RGB 不均匀性、二维径向 NPS | 含照明/靶材贡献；未知曲线不输出 EV |
| 坏点 / 污点 | 未实现 | 亮/暗坏点候选、宽尺度连通污点、位置/面积诊断 | 单帧不能确认永久坏点，需多帧复核 |
| 暗平场校正 | 未实现 | 多暗/平场估计 offset/gain、有效掩码、浮点校正 TIFF | 固定温度、增益、曝光和像素坐标 |
| PTC / PRNU / DSNU | 仅简单时间噪声 | 成对差分 PTC、DN/e、e/DN、读出噪声、DSNU、PRNU、满阱/DR 估计 | 线性未处理单通道；RAW 显式选择 CFA 周期位置；满阱依赖声明的饱和 DN |
| Checkerboard / Distortion | 仅投影残差 | 投影平面 + r²/r⁴ 径向模型和残差 | 固定中心假设；仅覆盖内；系数不能混用于其他模型 |
| 镜头内参 | 未实现 | 至少五姿态的 Brown-Conrady 标定、FOV、逐视图误差、去畸变 | 拒绝姿态不足；实测格距，限相同光学/分辨率条件 |
| Dot Pattern / 二维 CA | 未实现 | 点阵检测、畸变、逐 RGB 质心位移 RMS | 实际行列与完整点阵；非 CPIQ 等效指标 |
| Log Frequency / F-Contrast | 未实现 | 分对比度带的正弦回归、MTF/基频 CTF | 需各带 ROI、原像素起止频率、方向和调制度 |
| Dead Leaves / Spilled Coins | 只有 PSD | 同尺度参考 PSD 幅值比、50%/10% 频率、可选噪声扣除 | 非 cross-method 或 ISO texture MTF |
| 色彩摩尔纹 | 未实现 | 中性图案高频色度 RMS | 工程比较，非 CPIQ 色混叠标准指标 |
| Veiling glare | 未实现 | 真实暗陷阱、亮区、黑电平的比值 | 非 ISO18844/9358、IEEE2020 完整方法 |
| 同心圆 | 未实现 | 径向边界、像素半径；匹配角度参考时测角直径 | 声明中心，角度/边界数量不匹配则拒绝 |
| 视频 AE/AWB/AF | 未实现 | 有界抽帧、亮度/通道比例、稳定时间/过冲、焦点评分、有效边缘 MTF50 | 需中性灰 ROI 和真实阶跃时间；8-bit 解码 |
| 防抖 / 闪烁 | 未实现 | 相邻帧平移置信度、运动 RMS、亮度波动 | 非 ISO 防抖级数、rolling shutter/频闪协议 |
| 直接采集 | 只有文件监视 | DirectShow 摄像头/视频有界采帧、时间记录 | 摄像头显式指定 camera_index；未完成实机验收 |
| 相机 / ISP 仿真 | 只有调焦示例 | 高斯光学、PRNU、光子/读出噪声、WB/CCM、锐化/Gamma/量化，固定种子 | 非完整 Simatest，无 CFA/去马赛克/光谱/瞳面衍射 |
| SSIM / PSNR | 无数值比较 | 同尺寸已对齐图像比较，逐通道和平均 | 不隐式配准/缩放；完全相同用 identical=true、PSNR=null 表示无限大 |
| 找最清晰文件 | 仅焦位拟合 | 批量有效 MTF50 排名，保留相对焦点评分 | 无有效斜边的图排到末尾，不能当 MTF |
| Test Manager / Pass-Fail | 只有会话 | JSON 计划、区域/通道/置信度/数量门控、上下限、SQLite 历史 | 缺失和失败不判通过；无商业 Operator Console 工站协议 |
| 评价与参考 | 未统一解释测量结果 | 64 项测量和 13 类任务的条件、参考、工程建议及带单位的用户目标；逐点评价与覆盖率 | 工程建议不冒充行业合格线；失败区域保留在覆盖率分母；下界和未知曲线保留限制 |
| GUI / 报告 | 以调焦为主 | “图像质量”菜单、13 类工作台任务、新指标/曲线、JSON/CSV/离线 HTML | 高级参数可保存 JSON；单帧报告继续走原 PDF 流程 |

## 官方图卡兼容

`official_charts.PROFILES` 提供 35 项配置，CLI `charts` 可列出：

- 自动斜边候选：SFRplus、两代 eSFR ISO、ISO12233:2000、SFRreg。自动检测使用预览，测量读取原像素；候选需检查。
- 自动完整二值星图及实际线对数；正弦星图需参考调制度。
- 规则块：ColorChecker24/SG140、SFRplus SQ20 彩色/灰阶、线性灰阶、通用 m×n。用户框定矩形并提供参考。
- 指定结构：棋盘格、点阵、平场、纹理、点源、同心圆。
- 真实布局导入：ColorGray-44、DR36/HDR36、DR36+Color、OECF20、ISO14524/15739/21550、IT8、ChromaDuMonde、正弦星、USAF、Log F-Contrast、眩光、自定义混合图。

配置不含商业图卡源文件或猜测色值。不规则型号“可导入布局”不等于已实现全自动定位。本项目 JSON 为自己的 ROI 格式，不宣称读取商业 Imatest `.ini` 或其专用任意图卡格式。参考 [官方 Color/Tone](https://docs.imatest.com/docs/color-tone)、[官方参考文件格式](https://imatest.atlassian.net/wiki/spaces/KB/pages/11416044328/Color%2Bdensity%2Breference%2Bfiles%2Bin%2BCSV%2Bor%2BCGATS%2Bformat)。

## 尚未补齐的商业全套能力

本次没有完成商业软件所有功能，以下项目保留为明确差距：

1. 获授权的商业 Imatest 同输入、ROI、输入曲线和设置下逐模块数值验收；完整测量不确定度预算。
2. GenICam/GigE、厂商评估板、专用采集卡、光源/照度计/机械台 SDK 与实机闭环。
3. ISO12233/15739/18844/9358、IEEE2020、CPIQ、EMVA1288、FADGI 的全套标准协议与认证。
4. InfoDR、C4/Cmax、NEQ、SNRi、CDP、CPIQ acutance/SQF、cross-method texture MTF、CCE 的数值等效实现。
5. Gamutvision/ICC 色域、打印机/专业显示器测量、ISO 灵敏度全协议、高速运动、rolling shutter、延迟和 LED flicker 全协议。
6. 完整 Simatest、所有官方图卡版式的专用全自动定位/预畸变支持、USAF 编号 OCR。

这些项目没有用近似结果冒充实现。本文是当前功能状态，不能据此声明完全替代商业 Imatest。

## 验证与来源

- 真值和反例：`tests/test_iq_quality.py`；端到端导出、视频、GUI：`tests/test_iq_workflows.py`。
- 合并版验证记录：`validation/iq-v0.7-pytest.xml`、`validation/iq-build/verification.json`、`validation/iq-packaged/verification.json`、`validation/packaged-selftest-final/selftest.json`；便携测试按独立运行目录保存，避免复用旧输出。
- 官方示例：8 份 [Imatest GPL-3.0 示例](https://github.com/imatest/examples)，固定提交 `1699bbbc8143e5a3f90260961b2677c9c33f6dd0`，全部跑通。数据与指纹见 `validation/imatest-compatibility/verification.json`。官方照片只在忽略的 samples/private 中，不随模板/便携包分发。
- 点阵例实际为 15 行 × 20 列；错误行列会失败。官方 JPEG 验收使用 sRGB 假设并保留剪切提示，不证明真实相机 OECF，也未提供商业黄金数值。
- 模块基准：[26.1 文档目录](https://docs.imatest.com/docs)。
- 图卡与拍摄前提：[SFRplus / 镜头测试](https://docs.imatest.com/docs/lens_testing)、[新版 25.2 图卡变化](https://www.imatest.com/micro_site/imatest-25-2/)。
- 灰阶测量边界：[Stepchart](https://docs.imatest.com/docs/stepchart)。
- 传感器噪声物理模型：[Image Sensor Noise](https://www.imatest.com/imaging/image-sensor-noise/)。
- 商业信息指标：[Slanted-edge Information Measurements](https://docs.imatest.com/docs/new-measurements-from-slanted-edges-information-capacity-nps-neq-snri)。
- 比较与几何约定：[SSIM](https://docs.imatest.com/docs/ssim)、[Radial Geometry](https://docs.imatest.com/24.2/radial-geometry)。
