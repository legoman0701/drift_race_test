#!/usr/bin/env python3

# ======= IMPORTS =======

# global imports
import pygame, json, time, random, sys, math, uuid, argparse
from collections import deque
# local imports
from drift.tools.paths import asset_path, chdir_to_exe_folder_if_frozen, get_available_cars, normalize_asset_path, get_available_sprite_layers
import drift.config.const as const
import drift.render.camera as camera
import drift.core.car as car
from drift.core.car import get_car_engine_sound_id
import drift.ui.button as btn
import drift.ai.path_finder as path_finder
from drift.render.renderer import WorldRenderer
from drift.core.helpers import clamp, rand_name
from drift.core.gamemode import SimpleRace
from drift.ai.ai import ai_algorithme
from drift.core.inputs import read_inputs
from drift.net.communication import connect_to_relay, handle_network_messages, send_network_state, send_ai_states, send_ping, recv_jsons
from drift.ui.ui import handle_game_events, draw_stage_ui, invalidate_ui_text_cache, invalidate_palette_cache, draw_car
from drift.ui.draw_stage import set_palette_colors_from_car, get_palette_colors
from drift.core.rpm import calc_engine_rpm
from drift.audio.engine_audio import V8EngineAudio
from drift.audio.gear_shift_sound import GearShiftSound
from drift.render.map_chunks import ChunkedMap
from drift.core.gamepad import Gamepad

# ======= CONFIGURATION =======

chdir_to_exe_folder_if_frozen()

# ======= RELAY =======

RELAY_PUBLIC_ENDPOINT = const.RELAY_PUBLIC_ENDPOINT
# True : client creates a room, False : joining
I_AM_HOST = False

flags = const.FLAGS

# ======= LOADING SCREEN =======

def draw_loading_screen(screen, progress, total_steps, current_task="Loading...", gpu_display=None):
    """Draw a loading screen with circular progress bar from 7π/4 to π/4"""
    screen.fill(const.GREY_20)  # Dark background
    
    # Create fonts for loading screen
    title_font = pygame.font.SysFont(None, 72)
    task_font = pygame.font.SysFont(None, 36)
    
    # Calculate center
    center_x = const.WINDOW_WIDTH // 2
    center_y = const.WINDOW_HEIGHT // 2
    
    # Draw title
    title_text = title_font.render(f"Drift Race v{const.VERSION}", True, (255, 255, 255))
    title_rect = title_text.get_rect(center=(center_x, center_y - 100))
    screen.blit(title_text, title_rect)
    
    # Draw current task
    task_text = task_font.render(current_task, True, (200, 200, 200))
    task_rect = task_text.get_rect(center=(center_x, center_y + 80))
    screen.blit(task_text, task_rect)
    
    # Draw circular progress bar
    radius = 50
    thickness = 8
    
    # Background circle (darker)
    pygame.draw.circle(screen, (60, 60, 80), (center_x, center_y), radius, thickness)
    
    # Calculate progress angle
    # From 7π/4 (315°) to π/4 (45°) = 90° total sweep
    # 7π/4 = -π/4 in standard position
    start_angle = -5*math.pi / 4  # 7π/4 in standard position
    end_angle = math.pi / 4     # π/4
    total_sweep = end_angle - start_angle  # π/2 radians (90°)
    
    if total_steps > 0:
        progress_ratio = min(progress / total_steps, 1.0)
        
        # Draw progress arc
        if progress_ratio > 0:
            # Create points for the arc
            arc_points = []
            num_segments = max(1, int(progress_ratio * 50))  # More segments for smoother arc
            
            for i in range(num_segments + 1):
                angle = start_angle + (total_sweep * progress_ratio * i / num_segments)
                x = center_x + (radius - thickness // 2) * math.cos(angle)
                y = center_y + (radius - thickness // 2) * math.sin(angle)
                arc_points.append((x, y))
            
            # Draw the progress arc as a thick line
            if len(arc_points) > 1:
                for i in range(len(arc_points) - 1):
                    pygame.draw.line(screen, (100, 200, 255), arc_points[i], arc_points[i + 1], thickness)
    
    # Draw percentage text
    percentage = int((progress / max(total_steps, 1)) * 100)
    percent_text = task_font.render(f"{percentage}%", True, (255, 255, 255))
    percent_rect = percent_text.get_rect(center=(center_x, center_y))
    screen.blit(percent_text, percent_rect)
    
    # Present the loading screen (GPU or software path)
    if gpu_display is not None:
        try:
            gpu_display.present(screen)
        except Exception:
            pass
    else:
        pygame.display.flip()

def load_assets_with_progress(screen, clock, engine_sound_id, gpu_display=None):
    """Load all game assets with progress tracking"""
    
    # Define loading steps
    loading_steps = [
        ("Initializing audio...", "audio"),
        ("Loading car sprites...", "sprites"),
        ("Loading track data...", "track"),
        ("Initializing systems...", "systems"),
        ("Loading engine audio...", "engine_audio"),
        ("Loading shift audio...", "shift_audio"),
        ("Finalizing...", "final")
    ]
    
    total_steps = len(loading_steps)
    loaded_data = {}
    
    for step, (task_name, step_key) in enumerate(loading_steps):
        # Update loading screen
        draw_loading_screen(screen, step, total_steps, task_name, gpu_display)
        clock.tick(60)  # Maintain smooth animation
        
        # Handle pygame events to prevent "not responding"
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
        
        # Perform actual loading
        if step_key == "audio":
            loaded_data["audio_initialized"] = load_audio_system()
            time.sleep(0.1)  # Small delay to show progress
            
        elif step_key == "sprites":
            loaded_data["car_sprites_cache"] = load_all_car_sprites()
            time.sleep(0.2)
            
        elif step_key == "track":
            loaded_data["track_image"] = pygame.image.load(normalize_asset_path("track", f"map{const.MAP_NUM}", "main.png")).convert()
            loaded_data["chunk_map"] = ChunkedMap(root=normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=const.TILE_SIZE)
            time.sleep(0.1)
            
        elif step_key == "systems":
            loaded_data["path_poly"] = []  # Will be initialized later
            time.sleep(0.1)

        elif step_key == "engine_audio":
            loaded_data["engine_audio"] = load_engine_audio_system(loaded_data["audio_initialized"], engine_sound_id)
            
        elif step_key == "shift_audio":
            loaded_data["shift_sound"] = load_shift_sound_system(loaded_data["audio_initialized"])

        elif step_key == "final":
            time.sleep(0.1)
    
    # Show 100% completion briefly
    draw_loading_screen(screen, total_steps, total_steps, "Complete!", gpu_display)
    pygame.time.wait(500)
    
    return loaded_data

def load_audio_system():
    """Load audio system with fallback configurations"""
    audio_configs = [
        # High quality (try first)
        {"freq": 44100, "size": -16, "channels": 2, "buffer": 1024},
        # Medium quality (fallback 1)
        {"freq": 22050, "size": -16, "channels": 2, "buffer": 2048},
        # Low quality (fallback 2 - for very low-end devices)
        {"freq": 22050, "size": -16, "channels": 1, "buffer": 4096},
    ]
    
    audio_initialized = False
    for i, config in enumerate(audio_configs):
        try:
            pygame.mixer.pre_init(
                frequency=config["freq"],
                size=config["size"], 
                channels=config["channels"], 
                buffer=config["buffer"]
            )
            pygame.mixer.init()
            print(f"Audio initialized with config {i+1}: {config['freq']}Hz, {config['channels']}ch, buffer={config['buffer']}")
            audio_initialized = True
            break
        except Exception as e:
            print(f"Audio config {i+1} failed: {e}")
            try:
                pygame.mixer.quit()
            except:
                pass
    
    if not audio_initialized:
        print("Warning: All audio configurations failed - audio will be disabled")
    
    return audio_initialized

def load_all_car_sprites():
    """Load sprites for all car types"""
    def load_car_sprites(car_type):
        """Load sprites for a specific car type."""
        sprite_layers = get_available_sprite_layers(car_type)
        if not sprite_layers:
            # Fallback to first available car if this one has no sprites
            fallback = const.AVAILABLE_CARS[0] if const.AVAILABLE_CARS else None
            if fallback and fallback != car_type:
                sprite_layers = get_available_sprite_layers(fallback)
        
        car_sprites = []
        for path_template in sprite_layers:
            sprite_list = []
            for i in range(64):
                try:
                    img = pygame.image.load(asset_path(path_template.format(i=i))).convert_alpha()
                    sprite_list.append(img)
                except Exception as e:
                    print(f"Warning: Could not load {path_template.format(i=i)}: {e}")
                    placeholder = pygame.Surface((32, 32), pygame.SRCALPHA)
                    placeholder.fill((255, 0, 255, 128))  # Magenta placeholder
                    sprite_list.append(placeholder)
            car_sprites.append(sprite_list)
        return car_sprites
    
    # Load all car type sprites
    car_sprites_cache = {}
    for car_type in const.CAR_SPRITES.keys():
        car_sprites_cache[car_type] = load_car_sprites(car_type)
    
    return car_sprites_cache

def load_shift_sound_system(audio_initialized):
    shift_sound = None
    try:
        if audio_initialized:
            shift_sound = GearShiftSound()
            print("Shift audio system initialized")
        else:
            print("Audio system disabled due to initialization failure")
    except Exception as e:
        print("Shift audio init failed:", e)
        shift_sound = None

    return shift_sound


def load_engine_audio_system(audio_initialized, engine_sound_id):
    engine_audio = None
    try:
        if audio_initialized:
            engine_audio = V8EngineAudio(engine_sound_id=engine_sound_id)
            print(f"Engine audio system initialized for {engine_sound_id}")
        else:
            print("Audio system disabled due to initialization failure")
    except Exception as e:
        print("Engine audio init failed:", e)
        engine_audio = None

    return engine_audio


def reload_engine_audio_system(current_engine_audio, audio_initialized, engine_sound_id):
    if current_engine_audio is not None:
        try:
            current_engine_audio.stop_all()
        except Exception:
            pass
    return load_engine_audio_system(audio_initialized, engine_sound_id)


def sync_engine_audio_system(current_engine_audio, audio_initialized, current_engine_sound_id, active_car):
    next_engine_sound_id = getattr(active_car, "engine_sound_id", current_engine_sound_id)
    if next_engine_sound_id == current_engine_sound_id:
        return current_engine_audio, current_engine_sound_id
    return (
        reload_engine_audio_system(current_engine_audio, audio_initialized, next_engine_sound_id),
        next_engine_sound_id,
    )


# ─── Frame profiler ──────────────────────────────────────────────────────────
class FrameProfiler:
    """Lightweight rolling-window frame timer.

    Usage:
        profiler.begin('physics')
        ...code...
        profiler.end('physics')

    Then each frame call profiler.commit() to store the snapshot.
    draw_frame_analysis(surface, profiler) draws the overlay.
    """
    HISTORY = 120  # frames kept
    # Warm display colours per segment
    COLOURS = [
        (100, 200, 255),  # physics
        (255, 180,  60),  # render_world
        (160, 255, 120),  # camera
        (255, 100, 120),  # ui
        (200, 140, 255),  # gamemode
        (255, 220,  80),  # present
        ( 80, 200, 200),  # network
        (220, 220, 220),  # other
        ( 60,  80, 100),  # p.clear
        (255, 160,  50),  # p.world
        (120, 220, 255),  # p.ui
        (255, 255, 130),  # p.flip
    ]

    def __init__(self):
        self._t0: dict[str, float] = {}
        self._frame: dict[str, float] = {}
        self.history: deque[dict[str, float]] = deque(maxlen=self.HISTORY)
        self.labels: list[str] = []

    def begin(self, label: str):
        self._t0[label] = time.perf_counter()
        if label not in self.labels:
            self.labels.append(label)

    def end(self, label: str):
        if label in self._t0:
            self._frame[label] = self._frame.get(label, 0.0) + (time.perf_counter() - self._t0.pop(label))

    def commit(self):
        """Call once per frame after all begin/end pairs."""
        self.history.append(dict(self._frame))
        self._frame.clear()


def draw_frame_analysis(surface: pygame.Surface, profiler: 'FrameProfiler'):
    """Draw a rolling stacked-bar frame-time graph at the bottom-right."""
    if not profiler.history:
        return

    if not hasattr(draw_frame_analysis, "_font"):
        draw_frame_analysis._font = pygame.font.SysFont(None, 12)
    font = draw_frame_analysis._font

    labels  = profiler.labels
    colours = {lbl: profiler.COLOURS[i % len(profiler.COLOURS)] for i, lbl in enumerate(labels)}

    BAR_W   = 4
    GRAPH_H = 80
    LEGEND_H = len(labels) * 12 + 4
    PANEL_W  = max(160, len(profiler.history) * BAR_W + 4)
    PANEL_H  = GRAPH_H + LEGEND_H + 18   # 18 = header
    PANEL_X  = const.WINDOW_WIDTH  - PANEL_W - 6
    PANEL_Y  = const.WINDOW_HEIGHT - const.BOTTOM_LINE_Y - PANEL_H - 4

    panel = pygame.Surface((PANEL_W, PANEL_H), pygame.SRCALPHA)
    panel.fill((8, 10, 14, 200))
    pygame.draw.rect(panel, (80, 110, 160, 180), panel.get_rect(), 1)

    # Header: current total frame ms
    last = profiler.history[-1]
    total_ms = sum(last.values()) * 1000
    avg_ms   = sum(sum(f.values()) for f in profiler.history) / len(profiler.history) * 1000
    hdr = font.render(f"frame {total_ms:.1f}ms  avg {avg_ms:.1f}ms", True, (190, 210, 240))
    panel.blit(hdr, (3, 2))

    # Target line at 16.7 ms (60 fps)
    TARGET_MS = 1000 / 60
    SCALE     = GRAPH_H / max(TARGET_MS * 2, total_ms * 1.2, 1)  # px per ms
    target_py = 18 + GRAPH_H - int(TARGET_MS * SCALE)
    pygame.draw.line(panel, (120, 120, 120, 180), (2, target_py), (PANEL_W - 2, target_py))

    # Stacked bars (newest on right)
    frames = list(profiler.history)
    for fi, frame in enumerate(frames):
        bx = 2 + fi * BAR_W
        by = 18 + GRAPH_H
        for lbl in labels:
            ms  = frame.get(lbl, 0.0) * 1000
            h   = max(1, int(ms * SCALE))
            by -= h
            pygame.draw.rect(panel, colours[lbl], (bx, by, max(1, BAR_W - 1), h))

    # Legend
    ly = 18 + GRAPH_H + 4
    for lbl in labels:
        ms = last.get(lbl, 0.0) * 1000
        pygame.draw.rect(panel, colours[lbl], (3, ly + 2, 8, 8))
        txt = font.render(f"{lbl}  {ms:.1f}ms", True, (200, 210, 220))
        panel.blit(txt, (14, ly))
        ly += 12

    surface.blit(panel, (PANEL_X, PANEL_Y))


def draw_engine_audio_debug(surface, engine_audio):
    """Compact audio debug strip anchored to bottom-left."""
    if engine_audio is None or not const.DEBUG:
        return

    snapshot = engine_audio.get_debug_snapshot()
    groups = snapshot.get("groups", {})
    if not groups:
        return

    if not hasattr(draw_engine_audio_debug, "_font"):
        draw_engine_audio_debug._font = pygame.font.SysFont(None, 13)

    font = draw_engine_audio_debug._font
    rpm  = snapshot.get("rpm", 0.0)
    th   = snapshot.get("throttle", 0.0)

    row_h = 13
    bar_w = 80
    col_label = 4
    col_bar   = 90
    col_pct   = col_bar + bar_w + 3
    panel_w   = col_pct + 36

    lines = [f"SND  rpm={rpm:.0f}  th={th:.2f}"]
    group_order = [g for g in ("eng", "exh") if g in groups] or list(groups.keys())
    for gname in group_order:
        g = groups[gname]
        lines.append(f"--- {gname.upper()} vol={g.get('master_volume',0):.2f}")
        for tr in g.get("tracks", [])[:6]:
            lines.append((gname, tr))

    panel_h = len(lines) * row_h + 4
    panel_y = const.WINDOW_HEIGHT - const.BOTTOM_LINE_Y - panel_h - 4
    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel.fill((8, 10, 14, 180))
    pygame.draw.rect(panel, (80, 110, 160, 160), panel.get_rect(), 1)

    y = 2
    for line in lines:
        if isinstance(line, str):
            surf = font.render(line, True, (190, 210, 240))
            panel.blit(surf, (col_label, y))
        else:
            gname, tr = line
            vol = max(0.0, min(1.0, float(tr["volume"])))
            lbl = font.render(f"{tr['label'][:7]}", True, (180, 190, 205))
            panel.blit(lbl, (col_label, y))
            bar_rect = pygame.Rect(col_bar, y + 1, bar_w, row_h - 3)
            pygame.draw.rect(panel, (35, 40, 50), bar_rect)
            fill = max(0, int(bar_w * vol))
            if fill:
                fill_color = (100, 200, 130) if gname == "eng" else (220, 150, 80)
                pygame.draw.rect(panel, fill_color, (col_bar, y + 1, fill, row_h - 3))
            pygame.draw.rect(panel, (90, 100, 115), bar_rect, 1)
            pct = font.render(f"{vol*100:4.0f}%", True, (200, 210, 220))
            panel.blit(pct, (col_pct, y))
        y += row_h

    surface.blit(panel, (4, panel_y))


def draw_chunk_minimap(surface, renderer):
    """Top-right debug minimap: shows tire-mark chunks vs camera viewport."""
    if not const.DEBUG:
        return
    if renderer is None or not hasattr(renderer, "tire_mark_grid") or renderer.tire_mark_grid is None:
        return
    if not hasattr(draw_chunk_minimap, "_font"):
        draw_chunk_minimap._font = pygame.font.SysFont(None, 12)
    font = draw_chunk_minimap._font

    grid = renderer.tire_mark_grid
    marks = grid._marks
    if not marks:
        return

    all_keys = list(marks.keys())
    min_ix = min(k[0] for k in all_keys)
    max_ix = max(k[0] for k in all_keys)
    min_iy = min(k[1] for k in all_keys)
    max_iy = max(k[1] for k in all_keys)
    cols = max_ix - min_ix + 1
    rows = max_iy - min_iy + 1

    cell = max(4, min(14, 120 // max(cols, rows, 1)))
    map_w = cols * cell + 2
    map_h = rows * cell + 14  # 14px header
    panel_x = const.WINDOW_WIDTH - map_w - 6
    panel_y = const.TOP_LINE_Y + 6

    panel = pygame.Surface((map_w, map_h), pygame.SRCALPHA)
    panel.fill((10, 12, 18, 200))
    pygame.draw.rect(panel, (80, 110, 160, 180), panel.get_rect(), 1)

    hdr = font.render(f"chunks {len(marks)}", True, (170, 195, 230))
    panel.blit(hdr, (2, 1))

    for (ix, iy), surf in marks.items():
        cx = (ix - min_ix) * cell + 1
        cy = (iy - min_iy) * cell + 14
        # Sample alpha of centre pixel to estimate mark intensity
        try:
            px = surf.get_at((grid.tile_size // 2, grid.tile_size // 2))
            intensity = 255 - px[3]  # transparent = no marks
        except Exception:
            intensity = 128
        brightness = max(40, 255 - intensity)
        color = (brightness // 2, brightness, brightness // 2)
        pygame.draw.rect(panel, color, (cx, cy, cell - 1, cell - 1))

    surface.blit(panel, (panel_x, panel_y))

# ======= MAIN LOOP =======
  
def main():
    global I_AM_HOST  # ensure all references/assignments in this function use the module global
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["host", "join"])
    parser.add_argument("--code")
    parser.add_argument("--name")
    args, unknown = parser.parse_known_args()

    pygame.init()
    pygame.joystick.init()
    
    gpu_display = None
    use_gpu = True  # Set to True to enable GPU rendering with texture reuse
    
    if use_gpu:
        try:
            from drift.render.gpu_display import GPUDisplay
            gpu_display = GPUDisplay((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), f"Drift Race v{const.VERSION}")
            print("✓ GPU display initialized via pygame._sdl2")
            # With the SDL2 Renderer pipeline the window is owned by GPUDisplay.
            # We still need a scratch Surface for loading screens / fallback blits.
            screen = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
        except Exception as e:
            print(f"✗ GPU display initialization failed: {e}")
            print("  Using software rendering fallback")
            gpu_display = None
    
    if gpu_display is None:
        pygame.display.set_caption(f"Drift Race v{const.VERSION}")
        screen = pygame.display.set_mode((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
    
    clock = pygame.time.Clock()
    
    # Fullscreen state tracking
    is_fullscreen = False

    default_engine_sound_id = get_car_engine_sound_id(const.DEFAULT_CAR_ID)
    
    # Show loading screen and load assets
    loaded_assets = load_assets_with_progress(screen, clock, default_engine_sound_id, gpu_display)
    
    # Create fonts after pygame.init()
    font_small = pygame.font.SysFont(None, const.FONT_SMALL_SIZE)
    font_medium = pygame.font.SysFont(None, const.FONT_MEDIUM_SIZE)
    font_big = pygame.font.SysFont(None, const.FONT_BIG_SIZE)
    
    # Extract loaded assets
    audio_initialized = loaded_assets["audio_initialized"]
    car_sprites_cache = loaded_assets["car_sprites_cache"]
    track_image = loaded_assets["track_image"]
    chunked_map = loaded_assets["chunk_map"]
    engine_audio = loaded_assets["engine_audio"]
    shift_sound = loaded_assets["shift_sound"]

    stage1 = "lobby" # lobby | game | error | mode1 | mode2
    stage2 = "" # new_game | join_game | settings
    stage3 = "" # controls
    error_msg = ""
    remotes = {}
    ai_cars = []
    path_poly = []
    checkpoints = []
    game_mode = None           # active BaseGameMode instance (SimpleRace, etc.)
    _collision_mesh = []       # collision polygons from map_meta.json
    _prev_stage1 = "lobby"     # detect stage1 transitions
    _return_btn_rect = None    # leaderboard button rect from previous frame
    _local_result_sent = False

    my_name = rand_name()
    my_id = str(uuid.uuid4())[:8]
    code = None
    sock = None
    last_state_send = 0.0
    last_ping = 0.0
    host_name = None  # Will be set when hosting or joining

    lights_on = False

    spawnx = random.uniform(const.WINDOW_WIDTH*0.3, const.WINDOW_WIDTH*0.7)
    spawny = random.uniform(const.WINDOW_HEIGHT*0.3, const.WINDOW_HEIGHT*0.7)
    my_car = car.Car(spawnx, spawny, my_name, is_ai=False, car_type=const.DEFAULT_CAR_ID, car_name=const.DEFAULT_CAR_NAME)
    current_engine_sound_id = my_car.engine_sound_id
    # Set palette colors from car specs
    set_palette_colors_from_car(my_car.palette_colors)
    # Ensure palette cache is fresh and pre-warm colored sprites to avoid runtime stutter
    invalidate_palette_cache()
    try:
        # Pre-render one frame for the player's car to populate the palette cache
        temp_surf = pygame.Surface((128, 128), pygame.SRCALPHA)
        car_sprites = loaded_assets.get("car_sprites_cache", {}).get(my_car.car_type, [])
        draw_car(temp_surf, 64, 64, my_car.angle, my_car.name, car_sprites_list=car_sprites, palette_colors=get_palette_colors())
        print('aaa')
        del temp_surf
    except Exception:
        pass
    # Local player's engine state (avoid mutating Car which may use __slots__)
    engine_state = {"gear": 0, "last_rpm": None}

    # controller cooldowns
    ctlr_btn2_time = 0.0 # i'll store last time.time() the X button was pressed (change car)
    ctlr_btn3_time = 0.0 # same for the Y button (spawn ai car)

    if args.mode == "host" and args.code and args.name:
        my_name = args.name
        my_car.name = my_name
        code = args.code
        try:
            sock = connect_to_relay()
            join_pkt = {"t": "create", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
            # Wait briefly for confirmation; otherwise offline fallback
            join_ok_received = False
            timeout = time.time() + 1.0
            while time.time() < timeout:
                for msg in recv_jsons(sock):
                    if msg.get("t") == "join_ok":
                        join_ok_received = True
                        break
                    if msg.get("t") == "error":
                        raise Exception(msg.get("msg", "relay error"))
                if join_ok_received:
                    break
                time.sleep(0.02)
            if join_ok_received:
                stage1 = "game"
                I_AM_HOST = True  # set host flag for CLI host mode
            else:
                raise Exception("no join_ok")
        except Exception as e:
            print(f"Failed to connect to relay - starting in offline mode: {e!r}")
            # Offline fallback
            sock = None
            code = "Offline"
            stage1 = "game"
            I_AM_HOST = True
    elif args.mode == "join" and args.code and args.name:
        my_name = args.name
        my_car.name = my_name
        code = args.code
        try:
            sock = connect_to_relay()
            code = code.upper()
            join_pkt = {"t": "join", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
            # Wait briefly for confirmation; otherwise offline fallback
            join_ok_received = False
            timeout = time.time() + 1.0
            while time.time() < timeout:
                for msg in recv_jsons(sock):
                    if msg.get("t") == "join_ok":
                        join_ok_received = True
                        break
                    if msg.get("t") == "error":
                        raise Exception(msg.get("msg", "relay error"))
                if join_ok_received:
                    break
                time.sleep(0.02)
            if join_ok_received:
                stage1 = "game"
                I_AM_HOST = False  # set host flag for CLI join mode
            else:
                raise Exception("no join_ok")
        except Exception as e:
            print(f"Failed to connect to relay - starting in offline mode: {e!r}")
            # Offline fallback
            sock = None
            code = "Offline"
            stage1 = "game"
            I_AM_HOST = False
    
    # Renderer handles track, cars, and drift marks
    renderer = WorldRenderer(track_image, flags, chunked_map=chunked_map)

    # connect first available gamepad (if any)
    gp = Gamepad()
    gp.joystick = pygame.joystick.Joystick(0) if pygame.joystick.get_count() > 0 else None
    gp.selected_index = gp.joystick.get_id() if gp.joystick else None
    if gp.joystick: gp.connect_gamepad(gp.selected_index)

    # Create a camera object; mouse wheel will adjust zoom and middle mouse drag will pan.
    cam = camera.Camera(const.WINDOW_WIDTH, const.WINDOW_HEIGHT, zoom=1.0)
    dragging = False
    host_ref = [I_AM_HOST]

    def quit_game():
        pygame.quit()
        sys.exit(0)

    def leave_room(sock, code, my_id, remotes):
        nonlocal host_name, game_mode, _prev_stage1, _return_btn_rect, _local_result_sent
        if sock and code:
            try:
                sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                sock.close()
            except Exception:
                pass
        remotes.clear()
        ai_cars.clear()
        const.AI_PATH_FOLLOW = False
        const.CURSOR_FOLLOW = False
        host_name = None
        host_ref[0] = False
        if game_mode is not None:
            game_mode.on_exit()
            game_mode = None
        _prev_stage1 = "lobby"
        _return_btn_rect = None
        _local_result_sent = False
        invalidate_ui_text_cache('room')  # Clear cached room code text
        # Clear tire marks and chunk cache to free memory
        renderer.clear_tire_marks()
        renderer.clear_chunk_cache()
        return "lobby", "", None, None, remotes # stage, substage sock, code, remotes
    
    def handle_controls():
        nonlocal stage3
        stage3 = "controls"
        
    def switch_cursor_follow_mode(stage1):
        const.CURSOR_FOLLOW = not const.CURSOR_FOLLOW
        if const.CURSOR_FOLLOW: const.AI_PATH_FOLLOW = False
        # stage, substage sock, code, remotes
        try: return stage1, "", sock, code, remotes
        except Exception: return stage1, "", None, None, {}

    def switch_ai_path_mode(stage1):
        const.AI_PATH_FOLLOW = not const.AI_PATH_FOLLOW
        if const.AI_PATH_FOLLOW: const.CURSOR_FOLLOW = False
        # stage, substage sock, code, remotes
        try: return stage1, "", sock, code, remotes
        except Exception: return stage1, "", None, None, {}

    settings_buttons = [ # todo : be able to use '*' like '*/settings' for key binds
    btn.Button("Quit Game", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.35, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, [["lobby", "settings"]] ,lambda: quit_game()),
    btn.Button("Leave Room", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.35, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, [["game", "settings"], ["mode1", "settings"], ["mode2", "settings"], ["leaderboard", "settings"]] ,lambda: leave_room(sock, code, my_id, remotes)),
    btn.Button("Controls", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.45, const.BTN_WIDTH, const.BTN_HEIGHT, const.BLUE, [["lobby", "settings"], ["game", "settings"], ["mode1", "settings"], ["mode2", "settings"], ["leaderboard", "settings"]], handle_controls),
    btn.Button("Cursor Follow Mode", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.55, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, [["mode1", "settings"], ["mode2", "settings"]], lambda: switch_cursor_follow_mode(stage1)),
    btn.Button("AI Path Mode", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.65, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, [["mode1", "settings"], ["mode2", "settings"]], lambda: switch_ai_path_mode(stage1)),
    ]
    
    # Performance debugging
    frame_count = 0
    last_debug_time = time.time()
    profiler = FrameProfiler()
    show_frame_analysis = False

    # Reusable UI surface (avoid per-frame allocation)
    ui_surf = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), pygame.SRCALPHA)

    while True:
        dt = clock.tick(const.FPS) / 1000.0
        #dt = min(dt, 1 / const.FPS)  # Cap dt to avoid large jumps
        
        # Performance debugging - print cache sizes every 3 seconds
        frame_count += 1
        current_time = time.time()
        if current_time - last_debug_time >= 3.0:
            from drift.ui import ui_helpers
            text_cache_size = len(ui_helpers._header_footer_text_cache)
            button_cache_size = len(btn.Button._font_cache)
            chunk_cache_size = len(renderer.chunked_map._cache) if renderer and hasattr(renderer, 'chunked_map') else 0
            tire_mark_chunks = len(renderer.tire_mark_grid._marks) if renderer and hasattr(renderer, 'tire_mark_grid') else 0
            current_fps = clock.get_fps()
            # print(f"[DEBUG] FPS: {current_fps:.1f} | Text cache: {text_cache_size} | Button cache: {button_cache_size} | Chunk cache: {chunk_cache_size} | Tire marks: {tire_mark_chunks}")
            last_debug_time = current_time

        # ======== EVENT HANDLING ======== (keyboard)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                if sock and code:
                    try: sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                    except Exception: pass
                try:
                    if engine_audio:
                        engine_audio.stop_all()
                    if shift_sound:
                        shift_sound.stop_all()
                except Exception:
                    pass
                pygame.quit()
                sys.exit(0)

            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_l: # L to toggle headlights
                lights_on = not lights_on
            if ev.type == pygame.KEYDOWN and ev.key == const.CHANGE_CAR_KEY: # C to change car
                # Cycle through available car types
                available_types = list(const.CAR_SPRITES.keys())
                lower_types = [t.lower() for t in available_types]
                try:
                    current_index = available_types.index(my_car.car_type)
                except ValueError:
                    current_index = lower_types.index(my_car.car_type.lower()) if my_car.car_type.lower() in lower_types else 0
                next_index = (current_index + 1) % len(available_types)
                my_car.set_car_type(available_types[next_index])
                engine_audio, current_engine_sound_id = sync_engine_audio_system(
                    engine_audio,
                    audio_initialized,
                    current_engine_sound_id,
                    my_car,
                )
                set_palette_colors_from_car(my_car.palette_colors)
                invalidate_palette_cache()  # Recalculate colored sprites for new car type
            if ev.type == pygame.KEYDOWN and ev.key == const.RESET_KEY: # R to reset car to last checkpoint
                if stage1.startswith("mode") and my_car.last_checkpoint_coordinates is not None:
                    lx, ly, la = my_car.last_checkpoint_coordinates
                    my_car.x, my_car.y = lx, ly
                    my_car.angle = la
                    my_car.vx, my_car.vy = 0.0, 0.0
                    my_car.v_angle = 0.0
            if ev.type == pygame.KEYDOWN and ev.key == const.DEBUG_TOGGLE_KEY: # F3 to toggle debug mode
                # Toggle debug mode
                const.DEBUG = not const.DEBUG
                invalidate_ui_text_cache('debug')  # Clear cached debug text
                print(f"Debug mode {'enabled' if const.DEBUG else 'disabled'}")
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_F4:
                show_frame_analysis = not show_frame_analysis
            if ev.type == pygame.KEYDOWN and ev.key == const.FULLSCREEN_KEY:
                # Toggle fullscreen mode
                is_fullscreen = not is_fullscreen
                if is_fullscreen:
                    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                    const.WINDOW_WIDTH, const.WINDOW_HEIGHT = screen.get_size()
                    cam.zoom = 2.0
                else:
                    const.WINDOW_WIDTH, const.WINDOW_HEIGHT = const.WINDOW_WIDTH_W, const.WINDOW_HEIGHT_W
                    screen = pygame.display.set_mode((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
                    cam.zoom = 1.0
                print(f"Fullscreen mode {'enabled' if is_fullscreen else 'disabled'}")
            if ev.type == pygame.KEYDOWN and ev.key == const.AI_KEY: # N to add AI car
                _max_p = game_mode.max_players if game_mode else 6
                _total_players = 1 + len(remotes) + len(ai_cars)
                if I_AM_HOST and stage1 in ["game", "mode1", "mode2"] and stage2 == "" and _total_players < _max_p:
                    # Randomly assign car type for AI cars
                    ai_car_type = random.choice(const.AVAILABLE_CARS)
                    ai_inst = car.Car(
                        random.randint(const.TRACK_MARGIN + 200, const.WINDOW_WIDTH - const.TRACK_MARGIN - 200),
                        random.randint(const.TRACK_MARGIN + 120, const.WINDOW_HEIGHT - const.TRACK_MARGIN - 120),
                        name=f"AI-{len(ai_cars)+1}",
                        is_ai=True,
                        car_type=ai_car_type,
                    )
                    ai_cars.append(ai_inst)
                    if const.DEBUG:
                        print(f"Spawned AI car: {ai_inst.name} at ({ai_inst.x:.1f},{ai_inst.y:.1f}) type={ai_inst.car_type}")
                
            if ev.type == pygame.MOUSEWHEEL:
                # Adjust zoom (clamp between 0.5 and 3.0)
                cam.zoom *= 1.1 if ev.y > 0 else 0.9
                cam.zoom = clamp(cam.zoom, 1, 3.0)
            if ev.type == pygame.MOUSEBUTTONDOWN:
                if ev.button == 2:  # Middle mouse for panning
                    dragging = True
            if ev.type == pygame.MOUSEBUTTONUP:
                if ev.button == 2:
                    dragging = False
            if ev.type == pygame.MOUSEMOTION and dragging:
                # Adjust pan offset (divide by zoom so that panning is smooth)
                cam.offset[0] -= ev.rel[0] / cam.zoom
                cam.offset[1] -= ev.rel[1] / cam.zoom

            ev, stage1, stage2, stage3, remotes, sock, code, my_car, error_msg, host_name, track_image, chunked_map, checkpoints = handle_game_events(screen, ev, stage1, stage2, stage3, gp, remotes, ai_cars, sock, code, my_name, my_id, my_car, font_big, font_small, error_msg, host_ref, host_name, track_image=track_image, chunked_map=chunked_map, checkpoints=checkpoints)
            I_AM_HOST = host_ref[0]
            engine_audio, current_engine_sound_id = sync_engine_audio_system(
                engine_audio,
                audio_initialized,
                current_engine_sound_id,
                my_car,
            )

            # Leaderboard "Return to Lobby" button click
            if (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1
                    and stage1 == "leaderboard" and I_AM_HOST
                    and _return_btn_rect is not None
                    and _return_btn_rect.collidepoint(ev.pos)):
                # Return everyone to the waiting room
                if game_mode is not None:
                    game_mode.on_exit()
                    game_mode = None
                stage1 = "game"
                _prev_stage1 = "game"
                _return_btn_rect = None
                _local_result_sent = False
                # Teleport local player back to center
                my_car.x = const.WINDOW_WIDTH // 2
                my_car.y = const.WINDOW_HEIGHT // 2
                my_car.vx, my_car.vy = 0.0, 0.0
                # Tell remote players to return (via relay)
                if sock and code and code != "Offline":
                    try:
                        sock.send(json.dumps({
                            "t": "start_race", "code": code, "id": my_id,
                            "mode": "game"
                        }).encode("utf-8"))
                    except Exception:
                        pass

            # update map changes
            if renderer and track_image and renderer.track_image != track_image: renderer.track_image = track_image
            if renderer and chunked_map and renderer.chunked_map != chunked_map: renderer.chunked_map = chunked_map
            if renderer and checkpoints: renderer.checkpoints = checkpoints

        # ======== JOYSCTICK INPUTS HANDLING ======== (controller buttons)

        # A: button 0, B: button 1, X: button 2, Y: button 3
        # LB: button 4, RB: button 5
        # -: button 6, +: button 7
        # Left joystick: button 8 (press), Right joystick: button 9 (press)
        # Home: button 10

        if gp and gp.joystick:
            js = gp.joystick
            if js.get_button(2) and time.time() - ctlr_btn2_time > 0.2: # X to change car
                ctlr_btn2_time = time.time()
                # Cycle through available car types
                available_types = list(const.CAR_SPRITES.keys())
                current_index = available_types.index(my_car.car_type)
                next_index = (current_index + 1) % len(available_types)
                my_car.set_car_type(    available_types[next_index])
                engine_audio, current_engine_sound_id = sync_engine_audio_system(
                    engine_audio,
                    audio_initialized,
                    current_engine_sound_id,
                    my_car,
                )
                set_palette_colors_from_car(my_car.palette_colors)
                invalidate_palette_cache()  # Recalculate colored sprites for new car type
            if js.get_button(3) and time.time() - ctlr_btn3_time > 0.2: # Y to spawn ai car
                ctlr_btn3_time = time.time()
                _max_p = game_mode.max_players if game_mode else 6
                _total_players = 1 + len(remotes) + len(ai_cars)
                if I_AM_HOST and stage1 in ["game", "mode1", "mode2"] and stage2 == "" and _total_players < _max_p:
                    # Randomly assign car type for AI cars
                    ai_car_type = random.choice(const.AVAILABLE_CARS)
                    ai_inst = car.Car(
                        random.randint(const.TRACK_MARGIN + 200, const.WINDOW_WIDTH - const.TRACK_MARGIN - 200),
                        random.randint(const.TRACK_MARGIN + 120, const.WINDOW_HEIGHT - const.TRACK_MARGIN - 120),
                        name=f"AI-{len(ai_cars)+1}",
                        is_ai=True,
                        car_type=ai_car_type,
                    )
                    ai_cars.append(ai_inst)
                    if const.DEBUG:
                        print(f"Spawned AI car: {ai_inst.name} at ({ai_inst.x:.1f},{ai_inst.y:.1f}) type={ai_inst.car_type}")

        # ======== NETWORKING ========

        profiler.begin("network")
        if sock:
            # print(sock)
            net_result = handle_network_messages(sock, remotes, dt, my_id, I_AM_HOST, code)
            if net_result.get("host_name") is not None:
                host_name = net_result["host_name"] or None
            if net_result.get("host_id") is not None:
                I_AM_HOST = (net_result["host_id"] == my_id)
                host_ref[0] = I_AM_HOST
            if net_result.get("start_mode") and stage1 in ["game", "mode1", "mode2", "leaderboard"]:
                new_mode = net_result["start_mode"]

                # Race start transitions are one-way from waiting room only.
                # This avoids re-applying stale/echoed starts while already racing.
                if new_mode in ["mode1", "mode2"] and stage1 != "game":
                    new_mode = None
                if new_mode is None:
                    pass
                # "game" means return to waiting room (from leaderboard)
                elif new_mode == "game":
                    if stage1 != "game":
                        if game_mode is not None:
                            game_mode.on_exit()
                            game_mode = None
                        _prev_stage1 = "game"
                        _return_btn_rect = None
                        _local_result_sent = False
                        my_car.x = const.WINDOW_WIDTH // 2
                        my_car.y = const.WINDOW_HEIGHT // 2
                        my_car.vx, my_car.vy = 0.0, 0.0
                        renderer.clear_tire_marks()
                        stage1 = new_mode
                else:
                    stage1 = new_mode
                    renderer.clear_tire_marks()
                    # Non-host: load race track once on race start transition.
                    start_track = net_result.get("start_track")
                    if not I_AM_HOST and isinstance(start_track, str) and start_track.startswith("track"):
                        try:
                            new_map_num = int(start_track[5:])
                        except Exception:
                            new_map_num = const.MAP_NUM
                        if new_map_num != const.MAP_NUM:
                            const.MAP_NUM = new_map_num
                            track_image = pygame.image.load(normalize_asset_path("track", f"map{const.MAP_NUM}", "main.png")).convert()
                            chunked_map = ChunkedMap(root=normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=const.TILE_SIZE)
                            renderer.track_image = track_image
                            renderer.chunked_map = chunked_map
            if game_mode is not None and net_result.get("race_results"):
                game_mode.apply_network_results(net_result["race_results"])
            err = net_result.get("error")
            print(err) if err else None
            if err:
                # Switch to offline on relay errors
                try:
                    sock.close()
                except Exception:
                    print(f"Error closing socket after relay error: {err}")
                sock = None
                code = "Offline"
                remotes.clear()

        if sock and code and code != "Offline":
            now = time.time()
            if now - last_state_send >= 1.0 / const.SEND_HZ:
                last_state_send = now
                send_network_state(sock, code, my_id, my_car)
                if I_AM_HOST and ai_cars:
                    send_ai_states(sock, code, ai_cars)
            if now - last_ping >= 1.0 / const.PING_HZ:
                last_ping = now
                send_ping(sock, code)
        profiler.end("network")

        # ======== GAME MODE LIFECYCLE ========

        # Detect stage1 transitions → initialise / tear-down game modes
        if stage1 != _prev_stage1:
            # Leaving a mode
            if _prev_stage1 in ["mode1", "mode2"] and game_mode is not None:
                if stage1 != "leaderboard":  # keep mode alive for leaderboard
                    game_mode.on_exit()
                    game_mode = None

            # Entering mode1
            if stage1 == "mode1" and game_mode is None:
                _start_grid = []
                try:
                    meta_path = asset_path("track", f"map{const.MAP_NUM}", "map_meta.json")
                    with open(meta_path, "r", encoding="utf-8") as fh:
                        _meta = json.load(fh)
                    _start_grid = _meta.get("start", []) or []
                    _lines = _meta.get("lines", []) or []
                    _collision_mesh = _meta.get("collision_mesh", []) or []
                except Exception:
                    _start_grid = []
                    _lines = []
                    _collision_mesh = []

                renderer.collision_mesh = _collision_mesh

                game_mode = SimpleRace(renderer.checkpoints or [], total_laps=1, start_grid=_start_grid, lines=_lines, local_player_id=my_id) # here to change the number of laps
                _local_result_sent = False
                # Build player dict for on_enter
                _mode_players = {my_id: {"car_type": my_car.car_type, "name": my_car.name}}
                for pid, rd in remotes.items():
                    _mode_players[pid] = {"car_type": rd.get("car_type", "ae86"), "name": rd.get("name", pid)}
                for i, ai in enumerate(ai_cars, start=1):
                    _mode_players[f"AI-{i}"] = {"car_type": ai.car_type, "name": ai.name}
                game_mode.on_enter(_mode_players)
                # Teleport all players to start line
                sorted_spawn_ids = sorted(_mode_players.keys())
                start_positions = game_mode.get_start_positions(sorted_spawn_ids)
                if my_id in start_positions:
                    sx, sy, sa = start_positions[my_id]
                    my_car.x, my_car.y, my_car.angle = sx, sy, sa
                    my_car.target_angle = sa
                    my_car.vx, my_car.vy = 0.0, 0.0
                for i, ai in enumerate(ai_cars, start=1):
                    key = f"AI-{i}"
                    if key in start_positions:
                        sx, sy, sa = start_positions[key]
                        ai.x, ai.y, ai.angle = sx, sy, sa
                        ai.target_angle = sa
                        ai.vx, ai.vy = 0.0, 0.0

            # Leaving leaderboard (return to lobby/game)
            if _prev_stage1 == "leaderboard" and game_mode is not None:
                game_mode.on_exit()
                game_mode = None

            _prev_stage1 = stage1

        # Update active game mode
        mode_result = {}
        if game_mode is not None and stage1 in ["mode1", "mode2", "leaderboard"]:
            # Build a players dict that includes both network remotes and AI cars
            _mode_players_update = dict(remotes)
            for i, ai in enumerate(ai_cars, start=1):
                _mode_players_update[f"AI-{i}"] = ai
            mode_result = game_mode.update(dt, _mode_players_update, my_car, I_AM_HOST)
            local_finish_time = game_mode.get_local_finish_time()
            if (local_finish_time is not None and not _local_result_sent and sock and code and code != "Offline"):
                try:
                    sock.send(json.dumps({
                        "t": "race_result",
                        "code": code,
                        "id": my_id,
                        "time": float(local_finish_time),
                    }).encode("utf-8"))
                    _local_result_sent = True
                except Exception:
                    pass
            # Handle stage transition request (e.g. racing → leaderboard)
            if mode_result.get("stage_transition") == "leaderboard":
                stage1 = "leaderboard"
                _prev_stage1 = "leaderboard"

        # ======== FRAME UPDATE ========
        
        world_size = renderer.get_world_size(stage1 if stage1 != "leaderboard" else "mode1")

        # Skip physics computations when in menus (new_game, join_game, controls)
        # This saves CPU on low-end devices and improves battery life
        skip_physics = stage2 in ["new_game", "join_game"] or stage3 == "controls"

        profiler.begin("physics")
        if not skip_physics:
            movement_locked = bool(mode_result.get("movement_locked"))
            # Prepare remotes view for the player: include network remotes + AI cars (so player can collide with AIs)
            remotes_with_ai_for_player = dict(remotes)
            if I_AM_HOST:
                for i, ai in enumerate(ai_cars, start=1):
                    key = f"AI-{i}"
                    remotes_with_ai_for_player[key] = {"x": ai.x, "y": ai.y, "a": ai.angle, "vx": ai.vx, "vy": ai.vy, "drift_ratio": ai.drift_ratio, "name": ai.name}
                    
            # Update player car using remotes that include AIs
            # If AI path mode is enabled and a path is available, let the AI drive the player
            controls = None
            if const.AI_PATH_FOLLOW and path_poly:
                try:
                    controls, ai_debug_surface = ai_algorithme(path_poly, my_car, ai_path_mode=True, surface=pygame.Surface((track_image.get_width(), track_image.get_height()), pygame.SRCALPHA), font_small=font_small)
                except Exception:
                    controls = None
            if controls is None:
                controls = read_inputs(gp, my_car, cam, const.CURSOR_FOLLOW, const.AI_PATH_FOLLOW)
            # Lock movement during countdown/cooldown/leaderboard
            if movement_locked:
                controls = {"th": 0.0, "st": 0.0, "br": 0.0}
                my_car.vx, my_car.vy = 0.0, 0.0
                my_car.v_angle = 0.0
            else:
                my_car.step(controls, dt, remotes_with_ai_for_player, world_size, compute_debug=const.DEBUG, cursor_follow=const.CURSOR_FOLLOW, cam=cam, collision_mesh=_collision_mesh)
#                 my_car.step(controls, dt, remotes_with_ai_for_player, world_size, compute_debug=const.DEBUG, cursor_follow=const.CURSOR_FOLLOW, cam=cam)
            # Update engine audio based on RPM and throttle with enhanced drift characteristics
            try:
                if audio_initialized and (engine_audio is not None or shift_sound is not None):
                    speed_units = math.hypot(my_car.vx, my_car.vy)
                    th = clamp(controls.get("th", 0.0), -1.0, 1.0)
                    prev_rpm = engine_state.get("last_rpm")
                    rpm = calc_engine_rpm(
                        speed_units=speed_units,
                        drift_ratio=my_car.drift_ratio,
                        throttle=th,
                        prev_rpm=prev_rpm,
                        dt=dt,
                        params=my_car.rpm_params,
                        _state=engine_state,
                    )
                    engine_state["last_rpm"] = rpm
                    if engine_audio is not None:
                        engine_audio.update(rpm=rpm, throttle=abs(th))
                    current_gear = engine_state.get("gear", 0)
                    if shift_sound is not None:
                        shift_sound.update(
                            current_gear=current_gear,
                            rpm=rpm,
                            throttle=abs(th),
                            drift_ratio=my_car.drift_ratio,
                            engine_sound_id=getattr(my_car, "engine_sound_id", ""),
                        )
            except Exception:
                # Silently handle audio errors to prevent crashes on low-end devices
                pass

            # Prepare remotes view for AIs: include network remotes + all AIs + the local player (so AIs can detect collisions with player)
            remotes_with_ai_for_ais = dict(remotes)
            
            if I_AM_HOST:
                # add local player under a distinct key so AIs see it
                remotes_with_ai_for_ais[f"PLAYER-{my_id}"] = {"x": my_car.x, "y": my_car.y, "a": my_car.angle, "vx": my_car.vx, "vy": my_car.vy, "drift_ratio": my_car.drift_ratio, "name": my_car.name}
                for i, ai in enumerate(ai_cars, start=1):
                    key = f"AI-{i}"
                    remotes_with_ai_for_ais[key] = {"x": ai.x, "y": ai.y, "a": ai.angle, "vx": ai.vx, "vy": ai.vy, "drift_ratio": ai.drift_ratio, "name": ai.name}
                
            # Step AIs (each AI sees other AIs + network remotes + the player)
            if I_AM_HOST:
                for ai in ai_cars:
                    if movement_locked:
                        ai.vx, ai.vy = 0.0, 0.0
                        ai.v_angle = 0.0
                    else:
                        # Compute controls via AI algorithm and log when debugging
                        try:
                            controls = ai_algorithme(path_poly, ai)
                        except Exception:
                            controls = {"th": 0.0, "st": 0.0, "br": 0.0}
                        if const.DEBUG:
                            print(f"AI update {ai.name}: pos=({ai.x:.1f},{ai.y:.1f}) vx={ai.vx:.1f} vy={ai.vy:.1f} -> controls={controls}")
                        ai.step(controls, dt, remotes_with_ai_for_ais, world_size, compute_debug=const.DEBUG, collision_mesh=_collision_mesh)
            cam.update(my_car, world_size)
            profiler.end("physics")
        else:
            profiler.begin("physics")
            profiler.end("physics")
            # In menus: set default controls to prevent undefined variable errors
            controls = {"th": 0.0, "st": 0.0, "br": 0.0}

        # ======== RENDERING ========

        profiler.begin("render_world")
        if not skip_physics:
            # draw track, drift marks and cars (online & local)
            render_stage = stage1 if stage1 != "leaderboard" else "mode1"
            world_surf, resized, is_viewport = renderer.render_world(cam, render_stage, my_car, ai_cars, remotes, lights_on, car_sprites_cache)
            if resized and not is_viewport:
                path_poly = path_finder.discover_track(normalize_asset_path("track", f"map{const.MAP_NUM}", "main.png"))

            # draw camera view — let GPU handle upscaling when available
            if gpu_display is not None:
                if is_viewport: final_surf = world_surf            # chunk mode: GPU scales
                else: final_surf = cam.apply_no_scale(world_surf) # classic: GPU scales
            else:
                if is_viewport: final_surf = pygame.transform.scale(world_surf, (const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
                else: final_surf = cam.apply(world_surf)
        else:
            # blank world surface for lobby, settings, key binds
            world_surf = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
            world_surf.fill(const.GREY_20)
            final_surf = world_surf
        profiler.end("render_world")

        # draw ui
        profiler.begin("ui")
        ui_surf.fill((0, 0, 0, 0))
        fps = clock.get_fps()
        ui_checkpoints = renderer.checkpoints
        if game_mode is not None and stage1 in ["mode1", "leaderboard"]:
            # mode1 draws only the next checkpoint via SimpleRace.draw_checkpoints
            ui_checkpoints = []
        world_surf, button_results, new_game_rects, join_game_rects, palette_picker_rects = draw_stage_ui(
            ui_surf, stage1 if stage1 != "leaderboard" else "mode1",
            stage2, stage3, code, world_surf, world_size, ui_checkpoints,
            settings_buttons, error_msg, my_car, cam, gp, font_big, font_medium, font_small,
            controls, engine_state, fps, dt, I_AM_HOST, host_name, car_sprites_cache
        )
        draw_engine_audio_debug(ui_surf, engine_audio)
        draw_chunk_minimap(ui_surf, renderer)
        profiler.end("ui")

        # Game mode overlays (countdown, lap counter, leaderboard)
        profiler.begin("gamemode")
        _return_btn_rect = None
        if game_mode is not None:
            if stage1 == "leaderboard":
                lb_result = game_mode.draw_leaderboard(ui_surf, font_big, font_medium, font_small, I_AM_HOST)
                _return_btn_rect = lb_result.get("return_btn_rect")
            elif stage1 in ["mode1", "mode2"]:
                game_mode.draw_hud(ui_surf, cam, font_big, font_medium, font_small)
        profiler.end("gamemode")

        # Frame analysis overlay (F4)
        if show_frame_analysis:
            draw_frame_analysis(ui_surf, profiler)

        # Handle button results from settings menu
        for res in button_results:
            if isinstance(res, tuple) and len(res) == 5:
                new_stage, new_substage, new_sock, new_code, new_remotes = res
                stage1 = new_stage
                stage2 = new_substage
                sock = new_sock
                code = new_code
                remotes = new_remotes

        # AI path debug overlay — blit onto ui_surf before present
        if const.AI_PATH_FOLLOW and stage1 == "game":
            try:
                top_right_pos = cam.x-(const.WINDOW_WIDTH/2)/cam.zoom, cam.y-(const.WINDOW_HEIGHT/2)/cam.zoom
                camera_rect = pygame.Rect(top_right_pos[0],
                                        top_right_pos[1],
                                        const.WINDOW_WIDTH/cam.zoom,
                                        const.WINDOW_HEIGHT/cam.zoom)
                visible_ai_debug_surface = ai_debug_surface.subsurface(camera_rect)
                ui_surf.blit(visible_ai_debug_surface, (0, 0))
            except Exception: pass

        if gpu_display is not None:
            try:
                profiler.begin("present")
                gpu_display.present(final_surf, ui_surf, profiler=profiler)
                profiler.end("present")
            except Exception as _gpu_err:
                print(f"gpu present failed: {_gpu_err}")
                profiler.end("present")
        else:
            screen.blit(final_surf, (0,0))
            screen.blit(ui_surf, (0,0))
            profiler.begin("present")
            pygame.display.flip()
            profiler.end("present")
        profiler.commit()

if __name__ == "__main__":
    main()
