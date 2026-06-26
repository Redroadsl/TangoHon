"""
Pack editor.py and exam.py into standalone executables.
"""
import os
import sys
import subprocess
import shutil

SCRIPTS = [
    ("editor.py", "editor"),
    ("exam.py", "exam"),
]

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")
BUILD = os.path.join(HERE, "build")


def ensure_pyinstaller():
    try:
        import PyInstaller
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller"]
        )


def clean_build_artifacts():
    if os.path.isdir(BUILD):
        shutil.rmtree(BUILD)
    spec_files = [f for f in os.listdir(HERE) if f.endswith(".spec")]
    for f in spec_files:
        os.remove(os.path.join(HERE, f))


def clean_dist():
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)


def pack():
    ensure_pyinstaller()
    clean_build_artifacts()
    clean_dist()

    for src, name in SCRIPTS:
        src_path = os.path.join(HERE, src)
        if not os.path.exists(src_path):
            print(f"Warning: {src_path} not found, skipping")
            continue

        print(f"\n{'='*60}")
        print(f"Packaging {src} -> {name}.exe")
        print(f"{'='*60}")

        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--noconfirm",
            "--distpath", DIST,
            "--workpath", BUILD,
            "--specpath", HERE,
            "--name", name,
            "--windowed",
            src_path,
        ]

        subprocess.check_call(cmd)

        exe_path = os.path.join(DIST, f"{name}.exe")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"  -> {exe_path} ({size_mb:.1f} MB)")

    clean_build_artifacts()
    print(f"\nDone. Output directory: {DIST}")
    print(f"Files: {', '.join(os.path.join(DIST, f'{n}.exe') for _, n in SCRIPTS)}")


if __name__ == "__main__":
    pack()
