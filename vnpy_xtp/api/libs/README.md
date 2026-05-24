# XTP 预编译动态库（纳入 Git）

本目录存放 XTP 官方 SDK 二进制，便于 Windows / Linux 直接 `pip install .` 编译，无需每台机器单独拷贝 SDK。

| 文件 | 平台 | 用途 | SDK 版本 |
|------|------|------|----------|
| `xtpxquoteapi.dll` / `xtpxquoteapi.lib` | Windows | XTP Pro 行情 | 1.1.0-r.1 |
| `libxtpxquoteapi.so` | Linux (CentOS/Ubuntu) | XTP Pro 行情 | 1.1.0-r.1 (onload-8.1.2.26) |
| `xtptraderapi.dll` / `xtptraderapi.lib` | Windows | 旧 XTP 交易 | 2.2.32.x |
| `libxtptraderapi.so` | Linux | 旧 XTP 交易 | 待补充 |

运行时 `pip install` 会将 `.dll` / `.so` 一并打包到 `site-packages/vnpy_xtp/api/`。

**升级 SDK 时**：替换本目录对应文件并同步 `vnpy_xtp/api/` 根目录下的同名运行时库，更新此表版本号。

**注意**：中泰 SDK 可能有再分发限制，仅限内部私有仓库使用。
