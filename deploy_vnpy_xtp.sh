#!/usr/bin/env bash
# 在 Ubuntu 服务器上部署 vnpy_xtp（需先将 vnpy_xtp.tar.gz 放到 workspace 目录）
#
# 用法:
#   bash deploy_vnpy_xtp.sh
#   sh deploy_vnpy_xtp.sh
#   ./deploy_vnpy_xtp.sh
#   bash deploy_vnpy_xtp.sh /path/to/vnpy_xtp.tar.gz

# Ubuntu 的 sh 是 dash，不支持 pipefail；用 bash 重新执行本脚本
if [ -z "${BASH_VERSION:-}" ]; then
    exec /usr/bin/env bash "$0" "$@"
fi

set -euo pipefail

WORKSPACE="/home/ubuntu/workspace"
TARGET="${WORKSPACE}/vnpy_xtp"
ARCHIVE="${1:-${WORKSPACE}/vnpy_xtp.tar.gz}"
DATE="$(date +%Y%m%d)"
BACKUP="${WORKSPACE}/vnpy_xtp_${DATE}"

die() {
    echo "[ERROR] $*" >&2
    exit 1
}

info() {
    echo "[INFO] $*"
}

if [[ ! -f "${ARCHIVE}" ]]; then
    die "压缩包不存在: ${ARCHIVE}"
fi

if [[ -d "${TARGET}" ]]; then
    if [[ -e "${BACKUP}" ]]; then
        die "备份目录已存在，请先处理: ${BACKUP}"
    fi
    info "重命名 ${TARGET} -> ${BACKUP}"
    mv "${TARGET}" "${BACKUP}"
fi

info "解压 ${ARCHIVE} -> ${TARGET}"
mkdir -p "${TARGET}"
tar -zxf "${ARCHIVE}" -C "${TARGET}"

info "安装依赖: pip install ."
cd "${TARGET}"
pip install .

info "部署完成: ${TARGET}"
