"""Reference definitions, separate from measurement algorithms and pass/fail goals.

Numeric bands below are MUTEX engineering suggestions, not ISO acceptance
limits. A referenced standard defines a quantity; it does not endorse our bands.
"""
from dataclasses import dataclass, asdict
from .analysis_catalog import METRIC_LABELS

REFERENCE_VERSION = 'MUTEX-reference-1.1'
SOURCES = {
    'sharpness': ('Imatest · Sharpness / frequency units', 'https://www.imatest.com/imaging/sharpness/'),
    'noise': ('Imatest · Noise', 'https://www.imatest.com/imaging/noise/'),
    'dr': ('Imatest · Dynamic range', 'https://www.imatest.com/imaging/dynamic-range/'),
    'ca': ('Imatest · Chromatic aberration (different CA definition)', 'https://www.imatest.com/imaging/chromatic-aberration/'),
    'sharpening': ('Imatest · Sharpening', 'https://www.imatest.com/imaging/sharpening/'),
    'color': ('ISO/CIE 11664-6:2022 · CIEDE2000 definition', 'https://www.iso.org/standard/82662.html'),
    'geometry': ('OpenCV · Camera calibration', 'https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html'),
    'flat': ('Imatest · Flat field results', 'https://docs.imatest.com/docs/flatfield-results'),
    'oecf': ('Imatest · OECF / ISO 14524', 'https://www.imatest.com/imaging/iso-14524/'),
    'glare': ('ISO 18844:2017 · scope (no prescribed target range)', 'https://www.iso.org/standard/63552.html'),
    'information': ('Imatest · Information metrics (different capacity models)', 'https://docs.imatest.com/docs/new-measurements-from-slanted-edges-information-capacity-nps-neq-snri'),
    'local': ('MUTEX · 本项目测量定义与工程建议', ''),
}


@dataclass(frozen=True)
class Reference:
    reference: str
    criteria: str
    prerequisites: str
    action: str
    mode: str = 'target'
    unit: str = ''
    bands: tuple | None = None
    absolute: bool = False
    sources: tuple = ('local',)

    def to_dict(self, key):
        data = asdict(self)
        data['bands']=list(self.bands) if self.bands is not None else None
        data.update(metric=key, name=METRIC_LABELS[key], version=REFERENCE_VERSION,
                    basis='MUTEX 工程建议（非行业合格线）' if self.bands else '定义 / 理论参考；无统一合格线',
                    sources=[{'title': SOURCES[s][0], 'url': SOURCES[s][1]} for s in self.sources])
        return data


REFERENCES = {}


def add(keys, **kwargs):
    for key in keys.split():
        REFERENCES[key] = Reference(**kwargs)


add('resolution_limit ctf50 ctf20 ctf10 mtf50 mtf50p mtf20 mtf10 texture_mtf50 texture_mtf10 log_mtf50 log_mtf10',
    reference='奈奎斯特参考 0.5 cy/px；50 / 20 / 10% 是响应定义，不是合格线。',
    criteria='同图案、同方法、同通道和方向，频率越高通常越清晰。并列本帧同组最高值及比值，不据此评价器材等级。未跨阈值不填零；图卡上限只给实测下界。',
    prerequisites='有效定位、足够频率覆盖、已知输入曲线。lp/mm 与等效 DPI 需物理标定；LW/PH 需正确参考图高。方波 CTF 与正弦 MTF 分开解释。',
    action='比较完整曲线、最弱区域及锐化 / 混叠；扩大图卡频率覆盖或补拍焦位序列。',
    mode='relative_high', unit='cy/px', sources=('sharpness','local'))
add('usaf_focus_score mtf_area information_capacity_1d',
    reference='没有通用目标值；以相同设置的基准或自定义下限为参考。',
    criteria='同曝光、图案、通道和算法下越高通常越好；显示本帧同组最高值比值。整卡评分是项目定义；MTF 面积未按峰值归一化；1D 容量不等于位深或商业 C4/Cmax。',
    prerequisites='足够有效频率；容量还需有效噪声参考与线性化。同条件才可比较。',
    action='用相同位置的焦位序列或独立基准比较，避免跨图案、跨曝光直接排名。', mode='relative_high',
    sources=('information','sharpness','local'))
add('ca_r_g_px ca_b_g_px rgb_shift_px rgb_shift_x_px rgb_shift_y_px dot_ca_r_g_rms_px dot_ca_b_g_rms_px',
    reference='理想 0 px；有符号分量按绝对值评价，保留原始方向。',
    criteria='MUTEX 建议：|位移| ≤ 0.25 px 较小；≤ 0.75 px 留意；> 0.75 px 明显。此定义不同于 Imatest area CA，不能套用其分级。',
    prerequisites='RGB 与同位置 G 特征可靠匹配；整卡 / 点阵为二维，单斜边只测法向投影，不能代表完整二维位移。',
    action='查看位移矢量与彩边，比较不同场位；检查扫描 RGB 错行、镜头横向色差和配准质量。',
    mode='low', unit='px', bands=(.25,.75), absolute=True, sources=('ca','local'))
add('registration_rms_px edge_fit_rms_px projective_residual_rms_px radial_fit_rms_px',
    reference='理想 0 px；拟合残差越小越好。',
    criteria='MUTEX 建议：RMS ≤ 0.25 px 较小；≤ 0.75 px 留意；> 0.75 px 建议复查。低残差不能证明无畸变或图卡标定正确。',
    prerequisites='充分分布的有效标记 / 斜边，结合图案周期、ROI 大小和控制点覆盖范围。',
    action='核对模板、镜像、四点配准与图案定位；剔除错误标记并重新拍摄。',
    mode='low', unit='px', bands=(.25,.75), sources=('geometry','local'))
add('resolution_anisotropy star_anisotropy', reference='理想 max / min = 1。',
    criteria='MUTEX 建议：比值 ≤ 1.10 较一致；≤ 1.25 留意；> 1.25 方向差异较大。不能单独确诊像散。',
    prerequisites='各方向阈值分辨率均有效；同图案、同频率范围和物理尺度。',
    action='同时查看各方向曲线，检查运动、扫描方向、图卡印刷和配准，再用焦位序列区分原因。',
    mode='low', unit='ratio', bands=(1.1,1.25), sources=('sharpness','local'))
add('overshoot_pct undershoot_pct', reference='无光晕参考 0%。',
    criteria='MUTEX 建议：≤ 5% 较小；≤ 10% 留意；> 10% 光晕较明显。不是镜头清晰度合格线。',
    prerequisites='有效且未剪切的斜边、已知输入曲线；相对于阶跃高度计算。',
    action='查看 ESF / SFR；减少锐化并比较 RAW 或未处理扫描。', mode='low', unit='%', bands=(5.,10.),
    sources=('sharpening','local'))
add('sharpening_halo_pct',reference='无可检出光晕参考 0%；同时检查 halo_noise_floor_pct 检测下限。',
    criteria='MUTEX 工程提示：≤ 2% 未见明显光晕；2–5% 留意；> 5% 光晕明显。数值是过冲 / 下冲幅度，不是锐化概率或后期处理强度。',
    prerequisites='有效斜边或至少两个低频 USAF 元素；连续采样超过噪声检查。剪切可遮蔽光晕，未知曲线只提供输入域结果。',
    action='查看明暗边缘和 CTF / SFR，比较关闭锐化后的 RAW / 扫描；光学振铃和图卡也可能产生相同迹象。',
    mode='low',unit='%',bands=(2.,5.),sources=('sharpening','local'))
add('clipping_fraction', reference='定量测量期望 0；比例单位为 0–1。',
    criteria='按本次 maximum_clip_fraction 排除阈值检查；非零提示信号丢失，不能按图卡黑白面积给整机画质打分。',
    prerequisites='原测量 ROI 的黑白剪切阈值；保留剪切模式只能相对比较。',
    action='检查原像素直方图、曝光和扫描自动对比度；必要时降低曝光 / 关闭自动处理后重拍。',
    mode='clipping', unit='ratio')
add('wedge_alias_fraction', reference='预期分离异常比例 0。',
    criteria='MUTEX 建议：≤ 0.05 较少；≤ 0.20 留意；> 0.20 异常样本较多。不是整幅图像混叠百分比。',
    prerequisites='预期条数、频率和配准正确；噪声、误配及图卡品质也会造成异常。',
    action='查看楔形分离与基频一致性曲线，复核异常频段。', mode='low', unit='ratio', bands=(.05,.20))
add('contrast_at_frequency', reference='非负信号的 Michelson 对比度理论为 0–1。',
    criteria='相同图案、物理频率、输入处理下越高越好；频率 / 图案不同不混合评级。没有通用合格值。',
    prerequisites='确认指定测试频率和黑白信号；未知输入曲线时仅为编码信号对比度。',
    action='比较相同频率的焦位序列；需要分辨率时使用多频率曲线。', mode='target', unit='ratio', sources=('sharpness','local'))
add('mtf_nyquist', reference='在 0.5 cy/px 处取响应；没有通用最佳响应值。',
    criteria='高响应可能同时来自高频传递、锐化或混叠，不能简单判越高越好。',
    prerequisites='有效斜边 SFR 和输入线性化；结合完整曲线。', action='查看奈奎斯特附近曲线、过冲和混叠提示。',
    mode='target', unit='ratio', sources=('sharpness',))
add('alignment_gain_pct', reference='0% 无变化；正值提高，负值下降。',
    criteria='MUTEX 将 |变化| ≤ 2% 视为小幅变化提示；超过此值只描述增减，未实测重复性时不称显著改善。',
    prerequisites='同位置、同阈值的对齐前后分辨率均有效；插值会改变响应。',
    action='核对 RGB 矢量和前后曲线；对齐不能补回离焦细节。', mode='change', unit='%')
add('sampling_dpi_x sampling_dpi_y', reference='与扫描 / 翻拍要求的采样 PPI 比较，未设目标时不评价高低。',
    criteria='几何 PPI 描述采样密度，数值大不等于实际分辨率高；与等效分辨率 DPI 分开。',
    prerequisites='物理尺寸和图卡倍率已标定，配准有效。', action='输入所需 PPI 目标；结合实际分辨率与扫描重采样检查。',
    mode='target', unit='PPI', sources=('sharpness','local'))
add('mean', reference='无通用最佳均值；以曝光、白 / 灰参考和动态范围为目标。',
    criteria='当前归一化信号尺度下报告均值。亮度越大不一定越好。',
    prerequisites='均匀 ROI、正确黑电平与输入曲线；不同曝光不能直接比较。',
    action='检查直方图、剪切与已知灰块；需要时设置允许区间。', unit='signal')
add('spatial_snr_db', reference='20 / 30 / 40 dB 对应 S/N 约 10 / 31.6 / 100。',
    criteria='MUTEX 建议：≥ 40 dB 空间波动较小；≥ 30 dB 留意；< 30 dB 较大。同曝光越高越好。',
    prerequisites='真正均匀的测量块；单帧空间噪声包含照明和图卡纹理，不等于时间噪声或完整 ISO 15739 测量。',
    action='用重复暗 / 平场区分时间噪声、固定图样与照明不均。', mode='high', unit='dB', bands=(40.,30.), sources=('noise','local'))
add('edge_noise_rms', reference='同曝光、同信号尺度下越低越好；无通用 RMS 合格线。',
    criteria='斜边两侧空间噪声含图卡纹理；没有基准时只报告数值。',
    prerequisites='平坦边缘两侧、已知信号尺度和相同曝光。', action='补拍均匀场和重复帧，对比噪声谱。', unit='signal', sources=('noise','local'))
add('delta_e_2000', reference='理想 ΔE00 = 0。',
    criteria='MUTEX 建议：≤ 1 接近参考；≤ 3 留意；> 3 偏差较大。不是 ISO 合格线或对所有观察条件的可见性承诺。',
    prerequisites='参考 Lab、白点、色彩空间与色适应条件可靠；处理链须明确。',
    action='检查照明、白平衡、图卡参考和 CCM；用独立验证色块复测。', mode='low', unit='ΔE00', bands=(1.,3.), sources=('color','local'))
add('delta_e_76 white_balance_delta_ab', reference='理想色度距离 0。',
    criteria='越小越接近参考；ΔE76 / Δab 与 ΔE00 定义不同，不套用 ΔE00 分档。未设目标只报告距离。',
    prerequisites='可靠 Lab 参考与白点；白平衡指标仅用于中性色块。', action='检查白点、照明和中性灰；按用途设置允许色度距离。',
    unit='Lab distance', sources=('color','local'))
add('relative_illumination_min_pct corner_illumination_pct', reference='相对于中心理想 100%；线性光 50% 对应下降 1 EV。',
    criteria='MUTEX 扫描翻拍建议：相对中心偏差 ≤ 10% 较一致；≤ 25% 留意；> 25% 较大。高于中心也算不均匀。',
    prerequisites='同一均匀场且中心有效；未知输入曲线时仅评价编码信号比例。',
    action='检查照明、镜头暗角、扫描灯和靶材；分别检查每个角。', mode='distance100', unit='%', bands=(10.,25.), sources=('flat','local'))
add('corner_falloff_ev', reference='理想 0 EV；1 EV 为线性光下降到 50%。',
    criteria='MUTEX 建议：|衰减| ≤ 0.152 EV（约 10%）较小；≤ 0.415 EV（约 25%）留意；更大建议检查。',
    prerequisites='已线性化、中心和四角均匀场；负值表示角落更亮。', action='检查照明与暗角，勿把未知编码曲线当线性光。',
    mode='low', unit='EV', absolute=True, bands=(.152,.415), sources=('flat','local'))
add('illumination_nonuniformity_pct', reference='理想极差 / 中心 = 0%。',
    criteria='MUTEX 建议：≤ 10% 较小；≤ 25% 留意；> 25% 不均较大。',
    prerequisites='均匀场、网格和采样范围一致；同时包含照明和靶材影响。', action='查看照度网格并排查光源、靶材和暗角。',
    mode='low', unit='%', bands=(10.,25.), sources=('flat','local'))
add('color_shading_r_g_pct color_shading_b_g_pct', reference='RGB 比值的变异系数理想 0%。',
    criteria='MUTEX 建议：≤ 1% 较小；≤ 3% 留意；> 3% 色彩不均较明显。',
    prerequisites='中性均匀场，暗部已排除；照明和靶材本身色差需控制。', action='查看 RGB 比值分布，核对照明和镜头 / 传感器色偏。',
    mode='low', unit='%', bands=(1.,3.), sources=('flat','local'))
add('hot_pixel_count dead_pixel_count blemish_count', reference='参考 0 个候选；单帧候选不能认定永久缺陷。',
    criteria='0 仅表示当前阈值下未发现；> 0 提醒复测。比较需相同 ROI 面积、阈值、曝光、ISO 与温度。',
    prerequisites='暗 / 均匀场；排除图卡纹理、灰尘和照明变化。', action='重复暗平场并检查固定像素坐标，确认持久性。',
    mode='candidates', unit='count', sources=('flat','local'))
add('oecf_gamma', reference='线性编码斜率 1；简单幂律 sRGB 近似约 0.45，完整 sRGB 是分段函数。',
    criteria='与声明的编码曲线比较；不同 Gamma 约定不可混用，未设目标不给合格结论。',
    prerequisites='至少四级未剪切单调灰阶及参考曝光；本指标拟合原始编码信号。', action='查看 OECF 曲线和残差，用参考曝光导出线性化表。',
    unit='ratio', sources=('oecf',))
for snr, db in [(1,'0'),(2,'6.02'),(10,'20'),(20,'26.02')]:
    add(f'dynamic_range_snr{snr}_stops', reference=f'实测曝光跨度内场景参考 SNR ≥ {snr}（{db} dB）。',
        criteria='同方法下档数越多越好；无通用优秀档数。未跨过噪声阈值只给下界，不外推。SNR 20 是本项目自选较严阈值。',
        prerequisites='透射图卡实测密度、场景参考 SNR 和足够曝光跨度；单帧空间波动会影响结果。',
        action='使用更大密度范围的透射阶梯，检查曝光和最暗几级，必要时多帧复测。',
        mode='target', unit='stops', sources=('dr','local'))
add('radial_distortion_max_pct', reference='无径向位移参考 0%；保留桶形 / 枕形符号。',
    criteria='MUTEX 扫描翻拍建议：|位移| ≤ 0.1% 较小；≤ 0.5% 留意；> 0.5% 较明显。仅涵盖控制点覆盖范围。',
    prerequisites='控制点充分分布且图卡几何可靠；固定中心模型不等于完整相机标定。', action='查看残差和控制点覆盖，使用多视图标定作进一步校正。',
    mode='low', unit='%', bands=(.1,.5), absolute=True, sources=('geometry','local'))
add('color_moire_pct', reference='中性图案高频色差 RMS 理想 0%。',
    criteria='同图案、频段和尺度下越低越好；项目工程指标，无通用阈值，不等同 CPIQ 测量。',
    prerequisites='中性图案、相同处理链；排除彩色靶材与照明色差。', action='检查高频彩纹及去马赛克 / 锐化，比较 RAW 与处理输出。', unit='%', sources=('sharpness','local'))
add('veiling_glare_pct', reference='真实暗陷阱相对明亮参考的比值理想 0%。',
    criteria='同照明几何下越低越好；ISO 18844 不规定目标值或允许范围，本项目比值也不是完整标准方法。',
    prerequisites='真实暗陷阱、黑电平和亮参考；普通印刷黑块不能替代光阱。', action='检查遮光、光源位置和黑电平，用同配置基准或自定义上限评价。',
    unit='%', sources=('glare','local'))
add('outer_ring_radius_px', reference='与模板标称半径、倍率或已知基准比较。',
    criteria='尺寸本身无高低优劣；缺少目标只报告实测半径。', prerequisites='声明中心和完整圆环边界，物理尺寸需标定。',
    action='设置标称半径允许区间，核对圆环中心和图卡倍率。', unit='px')
add('encircled_r80_px', reference='同点源尺寸、倍率、波长及窗口下半径越小，能量越集中。',
    criteria='无通用像素合格线；有限点源和背景扣除影响结果。缺少光圈、波长及像元尺寸时不计算衍射合格线。',
    prerequisites='未剪切点像、充分积分窗口、已知背景和点源大小。', action='与同条件基准或自定义上限比较，检查积分窗口。',
    unit='px', sources=('sharpness','local'))
add('best_focus', reference='最佳焦位坐标本身无高低优劣；参考为被采样包围的稳定峰值。',
    criteria='至少 5 个不同焦位并包围峰值；报告拟合不确定度、有效覆盖和场间跨度，不套用通用高度阈值。',
    prerequisites='同图卡、同分辨率及处理链的焦位序列；机械倾角还需实测轴向高度和图卡物理尺寸。',
    action='峰值靠边、平坦或拟合不稳时扩大范围并加密采样；区分图卡、夹持和光学影响。', mode='focus', unit='focus unit')
add('focus_offset', reference='RGB 相对于 G 的轴向焦位差理想 0。',
    criteria='按共同焦位单位及拟合不确定度解释；未设允许焦深不以固定步数判好坏。单帧无法确定。',
    prerequisites='RGB 与 G 同一区域均有有效且被包围的峰值，使用共同焦位标定。',
    action='查看局部轴向焦差和不确定度；按实际焦深设置允许区间。', mode='focus_offset', unit='focus unit')


def reference_for(key):
    return REFERENCES[key].to_dict(key)


def reference_text(key):
    r = reference_for(key)
    return '\n'.join([f"参考值：{r['reference']}", f"评价标准：{r['criteria']}",
                      f"依据：{r['basis']}", f"适用条件：{r['prerequisites']}", f"建议：{r['action']}"])
