# paths.py
from pathlib import Path
import sys
import os

def _base_dir() -> Path:
    """
    Dossier de base selon le contexte:
    - onefile PyInstaller: _MEIPASS (temp)
    - onedir / installé: dossier de l'exe, ou {exe}/_internal si présent
    - dev: dossier du script
    """
    # onefile (_MEIPASS)
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)

    # onedir / dev
    exe_or_file = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    exe_dir = exe_or_file.parent

    internal = exe_dir / "_internal"
    return internal if internal.exists() else exe_dir

def assets_dir() -> Path:
    """
    Renvoie la vraie racine des assets:
    - {base}/assets si présent
    - sinon ./assets (utile en dev si _base_dir() != cwd)
    """
    bd = _base_dir()
    cand = bd / "assets"
    if cand.exists():
        return cand
    # fallback dev
    cwd_assets = Path.cwd() / "assets"
    return cwd_assets if cwd_assets.exists() else cand  # on renvoie quand même un chemin plausible

def asset_path(*parts) -> Path:
    """Construit un chemin absolu à partir de morceaux relatifs aux assets."""
    return assets_dir().joinpath(*parts)

def normalize_asset_path(*parts) -> Path:
    """
    Prend:
      - un chemin absolu, ou
      - 'assets/...', ou
      - 'track/map1/main.png' (relatif aux assets), ou
      - plusieurs parties: ("track", "map1", "main.png")
    et retourne un Path absolu vers l'asset réel (_internal/assets ou autre).
    """
    # If multiple parts provided, join them first
    if len(parts) > 1:
        # Multiple path parts provided, join them
        return assets_dir().joinpath(*parts)
    elif len(parts) == 0:
        return assets_dir()
    
    # Single argument - could be string or Path
    p = Path(parts[0])
    if p.is_absolute():
        return p

    path_parts = p.parts
    if path_parts and path_parts[0].lower() == "assets":
        # on enlève le préfixe "assets"
        return assets_dir().joinpath(*path_parts[1:])

    # sinon on considère que c'est relatif à la racine assets
    return assets_dir() / p

def chdir_to_exe_folder_if_frozen():
    """
    Optionnel mais recommandé: fixe le CWD sur le dossier de l'exe quand packagé.
    Ça évite que des chemins relatifs restants partent en balade.
    """
    if getattr(sys, "frozen", False):
        os.chdir(Path(sys.executable).parent)

def get_available_cars():
    """
    Scans the given directory and returns a sorted list of all car folder names.
    Ignores files and hidden directories.
    """
    cars_directory = assets_dir() / "cars"
    available_cars = []
    
    # Check if the directory actually exists to prevent crashes
    if not os.path.exists(cars_directory):
        print(f"Warning: Directory '{cars_directory}' not found!")
        return available_cars

    # Loop through everything in the assets/car folder
    for item in os.listdir(cars_directory):
        item_path = os.path.join(cars_directory, item)
        
        # Make sure it's a directory AND not a hidden folder (like .git or .DS_Store)
        if os.path.isdir(item_path) and not item.startswith('.'):
            available_cars.append(item)
            
    # Sort alphabetically so the order in your UI is always consistent
    return sorted(available_cars)
