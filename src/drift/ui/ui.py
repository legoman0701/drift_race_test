# global
import math, json, pygame
import numpy as np

# local
import drift.config.const as const
from drift.core.car import CAR_LEN, CAR_WID
from drift.core.helpers import clamp
from drift.ui.ui_helpers import get_cached_text, invalidate_ui_text_cache
from drift.ui.draw_stage import (
    draw_mode1, draw_mode2, draw_new_game, draw_join_game, draw_settings, draw_error,
    handle_new_game_click, handle_new_game_keypress, host_new_game, draw_controls,
    handle_join_game_click, handle_join_game_keypress, join_new_game,
    handle_controls_click, handle_controls_keypress, draw_game,
    get_game_setup, reset_game_setup, set_error_message, clear_error_message,
    handle_palette_picker_click, handle_palette_picker_keypress,
    draw_color_palette_picker, poll_connection
)
from drift.config.settings import settings_manager

_car_name_font_cache = {} # car name cache
_palette_cache = {} # palette color sprite cache
_new_game_rects_cache = None # new game rects cache
_join_game_rects_cache = None # join game rects cache
_controls_rects_cache = None # key binds rects cache
_palette_picker_rects_cache = None # palette picker rects cache
_game_rects_cache = None # game rects cache
_controls_rects_cache = None # controls rects cache

# Pending network connection (non-blocking state machine)
_pending_conn = None  # dict from host_new_game/join_new_game, or None
_pending_conn_context = None  # ("host"|"join", setup, is_host_flag_ref, my_car ref)

def invalidate_palette_cache():
    """Clear the palette color sprite cache so changes are visible immediately."""
    global _palette_cache
    _palette_cache.clear()


def _start_host_connection(my_id, setup, my_car, is_host_flag_ref):
    """Initiate a non-blocking host connection."""
    global _pending_conn, _pending_conn_context
    _pending_conn = host_new_game(my_id)
    _pending_conn_context = ("host", setup, is_host_flag_ref, my_car)
    # If already done (immediate offline fallback), don't set connecting message
    if _pending_conn.get("status") == "done":
        return  # will be applied in poll_pending_connection
    set_error_message("Connecting...")


def _start_join_connection(my_id, setup, my_car, is_host_flag_ref):
    """Initiate a non-blocking join connection."""
    global _pending_conn, _pending_conn_context
    _pending_conn = join_new_game(my_id)
    _pending_conn_context = ("join", setup, is_host_flag_ref, my_car)
    if _pending_conn.get("status") == "done":
        return
    set_error_message("Connecting...")


def poll_pending_connection():
    """Poll the pending connection each frame. Returns updated (stage1, stage2, sock, code, my_name, is_host, host_name, error, track_image, chunked_map, checkpoints) or None if nothing pending/resolved."""
    global _pending_conn, _pending_conn_context
    if _pending_conn is None:
        return None

    if _pending_conn.get("status") == "pending":
        poll_connection(_pending_conn)

    if _pending_conn.get("status") != "done":
        return None

    conn = _pending_conn
    ctx = _pending_conn_context
    _pending_conn = None
    _pending_conn_context = None

    mode, setup, is_host_flag_ref, my_car = ctx
    result = conn["result"]
    clear_error_message()

    if mode == "host":
        # result: ("game", my_name, code, sock, is_host, host_name, track_image, chunked_map, _cp_rects)
        stage1, my_name, code, sock, is_host, host_name, track_image, chunked_map, checkpoints = result
        is_host_flag_ref[0] = is_host
        my_car.name = my_name
        my_car.set_car_type(setup["selected_car"])
        invalidate_palette_cache()
        my_car.x = const.WINDOW_WIDTH // 2
        my_car.y = const.WINDOW_HEIGHT // 2
        return (stage1, "", sock, code, my_name, is_host, host_name, None, track_image, chunked_map, checkpoints)
    else:
        # result: ("game"|"lobby", my_name, code, sock, is_host, host_name, error, track_image, chunked_map, _cp_rects)
        stage1, my_name, code, sock, is_host, host_name, error, track_image, chunked_map, checkpoints = result
        is_host_flag_ref[0] = is_host
        if error:
            set_error_message(error)
            return None  # stay in lobby, error shown
        my_car.name = my_name
        my_car.set_car_type(setup["selected_car"])
        invalidate_palette_cache()
        my_car.x = const.WINDOW_WIDTH // 2
        my_car.y = const.WINDOW_HEIGHT // 2
        return (stage1, "", sock, code, my_name, is_host, host_name, error, track_image, chunked_map, checkpoints)


def has_pending_connection():
    """Check if a connection attempt is in progress."""
    return _pending_conn is not None

def draw_car(surface, x, y, angle, name,
             color_body=const.COLOR_BODY_DEFAULT,
             color_nose=const.COLOR_NOSE_DEFAULT, car_sprites_list=None, lights_on=False, palette_colors=None):
    """Draw car with optional palette-based color customization.
    
    Args:
        palette_colors: Tuple of 3 RGB tuples (color1, color2, color3) for palette replacement.
                       If provided and car has palette layer, applies color customization.
    """
    if car_sprites_list is None:
        car_sprites_list = []
    
    # Check if we have palette layer (index 3) and palette colors
    has_palette = len(car_sprites_list) > 3 and palette_colors is not None
    
    for i, car_sprite in enumerate(car_sprites_list):
        show_angle = (-angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
        sprite_index = round(show_angle * 64) % 64
        
        if i == 2:  # light spray
            if not lights_on:
                continue
            sprite_size = (car_sprite[sprite_index].get_width(), car_sprite[sprite_index].get_height())
            surface.blit(car_sprite[sprite_index],
                         (int(x - sprite_size[0] // 2), int(y - sprite_size[1] // 2)),
                         special_flags=pygame.BLEND_RGB_ADD)
        elif i == 0:  # shadow
            sprite_size = (car_sprite[sprite_index].get_width(), car_sprite[sprite_index].get_height())
            surface.blit(car_sprite[sprite_index], (int(x - sprite_size[0] // 2), int(y - sprite_size[1] // 2)))
        elif i == 1 and has_palette:  # diffuse with palette processing
            # Get diffuse and palette sprites
            diffuse_sprite = car_sprite[sprite_index]
            palette_sprite = car_sprites_list[3][sprite_index]
            
            # Process palette and blend with diffuse (cached)
            customized = _apply_palette_colors(diffuse_sprite, palette_sprite, palette_colors, sprite_index)
            sprite_size = (customized.get_width(), customized.get_height())
            surface.blit(customized, (int(x - sprite_size[0] // 2), int(y - sprite_size[1] // 2)))
        elif i == 3:  # skip palette layer, already processed with diffuse
            continue
        else:  # other layers (diffuse without palette, etc.)
            sprite_size = (car_sprite[sprite_index].get_width(), car_sprite[sprite_index].get_height())
            surface.blit(car_sprite[sprite_index], (int(x - sprite_size[0] // 2), int(y - sprite_size[1] // 2)))
    
    # Calculate car corner points for tire mark drawing
    ca, sa = math.cos(angle), math.sin(angle)
    halfL, halfW = CAR_LEN * 0.7, CAR_WID * 0.5
    pts_local = [(+halfL, +halfW), (+halfL, -halfW), (-halfL, -halfW), (-halfL, +halfW)]
    wpts = []
    for px, py in pts_local:
        rx = px * ca - py * sa
        ry = px * sa + py * ca
        wpts.append((int(x + rx), int(y + ry)))

    if name:
        scale = getattr(const, "UI_SCALE", 1.0)
        font_size = max(1, int(22 * scale))
        # Use cached font to avoid expensive font creation every frame
        if font_size not in _car_name_font_cache:
            _car_name_font_cache[font_size] = pygame.font.SysFont(None, font_size)
        font = _car_name_font_cache[font_size]
        text = font.render(name, True, (230, 230, 255))
        surface.blit(text, (int(x - text.get_width() / 2), int(y - int(40 * scale))))

    # Return all four car corner points for per-wheel tire mark drawing.
    return tuple(wpts)


def _apply_palette_colors(diffuse_surf, palette_surf, palette_colors, sprite_index):
    """Apply palette color replacement and blend with diffuse (with caching).
    
    Replaces red->color1, green->color2, blue->color3 in palette,
    fills transparent pixels with white, then multiplies with diffuse.
    Uses vectorized numpy operations and caches results.
    
    Args:
        diffuse_surf: Main car texture
        palette_surf: Palette mask (R/G/B channels indicate which color to use)
        palette_colors: Tuple of 3 RGB tuples (color1, color2, color3)
        sprite_index: Frame index (0-63) for cache key
    
    Returns:
        Surface with applied palette colors
    """
    global _palette_cache
    
    # Include source surface identities to avoid cross-car/frame cache collisions.
    # Using only (sprite_index, palette_colors) can reuse a blended sprite from a different car.
    cache_key = (id(diffuse_surf), id(palette_surf), sprite_index, palette_colors)
    
    # Return cached result if available
    if cache_key in _palette_cache:
        return _palette_cache[cache_key]
    
    # Get dimensions
    w, h = diffuse_surf.get_size()
    
    # Get pixel arrays (read-only copies)
    diffuse_arr = pygame.surfarray.array3d(diffuse_surf)
    diffuse_alpha = pygame.surfarray.array_alpha(diffuse_surf)
    palette_arr = pygame.surfarray.array3d(palette_surf)
    palette_alpha = pygame.surfarray.array_alpha(palette_surf)
    
    # Convert colors to numpy arrays for vectorization
    color1 = np.array(palette_colors[0], dtype=np.float32) / 255.0
    color2 = np.array(palette_colors[1], dtype=np.float32) / 255.0
    color3 = np.array(palette_colors[2], dtype=np.float32) / 255.0
    
    # Normalize palette colors to 0-1 range
    palette_norm = palette_arr.astype(np.float32) / 255.0
    
    # Extract R, G, B weights from palette
    r_weight = palette_norm[:, :, 0]
    g_weight = palette_norm[:, :, 1]
    b_weight = palette_norm[:, :, 2]
    
    # Calculate blended palette colors using vectorized operations
    # Each pixel gets a mix of color1 (by red), color2 (by green), color3 (by blue)
    palette_result = np.zeros((w, h, 3), dtype=np.float32)
    for c in range(3):  # RGB channels
        palette_result[:, :, c] = (
            r_weight * color1[c] +
            g_weight * color2[c] +
            b_weight * color3[c]
        )
    
    # Where alpha is 0 (transparent), use white (1.0)
    transparent_mask = palette_alpha == 0
    palette_result[transparent_mask] = 1.0
    
    # Multiply with diffuse (blend)
    diffuse_norm = diffuse_arr.astype(np.float32) / 255.0
    result_arr = (diffuse_norm * palette_result * 255).astype(np.uint8)
    
    # Create result surface and set RGB values
    result = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.surfarray.blit_array(result, result_arr)
    
    # Copy alpha channel from diffuse surface
    result_alpha = pygame.surfarray.pixels_alpha(result)
    result_alpha[:] = diffuse_alpha
    del result_alpha  # Unlock the surface
    
    result = result.convert_alpha()
    
    # Cache the result
    _palette_cache[cache_key] = result
    
    return result

_debug_font_cache = None # debug text cache
_hud_font_cache = {} # HUD text cache

def draw_wheel_debug(surface: pygame.Surface, car, offx: int = 0, offy: int = 0) -> None:
    """Show per-wheel has_grip, wheel heading vector and lateral force vector.

    offx/offy: camera offset to convert world->screen (used in chunked renderer).
    """
    import math
    global _debug_font_cache
    if not hasattr(car, "wheel_debug"):
        return

    wheels = car.wheel_debug.get("wheels", [])
    grips = getattr(car, "has_grip", (1.0, 1.0, 1.0, 1.0))

    if _debug_font_cache is None:
        _debug_font_cache = pygame.font.SysFont(None, 14)
    font = _debug_font_cache

    # Target heading visualization (magenta): where steering controller wants to face.
    if hasattr(car, "target_angle"):
        cx, cy = int(car.x - offx), int(car.y - offy)
        tx = int(cx + math.cos(car.target_angle) * 36)
        ty = int(cy + math.sin(car.target_angle) * 36)
        pygame.draw.line(surface, (255, 80, 220), (cx, cy), (tx, ty), 2)
        hax, hay = -math.sin(car.target_angle) * 4, math.cos(car.target_angle) * 4
        pygame.draw.line(surface, (255, 80, 220), (tx, ty), (int(tx - math.cos(car.target_angle) * 8 + hax), int(ty - math.sin(car.target_angle) * 8 + hay)), 2)
        pygame.draw.line(surface, (255, 80, 220), (tx, ty), (int(tx - math.cos(car.target_angle) * 8 - hax), int(ty - math.sin(car.target_angle) * 8 - hay)), 2)

        sm = getattr(car, "steering_multiplier", None)
        if sm is not None:
            sm_text = font.render(f"sm:{sm:.2f}", True, (255, 220, 140))
            surface.blit(sm_text, (cx + 8, cy + 10))

    # Car basis vectors (world frame) needed to rotate wheel-local vectors
    ca, sa = math.cos(car.angle), math.sin(car.angle)
    forward_x, forward_y = ca, sa
    right_x,   right_y   = -sa, ca

    # Scale factors: keep vectors readable regardless of force magnitude
    ANGLE_VEC_LEN = 14   # pixels for wheel heading arrow
    FLAT_SCALE    = 0.04  # pixels per unit of lateral force

    for w in wheels:
        wx, wy = w["world_pos"]
        idx = int(w.get("index", -1))
        grip = grips[idx] if 0 <= idx < len(grips) else 1.0

        sx, sy = int(wx - offx), int(wy - offy)
        grip_color = (int((1.0 - grip) * 255), int(grip * 255), 80)
        pygame.draw.circle(surface, grip_color, (sx, sy), 3)

        # ---- wheel heading vector (cyan) ----
        wheel_angle = w.get("wheel_angle", 0.0)
        total_angle = car.angle + wheel_angle
        wax, way = math.cos(total_angle), math.sin(total_angle)
        ex = int(sx + wax * ANGLE_VEC_LEN)
        ey = int(sy + way * ANGLE_VEC_LEN)
        pygame.draw.line(surface, (80, 220, 255), (sx, sy), (ex, ey), 1)
        # arrowhead
        ax, ay = -way * 3, wax * 3
        pygame.draw.line(surface, (80, 220, 255), (ex, ey), (int(ex - wax*4 + ax), int(ey - way*4 + ay)), 1)
        pygame.draw.line(surface, (80, 220, 255), (ex, ey), (int(ex - wax*4 - ax), int(ey - way*4 - ay)), 1)

        # ---- lateral force vector (orange) ----
        # F_lat acts along the wheel's lateral axis (perpendicular to wheel heading)
        f_lat = w.get("F_lat", 0.0)
        # Wheel lateral axis in world frame: rotate right vector by wheel_angle
        total_ca, total_sa = math.cos(car.angle + wheel_angle), math.sin(car.angle + wheel_angle)
        lat_wx = -total_sa   # perpendicular to wheel heading
        lat_wy =  total_ca
        flx = int(sx + lat_wx * f_lat * FLAT_SCALE)
        fly = int(sy + lat_wy * f_lat * FLAT_SCALE)
        if abs(f_lat) > 1.0:
            pygame.draw.line(surface, (255, 160, 30), (sx, sy), (flx, fly), 1)
            bax, bay = -lat_wy * 3, lat_wx * 3
            dxn = lat_wx if f_lat >= 0 else -lat_wx
            dyn = lat_wy if f_lat >= 0 else -lat_wy
            pygame.draw.line(surface, (255, 160, 30), (flx, fly), (int(flx - dxn*4 + bax), int(fly - dyn*4 + bay)), 1)
            pygame.draw.line(surface, (255, 160, 30), (flx, fly), (int(flx - dxn*4 - bax), int(fly - dyn*4 - bay)), 1)

        # ---- grip label ----
        ts = font.render(f"g{idx}:{grip:.2f}", True, (230, 230, 245))
        surface.blit(ts, (sx + 6, sy - 8))

def draw_collision_debug(surface: pygame.Surface, car, collision_mesh, offx: int = 0, offy: int = 0) -> None:
    """Draw collision mesh polygons and car spring points in debug mode."""
    import math

    # Draw collision mesh polygons (yellow outline)
    for polygon in collision_mesh:
        if len(polygon) < 2:
            continue
        screen_pts = [(int(x - offx), int(y - offy)) for x, y in polygon]
        pygame.draw.polygon(surface, (255, 255, 0), screen_pts, 2)
        for sx, sy in screen_pts:
            pygame.draw.circle(surface, (255, 255, 0), (sx, sy), 3)

    # Draw car spring points: rest position (cyan) and displaced position (red) with connecting line
    if hasattr(car, "spring_debug") and car.spring_debug:
        for wx, wy, dx, dy in car.spring_debug:
            sx, sy = int(wx - offx), int(wy - offy)
            dsx, dsy = int(dx - offx), int(dy - offy)
            # Line from rest to displaced (orange)
            if abs(wx - dx) > 0.1 or abs(wy - dy) > 0.1:
                pygame.draw.line(surface, (255, 160, 30), (sx, sy), (dsx, dsy), 1)
                pygame.draw.circle(surface, (255, 50, 50), (dsx, dsy), 3)  # displaced = red
            pygame.draw.circle(surface, (0, 255, 255), (sx, sy), 3)  # rest = cyan
    elif hasattr(car, "spring_points_local"):
        ca, sa = math.cos(car.angle), math.sin(car.angle)
        for lx, ly in car.spring_points_local:
            wx = car.x + lx * ca - ly * sa
            wy = car.y + lx * sa + ly * ca
            sx, sy = int(wx - offx), int(wy - offy)
            pygame.draw.circle(surface, (0, 255, 255), (sx, sy), 3)

def draw_header(surface, font_big, font_small, title_str: str, fps: float, host_username: str = None):
    # header background
    pygame.draw.rect(surface, const.TRACK_BORDER_COLOR, (0, 0, const.WINDOW_WIDTH, const.TOP_LINE_Y))
    pygame.draw.line(surface, const.WHITE, (0, const.TOP_LINE_Y), (const.WINDOW_WIDTH, const.TOP_LINE_Y))
    
    # game version
    version_text = get_cached_text(font_small, f"v{const.VERSION}", const.GREY_180,
                                    cache_key=(id(font_small), "version", const.VERSION))
    surface.blit(version_text, (10, const.NAVBAR_Y))
    
    # page title
    title = get_cached_text(font_big, title_str, const.WHITE_240)
    surface.blit(title, (const.WINDOW_WIDTH // 2 - title.get_width() // 2, const.TITLE_Y))
    
    # fps counter
    fps_rounded = round(fps)
    if fps_rounded >= 50: color = (120, 255, 120)
    elif fps_rounded >= 30: color = (255, 255, 120)
    else: color = (255, 120, 120)
    
    fps_text = get_cached_text(font_small, f"FPS: {fps_rounded}", color,
                                cache_key=(id(font_small), "fps", fps_rounded, color))
    surface.blit(fps_text, (const.WINDOW_WIDTH - fps_text.get_width() - 10, const.NAVBAR_Y))
    
    # debug status
    debug_status = "True" if const.DEBUG else "False"
    debug_color = (120, 255, 120) if const.DEBUG else (255, 120, 120)
    debug_text = get_cached_text(font_small, f"Debug: {debug_status}", debug_color,
                                  cache_key=(id(font_small), "debug", const.DEBUG))
    surface.blit(debug_text, (const.WINDOW_WIDTH*0.90 - debug_text.get_width() - 10, const.NAVBAR_Y))
    
    # host username
    if host_username:
        host_text = get_cached_text(font_small, f"Host: {host_username}", const.WHITE_240)
        # Position after version text with some spacing
        version_width = version_text.get_width()
        surface.blit(host_text, (20 + version_width, const.NAVBAR_Y))

def draw_footer(surface: str, font_small, code=None):
    # footer background
    pygame.draw.rect(surface, const.TRACK_BORDER_COLOR, (0, const.WINDOW_HEIGHT - const.BOTTOM_LINE_Y, const.WINDOW_WIDTH, const.BOTTOM_LINE_Y))
    pygame.draw.line(surface, const.WHITE, (0, const.WINDOW_HEIGHT - const.BOTTOM_LINE_Y), (const.WINDOW_WIDTH, const.WINDOW_HEIGHT - const.BOTTOM_LINE_Y))
    
    # relay endpoint
    relay = get_cached_text(font_small, f"Relay: {const.RELAY_PUBLIC_ENDPOINT}", const.GREY_180,
                            cache_key=(id(font_small), "relay", const.RELAY_PUBLIC_ENDPOINT))
    surface.blit(relay, (const.WINDOW_WIDTH // 2 - relay.get_width() // 2, const.WINDOW_HEIGHT - const.BOTTOM_LINE_Y + 5))

    # room code
    room_label = code if code else "Offline"
    code_text = get_cached_text(font_small, f"Room Code: {room_label}", const.WHITE_240,
                                 cache_key=(id(font_small), "room_code", room_label))
    surface.blit(code_text, (10, const.WINDOW_HEIGHT - const.BOTTOM_LINE_Y + 5))

def draw_stage_ui(ui_surf, stage1, stage2, stage3, code, world_surf, world_size, checkpoints, buttons, 
                  error_msg, my_car, cam, gamepad, font_big, font_medium, font_small,
                  ai_path_mode_controls, engine_state, fps, dt, is_host, host_name=None, car_sprites_cache=None):
    """Draw UI elements based on current stage levels (stage1, stage2, stage3).
    
    Stage levels:
    - stage1: lobby | game | error
    - stage2: settings | new_game | join_game
    - stage3: controls
    """
    global _new_game_rects_cache, _join_game_rects_cache, _controls_rects_cache, _palette_picker_rects_cache, _game_rects_cache, _controls_rects_cache

    button_results = []
    # click detection
    new_game_rects = None
    join_game_rects = None
    controls_rects = None
    palette_picker_rects = None
    
    # Stage 1: Main stages
    if stage1 == "lobby":
        if stage2 == "settings":
            if stage3 == "controls":
                controls_rects = draw_controls(ui_surf, font_small)
                _controls_rects_cache = controls_rects
                draw_header(ui_surf, font_big, font_small, "Controls", fps, host_name)
            else:
                _controls_rects_cache = None
                world_surf, button_results = draw_settings(ui_surf, world_surf, world_size, buttons, [stage1, stage2], font_small)
                draw_header(ui_surf, font_big, font_small, "Settings", fps, host_name)
        elif stage2 == "new_game": 
            new_game_rects = draw_new_game(ui_surf, font_big, font_medium, car_sprites_cache, dt)
            draw_header(ui_surf, font_big, font_small, "Host Game", fps, host_name)
            _new_game_rects_cache = new_game_rects  # Cache for event handling
            _join_game_rects_cache = None  # Clear join game cache
        elif stage2 == "join_game":
            # Join game page doesn't need header/footer - it's a full page
            join_game_rects = draw_join_game(ui_surf, font_big, font_medium, car_sprites_cache, dt)
            draw_header(ui_surf, font_big, font_small, "Join Game", fps, host_name)
            _join_game_rects_cache = join_game_rects  # Cache for event handling
            _new_game_rects_cache = None  # Clear new game cache
        else:
            # draw_lobby()
            draw_header(ui_surf, font_big, font_small, "Lobby", fps, host_name)
            _new_game_rects_cache = None  # Clear cache when not in new_game
            _join_game_rects_cache = None  # Clear cache when not in join_game
        draw_footer(ui_surf, font_small)

    elif stage1 == "game":
        _new_game_rects_cache = None  # Clear cache when in game
        _join_game_rects_cache = None  # Clear cache when in game
        if stage2 == "settings": 
            if stage3 == "controls":
                controls_rects = draw_controls(ui_surf, font_small)
                _controls_rects_cache = controls_rects  # Cache for event handling
                draw_header(ui_surf, font_big, font_small, "Controls", fps, host_name)
            else:
                _controls_rects_cache = None  # Clear cache when not in controls
                world_surf, button_results = draw_settings(ui_surf, world_surf, world_size, buttons, [stage1, stage2], font_small)
                draw_header(ui_surf, font_big, font_small, "Settings", fps, host_name)
        else:
            _controls_rects_cache = None  # Clear cache when not in settings
            game_rects = draw_game(ui_surf, font_big, font_medium, is_host)
            _game_rects_cache = game_rects
            draw_header(ui_surf, font_big, font_small, "Waiting Room", fps, host_name)
            draw_controls_hud(ui_surf, ai_path_mode_controls, gamepad, my_car, cam, font_small, dt, engine_state, 7000)
        draw_footer(ui_surf, font_small, code)

    elif stage1 == "mode1":
        _new_game_rects_cache = None  # Clear cache when in game
        _join_game_rects_cache = None  # Clear cache when in game
        if stage2 == "settings":
            if stage3 == "controls":
                controls_rects = draw_controls(ui_surf, font_small)
                _controls_rects_cache = controls_rects  # Cache for event handling
                draw_header(ui_surf, font_big, font_small, "Controls", fps, host_name)
            else:
                _controls_rects_cache = None  # Clear cache when not in controls
                world_surf, button_results = draw_settings(ui_surf, world_surf, world_size, buttons, [stage1, stage2], font_small)
                draw_header(ui_surf, font_big, font_small, "Settings", fps, host_name)
        else:
            _controls_rects_cache = None  # Clear cache when not in settings
            draw_mode1(ui_surf, font_big, font_medium, cam, checkpoints)
            palette_picker_rects = draw_color_palette_picker(ui_surf, font_small)
            _palette_picker_rects_cache = palette_picker_rects
            draw_header(ui_surf, font_big, font_small, "Classic Race", fps, host_name)
            draw_controls_hud(ui_surf, ai_path_mode_controls, gamepad, my_car, cam, font_small, dt, engine_state, 7000)
        draw_footer(ui_surf, font_small, code)

    elif stage1 == "mode2":
        _new_game_rects_cache = None  # Clear cache when in game
        _join_game_rects_cache = None  # Clear cache when in game
        if stage2 == "settings": 
            if stage3 == "controls":
                controls_rects = draw_controls(ui_surf, font_small)
                _controls_rects_cache = controls_rects  # Cache for event handling
                draw_header(ui_surf, font_big, font_small, "Controls", fps, host_name)
            else:
                _controls_rects_cache = None  # Clear cache when not in controls
                world_surf, button_results = draw_settings(ui_surf, world_surf, world_size, buttons, [stage1, stage2], font_small)
                draw_header(ui_surf, font_big, font_small, "Settings", fps, host_name)
        else:
            _controls_rects_cache = None  # Clear cache when not in settings
            draw_mode2(ui_surf, font_big, font_medium, cam, checkpoints)
            palette_picker_rects = draw_color_palette_picker(ui_surf, font_small)
            _palette_picker_rects_cache = palette_picker_rects
            draw_header(ui_surf, font_big, font_small, "Mode 2", fps, host_name)
            draw_controls_hud(ui_surf, ai_path_mode_controls, gamepad, my_car, cam, font_small, dt, engine_state, 7000)
        draw_footer(ui_surf, font_small, code)

    elif stage1 == "error":
        _new_game_rects_cache = None  # Clear cache when in error
        _join_game_rects_cache = None  # Clear cache when in error
        draw_header(ui_surf, font_big, font_small, "Error", fps)
        draw_error(ui_surf, error_msg, font_small)
        draw_footer(ui_surf, font_small, code)
    
    return world_surf, button_results, new_game_rects, join_game_rects, palette_picker_rects

def handle_game_events(screen, ev, stage1, stage2, stage3, gamepad, remotes, ai_cars, sock, code, my_name, my_id, my_car, font_big, font_small, error_msg, is_host_flag_ref, host_name=None, new_game_rects=None, track_image=None, chunked_map=None, checkpoints=None):
    """Handle game events including new game UI interactions."""
    global _new_game_rects_cache, _palette_picker_rects_cache

    if ev.type == pygame.KEYDOWN: # press a key
        if stage1 == "lobby": # in lobby
            if stage2 == "": # main lobby
                if ev.key == const.ESCAPE_KEY:
                    stage2 = "settings"
                if ev.key == const.HOST_KEY: # h
                    stage2 = "new_game" # host a room - open new game UI
                    reset_game_setup()  # Reset to defaults when opening
                if ev.key == const.JOIN_KEY: # j
                    stage2 = "join_game" # join a room - open join game UI
                    reset_game_setup()  # Reset to defaults when opening
            elif stage2 == "settings":
                if stage3 == "controls":
                    result = handle_controls_keypress(ev)
                    if result == "saved":
                        invalidate_ui_text_cache('all')
                    elif result == "back":
                        stage3 = ""
                elif stage3 == "" and ev.key == const.ESCAPE_KEY:
                    stage2 = ""
            elif stage2 == "new_game": # hosting game
                handle_new_game_keypress(ev)
                if ev.key == const.ESCAPE_KEY: # esc
                    stage2 = "" # go back to lobby
                    reset_game_setup()
                if ev.key in const.RETURN_KEYS and not has_pending_connection():
                    setup = get_game_setup()
                    _start_host_connection(my_id, setup, my_car, is_host_flag_ref)
            elif stage2 == "join_game": # joining game
                handle_join_game_keypress(ev)
                if ev.key == const.ESCAPE_KEY: # esc to go back to lobby
                    stage2 = ""
                    reset_game_setup()
                if ev.key in const.RETURN_KEYS and not has_pending_connection():
                    setup = get_game_setup()
                    if not setup["room_code"]: set_error_message("room code missing")
                    elif len(setup["room_code"]) < 4: set_error_message("room code too short")
                    else:
                        clear_error_message()
                        _start_join_connection(my_id, setup, my_car, is_host_flag_ref)
        elif stage1 in ["game", "mode1", "mode2", "leaderboard"]: # in game
            if stage2 == "" and ev.key == const.ESCAPE_KEY: 
                stage2 = "settings" # open settings
            elif stage2 == "settings":
                if stage3 == "controls":
                    result = handle_controls_keypress(ev)
                    if result == "saved":
                        invalidate_ui_text_cache('all')  # Refresh cached text after save
                    elif result == "back":
                        stage3 = ""  # Go back to settings menu
                elif stage3 == "" and ev.key == const.ESCAPE_KEY:
                    stage2 = "" # close settings
            elif stage2 == "":  # In game, not in settings
                # Handle palette picker key controls
                handle_palette_picker_keypress(ev)
        elif stage1 == "error" and ev.key == const.RESET_KEY: # r to reset from error
            stage1 = "lobby"
            stage2 = ""
            error_msg = ""
            remotes.clear()
            ai_cars.clear()
            if sock:
                try:
                    sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                except Exception:
                    pass
                sock.close()
                sock = None
            code = None
            import random
            spawnx = random.uniform(const.WINDOW_WIDTH*0.3, const.WINDOW_WIDTH*0.7)
            spawny = random.uniform(const.WINDOW_HEIGHT*0.3, const.WINDOW_HEIGHT*0.7)
            import drift.core.car as car
            my_car = car.Car(spawnx, spawny, my_name, is_ai=False, car_type="ae86")
    
    # Handle mouse clicks in new_game UI
    elif ev.type == pygame.MOUSEBUTTONDOWN:
        if stage1 == "lobby" and stage2 == "new_game" and _new_game_rects_cache:
            action = handle_new_game_click(ev.pos, _new_game_rects_cache)
            
            if action == "host_game" and not has_pending_connection():
                setup = get_game_setup()
                _start_host_connection(my_id, setup, my_car, is_host_flag_ref)
        elif stage1 == "lobby" and stage2 == "join_game" and _join_game_rects_cache:
            action = handle_join_game_click(ev.pos, _join_game_rects_cache)

            if action == "join_game" and not has_pending_connection():
                setup = get_game_setup()
                _start_join_connection(my_id, setup, my_car, is_host_flag_ref)
        elif stage1 == "game" and stage2 == "" and _game_rects_cache:
            start_btn = _game_rects_cache.get("start_btn") # Start button
            if start_btn and start_btn.collidepoint(ev.pos):
                setup = get_game_setup()
                if not is_host_flag_ref[0]:
                    set_error_message("only host can start game")
                elif sock:
                    try:
                        # Wait for relay echo/world update before changing stage locally.
                        sock.send(json.dumps({"t": "start_race", "code": code, "id": my_id, "mode": setup['selected_mode']}).encode("utf-8")) # client -> server
                    except Exception as e:
                        print(f"Error sending start: {e}")
                else:
                    # Offline fallback: no relay echo will arrive, so switch mode locally.
                    selected_mode = setup.get("selected_mode", "mode1")
                    stage1 = selected_mode if selected_mode in ["mode1", "mode2"] else "mode1"
                    clear_error_message()

        elif stage1 in ["mode1", "mode2"] and stage2 == "" and _palette_picker_rects_cache:
            handle_palette_picker_click(ev.pos, _palette_picker_rects_cache)
        elif stage1 in ["game", "mode1", "mode2", "leaderboard"] and stage2 == "settings" and stage3 == "controls" and _controls_rects_cache:
            res = handle_controls_click(ev.pos, _controls_rects_cache, gamepad)
            if res and res.startswith("gp_connected_"):
                stage2 = "" ; stage3 = "" # close controls & settings to confirm connection

    if gamepad and gamepad.joystick:
        js = gamepad.joystick
        if stage1 == "lobby": # in lobby
            if stage2 == "": # main lobby
                if js.get_button(6): # - -> join game (j)
                    stage2 = "join_game"
                    reset_game_setup()
                elif js.get_button(7): # + -> host game (h)
                    stage2 = "new_game"
                    reset_game_setup()
            elif stage2 == "new_game": # hosting game
                if js.get_button(8): # left stick press -> cancel (esc)
                    stage2 = "" # go back to lobby
                    reset_game_setup()
                elif js.get_button(9) and not has_pending_connection(): # right stick press -> confirm (enter)
                    setup = get_game_setup()
                    _start_host_connection(my_id, setup, my_car, is_host_flag_ref)
            elif stage2 == "join_game": # joining game
                if js.get_button(8): # left stick press -> cancel (esc)
                    stage2 = "" # go back to lobby
                    reset_game_setup()
                elif js.get_button(9) and not has_pending_connection(): # right stick press -> confirm (enter)
                    setup = get_game_setup()
                    if not setup["room_code"]: set_error_message("room code missing")
                    elif len(setup["room_code"]) < 4: set_error_message("room code too short")
                    else:
                        clear_error_message()
                        _start_join_connection(my_id, setup, my_car, is_host_flag_ref)
        elif stage1 in ["game", "mode1", "mode2", "leaderboard"]: # in game
            if stage2 == "": # main game screen
                if js.get_button(8): # left stick press -> open settings (esc)
                    stage2 = "settings"
            elif stage2 == "settings": # in settings menu
                if stage3 == "controls": # do not handle joystick buttons yet
                    if js.get_button(8): # left stick press -> back (esc)
                        stage3 = ""
                elif stage3 == "":
                    if js.get_button(8): # left stick press -> close settings (esc)
                        stage2 = ""
    
    # Handle slider events in settings menu (all event types)
    if ((stage1 in ["game", "mode1", "mode2", "leaderboard"] and stage2 == "settings" and stage3 == "") or 
        (stage1 == "lobby" and stage2 == "settings" and stage3 == "")):
        settings_manager.handle_slider_events(ev)

    return ev, stage1, stage2, stage3, remotes, sock, code, my_car, error_msg, host_name, track_image, chunked_map, checkpoints

def _get_cached_hud_font(font_small: pygame.font.Font, scale: float) -> pygame.font.Font:
    """Get or create a cached scaled font for HUD elements."""
    font_size = max(1, int(font_small.get_height() * scale))
    if font_size not in _hud_font_cache:
        _hud_font_cache[font_size] = pygame.font.SysFont(None, font_size)
    return _hud_font_cache[font_size]

def draw_controls_hud(ui_surf: pygame.Surface, ai_path_mode_controls, gamepad, my_car, cam, font_small, dt, engine_state, rpm_redline: float = 7000.0) -> None:
    """Draw bottom-right HUD with RPM gauge, steering wheel, throttle and brake bars.

    Parameters
    - st: steering input in [-1, 1]
    - th: throttle input in [-1, 1] (negative means reverse)
    - br: brake input in [0, 1]
    - rpm: optional engine RPM; if None, a simple estimate is derived from throttle
    - rpm_redline: maximum RPM for gauge scaling
    """

    # HUD: steering wheel + throttle/brake % bars (bottom-right)
    # Use the pre-computed controls dict passed from the main loop
    inp = ai_path_mode_controls if ai_path_mode_controls is not None else {"th": 0.0, "st": 0.0, "br": 0.0}

    th = clamp(inp.get("th", 0.0), -1.0, 1.0)
    br = clamp(inp.get("br", 0.0), 0.0, 1.0)
    st = clamp(inp.get("st", 0.0), -1.0, 1.0)

    # RPM already computed in the main loop physics phase
    rpm = engine_state.get("last_rpm") or 0.0

    # Apply UI scaling
    s = getattr(const, "UI_SCALE", 1.0)
    def sc(v: float) -> int:
        return int(round(v * s))

    # Compute a simple RPM if not supplied (idle -> redline by throttle)
    if rpm is None:
        rpm = abs(clamp(th, -1.0, 1.0)) * rpm_redline
    rpm = clamp(rpm, 0.0, rpm_redline)

    # HUD layout
    pad = sc(12)
    hud_h = sc(120)
    wheel_size = sc(76)
    gauge_size = sc(76)  # analog RPM gauge, same size as steering wheel

    # Compute dynamic width: gauge + wheel + bars area
    bars_min_width = sc(110)
    hud_w = gauge_size + wheel_size + bars_min_width + sc(32)  # extra padding/margins

    x = const.WINDOW_WIDTH - hud_w - pad
    y = const.WINDOW_HEIGHT - hud_h - pad

    # semi-transparent background
    bg = pygame.Surface((hud_w, hud_h), pygame.SRCALPHA)
    bg.fill((10, 10, 14, 200))
    ui_surf.blit(bg, (x, y))

    # --- RPM Gauge (left) ---
    gcx = x + gauge_size // 2 + sc(10)
    gcy = y + hud_h // 2
    g_r_outer = gauge_size // 2
    g_r = g_r_outer - sc(8)
    # outer ring
    
    pygame.draw.circle(ui_surf, (40, 40, 48), (gcx, gcy), g_r_outer)
    pygame.draw.circle(ui_surf, (20, 20, 26), (gcx, gcy), g_r_outer - sc(2))
    pygame.draw.circle(ui_surf, (60, 60, 70), (gcx, gcy), g_r, max(1, sc(4)))

    # Gauge angles and mapping (sweep from ~210° to ~330°)
    a0 = math.radians(100.0)
    a1 = math.radians(330.0)
    def angle_for_rpm(val: float) -> float:
        f = 0.0 if rpm_redline <= 0 else clamp(val / rpm_redline, 0.0, 1.0)
        return a0 + (a1 - a0) * f

    # ticks (0..8 x1000)
    max_k = int(rpm_redline // 1000)
    for k in range(0, max_k + 1):
        frac = k / max(1, max_k)
        ang = a0 + (a1 - a0) * frac
        ca, sa = math.cos(ang), math.sin(ang)
        r0 = g_r - sc(8)
        r1 = g_r + sc(2)
        color = (220, 80, 80) if k >= max_k - 1 else (180, 180, 190)
        x0, y0 = int(gcx + ca * r0), int(gcy + sa * r0)
        x1, y1 = int(gcx + ca * r1), int(gcy + sa * r1)
        pygame.draw.line(ui_surf, color, (x0, y0), (x1, y1), max(1, sc(2 if k % 2 == 0 else 1)))

        # numeric labels: 1000->"1", 2000->"2", ... skip 0
        if k >= 1:
            r_label = g_r + sc(10)
            lx = int(gcx + ca * r_label)
            ly = int(gcy + sa * r_label)
            fs = _get_cached_hud_font(font_small, s)
            ts = fs.render(str(k), True, const.GREY_200)
            ui_surf.blit(ts, (lx - ts.get_width() // 2, ly - ts.get_height() // 2))

    # needle
    ang = angle_for_rpm(rpm)
    nx = int(gcx + math.cos(ang) * (g_r - sc(12)))
    ny = int(gcy + math.sin(ang) * (g_r - sc(12)))
    needle_color = (240, 80, 80) if rpm > rpm_redline * 0.9 else (240, 220, 220)
    pygame.draw.line(ui_surf, needle_color, (gcx, gcy), (nx, ny), max(1, sc(3)))
    pygame.draw.circle(ui_surf, (30, 30, 36), (gcx, gcy), sc(6))

    # gauge label
    fs = _get_cached_hud_font(font_small, s)
    lbl_rpm = fs.render("RPM", True, const.WHITE_240)
    ui_surf.blit(lbl_rpm, (gcx - lbl_rpm.get_width()//2, y + sc(6)))
    small = fs.render("x1000", True, const.GREY_180)
    ui_surf.blit(small, (gcx - small.get_width()//2, y + hud_h - sc(18)))

    # --- Steering wheel (middle) ---
    wcx = x + gauge_size + sc(20) + wheel_size // 2
    wcy = y + hud_h // 2
    wheel_r = wheel_size // 2 - sc(6)
    pygame.draw.circle(ui_surf, (40, 40, 48), (wcx, wcy), wheel_r + sc(6))  # rim shadow
    pygame.draw.circle(ui_surf, (20, 20, 26), (wcx, wcy), wheel_r + sc(4))
    pygame.draw.circle(ui_surf, (60, 60, 70), (wcx, wcy), wheel_r, max(1, sc(6)))   # rim

    # steering indicator (spoke)
    MAX_WHEEL_ANGLE = math.radians(270)  # visual rotation range
    angle = st * MAX_WHEEL_ANGLE - (math.pi / 2)  # negative so positive steering rotates clockwise visually
    sx = int(wcx + math.cos(angle) * (wheel_r - sc(10)))
    sy = int(wcy + math.sin(angle) * (wheel_r - sc(10)))
    pygame.draw.line(ui_surf, (200, 200, 220), (wcx, wcy), (sx, sy), max(1, sc(6)))
    # small center hub
    pygame.draw.circle(ui_surf, (30, 30, 36), (wcx, wcy), sc(8))

    # Labels
    fs = _get_cached_hud_font(font_small, s)
    lbl = fs.render("STEER", True, const.WHITE_240)
    ui_surf.blit(lbl, (wcx - lbl.get_width()//2, y + hud_h - sc(18)))

    # --- throttle and brake bars (right side) ---
    bar_x = x + gauge_size + wheel_size + sc(30)
    bar_w = hud_w - (gauge_size + wheel_size + sc(32))
    bar_h = sc(16)
    # Throttle bar (top)
    th_y = y + sc(25)
    pygame.draw.rect(ui_surf, (40, 40, 48), (bar_x, th_y, bar_w, bar_h), border_radius=sc(4))
    if th > 0:
        fg_w = int(bar_w * clamp(th, 0.0, 1.0))
        pygame.draw.rect(ui_surf, (80, 220, 100), (bar_x, th_y, fg_w, bar_h), border_radius=sc(4))
    else:
        # reverse/backwards shown as orange to the left of bar
        fg_w = int(bar_w * clamp(-th, 0.0, 1.0))
        pygame.draw.rect(ui_surf, (255, 160, 60), (bar_x + bar_w - fg_w, th_y, fg_w, bar_h), border_radius=sc(4))
    th_pct = int(th * 100) if th >= 0 else int(th * 100)
    fs = _get_cached_hud_font(font_small, s)
    lbl_th = fs.render(f"THR {th_pct:+d}%", True, const.WHITE_240)
    ui_surf.blit(lbl_th, (bar_x, th_y - sc(18)))

    # Brake bar (bottom)
    br_y = th_y + bar_h + sc(25)
    pygame.draw.rect(ui_surf, (40, 40, 48), (bar_x, br_y, bar_w, bar_h), border_radius=sc(4))
    fg_wb = int(bar_w * clamp(br, 0.0, 1.0))
    pygame.draw.rect(ui_surf, (220, 80, 80), (bar_x, br_y, fg_wb, bar_h), border_radius=sc(4))
    lbl_br = fs.render(f"BRK {int(br*100):d}%", True, const.WHITE_240)
    ui_surf.blit(lbl_br, (bar_x, br_y - sc(18)))

    # Optional thin border around HUD
    pygame.draw.rect(ui_surf, (80, 88, 100), (x, y, hud_w, hud_h), max(1, sc(1)))


