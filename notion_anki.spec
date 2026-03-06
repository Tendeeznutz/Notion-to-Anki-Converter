# notion_anki.spec
# PyInstaller build specification for Notion → Anki Converter.
#
# Build commands
# ──────────────
#   Windows :  pyinstaller notion_anki.spec
#   macOS   :  pyinstaller notion_anki.spec
#
# Output
# ──────
#   Windows : dist/NotionToAnki.exe   (single-file portable executable)
#   macOS   : dist/NotionToAnki.app   (app bundle, then zipped by CI)

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Collect CustomTkinter assets (themes, icons, fonts) ─────────────────────
ctk_datas = collect_data_files("customtkinter", include_py_files=False)

# ── Hidden imports that PyInstaller's static analyser can miss ───────────────
hidden = [
    # tkinter backends
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    # customtkinter
    *collect_submodules("customtkinter"),
    # PIL / Pillow (used by CustomTkinter internally)
    "PIL._tkinter_finder",
    # requests / urllib3 internals
    "requests",
    "urllib3",
    "charset_normalizer",
    "idna",
    "certifi",
    # genanki internals
    "genanki",
    # our own package tree
    "src",
    "src.converter",
    "src.onboarding",
    "src.llm.ollama_client",
    "src.llm.text_processor",
    "src.parser.file_walker",
    "src.parser.markdown_parser",
    "src.anki.deck_builder",
    "src.utils.image_utils",
]

# ── Analysis ─────────────────────────────────────────────────────────────────
a = Analysis(
    ["src/main.py"],
    # Project root must be on the path so `import src.*` resolves.
    pathex=[str(Path(".").resolve())],
    binaries=[],
    datas=ctk_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # dev / test tools — keep the binary lean
        "pytest",
        "hypothesis",
        "black",
        "mypy",
        "ruff",
        "IPython",
        "jupyter",
        "notebook",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Executable ───────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="NotionToAnki",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Windowed mode — no console window on Windows / macOS.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,       # macOS: let CTk handle its own argv
    target_arch=None,           # None = native arch; set to "universal2" for fat binary
    codesign_identity=None,
    entitlements_file=None,
    # Windows-only metadata
    version=None,               # set via --version-file if needed
    icon=None,                  # replace with "assets/icon.ico" on Windows
)

# ── macOS app bundle ─────────────────────────────────────────────────────────
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="NotionToAnki.app",
        icon=None,              # replace with "assets/icon.icns" on macOS
        bundle_identifier="com.notionanki.converter",
        info_plist={
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.15",
        },
    )
