# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec para WooCommerce Connector
# Uso:
#   pyinstaller woocommerce_connector.spec
#
# Genera: dist/WooCommerceConnector/WooCommerceConnector.exe  (Windows)
#         dist/WooCommerceConnector/WooCommerceConnector      (macOS/Linux)

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── Recolectar archivos de datos de customtkinter ──────────────────────
# customtkinter incluye fuentes .otf y archivos .json de temas que
# DEBEN ir empaquetados, si no la app crashea al iniciar.
ctk_datas = collect_data_files("customtkinter")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=ctk_datas,
    hiddenimports=[
        "darkdetect",          # detección de tema claro/oscuro (dep de customtkinter)
        "tkinter",
        "tkinter.ttk",
        "_tkinter",
        "tinydb",
        "tinydb.storages",
        "tinydb.middlewares",
        "requests",
        "urllib3",
        "charset_normalizer",
        "idna",
        "certifi",
        "queue",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "numpy", "pandas", "scipy",
        "PIL", "cv2", "PyQt5", "wx",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WooCommerceConnector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,        # sin ventana de consola (GUI pura)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",   # descomenta cuando tengas un icono .ico
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WooCommerceConnector",
)
