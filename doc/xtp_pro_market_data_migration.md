# XTP Pro 行情升级方案

> 文档版本：2026-05-21  
> 适用项目：`vnpy_xtp`（LPC fork，当前 SDK 版本 2.2.32.2）  
> 背景：中泰证券计划于 6 月底下线 XTP 3.0 行情服务，需将 API 程序中的行情功能切换至 XTP Pro 版本。

---

## 1. 背景与目标

### 1.1 升级背景

中泰证券通知 XTP 3.0 行情服务将于 **6 月底下线**，需提前将行情接入切换至 **XTP Pro**。

### 1.2 测试环境

| 服务 | 地址 | 账号要求 |
|------|------|----------|
| 行情 | `122.112.252.150:3002` | XTP / XTP Pro 测试账号均可 |
| 交易 | `122.112.219.239:8100` | 仅 XTP Pro 测试账号 |

### 1.3 官方文档

| 资源 | 链接 |
|------|------|
| XTP Pro SDK 下载 | https://xtp.zts.com.cn/service/download/info?id=1&type=downloadProducts |
| XTP Pro 技术文档 | https://xtp.zts.com.cn/xtp-pro/ |
| XTP Pro 业务列表 | https://xtp.zts.com.cn/doc/xtpPro_business |
| 测试账号申请 | https://xtp.zts.com.cn/login |
| **行情 API 迁移文档** | https://xtp.zts.com.cn/xtp-pro/API4/从XTP行情到XTP%20Pro行情API的变化/从XTP行情到XTP%20Pro行情API的变化.html |

### 1.4 升级目标

- **阶段一（6 月底前必须完成）**：仅升级行情 SDK + Gateway，切换至 XTP Pro 行情接入
- **阶段二（可选）**：交易端同步迁移至 XTP Pro（`122.112.219.239:8100`）

---

## 2. 当前项目现状

### 2.1 架构分层

```
XTP SDK (C++ 动态库)
    ↓
vnxtpmd / vnxtptd (pybind11 C++ Extension)
    ↓
XtpMdApi / XtpTdApi (Python 子类，xtp_gateway.py)
    ↓
XtpGateway (VeighNa BaseGateway)
```

### 2.2 关键文件

| 层级 | 路径 | 作用 |
|------|------|------|
| Gateway | `vnpy_xtp/gateway/xtp_gateway.py` | 行情 + 交易 Gateway |
| 行情 C++ 封装 | `vnpy_xtp/api/vnxtp/vnxtpmd/vnxtpmd.cpp` | pybind11 绑定 |
| 交易 C++ 封装 | `vnpy_xtp/api/vnxtp/vnxtptd/vnxtptd.cpp` | pybind11 绑定 |
| SDK 头文件 | `vnpy_xtp/api/include/xtp/` | XTP C++ SDK 头文件 |
| SDK 二进制 | `vnpy_xtp/api/libs/` | 动态库（仓库内为空，需自行下载） |
| 代码生成 | `vnpy_xtp/api/generator/` | 从 SDK 头文件生成绑定 |
| 构建配置 | `setup.py` | C++ Extension 编译与链接 |

### 2.3 当前 SDK 版本

- 文档声明版本：**2.2.32.2**
- 链接库名：`xtpquoteapi`、`xtptraderapi`
- 命名空间：`XTP::API`
- **尚无 XTP Pro 相关代码**

### 2.4 平台支持

| 平台 | 支持情况 |
|------|----------|
| Windows | ✅ 支持 |
| Linux | ✅ 支持 |
| **macOS** | ❌ **不支持**（官方未提供 Mac 二进制库，`setup.py` 在 Mac 上不编译扩展模块） |

> XTP Pro SDK 与旧版 XTP 一样，仅提供 Windows / Linux 预编译库。在 Mac 上开发需借助 Linux 虚拟机、Docker 或远程 Linux/Windows 服务器进行编译和联调。

---

## 3. 总体策略

采用 **「行情先行、交易后续」** 的分阶段迁移：

```
阶段一（6 月底前）→ 仅升级行情 SDK + Gateway
阶段二（可选）    → 交易端同步迁移至 XTP Pro
```

**混用方案（官方支持）**：XTP Pro 行情（`XTPX::API`）+ 旧 XTP 交易（`XTP::API`）可同时使用，6 月底前只迁行情即可。

---

## 4. XTP Pro 行情 API 变更摘要

> 来源：[从 XTP 行情到 XTP Pro 行情 API 的变化](https://xtp.zts.com.cn/xtp-pro/API4/从XTP行情到XTP%20Pro行情API的变化/从XTP行情到XTP%20Pro行情API的变化.html)

### 4.1 命名空间变化（重要）

| 模块 | 命名空间 |
|------|----------|
| XTP Pro 行情 | `XTPX::API` |
| XTP 交易（旧） | `XTP::API` |

编译混用时，需在参数类型前加命名空间前缀消歧：

```cpp
// 行情（Pro）
XTPX::API::QuoteApi* pQuoteApi = XTPX::API::QuoteApi::CreateQuoteApi(...);

// 交易（旧）
XTP::API::TraderApi* pUserApi = XTP::API::TraderApi::CreateTraderApi(...);
```

### 4.2 结构体 XTPMD 变动

| 变化 | 说明 | 对项目影响 |
|------|------|------------|
| 去除 `data_type` | 改用 `data_type_v2` | 当前 `vnxtpmd.cpp` 已映射 `data_type_v2`，`data_type` 已注释，**基本无需改** |
| `ticker_status` 语义变化 | Pro 版直接透传交易所原始值，不再做转换 | Gateway 未使用该字段，**无影响**；若后续做停牌判断需重写逻辑 |

Tick 转换核心字段（`ticker`、`data_time`、`bid/ask`、`turnover` 等）**结构未变**，`onDepthMarketData` → `TickData` 逻辑可基本复用。

### 4.3 已删除接口

| 删除接口 | 当前项目使用情况 | 处理方式 |
|----------|------------------|----------|
| `SetUDPBufferSize()` | `xtp_gateway.py` UDP 模式调用 | **删除**，改配置文件 |
| `SetUDPSeqLogOutPutFlag()` | 已注释 | 删除 |
| `SetUDPRecvThreadAffinity()` 等绑核接口 | 未使用 | 改配置文件或 `SetUDPThreadAffinityArray()` |
| `GetTradingDay()` | `vnxtpmd.cpp` 已绑定 Python | **删除绑定** |
| 期权逐笔/订单簿 8 个接口 | `vnxtpmd.cpp` 有回调但未暴露 Python | 从 C++ 层删除 |
| `LoginToRebuildQuoteServer()` 等回补登录 | 未使用 | 无影响 |
| `OnTickByTickLossRange()` | 未使用 | 无影响 |

### 4.4 新增接口

| 新增接口 | 说明 | 优先级 |
|----------|------|--------|
| **`SetConfigFile()`** | UDP 模式下 **Login 前必须调用**，否则收不到行情 | **P0 必做** |
| `CreateQuoteApi()` 第 4 参数 | `udpseq_output`，替代 `SetUDPSeqLogOutPutFlag` | **P0 必做** |
| `SetUDPThreadAffinityArray()` | 运行时绑核，替代配置文件方式 | P2 可选 |
| `QueryTickersLatestMarketData()` | 查询最新快照 | P2 可选 |
| `SubscribeAllIndexPress()` | 指数通行情 | P3 按需 |
| `SubscribeAllHKCMarketData()` | 港股通行情 | P3 按需 |
| `OnXTPQuoteNQFullInfo()` | 新三板静态信息推送 | P3 按需 |

### 4.5 功能变化接口

| 接口 | 旧版 | Pro 版 | 项目影响 |
|------|------|--------|----------|
| `CreateQuoteApi()` | 3 参数 | 4 参数（新增 `udpseq_output`） | 修改 `vnxtpmd.cpp` |
| `QueryAllTickersPriceInfo()` | 无参数，查全市场 | **必须传入单市场** `exchange_id` | 修改 `vnxtpmd.cpp` 和 Gateway |
| `RequestRebuildQuote()` | 回补需先登录回补服务器 | **无需登录**，直接调用 | 未使用，无影响 |
| `Login()` | 支持 `local_ip` 参数 | 示例中未显式传 `local_ip`，UDP 改由配置文件设置 | 需确认 Pro SDK Login 签名 |

### 4.6 UDP 接入流程变化（最关键）

**旧版流程：**

```
CreateQuoteApi() → setUDPBufferSize() → Login() → Subscribe
```

**Pro 版流程：**

```
CreateQuoteApi(client_id, path, log_level, udpseq_output)
    ↓
SetConfigFile("quote_config.ini")   ← Login 前必须调用
    ↓
Login(ip, port, user, password, protocol)
    ↓
SubscribeMarketData / SubscribeAllMarketData
```

**配置文件示例（`quote_config.ini`）：**

```ini
[md]
decode_flag = 1
parse_cpu_id = 0

[md.normal]
enable = ON
local_ip = 10.0.0.1          # 接收组播的网卡地址，对应现有 local_ip 参数
recv_cpu_id = 0
enable_efvi = OFF
L1_buf_capacity = 256
L2_buf_capacity = 8

[md.fpga]
enable = OFF
local_ip = 10.0.0.1
recv_cpu_id = 0
L1_buf_capacity = 256
L2_buf_capacity = 8

[subscribe_quote_type]
sh_level2_md_stock = ON
sz_level2_md_stock = ON
# 按需开启其他行情类型
```

---

## 5. 与当前代码的对照改动清单

### 5.1 SDK 层

| 改动项 | 路径 / 说明 |
|--------|-------------|
| 替换头文件 | `vnpy_xtp/api/include/xtp/` 全部 `.h` |
| 替换二进制库 | `vnpy_xtp/api/libs/`（库名可能变为 `xtpproquoteapi` 等，以 SDK 实际文件名为准） |
| 更新链接库名 | `setup.py` 中 `libraries=[...]` |
| 交易 SDK | 可暂保留旧版，或分目录管理两套头文件/库 |

### 5.2 C++ 绑定层（`vnxtpmd.cpp`）

| 改动项 | 说明 |
|--------|------|
| 命名空间 | `XTP::API` → `XTPX::API` |
| `createQuoteApi` | 增加 `udpseq_output` 参数 |
| 新增 `setConfigFile` | 绑定 `SetConfigFile()` |
| 删除 `setUDPBufferSize` | 及 pybind 绑定 |
| 删除 `getTradingDay` | 及 pybind 绑定 |
| 修改 `queryAllTickersPriceInfo` | 增加 `exchange_id` 参数 |
| 删除 8 个期权逐笔/订单簿回调 | Pro 版已去除 |

### 5.3 Python Gateway 层（`xtp_gateway.py`）

**`XtpMdApi.connect()` 改造后流程：**

```python
def connect(...):
    if not self.connect_status:
        path = str(get_folder_path(self.gateway_name.lower())).encode("GBK")
        self.createQuoteApi(client_id, path, log_level, udpseq_output=False)
        self.setHeartBeatInterval(30)

        if quote_protocol == 'UDP':
            config_path = self._generate_quote_config(local_ip)  # 新增
            self.setConfigFile(config_path)                       # 新增
            # 删除: self.setUDPBufferSize(1024)

        self.login_server()
```

**需审查但基本可复用的逻辑：**

| 功能 | 文件位置 | 迁移关注点 |
|------|----------|------------|
| Tick 转换 | `onDepthMarketData()` | 字段映射基本不变 |
| 合约查询 | `onQueryAllTickers()` | `XTPQSI` 结构是否变化 |
| 单合约/全市场订阅 | `subscribe()` / `subscribe_all_tickets()` | 接口签名是否变化 |
| 断线重连 | `onDisconnected()` → `re_subscribe()` | 逻辑可复用 |
| Tick 过滤 | 仅处理已订阅标的、丢弃过期 Tick | 逻辑可复用 |

**`default_setting` 建议新增：**

```python
"行情配置文件": "",   # UDP 必填；留空则 Gateway 根据 local_ip 自动生成
```

**`query_all_last_price()` 改动：**

Pro 版 `QueryAllTickersPriceInfo()` 只支持单市场查询，需分别调用 SSE 和 SZSE。

### 5.4 当前代码中需直接删除/修改的位置

| 文件 | 行/位置 | 改动 |
|------|---------|------|
| `xtp_gateway.py` | `connect()` 中 `setUDPBufferSize(1024)` | 删除，改为 `setConfigFile()` |
| `xtp_gateway.py` | `connect()` 中 `createQuoteApi(...)` | 增加 `udpseq_output` 参数 |
| `vnxtpmd.cpp` | `createQuoteApi()` | 命名空间 + 第 4 参数 |
| `vnxtpmd.cpp` | `setUDPBufferSize()` / `getTradingDay()` | 删除 |
| `vnxtpmd.cpp` | `queryAllTickersPriceInfo()` | 增加 `exchange_id` 参数 |

---

## 6. 分阶段实施计划

### 阶段 0：准备（1–2 天）

| 任务 | 说明 |
|------|------|
| 下载 XTP Pro SDK | 从官方下载页获取头文件 + 动态库 |
| 申请 Pro 测试账号 | https://xtp.zts.com.cn/login |
| 阅读迁移文档 | 确认 API diff |
| 准备 Linux/Windows 编译环境 | Mac 无法本地编译 |

### 阶段 1：SDK 替换（1 天）

1. 备份当前 `include/xtp/` 与 `libs/`
2. 用 XTP Pro SDK 覆盖行情相关头文件与二进制
3. 修改 `setup.py` 链接库名（若变化）
4. 尝试编译：`pip install .`

### 阶段 2：C++ 绑定层改造（3–4 天）

按第 5.2 节清单修改 `vnxtpmd.cpp`，重新生成或更新 generator 脚本产物。

### 阶段 3：Python Gateway 适配（1–2 天）

按第 5.3 节清单修改 `xtp_gateway.py`，实现配置文件生成逻辑。

### 阶段 4：联调测试（3–5 天）

测试环境：`122.112.252.150:3002`

| 优先级 | 测试项 | 验收标准 |
|--------|--------|----------|
| P0 | TCP 登录 → 单合约订阅 → Tick 推送 | 字段正确，延迟可接受 |
| P0 | UDP 登录（含 SetConfigFile）→ 订阅 → Tick | 配置文件正确时可收 Tick |
| P0 | 断线重连 → 恢复订阅 | 自动重连并恢复订阅列表 |
| P1 | 全市场订阅 | `subscribeAllMarketData` 正常 |
| P1 | 合约查询 | 沪深合约加载、ST 股识别正常 |
| P2 | 分市场查最新价 | `queryAllTickersPriceInfo(exchange_id)` |
| P2 | 长时间运行 | 8 小时无异常断线、无内存泄漏 |

**建议测试顺序**：先用 **TCP** 验证基础链路，再切 **UDP**（UDP 配置错误会导致完全收不到行情）。

### 阶段 5：生产切换（1 天）

1. 测试环境全部用例通过
2. 更新生产配置：行情地址/端口改为 Pro 生产接入点
3. 选择低峰时段切换
4. 切换后监控：登录、订阅、Tick 推送、重连
5. 保留旧 SDK 备份，便于回滚

**建议时间节点**：

- **6 月中旬前**：完成测试
- **6 月底前**：完成生产切换

---

## 7. 工作量与风险

### 7.1 工作量估算

| 阶段 | 工期 | 人力 |
|------|------|------|
| 准备 + API Diff | 1–2 天 | 1 人 |
| SDK 替换 + 编译 | 1 天 | 1 人（C++） |
| 绑定 + Gateway 适配 | 3–5 天 | 1 人 |
| 联调测试 | 3–5 天 | 1–2 人 |
| 生产切换 | 1 天 | 1 人 |
| **合计** | **约 2–3 周** | — |

### 7.2 风险与应对

| 风险 | 等级 | 应对 |
|------|------|------|
| UDP 配置文件不正确导致无 Tick | 高 | 先用 TCP 验证；提供配置模板和自动生成逻辑 |
| Pro SDK 与 2.2.32 API 差异大 | 中 | 提前做头文件 diff；必要时重写 `vnxtpmd.cpp` |
| 命名空间混用编译错误 | 中 | 行情/交易分 Extension，显式加命名空间前缀 |
| 行情/交易 SDK 需分离 | 中 | 分目录存放，setup.py 分别链接 |
| Mac 无法本地开发 | 低 | 使用 Linux VM / Docker / 远程服务器 |
| 6 月底 deadline | 中 | 优先完成行情，交易后续单独迁移 |

---

## 8. 架构改动示意

```
┌─────────────────────────────────────────────────────────┐
│                    xtp_gateway.py                        │
│  XtpMdApi (改造)              XtpTdApi (暂不动)          │
└──────────────┬────────────────────────┬─────────────────┘
               │                        │
┌──────────────▼──────────────┐  ┌──────▼──────────────────┐
│  vnxtpmd.cpp (改造)         │  │  vnxtptd.cpp (暂不动)   │
│  XTPX::API::QuoteApi        │  │  XTP::API::TraderApi    │
└──────────────┬──────────────┘  └──────┬──────────────────┘
               │                        │
┌──────────────▼──────────────┐  ┌──────▼──────────────────┐
│  XTP Pro 行情库 (新)        │  │  XTP 交易库 (旧)        │
│  xtpproquoteapi.so/.dll     │  │  xtptraderapi.so/.dll   │
└─────────────────────────────┘  └─────────────────────────┘
```

---

## 9. 附录

### 9.1 当前 Gateway 定制逻辑（迁移后保留）

以下逻辑在 2023-12 断线优化中引入，迁移后应保留：

1. 当前进程仅处理自身订阅标的的 Tick，其他 Tick 直接丢弃
2. 丢弃时间戳早于本地的 Tick，减少队列积压
3. 断线重连 sleep 3 秒后再重连
4. 重连时先取消之前订阅的标的
5. 系统配置 `re_auto_login_xtp` 控制是否自动重连
6. TCP 连接超时时间 30 秒
7. UDP 模式下重连不会重新订阅

### 9.2 ticker_status 标志位（Pro 版，供后续参考）

**沪市：**

| 位 | 含义 |
|----|------|
| 第 0 位 | S=开市前, C=开盘集合竞价, T=连续竞价, E=闭市, P=停牌, M=可恢复熔断, N=不可恢复熔断, U=收盘集合竞价 |
| 第 1 位 | 0=不可正常交易, 1=可正常交易 |
| 第 2 位 | 0=未上市, 1=已上市 |
| 第 3 位 | 0=不接受新订单, 1=可接受新订单 |

**深市：**

| 位 | 含义 |
|----|------|
| 第 0 位 | S=开市前, O=开盘集合竞价, T=连续竞价, B=休市, C=收盘集合竞价, E=闭市, H=临时停牌, A=盘后交易, V=波动性中断 |
| 第 1 位 | 0=正常, 1=全天停牌 |

### 9.3 参考链接

- [XTP Pro API 文档首页](https://xtp.zts.com.cn/xtp-pro/)
- [行情 XQuote-API QuickStart](https://xtp.zts.com.cn/xtp-pro/)
- [行情断线后应对措施](https://xtp.zts.com.cn/xtp-pro/)
- [L2 行情数据回补功能说明](https://xtp.zts.com.cn/xtp-pro/)
- [错误代码速查表](https://xtp.zts.com.cn/xtp-pro/)
