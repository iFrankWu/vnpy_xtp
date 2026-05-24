#!/usr/bin/env bash
# vnpy_xtp Linux 部署脚本
#
# 常规部署（头文件与 .so 已在 Git 中，无需 SDK 目录）:
#   cd /home/ubuntu/workspace/vnpy_xtp
#   bash script/deploy_xtp_pro_linux.sh
#
# 维护者从官方 SDK 刷新头文件/库（升级 SDK 时用）:
#   bash script/deploy_xtp_pro_linux.sh --refresh-sdk ~/XTPXQuoteAPI_1.1.0-r.1_20260327
#   bash script/deploy_xtp_pro_linux.sh --refresh-sdk ~/XTPXQuoteAPI_xxx --trader-lib /path/to/old_xtp_trader

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INCLUDE_DIR="${ROOT_DIR}/vnpy_xtp/api/include/xtp"
LIBS_DIR="${ROOT_DIR}/vnpy_xtp/api/libs"
API_DIR="${ROOT_DIR}/vnpy_xtp/api"

REFRESH_SDK=0
SDK_DIR=""
TRADER_LIB_DIR=""

die() {
    echo "[ERROR] $*" >&2
    exit 1
}

info() {
    echo "[INFO] $*"
}

usage() {
    cat <<'EOF'
用法:
  bash script/deploy_xtp_pro_linux.sh
  bash script/deploy_xtp_pro_linux.sh --refresh-sdk <SDK目录> [--trader-lib <交易库目录>]

说明:
  默认模式    使用 Git 仓库内已提交的头文件与 libxtpxquoteapi.so，直接 pip install
  --refresh-sdk  从官方 SDK 包更新 include/ 与 api/libs/（维护者升级 SDK 时使用）
EOF
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "缺少命令: $1"
}

find_quote_so() {
    local sdk="$1"
    local candidates=(
        "${sdk}/lib/centos/onload-8.1.2.26/libxtpxquoteapi.so"
        "${sdk}/lib/centos/onload-7.1.0.265/libxtpxquoteapi.so"
        "${sdk}/lib/linux/libxtpxquoteapi.so"
        "${sdk}/lib/libxtpxquoteapi.so"
    )
    local path
    for path in "${candidates[@]}"; do
        if [[ -f "${path}" ]]; then
            echo "${path}"
            return 0
        fi
    done
    return 1
}

find_trader_so() {
    local dir="$1"
    local candidates=(
        "${dir}/libxtptraderapi.so"
        "${dir}/libs/libxtptraderapi.so"
        "${dir}/lib/linux/libxtptraderapi.so"
        "${dir}/lib/libxtptraderapi.so"
    )
    local path
    for path in "${candidates[@]}"; do
        if [[ -f "${path}" ]]; then
            echo "${path}"
            return 0
        fi
    done
    return 1
}

sync_runtime_libs() {
    info "同步运行时动态库 api/libs/ -> api/"
    [[ -f "${LIBS_DIR}/libxtpxquoteapi.so" ]] || die "缺少 ${LIBS_DIR}/libxtpxquoteapi.so，请 git pull 或使用 --refresh-sdk"
    cp -f "${LIBS_DIR}/libxtpxquoteapi.so" "${API_DIR}/libxtpxquoteapi.so"
    if [[ -f "${LIBS_DIR}/libxtptraderapi.so" ]]; then
        cp -f "${LIBS_DIR}/libxtptraderapi.so" "${API_DIR}/libxtptraderapi.so"
    else
        info "未找到 libxtptraderapi.so，将仅编译行情模块 vnxtpmd"
    fi
}

refresh_from_sdk() {
    [[ -d "${SDK_DIR}" ]] || die "SDK 目录不存在: ${SDK_DIR}"
    [[ -d "${SDK_DIR}/header" ]] || die "未找到 ${SDK_DIR}/header"

    mkdir -p "${INCLUDE_DIR}" "${LIBS_DIR}" "${API_DIR}"

    info "从 SDK 刷新头文件: ${SDK_DIR}/header"
    cp -f "${SDK_DIR}/header/"*.h "${INCLUDE_DIR}/"

    local quote_so
    quote_so="$(find_quote_so "${SDK_DIR}")" || die "未找到 libxtpxquoteapi.so"
    info "从 SDK 刷新行情库: ${quote_so}"
    cp -f "${quote_so}" "${LIBS_DIR}/libxtpxquoteapi.so"

    if [[ -n "${TRADER_LIB_DIR}" ]]; then
        local trader_so
        trader_so="$(find_trader_so "${TRADER_LIB_DIR}")" || die "未找到 libxtptraderapi.so: ${TRADER_LIB_DIR}"
        info "从 SDK 刷新交易库: ${trader_so}"
        cp -f "${trader_so}" "${LIBS_DIR}/libxtptraderapi.so"
    fi

    info "SDK 文件已更新，请 git add 并 commit 后推送到仓库"
}

verify_md_api() {
    python3 - <<'PY'
import importlib.util
from pathlib import Path
import sysconfig

site = Path(sysconfig.get_paths()["purelib"])
candidates = list(site.glob("vnpy_xtp/api/vnxtpmd*.so"))
if not candidates:
    candidates = list(Path("vnpy_xtp/api").glob("vnxtpmd*.so"))
if not candidates:
    raise SystemExit("未找到 vnxtpmd 扩展模块")

spec = importlib.util.spec_from_file_location("vnxtpmd", candidates[0])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

api = mod.MdApi()
api.createQuoteApi(1, b"/tmp/xtp_md", 3, False)
print("XTP Pro MD API version:", api.getApiVersion())
PY
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --refresh-sdk)
            REFRESH_SDK=1
            SDK_DIR="${2:-}"
            [[ -n "${SDK_DIR}" ]] || die "--refresh-sdk 需要 SDK 目录参数"
            shift 2
            ;;
        --trader-lib)
            TRADER_LIB_DIR="${2:-}"
            [[ -n "${TRADER_LIB_DIR}" ]] || die "--trader-lib 需要目录参数"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "未知参数: $1（使用 --help 查看用法）"
            ;;
    esac
done

info "项目目录: ${ROOT_DIR}"

require_cmd g++
require_cmd pip3
python3 - <<'PY' || die "请先安装: sudo apt install python3-dev build-essential"
import sysconfig
print("python include:", sysconfig.get_path("include"))
PY

if [[ "${REFRESH_SDK}" -eq 1 ]]; then
    refresh_from_sdk
fi

sync_runtime_libs

info "开始编译安装..."
cd "${ROOT_DIR}"
pip3 install .

info "验证行情扩展模块..."
verify_md_api

info "部署完成。"
info "公网测试行情: 122.112.252.150:3002"
info "验证示例: python3 /home/ubuntu/workspace/lpc-stock/examples/no_ui/start_client_xtp_pro.py 1"
