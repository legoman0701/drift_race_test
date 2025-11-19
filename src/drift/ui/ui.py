# global
import math, json, pygame

# local
import drift.config.const as const
from drift.core.car import CAR_LEN, CAR_WID
from drift.core.helpers import clamp
from drift.core.inputs import read_inputs
from drift.core.rpm import calc_engine_rpm
from drift.ui.ui_helpers import get_cached_text, invalidate_ui_text_cache
from drift.ui.draw_stage import (
    draw_new_game, draw_join_game, draw_settings, draw_error,
    handle_new_game_click, handle_new_game_keypress, host_new_game, draw_key_binds,
    handle_join_game_click, handle_join_game_keypress, join_new_game,
    handle_key_binds_click, handle_key_binds_keypress,
    get_game_setup, reset_game_setup, set_error_message, clear_error_message
)
from drift.config.settings import settings_manager

_car_name_font_cache = {} # car name cache
_new_game_rects_cache = None # new game rects cache
_join_game_rects_cache = None # join game rects cache
_key_binds_rects_cache = None # key binds rects cache

def draw_car(surface, x, y, angle, name,
             color_body=const.COLOR_BODY_DEFAULT,
             color_nose=const.COLOR_NOSE_DEFAULT, car_sprites_list=None, lights_on=False):
    if car_sprites_list is None:
        car_sprites_list = []
    for i, car_sprite in enumerate(car_sprites_list):
        if i == 2:  # light spray
            if not lights_on:
                continue
            show_angle = (-angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
            sprite_index = round(show_angle * 64) % 64
            sprite_size = (car_sprite[sprite_index].get_width(), car_sprite[sprite_index].get_height())
            surface.blit(car_sprite[sprite_index],
                         (int(x - sprite_size[0] // 2), int(y - sprite_size[1] // 2)),
                         special_flags=pygame.BLEND_RGB_ADD)
        elif i == 0:  # shadow (shadown mask to be made)
            show_angle = (-angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
            sprite_index = round(show_angle * 64) % 64
            sprite_size = (car_sprite[sprite_index].get_width(), car_sprite[sprite_index].get_height())
            surface.blit(car_sprite[sprite_index], (int(x - sprite_size[0] // 2), int(y - sprite_size[1] // 2)))
        else:
            show_angle = (-angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
            sprite_index = round(show_angle * 64) % 64
            sprite_size = (car_sprite[sprite_index].get_width(), car_sprite[sprite_index].get_height())
            surface.blit(car_sprite[sprite_index], (int(x - sprite_size[0] // 2), int(y - sprite_size[1] // 2)))

    # Draw oriented collision rectangle overlay
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

    # Return rear-wheel edge points for tire mark drawing by callers (indices 2 and 3)
    return (wpts[2], wpts[3])

_debug_font_cache = None # debug text cache
_hud_font_cache = {} # HUD text cache

def draw_wheel_debug(surface: pygame.Surface, car, offx: int = 0, offy: int = 0) -> None:
    """Visualize per-wheel forces and angles for a car.

    - Draws longitudinal (green/red) and lateral (blue) force arrows per wheel.
    - Renders small text with slip angle and wheel angle near each wheel.
    - offx/offy: camera offset to convert world->screen (used in chunked renderer).
    """
    global _debug_font_cache
    if not hasattr(car, "wheel_debug"):
        return
    wheels = car.wheel_debug.get("wheels", [])

    # Scale factors for arrow lengths
    k_long = 0.06  # pixels per unit force
    k_lat = 0.06
    # Use cached font to avoid expensive font creation every frame
    if _debug_font_cache is None:
        _debug_font_cache = pygame.font.SysFont(None, 14)
    font = _debug_font_cache

    for w in wheels:
        wx, wy = w["world_pos"]
        wl_ang = w["wheel_angle"]
        Fl = w["F_long"]
        Ft = w["F_lat"]
        slip = w["slip"]

        # Wheel forward axis in world
        ca, sa = math.cos(car.angle + wl_ang), math.sin(car.angle + wl_ang)
        # Build arrow endpoints
        # Longitudinal: along wheel heading
        ex_long = wx + ca * Fl * k_long
        ey_long = wy + sa * Fl * k_long
        # Lateral: perpendicular to wheel heading (to the left of wheel axis)
        nx, ny = -sa, ca
        ex_lat = wx + nx * Ft * k_lat
        ey_lat = wy + ny * Ft * k_lat

        # Convert to screen
        sx, sy = int(wx - offx), int(wy - offy)
        sxL, syL = int(ex_long - offx), int(ey_long - offy)
        sxT, syT = int(ex_lat - offx), int(ey_lat - offy)

        # Draw axes dot
        pygame.draw.circle(surface, (240, 240, 255), (sx, sy), 2)
        # Longitudinal arrow (green forward, red backward)
        color_long = (80, 220, 100) if Fl >= 0 else (230, 80, 80)
        pygame.draw.line(surface, color_long, (sx, sy), (sxL, syL), 2)
        # Lateral arrow (blue)
        pygame.draw.line(surface, (80, 120, 255), (sx, sy), (sxT, syT), 2)

        # Text with values (rounded for readability)
        txt = f"ang={math.degrees(wl_ang):.0f}° slip={math.degrees(slip):.0f}°\nFx={Fl:.0f} Fy={Ft:.0f}"
        # Render multiline: split lines
        lines = txt.split("\n")
        ty = sy - 22
        for i, line in enumerate(lines):
            ts = font.render(line, True, (230, 230, 245))
            surface.blit(ts, (sx + 6, ty + i * 12))

    # Draw body-level forces (rolling, aero, brake) from car center
    body_forces = car.wheel_debug.get("body_forces")
    if body_forces:
        cx, cy = int(car.x - offx), int(car.y - offy)
        k_body = 0.06
        roll = body_forces.get("rolling", (0.0, 0.0))
        drag = body_forces.get("aero_drag", (0.0, 0.0))
        brk  = body_forces.get("brake", (0.0, 0.0))

        def draw_vec(vec, color):
            ex = int(cx + vec[0] * k_body)
            ey = int(cy + vec[1] * k_body)
            pygame.draw.line(surface, color, (cx, cy), (ex, ey), 2)

        draw_vec(roll, (200, 180, 80))   # rolling resistance: amber
        draw_vec(drag, (180, 80, 220))   # aero drag: purple
        draw_vec(brk,  (240, 80, 80))    # brake drag: red

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

def draw_stage_ui(ui_surf, stage1, stage2, stage3, code, world_surf, world_size, buttons, 
                  error_msg, my_car, cam, joysticks, font_big, font_medium, font_small,
                  ai_path_mode_controls, engine_state, fps, dt, host_name=None, car_sprites_cache=None):
    """Draw UI elements based on current stage levels (stage1, stage2, stage3).
    
    Stage levels:
    - stage1: lobby | game | error
    - stage2: settings | new_game | join_game
    - stage3: key_binds
    """
    global _new_game_rects_cache, _join_game_rects_cache, _key_binds_rects_cache

    button_results = []
    # click detection
    new_game_rects = None
    join_game_rects = None
    key_binds_rects = None
    
    # Stage 1: Main stages
    if stage1 == "lobby":
        if stage2 == "settings":
            if stage3 == "key_binds":
                draw_header(ui_surf, font_big, font_small, "Key Bindings", fps, host_name)
            else:
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
            if stage3 == "key_binds":
                key_binds_rects = draw_key_binds(ui_surf, font_small)
                _key_binds_rects_cache = key_binds_rects  # Cache for event handling
                draw_header(ui_surf, font_big, font_small, "Key Bindings", fps, host_name)
            else:
                _key_binds_rects_cache = None  # Clear cache when not in key_binds
                world_surf, button_results = draw_settings(ui_surf, world_surf, world_size, buttons, [stage1, stage2], font_small)
                draw_header(ui_surf, font_big, font_small, "Settings", fps, host_name)
        else:
            _key_binds_rects_cache = None  # Clear cache when not in settings
            # draw_game()
            draw_header(ui_surf, font_big, font_small, "In Game", fps, host_name)
            draw_controls_hud(ui_surf, ai_path_mode_controls, joysticks, my_car, cam, font_small, dt, engine_state, 7000)
        draw_footer(ui_surf, font_small, code)

    elif stage1 == "error":
        _new_game_rects_cache = None  # Clear cache when in error
        _join_game_rects_cache = None  # Clear cache when in error
        draw_header(ui_surf, font_big, font_small, "Error", fps)
        draw_error(ui_surf, error_msg, font_small)
        draw_footer(ui_surf, font_small, code)
    
    return world_surf, button_results, new_game_rects, join_game_rects

def handle_game_events(screen, ev, stage1, stage2, stage3, remotes, ai_cars, sock, code, my_name, my_id, my_car, font_big, font_small, error_msg, is_host_flag_ref, host_name=None, new_game_rects=None):
    """Handle game events including new game UI interactions."""
    global _new_game_rects_cache
    
    if ev.type == pygame.KEYDOWN: # press a key
        if stage1 == "lobby": # in lobby
            if stage2 == "" and ev.key == const.HOST_KEY:  # h
                stage2 = "new_game" # host a room - open new game UI
                reset_game_setup()  # Reset to defaults when opening
            elif stage2 == "" and ev.key == const.JOIN_KEY:  # j
                stage2 = "join_game" # join a room - open join game UI
                reset_game_setup()  # Reset to defaults when opening
            elif stage2 == "new_game": # in new_game UI
                handle_new_game_keypress(ev)
                if ev.key == const.ESCAPE_KEY: # esc
                    stage2 = "" # go back to lobby
                    reset_game_setup()
                if ev.key in const.RETURN_KEYS:
                    setup = get_game_setup()
                    if setup["username"]:  # Only proceed if username is entered
                        stage1, my_name, code, sock, is_host, host_name = host_new_game(my_id)
                        stage2 = "" # Close new_game UI
                        is_host_flag_ref[0] = is_host
                        my_car.name = my_name # update car with new name
                        my_car.car_type = setup["selected_car"] # update car selected car type
                        my_car.x = const.WINDOW_WIDTH // 2
                        my_car.y = const.WINDOW_HEIGHT // 2
                    else:
                        set_error_message("username missing")
            elif stage2 == "join_game": # in join_game UI
                handle_join_game_keypress(ev)
                if ev.key == const.ESCAPE_KEY: # esc to go back to lobby
                    stage2 = ""
                    reset_game_setup()
                if ev.key in const.RETURN_KEYS:
                    setup = get_game_setup()
                    if not setup["username"]:
                        set_error_message("username missing")
                    elif not setup["room_code"]:
                        set_error_message("room code missing")
                    elif len(setup["room_code"]) < 4:
                        set_error_message("room code too short")
                    else: # Only proceed if username is entered
                        clear_error_message()
                        stage1, my_name, code, sock, is_host, host_name, error = join_new_game(my_id)
                        if error: set_error_message(error)
                        else:
                            stage2 = "" # Close new_game UI
                            my_car.name = my_name # update car with new name
                            my_car.car_type = setup["selected_car"] # update car selected car type
                            my_car.x = const.WINDOW_WIDTH // 2
                            my_car.y = const.WINDOW_HEIGHT // 2
        elif stage1 == "game": # in game
            if stage2 == "" and ev.key == const.ESCAPE_KEY: 
                stage2 = "settings" # open settings
            elif stage2 == "settings":
                if stage3 == "key_binds":
                    result = handle_key_binds_keypress(ev)
                    if result == "saved":
                        invalidate_ui_text_cache('all')  # Refresh cached text after save
                    elif result == "back":
                        stage3 = ""  # Go back to settings menu
                elif stage3 == "" and ev.key == const.ESCAPE_KEY:
                    stage2 = "" # close settings
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
            
            if action == "host_game":
                # Get game setup and start hosting
                setup = get_game_setup()
                if setup["username"]:  # Only proceed if username is entered
                    stage1, my_name, code, sock, is_host, host_name = host_new_game(my_id)
                    is_host_flag_ref[0] = is_host
                    stage2 = ""  # Close new_game UI
                    
                    # Update car with new name and selected car type
                    my_car.name = my_name
                    my_car.car_type = setup["selected_car"]
        elif stage1 == "lobby" and stage2 == "join_game" and _join_game_rects_cache:
            action = handle_join_game_click(ev.pos, _join_game_rects_cache)

            if action == "join_game":
                # Get game setup and start joining
                setup = get_game_setup()
                if setup["username"]:  # Only proceed if username is entered
                    stage1, my_name, code, sock, is_host, host_name = join_new_game(my_id)
                    stage2 = ""  # Close new_game UI
                    
                    # Update car with new name and selected car type
                    my_car.name = my_name
                    my_car.car_type = setup["selected_car"]
        elif stage1 == "game" and stage2 == "settings" and stage3 == "key_binds" and _key_binds_rects_cache:
            handle_key_binds_click(ev.pos, _key_binds_rects_cache)
    
    # Handle slider events in settings menu (all event types)
    if ((stage1 == "game" and stage2 == "settings" and stage3 == "") or 
        (stage1 == "lobby" and stage2 == "settings" and stage3 == "")):
        settings_manager.handle_slider_events(ev)

    return ev, stage1, stage2, stage3, remotes, sock, code, my_car, error_msg, host_name

def _get_cached_hud_font(font_small: pygame.font.Font, scale: float) -> pygame.font.Font:
    """Get or create a cached scaled font for HUD elements."""
    font_size = max(1, int(font_small.get_height() * scale))
    if font_size not in _hud_font_cache:
        _hud_font_cache[font_size] = pygame.font.SysFont(None, font_size)
    return _hud_font_cache[font_size]

def draw_controls_hud(ui_surf: pygame.Surface, ai_path_mode_controls, joysticks, my_car, cam, font_small, dt, engine_state, rpm_redline: float = 7000.0) -> None:
    """Draw bottom-right HUD with RPM gauge, steering wheel, throttle and brake bars.

    Parameters
    - st: steering input in [-1, 1]
    - th: throttle input in [-1, 1] (negative means reverse)
    - br: brake input in [0, 1]
    - rpm: optional engine RPM; if None, a simple estimate is derived from throttle
    - rpm_redline: maximum RPM for gauge scaling
    """

    # HUD: steering wheel + throttle/brake % bars (bottom-right)
    if const.AI_PATH_FOLLOW and ai_path_mode_controls is not None: 
        inp = ai_path_mode_controls
    else: 
        inp = read_inputs(joysticks, my_car, cam, const.CURSOR_FOLLOW, const.AI_PATH_FOLLOW)

    th = clamp(inp.get("th", 0.0), -1.0, 1.0)
    br = clamp(inp.get("br", 0.0), 0.0, 1.0)
    st = clamp(inp.get("st", 0.0), -1.0, 1.0)
    
    # Engine RPM estimation: uses speed, drift state, throttle and smoothing
    speed_units = math.hypot(my_car.vx, my_car.vy)
    # Persist transient engine state externally (gear, last rpm)
    prev_rpm = engine_state.get("last_rpm")
    rpm = calc_engine_rpm(
        speed_units=speed_units,
        drift_ratio=my_car.drift_ratio,
        throttle=th,
        prev_rpm=prev_rpm,
        dt=dt,
        params=None,
        _state=engine_state,
    )
    engine_state["last_rpm"] = rpm

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


