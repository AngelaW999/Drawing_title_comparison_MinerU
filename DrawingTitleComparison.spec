# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

hiddenimports = []
hiddenimports += collect_submodules("tkinter")
hiddenimports += collect_submodules("PIL")
hiddenimports += collect_submodules("requests")

# 你项目里用到 PyMuPDF：import fitz
hiddenimports += collect_submodules("fitz")
hiddenimports += collect_submodules("pymupdf")

# 兜底：把你自己的 src 包也显式收一下（防止动态 import 漏掉）
hiddenimports += collect_submodules("src")

datas = []
datas += collect_data_files("PIL")
datas += collect_data_files("fitz")
datas += collect_data_files("pymupdf")
datas += [("assets/icon.ico", "assets"), ("assets/icon.png", "assets")]

# 配置模板（可选）
a = Analysis(
    ["entry_gui.py"],
    pathex=["."],          # 当前 spec 所在目录就是根目录
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="目录标题对比工具",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # Tk GUI
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="目录标题对比工具",
)
