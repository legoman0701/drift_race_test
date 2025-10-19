# src/drift/utils/paths.py
from pathlib import Path
import os, sys

def _find_assets_from(start: Path) -> Path | None:
    """Walk up from 'start' to root and return the first 'assets' dir found."""
    for p in [start, *start.parents]:
        cand = p / "assets"
        if cand.is_dir():
            return cand
    return None

def assets_dir() -> Path:
    # 1) Allow override for dev/testing
    override = os.environ.get("DRIFT_ASSETS_DIR")
    if override:
        p = Path(override)
        if p.is_dir():
            return p

    # 2) Frozen app (PyInstaller)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        # Newer PyInstaller onedir uses _internal by default
        internal = exe_dir / "_internal"
        base = internal if internal.is_dir() else exe_dir
        # Try exact location, then walk up just in case
        return _find_assets_from(base) or (base / "assets")

    # 3) Running from source
    # Start from this file’s folder and walk upward to find 'assets'
    here = Path(__file__).resolve()
    found = _find_assets_from(here)
    if found:
        return found

    # 4) Fallback to CWD (useful in some dev runners)
    cwd_found = _find_assets_from(Path.cwd())
    if cwd_found:
        return cwd_found

    # Last-ditch: project root guess (src/drift/app.py -> project root = parents[2])
    return here.parents[2] / "assets"

def asset_path(*parts: str) -> str:
    return str(assets_dir().joinpath(*parts))
