# Source attribution

Afterglow Desktop reuses the original [Afterglow core](https://github.com/kldhsh123/Afterglow) as a versioned runtime component. It does not replace its retrieval, memory, import or analysis implementation. The prepared v0.1.0 release bundles core version 0.4.1; later core updates may be installed independently.

Bundled QQ code derives from the supplied local Afterglow-QQBot-main snapshot; bundled WeChat code derives from Afterglow-WeiXinBot-main. The original AGPL-3.0 license texts are preserved in both channel directories. The root project uses AGPL-3.0-or-later.

Desktop changes include private-pipe configuration, structured state events, per-instance paths, SQLite contact authorization, revocation checks, protected login state and display-delay controls. Modified channel sources are distributed with the desktop code.

Brand assets follow the supplied Afterglow website/core assets. Dependencies retain upstream licenses and package metadata; release preparation must retain them and the official portable Python license.
