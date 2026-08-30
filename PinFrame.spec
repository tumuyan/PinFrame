# -*- mode: python ; coding: utf-8 -*-
import os
import subprocess
import datetime

def update_version_info():
    try:
        version_str = subprocess.check_output(['git', 'describe', '--tags', '--long'], text=True).strip()
    except:
        version_str = "unknown"

    try:
        repo_url = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], text=True).strip()
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(repo_url)
        if parsed.username or parsed.password:
            parsed = parsed._replace(netloc=parsed.hostname + (f":{parsed.port}" if parsed.port else ""))
            repo_url = urlunparse(parsed)
    except:
        repo_url = "https://github.com/tumuyan/PinFrame"

    build_date = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='minutes')
    
    # 写 `version.py`（P3-9）：该文件**不入库**（见 .gitignore），只在打包时生成，
    # 故每次构建重写它不会再污染工作区。开发态没有它 —— `main_window` 的导入是
    # **容错**的（缺文件时回落到运行时 git describe / 内置默认 URL）。
    #
    # 生成时机仍在 `Analysis` 之前，这样 PyInstaller 的静态分析能把它收进产物。
    version_file = os.path.join('src', 'core', 'version.py')
    with open(version_file, 'w') as f:
        f.write(f'VERSION = "{version_str}"\n')
        f.write(f'REPO_URL = "{repo_url}"\n')
        f.write(f'BUILD_DATE = "{build_date}"\n')

update_version_info()

a = Analysis(
    ['main.py'],
    pathex=['src'],
    binaries=[],
    datas=[('src/i18n', 'src/i18n'), ('src/resources', 'src/resources')],
    # `core.version` 由上面的 `update_version_info()` 生成，且 `core` 是命名空间包
    # （无 __init__.py）。显式列出以免静态分析漏收 —— 漏了的后果是打包产物里
    # 版本号为空，且**不报错**（导入是容错的）。
    hiddenimports=['core.version'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PinFrame',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(os.getcwd(), 'src', 'resources', 'icon.ico'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PinFrame',
)
