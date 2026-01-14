# -*- mode: python ; coding: utf-8 -*-
import os
import subprocess
import datetime

def update_version_info():
    try:
        version_str = subprocess.check_output(['git', 'describe', '--tags', '--long'], text=True).strip()
    except:
        version_str = "unknown"

    compile_date = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='minutes')
    
    version_file = os.path.join('src', 'core', 'version.py')
    with open(version_file, 'w') as f:
        f.write(f'VERSION = "{version_str}"\n')
        f.write(f'COMPILE_DATE = "{compile_date}"\n')

update_version_info()

a = Analysis(
    ['main.py'],
    pathex=['src'],
    binaries=[],
    datas=[('src/i18n', 'src/i18n'), ('src/resources', 'src/resources')],
    hiddenimports=[],
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
