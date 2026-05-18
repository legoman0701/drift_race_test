# paths.py
from pathlib import Path
import sys
import os


def _read_map_index_entries():
    """Return ordered track folder names from assets/track/map_index.txt."""
    index_path = assets_dir() / "track" / "map_index.txt"
    entries = []
    try:
        if index_path.exists():
            with open(index_path, "r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    entries.append(line)
    except Exception:
        return []
    return entries


def get_track_folders():
    """Return available track folders in numbered order (1-based via map_index)."""
    entries = _read_map_index_entries()
    if entries:
        return entries

    # Fallback for old setups without map_index.txt
    track_root = assets_dir() / "track"
    if not track_root.exists():
        return []

    folders = []
    for item in sorted(track_root.iterdir()):
        if not item.is_dir():
            continue
        # Ignore generated/utility folders if present
        if item.name.startswith("chunks"):
            continue
        folders.append(item.name)
    return folders


def resolve_track_folder(track_key):
    """Resolve map key like 'map2' to actual folder name from map_index.txt."""
    key = str(track_key)
    if not key.lower().startswith("map"):
        return key

    number = key[3:]
    if not number.isdigit():
        return key

    map_num = int(number)
    folders = get_track_folders()
    if 1 <= map_num <= len(folders):
        return folders[map_num - 1]
    return key


def get_track_base_image_path(track_key):
    """Return a usable base track image path for map key (main -> bg -> fg)."""
    for filename in ("main.png", "main_bg.png", "main_fg.png"):
        candidate = asset_path("track", track_key, filename)
        if candidate.exists():
            return candidate
    return asset_path("track", track_key, "main.png")


def _resolve_track_parts(parts):
    """Map ('track', 'mapN', ...) to ('track', '<folder_from_index>', ...)."""
    if len(parts) >= 2 and str(parts[0]).lower() == "track":
        resolved = [str(parts[0]), resolve_track_folder(parts[1])]
        resolved.extend(str(p) for p in parts[2:])
        return resolved
    return [str(p) for p in parts]

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
    return assets_dir().joinpath(*_resolve_track_parts(parts))

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
        return assets_dir().joinpath(*_resolve_track_parts(parts))
    elif len(parts) == 0:
        return assets_dir()
    
    # Single argument - could be string or Path
    p = Path(parts[0])
    if p.is_absolute():
        return p

    # Rewrite track/mapN/... to track/<map_index_entry>/...
    p_parts = list(p.parts)
    if len(p_parts) >= 2 and str(p_parts[0]).lower() == "track":
        p_parts[1] = resolve_track_folder(p_parts[1])
        p = Path(*p_parts)

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

def get_available_sprite_layers(car_type: str):
    """
    Auto-detects available sprite layers for a car by scanning its directory.
    Returns ordered list of sprite layer paths.
    
    Standard layer order: Shadow_Map, Diffuse, Light_Spray, Palette
    Each layer should have 64 frames: Image0000.png to Image0063.png
    
    Args:
        car_type: Car folder name (e.g., 'ae86', '911')
    
    Returns:
        List of path templates with {i:04d} placeholder for frame numbers
    """
    car_dir = assets_dir() / "cars" / car_type
    
    if not car_dir.exists():
        print(f"Warning: Car directory '{car_dir}' not found!")
        return []
    
    # Standard layer folders in expected order
    layer_folders = ["Shadow_Map", "Diffuse", "Light_Spray", "Palette"]
    available_layers = []
    
    for layer_folder in layer_folders:
        layer_path = car_dir / layer_folder
        
        # Check if the layer folder exists
        if layer_path.exists() and layer_path.is_dir():
            # Verify at least one frame image exists
            test_frame = layer_path / "Image0000.png"
            if test_frame.exists():
                # Use relative path from assets for consistency
                path_template = f"cars/{car_type}/{layer_folder}/Image{{i:04d}}.png"
                available_layers.append(path_template)
            else:
                print(f"Warning: No Image0000.png found in {layer_path}")
    
    if not available_layers:
        print(f"Warning: No valid sprite layers found for car '{car_type}'")
    
    return available_layers
