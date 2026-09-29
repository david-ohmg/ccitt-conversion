# PyInstaller spec for the double-clickable macOS app.
# Build with:  ./build_app.sh   (output: dist/CCITT Converter.app)

a = Analysis(
    ["main.py"],
    hiddenimports=["tkinterdnd2"],
    excludes=["PyInstaller"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CCITT Converter",
    console=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="CCITT Converter")

app = BUNDLE(
    coll,
    name="CCITT Converter.app",
    icon="icon.icns",
    bundle_identifier="com.guitardave.ccitt-converter",
    version="0.1.0",
    info_plist={
        "CFBundleDisplayName": "CCITT Converter",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # Lets audio files and folders be dropped onto the app icon.
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Audio",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["public.audio", "public.movie", "public.folder"],
            }
        ],
    },
)
