# 图像质量工作台与官方图卡

主窗口 **图像质量 → 图像质量工作台** 提供 13 类任务。**图卡模板 → Imatest / 标准图卡兼容设置** 创建本机模板。全部在本机处理。

## 官方图卡

1. 选择型号和实拍/扫描图像。SFRplus/eSFR ISO 等自动生成斜边候选；完成后用模板编辑器逐个检查。
2. 规则色块填写有效矩形 x,y,w,h（相对整图 0–1）和行列数。SG140 为 10×14，ColorChecker24 为 4×6；选择的是色块区域，不是纸张外框。
3. 导入随卡 CSV/CGATS；默认按编号匹配。确认顺序后才能选择按行匹配；Lab/XYZ 参考白点为 D50/D65。
4. ColorGray-44、DR36+Color、IT8 等提供真实布局 JSON，或先在模板编辑器标记区域。软件不猜密度、色值、楔形频率或星图线对数。
5. 只有实际透射图卡才勾“透射图卡”计算实测曝光范围。实物毫米尺寸另在模板编辑器确认。
6. 选择真实输入曲线后运行；色差要求 sRGB 或适用 CCM。未经标定的 RAW 相机 RGB 只用于取均值训练 CCM，不直接输出 ΔE。

参考 CSV 示例（需替换成自己的实测值，不是官方默认色）：

```csv
id,Lab_L,Lab_a,Lab_b
1,50.0,2.0,-3.0
2,70.0,1.0,2.0
```

灰阶用 `id,density` 或 `id,luminance`。CGATS 支持 SAMPLE_ID、LAB_L/A/B、XYZ_X/Y/Z（0–100）、D_VIS。混合参考允许灰阶行只填密度、彩色行只填 Lab。灰阶 Lab 可从 L* 转相对 Y，转换方式记录在模板。

布局为 Region 数组或带 regions 的对象，例如：

```json
{"regions":[
 {"id":"A1","kind":"color","box":[0.1,0.1,0.06,0.06],"params":{"patch_id":"A1","rgb_space":"sRGB"}},
 {"id":"N1","kind":"step","box":[0.2,0.1,0.06,0.06],"params":{"patch_id":"N1"}},
 {"id":"E1","kind":"edge","box":[0.3,0.3,0.05,0.08]}
]}
```

强透视下 ROI 包围框可能混入邻块，需检查。配置采用实拍图像坐标；不自动推断物理尺度。现有四点/参考配准可复用模板。

## 工作台

左侧每行一个文件并保留顺序；右侧参数为可保存的 JSON。每次生成独立子目录，包含 lab-result.json、离线 report.html，以及适用的 CSV/TIFF/标定文件。

| 任务 | 输入与主要参数 | 结果与边界 |
|---|---|---|
| PTC | dark_count 张暗场，再按曝光分组的平场；至少四级、每级 group_size≥2；真实 saturation_dn | 线性单通道 DN TIFF/PNG；RAW 显式 cfa_site:[行,列]，不用去马赛克 RGB；增益、读出、PRNU/DSNU、依饱和 DN 估计满阱/DR |
| 暗平场 | 依次暗场、平场、待校正图，至少两暗两平 | gain/offset/valid NPZ、浮点校正 TIFF；无响应像素结合掩码 |
| CCM | 含色块均值/参考的 result.json，或 measured_rgb/reference_lab 数组 | color-matrix.json；主窗口菜单可应用/清除；训练误差需独立验证 |
| OECF | 含至少四级单调灰阶的 result.json、channel | oecf.json 供主窗口输入曲线使用；范围外钳位，不恢复剪切 |
| 镜头标定 | 至少五种姿态、rows/cols、实测 square_mm、pattern | OpenCV 内参/畸变/FOV/逐视图误差；单视图工程系数不可混用 |
| 去畸变 | 图像和 calibration 文件 | 同分辨率的浮点重采样 TIFF |
| SSIM/PSNR | 顺序为参考图、被测图；原像素 roi | 同尺寸同尺度已对齐；不隐式配准。完全相同以 identical=true / PSNR=null 表示无限大 |
| 视频 | 一个视频、可选 roi、every/max_frames、step_time、tolerance/stable_duration | AE/AF 需真实阶跃；AWB 需中性灰 ROI；恒定容器帧率时间轴，8-bit 解码 |
| 重复帧 | 至少三帧、可选实际 times_seconds | 未填时间戳时使用声明的 interval_seconds；不冒称实拍时间 |
| 采集 | source 为视频；摄像头须显式 camera_index | 有界 count、可取消，未做摄像头实机验收 |
| 仿真 | 线性参考、blur_sigma_px、full_well_e、read_noise_e、prnu_pct、gamma/bits/seed | 可复现的独立模型；非完整相机光谱/CFA 仿真 |
| 锐度排名 | 多图、相同 roi/channel | 按有效 MTF50 排名，无有效边缘保留相对评分并排末尾 |
| 测试计划 | 计划 JSON | 逐条判定、SQLite 历史；缺失/无效不算通过 |

## 测试计划示例

路径用绝对路径：

```json
{"version":1,"name":"镜头检查","tests":[{
 "name":"清晰度","image":"D:/lab/photo.tif","chart":"D:/lab/chart.json",
 "config":{"transfer":"linear","channels":"G"},
 "limits":[{"metric":"mtf50","channel":"G","min":0.15,"max":0.5,"minimum_count":5,"aggregation":"all","require_all_valid":true}]
}]}
```

可用 result 替代 image/chart 判定已有结果。规则支持 region_ids、kinds、minimum_confidence 和可选 unit 严格核对；缺失、无效、数量不足、越限均 fail，异常为 error。图卡只给出下界时，可以证明已达到不高于该下界的最低要求，不能据此证明满足上限。计划哈希和源指纹写入 SQLite；CLI 计划未通过退出 2，运行错误退出 1。

## CLI

```powershell
.venv\Scripts\python.exe -m mutex_imatest charts
.venv\Scripts\python.exe -m mutex_imatest analyze photo.tif --profile sfrplus --channels RGB --transfer srgb --out output --report --report-format html
.venv\Scripts\python.exe -m mutex_imatest chart-prepare card.tif --profile colorchecker24 --reference batch.csv --ref-white D50 --profile-box 0.1 0.2 0.7 0.5 --out my-card.json
.venv\Scripts\python.exe -m mutex_imatest chart-prepare dr36.tif --profile dr36 --layout layout.json --reference density.csv --transmissive --out dr36.json
.venv\Scripts\python.exe -m mutex_imatest lab iq-task.json --out output/iq-run
.venv\Scripts\python.exe -m mutex_imatest test-db output/iq-run/test-history.sqlite
```

便携版用 MUTEX-CLI.exe 替换 Python 命令。完整剩余差距与验收见 [对照调研](IMATEST_GAP_ANALYSIS.md)。
