"""Template capability and prerequisites, separate from measurement quality."""
from dataclasses import asdict
from .resolution import MULTI_METRICS,PAIRED_SHIFT_METRICS


def metric_availability(chart,result=None,focus=None,configured_channels='G',planning=False):
    regions=result.template.get('regions',[]) if result is not None else [asdict(r) for r in chart.regions]
    regions=[r for r in regions if r.get('enabled',True)]
    kinds={r['kind'] for r in regions}
    full=any(r['kind']=='usaf' and r.get('params',{}).get('multi_frequency') for r in regions)
    channels={m.channel for m in result.measurements} if result is not None else set(['R','G','B','Y','Y_align'] if configured_channels=='RGBY' else ['R','G','B'] if configured_channels=='RGB' else [configured_channels])
    if planning:channels={'R','G','B','Y','Y_align'}
    calibrated=bool(result.template.get('calibrated') and result.template.get('physical_size_mm')) if result is not None else bool(chart.calibrated and chart.physical_size_mm)
    available={};
    def add(keys):
        for key in keys:available[key]=''
    if kinds:add(['clipping_fraction'])
    if 'edge' in kinds:add(['mtf50','mtf50p','mtf20','mtf10','mtf_nyquist','overshoot_pct','undershoot_pct','edge_fit_rms_px'])
    for r in regions:
        if r['kind']=='star':
            add(['contrast_at_frequency'])
            p=r.get('params',{})
            add(['mtf50','mtf20','mtf10'] if p.get('pattern')=='sinusoidal' and p.get('reference_modulation') is not None else ['ctf50','ctf20','ctf10'])
            add(['resolution_limit','star_anisotropy'])
    if 'wedge' in kinds:add(['ctf50','ctf20','ctf10','resolution_limit','contrast_at_frequency','wedge_alias_fraction'])
    if kinds and any(r.get('params',{}).get('auto_detect') for r in regions):add(['registration_rms_px'])
    if 'usaf' in kinds:add(['contrast_at_frequency'])
    if full:
        add(MULTI_METRICS)
        directions={r.get('params',{}).get('direction','vertical') for r in regions if r['kind']=='usaf'}
        if not {'horizontal','vertical'}<=directions:available['resolution_anisotropy']='需要横竖两个方向的 USAF 测量区域'
        for key in ['sampling_dpi_x','sampling_dpi_y']:
            if not calibrated:available[key]='请先确认图卡实物尺寸并勾选实际尺寸已校准'
        if not {'Y','Y_align'}<=channels:available['alignment_gain_pct']='当前结果未包含两种灰度；选择 RGBY 并重新分析'
        for key in ['rgb_shift_px','rgb_shift_x_px','rgb_shift_y_px']:
            if result is not None and result.image.channels<3:available[key]='源图像不包含三个颜色通道'
    for key,ch in PAIRED_SHIFT_METRICS.items():
        if full or 'edge' in kinds:
            available[key]='' if full or {'R','G','B'}<=channels else '当前结果没有所需 RGB 通道；选择 RGB 或 RGBY 并重新分析'
            if full and result is not None and result.image.channels<3:available[key]='源图像不包含三个颜色通道'
        else:available[key]='需要整卡多频率 USAF 或有效斜边；单个 USAF 三线元素不输出二维通道位移'
    if kinds & {'flat','step'}:add(['mean'])
    if 'flat' in kinds:add(['spatial_snr_db'])
    if 'color' in kinds:
        available['delta_e_2000']='' if any(r['kind']=='color' and 'reference_lab' in r.get('params',{}) and r.get('params',{}).get('rgb_space')=='sRGB' for r in regions) else '需要色块的参考 Lab 值和已知 sRGB 色空间'
        if result is not None and (result.image.is_raw or result.settings.get('transfer')=='unknown'):available['delta_e_2000']='需要已知 sRGB 色空间和输入曲线；原始相机 RGB 不能直接计算色差'
    if 'grid' in kinds:add(['projective_residual_rms_px'])
    from .analysis_catalog import EXTENDED_METRICS
    for key,(_,required,_) in EXTENDED_METRICS.items():
        if kinds & (required-{'tone_summary'}):add([key])
    steps=[r for r in regions if r['kind']=='step' and ('reference_density' in r.get('params',{}) or 'reference_luminance' in r.get('params',{}))]
    if len(steps)>=4:
        add(['oecf_gamma'])
        for key in ['dynamic_range_snr1_stops','dynamic_range_snr2_stops','dynamic_range_snr10_stops','dynamic_range_snr20_stops']:
            available[key]='' if all(r['params'].get('transmissive') for r in steps) else '动态范围需要透射图卡、匹配批次的密度参考及至少四级灰阶'
    if 'texture' in kinds:
        for key in ['texture_mtf50','texture_mtf10']:
            available[key]='' if any(r['kind']=='texture' and r.get('params',{}).get('reference_image') for r in regions) else '需要同尺度、同尺寸的线性纹理参考图及 reference_image 参数'
    if 'color' in kinds:
        for key in ['delta_e_76','white_balance_delta_ab']:available[key]=available.get('delta_e_2000','需要色块参考')
        if result is not None and result.settings.get('ccm_sha256'):
            for key in ['delta_e_2000','delta_e_76','white_balance_delta_ab']:available[key]=''
    if result is not None:
        # Keep supported but failed measurements selectable, exposing their
        # quality flags rather than hiding an unsuccessful experiment.
        for m in result.measurements:
            for key in m.values:
                if key not in available:available[key]=''
        if not full and any(m.metric('registration_rms_px') is not None for m in result.measurements):add(['registration_rms_px'])
    matching_focus=bool(focus and (result is None or result.image.fingerprint in focus.get('image_fingerprints',[])))
    available['best_focus']='' if matching_focus else '需要至少 5 个包围峰值的焦位，并先完成焦位序列拟合'
    available['focus_offset']='' if matching_focus and focus.get('rgb_focus_offsets') else '需要五通道焦位序列拟合（ALL），单张图不能测轴向焦位差'
    return available,full
