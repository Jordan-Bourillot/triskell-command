# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Triskell Command.

Build:  pyinstaller triskell_command.spec
Output: dist/Triskell Command/Triskell Command.exe
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_all

# Racine du projet
ROOT = Path(SPECPATH).resolve()
# Le repo a été renommé "triskell-core" (sans espace) — on garde un fallback
# sur l'ancien nom "Triskell Core" pour rétrocompatibilité.
_CORE_CANDIDATES = [
    ROOT.parent / "triskell-core",
    ROOT.parent / "Triskell Core",
]
CORE_ROOT = next((p for p in _CORE_CANDIDATES if p.exists()), _CORE_CANDIDATES[0])

# Inclut le mega_prompts.json du Core pour la couche IA + l'icône Triskell
datas = [
    (str(CORE_ROOT / "triskell_core" / "data" / "mega_prompts.json"),
     "triskell_core/data"),
    (str(ROOT / "assets" / "triskell.ico"), "assets"),
    (str(ROOT / "assets" / "triskell.png"), "assets"),
]

# Collect ALL the supabase ecosystem (lazy imports + namespace packages)
binaries_extra = []
hiddenimports_extra = []
for pkg in ("supabase", "gotrue", "postgrest", "realtime", "storage3",
            "supafunc", "httpx", "httpcore", "h11", "h2", "websockets",
            "deprecation", "strenum", "anyio"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries_extra += b
        hiddenimports_extra += h
    except Exception:
        pass  # package absent, skip

# CustomTkinter packagé : ses assets sont auto-détectés par PyInstaller
# si on l'importe normalement. On force juste les modules cachés.
hiddenimports = [
    "customtkinter",
    "PIL",
    "PIL._tkinter_finder",
    "pyperclip",
    "bs4",
    "lxml",
    "lxml.etree",
    # Supabase SDK + ses dépendances (lazy imports → PyInstaller ne les détecte pas seul)
    "supabase",
    "gotrue",
    "postgrest",
    "realtime",
    "storage3",
    "supafunc",
    "httpx",
    "websockets",
    # triskell_core
    "triskell_core",
    "triskell_core.prospect",
    "triskell_core.prospect.cli",
    "triskell_core.prospect.nightly",
    "triskell_core.prospect.core.prospect",
    "triskell_core.prospect.core.crm",
    "triskell_core.prospect.sources.denicheur",
    "triskell_core.prospect.sources.sirene",
    "triskell_core.prospect.sources.maps",
    "triskell_core.prospect.enrichers.web",
    "triskell_core.prospect.enrichers.linktree",
    "triskell_core.prospect.enrichers.footprint",
    "triskell_core.prospect.outreach.templates",
    "triskell_core.prospect.outreach.smtp_sender",
    "triskell_core.prospect.outreach.imap_listener",
    "triskell_core.ai.providers",
    "triskell_core.ai.builder",
    "triskell_core.ai.library",
    # vues Triskell Command
    "triskell_command.views.templates",
    "triskell_command.integrations.sales_tunnel",
    "triskell_command.updater",
    "triskell_command.widgets.splash",
    "triskell_command.widgets.prospect_dialog",
    "triskell_command.views.autopilot",
    "triskell_command.views.drafts",
    "triskell_command.widgets.help_dialog",
    "triskell_command.widgets.status_bar",
    "triskell_command.widgets.onboarding",
    "triskell_command.widgets.window_icon",
    "triskell_core.prospect.pipeline",
]


a = Analysis(
    ["run.py"],
    pathex=[str(ROOT), str(CORE_ROOT)],
    binaries=binaries_extra,
    datas=datas,
    hiddenimports=hiddenimports + hiddenimports_extra,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "numpy", "pandas", "scipy",
        "pytest", "test",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Triskell Command",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "triskell.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Triskell Command",
)
