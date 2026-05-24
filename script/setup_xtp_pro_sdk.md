# XTP Pro SDK 部署说明

> 头文件与 Linux/Windows 动态库已纳入 Git（`vnpy_xtp/api/include/xtp/`、`vnpy_xtp/api/libs/`）。  
> 常规部署只需 **git pull + pip install**，无需再手动下载 SDK。

## 快速安装

### Windows

```bash
cd vnpy_xtp
pip install .
```

### Ubuntu / Linux

```bash
sudo apt install -y build-essential python3-dev python3-pip
cd /home/ubuntu/workspace/vnpy_xtp
git pull
bash script/deploy_xtp_pro_linux.sh
```

脚本会自动：同步 `api/libs/` → `api/`、`pip3 install .`、验证 API 版本。

## 仓库内二进制清单

| 文件 | 平台 | 用途 |
|------|------|------|
| `api/libs/xtpxquoteapi.dll` + `.lib` | Windows | XTP Pro 行情 |
| `api/libs/libxtpxquoteapi.so` | Linux | XTP Pro 行情 |
| `api/libs/xtptraderapi.dll` + `.lib` | Windows | 旧 XTP 交易 |
| `api/libs/libxtptraderapi.so` | Linux | 旧 XTP 交易（若缺失则只编译行情模块） |

## 验证

```bash
python start_client_xtp_pro.py 1
# 或 Linux: python3 ...
```

公网测试行情：`122.112.252.150:3002`

---

## SDK 升级时（维护者）

1. 从官方下载新版 SDK：https://xtp.zts.com.cn/service/download/info?id=1&type=downloadProducts
2. 替换 `vnpy_xtp/api/include/xtp/` 下 Pro 行情头文件（`xtpx_*.h`、`xquote_x_*.h`）
3. 执行 `bash script/deploy_xtp_pro_linux.sh --refresh-sdk <SDK目录>` 刷新文件
4. 提交 Git 后各环境 `git pull && bash script/deploy_xtp_pro_linux.sh`

也可使用脚本（维护者从本地 SDK 目录刷新库文件后提交 Git）：

```bash
bash script/deploy_xtp_pro_linux.sh --refresh-sdk ~/XTPXQuoteAPI_x.x.x
```

## 注意事项

- **Git 体积**：`.so`/`.dll` 约数 MB，私有仓库可接受；若过大可改用 Git LFS
- **许可证**：确认中泰 SDK 允许在内部仓库中再分发
- **macOS**：官方无库，不支持
- **UDP**：`local_ip` 填本机内网 IP，Login 前需 `SetConfigFile`
