"""Auditable reference values and conditional interpretation for IQ workflows.

These rules interpret this application's engineering measurements.  They do not
claim conformance to a standard, and a missing value can never pass a target.
All targets use the output's native units and are saved with the assessment.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import html
import math
from numbers import Real


RULE_VERSION = "2026-10-17.1"
SOURCES = {
    "ssim": "https://ece.uwaterloo.ca/~z70wang/research/ssim/",
    "psnr": "https://docs.opencv.org/4.x/d5/dc4/tutorial_video_input_psnr_ssim.html",
    "sensor": "https://www.emva.org/wp-content/uploads/EMVA1288Linear_4.0Release.pdf",
    "color": "https://www.cie.co.at/publications/colorimetry-part-6-ciede2000-colour-difference-formula-0",
    "ccm": "https://docs.imatest.com/docs/colormatrix",
    "tone": "https://docs.imatest.com/docs/color-tone/",
    "calibration": "https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html",
    "motion": "https://docs.opencv.org/4.x/d7/df3/group__imgproc__motion.html",
    "video": "https://docs.opencv.org/4.x/d4/d15/group__videoio__flags__base.html",
}
LABELS = {
    "within_target": "达到用户目标", "outside_target": "未达用户目标",
    "needs_target": "待设目标", "reference": "参考解读", "review": "需要复核",
    "insufficient": "数据不足", "invalid": "数据无效", "configured": "仿真设定",
    "complete": "操作完成", "incomplete": "操作未完成", "estimate": "条件估计",
}
POLICY = "参考值分为数学定义、算法前提、工程建议、相对比较和用户目标；工程建议不代表 ISO / EMVA 合格线。"
TARGET_HELP = '可在参数中添加 evaluation_targets，例如 {"psnr_db":{"min":40}}；限值为本项目用户目标，单位沿用原始输出。'


@dataclass(frozen=True)
class Rule:
    metric: str
    name: str
    unit: str
    reference: str
    criteria: str
    explanation: str
    action: str
    basis: str = "定义 / 相对比较"
    source: str = ""
    minimum: float | None = None
    maximum: float | None = None
    mode: str = "target"


def _r(metric, name, unit, reference, criteria, explanation, action, **kwargs):
    return Rule(metric, name, unit, reference, criteria, explanation, action, **kwargs)


RULES = {
    "compare": [
        _r("ssim", "结构相似度 SSIM", "ratio", "同一像素图为 1；可能为负值", "同尺度、同 ROI、同解码且已对齐；不设通用合格线。", "越接近 1 表示与指定参考的局部结构越相似；不是光学分辨率。", "核对像素对齐、曝光及输入曲线，再设适用场景目标。", source="ssim", minimum=-1, maximum=1),
        _r("psnr_db", "峰值信噪比 PSNR", "dB", "10 log10(1/MSE)；MSE=0 时为 +∞", "本实现 data_range=1；只比较同一参考和编码尺度。", "数值越大表示像素误差越小；不能替代感知质量或传感器 SNR。", "以可接受失真样本设目标，不套用视频压缩经验值。", source="psnr"),
        _r("mse", "均方像素误差 MSE", "signal²", "0 为逐像素一致", "在同一归一化信号尺度下越小越接近参考。", "亮度差、错位和噪声都会增加 MSE。", "先检查参考与被测图配准，避免把位移当画质损失。", source="psnr", minimum=0),
    ],
    "ptc": [
        _r("gain_dn_per_e", "系统增益", "DN/e⁻", "PTC 方差对信号的正斜率", "应为正值；与相机增益档位和 DN 定义有关，越大不等于更好。", "只在线性、未处理的同一 CFA / 单色像素上解释。", "核对成对曝光、黑电平、位深和增益设置。", source="sensor", minimum=0),
        _r("gain_e_per_dn", "电子 / DN 转换系数", "e⁻/DN", "系统增益的倒数", "应为正值；与 DN/e⁻ 必须互为倒数。", "用于把噪声由 DN 转为电子，不能跨位深直接比较。", "保留输入 DN 尺度和同温度、同增益设置。", source="sensor", minimum=0),
        _r("black_level_dn", "暗场平均黑电平", "DN", "同设置暗帧均值", "属于偏置；无统一最佳值，不能视作噪声标准差。", "黑电平可能受曝光、温度和相机偏置影响。", "对比相同条件暗帧，并检查零端剪切。", source="sensor"),
        _r("read_noise_dn", "暗场时间噪声", "DN RMS", "理想无噪声为 0", "同设置下较低通常更好；包含所选暗曝光的时间噪声。", "长曝光暗电流、量化和相机处理可能贡献噪声，不能自动分离纯读出噪声。", "补拍短曝光暗场，注明温度和读出模式。", source="sensor", minimum=0),
        _r("read_noise_e", "等效暗场 / 读出噪声", "e⁻ RMS", "暗场 DN RMS / 系统增益", "依赖有效 PTC 增益；不得当作认证读出噪声。", "跨设备比较需匹配像素尺寸、读出模式、温度及曝光。", "同时检查 PTC R² 和 DN 噪声。", source="sensor", minimum=0),
        _r("dsnu_dn", "暗信号不均匀性 DSNU", "DN RMS", "理想均匀暗场为 0", "扣除有限帧时间噪声后的暗均值空间离散。", "较小表示暗场更均匀；并非随时间变化的噪声。", "匹配温度、曝光并增加暗帧数量。", source="sensor", minimum=0),
        _r("dsnu_e", "等效 DSNU", "e⁻ RMS", "DSNU_DN / 系统增益", "依赖同条件有效增益；无统一合格线。", "空间偏置在电子单位下的工程估计。", "用校正前后暗场和独立重复采集验证。", source="sensor", minimum=0),
        _r("prnu_pct", "光响应不均匀性 PRNU", "%", "理想均匀响应为 0%", "仅同照明、曝光、增益和像素位置可比较。", "包含光源、图卡和镜头不均匀；不是独立传感器 PRNU。", "采用均匀稳定光源，并区分镜头阴影与像素响应。", source="sensor", minimum=0),
        _r("estimated_full_well_e", "饱和信号电子数估计", "e⁻", "(用户 saturation_dn − 黑电平) / 增益", "用户饱和 DN 推算值；没有实测饱和扫描不能确认满阱。", "该结果可能受 ADC 截断和饱和定义影响。", "补拍直到饱和的曝光序列，再确认饱和端与增益。", source="sensor", minimum=0, mode="estimate"),
        _r("estimated_dynamic_range_stops", "噪声动态范围估计", "stops", "log2(估计饱和电子数 / 暗场等效噪声)", "是传感器模型估计，不能等同于图卡动态范围或 JPEG 可用宽容度。", "依赖噪声和用户饱和 DN，尚无独立饱和 / QE 测量。", "报告曝光、温度、增益并验证两端数据。", source="sensor", mode="estimate"),
        _r("ptc_r_squared", "PTC 线性拟合 R²", "ratio", "理想线性拟合为 1", "本项目工程提醒线为 0.98；低于此值复核，非 EMVA 规定合格线。", "高 R² 只说明所选数据接近直线，不能排除预处理或错误采集。", "检查拟合区间、残差、配对帧和曝光稳定性。", source="sensor", maximum=1, mode="ptc_fit", basis="项目工程建议"),
        _r("variance_intercept_dn2", "PTC 方差拟合截距", "DN²", "模型截距应与暗场时间方差相容", "有限采样可产生负截距；负值需复核拟合和黑电平。", "本实现读出噪声来自暗帧，未以拟合截距直接开方。", "比较暗场方差与拟合残差，增加曝光级别。", source="sensor", mode="intercept"),
        _r("normalized_temporal_noise_model", "归一化时间噪声模型系数", "normalized variance", "常数、一次、二次项的非负拟合", "是当前 PTC 拟合的辅助模型，不是独立 PRNU 测量。", "二次项不能自动解释为传感器固有光响应不均匀。", "对照原始 PTC 点和残差，不按单个系数大小判定合格。", mode="vector"),
        _r("fitted_levels", "有效 PTC 曝光级别", "levels", "算法至少要求 4 级", "至少 4 级是计算前提，不是传感器合格要求。", "级别越少越难发现非线性，需覆盖所选拟合区间。", "补充独立曝光级别和重复帧。", basis="算法前提", minimum=4, mode="count"),
        _r("max_clipped_fraction", "平场级别最大剪切比例", "ratio", "未剪切参考为 0", "本算法拟合仅纳入剪切比例 <0.001 的级别；此处包括被排除级别。", "高曝光饱和级别可用于观察饱和端，但不能进入线性拟合。", "检查 levels 表的曝光覆盖和拟合入选情况。", minimum=0, maximum=1),
    ],
    "dark_flat": [
        _r("valid_pixel_fraction", "平场校正有效像素比例", "ratio", "1 表示本 ROI 全部像素满足响应掩码", "算法掩码要求响应 > 平均响应的 10%；不是行业坏点合格线。", "掩码外像素不能靠增益校正恢复。", "检查 valid 掩码，独立平场验证残余不均匀和噪声。", minimum=0, maximum=1, basis="算法定义"),
        _r("corrected_count", "已生成校正图像数", "files", "应与待校正输入数一致", "文件生成成功只代表操作完成。", "不能据此证明均匀性、噪声或测量准确度改善。", "在独立平场和暗场上比较校正前后结果。", minimum=1, mode="operation"),
        _r("validation_residual_pct", "独立平场残余不均匀", "%", "待提供独立验证测量", "工作流未自动重测；未提供值不能判定校正质量。", "应避免以生成校正系数的同一组帧代替独立验证。", "另拍同条件平场，用均匀性测量设定目标。", minimum=0),
    ],
    "ccm": [
        _r("mean_delta_e_before", "拟合色块校正前平均色差", "ΔE00", "与所给参考一致为 0", "须有正确参考白点与线性 RGB；无统一感知 / 合格阈值。", "校正前数值是拟合基线，不代表独立验证。", "检查参考测量、照明、颜色空间与输入曲线。", source="color", minimum=0),
        _r("mean_delta_e_after", "拟合色块校正后平均色差", "ΔE00", "与所给参考一致为 0", "仅对拟合色块目标比较；平均值不能替代最差色块。", "不能把训练误差当作未见颜色或其他光源下的色准。", "另拍验证图卡并检查逐色块误差。", source="ccm", minimum=0),
        _r("max_delta_e_after", "拟合色块最大校正后色差", "ΔE00", "理想为 0", "由逐色块 ΔE00 取最大值；只描述训练集合。", "发现被均值掩盖的最差色块。", "查看对应色块是否剪切、偏色或参考不匹配。", source="color", minimum=0),
        _r("delta_e_reduction_pct", "拟合平均色差相对降低", "%", "正值表示拟合均值降低，0 表示未变", "只做相同色块的前后相对比较。", "负值表示均值变差；接近零的前值不计算百分比。", "用独立样本确认改善没有过拟合。", source="ccm", mode="improvement"),
        _r("condition_number", "CCM 设计矩阵条件数", "ratio", "越接近 1 越稳定", "本算法拒绝 >10⁶ 或秩亏输入；不是色准阈值。", "较大条件数意味着对色块噪声更敏感。", "增加覆盖不同色相、饱和度和亮度的色块。", minimum=1, mode="conditioning", basis="算法前提"),
        _r("patch_count", "拟合色块数量", "patches", "本算法至少要求 6 块", "至少 6 块且设计矩阵满秩；数量足够不证明色彩覆盖。", "增加覆盖和独立验证比单纯增加重复色块更有效。", "补充独立验证图，不以训练误差直接验收。", minimum=6, mode="count", basis="算法前提"),
        _r("matrix", "CCM 系数矩阵", "linear RGB", "依输入颜色空间而定；无需接近单位阵", "output = input @ matrix + offset。", "负系数或大于 1 的系数不自动表示错误；需检查溢出和噪声放大。", "使用线性浮点输出，在独立图像上验证。", source="ccm", mode="vector"),
        _r("offset", "CCM 常量偏置", "linear RGB", "不拟合偏置时为 [0,0,0]", "属于颜色转换模型，不是传感器暗场黑电平。", "加入偏置增加模型自由度，需防止过拟合和暗部偏色。", "在独立灰阶和色块上验证暗部。", source="ccm", mode="vector"),
    ],
    "oecf": [
        _r("sample_count", "OECF 实测灰阶数", "levels", "导出前至少需要 4 级有效单调灰阶", "数量仅是 LUT 前提，不代表全动态范围覆盖。", "表外会夹到端点，不能外推未测高光和暗部。", "增加未剪切且有实测参考的灰阶。", source="tone", minimum=4, mode="count"),
        _r("monotonic", "OECF 严格单调性", "boolean", "编码值严格递增；线性参考不下降", "重复编码值或逆序不能生成可逆线性化表。", "单调只说明可以插值，不证明真实辐射定标。", "核对灰阶顺序、参考密度和剪切。", source="tone", mode="monotonic"),
        _r("encoded_min", "LUT 最低实测编码值", "normalized signal", "编码范围为 0–1", "只在最低至最高实测编码之间插值。", "大于 0 说明未覆盖全部黑端。", "避免将 LUT 端点之外的数据当作已定标。", minimum=0, maximum=1),
        _r("encoded_max", "LUT 最高实测编码值", "normalized signal", "编码范围为 0–1", "最亮参考归一到 1，不代表已到传感器饱和。", "小于 1 说明未覆盖全部白端。", "补充高光灰阶并排除剪切。", minimum=0, maximum=1),
        _r("encoded_coverage", "编码值实测覆盖跨度", "ratio", "max(encoded) − min(encoded)，最大 1", "覆盖越广仅说明 LUT 的实测区间越广。", "不是可用动态范围，也不提供暗端 SNR。", "记录表的有效区间，不把 LUT 当作满量程定标。", minimum=0, maximum=1),
    ],
    "calibrate": [
        _r("rms_px", "多视图重投影 RMS", "px", "理想模型与角点一致时为 0 px", "以任务几何误差预算设限；不设通用 0.5 / 1 px 合格线。", "训练视图残差小不保证外推精度或标定正确。", "检查边缘视图和独立图像中的直线 / 尺度残差。", source="calibration", minimum=0),
        _r("max_per_view_rms_px", "最差视图重投影 RMS", "px", "0 px 为理想", "与总体 RMS 同单位，应用最差视图约束检查离群。", "总体均值可能掩盖图卡翘曲、模糊或错误角点。", "查看最差视图，核对角点后重拍。", source="calibration", minimum=0),
        _r("view_count", "有效标定视图数", "views", "本算法至少要求 5 个不同姿态", "数量与姿态、距离、全画面覆盖都需要核对。", "只有平移或重复正视图不能稳定约束内参。", "加入边缘、倾斜和不同距离视图。", source="calibration", minimum=5, mode="count", basis="算法前提"),
        _r("rejected_count", "未检出完整图卡的视图数", "views", "0 表示未排除输入", "排除的帧不参与拟合；不是相机质量测量。", "需确认排除后仍有足够姿态覆盖。", "检查完整角点、模糊、反光和 rows/cols。", minimum=0, mode="informational"),
        _r("horizontal_fov_deg", "模型水平视场", "degrees", "由内参及当前图像尺寸计算", "随焦距、裁切、对焦变化；无统一最佳值。", "属于当前标定模型估计，不能证明物理镜头标称视角。", "使用独立角度靶验证所需视场。", source="calibration", minimum=0, maximum=180),
        _r("vertical_fov_deg", "模型垂直视场", "degrees", "由内参及当前图像尺寸计算", "与当前分辨率、裁切和对焦绑定。", "重采样或裁切后不能直接沿用旧内参。", "保留标定时分辨率、焦距和对焦状态。", source="calibration", minimum=0, maximum=180),
        _r("distortion", "Brown–Conrady 畸变系数", "model coefficients", "k1,k2,p1,p2,k3；依模型和归一坐标而定", "系数不是百分比，不按接近 0 评价镜头好坏。", "不同模型、裁切和视场下系数不能直接排名。", "用图像边缘和独立视图验证残余畸变。", source="calibration", mode="vector"),
        _r("camera_matrix", "相机内参矩阵", "px / homogeneous", "fx,fy,cx,cy 属当前分辨率与裁切坐标", "焦距和主点需与当前画面及独立几何实测一致。", "像素焦距不能在没有传感器尺寸时换算物理焦距。", "保持焦距、对焦、分辨率和裁切一致，再用独立视图验证。", source="calibration", mode="vector"),
    ],
    "undistort": [
        _r("corrected_count", "已去畸变图像数", "files", "应与所选输入数一致", "只代表已生成线性浮点重采样图像。", "不代表标定准确或分辨率提升。", "检查边缘裁切和独立图像中的残余畸变。", minimum=1, mode="operation"),
        _r("validation_residual_px", "去畸变后独立几何残差", "px", "待提供独立验证结果；理想为 0 px", "当前工作流没有自动重测，不判为校正质量通过。", "需要在同焦距、对焦、分辨率下验证。", "对独立棋盘格或点阵重新测量。", source="calibration", minimum=0),
    ],
    "sequence": [],  # Temporal rules are shared below, with separate noise outputs.
    "video": [],
    "simulate": [
        _r("optical_sigma_px", "高斯光学模糊设定", "px sigma", "0 为本模型无高斯模糊", "仿真输入，不是实测 PSF 或实际分辨率。", "本模型不含衍射瞳面、像差或复杂 PSF。", "用真实图卡测量验证模型能否代表设备。", minimum=0, mode="configured"),
        _r("full_well_e", "模型满阱设定", "e⁻", "用户给定正值", "是模型参数，不能据此评价真实传感器。", "泊松散粒噪声和读出噪声依该值生成。", "用 PTC 实测数据约束仿真。", minimum=1, mode="configured"),
        _r("read_noise_e", "模型读出噪声设定", "e⁻ RMS", "0 为不加入高斯读出噪声", "仿真参数，非测量结果。", "不包含所有真实传感器噪声成分。", "匹配真实读出模式与温度。", minimum=0, mode="configured"),
        _r("prnu_pct", "模型 PRNU 设定", "%", "0 为不加入 PRNU", "仿真参数，不是传感器 PRNU 评价。", "固定图样只在此次仿真内保持。", "需要多帧传感器仿真时核对固定图样一致性。", minimum=0, mode="configured"),
        _r("exposure", "仿真曝光倍数", "ratio", "1 为保持参考曝光", "输入线性；不是实际曝光时间。", "曝光倍数会影响剪切和噪声。", "与源图和噪声参数一起报告。", minimum=0, mode="configured"),
        _r("gamma", "仿真编码 Gamma", "ratio", "1 为保持线性", "模型 encoded = signal^(1/gamma)。", "不是 sRGB 分段传递曲线，也不是实测 OECF。", "分析输出时选择相应输入响应。", minimum=0, mode="configured"),
        _r("bits", "仿真量化位数", "bits", "8 / 10 / 12 / 14 / 16", "量化级数由参数决定；不等于有效噪声位数。", "高位深不自动带来对应动态范围。", "比较噪声、剪切与量化误差。", minimum=8, maximum=16, mode="configured"),
        _r("clipped_fraction", "仿真输出剪切比例", "ratio", "0 表示本统计阶段未触及两端", "基于 WB/CCM/锐化后、Gamma 前信号；不是完整 RAW 饱和统计。", "大于 0 提醒该模型已有丢失信号。", "降低曝光、白平衡增益或锐化，并检查单通道。", minimum=0, maximum=1),
    ],
    "capture": [
        _r("captured", "已采集帧数", "frames", "应与 requested 一致", "只评价采集操作完成程度，不评价 RAW 质量。", "驱动 / 解码 RGB 8-bit 不能视为原始传感器数据。", "核对文件和实际时间戳，保留设备设置。", minimum=1, mode="operation"),
        _r("complete", "采集任务完整性", "boolean", "captured = requested 且 complete=true", "仅代表所请求帧数已写出。", "不保证无丢帧、无压缩或硬件同步。", "用独立帧计数器 / 硬件时间戳验证采集。", mode="capture_complete", basis="任务完成条件"),
        _r("median_interval_s", "已记录采集间隔中位数", "s", "相邻 time_s 的正差中位数", "本机读取 / 保存时刻，非传感器曝光时间戳。", "包括驱动、解码和写文件耗时；视频源通常尽快读取。", "需要实时性能时使用硬件时间戳。", source="video", minimum=0),
    ],
    "test_plan": [
        _r("test_count", "计划执行测试数", "tests", "至少 1 项，且各项有限值规则", "仅明确用户限值可以得到通过 / 未通过。", "测试计划不是 ISO 或 EMVA 认证方案。", "审核限值、单位、通道、区域和有效测点数量。", minimum=1, mode="count", basis="用户测试计划"),
        _r("status", "测试计划综合状态", "status", "全部测试及规则均有有效数值并达到用户限值", "不能只根据顶层 pass 字符串通过；需可审核的规则明细。", "只评价当前计划所写的条件，不代表其他未测试项目。", "查看逐项规则、缺失测点和异常信息。", mode="plan_status", basis="用户测试计划"),
    ],
    "rank": [
        _r("valid_mtf_count", "具有有效 MTF50 的排名图像数", "images", "至少 2 张有效图像才有 MTF 相对比较意义", "同图案、ROI、曝光、采样尺度和处理链比较。", "无有效斜边的图像不能按 MTF50 评价优劣。", "固定测试条件并检查每张图的有效斜边。", minimum=0, mode="rank_count"),
        _r("best_mtf50", "候选图像最高有效 MTF50", "cy/px", "当前采样的奈奎斯特频率为 0.5 cy/px", "当前候选集的最大值；不代表镜头极限或整个幅面。", "锐化会提高 MTF50；同时检查过冲、混叠和其他位置。", "比较同条件未锐化结果，并扩大测点覆盖。", minimum=0, maximum=.5),
        _r("best_focus_score", "候选图像最高相对梯度评分", "signal²/px²", "Tenengrad 分数无通用单位阈值", "仅同曝光、同场景、同处理下相对比较。", "噪声、纹理和对比度会提高分数，不能换算 DPI。", "优先查看有效 MTF50 和图卡曲线。", minimum=0, mode="informational"),
    ],
}


_TEMPORAL_RULES = [
    _r("frame_count", "有效采样帧数", "frames", "至少 3 帧才能计算本统计", "帧数和时间覆盖共同决定观察能力。", "抽样可能漏掉短暂振荡或阶跃。", "提高采样密度并延长稳定段。", minimum=3, mode="count", basis="算法前提"),
    _r("duration_s", "已观察时长", "s", "最后与最早采样时间差", "必须覆盖真实阶跃和所需稳定时长。", "短序列未稳定不能当作超时规格实测上限。", "延长采集并记录实际时间戳。", minimum=0, mode="informational"),
    _r("brightness_flicker_pct", "亮度帧间变动系数", "%", "100 × 帧均值标准差 / 平均亮度；理想稳定值为 0%", "包含曝光阶跃、运动及照明变化，不能当作频闪频率 / SVM / PstLM。", "只有稳定场景 / 照明观察段才可解释为亮度稳定性。", "分离阶跃与稳定窗口，并增加采样率。", minimum=0, source="video"),
    _r("motion_step_rms_px", "相邻采样帧平移 RMS", "px", "静态图案理想为 0 px", "仅纳入相关响应足够的平移，不是 ISO 防抖档数。", "运动、低纹理、缩放、旋转和滚动快门会影响结果。", "固定静态纹理靶，检查相关有效比例与抽样间隔。", minimum=0, source="motion"),
    _r("motion_valid_fraction", "运动相关有效间隔比例", "ratio", "有效平移间隔 / 所有相邻间隔，最大 1", "低纹理失配的间隔不应被当成零运动。", "RMS 只代表被接受间隔；比例不足时存在选择偏差。", "增加稳定纹理并检查每帧 response。", minimum=0, maximum=1),
    _r("best_focus_time_s", "相对焦点评分峰值时刻", "s", "当前采样帧中的梯度分数峰值", "不是镜头焦距 / 物距 / 轴向最佳焦位。", "曝光和内容变化可改变峰值；不能用于 RGB 轴向色差结论。", "固定曝光和场景，另做有实际焦位的焦点序列。", minimum=0, mode="informational"),
    _r("max_clipped_fraction", "采样帧最大剪切比例", "ratio", "0 为未触及输入两端", "是处理后归一化信号统计，黑区域也可能贡献端点像素。", "不能仅凭零端像素判断真实传感器欠曝。", "检查 ROI 和每通道直方图，排除标靶黑白实色影响。", minimum=0, maximum=1),
    _r("valid_mtf_count", "含有效斜边 MTF50 的帧数", "frames", "有效斜边帧才有 MTF 输出", "未检出时保留相对梯度分数；不补造 MTF。", "数量不代表整个视频每帧都测到同一边缘。", "固定斜边 ROI 并检查帧间运动。", minimum=0, mode="informational"),
]
for _kind in ("video", "sequence"):
    RULES[_kind] = list(_TEMPORAL_RULES)
    for _prefix, _name in (("ae", "AE 亮度"), ("awb_r_g", "AWB R/G"), ("awb_b_g", "AWB B/G"), ("focus", "AF 相对梯度")):
        RULES[_kind].append(_r(_prefix+".settling_seconds", _name+"稳定时间", "s", "从声明的真实阶跃起进入容差，并在剩余记录中保持", "容差与持续时长由参数给定；无通用速度合格线。", "未找到稳定段表示观测窗内未证实稳定，不能填 0 秒。", "确认阶跃时刻；AWB 还需中性灰 ROI，AF 还需固定曝光与场景。", minimum=0, mode="settling"))
        RULES[_kind].append(_r(_prefix+".overshoot_pct", _name+"单侧最大超调", "%", "0 表示未观察到高于终值的正向超调", "仅统计正向最大值，不是正负双向误差或全瞬态性能。", "AWB 终值按 R/G、B/G=1；AE 可用目标或尾段中位数。", "同时查看完整时序、容差和是否实际稳定。", minimum=0, mode="temporal_overshoot"))
RULES["sequence"] += [
    _r("noise.temporal_noise", "重复帧时间噪声", "normalized signal RMS", "逐像素时间方差的均方根；理想为 0", "要求固定场景、曝光、图像坐标与响应；不等于 e⁻ 读出噪声。", "运动和光源闪烁也会增加该值。", "采用稳定均匀靶和实际时间戳，电子单位另做 PTC。", minimum=0),
    _r("noise.fixed_pattern_rms", "重复帧空间固定分量", "normalized signal RMS", "扣除有限帧时间噪声后的空间标准差", "含图案、照明及镜头不均匀，不能自动视为传感器固有固定噪声。", "拍摄真实场景时该值会包含正常纹理。", "使用确认均匀的平场或暗场。", minimum=0),
    _r("noise.prnu_pct", "重复帧表观 PRNU", "%", "空间固定分量 / 平均信号 ×100", "须显式 uniform_roi_confirmed=true 才按均匀平场解读。", "未确认均匀场时只属于场景空间变化，不能称为传感器 PRNU。", "确认平场均匀、无剪切及同设置后再比较。", minimum=0, mode="uniform"),
]


WORKFLOW_GUIDANCE = {
    "compare": "SSIM=1、MSE=0 表示与指定参考一致；PSNR 零误差为 +∞。评价需同尺度、同 ROI、同解码并已对齐；未设目标只给相对解读。",
    "ptc": "PTC 使用线性未处理 DN；增益 / 噪声 / PRNU 没有跨设备统一合格线。R²≥0.98 是本项目拟合复核建议，满阱和动态范围仍为用户饱和 DN 的条件估计。",
    "dark_flat": "有效掩码代表可校正像素，文件写出代表操作完成；校正质量应另拍平场和暗场独立验证。",
    "ccm": "ΔE00 越小越接近所给参考；校正前后仅在同一拟合色块上比较，需独立图卡验证，不能套用统一可见 / 合格阈值。",
    "oecf": "参考为至少 4 级有效单调灰阶。LUT 只在实测编码范围插值，表外夹到端点；最亮归一化不等于测到饱和。",
    "calibrate": "重投影误差理想为 0 px；按用途设误差预算。至少 5 视图是算法前提，低残差还需不同姿态覆盖和独立图像验证。",
    "undistort": "写出成功只代表操作完成。校正图已重采样；残余畸变和分辨率需在独立图像上重新测量。",
    "video": "AE/AF 需 step_declared=true 确认真实阶跃，AWB 需 neutral_roi_confirmed=true 确认中性灰。相邻平移不是防抖档数，帧亮度变动不是频闪标准量。",
    "sequence": "固定场景 / 曝光 / 像素位置才可比较时间噪声；电子噪声另做 PTC。PRNU 解读需 uniform_roi_confirmed=true；假定时间间隔不能替代硬件时间戳。",
    "simulate": "参数是模型输入而非设备测量。剪切为模型输出统计；仿真结果不能据此获得真实传感器或光学质量合格结论。",
    "capture": "帧数相符只代表采集任务完成。驱动 / 视频输出是 RGB 8-bit，写文件时间不是曝光硬件时间戳。",
    "test_plan": "只有明确的用户限值、足够有效测点及完整执行才能通过；缺失、无效、异常和未运行的测项不能通过。",
    "rank": "只在同 ROI、采样、曝光和处理下按有效 MTF50 相对排名；梯度评分会受噪声影响，不能换算实际 DPI。",
}


def _number(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value))


def _finite_values(values):
    return [float(v) for v in values if _number(v)] if isinstance(values, (list, tuple)) else []


def _get(data, key):
    for part in key.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def _median(values):
    values = sorted(values)
    n = len(values)
    return (values[(n-1)//2]+values[n//2])/2 if n else None


def _derived(kind, output):
    data = dict(output)
    if kind == "ptc":
        values = [r.get("clipped_fraction") for r in output.get("levels", []) if isinstance(r, dict)]
        finite = _finite_values(values)
        data["max_clipped_fraction"] = max(finite) if finite else None
    elif kind == "ccm":
        finite = _finite_values(output.get("delta_e_2000_after"))
        data["max_delta_e_after"] = max(finite) if finite else None
        before, after = output.get("mean_delta_e_before"), output.get("mean_delta_e_after")
        data["delta_e_reduction_pct"] = 100*(before-after)/before if _number(before) and before > 1e-12 and _number(after) else None
    elif kind == "oecf":
        encoded, linear = output.get("encoded"), output.get("linear")
        e, l = _finite_values(encoded), _finite_values(linear)
        complete = bool(e and l and len(e) == len(l) == len(encoded) == len(linear))
        data.update(sample_count=len(e) if complete else None,
                    monotonic=bool(all(b > a for a, b in zip(e, e[1:])) and all(b >= a for a, b in zip(l, l[1:]))) if complete else None,
                    encoded_min=min(e) if complete else None, encoded_max=max(e) if complete else None,
                    encoded_coverage=max(e)-min(e) if complete else None)
    elif kind == "calibrate":
        finite = _finite_values(output.get("per_view_rms_px"))
        data["max_per_view_rms_px"] = max(finite) if finite else None
        data["rejected_count"] = len(output["rejected_images"]) if isinstance(output.get("rejected_images"), list) else None
    elif kind in {"video", "sequence"}:
        data.update(output.get("summary") or {})
        frames = [r for r in output.get("frames", []) if isinstance(r, dict)]
        if len(frames) > 1:
            data["motion_valid_fraction"] = sum(_number(r.get("dx_px")) and _number(r.get("dy_px")) for r in frames[1:])/(len(frames)-1)
        clipping = _finite_values([r.get("clipped_fraction") for r in frames])
        data["max_clipped_fraction"] = max(clipping) if clipping else None
        data["valid_mtf_count"] = sum(_number(r.get("mtf50")) for r in frames) if frames else None
    elif kind == "capture":
        t = _finite_values([r.get("time_s") for r in output.get("frames", []) if isinstance(r, dict)])
        data["median_interval_s"] = _median([b-a for a, b in zip(t, t[1:]) if b > a])
    elif kind == "test_plan":
        data["test_count"] = len(output["tests"]) if isinstance(output.get("tests"), list) else None
    elif kind == "rank":
        rows = [r for r in output.get("ranking", []) if isinstance(r, dict)]
        mtf = _finite_values([r.get("mtf50") for r in rows])
        scores = _finite_values([r.get("focus_score") for r in rows])
        data.update(valid_mtf_count=len(mtf) if rows else None, best_mtf50=max(mtf) if mtf else None,
                    best_focus_score=max(scores) if scores else None)
    return data


def _target(target):
    if not isinstance(target, dict) or not ({"min", "max"} & target.keys()):
        return None
    low, high = target.get("min"), target.get("max")
    if all(v is None for v in (low, high)) or any(v is not None and not _number(v) for v in (low, high)):
        return None
    if low is not None and high is not None and low > high:
        return None
    return {"min": low, "max": high}


def _interpret(rule, value, data, parameters):
    """Return verdict and additional text; never infer validity from zero alone."""
    kind = parameters.get("_workflow")
    prefix = rule.metric.split(".")[0]
    if rule.metric == "psnr_db" and data.get("identical") is True and data.get("mse") == 0 and value is None:
        return "reference", "MSE=0，PSNR 按定义为 +∞；JSON 以 null 保存该特殊值，不能误读为 0 dB。"
    if rule.mode == "settling":
        block = data.get(prefix)
        if not isinstance(block, dict):
            return "insufficient", "没有有效的稳定性记录。"
        prerequisite = (parameters.get("neutral_roi_confirmed") is True if prefix.startswith("awb") else parameters.get("step_declared") is True)
        if not prerequisite:
            return "insufficient", "尚未确认中性灰 ROI，不能评价 AWB。" if prefix.startswith("awb") else "尚未声明真实 AE / AF 阶跃，当前只可观察信号变化。"
        if block.get("within_tolerance") is not True or not _number(value):
            return "review", "观测窗口内未证实达到并保持稳定；无稳定时间值，不能填 0 或判定通过。"
    if rule.mode == "temporal_overshoot":
        prerequisite = (parameters.get("neutral_roi_confirmed") is True if prefix.startswith("awb") else parameters.get("step_declared") is True)
        if not prerequisite:
            return "insufficient", "没有确认该瞬态测试的阶跃或中性灰前提。"
    if rule.mode == "uniform" and parameters.get("uniform_roi_confirmed") is not True:
        return "insufficient", "未确认均匀平场；该数值只能描述场景的空间变化，不能评价 PRNU。"
    if rule.mode == "vector":
        def finite_tree(v):
            return _number(v) or isinstance(v, (list, tuple)) and bool(v) and all(finite_tree(i) for i in v)
        return ("reference", "系数仅描述当前模型；需要独立验证，不能按系数大小自动判定优劣。") if finite_tree(value) else ("insufficient", "未提供完整有限的模型系数。")
    if rule.mode == "monotonic":
        return ("reference", "当前表满足单调插值前提；未证明整个输入范围已定标。") if value is True else ("invalid", "LUT 非单调。") if value is False else ("insufficient", "缺少完整 LUT，不能确认单调性。")
    if rule.mode == "capture_complete":
        captured, requested = data.get("captured"), data.get("requested")
        complete = value is True and _number(captured) and _number(requested) and captured == requested and requested > 0
        return ("complete", "请求帧数已写出；这属于操作结果。") if complete else ("incomplete", "请求帧数未证实完整写出。")
    if rule.mode == "plan_status":
        rows = _plan_items(data)
        if value == "pass" and rows and all(r["verdict"] == "within_target" for r in rows):
            return "within_target", "全部可审核的计划规则达到当前用户限值。"
        if value in {"fail", "error"}:
            return "outside_target", "计划含未通过或异常测试；需查看各项明细。"
        return "insufficient", "缺少完整、有效、可审核的计划规则，不能判定通过。"
    if not _number(value):
        return "insufficient", "未提供有限有效数值；不填 0，不判定通过。"
    if rule.minimum is not None and value < rule.minimum or rule.maximum is not None and value > rule.maximum:
        return "invalid", "数值不满足该定义或算法前提，请检查输入、参考和输出完整性。"
    if rule.mode == "configured":
        return "configured", "该值为模型输入，不能据此证明设备的实测表现。"
    if rule.mode == "estimate":
        return "estimate", "由用户饱和 DN 和拟合增益推算；未确认真实饱和端前保留为条件估计。"
    if kind == "ptc" and rule.metric in {"gain_dn_per_e", "gain_e_per_dn", "read_noise_e", "dsnu_e"}:
        if rule.metric.startswith("gain_") and value <= 0:
            return "invalid", "增益必须为正值。"
        r2 = data.get("ptc_r_squared")
        if not _number(r2) or r2 < .98:
            return "review", "PTC 拟合未满足本项目 R²≥0.98 的工程复核建议，电子数换算 / 增益需复核。"
        gain, inverse = data.get("gain_dn_per_e"), data.get("gain_e_per_dn")
        if not _number(gain) or not _number(inverse) or gain <= 0 or inverse <= 0 or not math.isclose(gain*inverse, 1, rel_tol=1e-3):
            return "invalid", "系统增益与电子 / DN 转换系数缺失或不互为倒数，不能使用电子单位结果。"
    if rule.mode == "ptc_fit" and value < .98:
        return "review", "低于本项目 0.98 工程提醒线；不是 EMVA 合格判定。"
    if rule.mode == "intercept" and value < 0:
        return "review", "拟合截距为负；需检查拟合区间、噪声和黑电平。"
    if rule.mode == "conditioning" and value > 1e6:
        return "invalid", "超出本算法可接受的矩阵条件数 10⁶。"
    if rule.mode == "improvement" and value < 0:
        return "review", "拟合色差均值增加，需检查参考和优化。"
    if rule.mode == "rank_count" and value < 2:
        return "insufficient", "不足两张有效 MTF50 图像，无法作可靠的 MTF 相对排名。"
    targets = parameters.get("evaluation_targets")
    if isinstance(targets, dict) and rule.metric in targets:
        target = _target(targets[rule.metric])
        if target is None:
            return "invalid", "用户目标无效：需有限 min / max，且 min≤max。"
        if kind == "ccm" and parameters.get("_input_transfer") == "unknown":
            return "review", "输入响应未知，不能确认线性 RGB 前提；色差 / CCM 用户目标暂不判通过。"
        passed = (target["min"] is None or value >= target["min"]) and (target["max"] is None or value <= target["max"])
        return ("within_target", "达到所保存的用户目标；仅在本测量条件和范围内有效。") if passed else ("outside_target", "未达到所保存的用户目标。")
    if rule.mode == "operation":
        return "complete", "已生成输出文件；未自动验证校正后的质量。"
    if rule.mode == "ptc_fit":
        return "reference", "达到本项目 R²≥0.98 的拟合参考；仍需检查采集条件和残差。"
    if rule.mode == "conditioning":
        return "reference", "未超出算法病态拒绝界限；不等于色准通过。"
    if rule.mode == "improvement":
        return "reference", "拟合色差均值相对降低或持平；尚需独立验证。"
    if rule.mode in {"count", "informational", "rank_count"}:
        return "reference", "满足当前统计的数量 / 数据前提或给出相对信息，不代表质量合格。"
    return "needs_target", "已有测量值；请按用途、设备和采集条件设定目标，当前不作通用合格判定。"


def _plan_items(data):
    rows = []
    for index, test in enumerate(data.get("tests") or []):
        if not isinstance(test, dict):
            continue
        rules = test.get("rules")
        if not isinstance(rules, list) or not rules:
            rows.append(dict(metric=f"test.{index+1}", name=f"测试 {index+1} · {test.get('name', '')}", value=test.get("status"), unit="status", reference="完整执行且含明确限值规则", criteria="缺失规则、异常或未运行不可通过。", basis="用户测试计划", verdict="invalid" if test.get("status") == "error" else "insufficient", explanation=str(test.get("reason") or "未提供可审核的限值规则。"), action="检查测试结果、图卡和限值。", source_urls=[]))
            continue
        for j, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            target = _target(rule)
            values = _finite_values(rule.get("values"))
            count, minimum = rule.get("valid_count"), rule.get("minimum_count", 1)
            complete = bool(target and values and isinstance(rule.get("values"), list) and len(values) == len(rule["values"]) and _number(count) and _number(minimum) and minimum >= 1 and count >= minimum)
            passed = bool(complete and test.get("status") in {"pass", "fail"} and rule.get("status") == "pass" and all((target["min"] is None or v >= target["min"]) and (target["max"] is None or v <= target["max"]) for v in values))
            verdict = "within_target" if passed else "outside_target" if complete else "insufficient"
            rows.append(dict(metric=f"test.{index+1}.rule.{j+1}", name=f"{test.get('name', index+1)} · {rule.get('metric', j+1)} · {rule.get('channel', 'all')}", value=values or None, unit="metric native unit", reference=f"用户最小值 {rule.get('min')}；最大值 {rule.get('max')}", criteria=f"聚合 {rule.get('aggregation', 'all')}；最少有效测点 {minimum}；有效 / 匹配 {count}/{rule.get('matched_count')}", basis="用户测试计划", verdict=verdict, explanation="达到当前计划所保存的限值。" if passed else str(rule.get("reason") or test.get("reason") or "缺少有效数据或未达到计划限值。"), action="同时核对计量单位、测点有效性、区域覆盖和计划中的采集条件。", source_urls=[], target=target))
    return rows


def assess_workflow(kind, output, parameters=None):
    """Return JSON-safe per-result criteria, evidence and conditional verdicts."""
    parameters = dict(parameters or {})
    parameters["_workflow"] = kind
    output = output if isinstance(output, dict) else {}
    data = _derived(kind, output)
    invalid = output.get("valid") is False or output.get("status") in {"invalid", "error"}
    flags = output.get("flags", [])
    invalid = invalid or isinstance(flags, list) and any(v in {"invalid", "missing_reference", "uncalibrated"} for v in flags)
    items = []
    for rule in RULES.get(kind, []):
        value = _get(data, rule.metric)
        verdict, extra = _interpret(rule, value, data, parameters)
        if invalid:
            verdict, extra = "invalid", "原始工作流标记无效 / 缺失标定或参考，不能按数值判定通过。"
        elif output.get("lower_bound") is True or output.get("upper_bound") is True or isinstance(flags, list) and any(v in {"lower_bound", "upper_bound"} for v in flags):
            verdict, extra = "estimate", "原始工作流仅提供测量下界 / 上界，不能作为精确值进行质量通过判定。"
        item = dict(metric=rule.metric, name=rule.name, value=_safe(value), unit=rule.unit,
                    reference=rule.reference, criteria=rule.criteria, basis=rule.basis,
                    verdict=verdict, explanation=rule.explanation+" "+extra, action=rule.action,
                    source_urls=[SOURCES[rule.source]] if rule.source else [])
        if rule.metric == "psnr_db" and data.get("identical") is True and data.get("mse") == 0 and value is None:
            item["display_value"] = "+∞（MSE=0）"
        targets = parameters.get("evaluation_targets")
        if isinstance(targets, dict) and rule.metric in targets:
            item["target"] = _safe(targets[rule.metric])
            item["criteria"] += " 用户目标（原生单位）："+str(item["target"])
            item["basis"] += " / 用户目标"
        items.append(item)
    if kind == "test_plan":
        plan_rows = _plan_items(data)
        if invalid:
            for row in plan_rows:
                row.update(verdict="invalid", explanation="原始计划标记无效，规则数值不能用于通过判定。")
        items.extend(plan_rows)
    counts = dict(Counter(item["verdict"] for item in items))
    attention = any(counts.get(k, 0) for k in ("outside_target", "invalid", "review", "incomplete"))
    missing = any(counts.get(k, 0) for k in ("insufficient", "needs_target", "estimate"))
    status = "attention" if attention else "conditional" if missing else "reference"
    return {"schema_version": 1, "rule_version": RULE_VERSION, "workflow": kind,
            "policy": POLICY, "guidance": WORKFLOW_GUIDANCE.get(kind, "未知工作流，暂无评价规则。"),
            "summary": {"status": status, "counts": counts,
                        "message": "存在需复核 / 未达目标的项目。" if attention else "部分项目需补充数据、目标或独立验证。" if missing else "已提供参考解读；不构成统一质量认证。"},
            "items": items, "limitations": _safe(output.get("warnings", output.get("limitations", [])))}


def _safe(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Real):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    return str(value)


def _display(value):
    if value is None:
        return "未提供 / 未测得"
    if isinstance(value, bool):
        return "是" if value else "否"
    if _number(value):
        return f"{value:.6g}"
    return str(value)


def workflow_reference_text(kind):
    """Help shown before a task starts, including native-unit target examples."""
    lines = [WORKFLOW_GUIDANCE.get(kind, ""), POLICY, TARGET_HELP, ""]
    for rule in RULES.get(kind, []):
        lines.extend([f"{rule.name}（{rule.unit}）", f"参考：{rule.reference}",
                      f"标准 / 条件：{rule.criteria} [{rule.basis}]", f"说明：{rule.explanation}", f"建议：{rule.action}", ""])
    return "\n".join(lines)


def evaluation_text(evaluation):
    lines = ["结果评价 / 参考值与评价标准", evaluation.get("policy", POLICY),
             evaluation.get("guidance", ""), evaluation.get("summary", {}).get("message", ""), ""]
    for item in evaluation.get("items", []):
        lines.extend([f"{item['name']}：{item.get('display_value', _display(item.get('value')))} {item['unit']} · {LABELS.get(item['verdict'], item['verdict'])}",
                      f"参考：{item['reference']}", f"标准 / 条件：{item['criteria']} [{item['basis']}]",
                      f"评价：{item['explanation']}", f"建议：{item['action']}", ""])
    return "\n".join(lines)


def evaluation_html(evaluation):
    esc = lambda v: html.escape(str(v), quote=True)
    rows = []
    for item in evaluation.get("items", []):
        sources = " ".join(f"<a href='{esc(url)}' rel='noreferrer'>定义来源</a>" for url in item.get("source_urls", []))
        rows.append(f"<tr><td>{esc(item['name'])}<br><strong>{esc(item.get('display_value', _display(item.get('value'))))} {esc(item['unit'])}</strong></td>"
                    f"<td><span class='verdict {esc(item['verdict'])}'>{esc(LABELS.get(item['verdict'], item['verdict']))}</span></td>"
                    f"<td>{esc(item['reference'])}<br><small>{esc(item['criteria'])}<br>依据：{esc(item['basis'])}</small></td>"
                    f"<td>{esc(item['explanation'])}<br>建议：{esc(item['action'])}<br>{sources}</td></tr>")
    return (f"<section><h2>结果评价 / 参考值与评价标准</h2><p>{esc(evaluation.get('policy', POLICY))}</p>"
            f"<p>{esc(evaluation.get('guidance', ''))}</p><p>{esc(evaluation.get('summary', {}).get('message', ''))}"
            f" 规则版本：{esc(evaluation.get('rule_version', ''))}</p><div class='scroll'><table class='evaluation'>"
            "<thead><tr><th>项目 / 结果</th><th>评价</th><th>参考值 / 标准 / 依据</th><th>解读与行动</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div></section>")
