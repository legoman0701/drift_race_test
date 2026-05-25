import pygame, json, time, math, random
import drift.config.const as const
from drift.render.map_chunks import ChunkedMap
from drift.ui.ui_helpers import invalidate_ui_text_cache, get_cached_text
from drift.ui.button import Button
from drift.core.helpers import rand_code
from drift.net.communication import connect_to_relay, recv_jsons
from drift.ui.slider import Slider
from drift.config.settings import physics_controls, audio_volumes
from drift.tools.paths import asset_path, normalize_asset_path, get_track_base_image_path, get_track_folders

AVAILABLE_CARS = const.AVAILABLE_CARS

# Game setup state (shared across new_game and join_game UI)
_game_setup = {
    "username": "",
    "username_active": False,
    "selected_car": const.AVAILABLE_CARS[0] if const.AVAILABLE_CARS else "AE86",  # Default car
    "selected_track": "track1",  # Default track
    "selected_mode": "mode1",  # Default mode
    "room_code": "",  # For join game
    "code_active": False,  # For join game code input
    "error_message": None,  # For displaying errors
}

# Controls state
_controls_state = {
    "waiting_for_key": None,  # Which bind is waiting for input (e.g., "UP_KEY")
    "selected_bind": None,  # Currently selected/hovered bind
    "selected_gamepad": None,  # Index of the active/connected gamepad
    "active_joystick_object": None,  # Active pygame joystick object selected from UI
}

# Car rotation state for selection screens
_car_rotation_angle = 0.0  # Global rotation angle for all car sprites

# Color palette state for car customization
_color_palette = {
    "color1": (255, 0, 0),    # Red channel replacement
    "color2": (0, 255, 0),    # Green channel replacement
    "color3": (0, 0, 255),    # Blue channel replacement
    "active_picker": None,    # Which color is being edited (1, 2, 3, or None)
}
_palette_initialized_for_car = None

# Game options panel state (lobby slide-out menu)
_game_options = {
    "panel_open": False,
    "panel_page": "main",   # "main", "mode", "ai"
    "selected_car_index": 0,
    "selected_map_index": 0,
    "selected_mode_index": 0,
    "choice": 2,
    "ai_amount": 0,
    "ai_difficulty": "Random",
}

# cache
_map_meta_cache = {}
_map_thumb_cache = {}
_illustration_cache = {}

_MODE_OPTIONS = [
    ("mode1", "ClassicRace"),
    ("mode2", "BestLap"),
    ("mode3", "DriftRace"),
]


def get_tutorial_track_key() -> str:
    """Return track key (trackN) for the first map containing tutorial steps."""
    folders = get_track_folders()
    for idx, folder in enumerate(folders, start=1):
        try:
            meta_path = asset_path("track", folder, "map_meta.json")
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            tutorial = meta.get("tutorial") if isinstance(meta, dict) else None
            steps = tutorial.get("steps") if isinstance(tutorial, dict) else None
            if isinstance(steps, list) and len(steps) > 0:
                return f"track{idx}"
        except Exception:
            continue
    return "track1"

def get_game_options():
    """Get current game options state."""
    return _game_options

def set_game_option(key, value):
    """Set a game option value."""
    _game_options[key] = value

def _get_map_names():
    """Return list of (track_key, display_name) for non-tutorial maps."""
    maps = []
    for i in range(1, const.TOTAL_MAPS + 1):
        key = f"track{i}"
        if key not in _map_meta_cache:
            try:
                meta_path = asset_path("track", f"map{i}", "map_meta.json")
                with open(meta_path, "r", encoding="utf-8") as fh:
                    _map_meta_cache[key] = json.load(fh)
            except Exception:
                _map_meta_cache[key] = {"map_name": f"Map {i}"}
        meta = _map_meta_cache.get(key) or {}
        tutorial = meta.get("tutorial") if isinstance(meta, dict) else None
        tutorial_steps = tutorial.get("steps") if isinstance(tutorial, dict) else None
        # Keep tutorial map out of the regular map selection screen.
        if isinstance(tutorial_steps, list) and len(tutorial_steps) > 0:
            continue
        maps.append((key, _map_meta_cache[key].get("map_name", f"Map {i}")))
    return maps

def _get_map_thumbnail(map_index, thumb_w=100, thumb_h=70):
    """Get a scaled thumbnail of a map image. Cached."""
    key = f"map{map_index + 1}"
    if key in _map_thumb_cache:
        return _map_thumb_cache[key]
    try:
        img = pygame.image.load(get_track_base_image_path(key)).convert()
        thumb = pygame.transform.smoothscale(img, (thumb_w, thumb_h))
        _map_thumb_cache[key] = thumb
        return thumb
    except Exception:
        return None

def _get_illustration_thumbnail(key, thumb_w=120, thumb_h=65):
    """Get a scaled thumbnail of a map illustration. Cached."""
    if key in _illustration_cache:
        return _illustration_cache[key]

    # Support both human-readable labels (e.g. "Classic Race") and file-style keys
    # (e.g. "ClassicRace") for illustration asset lookup.
    candidates = []
    raw_key = str(key)
    normalized = "".join(ch for ch in raw_key if ch.isalnum())
    for name in (raw_key, normalized):
        if name and name not in candidates:
            candidates.append(name)

    for candidate in candidates:
        try:
            img = pygame.image.load(normalize_asset_path("illustrations", f"{candidate}.png")).convert_alpha()
            thumb = pygame.transform.smoothscale(img, (thumb_w, thumb_h))
            _illustration_cache[key] = thumb
            return thumb
        except Exception:
            continue

    return None


def _resolve_car_folder(car_type):
    """Resolve car folder using case-insensitive lookup from available cars."""
    car_str = str(car_type)
    for car in AVAILABLE_CARS:
        if str(car).lower() == car_str.lower():
            return car
    return car_str


def _normalize_selected_car(selected_car):
    """Return a selected car value guaranteed to match AVAILABLE_CARS casing."""
    if AVAILABLE_CARS:
        resolved = _resolve_car_folder(selected_car)
        if resolved in AVAILABLE_CARS:
            return resolved
        return AVAILABLE_CARS[0]
    return selected_car

def set_palette_colors_from_car(palette_colors):
    """Set palette colors from car specs.
    
    Args:
        palette_colors: Tuple of 3 RGB tuples (color1, color2, color3)
    """
    global _color_palette
    if palette_colors and len(palette_colors) >= 3:
        _color_palette["color1"] = tuple(palette_colors[0]) if isinstance(palette_colors[0], (list, tuple)) else palette_colors[0]
        _color_palette["color2"] = tuple(palette_colors[1]) if isinstance(palette_colors[1], (list, tuple)) else palette_colors[1]
        _color_palette["color3"] = tuple(palette_colors[2]) if isinstance(palette_colors[2], (list, tuple)) else palette_colors[2]

def _load_car_specs(car_type):
    """Load car specifications from JSON file."""
    try:
        car_folder = _resolve_car_folder(car_type)
        spec_path = normalize_asset_path("cars", car_folder, "specs.json")
        with open(spec_path, "r", encoding="utf-8") as fh:
            specs = json.load(fh)
        metadata = specs.get("metadata", {}) or {}
        # manufacturer = metadata.get("manufacturer", specs.get("manufacturer", "Unknown"))
        model = metadata.get("short", specs.get("short", "Unknown"))
        return model
    except Exception as e:
        print(f"Warning: Could not load specs for {car_type}: {e}")
        return "Unknown"


def _init_palette_for_selected_car(car_type, force=False):
    """Initialize shared palette from selected car default palette in specs."""
    global _palette_initialized_for_car

    car_folder = _resolve_car_folder(car_type)
    if not force and _palette_initialized_for_car == car_folder:
        return

    try:
        spec_path = normalize_asset_path("cars", car_folder, "specs.json")
        with open(spec_path, "r", encoding="utf-8") as fh:
            specs = json.load(fh)
        palette = specs.get("specs", {}).get("default_pallet")
        if isinstance(palette, (list, tuple)) and len(palette) >= 3:
            set_palette_colors_from_car(palette)
            from drift.ui.ui import invalidate_palette_cache
            invalidate_palette_cache()
            _palette_initialized_for_car = car_folder
    except Exception as e:
        print(f"Warning: Could not initialize palette for {car_type}: {e}")

def _update_car_rotation(dt):
    """Update the global car rotation angle for selection screens."""
    global _car_rotation_angle
    # Rotate at 45 degrees per second (π/4 radians per second)
    _car_rotation_angle += (math.pi / 4) * dt
    if _car_rotation_angle >= 2 * math.pi:
        _car_rotation_angle -= 2 * math.pi

def get_palette_colors():
    """Get current color palette as tuple of 3 RGB tuples."""
    return (_color_palette["color1"], _color_palette["color2"], _color_palette["color3"])

def draw_color_palette_picker(ui_surf, font_small):
    """Draw color palette picker UI in top right corner.
    
    Controls:
    - Click a color box to select it
    - R/F: Adjust red channel (+/-)
    - T/G: Adjust green channel (+/-)
    - Y/H: Adjust blue channel (+/-)
    - Hold SHIFT for faster adjustment (20 vs 5)
    - ESC: Deselect color
    
    Returns:
        dict: Rectangles for each color picker for click detection
    """
    # Position in top right corner
    padding = 10
    box_size = 40
    spacing = 10
    
    x_start = const.WINDOW_WIDTH - (box_size * 3 + spacing * 2 + padding)
    y_start = const.TOP_LINE_Y + padding
    
    rects = {}
    
    # Calculate background size
    if _color_palette["active_picker"] is not None:
        bg_height = 55 + box_size + 25
    else:
        bg_height = 25 + box_size + 25
    
    bg_width = box_size * 3 + spacing * 2 + 20
    
    # Draw semi-transparent background
    bg_surf = pygame.Surface((bg_width, bg_height), pygame.SRCALPHA)
    bg_surf.fill((20, 20, 26, 220))
    ui_surf.blit(bg_surf, (x_start - 10, y_start))
    
    # Draw label
    label = font_small.render("Palette Colors:", True, const.WHITE_240)
    ui_surf.blit(label, (x_start, y_start + 5))
    
    # Draw controls hint if a color is selected
    if _color_palette["active_picker"] is not None:
        hint_y = y_start + 25
        hint_text = ["R/F:Red T/G:Grn Y/H:Blu", "SHIFT: Fast ESC: Done", "Click: Random color"]
        for i, hint in enumerate(hint_text):
            hint_surf = font_small.render(hint, True, const.GREY_180)
            ui_surf.blit(hint_surf, (x_start, hint_y + i * 15))
        y_boxes = y_start + 55
    else:
        hint_text = "Click box: Random color"
        hint_surf = font_small.render(hint_text, True, const.GREY_180)
        ui_surf.blit(hint_surf, (x_start, y_start + 20))
        y_boxes = y_start + 40
    
    # Draw 3 color boxes
    for i in range(1, 4):
        x_pos = x_start + (i - 1) * (box_size + spacing)
        color_key = f"color{i}"
        color = _color_palette[color_key]
        
        # Color box
        rect = pygame.Rect(x_pos, y_boxes, box_size, box_size)
        pygame.draw.rect(ui_surf, color, rect)
        pygame.draw.rect(ui_surf, const.WHITE if _color_palette["active_picker"] == i else const.GREY_180, rect, 2)
        
        # Label below box
        num_label = font_small.render(str(i), True, const.WHITE_240)
        ui_surf.blit(num_label, (x_pos + box_size//2 - num_label.get_width()//2, y_boxes + box_size + 5))
        
        rects[i] = rect
    
    return rects

def handle_palette_picker_click(pos, rects):
    """Handle click on palette picker.
    
    Clicking a color box generates a random color and selects that box.
    
    Returns:
        int or None: Color number (1, 2, 3) if clicked, None otherwise
    """
    from drift.ui.ui import invalidate_palette_cache
    
    for color_num, rect in rects.items():
        if rect.collidepoint(pos):
            # Generate random color
            random_color = (
                random.randint(0, 255),
                random.randint(0, 255),
                random.randint(0, 255)
            )
            color_key = f"color{color_num}"
            _color_palette[color_key] = random_color
            _color_palette["active_picker"] = color_num
            invalidate_palette_cache()  # Clear cache so changes are visible
            return color_num
    return None

def handle_palette_picker_keypress(ev):
    """Handle keyboard input for palette color adjustment.
    
    Uses arrow keys to adjust RGB values of active color.
    """
    from drift.ui.ui import invalidate_palette_cache
    
    active = _color_palette["active_picker"]
    if active is None:
        return
    
    color_key = f"color{active}"
    r, g, b = _color_palette[color_key]
    
    step = 5 if not (ev.mod & pygame.KMOD_SHIFT) else 20
    
    color_changed = False
    if ev.key == pygame.K_r:
        r = min(255, r + step)
        color_changed = True
    elif ev.key == pygame.K_f:
        r = max(0, r - step)
        color_changed = True
    elif ev.key == pygame.K_t:
        g = min(255, g + step)
        color_changed = True
    elif ev.key == pygame.K_g:
        g = max(0, g - step)
        color_changed = True
    elif ev.key == pygame.K_y:
        b = min(255, b + step)
        color_changed = True
    elif ev.key == pygame.K_h:
        b = max(0, b - step)
        color_changed = True
    elif ev.key == pygame.K_ESCAPE:
        _color_palette["active_picker"] = None
        return
    
    if color_changed:
        _color_palette[color_key] = (r, g, b)
        invalidate_palette_cache()  # Clear cache so changes are visible immediately

def draw_menu(ui_surf, font_big, font_medium, is_host):
    """Draw the game lobby/waiting room with start button (host only)."""
    
    btn_width = const.BTN_WIDTH
    btn_height = const.BTN_HEIGHT
    center_x = const.WINDOW_WIDTH // 2
    
    # Start button (bottom center) - only if host
    if is_host:
        start_btn_y = const.WINDOW_HEIGHT - 150  # Bottom area
        start_btn = Button("Start Game", center_x - btn_width // 2, start_btn_y, btn_width, btn_height, const.GREEN, ["lobby"])
        start_btn.draw(ui_surf, "lobby")
        
        return {"start_btn": start_btn.rect}
    
    return {}


# ── Game Options Panel Constants ──
_PANEL_WIDTH = 210
_PANEL_PADDING = 10
_TOGGLE_SIZE = 40
_SECTION_BOX_W = 130
_SECTION_BOX_H = 90
_ARROW_BTN_SIZE = 35
_NAV_BTN_W = 180
_NAV_BTN_H = 45
_PM_BTN_SIZE = 40  # plus/minus button size
_DIFF_BTN_W = 80
_DIFF_BTN_H = 36
_CONTENT_PAD = 8   # vertical padding inside the panel rect


def draw_game_options_panel(ui_surf, font_big, font_medium, font_small, is_host,
                            car_sprites_cache, room_clients_count=1, dt=0.016):
    """Draw the slide-out game options panel on the right side of the lobby.

    Returns dict of clickable rects for event handling.
    """
    _update_car_rotation(dt)
    rects = {}
    panel_x = const.WINDOW_WIDTH - _PANEL_WIDTH
    cx = panel_x + _PANEL_WIDTH // 2
    fh_m = font_medium.get_height()

    # ── Closed state: toggle at screen centre-right ──
    if not _game_options["panel_open"]:
        toggle_x = const.WINDOW_WIDTH - _TOGGLE_SIZE - 5
        toggle_y = const.WINDOW_HEIGHT // 2 - _TOGGLE_SIZE // 2
        toggle_rect = pygame.Rect(toggle_x, toggle_y, _TOGGLE_SIZE, _TOGGLE_SIZE)
        pygame.draw.rect(ui_surf, (100, 100, 110), toggle_rect)
        pygame.draw.rect(ui_surf, const.WHITE, toggle_rect, 2)
        arrow_surf = font_big.render("<", True, const.WHITE_240)
        ui_surf.blit(arrow_surf, (toggle_rect.centerx - arrow_surf.get_width() // 2,
                                   toggle_rect.centery - arrow_surf.get_height() // 2))
        rects["toggle"] = toggle_rect
        return rects

    # ── Compute content height for the current page ──
    page = _game_options["panel_page"]
    if page == "main":
        title_text = "Game Options"
        content_h = _CONTENT_PAD
        content_h += fh_m + 3 + _SECTION_BOX_H + 8          # Car
        if is_host:
            content_h += fh_m + 3 + _SECTION_BOX_H + 8      # Map
            content_h += 5 + _NAV_BTN_H + 8                  # Mode nav
            content_h += _NAV_BTN_H                          # AI nav
        content_h += _CONTENT_PAD
    elif page == "mode":
        title_text = "Mode Options"
        content_h = _CONTENT_PAD
        content_h += fh_m + 3 + _SECTION_BOX_H + 8          # Mode selector
        content_h += 5 + fh_m + 5 + _PM_BTN_SIZE            # Choice
        content_h += _CONTENT_PAD
    elif page == "ai":
        title_text = "AI Options"
        content_h = _CONTENT_PAD
        content_h += fh_m + 5 + _PM_BTN_SIZE + 15           # Amount
        content_h += fh_m + 5 + 2 * (_DIFF_BTN_H + 6) - 6  # Difficulty grid
        content_h += _CONTENT_PAD
    else:
        return rects

    # ── Centre everything vertically ──
    title_surf = font_medium.render(title_text, True, const.WHITE_240)
    title_h = title_surf.get_height()
    title_gap = 5
    total_h = title_h + title_gap + content_h
    top_y = const.WINDOW_HEIGHT // 2 - total_h // 2

    # Title (outside the rect)
    ui_surf.blit(title_surf, (cx - title_surf.get_width() // 2, top_y))

    # Back button for sub-pages (outside the rect, next to title)
    if page in ("mode", "ai"):
        back_rect = pygame.Rect(panel_x + 5, top_y, 30, title_h)
        pygame.draw.rect(ui_surf, (80, 80, 90), back_rect)
        pygame.draw.rect(ui_surf, const.WHITE, back_rect, 1)
        back_arr = font_medium.render("<", True, const.WHITE_240)
        ui_surf.blit(back_arr, (back_rect.centerx - back_arr.get_width() // 2,
                                 back_rect.centery - back_arr.get_height() // 2))
        rects["back"] = back_rect

    # Panel rect (tight fit around content)
    rect_y = top_y + title_h + title_gap
    bg_surf = pygame.Surface((_PANEL_WIDTH, content_h), pygame.SRCALPHA)
    bg_surf.fill((20, 20, 26, 230))
    ui_surf.blit(bg_surf, (panel_x, rect_y))
    pygame.draw.rect(ui_surf, const.WHITE, (panel_x, rect_y, _PANEL_WIDTH, content_h), 1)

    # Toggle button (vertically centred with the rect)
    toggle_x = panel_x - _TOGGLE_SIZE - 5
    toggle_y = rect_y + content_h // 2 - _TOGGLE_SIZE // 2
    toggle_rect = pygame.Rect(toggle_x, toggle_y, _TOGGLE_SIZE, _TOGGLE_SIZE)
    pygame.draw.rect(ui_surf, (100, 100, 110), toggle_rect)
    pygame.draw.rect(ui_surf, const.WHITE, toggle_rect, 2)
    arrow_surf = font_big.render(">", True, const.WHITE_240)
    ui_surf.blit(arrow_surf, (toggle_rect.centerx - arrow_surf.get_width() // 2,
                               toggle_rect.centery - arrow_surf.get_height() // 2))
    rects["toggle"] = toggle_rect

    # ── Draw page content inside the rect ──
    if page == "main":
        _draw_options_main_page(ui_surf, font_big, font_medium, font_small,
                                is_host, car_sprites_cache, panel_x, rect_y, rects)
    elif page == "mode":
        _draw_options_mode_page(ui_surf, font_big, font_medium, font_small,
                                car_sprites_cache, panel_x, rect_y, rects)
    elif page == "ai":
        _draw_options_ai_page(ui_surf, font_big, font_medium, font_small,
                              panel_x, rect_y, room_clients_count, rects)

    return rects


def _draw_options_main_page(ui_surf, font_big, font_medium, font_small,
                            is_host, car_sprites_cache, px, py, rects):
    """Draw the main options page content (Car, Map, Mode, AI)."""
    cx = px + _PANEL_WIDTH // 2
    y = py + _CONTENT_PAD

    # ── Car section ──
    y = _draw_item_selector(ui_surf, font_medium, font_small, car_sprites_cache,
                            "Car", _game_options["selected_car_index"],
                            AVAILABLE_CARS, px, y, rects, "car", show_car=True)

    if is_host:
        # ── Map section ──
        maps = _get_map_names()
        if maps:
            # Clamp selection to non-tutorial map list and keep setup in sync.
            safe_idx = _game_options["selected_map_index"] % len(maps)
            _game_options["selected_map_index"] = safe_idx
            _game_setup["selected_track"] = maps[safe_idx][0]
        map_labels = [m[1] for m in maps]
        y = _draw_item_selector(ui_surf, font_medium, font_small, None,
                                "Map", _game_options["selected_map_index"],
                                map_labels, px, y, rects, "map", show_map=True)

        # ── Mode nav button ──
        y += 5
        nav_x = cx - _NAV_BTN_W // 2
        mode_rect = pygame.Rect(nav_x, y, _NAV_BTN_W, _NAV_BTN_H)
        pygame.draw.rect(ui_surf, (100, 100, 110), mode_rect)
        pygame.draw.rect(ui_surf, const.GREY_180, mode_rect, 1)
        lbl = font_medium.render("mode", True, const.WHITE_240)
        ui_surf.blit(lbl, (mode_rect.x + 15, mode_rect.centery - lbl.get_height() // 2))
        arr = font_big.render(">", True, const.WHITE_240)
        ui_surf.blit(arr, (mode_rect.right - arr.get_width() - 10,
                           mode_rect.centery - arr.get_height() // 2))
        rects["nav_mode"] = mode_rect
        y += _NAV_BTN_H + 8

        # ── AI nav button ──
        ai_rect = pygame.Rect(nav_x, y, _NAV_BTN_W, _NAV_BTN_H)
        pygame.draw.rect(ui_surf, (100, 100, 110), ai_rect)
        pygame.draw.rect(ui_surf, const.GREY_180, ai_rect, 1)
        lbl = font_medium.render("ai", True, const.WHITE_240)
        ui_surf.blit(lbl, (ai_rect.x + 15, ai_rect.centery - lbl.get_height() // 2))
        arr = font_big.render(">", True, const.WHITE_240)
        ui_surf.blit(arr, (ai_rect.right - arr.get_width() - 10,
                           ai_rect.centery - arr.get_height() // 2))
        rects["nav_ai"] = ai_rect


def _draw_item_selector(ui_surf, font_medium, font_small, car_sprites_cache,
                        label, index, items, px, y, rects, prefix,
                        show_car=False, show_map=False, show_illustration=False, car_id_override=None):
    """Draw a selection widget (used for Car, Map, Mode).

    Returns the new y position after drawing.
    """
    cx = px + _PANEL_WIDTH // 2

    # Section label
    lbl = font_medium.render(label, True, const.WHITE_240)
    ui_surf.blit(lbl, (cx - lbl.get_width() // 2, y))
    y += lbl.get_height() + 3

    total = len(items)
    if total == 0:
        return y + _SECTION_BOX_H + 10

    safe_index = index % total

    # Item display box with green border
    box_x = px + _PANEL_PADDING
    box_rect = pygame.Rect(box_x, y, _SECTION_BOX_W, _SECTION_BOX_H)
    pygame.draw.rect(ui_surf, (30, 30, 36), box_rect)
    pygame.draw.rect(ui_surf, const.GREEN, box_rect, 2)

    # Draw content inside the box
    if show_car and car_sprites_cache:
        car_id = car_id_override if car_id_override else items[safe_index]
        text_over = items[safe_index] if car_id_override else None
        _draw_rotating_car(ui_surf, car_id, box_rect, font_small, car_sprites_cache, _car_rotation_angle, text_override=text_over)
    elif show_map:
        item_name = items[safe_index]
        name_surf = font_small.render(item_name, True, const.WHITE_240)
        ui_surf.blit(name_surf, (box_rect.centerx - name_surf.get_width() // 2, box_rect.y + 6))
        thumb = _get_map_thumbnail(safe_index, _SECTION_BOX_W - 4, _SECTION_BOX_H - 25)
        if thumb: ui_surf.blit(thumb, (box_rect.x + 2, box_rect.y + 22))
    elif show_illustration: # mode icon
        item_name = items[safe_index]
        name_surf = font_small.render(item_name, True, const.WHITE_240)
        ui_surf.blit(name_surf, (box_rect.centerx - name_surf.get_width() // 2, box_rect.y + 6))
        img = _get_illustration_thumbnail(item_name, _SECTION_BOX_W - 10, _SECTION_BOX_H - 25)
        if img: ui_surf.blit(img, (box_rect.x + _SECTION_BOX_W//2 - img.get_width()//2, box_rect.y + 22))
    else:
        item_name = items[safe_index]
        name_surf = font_medium.render(item_name, True, const.WHITE_240)
        ui_surf.blit(name_surf, (box_rect.centerx - name_surf.get_width() // 2,
                                  box_rect.centery - name_surf.get_height() // 2))

    # Up/Down arrows and counter on the right side
    arr_x = box_x + _SECTION_BOX_W + 3
    up_rect = pygame.Rect(arr_x, y, _ARROW_BTN_SIZE, _ARROW_BTN_SIZE)
    pygame.draw.rect(ui_surf, (60, 60, 70), up_rect)
    pygame.draw.rect(ui_surf, const.WHITE, up_rect, 1)
    up_sym = font_medium.render("^", True, const.WHITE_240)
    ui_surf.blit(up_sym, (up_rect.centerx - up_sym.get_width() // 2,
                           up_rect.centery - up_sym.get_height() // 2))
    rects[f"{prefix}_up"] = up_rect

    # Counter
    counter_text = f"{safe_index + 1}/{total}"
    counter_surf = font_small.render(counter_text, True, const.WHITE_240)
    counter_y = y + _ARROW_BTN_SIZE + 2
    ui_surf.blit(counter_surf, (arr_x + _ARROW_BTN_SIZE // 2 - counter_surf.get_width() // 2,
                                 counter_y))

    down_y = counter_y + counter_surf.get_height() + 2
    down_rect = pygame.Rect(arr_x, down_y, _ARROW_BTN_SIZE, _ARROW_BTN_SIZE)
    pygame.draw.rect(ui_surf, (60, 60, 70), down_rect)
    pygame.draw.rect(ui_surf, const.WHITE, down_rect, 1)
    down_sym = font_medium.render("v", True, const.WHITE_240)
    ui_surf.blit(down_sym, (down_rect.centerx - down_sym.get_width() // 2,
                             down_rect.centery - down_sym.get_height() // 2))
    rects[f"{prefix}_down"] = down_rect

    return y + _SECTION_BOX_H + 8


def _draw_options_mode_page(ui_surf, font_big, font_medium, font_small,
                            car_sprites_cache, px, py, rects):
    """Draw Mode Options sub-page content."""
    cx = px + _PANEL_WIDTH // 2
    y = py + _CONTENT_PAD

    # Mode selector with decorative current car
    current_car = AVAILABLE_CARS[_game_options["selected_car_index"] % len(AVAILABLE_CARS)] if AVAILABLE_CARS else None
    y = _draw_item_selector(ui_surf, font_medium, font_small, car_sprites_cache,
                            "Mode", _game_options["selected_mode_index"],
                            const.MODES_NAMES, px, y, rects, "mode",
                            show_car=False, show_illustration=True, car_id_override=current_car)

    # Choice section
    y += 5
    choice_lbl = font_medium.render(const.MODES_OPTION_STR[const.MODE_INDEX], True, const.WHITE_240)
    ui_surf.blit(choice_lbl, (cx - choice_lbl.get_width() // 2, y))
    y += choice_lbl.get_height() + 5

    # -  [value]  +
    total_w = _PM_BTN_SIZE * 2 + 60
    start_x = cx - total_w // 2

    minus_rect = pygame.Rect(start_x, y, _PM_BTN_SIZE, _PM_BTN_SIZE)
    pygame.draw.rect(ui_surf, (60, 60, 70), minus_rect)
    pygame.draw.rect(ui_surf, const.WHITE, minus_rect, 1)
    m_sym = font_big.render("-", True, const.WHITE_240)
    ui_surf.blit(m_sym, (minus_rect.centerx - m_sym.get_width() // 2,
                          minus_rect.centery - m_sym.get_height() // 2))
    rects["choice_minus"] = minus_rect

    val_rect = pygame.Rect(start_x + _PM_BTN_SIZE, y, 60, _PM_BTN_SIZE)
    pygame.draw.rect(ui_surf, (40, 40, 46), val_rect)
    pygame.draw.rect(ui_surf, const.WHITE, val_rect, 1)
    val_surf = font_big.render(str(const.MODES_CHOICES[const.MODE_INDEX][_game_options["choice"]]), True, const.WHITE_240)
    ui_surf.blit(val_surf, (val_rect.centerx - val_surf.get_width() // 2,
                             val_rect.centery - val_surf.get_height() // 2))

    plus_rect = pygame.Rect(start_x + _PM_BTN_SIZE + 60, y, _PM_BTN_SIZE, _PM_BTN_SIZE)
    pygame.draw.rect(ui_surf, (60, 60, 70), plus_rect)
    pygame.draw.rect(ui_surf, const.WHITE, plus_rect, 1)
    p_sym = font_big.render("+", True, const.WHITE_240)
    ui_surf.blit(p_sym, (plus_rect.centerx - p_sym.get_width() // 2,
                          plus_rect.centery - p_sym.get_height() // 2))
    rects["choice_plus"] = plus_rect


def _draw_options_ai_page(ui_surf, font_big, font_medium, font_small,
                          px, py, room_clients_count, rects):
    """Draw AI Options sub-page content."""
    cx = px + _PANEL_WIDTH // 2
    y = py + _CONTENT_PAD

    # Amount section
    amount_lbl = font_medium.render("Amount", True, const.WHITE_240)
    ui_surf.blit(amount_lbl, (cx - amount_lbl.get_width() // 2, y))
    y += amount_lbl.get_height() + 5

    total_w = _PM_BTN_SIZE * 2 + 60
    start_x = cx - total_w // 2

    minus_rect = pygame.Rect(start_x, y, _PM_BTN_SIZE, _PM_BTN_SIZE)
    pygame.draw.rect(ui_surf, (60, 60, 70), minus_rect)
    pygame.draw.rect(ui_surf, const.WHITE, minus_rect, 1)
    m_sym = font_big.render("-", True, const.WHITE_240)
    ui_surf.blit(m_sym, (minus_rect.centerx - m_sym.get_width() // 2,
                          minus_rect.centery - m_sym.get_height() // 2))
    rects["ai_amount_minus"] = minus_rect

    val_rect = pygame.Rect(start_x + _PM_BTN_SIZE, y, 60, _PM_BTN_SIZE)
    pygame.draw.rect(ui_surf, (40, 40, 46), val_rect)
    pygame.draw.rect(ui_surf, const.WHITE, val_rect, 1)
    val_surf = font_big.render(str(_game_options["ai_amount"]), True, const.WHITE_240)
    ui_surf.blit(val_surf, (val_rect.centerx - val_surf.get_width() // 2,
                             val_rect.centery - val_surf.get_height() // 2))

    plus_rect = pygame.Rect(start_x + _PM_BTN_SIZE + 60, y, _PM_BTN_SIZE, _PM_BTN_SIZE)
    pygame.draw.rect(ui_surf, (60, 60, 70), plus_rect)
    pygame.draw.rect(ui_surf, const.WHITE, plus_rect, 1)
    p_sym = font_big.render("+", True, const.WHITE_240)
    ui_surf.blit(p_sym, (plus_rect.centerx - p_sym.get_width() // 2,
                          plus_rect.centery - p_sym.get_height() // 2))
    rects["ai_amount_plus"] = plus_rect
    y += _PM_BTN_SIZE + 15

    # Difficulty section
    diff_lbl = font_medium.render("Difficulty", True, const.WHITE_240)
    ui_surf.blit(diff_lbl, (cx - diff_lbl.get_width() // 2, y))
    y += diff_lbl.get_height() + 5

    difficulties = ["Easy", "Medium", "Hard", "Random"]
    grid_w = _DIFF_BTN_W * 2 + 8
    grid_x = cx - grid_w // 2
    for i, diff in enumerate(difficulties):
        col = i % 2
        row = i // 2
        bx = grid_x + col * (_DIFF_BTN_W + 8)
        by = y + row * (_DIFF_BTN_H + 6)
        btn_rect = pygame.Rect(bx, by, _DIFF_BTN_W, _DIFF_BTN_H)
        is_selected = _game_options["ai_difficulty"] == diff
        bg_color = (40, 80, 40) if is_selected else (60, 60, 70)
        border_color = const.GREEN if is_selected else const.WHITE
        border_w = 2 if is_selected else 1
        pygame.draw.rect(ui_surf, bg_color, btn_rect)
        pygame.draw.rect(ui_surf, border_color, btn_rect, border_w)
        btn_text = font_small.render(diff, True, const.WHITE_240)
        ui_surf.blit(btn_text, (btn_rect.centerx - btn_text.get_width() // 2,
                                 btn_rect.centery - btn_text.get_height() // 2))
        rects[f"diff_{diff.lower()}"] = btn_rect


def handle_game_options_click(click_pos, rects, is_host, room_clients_count=1):
    """Handle clicks on the game options panel.

    Returns an action string or None.
    Possible actions:
      "toggle_panel", "car_prev", "car_next", "map_prev", "map_next",
      "nav_mode", "nav_ai", "back",
      "mode_prev", "mode_next", "choice_minus", "choice_plus",
      "ai_amount_minus", "ai_amount_plus", "diff_<name>"
    """
    for name, rect in rects.items():
        if not rect.collidepoint(click_pos):
            continue

        if name == "toggle":
            _game_options["panel_open"] = not _game_options["panel_open"]
            return "toggle_panel"

        if name == "back":
            _game_options["panel_page"] = "main"
            return "back"

        if name == "nav_mode" and is_host:
            _game_options["panel_page"] = "mode"
            return "nav_mode"

        if name == "nav_ai" and is_host:
            _game_options["panel_page"] = "ai"
            return "nav_ai"

        # Car selection
        if name == "car_up":
            total = len(AVAILABLE_CARS)
            if total > 0:
                _game_options["selected_car_index"] = (_game_options["selected_car_index"] - 1) % total
                _game_setup["selected_car"] = AVAILABLE_CARS[_game_options["selected_car_index"]]
                _init_palette_for_selected_car(_game_setup["selected_car"], force=True)
            return "car_prev"
        if name == "car_down":
            total = len(AVAILABLE_CARS)
            if total > 0:
                _game_options["selected_car_index"] = (_game_options["selected_car_index"] + 1) % total
                _game_setup["selected_car"] = AVAILABLE_CARS[_game_options["selected_car_index"]]
                _init_palette_for_selected_car(_game_setup["selected_car"], force=True)
            return "car_next"

        # Map selection (host only)
        if name == "map_up" and is_host:
            maps = _get_map_names()
            total = len(maps)
            if total > 0:
                _game_options["selected_map_index"] = (_game_options["selected_map_index"] - 1) % total
                _game_setup["selected_track"] = maps[_game_options["selected_map_index"]][0]
            return "map_prev"
        if name == "map_down" and is_host:
            maps = _get_map_names()
            total = len(maps)
            if total > 0:
                _game_options["selected_map_index"] = (_game_options["selected_map_index"] + 1) % total
                _game_setup["selected_track"] = maps[_game_options["selected_map_index"]][0]
            return "map_next"

        # Mode selection
        if name == "mode_up" and is_host:
            total = len(_MODE_OPTIONS)
            if total > 0:
                _game_options["selected_mode_index"] = (_game_options["selected_mode_index"] - 1) % total
                _game_setup["selected_mode"] = _MODE_OPTIONS[_game_options["selected_mode_index"]][0]
                const.MODE_INDEX = _game_options["selected_mode_index"]
            return "mode_prev"
        if name == "mode_down" and is_host:
            total = len(_MODE_OPTIONS)
            if total > 0:
                _game_options["selected_mode_index"] = (_game_options["selected_mode_index"] + 1) % total
                _game_setup["selected_mode"] = _MODE_OPTIONS[_game_options["selected_mode_index"]][0]
                const.MODE_INDEX = _game_options["selected_mode_index"]
            return "mode_next"

        # Choice
        if name == "choice_minus":
            _game_options["choice"] = max(0, _game_options["choice"] - 1)
            return "choice_minus"
        if name == "choice_plus":
            _game_options["choice"] = min(len(const.MODES_CHOICES[const.MODE_INDEX])-1, _game_options["choice"]+1)
            return "choice_plus"

        # AI amount
        if name == "ai_amount_minus":
            _game_options["ai_amount"] = max(0, _game_options["ai_amount"] - 1)
            return "ai_amount_minus"
        if name == "ai_amount_plus":
            max_ai = max(0, 6 - room_clients_count)
            _game_options["ai_amount"] = min(max_ai, _game_options["ai_amount"] + 1)
            return "ai_amount_plus"

        # Difficulty
        for diff in ("easy", "medium", "hard", "random"):
            if name == f"diff_{diff}":
                _game_options["ai_difficulty"] = diff.capitalize()
                return f"diff_{diff}"

    return None

def draw_error(ui_surf, error_msg, font_small):
    msg = font_small.render(error_msg, True, (255,200,200))
    ui_surf.blit(msg, (const.WINDOW_WIDTH//2 - msg.get_width()//2, const.WINDOW_HEIGHT//2))
    tip = font_small.render("Press R to restart", True, const.GREY_200)
    ui_surf.blit(tip, (const.WINDOW_WIDTH//2 - tip.get_width()//2, const.WINDOW_HEIGHT//2 + 40))

def _draw_rotating_car(ui_surf, car_id, rect, font_medium, car_sprites_cache, rotation_angle, text_override=None):
    """Helper to draw a rotating car sprite and its text centered in a given rect."""
    # draw cars' sprites
    if car_sprites_cache and car_id in car_sprites_cache:
        sprites = car_sprites_cache[car_id]
        if sprites:
            main_sprite = sprites[1] if len(sprites) > 1 else sprites[0]
            if main_sprite:
                show_angle = (-rotation_angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
                sprite_index = round(show_angle * 64) % 64
                sprite = main_sprite[sprite_index]
                # Center the sprite in the rect (draw_car centers on x,y)
                cx = rect.centerx
                cy = rect.y + 20 + sprite.get_height() // 2 - 20
                from drift.ui.ui import draw_car
                draw_car(ui_surf, cx, cy, rotation_angle, None,
                         car_sprites_list=sprites,
                         palette_colors=get_palette_colors())
    
    # draw label text
    label = text_override if text_override else _load_car_specs(car_id)
    text_surf = font_medium.render(f"{label}", True, const.WHITE_240)
    text_x = rect.centerx - text_surf.get_width() // 2
    text_y = rect.top + text_surf.get_height() - 5
    ui_surf.blit(text_surf, (text_x, text_y))

def draw_menu_connection_bar(ui_surf, font_medium):
    """Draw horizontal connection bar at bottom center of menu screen.

    Layout: [Username] [margin] [Code] [Action Button]
    Action button is orange "Host" when code is empty, green "Join" when code has text.
    Returns dict of rects for click detection.
    """
    ORANGE = (255, 165, 0)
    bar_height = 40
    bar_y = const.WINDOW_HEIGHT - const.BOTTOM_LINE_Y - bar_height - 15
    center_x = const.WINDOW_WIDTH // 2

    # Element dimensions
    username_w = 180
    code_w = 100
    action_btn_w = 80
    margin = 15

    tutorial_btn_w = 110
    total_w = username_w + margin + code_w + action_btn_w + margin + tutorial_btn_w
    x = center_x - total_w // 2

    rects = {}

    # 1. Username textbox
    username_rect = pygame.Rect(x, bar_y, username_w, bar_height)
    username_color = (100, 200, 100) if _game_setup["username_active"] else (80, 80, 90)
    pygame.draw.rect(ui_surf, username_color, username_rect, 2)
    if _game_setup["username"]:
        text_surf = font_medium.render(_game_setup["username"], True, const.WHITE_240)
    else:
        text_surf = font_medium.render("Username", True, const.GREY_180)
    ui_surf.blit(text_surf, (username_rect.centerx - text_surf.get_width() // 2,
                              username_rect.centery - text_surf.get_height() // 2))
    rects["username_box"] = username_rect

    # 2. Code textbox
    x += username_w + margin
    code_rect = pygame.Rect(x, bar_y, code_w, bar_height)
    code_color = (100, 200, 100) if _game_setup.get("code_active", False) else (80, 80, 90)
    pygame.draw.rect(ui_surf, code_color, code_rect, 2)
    if _game_setup.get("room_code", ""):
        code_surf = font_medium.render(_game_setup["room_code"], True, const.WHITE_240)
    else:
        code_surf = font_medium.render("Code", True, const.GREY_180)
    ui_surf.blit(code_surf, (code_rect.centerx - code_surf.get_width() // 2,
                              code_rect.centery - code_surf.get_height() // 2))
    rects["code_box"] = code_rect

    # 3. Dynamic action button (immediately next to code)
    x += code_w
    has_code = bool(_game_setup.get("room_code", ""))
    action_color = const.GREEN if has_code else ORANGE
    action_label = "Join" if has_code else "Host"
    action_rect = pygame.Rect(x, bar_y, action_btn_w, bar_height)
    pygame.draw.rect(ui_surf, action_color, action_rect)
    action_text = font_medium.render(action_label, True, const.WHITE_240)
    ui_surf.blit(action_text, (action_rect.centerx - action_text.get_width() // 2,
                                action_rect.centery - action_text.get_height() // 2))
    rects["action_btn"] = action_rect

    # 4. Tutorial button (always available, local/offline flow)
    x += action_btn_w + margin
    tutorial_rect = pygame.Rect(x, bar_y, tutorial_btn_w, bar_height)
    pygame.draw.rect(ui_surf, (70, 120, 230), tutorial_rect)
    tutorial_text = font_medium.render("Tutorial", True, const.WHITE_240)
    ui_surf.blit(tutorial_text, (tutorial_rect.centerx - tutorial_text.get_width() // 2,
                                  tutorial_rect.centery - tutorial_text.get_height() // 2))
    rects["tutorial_btn"] = tutorial_rect

    # Error message (above bar)
    if _game_setup["error_message"]:
        error_surf = font_medium.render(_game_setup["error_message"], True, (255, 100, 100))
        ui_surf.blit(error_surf, (center_x - error_surf.get_width() // 2, bar_y - 30))

    return rects

def handle_menu_bar_click(click_pos, rects):
    """Handle mouse clicks on the menu connection bar."""
    if "username_box" in rects and rects["username_box"].collidepoint(click_pos):
        _game_setup["username_active"] = True
        _game_setup["code_active"] = False
        return "username_clicked"
    elif "code_box" in rects and rects["code_box"].collidepoint(click_pos):
        _game_setup["code_active"] = True
        _game_setup["username_active"] = False
        return "code_clicked"
    elif "action_btn" in rects and rects["action_btn"].collidepoint(click_pos):
        if _game_setup.get("room_code", ""):
            return "join_game"
        return "host_game"
    elif "tutorial_btn" in rects and rects["tutorial_btn"].collidepoint(click_pos):
        return "start_tutorial"
    return None

def handle_menu_bar_keypress(event):
    """Handle keyboard input for username and code fields in menu bar."""
    if _game_setup["username_active"]:
        if event.key == pygame.K_TAB:
            _game_setup["code_active"] = True
            _game_setup["username_active"] = False
        elif event.key == pygame.K_BACKSPACE:
            _game_setup["username"] = _game_setup["username"][:-1]
        elif event.key == pygame.K_ESCAPE:
            _game_setup["username_active"] = False
        else:
            if event.unicode and event.unicode.isprintable():
                if len(_game_setup["username"]) < const.MAX_NAME_LENGTH:
                    _game_setup["username"] += event.unicode
    elif _game_setup["code_active"]:
        if event.key == pygame.K_TAB:
            _game_setup["code_active"] = False
            _game_setup["username_active"] = True
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            _game_setup["code_active"] = False
            if _game_setup["room_code"]:
                return "join_game"
        elif event.key == pygame.K_BACKSPACE:
            _game_setup["room_code"] = _game_setup["room_code"][:-1]
        elif event.key == pygame.K_ESCAPE:
            _game_setup["code_active"] = False
        else:
            if event.unicode and event.unicode.isprintable():
                if len(_game_setup["room_code"]) < 4:
                    _game_setup["room_code"] += event.unicode.upper()

def get_game_setup():
    """Get current game setup configuration."""
    return _game_setup.copy()


def update_game_setup(mode=None, track=None):
    """Update selected mode/track in shared game setup state."""
    if mode is not None:
        _game_setup["selected_mode"] = str(mode)
    if track is not None:
        track_key = str(track)
        _game_setup["selected_track"] = track_key
        if track_key.startswith("track") and track_key[5:].isdigit():
            idx = max(0, int(track_key[5:]) - 1)
            _game_options["selected_map_index"] = idx

def reset_game_setup():
    """Reset game setup to defaults."""
    _game_setup["username"] = ""
    _game_setup["username_active"] = True
    _game_setup["selected_car"] = AVAILABLE_CARS[0] if AVAILABLE_CARS else "ae86"
    _game_setup["selected_track"] = "track1"
    _game_setup["selected_mode"] = "mode1"
    _game_setup["room_code"] = ""
    _game_setup["code_active"] = False
    _game_setup["error_message"] = None
    _init_palette_for_selected_car(_game_setup["selected_car"], force=True)
    # Reset game options panel
    _game_options["panel_open"] = False
    _game_options["panel_page"] = "main"
    _game_options["selected_car_index"] = 0
    _game_options["selected_map_index"] = 0
    _game_options["selected_mode_index"] = 0
    _game_options["choice"] = 2
    _game_options["ai_amount"] = 0
    _game_options["ai_difficulty"] = "Random"

def set_error_message(message):
    """Set an error message to display in the UI."""
    _game_setup["error_message"] = message

def clear_error_message():
    """Clear the error message."""
    _game_setup["error_message"] = None

def host_new_game(my_id):
    """
    Initiate hosting a new game (non-blocking).
    Sends the create packet and returns a pending connection state.
    Call poll_connection() each frame to check for completion.
    Returns: connection state dict
    """
    my_name = _game_setup["username"] or "Player_" + str(my_id)[:4]
    code = rand_code()
    sock = None
    is_host = True
    host_name = my_name

    try:
        sock = connect_to_relay()
        join_pkt = {
            "t": "create",
            "code": code,
            "name": my_name,
            "id": my_id,
            "car_type": _game_setup["selected_car"],
            "track": _game_setup["selected_track"],
            "mode": _game_setup["selected_mode"]
        }
        sock.send(json.dumps(join_pkt).encode("utf-8"))
    except Exception as e:
        print(f"Failed to connect to relay: {e}")
        # Immediate offline fallback
        return _finalize_connection(my_name, "Offline", None, True, my_name, None, is_host_mode=True)

    return {
        "status": "pending",
        "sock": sock,
        "code": code,
        "my_name": my_name,
        "my_id": my_id,
        "is_host": True,
        "host_name": host_name,
        "deadline": time.time() + 1.0,
        "mode": "host",
    }


def join_new_game(my_id):
    """
    Initiate joining an existing game (non-blocking).
    Sends the join packet and returns a pending connection state.
    Call poll_connection() each frame to check for completion.
    Returns: connection state dict
    """
    my_name = _game_setup["username"] or "Player_" + str(my_id)[:4]
    code = _game_setup["room_code"].upper() if _game_setup["room_code"] else ""
    sock = None

    try:
        sock = connect_to_relay()
        join_pkt = {
            "t": "join",
            "code": code,
            "name": my_name,
            "id": my_id,
            "car_type": _game_setup["selected_car"]
        }
        sock.send(json.dumps(join_pkt).encode("utf-8"))
    except Exception as e:
        error = str(e)
        print(f"Failed to join game: {error}")
        return {
            "status": "done",
            "result": ("menu", my_name, "", None, False, "Host", error, None, None, []),
        }

    return {
        "status": "pending",
        "sock": sock,
        "code": code,
        "my_name": my_name,
        "my_id": my_id,
        "is_host": False,
        "host_name": "Host",
        "deadline": time.time() + 1.0,
        "mode": "join",
    }


def poll_connection(conn):
    """Poll a pending connection state (non-blocking, call each frame).
    Returns the same dict. Check conn["status"] == "done" and use conn["result"].
    """
    if conn["status"] != "pending":
        return conn

    sock = conn["sock"]
    my_name = conn["my_name"]
    host_name = conn["host_name"]
    code = conn["code"]

    try:
        for msg in recv_jsons(sock):
            if msg.get("t") == "join_ok":
                host_name = msg.get("host_name", host_name)
                if conn["mode"] == "join":
                    server_track = msg.get("track")
                    if server_track:
                        _game_setup["selected_track"] = server_track
                conn["status"] = "done"
                conn["result"] = _finalize_connection(
                    my_name, code, sock,
                    conn["is_host"], host_name,
                    None,
                    is_host_mode=conn["is_host"],
                )
                return conn
            if msg.get("t") == "error":
                error_msg = msg.get("msg", "relay error")
                try: sock.close()
                except Exception: pass
                if conn["mode"] == "host":
                    conn["status"] = "done"
                    conn["result"] = _finalize_connection(
                        my_name, "Offline", None, True, my_name, None, is_host_mode=True
                    )
                else:
                    conn["status"] = "done"
                    conn["result"] = ("menu", my_name, "", None, False, "Host", error_msg, None, None, [])
                return conn
    except Exception:
        pass

    # Check timeout
    if time.time() >= conn["deadline"]:
        try: sock.close()
        except Exception: pass
        if conn["mode"] == "host":
            conn["status"] = "done"
            conn["result"] = _finalize_connection(
                my_name, "Offline", None, True, my_name, None, is_host_mode=True
            )
        else:
            conn["status"] = "done"
            conn["result"] = ("menu", my_name, "", None, False, "Host", "join_timeout", None, None, [])
        return conn

    return conn


def _finalize_connection(my_name, code, sock, is_host, host_name, error, is_host_mode=True):
    """Load track assets and return the final result tuple."""
    try: const.MAP_NUM = int(_game_setup["selected_track"][5:])
    except Exception: pass
    track_image = pygame.image.load(get_track_base_image_path(f"map{const.MAP_NUM}")).convert()
    chunked_map = ChunkedMap(root=normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=const.TILE_SIZE)

    _cp_rects = []
    meta_path = asset_path("track", f"map{const.MAP_NUM}", "map_meta.json")
    try:
        with open(meta_path, "r", encoding="utf-8") as fh: meta = json.load(fh)
        checkpoints = meta.get("checkpoints", {}) if is_host_mode else meta.get("checkpoints", [])
        for cp in checkpoints:
            rect = pygame.Rect(cp.get("x", 0), cp.get("y", 0), cp.get("width", 0), cp.get("height", 0))
            _cp_rects.append(rect)
    except Exception as e: print(f"Error reading map metadata: {e}")

    invalidate_ui_text_cache('room')
    if is_host_mode:
        return ("lobby", my_name, code, sock, is_host, host_name, track_image, chunked_map, _cp_rects)
    else:
        return ("lobby", my_name, code, sock, is_host, host_name, error, track_image, chunked_map, _cp_rects)

def draw_settings(ui_surf, world_surf, world_size, buttons, stage_path, font_small=None, is_host=False):    
    # Draw buttons and handle their state
    button_results = []
    for button in buttons:
        if button.text == "Stop Race" and not is_host: continue
        res = button.draw(ui_surf, stage_path)
        if res is not None:
            button_results.append(res)
    
    # Draw STEER_BIAS slider
    if font_small is not None:
        # Initialize slider if not already done
        if 'steer_bias' not in physics_controls.sliders:
            slider_x = const.WINDOW_WIDTH // 2 - 100
            slider_y = const.WINDOW_HEIGHT * 0.75  # Position below buttons
            slider = Slider(
                x=slider_x, y=slider_y, width=200, height=30,
                min_val=0.5, max_val=1.5, current_val=physics_controls.get_value("steer_bias"),
                label="Steer Bias:", font=font_small
            )
            physics_controls.add_slider('steer_bias', slider)
        
        # Draw the slider
        physics_controls.draw_sliders(ui_surf)

    return world_surf, button_results

def draw_controls(ui_surf, font_small):
    """Draw key binds configuration page with dynamic layout.
    
    Returns:
        dict: Rectangles for click detection {bind_name: rect, "gp_0": rect, ...}
    """
    # list every gamepad connected to the hardware
    count = pygame.joystick.get_count()
    joysticks = [pygame.joystick.Joystick(i) for i in range(count)]

    # Display connected gamepads at the top
    center_x = const.WINDOW_WIDTH // 2
    gp_y = int(const.WINDOW_HEIGHT * 0.08)
    gp_row_height = font_small.get_height() + 8
    gp_rects = {}  # {"gp_0": rect, "gp_1": rect, ...}

    gp_title = get_cached_text(font_small, f"Connected Gamepads ({count})", const.WHITE_240,
                               cache_key=("controls", "gp_title", count))
    ui_surf.blit(gp_title, (center_x - gp_title.get_width() // 2, gp_y))

    row_y = gp_y + gp_title.get_height() + 6
    if count == 0:
        no_gp = get_cached_text(font_small, "No gamepads detected", const.GREY_180,
                                cache_key=("controls", "no_gp"))
        no_gp_rect = pygame.Rect(center_x - no_gp.get_width() // 2 - 8, row_y,
                                 no_gp.get_width() + 16, gp_row_height)
        pygame.draw.rect(ui_surf, (50, 50, 60), no_gp_rect)
        pygame.draw.rect(ui_surf, const.GREY_180, no_gp_rect, 1)
        ui_surf.blit(no_gp, (no_gp_rect.centerx - no_gp.get_width() // 2,
                              no_gp_rect.centery - no_gp.get_height() // 2))
        gp_rects["gp_none"] = no_gp_rect
    else:
        for i, js in enumerate(joysticks):
            is_selected = _controls_state["selected_gamepad"] == i
            js_label = f"[{i}]  {js.get_name()}"
            if is_selected:
                js_label += "  [connected]"
            js_text = get_cached_text(font_small, js_label, const.WHITE_240 if is_selected else const.GREY_180,
                                      cache_key=("controls", "gp", i, js.get_name(), is_selected))
            js_rect = pygame.Rect(center_x - js_text.get_width() // 2 - 8,
                                  row_y + i * gp_row_height + 5 * i,
                                  js_text.get_width() + 16, gp_row_height)
            bg_color = (40, 80, 40) if is_selected else (50, 50, 60)
            border_color = (100, 200, 100) if is_selected else const.GREY_180
            pygame.draw.rect(ui_surf, bg_color, js_rect)
            pygame.draw.rect(ui_surf, border_color, js_rect, 2 if is_selected else 1)
            ui_surf.blit(js_text, (js_rect.centerx - js_text.get_width() // 2,
                                   js_rect.centery - js_text.get_height() // 2))
            gp_rects[f"gp_{i}"] = js_rect

    # Define key bindings to display (order matters for UI)
    controls = [
        ("UP_KEY", "Accelerate"),
        ("DOWN_KEY", "Reverse"),
        ("LEFT_KEY", "Steer Left"),
        ("RIGHT_KEY", "Steer Right"),
        ("BRAKE_KEY", "Handbrake"),
        ("RESET_KEY", "Restart Checkpoint"),
    ]
    
    total_btn = len(controls)
    
    # Layout calculations
    label_width = 150
    key_box_width = 120
    key_box_height = 40
    spacing_x = 15  # Space between label and key box
    column_spacing = 60  # Space between two columns
    
    # Calculate vertical spacing to distribute button rows evenly
    # Leave margin at top and bottom
    top_margin = const.WINDOW_HEIGHT * 0.3
    bottom_margin = const.WINDOW_HEIGHT * 0.3
    available_height = const.WINDOW_HEIGHT - top_margin - bottom_margin
    
    # Calculate number of rows (2 items per row)
    num_rows = (total_btn + 1) // 2  # Ceiling division
    
    # Space between each key bind row
    if num_rows > 1:
        row_spacing = available_height / (num_rows - 1)
    else:
        row_spacing = 0
    
    # Calculate width of one column (label + spacing + key box)
    column_width = label_width + spacing_x + key_box_width
    
    # Store rects for click detection
    bind_rects = {}
    
    for idx, (bind_name, bind_label) in enumerate(controls):
        row = idx // 2  # Which row (0, 1, 2, ...)
        col = idx % 2   # Which column (0 = left, 1 = right)
        
        y = int(top_margin + row * row_spacing)
        
        # Calculate x position for this column
        if col == 0:
            # Left column
            label_x = center_x - column_width - column_spacing // 2
        else:
            # Right column
            label_x = center_x + column_spacing // 2
        
        # Get current key value from const
        current_value = getattr(const, bind_name, pygame.K_UNKNOWN)
        
        # Handle list of keys (like UP_KEY = [K_UP, K_z])
        # Display the second element (index 1) for list keys
        if isinstance(current_value, list):
            current_key = current_value[1] if len(current_value) > 1 else pygame.K_UNKNOWN
        else:
            current_key = current_value
        
        # Get key name
        if _controls_state["waiting_for_key"] == bind_name:
            key_text = "Press a key..."
            key_color = (255, 200, 100)  # Orange when waiting
        else:
            key_text = pygame.key.name(current_key).upper()
            key_color = (80, 80, 90)  # Grey color
        
        # Draw label (action description)
        label_surf = get_cached_text(font_small, bind_label, const.WHITE_240,
                                     cache_key=("controls", "label", bind_label))
        ui_surf.blit(label_surf, (label_x, y + (key_box_height - label_surf.get_height()) // 2))
        
        # Draw key box (clickable rect)
        key_box_x = label_x + label_width + spacing_x
        key_box_rect = pygame.Rect(key_box_x, y, key_box_width, key_box_height)
        
        # Highlight if selected/hovered
        if _controls_state["selected_bind"] == bind_name or _controls_state["waiting_for_key"] == bind_name:
            pygame.draw.rect(ui_surf, (100, 200, 100), key_box_rect, 3)  # Green border
        else:
            pygame.draw.rect(ui_surf, key_color, key_box_rect)
            pygame.draw.rect(ui_surf, const.GREY_180, key_box_rect, 2)  # Border
        
        # Draw key text (always white)
        key_surf = get_cached_text(font_small, key_text, const.WHITE_240,
                                   cache_key=("controls", "key", bind_name, key_text))
        ui_surf.blit(key_surf, (key_box_rect.centerx - key_surf.get_width() // 2,
                                key_box_rect.centery - key_surf.get_height() // 2))
        
        # Store rect for click detection
        bind_rects[bind_name] = key_box_rect
    
    return {**bind_rects, **gp_rects}

def handle_controls_click(click_pos, all_rects, gamepad):
    """Handle mouse clicks on key bind rectangles and gamepad rows.
    
    Args:
        click_pos: (x, y) tuple of click position
        all_rects: merged dict returned by draw_controls
        gamepad: Gamepad object
    
    Returns:
        str: The bind name clicked, "gp_connected_N" for a gamepad, or None
    """
    for name, rect in all_rects.items():
        if not rect.collidepoint(click_pos): continue
        if name.startswith("gp_") and name != "gp_none":
            idx = int(name[3:])
            gamepad.connect_gamepad(idx)
            _controls_state["selected_gamepad"] = idx
            invalidate_ui_text_cache('all')
            return f"gp_connected_{idx}"
        elif not name.startswith("gp_"):
            _controls_state["waiting_for_key"] = name
            _controls_state["selected_bind"] = name
            invalidate_ui_text_cache('all')
            return name
    return None

def handle_controls_keypress(event):
    """Handle keyboard input for key binds configuration.
    
    Args:
        event: pygame.KEYDOWN event
    
    Returns:
        str: "saved" if changes were saved, "back" if escape pressed, None otherwise
    """
    # Check if we're waiting for a key to rebind
    if _controls_state["waiting_for_key"]:
        bind_name = _controls_state["waiting_for_key"]
        
        # Escape cancels the rebind
        if event.key == pygame.K_ESCAPE:
            _controls_state["waiting_for_key"] = None
            _controls_state["selected_bind"] = None
            invalidate_ui_text_cache('all')
            return "back"
        
        # Get current value from const
        current_value = getattr(const, bind_name, None)
        
        # Update the key binding
        # If it's a list, update list[1] only
        if isinstance(current_value, list):
            # Keep index 0, update index 1
            new_list = [current_value[0], event.key]
            if len(current_value) > 2:
                # Preserve any additional elements
                new_list.extend(current_value[2:])
            setattr(const, bind_name, new_list)
        else:
            # Single key, replace directly
            setattr(const, bind_name, event.key)
        
        # Clear waiting state and auto-save
        _controls_state["waiting_for_key"] = None
        _controls_state["selected_bind"] = None
        invalidate_ui_text_cache('all')  # Clear cache to show new key
        return "saved"
    
    # If not waiting for key, Escape exits to settings menu
    if event.key == pygame.K_ESCAPE:
        return "back"
    
    return None

def draw_audio_sliders(ui_surf, font_small):
    # (self, x, y, width, height, min_val, max_val, current_val, label, font)
    if 'master_volume' not in audio_volumes.sliders:
        master_slider = Slider(
            x=const.WINDOW_WIDTH // 2 - 100, y=int(const.WINDOW_HEIGHT * 0.4),
            width=200, height=30, min_val=0.0, max_val=1.0, current_val=audio_volumes.get_value("master_volume"),
            label="Master Volume:", font=font_small
        )
        audio_volumes.add_slider('master_volume', master_slider)
    if 'music_volume' not in audio_volumes.sliders:
        music_slider = Slider(
            x=const.WINDOW_WIDTH // 2 - 100, y=int(const.WINDOW_HEIGHT * 0.5),
            width=200, height=30, min_val=0.0, max_val=1.0, current_val=audio_volumes.get_value("music_volume"),
            label="Music Volume:", font=font_small
        )
        audio_volumes.add_slider('music_volume', music_slider)
    if 'sfx_volume' not in audio_volumes.sliders:
        sfx_slider = Slider(
            x=const.WINDOW_WIDTH // 2 - 100, y=int(const.WINDOW_HEIGHT * 0.6),
            width=200, height=30, min_val=0.0, max_val=1.0, current_val=audio_volumes.get_value("sfx_volume"),
            label="SFX Volume:", font=font_small
        )
        audio_volumes.add_slider('sfx_volume', sfx_slider)
    
    audio_volumes.draw_sliders(ui_surf)

def handle_audio_keypress(event):
    if event.key == pygame.K_ESCAPE: return "back"
    return None

def switch_cursor_follow_mode(stage3):
    const.CURSOR_FOLLOW = not const.CURSOR_FOLLOW
    if const.CURSOR_FOLLOW: const.AI_PATH_FOLLOW = False
    const.MODE_CLICKED = True

def switch_ai_path_mode(stage3):
    const.AI_PATH_FOLLOW = not const.AI_PATH_FOLLOW
    if const.AI_PATH_FOLLOW: const.CURSOR_FOLLOW = False
    const.MODE_CLICKED = True

def get_color(const_var):
    return const.GREEN if const_var else const.RED

def draw_modes_panel(ui_surf, stage_path, stage3):
    mode_rects = [
        Button("Follow Cursor", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.45, const.BTN_WIDTH, const.BTN_HEIGHT, get_color(const.CURSOR_FOLLOW), 
                                [["menu", "settings", "modes"], ["lobby", "settings", "modes"], ["mode1", "settings", "modes"], ["mode2", "settings", "modes"], ["mode3", "settings", "modes"]], lambda: switch_cursor_follow_mode(stage3)),
        Button("AI AutoPilot", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.55, const.BTN_WIDTH, const.BTN_HEIGHT, get_color(const.AI_PATH_FOLLOW), 
                               [["mode1", "settings", "modes"], ["mode2", "settings", "modes"], ["mode3", "settings", "modes"]], lambda: switch_ai_path_mode(stage3))
    ]
    for button in mode_rects: button.draw(ui_surf, stage_path)
    return stage3

def handle_modes_keypress(event):
    if event.key == pygame.K_ESCAPE: return "back"
    return None
