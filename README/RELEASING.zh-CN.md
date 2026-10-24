# 如何发布版本

[项目说明](README.zh-CN.md) · [English README](../README.md) · [贡献指南](CONTRIBUTING.zh-CN.md)

本文以正式版 **v0.1.0** 为例。命令均由维护者手动执行；版本同步、构建、整理发布附件、上传 GitHub 是独立步骤。`release_catalog.py` 只整理本地附件，不会上传或发布。

## 1. 确认版本与源码

版本来源是仓库根目录的 `version.json`，本次配置为：

```json
{
  "baseVersion": "0.1.0",
  "internalBuild": 16,
  "channel": "stable"
}
```

- 之后统一使用正式版，`channel` 保持 `stable`；对外显示 `0.1.0`，Git 标签使用 `v0.1.0`。
- `internalBuild` 是安装程序的内部计数，本次 Windows 文件版本为 `0.1.0.16`。它不代表内部测试版，由升级命令自动维护，无需手动修改。

同步版本：

```bash
npm run version:sync
```

这会同步 npm、Cargo、Tauri 及运行组件清单，保持当前 `0.1.0` 不变，不会构建程序。

**本次发布仍使用 `0.1.0`。以后准备下一版时**，运行一次：

```bash
npm run version:bump
```

命令会自动将 `0.1.0` 升至 `0.1.1`，同时维护 Windows 构建计数并同步所有版本文件。以后依次为 `0.1.2`、`0.1.3`，均为正式版；重复执行会再次升级。需要发布 `0.2.0` 或 `1.0.0` 时，再明确修改 `baseVersion` 并运行 `version:sync`。

提交前检查 `git status`，只纳入源代码、语言文件、文档、测试和必要素材。不要提交 `开发缓存/`、`artifacts/`、Python 运行环境、核心 ZIP、依赖、密钥或实例数据。根目录的 `LICENSE`、`THIRD_PARTY_NOTICES.md` 和依赖的许可声明需要保留。

## 2. 确认运行资源

本次随包核心为 **Afterglow 0.4.1**，来源：[kldhsh123/Afterglow](https://github.com/kldhsh123/Afterglow)。开发缓存中的 `Afterglow-0.4.1` 已用于准备本地运行包。

构建前需要存在：

```text
src-tauri/resources/python/python.exe
src-tauri/resources/python/afterglow-runtime.json
src-tauri/resources/packages/afterglow-core-0.4.1-windows-x64.zip
src-tauri/resources/catalog.json
src-tauri/resources/runtime-catalog.json
```

这些二进制资源不会提交 Git，刚克隆仓库时需要另行准备。准备方式见 `python scripts/prepare_windows.py --help`：该脚本需要在 Windows CPython 3.12 x64 中运行，提供已独立核对 SHA-256 的官方嵌入式 Python ZIP 和核心源码路径。它会准备运行环境和依赖，不负责发布桌面版。

核心 ZIP 仅作为安装包和便携版内部资源保留，首次安装或补装直接使用本地包，**不需要单独上传到 GitHub Release**。

已有经过验证的核心运行包、仅替换核心源码且依赖声明不变时，可使用 `scripts/refresh_bundled_core.py --help` 查看资源更新方式；它会检查依赖能否复用，不能复用时需要重新准备运行环境。

## 3. 手动构建 Windows 安装包

目前项目提供的完整官网风格安装包构建流程运行于已配置工具链的 WSL 环境。除 Node.js／npm 外，还需要脚本使用的 Rust、cargo-xwin、LLVM、NSIS 工具链，以及已准备好的运行资源。WebView2 引导程序放在 `开发缓存/工具链/MicrosoftEdgeWebview2Setup.exe`，脚本会检查 Microsoft 签名。

在仓库根目录执行：

```bash
npm ci
bash scripts/build_windows_cross.sh
```

预期产物：

```text
artifacts/Afterglow-0.1.0-windows-x64-portable/
artifacts/Afterglow-0.1.0-windows-x64-setup.exe
artifacts/Afterglow-0.1.0-windows-x64-setup.exe.sha256
artifacts/Afterglow-0.1.0-windows-x64-setup.exe.build.json
```

脚本不运行安装程序。`.exe.build.json` 是本地构建记录，后续生成更新清单时需要保留。

如果同名便携目录或安装包已存在，请先移到备份目录，避免混入旧产物。不要使用已经运行并写入配置、密钥或聊天数据的便携目录制作发布包。`--package-only` 仅用于版本一致、编译产物仍有效的重新打包；升级桌面版本或修改代码后应完整构建。

发布前由维护者在 Windows 上验收安装、首次语言选择与配置、核心启动、聊天与导入、托盘退出、更新及卸载。源码检查通过不能代替这些实际操作。

## 4. 整理发布附件和更新清单

安装包验收通过后执行：

```bash
python3 scripts/release_catalog.py \
  --tag v0.1.0 \
  --output artifacts/release-v0.1.0
```

输出目录需要尚不存在。脚本核对安装包的构建记录及 SHA-256，并生成以下附件：

| 文件 | 用途 |
| --- | --- |
| `Afterglow-0.1.0-windows-x64-setup.exe` | 用户安装及桌面端更新 |
| `Afterglow-0.1.0-windows-x64-setup.exe.sha256` | 安装包校验值 |
| `catalog.json` | 桌面端版本、安装包下载地址及 SHA-256 |
| `PUBLISHING.txt` | 本地上传提示，可不上传 |

**发布用的 `catalog.json` 是此步骤的输出，不是直接复制 `src-tauri/resources/catalog.json` 或 `runtime-catalog.json`。** 源码中的清单用于安装时的内置资源；发布清单还包含 `desktop` 字段，应用才能下载新的桌面安装包。

发布清单保留 `"components": []` 以兼容已有客户端，不提供独立核心 ZIP 的下载地址。无需上传核心 ZIP，也无需在每次桌面发布时重复分发该附件。

整理完成后不要再改动 EXE；如需重新打包，请重新生成构建记录、校验值和发布清单。已有旧版发布附件目录时，请先移到备份位置，再生成新目录，避免误上传旧的核心 ZIP 或清单。

## 5. 上传 GitHub Release

在 [Afterglow-Desktop Releases](https://github.com/kldhsh123/Afterglow-Desktop/releases) 创建发布：

1. 先将此次源代码和同步后的版本文件提交、推送到仓库；标签必须对应实际构建所用的提交。
2. 标签填写 `v0.1.0`，标题可用 `Afterglow Desktop v0.1.0`。
3. 写明更新内容，并上传上表前三个附件（安装包、校验文件、`catalog.json`）；保持文件名不变。
4. 作为正式版发布，不勾选预发布，并将它设为最新正式发布（Latest）。
5. 核对附件、版本和提交后，再发布 Release。

如要同时提供便携版，将未经运行的完整便携目录压缩为 ZIP 后一并上传即可。当前应用内桌面更新仍使用安装包，不使用便携 ZIP。

GitHub 操作说明：[管理仓库中的发布](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。

## 6. 确认应用能获取更新

正式发布后，下面的固定地址应当可以直接访问：

```text
https://github.com/kldhsh123/Afterglow-Desktop/releases/latest/download/catalog.json
```

它就是应用内“更新来源／已发布的更新清单地址”。默认运行清单已经配置此地址；下一次发布时仍使用同一个地址，由 GitHub 指向最新正式发布。

需要区别两种检查：

- **桌面端**：仓库 `version.json` 用于发现新版本；实际下载安装必须有已发布的 `catalog.json`、安装包和正确校验值。仅改仓库版本号不等于发布完成。
- **Afterglow 核心**：首次安装或补装使用桌面程序自带的核心资源；之后从原核心仓库的 `VERSION` 检查版本，并从原仓库获取源码更新。无需单独上传核心 ZIP，也无需为了单独更新核心而重新发布整个桌面程序。

所有请求只直连 GitHub，不使用镜像。无法连接时会保留现有版本；不要在清单里填入镜像地址。

最后可在旧版应用的“组件与更新”里检查实际可用性。正式版 `0.1.0` 应高于 `0.1.0-internal.*`；同一个 `0.1.0` 不应反复提示更新。旧内部版的仓库版本文件解析只支持内部版本后缀，但发布清单支持正式版版本号，可通过发布清单获取正式版安装包。
