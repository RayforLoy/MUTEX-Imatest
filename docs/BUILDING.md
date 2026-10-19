# 开发、构建与发布

Windows x64 / Python 3.12。发布包为独立的 PyInstaller 文件夹，GUI 和命令行程序共享 `_internal`；须完整解压，不要只复制 EXE。

## 源码安装

在仓库根目录执行：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.venv\Scripts\python.exe scripts\upgrade_libraw.py
.venv\Scripts\python.exe -m mutex_imatest gui
```

`upgrade_libraw.py` 从 LibRaw 官方下载 0.22.2 源码/Windows 发行包，核对 rawpy 引用的 C++ 符号后替换本虚拟环境内的 DLL。重装 rawpy 后需要重跑。源码 Release 附带同一原始 ZIP；Git 仓库通过此脚本获取，避免跟踪第三方编译产物。许可证、源地址和第三方通知位于 `licenses/` 和 `THIRD_PARTY_NOTICES.md`。

## 检查与打包

```powershell
.venv\Scripts\python.exe -m pytest --junitxml=validation/pytest.xml
.venv\Scripts\python.exe scripts\build_iq_release.py
& '.\dist\MUTEX Imatest\MUTEX-CLI.exe' selftest --out validation/packaged-selftest-final
.venv\Scripts\python.exe scripts\release.py --zip
```

GUI 自检使用合成 48-bit TIFF，检查后台进程、焦位分析、HTML/PDF、PDF 重渲染、加密模板、评价界面与工作台。打包脚本要求 pytest 和当前 EXE 自检通过，再生成 Windows ZIP、源码 ZIP、SHA256SUMS.txt 与体积清单。

首次运行自检和 pytest 会在 `validation/`、系统临时目录生成数据。这些可重建数据不进入 Git。真实 RAW 验证可运行 `scripts/raw_acceptance.py`；官方图像验证脚本会另行下载公开样本到 `samples/private/`，样本不随源码仓库上传。测试支持缺失个人输入时跳过相应样例。

## 体积控制

保留 OpenCV 视频编解码、NumPy/SciPy、Colour Science、LibRaw、libvips、TIFF/imagecodecs、Qt SVG/PDF 和 cryptography。界面使用 QWidget/pyqtgraph 的二维栅格绘制；pyqtgraph 在导入时需要 QtOpenGL/QtOpenGLWidgets 绑定，因此仍保留这两个模块，仅去除未使用的 QML/Quick、虚拟键盘和软件 OpenGL 渲染器。打印模板、说明文档和许可证放在 EXE 同级各一份。历史验收截图和原始测试数据不进入运行包，当前验收摘要可通过 `validation/release-checks.json` 加入。

Windows ZIP 使用标准 DEFLATE 9 级压缩，兼容系统解压；已有 ZIP 直接存储。模板导出的 `.mxtpl` 仍使用快速压缩，其加密方式不受发布压缩设置影响。

若已安装 7-Zip，可额外生成体积更小的 Windows 7z 包；原 ZIP 仍会保留：

```powershell
.venv\Scripts\python.exe scripts\release.py --zip --seven-zip 'C:\Program Files\7-Zip\7z.exe'
```

7z 和 ZIP 包含相同的便携目录。需要全部授权模板时，先完成文末的资产准备并加上 `--require-bundled`；脚本另生成单独模板 ZIP，记录各文件的大小与 SHA-256。

## 文件与发布边界

Git 跟踪源码、测试、构建脚本、文档、许可证与可再分发的 `template/` 图卡。`.venv/`、`build/`、`dist/`、`example/`、`samples/`、`output/`、`validation/`、私有图卡和本机凭据均忽略。原始用户文件和个人结果仅保留本地。发布前确认待提交文件清单与许可证。

GitHub Release 上传 Windows ZIP、完整源码 ZIP、SHA256SUMS.txt 和发布清单；二进制包不提交进 Git 历史。源码 ZIP 包含匹配的 LibRaw 原始发行包。发布使用版本标签，上传后核对大小及 GitHub 返回的 SHA-256。

## 随发布包提供全部模板

公开 `template/` 保留 6 套可打印源图和独立许可。授权随软件发布的三套私有图卡（120、135、星图 + ISO12233）可用 `scripts/build_bundled_templates.py --chart 120.json --chart 135.json --chart 混合图卡.json --out private_assets/bundled_templates` 构建，再使用 `scripts/release.py --zip --require-bundled` 打包。完整发布包共 10 套模板；构建验收依据输入清单检查实际数量。

构建只保留测量定义和 PNG 配准参考，用 `.mxasset` 二进制容器分发；不装入私有 SVG/PDF。容器使用公开应用加载口令，支持离线免输入使用，因此不声称隐藏可测量的几何或栅格数据；用户自行导出的 `.mxtpl` 仍使用用户自己的秘密口令，不受此加载口令影响。模板作品版权与代码 GPL 分开。Git 仓库不含私有作品；完整源码 ZIP、Windows ZIP 和单独模板 ZIP 包含这些可用资产。
