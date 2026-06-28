#!/usr/bin/env python3
"""Build Screen Doodle into a standalone Windows executable with PyInstaller.

Usage:
    python build.py               # onedir mode (folder output)
    python build.py --onefile     # single exe (slower startup)
    python build.py --clean       # remove old build artifacts

Output:
    dist/screen-doodle/  (onedir) or dist/screen-doodle.exe (onefile)

Requirements:
    pip install pyinstaller
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
SPEC_FILE = PROJECT_ROOT / "screen-doodle.spec"
MAIN_SCRIPT = PROJECT_ROOT / "main.py"
DATA_FILES = [
    (str(PROJECT_ROOT / "setting.json"), "."),  # (src, dst_folder_in_bundle)
]

# -- Version info ----------------------------------------------------------
VERSION = "0.2.0"
COMPANY_NAME = "Screen Doodle"
FILE_DESCRIPTION = "Screen Doodle - screen annotation tool"


def _conda_dll_args() -> list[str]:
    """Extra PyInstaller args to bundle Python DLL from conda environments.

    Conda places ``python3XY.dll`` in the environment root (not in ``DLLs/``
    or ``Library/bin/`` like a standard Python install).  PyInstaller 6.x
    sometimes misses it in this layout, causing a *Failed to load Python DLL*
    error at startup.
    """
    dll_name = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    conda_dll = os.path.join(os.path.dirname(sys.executable), dll_name)
    if os.path.exists(conda_dll):
        print(f"  [conda] Found conda Python DLL: {conda_dll}")
        return [
            "--paths", os.path.dirname(sys.executable),
            "--add-binary", f"{conda_dll}{os.pathsep}.",
        ]
    return []


def build_onedir():
    """Build in onedir mode (folder with all dependencies, faster startup)."""
    print("=== Building: onedir mode ===")
    _run_pyinstaller(
        [
            "--onedir",
            "--name", "screen-doodle",
            "--noconsole",
            "--clean",
            "--noconfirm",
            "--version-file", str(_write_version_file()),
            "--hidden-import", "keyboard",
            "--hidden-import", "keyboard._winkeyboard",
            "--hidden-import", "keyboard._winmouse",
            "--hidden-import", "PIL",
            "--hidden-import", "PIL._imaging",
            "--collect-binaries", "PySide6",
            *_conda_dll_args(),
            str(MAIN_SCRIPT),
        ]
    )
    out_dir = DIST_DIR / "screen-doodle"
    _trim_unused_qt(out_dir / "_internal" / "PySide6")
    _copy_setting_json(out_dir)
    _print_size(out_dir)
    print(f"[done] Build complete! Output: {out_dir}")


def build_onefile():
    """Build as a single executable (slower startup, cleaner distribution)."""
    print("=== Building: onefile mode ===")
    _run_pyinstaller(
        [
            "--onefile",
            "--name", "screen-doodle",
            "--noconsole",
            "--clean",
            "--noconfirm",
            "--version-file", str(_write_version_file()),
            *[arg for src, dst in DATA_FILES for arg in _data_arg(src, dst)],
            "--hidden-import", "keyboard",
            "--hidden-import", "keyboard._winkeyboard",
            "--hidden-import", "keyboard._winmouse",
            "--hidden-import", "PIL",
            "--hidden-import", "PIL._imaging",
            "--collect-binaries", "PySide6",
            *_conda_dll_args(),
            str(MAIN_SCRIPT),
        ]
    )
    exe = DIST_DIR / "screen-doodle.exe"
    if exe.exists():
        print(f"[done] Build complete! Single exe: {exe}")
    else:
        print(f"[warn] Expected output not found: {exe}")


def _run_pyinstaller(args: list[str]) -> None:
    """Run PyInstaller with the given arguments."""
    cmd = [sys.executable, "-m", "PyInstaller"] + args
    print(f"Running: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=PROJECT_ROOT)


def _data_arg(src: str, dst: str) -> list[str]:
    """Return ``--add-data`` flag components for PyInstaller."""
    return ["--add-data", f"{src}{os.pathsep}{dst}"]


def _trim_unused_qt(qt_dir: Path) -> None:
    """Remove unused Qt DLLs and plugins to shrink the bundle."""
    if not qt_dir.is_dir():
        return

    # Qt modules the app actually uses
    _KEEP_PREFIXES = {
        "Qt6Core",      # Core
        "Qt6Gui",       # GUI (image format plugins, platform support)
        "Qt6Widgets",   # Widgets
        "Qt6Network",   # Network (may be used internally by Qt)
    }

    removed_size = 0
    # Remove big unused Qt DLLs
    for f in qt_dir.iterdir():
        if f.is_file() and f.suffix.lower() == ".dll":
            name = f.stem
            if any(name.startswith(p) for p in _KEEP_PREFIXES):
                continue
            if name.startswith("Qt6"):
                sz = f.stat().st_size
                f.unlink()
                removed_size += sz
                print(f"  [remove] {f.name} (saved {sz / 1024 / 1024:.0f} MB)")

    # Remove unused plugin directories
    plugins_dir = qt_dir / "plugins"
    if plugins_dir.is_dir():
        for plugin_sub in list(plugins_dir.iterdir()):
            name = plugin_sub.name
            if name in ("platforms", "imageformats", "styles"):
                continue
            if plugin_sub.is_dir():
                sz = sum(f.stat().st_size for f in plugin_sub.rglob("*") if f.is_file())
                shutil.rmtree(plugin_sub)
                removed_size += sz
                print(f"  [remove-plugin] {name}/ (saved {sz / 1024 / 1024:.0f} MB)")

    # Remove QML directory (not needed)
    qml_dir = qt_dir / "qml"
    if qml_dir.is_dir():
        sz = sum(f.stat().st_size for f in qml_dir.rglob("*") if f.is_file())
        shutil.rmtree(qml_dir)
        removed_size += sz
        print(f"  [remove-qml] (saved {sz / 1024 / 1024:.0f} MB)")

    # Remove multimedia DLLs (avcodec, avformat, etc.)
    for f in qt_dir.iterdir():
        if f.is_file() and f.suffix.lower() == ".dll":
            name = f.stem.lower()
            if any(codec in name for codec in ("avcodec", "avformat", "avutil", "swresample", "swscale")):
                sz = f.stat().st_size
                f.unlink()
                removed_size += sz
                print(f"  [remove-media] {f.name} (saved {sz / 1024 / 1024:.0f} MB)")

    print(f"  Total saved: {removed_size / 1024 / 1024:.0f} MB")


def _print_size(path: Path) -> None:
    """Print human-readable total size of a directory."""
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    print(f"  [size] Total size: {total / 1024 / 1024:.0f} MB")


def _copy_setting_json(dist_root: Path) -> None:
    """Copy setting.json next to the exe for easy user editing."""
    src = PROJECT_ROOT / "setting.json"
    if src.exists():
        dst = dist_root / "setting.json"
        shutil.copy2(str(src), str(dst))
        print(f"  Copied setting.json -> {dst}")


def _write_version_file() -> Path:
    """Write a temporary version-info file for the executable metadata."""
    content = f"""# UTF-8
#
# For more details about fixed file info 'ffi' see:
# https://learn.microsoft.com/en-us/windows/win32/menurc/versioninfo-resource
#
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({VERSION.replace('.', ',')},0),
    prodvers=({VERSION.replace('.', ',')},0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0,0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [StringStruct('CompanyName', '{COMPANY_NAME}'),
          StringStruct('FileDescription', '{FILE_DESCRIPTION}'),
          StringStruct('FileVersion', '{VERSION}'),
          StringStruct('InternalName', 'screen-doodle'),
          StringStruct('LegalCopyright', 'Copyright (c) 2025'),
          StringStruct('OriginalFilename', 'screen-doodle.exe'),
          StringStruct('ProductName', 'Screen Doodle'),
          StringStruct('ProductVersion', '{VERSION}')])
      ]),
    VarFileInfo([VarStruct('Translation', [0x0409, 1200])])
  ]
)
"""
    path = PROJECT_ROOT / ".version-file.txt"
    path.write_text(content, encoding="utf-8")
    return path


def clean():
    """Remove build artifacts."""
    for p in [BUILD_DIR, DIST_DIR, SPEC_FILE, PROJECT_ROOT / ".version-file.txt"]:
        if p.is_dir():
            shutil.rmtree(p)
            print(f"Removed directory: {p}")
        elif p.is_file():
            p.unlink()
            print(f"Removed file: {p}")

    for spec in PROJECT_ROOT.glob("*.spec"):
        spec.unlink()
        print(f"Removed file: {spec}")
    print("[done] Clean complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Screen Doodle executable")
    parser.add_argument("--onefile", action="store_true", help="Build as single exe")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts")
    args = parser.parse_args()

    if args.clean:
        clean()
        sys.exit(0)

    if args.onefile:
        build_onefile()
    else:
        build_onedir()
