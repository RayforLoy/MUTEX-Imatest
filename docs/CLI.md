# CLI

v0.6.0 新增 `charts`、`chart-prepare`、`lab`、`test-db` 和 `analyze --profile`。图卡参考、多帧和测试计划示例见 [图像质量工作台](IQ_WORKBENCH.md)。

开发环境激活 .venv 后使用 python -m mutex_imatest；便携版使用 MUTEX-CLI.exe。同目录的 MUTEX Imatest.exe 用于双击桌面界面。

    python -m mutex_imatest info
    python -m mutex_imatest gui --demo
    python -m mutex_imatest demo --out samples/demo --analyze

分析一张或多张：

    python -m mutex_imatest analyze photo.arw scan.tiff --chart my-chart.json --out output --channels RGB --transfer linear --report

`--report` 默认同时导出 `report.html` 与 `report.pdf`，并保留 CSV/JSON/PNG。可用 `--report-format html` 或 `--report-format pdf` 单独选择；HTML 内嵌热力图，不依赖网络或同目录图片。

整卡多频率 / RGB 与两种灰度（使用 GUI 保存的 SVG 模板或已经含全频率 ROI 的模板）：

    python -m mutex_imatest analyze scan.tif --chart my-chart.json --whole-card --config config.json --out output --report

相对调焦配置可设 `reject_clipping: false`，保留剪切警告；`transfer` 必须按真实输出设定，未知则保留 unknown。`--whole-card` 展开 SVG 的全部 USAF 频率并使用 RGBY 五通道、双向和原像素配准。详见 WHOLE_CARD.md。本机早期样本研究脚本不进入公开分发，当前整卡分析直接运行产品的统一引擎。

已有结果无需重新测量即可重新导出，或导出原尺寸灰度：

    python -m mutex_imatest report output/scan/result.json --preview output/scan/preview.png --out output/reports
    python -m mutex_imatest gray-export output/scan/result.json --out output/gray

report 的 `--format html/pdf/both` 选择报告格式。多频率报告保存五通道 / 双向完整曲线、分辨率、RGB 位移及质量信息。gray-export 导出的 Y_align.tif 必须结合有效像素掩码使用。

RAW 不受 transfer 的显示/成品曲线设置影响，固定输出线性 camera RGB。TIFF 的 transfer 需要按真实输出设置。无模板时 --auto 可产生待检查斜边候选，不能据此声称所有候选已正确匹配。

    python -m mutex_imatest analyze scan.tif --auto --out output

配置文件使用 AnalysisConfig JSON；--config 后可用 --channels、--transfer、--memory-mb 覆盖。完整字段见 config.py，数据类型与可选值由 validate 检查。物方标定在图卡 JSON，不能仅用扫描 DPI 替代。--z 与 --z-unit 可设置当前文件高度，未指定则读取 _z0.25mm 等文件名。

    python -m mutex_imatest focus "samples/demo/results/*.json" --metric mtf50 --channel G --objective balanced --out output/focus.json

整卡五通道最佳焦位与轴向 RGB 焦差：

    python -m mutex_imatest focus "output/series/*/result.json" --metric usaf_focus_score --channel ALL --objective balanced --out output/focus-rgb.json

只有焦位数值确实是图卡/载台实测轴向高度时，才加 --height-calibrated。镜头马达参数即使标为 mm，也不直接换算成机械倾角。

    python -m mutex_imatest watch D:/capture --chart my-chart.json --out output --config config.json

watch --once 在现有匹配文件稳定处理后退出；没有文件时持续等待。Ctrl+C 停止。监视为读文件，不向硬件发送采集命令。

重复暗/平场：

    python -m mutex_imatest temporal flat1.tiff flat2.tiff flat3.tiff --roi 500 500 256 256 --channel G --transfer linear --out output/noise.json

ROI 单位为源文件原生像素 x y width height，帧必须同尺寸、同通道和受控照明/曝光。该近似 PRNU 同时含图卡/照明不均，不能代替完整 EMVA / PTC 测量。

验证与构建：

    python -m pytest
    python scripts/gui_smoke.py --headless
    python scripts/benchmark.py --sizes 100 300 800 --compressed
    python scripts/raw_acceptance.py --cold
    python scripts/licenses.py
    python scripts/upgrade_libraw.py
    python -m PyInstaller --noconfirm MUTEX.spec

upgrade_libraw 下载官方 0.22.2 DLL，验证 rawpy 用到的全部 32 个导出符号后替换当前项目环境的 raw_r.dll。保留原始 DLL 和官方源码包；重新安装 rawpy 会还原到 wheel 自带版本，打包前需重新运行并完成 RAW 回归。版本 / 哈希记录在 validation/libraw-upgrade.json。


## 多项分析

一次测量生成多个所选结果：

    MUTEX-CLI.exe analyze input.tif --chart chart.json --channels RGBY --metrics resolution_limit ctf50 ctf20 ca_r_g_px ca_b_g_px alignment_gain_pct --out output --report

也可在配置 JSON 中填写 analysis_metrics 数组。省略时保留原有完整测量流程；显式空数组会提示先选择项目。依赖 RGB / RGBY 的项目自动补齐所需通道。所选报告为 report.html/pdf，完整曲线与详细报告为 detail-report.html/pdf，汇总为 analysis-results.json/csv。

## 混合图卡与局部照片

使用已经保存的私有模板或根目录公开模板定义。配置中设置 `registration: "auto_chart"`，以参考特征确定实际可见区域，不使用整幅假设。示例：

    MUTEX-CLI.exe analyze photo.jpg --chart template/definitions/generic-iso12233-style.json --config mixed-config.json --channels RGBY --metrics mtf50 mtf20 ctf50 resolution_limit ca_r_g_px ca_b_g_px overshoot_pct wedge_alias_fraction --out output/mixed --report

准确的定义文件名以 template/manifest.json 为准；可用项目由模板实际 ROI 决定。更多参数、检测与物理单位边界见 [混合图卡说明](MIXED_TARGETS.md)。桌面导出对话框提供自定义文件名、标题和附件，CLI 保持可复现的固定 report.* 命名，每张输入单独放在输出文件夹中。
