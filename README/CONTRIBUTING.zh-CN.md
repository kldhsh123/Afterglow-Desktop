# 参与 Afterglow Desktop

[English](../CONTRIBUTING.md) · [项目说明](README.zh-CN.md)

欢迎反馈问题、完善文档、翻译和贡献代码。提交 Issue 前请先搜索已有讨论；较大的改动请先通过 Issue 沟通。

## 开发流程

1. Fork 本仓库，从当前默认分支创建工作分支。
2. 安装 Node.js／npm、Python 3.12；开发原生桌面功能还需 Rust 和 Tauri 对应依赖。
3. 运行 `npm ci` 安装依赖，通过 `npm run dev` 预览界面。
4. 保持改动集中，在适当情况下为行为变化补充测试。
5. 向本仓库默认分支提交 PR，说明改动原因及实际执行的检查。

界面使用 Vue 3 和 TypeScript，原生功能使用 Tauri 2 和 Rust，Python 宿主及自带扩展位于 `desktop_host/`。界面文案分别维护在 `locales/zh-CN.json` 和 `locales/en-US.json`；修改安装文案时也请同步两份安装程序语言文件。

完整桌面开发需要经过验证的 Windows x64 Python／核心资源。准备前请阅读 `python3 scripts/prepare_windows.py --help`，生成的资源不提交到 Git。运行核心来源为 [kldhsh123/Afterglow](https://github.com/kldhsh123/Afterglow)，请保留原有声明，并区分桌面端改动与上游代码。

## 检查

根据改动范围运行相关检查，不能执行的项目请在 PR 中说明：

```bash
npm test
npx vue-tsc --noEmit
python3 -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

安装程序、托盘等改动还需要在 Windows 上手动验证；未验证请如实注明。不要在 PR 中提交构建产物。`version.json` 是版本来源，之后统一使用正式版。维护者运行一次 `npm run version:bump`，即可递增修订号（例如 `0.1.0` → `0.1.1`），并同步 npm、Cargo、Tauri 及运行组件清单；Windows 构建计数也会自动递增。仅同步当前版本、不升级时，使用 `npm run version:sync`。两个命令都不会构建程序。发布次版本或主版本时，由维护者明确修改 `baseVersion` 后同步。

## 反馈与仓库整理

- 问题和建议请使用 Issue 模板。报告异常时注明桌面端、核心及 Windows 版本。
- 日志与截图请先删除 API 密钥、令牌、个人信息和私人聊天内容。示例及测试数据请使用虚构内容。
- 不提交 `.env`、本地配置、聊天导出、日志、开发缓存、依赖、生成的 schema 或发布二进制文件。
- 保留版权与许可声明；引入依赖时，请在 PR 中说明依赖及许可证。
- 属于原版核心的问题请关联 [Afterglow Issue](https://github.com/kldhsh123/Afterglow/issues)，不要在桌面界面中复制一份核心实现。

## 贡献协议与代码所有权

提交 Pull Request 即视为同意本节全部条款。请仔细阅读。

通过向本仓库提交 Pull Request（PR）或以其他方式贡献代码，即表示您同意以下条款：

1. 您保留对自身贡献的版权。
2. 您授予仓库所有者（kldhsh123 及其指定继承者/受让人）永久的、不可撤销的、非独占的、全球范围的、免费的权利：使用、复制、修改、合并、发布、分发、转授权（sublicense）和以任何形式再许可（relicense）您的贡献，包括将贡献纳入项目整体并变更整个项目的许可证。
3. 此授权适用于当前及未来任何许可证。
4. 您的贡献默认以项目当前许可证（AGPL-3.0）分发，但仓库所有者有权随时变更整个项目的许可证，而无需另行获得您的同意。
5. 如果您对特定贡献有额外限制，请在 PR 描述中明确说明，否则视为无限制授权。
6. 本条款构成贡献者许可协议（CLA）的一部分。

此设计旨在让 Afterglow-Desktop 项目能长期灵活发展，同时尊重每位贡献者的劳动。

您只能授予自己拥有或有权授予的权利。引入第三方代码时，请在 PR 中注明来源。本协议不覆盖 Afterglow 核心、依赖及其他第三方材料原有的版权和许可，也不能代表其作者授权。
