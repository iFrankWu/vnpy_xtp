import platform
from pathlib import Path

from setuptools import Extension, setup


def _has_trader_lib() -> bool:
    """交易库存在时才编译 vnxtptd。"""
    libs_dir = Path(__file__).parent / "vnpy_xtp" / "api" / "libs"
    api_dir = Path(__file__).parent / "vnpy_xtp" / "api"
    if platform.system() == "Windows":
        return (libs_dir / "xtptraderapi.lib").exists()
    return (
        (libs_dir / "libxtptraderapi.so").exists()
        or (api_dir / "libxtptraderapi.so").exists()
    )


def get_ext_modules() -> list:
    """
    获取三方模块
    Linux和Windows需要编译封装接口
    Mac由于缺乏二进制库支持无法使用
    """
    if platform.system() == "Linux":
        extra_compile_flags = [
            "-std=c++17",
            "-O3",
            "-Wno-delete-incomplete",
            "-Wno-sign-compare",
        ]
        extra_link_args = ["-lstdc++"]
        runtime_library_dirs = ["$ORIGIN"]

    elif platform.system() == "Windows":
        extra_compile_flags = ["-O2", "-MT"]
        extra_link_args = []
        runtime_library_dirs = []

    else:
        return []

    vnxtpmd = Extension(
        "vnpy_xtp.api.vnxtpmd",
        [
            "vnpy_xtp/api/vnxtp/vnxtpmd/vnxtpmd.cpp",
        ],
        include_dirs=["vnpy_xtp/api/include",
                      "vnpy_xtp/api/vnxtp"],
        define_macros=[],
        undef_macros=[],
        library_dirs=["vnpy_xtp/api/libs", "vnpy_xtp/api"],
        libraries=["xtpxquoteapi"],
        extra_compile_args=extra_compile_flags,
        extra_link_args=extra_link_args,
        runtime_library_dirs=runtime_library_dirs,
        depends=[],
        language="cpp",
    )

    vnxtptd = Extension(
        "vnpy_xtp.api.vnxtptd",
        [
            "vnpy_xtp/api/vnxtp/vnxtptd/vnxtptd.cpp",
        ],
        include_dirs=["vnpy_xtp/api/include",
                      "vnpy_xtp/api/vnxtp"],
        define_macros=[],
        undef_macros=[],
        library_dirs=["vnpy_xtp/api/libs", "vnpy_xtp/api"],
        libraries=["xtptraderapi"],
        extra_compile_args=extra_compile_flags,
        extra_link_args=extra_link_args,
        runtime_library_dirs=runtime_library_dirs,
        depends=[],
        language="cpp",
    )

    exts = [vnxtpmd]
    if _has_trader_lib():
        exts.append(vnxtptd)
    return exts


setup(
    ext_modules=get_ext_modules(),
)
