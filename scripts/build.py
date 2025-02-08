#!/usr/bin/env python3
import os
import platform
import shutil
import subprocess
from pathlib import Path


def clean_build_dirs():
    """Clean build and dist directories"""
    dirs_to_clean = ['build', 'dist']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)


def build_macos():
    """Build macOS application"""
    print("Building macOS application...")
    subprocess.run([
        'pyinstaller',
        '--clean',
        '--noconfirm',
        'build_config/macos_build.spec'
    ], check=True)

    # Create DMG (optional)
    # You might want to use create-dmg or similar tools here


def build_windows():
    """Build Windows application"""
    print("Building Windows application...")
    subprocess.run([
        'pyinstaller',
        '--clean',
        '--noconfirm',
        'build_config/windows_build.spec'
    ], check=True)

    # Create ZIP archive for portable distribution
    shutil.make_archive(
        'dist/FinancialAutomation-win64-portable',
        'zip',
        'dist/FinancialAutomation'
    )


def main():
    # Change to project root directory
    os.chdir(Path(__file__).parent.parent)

    # Clean previous builds
    clean_build_dirs()

    # Determine current platform
    system = platform.system()

    if system == 'Darwin':
        build_macos()
    elif system == 'Windows':
        build_windows()
    else:
        print(f"Building on {system} is not supported")
        return 1

    print("Build completed successfully!")
    return 0


if __name__ == "__main__":
    exit(main())
