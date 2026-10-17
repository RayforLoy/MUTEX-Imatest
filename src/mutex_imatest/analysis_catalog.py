"""Analysis names shared by the desktop, batch records, and exports."""
METRICS=[('已确认分辨率 · 条纹 / 星图','resolution_limit'),('CTF50 · 多频率 / 星图','ctf50'),
 ('CTF20 · 多频率 / 星图','ctf20'),('CTF10 · 多频率 / 星图','ctf10'),('整卡多频率调焦评分','usaf_focus_score'),
 ('RGB 位移 R−G','ca_r_g_px'),('RGB 位移 B−G','ca_b_g_px'),
 ('RGB 相对 G 位移幅值','rgb_shift_px'),('RGB 相对 G 横向位移','rgb_shift_x_px'),('RGB 相对 G 纵向位移','rgb_shift_y_px'),
 ('对齐后灰度分辨率变化 %','alignment_gain_pct'),('方向分辨率比值','resolution_anisotropy'),
 ('几何采样 PPI · X','sampling_dpi_x'),('几何采样 PPI · Y','sampling_dpi_y'),('配准 RMS','registration_rms_px'),
 ('剪切比例','clipping_fraction'),('MTF50','mtf50'),('MTF50P','mtf50p'),('MTF20','mtf20'),('MTF10','mtf10'),
 ('奈奎斯特频率 SFR 响应','mtf_nyquist'),('斜边亮侧过冲 %','overshoot_pct'),('斜边暗侧下冲 %','undershoot_pct'),('斜边拟合 RMS','edge_fit_rms_px'),
 ('星图方向分辨率比值','star_anisotropy'),('楔形分离异常比例','wedge_alias_fraction'),
 ('固定频率对比度（USAF / 星图）','contrast_at_frequency'),('均匀块均值','mean'),('均匀块 SNR','spatial_snr_db'),
 ('色差 ΔE2000','delta_e_2000'),('几何残差','projective_residual_rms_px'),
 ('最佳焦位地图','best_focus'),('RGB 最佳焦位差 · 相对 G','focus_offset')]
METRIC_LABELS={key:name for name,key in METRICS}
METRIC_DESCRIPTIONS={
 'resolution_limit':'在当前输入和设定阈值下，确认仍能分辨的最高测试频率。USAF 使用多频率条纹及双向较弱结果；二值星图使用环向条纹响应；楔形图还检查预期条数分离和基频一致性。不是几何采样 PPI，也不会外推未测试或分离失败的频率。',
 'ctf50':'条纹或二值星图的对比度响应下降到低频参考值 50% 时的频率。用于比较合焦情况；CTF 是方波响应，不能直接当作正弦 MTF。若曲线未跨过阈值则不填数值。',
 'ctf20':'条纹或二值星图的相对对比度下降到 20% 时的频率。比 CTF50 更关注细小纹理；对噪声、混叠和锐化更敏感，需要结合曲线和质量标志。',
 'ctf10':'条纹或二值星图的相对对比度下降到 10% 时的频率，接近低对比度的分辨极限。未跨过阈值或受混叠影响时不应当作已确认能力。',
 'usaf_focus_score':'把同一 USAF 单元的多频率有效响应合成为调焦评分，兼顾多个频率，避免只看某一个条纹。适合相同输入设置、同一图卡和位置之间的相对比较。',
 'ca_r_g_px':'R 相对于 G 的彩边位移。整卡多频率法估计局部二维位移幅值；斜边法只测垂直于该边缘的分量。单位为原图像素，G 为参考。',
 'ca_b_g_px':'B 相对于 G 的彩边位移。整卡多频率法估计局部二维位移幅值；斜边法只测垂直于该边缘的分量。单位为原图像素，G 为参考。',
 'rgb_shift_px':'R、B 相对于同位置 G 特征的二维位移幅值。用来观察横向色散或扫描 RGB 错位；不能由此推断轴向离焦距离。',
 'rgb_shift_x_px':'R、B 相对于 G 的横向位移，按原始图像坐标，向右为正，单位为像素。改变预览镜像或旋转不会改变这里的测量坐标。',
 'rgb_shift_y_px':'R、B 相对于 G 的纵向位移，按原始图像坐标，向下为正，单位为像素。改变预览镜像或旋转不会改变这里的测量坐标。',
 'alignment_gain_pct':'同一位置把 R、B 对齐到 G 后，合成灰度分辨率相对于对齐前的变化百分比。正值表示改善，负值表示下降；重采样也会影响结果，不能补回离焦细节。',
 'resolution_anisotropy':'同一位置两个条纹方向的分辨率比值，用于观察方向差异。偏离 1 越多，方向不一致越明显；需结合原始双向结果判断原因。',
 'sampling_dpi_x':'通过图卡已知物理尺寸与图像对应关系估算横向几何采样密度，单位 PPI。它描述每英寸采了多少像素，不等于实际分辨率的等效 DPI。',
 'sampling_dpi_y':'通过图卡已知物理尺寸与图像对应关系估算纵向几何采样密度，单位 PPI。它描述每英寸采了多少像素，不等于实际分辨率的等效 DPI。',
 'registration_rms_px':'模板测量区域与图像特征定位之间的均方根误差，单位像素。用于检查配准可靠性；定位误差大时应先核对模板、局部范围和四点配准。',
 'clipping_fraction':'测量区域中落在输入黑端或白端剪切阈值的像素比例。剪切会丢失细节，影响定量响应；保留模式仍会显示警告，不能恢复丢失信号。',
 'mtf50':'斜边空间频率响应下降到低频值 50% 时的频率，常用于比较清晰度。需要合适角度的有效斜边和输入传递曲线；受锐化与拍摄处理影响。',
 'mtf50p':'斜边响应下降到峰值 50% 时的频率。与 MTF50 的低频归一化方式不同，对存在锐化峰的图像可作为补充清晰度指标。',
 'mtf20':'斜边响应下降到低频值 20% 时的频率，反映较细纹理的传递情况。应结合完整 SFR 曲线、噪声和混叠提示查看。',
 'mtf10':'斜边响应下降到低频值 10% 时的频率，接近低对比度分辨极限。对噪声、锐化和混叠敏感，不能脱离质量检查单独判断。',
 'contrast_at_frequency':'在指定测试频率处测量条纹或星图的黑白对比度。适合固定频率的相对调焦；不同频率或不同图案的数值不能直接混作同一分辨率。',
 'mean':'均匀测量块的平均信号值，可观察亮度、通道差异和曝光均匀性。需要模板配置均匀块；图案、渐变或阴影会影响解释。',
 'spatial_snr_db':'均匀块平均信号与空间波动的比值，以 dB 表示。包含噪声与不均匀性，不能当作多帧时间噪声测量；需要合适的均匀区域。',
 'delta_e_2000':'已知参考色块与实测颜色之间的 CIEDE2000 色差。数值越小越接近参考；必须提供有效的参考色和颜色转换条件。',
 'projective_residual_rms_px':'用投影几何关系拟合标记后，标记位置残差的均方根值。用于发现几何偏离和定位异常；不能把单个残差指标直接解释为镜头畸变百分比。',
 'best_focus':'由多张不同焦位图像拟合每个区域的最佳焦位，查看倾斜和场曲趋势。需要至少 5 个不同焦位并包围峰值；单张图像不能确定轴向最佳焦位。',
 'focus_offset':'多帧焦位序列中，R 或 B 的最佳焦位相对于 G 的差值，用于比较轴向色差。需要各通道的有效峰值与共同焦位标定，不是单帧彩边位移。',
 'star_anisotropy':'西门子星图八个 45° 扇区的阈值分辨率最大值 / 最小值，比值不小于 1，越接近 1 表示方向越一致。任一扇区未测得则不填值；配准、图案品质和打印限制仍会影响结果，不能据此单独确诊像散。',
 'mtf_nyquist':'斜边空间频率响应在 0.5 cycles/pixel（奈奎斯特频率）处的值，显示采样极限附近的响应。高响应也可能伴随锐化或混叠，需结合完整曲线。',
 'overshoot_pct':'斜边亮侧相对于阶跃高度的过冲百分比，用于检查锐化光晕。需要合适的输入曲线和未剪切边缘，不直接代表镜头分辨能力。',
 'undershoot_pct':'斜边暗侧相对于阶跃高度的下冲百分比，用于检查锐化暗晕。需要合适的输入曲线和未剪切边缘，不直接代表镜头分辨能力。',
 'edge_fit_rms_px':'斜边拟合位置的均方根残差，单位像素。数值增大可能来自弯曲、纹理、噪声或误选图案，可用于检查斜边测量的几何质量。',
 'wedge_alias_fraction':'楔形图的频率样本中，预期条数分离检查或基频一致性检查失败的比例，范围 0–1。较低表示较少分离异常，但也受误配、噪声和打印限制影响；不是整体画质评分，异常段曲线仍保留供检查。',
}
EXTENDED_METRICS={
 'mtf_area':('MTF 曲线面积',{'edge'},'0–Nyquist 的归一化 SFR 面积，用于同条件锐度比较；未加人眼 CSF 权重。'),
 'information_capacity_1d':('一维信息容量 · 工程模型',{'edge'},'由斜边 MTF、平坦两侧 NPS 和均匀输入信号模型积分，单位 bits/px。不是商业 Imatest C4/Cmax，也不包含二维容量。'),
 'edge_noise_rms':('斜边两侧噪声 RMS',{'edge'},'原像素边缘两侧的空间噪声谱积分；包含图卡纹理和处理影响，不能直接当作传感器读出噪声。'),
 'relative_illumination_min_pct':('最低相对照度 %',{'flat'},'均匀场网格最暗格相对于中心的平均信号百分比。输入曲线未知时仅是信号比例。'),
 'corner_illumination_pct':('四角相对照度 %',{'flat'},'均匀场四角取样格相对于中心的平均信号百分比；需确保图卡与照明均匀，且没有其他图案进入区域。'),
 'corner_falloff_ev':('四角亮度衰减 EV',{'flat'},'已知传递曲线的线性光下，用 -log2(四角/中心) 表示亮度衰减。'),
 'illumination_nonuniformity_pct':('照度不均匀性 %',{'flat'},'均匀场网格最大与最小均值之差，占中心信号的百分比；该值包含镜头、照明和图卡的不均匀贡献。'),
 'hot_pixel_count':('候选亮坏点数',{'flat'},'超过局部背景及噪声阈值的亮像素；单帧候选需通过重复暗平场确认。'),
 'dead_pixel_count':('候选暗坏点数',{'flat'},'低于局部背景及噪声阈值的暗像素；须在多张同条件暗平场中复核，单张图不能确认永久坏点。'),
 'blemish_count':('候选污点数',{'flat'},'平滑信号相对大尺度背景偏差超过阈值的连通区域数量；受照明和靶材影响。'),
 'color_shading_r_g_pct':('色彩不均匀性 R/G %',{'flat'},'均匀场内 R/G 比值的变异系数，暗部被排除；只适用于无图案的中性色均匀场和三个有效颜色通道。'),
 'color_shading_b_g_pct':('色彩不均匀性 B/G %',{'flat'},'均匀场内 B/G 比值的变异系数，暗部被排除；只适用于无图案的中性色均匀场和三个有效颜色通道。'),
 'oecf_gamma':('OECF 编码 Gamma',{'tone_summary'},'至少四级未剪切、单调灰阶，在 log 参考曝光与 log 编码信号上拟合斜率。'),
 'dynamic_range_snr1_stops':('动态范围 · SNR ≥ 1',{'tone_summary'},'仅透射图卡：按场景参考噪声计算的连续可用曝光范围；不外推，未跨阈值时标为下界。'),
 'dynamic_range_snr2_stops':('动态范围 · SNR ≥ 2',{'tone_summary'},'仅透射图卡：场景参考 SNR 不低于 2 的连续实测曝光范围；没有跨越噪声阈值时仅为下界，不外推。'),
 'dynamic_range_snr10_stops':('动态范围 · SNR ≥ 10',{'tone_summary'},'仅透射图卡：场景参考 SNR 不低于 10 的连续实测曝光范围；没有跨越噪声阈值时仅为下界，不外推。'),
 'dynamic_range_snr20_stops':('动态范围 · SNR ≥ 20',{'tone_summary'},'仅透射图卡：场景参考 SNR 不低于 20 的连续实测曝光范围；没有跨越噪声阈值时仅为下界，不外推。'),
 'delta_e_76':('色差 ΔE76',{'color'},'参考白点明确为 D50 或 D65；D50 参考经 Bradford 适应后与线性 sRGB D65 比较。'),
 'white_balance_delta_ab':('中性灰白平衡误差',{'color'},'仅参考色度接近中性的色块，报告实测与参考 a/b 的距离；需要已知输入色空间、参考白点及有效灰块。'),
 'radial_distortion_max_pct':('径向畸变最大值 %',{'grid','dot'},'固定畸变中心下的投影平面 + r²/r⁴ 模型；只报告控制点覆盖内，系数不能直接替代相机标定。'),
 'radial_fit_rms_px':('径向模型残差 RMS',{'grid','dot'},'投影平面和径向畸变联合拟合的像素 RMS，包含图卡与定位误差；需有覆盖足够画面的完整控制点。'),
 'dot_ca_r_g_rms_px':('点阵二维色差 R−G RMS',{'dot'},'逐点源像素质心的 R−G 二维位移 RMS，受点阵色度和反光影响。'),
 'dot_ca_b_g_rms_px':('点阵二维色差 B−G RMS',{'dot'},'逐点源像素质心的 B−G 二维位移 RMS，包含点阵颜色与反光影响；需要完整点阵和三个原始颜色通道。'),
 'texture_mtf50':('参考纹理响应 50%',{'texture'},'同尺度线性参考的径向 PSD 幅值比，可扣除噪声参考；不是 ISO texture MTF 认证。'),
 'texture_mtf10':('参考纹理响应 10%',{'texture'},'同尺度线性参考的径向 PSD 幅值比降到 10% 的频率；需同尺寸参考，噪声和锐化也影响该工程指标。'),
 'log_mtf50':('对数频率 MTF50',{'logf'},'声明正弦图案的原像素起止频率、方向和参考调制度后，用局部正弦回归测量。'),
 'log_mtf10':('对数频率 MTF10',{'logf'},'声明频率几何与参考调制度的正弦对数频率图案响应降至参考的 10%；未跨越阈值时保留空值。'),
 'color_moire_pct':('色彩摩尔纹高频 RMS %',{'star','wedge','logf'},'中性图案的高频通道色差 RMS，占均值百分比；工程指标，不等同 CPIQ 标准指标。'),
 'veiling_glare_pct':('遮光区眩光比值 %',{'flare'},'真实暗陷阱扣黑电平后的均值 / 明亮参考均值；不是 ISO18844 或 IEEE2020 完整方法认证。'),
 'outer_ring_radius_px':('最外同心圆边界半径',{'rings'},'围绕声明中心的径向轮廓边界半径；完整圆环才参与。缺少实际角度参考时不能从像素半径推导视场。'),
 'encircled_r80_px':('点像 80% 包围能量半径',{'point'},'扣除背景的点像 80% 包围能量半径，受有限点源大小影响；ROI 需要覆盖足够背景和完整能量分布。'),
}
for key,(name,kinds,description) in EXTENDED_METRICS.items():
    METRICS.append((name,key));METRIC_LABELS[key]=name;METRIC_DESCRIPTIONS[key]=description
SEQUENCE_METRICS={'best_focus','focus_offset'}
IMAGE_METRICS=set(METRIC_LABELS)-SEQUENCE_METRICS
RGB_METRICS={'ca_r_g_px','ca_b_g_px','rgb_shift_px','rgb_shift_x_px','rgb_shift_y_px','alignment_gain_pct'}
RGB_METRICS.update({'dot_ca_r_g_rms_px','dot_ca_b_g_rms_px','color_shading_r_g_pct','color_shading_b_g_pct','color_moire_pct'})


def required_channels(channels,metrics):
    metrics=set(metrics or [])
    if 'alignment_gain_pct' in metrics:return 'RGBY'
    if metrics & RGB_METRICS and channels not in {'RGB','RGBY'}:
        return 'RGBY' if channels=='Y' else 'RGB'
    return channels
