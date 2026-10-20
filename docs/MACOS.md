# macOS 便携版

v0.9.2 提供 Apple Silicon（arm64，M 系列）与 Intel（x86_64）两个独立 ZIP，和 Windows 版放在同一个 Release。要求 macOS 15 或以上。两种架构在对应 GitHub macOS 15 构建机上分别打包和验收，不能在 Windows 上交叉构建后视为已通过 Mac 验收。

## 下载和运行

1. 在「关于本机」查看处理器，选择匹配的 arm64 或 x86_64 包。
2. 完整解压 ZIP；可将 `MUTEX Imatest.app` 拖入「应用程序」，双击启动。应用内已包含 Python、Qt、图像解码库和全部 10 套模板。
3. 第一次可使用「合成示例」检查分析、热力图及报告。自己的 RAW / TIFF 和报告保存在本机，不会自动上传。

该版本使用临时签名（ad-hoc），没有 Apple Developer ID 签名或 Apple 公证。下载的应用可能被 Gatekeeper 拦截；请先核对 Release 的校验值，并按 [Apple 官方说明](https://support.apple.com/102445) 在确认来源后处理系统提示。不要把构建自检通过理解为 Apple 公证通过。

ZIP 根目录的 `template/` 包含全部可分发模板，便于查看和打印；App 内也保留相同的资源供离线加载。三套授权模板为测量定义与栅格参考，不包含原始 SVG / PDF。用户模板、设置和缓存保存在系统用户目录；应用不向自身签名包内写入配置。

## CLI

```bash
"/Applications/MUTEX Imatest.app/Contents/MacOS/MUTEX-CLI" info
"/Applications/MUTEX Imatest.app/Contents/MacOS/MUTEX-CLI" analyze scan.tif --chart chart.json --out results --report
```

CLI 与 GUI 使用同一套测量程序。原精度 TIFF、局部拍摄、RGB、焦位序列、HTML / PDF 和质量说明沿用共同的测量定义。未知输入曲线、未确认尺度及缺失阈值不会因平台改变而自动变为有效。

## 构建与验收

在目标架构的 macOS 15 构建机上运行：

```bash
python3.12 -m venv .venv
.venv/bin/python scripts/prepare_macos_runtime.py
.venv/bin/python -c "import cv2,pytest;cv2.setNumThreads(1);raise SystemExit(pytest.main(['-q','--junitxml=validation/pytest.xml']))"
.venv/bin/python -m PyInstaller --noconfirm MUTEX-macos.spec
.venv/bin/python scripts/package_macos.py
.venv/bin/python scripts/verify_macos_release.py
```

准备脚本核对 LibRaw 0.22.2 和 rawpy 0.27.1 源码的 SHA-256，在两种架构上均从源码编译 RAW 绑定；其余 Python 依赖按 `requirements-macos.txt` 锁定。原始组件源码随完整源码包与 Mac ZIP 提供。构建需要网络和 Homebrew；日常运行不需要。

验收从最终 ZIP 解压后进行，检查可执行权限、架构、App 签名完整性、Cocoa 原生窗口、简易 / 专业模式、中英文 / 主题、全部 10 套模板、加密模板往返、HTML / PDF、uint16 TIFF 压缩和 planar RGB、视频，以及公开 CC0 的 Sony A7R IV 压缩 ARW 与 Canon 5D IV CR2。Mac 未复验的其它设备 / 压缩模式保留独立的兼容性范围；不沿用 Windows 的七份 RAW 记录来声称 Mac 全部通过。

两个 `macos-*-checks.json` 发布附件记录对应架构的最终 ZIP 哈希、Python / LibRaw / libvips 版本、测试数量和实际验收范围。私有原始图卡、用户照片和本地实扫报告不进入发布包或 CI。
