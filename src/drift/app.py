#!/usr/bin/env python3

# ======= IMPORTS =======

# global imports
import pygame, json, time, random, sys, math, uuid, argparse, os
from collections import deque
# local imports
from drift.tools.paths import asset_path, chdir_to_exe_folder_if_frozen, normalize_asset_path, get_available_sprite_layers, get_track_base_image_path
import drift.config.const as const
from drift.config.settings import audio_volumes, physics_controls
from drift.config.store_data import SaveManager
import drift.render.camera as camera
from drift.render.renderer import WorldRenderer
from drift.render.map_chunks import ChunkedMap, ensure_all_maps_sliced
from drift.core.car import get_car_engine_sound_id, CollisionMesh, Car
from drift.core.helpers import clamp, rand_name
from drift.core.path_utils import is_path_closed
from drift.core.tutorial_controller import TutorialController, load_tutorial_steps_for_map
from drift.ai.ai import ai_algorithme
from drift.core.inputs import read_inputs
from drift.core.rpm import calc_engine_rpm
from drift.core.gamepad import Gamepad
import drift.ui.button as btn
from drift.ui.ui import handle_game_events, draw_stage_ui, draw_scoreboard, invalidate_ui_text_cache, invalidate_palette_cache, draw_car, poll_pending_connection
from drift.ui.draw_stage import set_palette_colors_from_car, get_palette_colors, get_game_options, get_game_setup, set_game_option
from drift.ai.ai import ai_algorithme
import drift.ai.path_finder as path_finder
from drift.gamemodes.classicrace import ClassicRace
from drift.gamemodes.bestlap import BestLap
from drift.net.communication import connect_to_relay, handle_network_messages, send_network_state, send_ai_states, send_ping, advance_remotes, send_stop_race
from drift.audio.engine_audio import V8EngineAudio
from drift.audio.gear_shift_sound import GearShiftSound

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
    title_text = title_font.render(f"drift_race_v{const.VERSION}", True, (255, 255, 255))
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
            ensure_all_maps_sliced()  # Slice all map chunks once at startup
            loaded_data["track_image"] = pygame.image.load(get_track_base_image_path(f"map{const.MAP_NUM}")).convert()
            loaded_data["chunk_map"] = ChunkedMap(root=normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=const.TILE_SIZE)
            _bg_root = normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks_bg")
            loaded_data["chunk_map_bg"] = ChunkedMap(root=_bg_root, tile_size=const.TILE_SIZE) if os.path.isdir(_bg_root) else None
            _fg_root = normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks_fg")
            loaded_data["chunk_map_fg"] = ChunkedMap(root=_fg_root, tile_size=const.TILE_SIZE, use_alpha=True) if os.path.isdir(_fg_root) else None
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
        draw_frame_analysis._panel = None
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

    cached = draw_frame_analysis._panel
    if cached is None or cached.get_size() != (PANEL_W, PANEL_H):
        cached = pygame.Surface((PANEL_W, PANEL_H), pygame.SRCALPHA)
        draw_frame_analysis._panel = cached
    panel = cached
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
        draw_engine_audio_debug._panel = None
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
        lines.append(f"--- {gname.upper()} vol={g.get('master',0):.2f}")
        for tr in g.get("tracks", [])[:6]:
            lines.append((gname, tr))

    panel_h = len(lines) * row_h + 4
    panel_y = const.WINDOW_HEIGHT - const.BOTTOM_LINE_Y - panel_h - 4
    cached = draw_engine_audio_debug._panel
    if cached is None or cached.get_size() != (panel_w, panel_h):
        cached = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        draw_engine_audio_debug._panel = cached
    panel = cached
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

def draw_minimap(surface, path_poly, world_size, my_car, remotes, ai_cars, stage1):
    """Bottom-left minimap: shows track path and car positions during gameplay."""
    if not path_poly or stage1 not in ("game", "mode1", "mode2", "mode_tutorial", "leaderboard"):
        return
    if world_size is None or world_size[0] <= 0 or world_size[1] <= 0:
        return

    MAP_W, MAP_H = 160, 130
    PAD = 8

    ww, wh = world_size
    scale = min(MAP_W / ww, MAP_H / wh)
    off_x = (MAP_W - ww * scale) / 2
    off_y = (MAP_H - wh * scale) / 2

    panel_x = 6
    panel_y = const.WINDOW_HEIGHT - const.BOTTOM_LINE_Y - MAP_H - PAD * 2 - 4

    # Reuse fixed-size panel surface
    if draw_minimap._panel is None:
        draw_minimap._panel = pygame.Surface((MAP_W + PAD * 2, MAP_H + PAD * 2), pygame.SRCALPHA)
        draw_minimap._panel.set_alpha(200)
    panel = draw_minimap._panel

    def to_mini(wx, wy):
        return (PAD + off_x + wx * scale, PAD + off_y + wy * scale)

    # Rebuild static track layer only when path_poly changes
    poly_closed = is_path_closed(path_poly)
    poly_key = (id(path_poly), len(path_poly), world_size, poly_closed)
    if draw_minimap._track_surf is None or draw_minimap._track_key != poly_key:
        track_surf = pygame.Surface((MAP_W + PAD * 2, MAP_H + PAD * 2))
        track_surf.fill((8, 10, 16))
        pygame.draw.rect(track_surf, (80, 110, 160, 180), track_surf.get_rect(), 1)
        if len(path_poly) >= 2:
            n = len(path_poly)
            # Build perpendicular unit vectors for each point using its neighbours
            perps = []
            for i in range(n):
                ax, ay, _ = path_poly[i]
                if poly_closed:
                    nb = (i + 1) % n
                else:
                    nb = min(i + 1, n - 1)
                bx, by, _ = path_poly[nb]
                dx, dy = bx - ax, by - ay
                seg_len = math.hypot(dx, dy)
                if seg_len < 1e-4:
                    if not poly_closed and i > 0:
                        perps.append(perps[-1])
                    else:
                        perps.append((0.0, 0.0))
                else:
                    perps.append((-dy / seg_len, dx / seg_len))

            if not poly_closed and len(perps) >= 2:
                # Keep stable end caps for open paths.
                perps[0] = perps[1]
                perps[-1] = perps[-2]

            outer = []
            inner = []
            for i in range(n):
                mx2, my2 = to_mini(path_poly[i][0], path_poly[i][1])
                hw = max(1.0, path_poly[i][2] * scale / 2)
                px_u, py_u = perps[i]
                outer.append((int(mx2 + px_u * hw), int(my2 + py_u * hw)))
                inner.append((int(mx2 - px_u * hw), int(my2 - py_u * hw)))

            # Fill road area: open paths are end-capped by reversed inner edge.
            road_poly = outer + inner[::-1]
            pygame.draw.polygon(track_surf, (40, 55, 85), road_poly)
            pygame.draw.lines(track_surf, (60, 80, 110), poly_closed, outer, 1)
            pygame.draw.lines(track_surf, (60, 80, 110), poly_closed, inner, 1)

        draw_minimap._track_surf = track_surf
        draw_minimap._track_key = poly_key
    
    panel.blit(draw_minimap._track_surf, (0, 0))

    # Remote/AI cars
    for rd in remotes.values():
        rx, ry = to_mini(rd.get("x", 0), rd.get("y", 0))
        pygame.draw.circle(panel, (255, 160, 80), (int(rx), int(ry)), 3)
    for ai in ai_cars:
        ax, ay = to_mini(ai.x, ai.y)
        pygame.draw.circle(panel, (80, 220, 120), (int(ax), int(ay)), 3)

    # Player (drawn last so it's on top)
    mx, my = to_mini(my_car.x, my_car.y)
    pygame.draw.circle(panel, (200, 230, 255), (int(mx), int(my)), 3)

    surface.blit(panel, (panel_x, panel_y))

draw_minimap._panel = None
draw_minimap._track_surf = None
draw_minimap._track_key = None

def draw_tutorial_overlay(surface, font_small, frame_state):
    if frame_state is None or not getattr(frame_state, "active", False):
        return

    msg = str(getattr(frame_state, "prompt", "")).strip()
    if not msg:
        return

    raw_lines = [ln.strip() for ln in msg.splitlines() if ln.strip()]
    hint_name = str(getattr(frame_state, "hint_image", "") or "").strip()

    # Cache keyboard hint images by resolved path to avoid reloading each frame.
    if not hasattr(draw_tutorial_overlay, "_hint_cache"):
        draw_tutorial_overlay._hint_cache = {}

    hint_surface = None
    if hint_name:
        hint_path = str(asset_path("track", f"map{const.MAP_NUM}", hint_name))
        if hint_path not in draw_tutorial_overlay._hint_cache:
            try:
                draw_tutorial_overlay._hint_cache[hint_path] = pygame.image.load(hint_path).convert_alpha()
            except Exception:
                draw_tutorial_overlay._hint_cache[hint_path] = None
        hint_surface = draw_tutorial_overlay._hint_cache.get(hint_path)

    panel_w = 420
    if hint_surface is not None:
        panel_w = 540
    text_max_w = panel_w - 28

    def _wrap_line(text: str) -> list[str]:
        words = text.split()
        if not words:
            return []
        out = []
        cur = words[0]
        for w in words[1:]:
            candidate = f"{cur} {w}"
            if font_small.size(candidate)[0] <= text_max_w:
                cur = candidate
            else:
                out.append(cur)
                cur = w
        out.append(cur)
        return out

    prompt_lines = []
    for ln in raw_lines:
        prompt_lines.extend(_wrap_line(ln))
    if not prompt_lines:
        return

    progress = float(getattr(frame_state, "progress", 0.0))
    progress = max(0.0, min(1.0, progress))

    hint_draw = None
    if hint_surface is not None:
        # Roughly 2x the previous hint size.
        target_w = 184
        target_h = 128
        iw, ih = hint_surface.get_width(), hint_surface.get_height()
        if iw > 0 and ih > 0:
            scale = min(target_w / iw, target_h / ih)
            sw = max(1, int(iw * scale))
            sh = max(1, int(ih * scale))
            hint_draw = pygame.transform.smoothscale(hint_surface, (sw, sh))

    text_block_h = max(1, len(prompt_lines)) * 18
    hint_block_h = (hint_draw.get_height() + 10) if hint_draw is not None else 0
    panel_h = 62 + text_block_h + hint_block_h + 16
    x = const.WINDOW_WIDTH // 2 - panel_w // 2
    y = const.TOP_LINE_Y + 16

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel.fill((10, 10, 16, 215))
    pygame.draw.rect(panel, (180, 180, 220), panel.get_rect(), 1)

    title = font_small.render("TUTORIAL", True, (200, 230, 255))
    panel.blit(title, (14, 10))

    py = 34
    for line in prompt_lines:
        prompt = font_small.render(line, True, (245, 245, 255))
        panel.blit(prompt, (14, py))
        py += 18

    if hint_draw is not None:
        hx = (panel_w - hint_draw.get_width()) // 2
        hy = py + 8
        panel.blit(hint_draw, (hx, hy))

    bar_x, bar_y, bar_w, bar_h = 14, panel_h - 18, panel_w - 28, 8
    pygame.draw.rect(panel, (35, 40, 52), (bar_x, bar_y, bar_w, bar_h))
    fill_w = int(bar_w * progress)
    if fill_w > 0:
        pygame.draw.rect(panel, (90, 220, 140), (bar_x, bar_y, fill_w, bar_h))
    pygame.draw.rect(panel, (110, 130, 165), (bar_x, bar_y, bar_w, bar_h), 1)

    surface.blit(panel, (x, y))

def _tutorial_bootstrap_ai_controls(my_car, tutorial_ctrl):
    """Fallback AI while path discovery is pending in tutorial mode."""
    controls = {"th": 1.0, "st": 0.0, "br": 0.0}
    if tutorial_ctrl is None or not getattr(tutorial_ctrl, "has_steps", False):
        return controls

    try:
        step = tutorial_ctrl.steps[tutorial_ctrl.step_index]
        if hasattr(step, "target_point"):
            tx, ty = step.target_point
        elif hasattr(step, "zone"):
            tx, ty = step.zone.centerx, step.zone.centery
        else:
            tx, ty = my_car.x, my_car.y
        dx = tx - my_car.x
        dy = ty - my_car.y
        angle_to_target = math.atan2(dy, dx)
        angle_diff = ((angle_to_target - my_car.angle + math.pi) % (2.0 * math.pi)) - math.pi

        # Match the regular AI style: set target heading directly.
        my_car.target_angle = angle_to_target

        # If heavily misaligned, avoid full straight throttle into the wrong heading.
        if abs(angle_diff) > 2.2:
            controls["th"] = 0.55
    except Exception:
        pass

    return controls

def draw_chunk_minimap(surface, renderer):
    """Top-right debug minimap: shows tire-mark chunks vs camera viewport."""
    if not const.DEBUG:
        return
    if renderer is None or not hasattr(renderer, "tire_mark_grid") or renderer.tire_mark_grid is None:
        return
    if not hasattr(draw_chunk_minimap, "_font"):
        draw_chunk_minimap._font = pygame.font.SysFont(None, 12)
        draw_chunk_minimap._panel = None
        draw_chunk_minimap._panel_size = None
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

    if draw_chunk_minimap._panel is None or draw_chunk_minimap._panel_size != (map_w, map_h):
        draw_chunk_minimap._panel = pygame.Surface((map_w, map_h), pygame.SRCALPHA)
        draw_chunk_minimap._panel_size = (map_w, map_h)
    panel = draw_chunk_minimap._panel
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

    # ----- Load data -----
    save_manager = SaveManager()
    save_manager.apply_settings(audio_volumes, physics_controls)
    # ----- Load data -----
    
    gpu_display = None
    use_gpu = True  # Set to True to enable GPU rendering with texture reuse
    
    if use_gpu:
        try:
            from drift.render.gpu_display import GPUDisplay
            gpu_display = GPUDisplay((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), f"drift_race_v{const.VERSION}")
            print("GPU display initialized via pygame._sdl2")
            # With the SDL2 Renderer pipeline the window is owned by GPUDisplay.
            # We still need a scratch Surface for loading screens / fallback blits.
            screen = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
        except Exception as e:
            print(f"GPU display initialization failed: {e}")
            print("  Using software rendering fallback")
            gpu_display = None
    
    if gpu_display is None:
        pygame.display.set_caption(f"drift_race_v{const.VERSION}")
        screen = pygame.display.set_mode((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
    
    clock = pygame.time.Clock()
    
    # Fullscreen state tracking
    is_fullscreen = False

    default_engine_sound_id = get_car_engine_sound_id(const.CAR_ID)
    
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
    chunked_map_bg = loaded_assets.get("chunk_map_bg")
    chunked_map_fg = loaded_assets.get("chunk_map_fg")
    engine_audio = loaded_assets["engine_audio"]
    shift_sound = loaded_assets["shift_sound"]

    stage1 = "menu" # menu | lobby | error | mode1 | mode2 | mode_tutorial
    stage2 = "" # settings
    stage3 = "" # controls | audio | modes
    error_msg = ""
    remotes = {}
    ai_cars = []
    path_poly = []
    checkpoints = []
    game_mode = None           # active BaseGameMode instance (ClassicRace, etc.)
    _collision_mesh = CollisionMesh([])  # collision polygons from map_meta.json (with spatial hash)
    _path_future = None        # Future for async track discovery
    _path_future_map_num = None
    _path_poly_map_num = None  # MAP_NUM for the currently valid path_poly

    _ai_debug_surf = None      # Cached surface for AI path debug overlay
    _skip_surf = None          # Cached surface for skip-physics (menu) background
    _prev_stage1 = "menu"     # detect stage1 transitions

    _return_btn_rect = None    # leaderboard button rect from previous frame
    _local_result_sent = False
    _ai_results_sent = {}
    _start_roster = None       # authoritative player/AI roster from relay at race start
    tutorial_ctrl = None
    tutorial_frame_state = None
    tutorial_end_zone = None
    tutorial_variant = 1
    time_scale = 1.0
    rewind_history = deque(maxlen=max(600, int(const.FPS * (const.TUTORIAL_REWIND_SECONDS + 1.5))))
    last_rewind_at = -9999.0
    rewind_playback = []
    rewind_playback_idx = 0
    rewind_playback_active = False
    rewind_playback_rate = 1.4

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
    my_car = Car(spawnx, spawny, my_name, is_ai=False)
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
        del temp_surf
    except Exception:
        pass
    # Local player's engine state (avoid mutating Car which may use __slots__)
    engine_state = {"gear": 0, "last_rpm": None}

    def _start_path_discovery_for_current_map():
        """Launch async polygon discovery for the currently selected map."""
        nonlocal _path_future, _path_future_map_num, _path_poly_map_num, path_poly
        if _path_future is not None and _path_future_map_num == const.MAP_NUM:
            return
        _disc_start_pos, _disc_start_angle = (220, 1700), 90
        try:
            import json as _json
            with open(asset_path("track", f"map{const.MAP_NUM}", "map_meta.json"), "r", encoding="utf-8") as _mf:
                _meta_disc = _json.load(_mf)
            _starts = _meta_disc.get("start", []) or []
            if _starts:
                _disc_start_pos = (
                    sum(s["x"] for s in _starts) / len(_starts),
                    sum(s["y"] for s in _starts) / len(_starts),
                )
                _disc_start_angle = math.degrees(sum(s["a"] for s in _starts) / len(_starts))
        except Exception:
            pass

        _path_future_map_num = const.MAP_NUM
        _path_poly_map_num = None
        path_poly = []
        _path_future = path_finder.discover_track_async(
            path_finder.get_pathfinder_image_path(f"map{const.MAP_NUM}"),
            start_pos=_disc_start_pos, start_angle=_disc_start_angle,
        )

    def _tutorial_profile_flags():
        """Return (allow_ai_takeover_between_qte, enable_qte, enable_rewind)."""
        # New 3-tier sequence (old level 2 removed):
        # 01 old 01 (all assists)
        # 02 old 03 (no QTE)
        # 03 old 04 (no rewind)
        allow_ai_takeover = tutorial_variant <= 1
        enable_qte = tutorial_variant <= 1
        enable_rewind = tutorial_variant <= 2
        return allow_ai_takeover, enable_qte, enable_rewind

    def _tutorial_intro_text():
        if tutorial_variant == 1:
            return "01 - Let's learn how to drift. Follow the prompts and everything should go well"
        if tutorial_variant == 2:
            return "02 - Perfect, Try finishing the map without any prompts"
        return "03 - Now without crashing"

    def _load_chunked_tutorial_fg(map_num: int, variant: int):
        """Return a variant FG ChunkedMap for tutorial map when available, else default FG."""
        map_key = f"map{map_num}"
        default_fg_root = normalize_asset_path("track", map_key, "chunks_fg")
        default_fg = ChunkedMap(root=default_fg_root, tile_size=const.TILE_SIZE, use_alpha=True) if os.path.isdir(default_fg_root) else None

        # Logical tutorial tier -> source FG variant file.
        fg_source_variant = {1: 1, 2: 2, 3: 3}.get(int(variant), int(variant))
        fg_variant_name = f"main_fg_{int(fg_source_variant):02d}.png"
        fg_variant_path = asset_path("track", map_key, fg_variant_name)
        if not os.path.exists(fg_variant_path):
            return default_fg

        fg_variant_chunks = normalize_asset_path("track", map_key, f"chunks_fg_{int(fg_source_variant):02d}")
        try:
            # Slice once per variant into a dedicated folder.
            from drift.tools.slice_map import slice_map
            slice_map(
                input_path=fg_variant_path,
                outdir=fg_variant_chunks,
                tile=const.TILE_SIZE,
                indexing="zero",
                prefix="",
                pad_color=(0, 0, 0, 0),
                force=False,
            )
        except Exception:
            return default_fg

        if os.path.isdir(fg_variant_chunks):
            return ChunkedMap(root=fg_variant_chunks, tile_size=const.TILE_SIZE, use_alpha=True)
        return default_fg

    def _init_tutorial_runtime(reset_variant=False):
        nonlocal tutorial_ctrl, tutorial_frame_state, tutorial_end_zone, tutorial_variant
        nonlocal time_scale, rewind_history, rewind_playback, rewind_playback_idx, rewind_playback_active
        nonlocal _collision_mesh, chunked_map_fg

        if reset_variant:
            tutorial_variant = 1

        _meta = {}
        _collision_mesh = CollisionMesh([])
        tutorial_end_zone = None
        try:
            meta_path = asset_path("track", f"map{const.MAP_NUM}", "map_meta.json")
            with open(meta_path, "r", encoding="utf-8") as fh:
                _meta = json.load(fh)
            _raw_mesh = _meta.get("collision_mesh", []) or []
            _collision_mesh = CollisionMesh(_raw_mesh) if _raw_mesh else CollisionMesh([])
            _tuto = _meta.get("tutorial") if isinstance(_meta, dict) else None
            _raw_end_zone = _tuto.get("end_zone") if isinstance(_tuto, dict) else None
            if isinstance(_raw_end_zone, dict):
                tutorial_end_zone = pygame.Rect(
                    int(_raw_end_zone.get("x", 0)),
                    int(_raw_end_zone.get("y", 0)),
                    max(1, int(_raw_end_zone.get("width", 1))),
                    max(1, int(_raw_end_zone.get("height", 1))),
                )
        except Exception:
            pass

        renderer.collision_mesh = _collision_mesh
        tutorial_steps = load_tutorial_steps_for_map(const.MAP_NUM)
        allow_ai_takeover, enable_qte, _ = _tutorial_profile_flags()
        tutorial_ctrl = TutorialController(
            tutorial_steps,
            allow_ai_takeover_between_qte=allow_ai_takeover,
            enable_qte=enable_qte,
            start_qte_intro_text=_tutorial_intro_text(),
            auto_fill_actions=False,
        )

        # Tutorial mode should spawn from the map's explicit start list.
        try:
            _starts = _meta.get("start", []) or []
            if _starts:
                _sp = _starts[0]
                sx = float(_sp.get("x", my_car.x))
                sy = float(_sp.get("y", my_car.y))
                sa = float(_sp.get("a", my_car.angle))
                my_car.x, my_car.y, my_car.angle = sx, sy, sa
                my_car.target_angle = sa
                my_car.vx, my_car.vy = 0.0, 0.0
                my_car.v_angle = 0.0
        except Exception:
            pass

        tutorial_frame_state = None
        time_scale = 1.0
        rewind_history.clear()
        rewind_playback = []
        rewind_playback_idx = 0
        rewind_playback_active = False

        # Keep tutorial visuals in sync with assist tier (01..04 foreground variants).
        chunked_map_fg = _load_chunked_tutorial_fg(const.MAP_NUM, tutorial_variant)
        renderer.chunked_map_fg = chunked_map_fg

    # controller cooldowns
    ctlr_btn2_time = 0.0 # i'll store last time.time() the X button was pressed (change car)
    ctlr_btn3_time = 0.0 # same for the Y button (spawn ai car)

    # CLI connection state (non-blocking; polled each frame before main loop)
    _cli_conn = None

    if args.mode == "host" and args.code and args.name:
        my_name = args.name
        my_car.name = my_name
        code = args.code
        try:
            _cli_sock = connect_to_relay()
            join_pkt = {"t": "create", "code": code, "name": my_name, "id": my_id}
            _cli_sock.send(json.dumps(join_pkt).encode("utf-8"))
            _cli_conn = {
                "status": "pending", "sock": _cli_sock, "code": code,
                "my_name": my_name, "my_id": my_id, "is_host": True,
                "host_name": my_name, "deadline": time.time() + 1.0, "mode": "host",
            }
        except Exception as e:
            print(f"Failed to connect to relay - starting in offline mode: {e!r}")
            sock = None; code = "Offline"; stage1 = "lobby"; I_AM_HOST = True
    elif args.mode == "join" and args.code and args.name:
        my_name = args.name
        my_car.name = my_name
        code = args.code.upper()
        try:
            _cli_sock = connect_to_relay()
            join_pkt = {"t": "join", "code": code, "name": my_name, "id": my_id}
            _cli_sock.send(json.dumps(join_pkt).encode("utf-8"))
            _cli_conn = {
                "status": "pending", "sock": _cli_sock, "code": code,
                "my_name": my_name, "my_id": my_id, "is_host": False,
                "host_name": "Host", "deadline": time.time() + 1.0, "mode": "join",
            }
        except Exception as e:
            print(f"Failed to connect to relay - starting in offline mode: {e!r}")
            sock = None; code = "Offline"; stage1 = "lobby"; I_AM_HOST = False
    
    # Renderer handles track, cars, and drift marks
    renderer = WorldRenderer(track_image, flags, chunked_map=chunked_map, chunked_map_bg=chunked_map_bg, chunked_map_fg=chunked_map_fg)

    # connect first available gamepad (if any)
    gp = Gamepad()
    gp.joystick = pygame.joystick.Joystick(0) if pygame.joystick.get_count() > 0 else None
    gp.selected_index = gp.joystick.get_id() if gp.joystick else None
    if gp.joystick: gp.connect_gamepad(gp.selected_index)

    # Create a camera object; mouse wheel will adjust zoom and middle mouse drag will pan.
    cam = camera.Camera(const.WINDOW_WIDTH, const.WINDOW_HEIGHT, zoom=1.0)
    dragging = False
    host_ref = [I_AM_HOST]
    
    def stop_race(sock, code, my_id): # flag1
        nonlocal stage2
        stage2 = ""
        # print("hi from stop_race located in app.py")
        if not send_stop_race(sock, code, my_id):
            game_mode.force_end_race()
            # game_mode.phase = game_mode.PHASE_COOLDOWN
            # game_mode.cooldown_start = time.monotonic()

    def quit_game():
        save_manager.save_settings(audio_volumes, physics_controls)
        pygame.quit()
        sys.exit(0)

    def leave_room(sock, code, my_id, remotes):
        nonlocal host_name, game_mode, _prev_stage1, _return_btn_rect, _local_result_sent, _ai_results_sent, _start_roster
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
        _prev_stage1 = "menu"
        _return_btn_rect = None
        _local_result_sent = False
        _ai_results_sent = {}
        _start_roster = None
        invalidate_ui_text_cache('room')  # Clear cached room code text
        # Clear tire marks and chunk cache to free memory
        renderer.clear_tire_marks()
        renderer.clear_chunk_cache()
        return "menu", "", None, None, remotes # stage, substage sock, code, remotes
    
    def handle_controls():
        nonlocal stage3
        stage3 = "controls"
    
    def handle_audio():
        nonlocal stage3
        stage3 = "audio"
        # print("hi from handle_audio located in app.py")
    
    def handle_modes():
        nonlocal stage3
        stage3 = "modes"
        # print("hi from handle_modes located in app.py")

    settings_buttons = [ # todo : be able to use '*' like '*/settings' for key binds
    btn.Button("Stop Race", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.25, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, 
               [["mode1", "settings"], ["mode2", "settings"], ["mode_tutorial", "settings"]], lambda: stop_race(sock, code, my_id)),
    btn.Button("Quit Game", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.35, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, 
               [["menu", "settings"]] ,lambda: quit_game()),
    btn.Button("Leave Room", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.35, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, 
               [["lobby", "settings"], ["mode1", "settings"], ["mode2", "settings"], ["mode_tutorial", "settings"], ["leaderboard", "settings"]] ,lambda: leave_room(sock, code, my_id, remotes)),
    btn.Button("Controls", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.45, const.BTN_WIDTH, const.BTN_HEIGHT, const.BLUE, 
               [["menu", "settings"], ["lobby", "settings"], ["mode1", "settings"], ["mode2", "settings"], ["mode_tutorial", "settings"], ["leaderboard", "settings"]], handle_controls),
    btn.Button("Audio", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.55, const.BTN_WIDTH, const.BTN_HEIGHT, const.BLUE, 
               [["menu", "settings"], ["lobby", "settings"], ["mode1", "settings"], ["mode2", "settings"], ["mode_tutorial", "settings"], ["leaderboard", "settings"]], handle_audio),
    btn.Button("Modes", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.65, const.BTN_WIDTH, const.BTN_HEIGHT, const.BLUE, 
               [["menu", "settings"], ["lobby", "settings"], ["mode1", "settings"], ["mode2", "settings"], ["mode_tutorial", "settings"], ["leaderboard", "settings"]], handle_modes),
    ]
    
    profiler = FrameProfiler()
    show_frame_analysis = False
    show_scoreboard = False

    # Reusable UI surface (avoid per-frame allocation)
    ui_surf = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), pygame.SRCALPHA)

    # ── Helper: cycle car type (shared by keyboard & gamepad) ──
    def _cycle_car_type():
        nonlocal engine_audio, current_engine_sound_id
        if stage1 == "mode_tutorial":
            return
        available_types = list(const.CAR_SPRITES.keys())
        lower_types = [t.lower() for t in available_types]
        try:
            idx = available_types.index(my_car.car_type)
        except ValueError:
            idx = lower_types.index(my_car.car_type.lower()) if my_car.car_type.lower() in lower_types else 0
        my_car.set_car_type(available_types[(idx + 1) % len(available_types)])
        engine_audio, current_engine_sound_id = sync_engine_audio_system(
            engine_audio, audio_initialized, current_engine_sound_id, my_car,
        )
        set_palette_colors_from_car(my_car.palette_colors)
        invalidate_palette_cache()

    # ── Helper: load map start grid ──
    def _load_start_grid():
        """Return list of (x, y, a) tuples from the current map's map_meta.json."""
        try:
            meta_path = asset_path("track", f"map{const.MAP_NUM}", "map_meta.json")
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            return [
                (float(sp.get("x", 400)), float(sp.get("y", 400)), float(sp.get("a", 0.0)))
                for sp in (meta.get("start") or [])
            ]
        except Exception:
            return []

    def _reload_current_map_assets():
        """Reload base track assets and map-scoped caches for the current MAP_NUM."""
        nonlocal track_image, chunked_map, chunked_map_bg, chunked_map_fg
        nonlocal checkpoints, _path_future, _path_future_map_num, _path_poly_map_num, path_poly

        track_image = pygame.image.load(get_track_base_image_path(f"map{const.MAP_NUM}")).convert()
        chunked_map = ChunkedMap(root=normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=const.TILE_SIZE)
        _bg_root = normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks_bg")
        chunked_map_bg = ChunkedMap(root=_bg_root, tile_size=const.TILE_SIZE) if os.path.isdir(_bg_root) else None
        _fg_root = normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks_fg")
        chunked_map_fg = ChunkedMap(root=_fg_root, tile_size=const.TILE_SIZE, use_alpha=True) if os.path.isdir(_fg_root) else None

        _cp_rects = []
        meta_path = asset_path("track", f"map{const.MAP_NUM}", "map_meta.json")
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            for cp in meta.get("checkpoints", []):
                _cp_rects.append(pygame.Rect(cp.get("x", 0), cp.get("y", 0), cp.get("width", 0), cp.get("height", 0)))
        except Exception:
            pass
        checkpoints = _cp_rects

        _path_future = None
        _path_future_map_num = None
        _path_poly_map_num = None
        path_poly = []

        if renderer:
            renderer.track_image = track_image
            renderer.chunked_map = chunked_map
            renderer.chunked_map_bg = chunked_map_bg
            renderer.chunked_map_fg = chunked_map_fg
            renderer.checkpoints = checkpoints

    # ── Helper: spawn AI car (shared by keyboard & gamepad) ──
    def _try_spawn_ai():
        _max_p = game_mode.max_players if game_mode else 6
        if I_AM_HOST and stage1 in ["lobby", "mode1", "mode2"] and stage2 == "" and 1 + len(remotes) + len(ai_cars) < _max_p:
            from drift.ui.draw_stage import set_game_option
            set_game_option("ai_amount", len(ai_cars) + 1)

    def _sync_ai_count():
        """Spawn or remove AI cars to match game_options ai_amount."""
        if not I_AM_HOST:
            return
        target = get_game_options()["ai_amount"]
        if len(ai_cars) < target:
            grid = _load_start_grid()
            humans = 1 + len(remotes)  # slot 0..humans-1 occupied by real players
            while len(ai_cars) < target:
                slot = humans + len(ai_cars)
                if grid and slot < len(grid):
                    sx, sy, sa = grid[slot]
                elif grid:
                    sx, sy, sa = grid[len(ai_cars) % len(grid)]
                else:
                    sx, sy, sa = 400.0, 400.0, 0.0
                ai_car_type = random.choice(const.AVAILABLE_CARS)
                ai_inst = Car(
                    sx, sy,
                    name=f"AI-{len(ai_cars)+1}", is_ai=True, car_type=ai_car_type,
                )
                ai_inst.angle = sa
                ai_cars.append(ai_inst)
        while len(ai_cars) > target:
            ai_cars.pop()

    # ══════════════════════════════════════════════════════════
    #  MAIN LOOP  —  strict  Input → Update → Draw  ordering
    # ══════════════════════════════════════════════════════════
    
    while True:
        dt = clock.tick(const.FPS) / 1000.0
        dt_sim = dt * time_scale

        # ── Poll pending CLI connection (non-blocking) ──
        if _cli_conn is not None and _cli_conn["status"] == "pending":
            from drift.ui.draw_stage import poll_connection
            poll_connection(_cli_conn)
            if _cli_conn["status"] == "done":
                _cli_sock = _cli_conn.get("sock")
                _cli_mode = _cli_conn["mode"]
                # For CLI, we only care about getting the socket; track assets already loaded
                if _cli_mode == "host":
                    # Check if we got a live socket or fell back offline
                    if _cli_sock and _cli_conn.get("result") and _cli_conn["result"][3] is not None:
                        sock = _cli_conn["result"][3]
                    else:
                        sock = None; code = "Offline"
                    stage1 = "lobby"; I_AM_HOST = True
                else:  # join
                    result = _cli_conn.get("result")
                    if result and result[0] == "lobby" and result[3] is not None:
                        sock = result[3]; code = result[2]
                        stage1 = "lobby"; I_AM_HOST = False
                    else:
                        sock = None; code = "Offline"
                        stage1 = "lobby"; I_AM_HOST = False
                _cli_conn = None

        # ────────────────────────────────────────────────────
        # PHASE 1 · INPUT  —  collect all events & controls
        # ────────────────────────────────────────────────────

        profiler.begin("input")

        # 1a. Pump SDL events
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                if sock and code:
                    try: sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                    except Exception: pass
                try:
                    if engine_audio: engine_audio.stop_all()
                    if shift_sound: shift_sound.stop_all()
                except Exception: pass
                save_manager.save_settings(audio_volumes, physics_controls)
                pygame.quit(); sys.exit(0)

            # Keyboard shortcuts (global)
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_l:
                    lights_on = not lights_on
                elif ev.key == const.CHANGE_CAR_KEY:
                    _cycle_car_type()
                elif ev.key == const.RESET_KEY:
                    if stage1.startswith("mode") and my_car.last_checkpoint_coordinates is not None:
                        lx, ly, la = my_car.last_checkpoint_coordinates
                        my_car.x, my_car.y, my_car.angle = lx, ly, la
                        my_car.vx, my_car.vy = 0.0, 0.0
                        my_car.v_angle = 0.0
                elif ev.key == const.RESTART_KEY:
                    if stage1.startswith("mode") and len(remotes) == 0:
                        # Restart race (solo player only, AI don't count)
                        if game_mode is not None:
                            game_mode.on_exit(); game_mode = None
                        renderer.clear_tire_marks()
                        my_car.last_checkpoint_coordinates = None
                        _local_result_sent = False
                        _ai_results_sent = {}
                        _start_roster = None
                        _prev_stage1 = "lobby"
                    elif stage1.startswith("mode") and my_car.last_checkpoint_coordinates is not None:
                        lx, ly, la = my_car.last_checkpoint_coordinates
                        my_car.x, my_car.y, my_car.angle = lx, ly, la
                        my_car.vx, my_car.vy = 0.0, 0.0
                        my_car.v_angle = 0.0
                elif ev.key == const.DEBUG_TOGGLE_KEY:
                    const.DEBUG = not const.DEBUG
                    invalidate_ui_text_cache('debug')
                elif ev.key == pygame.K_F4:
                    show_frame_analysis = not show_frame_analysis
                elif ev.key == pygame.K_TAB:
                    show_scoreboard = True
            if ev.type == pygame.KEYUP:
                if ev.key == pygame.K_TAB:
                    show_scoreboard = False
                elif ev.key == const.FULLSCREEN_KEY:
                    is_fullscreen = not is_fullscreen
                    if is_fullscreen:
                        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                        const.WINDOW_WIDTH, const.WINDOW_HEIGHT = screen.get_size()
                        cam.zoom = 2.0
                    else:
                        const.WINDOW_WIDTH, const.WINDOW_HEIGHT = const.WINDOW_WIDTH_W, const.WINDOW_HEIGHT_W
                        screen = pygame.display.set_mode((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
                        cam.zoom = 1.0
                elif ev.key == const.AI_KEY:
                    _try_spawn_ai()

            # Camera controls (mouse)
            if ev.type == pygame.MOUSEWHEEL:
                cam.zoom *= 1.1 if ev.y > 0 else 0.9
                cam.zoom = clamp(cam.zoom, 1, 3.0)
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 2:
                dragging = True
            if ev.type == pygame.MOUSEBUTTONUP and ev.button == 2:
                dragging = False
            if ev.type == pygame.MOUSEMOTION and dragging:
                cam.offset[0] -= ev.rel[0] / cam.zoom
                cam.offset[1] -= ev.rel[1] / cam.zoom

            # print(f"stage3 before handle_game_events: {stage3}")
            map_num_before_ui = const.MAP_NUM
            # Delegate to UI event handler (menus, menu, lobby setup)
            ev, stage1, stage2, stage3, remotes, sock, code, my_car, error_msg, host_name, track_image, chunked_map, checkpoints = handle_game_events(
                screen, ev, stage1, stage2, stage3, save_manager, gp, remotes, ai_cars, sock, code,
                my_name, my_id, my_car, font_big, font_small, error_msg, host_ref, host_name,
                track_image=track_image, chunked_map=chunked_map, checkpoints=checkpoints,
            )
            if const.MAP_NUM != map_num_before_ui:
                _reload_current_map_assets()
            # print(f"stage3 after: {stage3}")
            I_AM_HOST = host_ref[0]
            engine_audio, current_engine_sound_id = sync_engine_audio_system(
                engine_audio, audio_initialized, current_engine_sound_id, my_car,
            )

            # Leaderboard "Return to Lobby" button click
            if (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1
                    and stage1 == "leaderboard" and I_AM_HOST
                    and _return_btn_rect is not None
                    and _return_btn_rect.collidepoint(ev.pos)):
                if game_mode is not None:
                    game_mode.on_exit(); game_mode = None
                stage1 = "lobby"; _prev_stage1 = "lobby"
                _return_btn_rect = None; _local_result_sent = False; _ai_results_sent = {}; _start_roster = None
                my_car.x, my_car.y = random.randint(100, const.WINDOW_WIDTH - 100), random.randint(100, const.WINDOW_HEIGHT - 100)
                my_car.vx, my_car.vy = 0.0, 0.0
                if sock and code and code != "Offline":
                    try:
                        sock.send(json.dumps({"t": "start_race", "code": code, "id": my_id, "mode": "lobby"}).encode("utf-8"))
                    except Exception:
                        pass

        # ── Per-frame: apply completed non-blocking connection (runs once/frame, not per-event) ──
        conn_result = poll_pending_connection()
        if conn_result is not None:
            stage1, stage2, sock, code, my_name, is_host, host_name, _err, track_image, chunked_map, checkpoints = conn_result
            I_AM_HOST = is_host; host_ref[0] = is_host
            engine_audio, current_engine_sound_id = sync_engine_audio_system(
                engine_audio, audio_initialized, current_engine_sound_id, my_car
            )

            # Sync renderer with any map changes from UI
            if renderer and track_image and renderer.track_image != track_image: renderer.track_image = track_image
            if renderer and chunked_map and renderer.chunked_map != chunked_map:
                renderer.chunked_map = chunked_map
                _bg_root = normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks_bg")
                renderer.chunked_map_bg = ChunkedMap(root=_bg_root, tile_size=const.TILE_SIZE) if os.path.isdir(_bg_root) else None
                _fg_root = normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks_fg")
                renderer.chunked_map_fg = ChunkedMap(root=_fg_root, tile_size=const.TILE_SIZE, use_alpha=True) if os.path.isdir(_fg_root) else None
            if renderer and checkpoints: renderer.checkpoints = checkpoints

        # 1b. Gamepad buttons (outside event loop — polled)
        if gp and gp.joystick:
            js = gp.joystick
            if js.get_button(2) and time.time() - ctlr_btn2_time > 0.2:
                ctlr_btn2_time = time.time()
                _cycle_car_type()
            if js.get_button(3) and time.time() - ctlr_btn3_time > 0.2:
                ctlr_btn3_time = time.time()
                _try_spawn_ai()

        # 1c. Compute authoritative controls for this frame (single source of truth)
        skip_physics = stage3 == "controls"

        # Sync AI car count with game options (lobby + active gameplay)
        if stage1 in ("lobby", "mode1", "mode2"):
            _sync_ai_count()

        controls = {"th": 0.0, "st": 0.0, "br": 0.0}
        ai_controls_for_player = {"th": 0.0, "st": 0.0, "br": 0.0}
        ai_debug_surface = None
        if not skip_physics:
            tutorial_allow_ai_takeover = False
            if stage1 == "mode_tutorial":
                tutorial_allow_ai_takeover, _, _ = _tutorial_profile_flags()

            if stage1 == "mode_tutorial":
                # In tutorial mode, base controls should always come from the player;
                # tutorial AI may still take over explicitly via force_ai_drive.
                controls = read_inputs(gp, my_car, cam)
                if tutorial_allow_ai_takeover:
                    if tutorial_ctrl is not None and path_poly:
                        try:
                            ai_controls_for_player = ai_algorithme(path_poly, my_car)
                        except Exception:
                            ai_controls_for_player = _tutorial_bootstrap_ai_controls(my_car, tutorial_ctrl)
                    else:
                        ai_controls_for_player = _tutorial_bootstrap_ai_controls(my_car, tutorial_ctrl)
            else:
                ai_controls_ok = False
                if const.AI_PATH_FOLLOW and path_poly:
                    try:
                        _ai_surf_size = (track_image.get_width(), track_image.get_height())
                        if _ai_debug_surf is None or _ai_debug_surf.get_size() != _ai_surf_size:
                            _ai_debug_surf = pygame.Surface(_ai_surf_size, pygame.SRCALPHA)
                        else:
                            _ai_debug_surf.fill((0, 0, 0, 0))
                        controls, ai_debug_surface = ai_algorithme(
                            path_poly, my_car, ai_path_mode=True,
                            surface=_ai_debug_surf,
                            font_small=font_small,
                        )
                        ai_controls_ok = True
                    except Exception:
                        pass
                if not ai_controls_ok:
                    controls = read_inputs(gp, my_car, cam)

            # Tutorial should be AI-driven immediately on entry, even before
            # the controller instance is created later in the frame lifecycle.
            if stage1 == "mode_tutorial" and tutorial_allow_ai_takeover and tutorial_ctrl is None:
                controls = ai_controls_for_player

            if stage1 == "mode_tutorial" and tutorial_ctrl is not None:
                tutorial_frame_state = tutorial_ctrl.update(dt, time_scale, my_car, controls)
                if tutorial_allow_ai_takeover and tutorial_frame_state.force_ai_drive:
                    controls = ai_controls_for_player
            else:
                tutorial_frame_state = None

        if stage1 == "mode_tutorial" and tutorial_ctrl is not None and tutorial_frame_state is not None:
            target_scale = float(tutorial_frame_state.target_time_scale)
        else:
            target_scale = 1.0

        target_scale = max(0.0, min(1.0, target_scale))
        rate = const.TUTORIAL_SPEEDUP_RATE if target_scale >= time_scale else const.TUTORIAL_SLOWDOWN_RATE
        time_scale += (target_scale - time_scale) * min(1.0, rate * dt)

        if target_scale <= 0.0:
            # Smoothly ease toward freeze, then snap only when very close.
            if time_scale <= 0.005:
                time_scale = 0.0
            time_scale = max(0.0, min(1.0, time_scale))
        else:
            tutorial_min_scale = max(0.0, float(getattr(const, "TUTORIAL_MIN_TIME_SCALE", 0.0)))
            time_scale = max(tutorial_min_scale, min(1.0, time_scale))
        dt_sim = dt * time_scale

        profiler.end("input")

        # ────────────────────────────────────────────────────
        # PHASE 2 · UPDATE: NETWORK
        # ────────────────────────────────────────────────────

        profiler.begin("network")
        if sock:
            net_result = handle_network_messages(sock, remotes, dt, my_id, I_AM_HOST, code, my_car=my_car) # flag1
            if net_result.get("stop_race") and game_mode:
                game_mode.force_end_race()
                # game_mode.phase = game_mode.PHASE_COOLDOWN
                # game_mode.cooldown_start = time.monotonic()
            if net_result.get("host_name") is not None:
                host_name = net_result["host_name"] or None
            if net_result.get("host_id") is not None:
                I_AM_HOST = (net_result["host_id"] == my_id)
                host_ref[0] = I_AM_HOST
            if net_result.get("start_mode") and stage1 in ["lobby", "mode1", "mode2", "mode_tutorial", "leaderboard"]:
                new_mode = net_result["start_mode"]
                if new_mode.startswith("mode") and stage1 != "lobby":
                    new_mode = None
                if new_mode is None:
                    pass
                elif new_mode == "lobby":
                    if stage1 != "lobby":
                        if game_mode is not None:
                            game_mode.on_exit(); game_mode = None
                        tutorial_ctrl = None
                        tutorial_frame_state = None
                        time_scale = 1.0
                        rewind_history.clear()
                        _prev_stage1 = "lobby"; _return_btn_rect = None; _local_result_sent = False; _ai_results_sent = {}; _start_roster = None
                        my_car.x, my_car.y = random.randint(100, const.WINDOW_WIDTH - 100), random.randint(100, const.WINDOW_HEIGHT - 100)
                        my_car.vx, my_car.vy = 0.0, 0.0
                        renderer.clear_tire_marks()
                        stage1 = new_mode
                else:
                    stage1 = new_mode
                    renderer.clear_tire_marks()
                    start_choice = net_result.get("start_choice")
                    if isinstance(start_choice, int):
                        set_game_option("choice", start_choice)
                    # Save relay roster so spawn positions are deterministic
                    # across all clients (avoids AI/player slot mismatch).
                    _start_roster = net_result.get("start_roster")
                    start_track = net_result.get("start_track")
                    # For host, use selected_track from game setup (they may have changed it in the panel)
                    if I_AM_HOST:
                        start_track = get_game_setup().get("selected_track", "track1")
                    if isinstance(start_track, str) and start_track.startswith("track"):
                        try:
                            new_map_num = int(start_track[5:])
                        except Exception:
                            new_map_num = const.MAP_NUM
                        if new_map_num != const.MAP_NUM:
                            const.MAP_NUM = new_map_num
                            track_image = pygame.image.load(get_track_base_image_path(f"map{const.MAP_NUM}")).convert()
                            chunked_map = ChunkedMap(root=normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=const.TILE_SIZE)
                            _bg_root = normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks_bg")
                            chunked_map_bg = ChunkedMap(root=_bg_root, tile_size=const.TILE_SIZE) if os.path.isdir(_bg_root) else None
                            _fg_root = normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks_fg")
                            chunked_map_fg = ChunkedMap(root=_fg_root, tile_size=const.TILE_SIZE, use_alpha=True) if os.path.isdir(_fg_root) else None
                            renderer.track_image = track_image
                            renderer.chunked_map = chunked_map
                            renderer.chunked_map_bg = chunked_map_bg
                            renderer.chunked_map_fg = chunked_map_fg
                            _path_future = None
                            _path_future_map_num = None
                            _path_poly_map_num = None
                            path_poly = []
            if game_mode is not None and net_result.get("race_results"):
                game_mode.apply_network_results(net_result["race_results"])
            err = net_result.get("error")
            if err:
                try:
                    sock.close()
                except Exception:
                    pass
                sock = None; code = "Offline"; remotes.clear()

        if sock and code and code != "Offline":
            now = time.time()
            if now - last_state_send >= 1.0 / const.SEND_HZ:
                last_state_send = now
                send_network_state(sock, code, my_id, my_car, palette=get_palette_colors())
                if I_AM_HOST and ai_cars and stage1 != "lobby":
                    send_ai_states(sock, code, ai_cars)
            if now - last_ping >= 1.0 / const.PING_HZ:
                last_ping = now
                send_ping(sock, code)
        profiler.end("network")

        # ────────────────────────────────────────────────────
        # PHASE 3 · UPDATE: GAME MODE LIFECYCLE
        # ────────────────────────────────────────────────────

        profiler.begin("gamemode")

        # Offline/local starts do not receive a relay start event, so apply
        # the selected lobby track before creating the race game mode.
        if (
            stage1 != _prev_stage1
            and _prev_stage1 in ("lobby", "menu")
            and stage1.startswith("mode")
            and (not sock or code == "Offline")
        ):
            local_track = get_game_setup().get("selected_track", "track1")
            if isinstance(local_track, str) and local_track.startswith("track"):
                try:
                    new_map_num = int(local_track[5:])
                except Exception:
                    new_map_num = const.MAP_NUM

                if new_map_num != const.MAP_NUM:
                    const.MAP_NUM = new_map_num
                    track_image = pygame.image.load(get_track_base_image_path(f"map{const.MAP_NUM}")).convert()
                    chunked_map = ChunkedMap(root=normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=const.TILE_SIZE)
                    _bg_root = normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks_bg")
                    chunked_map_bg = ChunkedMap(root=_bg_root, tile_size=const.TILE_SIZE) if os.path.isdir(_bg_root) else None
                    _fg_root = normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks_fg")
                    chunked_map_fg = ChunkedMap(root=_fg_root, tile_size=const.TILE_SIZE, use_alpha=True) if os.path.isdir(_fg_root) else None
                    renderer.track_image = track_image
                    renderer.chunked_map = chunked_map
                    renderer.chunked_map_bg = chunked_map_bg
                    renderer.chunked_map_fg = chunked_map_fg
                    _path_future = None
                    _path_future_map_num = None
                    _path_poly_map_num = None
                    path_poly = []

                _cp_rects = []
                meta_path = asset_path("track", f"map{const.MAP_NUM}", "map_meta.json")
                try:
                    with open(meta_path, "r", encoding="utf-8") as fh:
                        meta = json.load(fh)
                    for cp in meta.get("checkpoints", []):
                        _cp_rects.append(pygame.Rect(cp.get("x", 0), cp.get("y", 0), cp.get("width", 0), cp.get("height", 0)))
                except Exception:
                    pass
                checkpoints = _cp_rects
                renderer.checkpoints = checkpoints

        if stage1 != _prev_stage1:
            if _prev_stage1.startswith("mode") and game_mode is not None:
                if stage1 != "leaderboard":
                    game_mode.on_exit(); game_mode = None
            if _prev_stage1.startswith("mode") and stage1 != _prev_stage1:
                tutorial_ctrl = None
                tutorial_frame_state = None
                tutorial_end_zone = None
                time_scale = 1.0
                rewind_history.clear()
                rewind_playback = []
                rewind_playback_idx = 0
                rewind_playback_active = False

            if stage1.startswith("mode") and game_mode is None:
                _start_grid = []; _lines = []; _collision_mesh = CollisionMesh([])
                try:
                    meta_path = asset_path("track", f"map{const.MAP_NUM}", "map_meta.json")
                    with open(meta_path, "r", encoding="utf-8") as fh:
                        _meta = json.load(fh)
                    _start_grid = _meta.get("start", []) or []
                    _lines = _meta.get("lines", []) or []
                    _raw_mesh = _meta.get("collision_mesh", []) or []
                    _collision_mesh = CollisionMesh(_raw_mesh) if _raw_mesh else CollisionMesh([])
                except Exception:
                    pass

                renderer.collision_mesh = _collision_mesh
                mode_classes = {0: ClassicRace, 1: BestLap}
                game_mode = mode_classes.get(const.MODE_INDEX)
                if game_mode:
                    # print(get_game_options()["choice"])
                    game_mode = game_mode(renderer.checkpoints or [], start_grid=_start_grid, choice_index=get_game_options()["choice"], 
                                          lines=_lines, local_player_id=my_id, path_poly=path_poly)

                _local_result_sent = False
                _ai_results_sent = {}
                _mode_players = {my_id: {"car_type": my_car.car_type, "name": my_car.name}}
                for pid, rd in remotes.items():
                    _mode_players[pid] = {"car_type": rd.get("car_type", "AE86"), "name": rd.get("name", pid)}
                for i, ai in enumerate(ai_cars, start=1):
                    _mode_players[f"AI-{i}"] = {"car_type": ai.car_type, "name": ai.name}
                game_mode.on_enter(_mode_players)

                # Use the relay-provided roster for spawn slot assignment so
                # every client (host & non-host) computes identical positions,
                # even if some AI world-states haven't arrived yet.
                if _start_roster and isinstance(_start_roster, list):
                    sorted_spawn_ids = sorted(_start_roster)
                    # Ensure our own id is in the roster (shouldn't be missing,
                    # but guard against relay hiccups).
                    if my_id not in sorted_spawn_ids:
                        sorted_spawn_ids.append(my_id)
                        sorted_spawn_ids.sort()
                else:
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

            if stage1 == "mode_tutorial":
                tutorial_car_type = "AE86"
                if my_car.car_type.lower() != tutorial_car_type.lower():
                    my_car.set_car_type(tutorial_car_type)
                    set_palette_colors_from_car(my_car.palette_colors)
                    invalidate_palette_cache()
                _init_tutorial_runtime(reset_variant=True)

            if _prev_stage1 == "leaderboard" and game_mode is not None:
                game_mode.on_exit(); game_mode = None

            _prev_stage1 = stage1

        mode_result = {}
        if game_mode is not None and (stage1.startswith("mode") or stage1 in ["leaderboard"]):
            _mode_players_update = dict(remotes)
            for i, ai in enumerate(ai_cars, start=1):
                _mode_players_update[f"AI-{i}"] = ai
            mode_result = game_mode.update(dt_sim, _mode_players_update, my_car, I_AM_HOST)
            local_finish_time = game_mode.get_local_finish_time()
            if local_finish_time is not None and not _local_result_sent and sock and code and code != "Offline":
                try:
                    # Include best lap time if available so relay can broadcast it
                    best_lap = None
                    try:
                        if game_mode and my_id in getattr(game_mode, 'player_states', {}):
                            bp = game_mode.player_states.get(my_id)
                            best_lap = bp.best_lap_time if bp is not None else None
                    except Exception:
                        best_lap = None

                    payload = {"t": "race_result", "code": code, "id": my_id, "time": float(local_finish_time)}
                    if best_lap is not None:
                        payload["best_lap"] = float(best_lap)

                    sock.send(json.dumps(payload).encode("utf-8"))
                    _local_result_sent = True
                except Exception:
                    pass
            # If host, send race_result for AI cars when they finish so relay records authoritative results
            if I_AM_HOST and game_mode is not None and sock and code and code != "Offline":
                try:
                    for i, ai in enumerate(ai_cars, start=1):
                        aid = f"AI-{i}"
                        ps = game_mode.player_states.get(aid)
                        if ps is None:
                            continue
                        if ps.finished and not _ai_results_sent.get(aid):
                            # send race_result for this AI
                            payload = {"t": "race_result", "code": code, "id": aid, "time": float(ps.finish_time)}
                            try:
                                if ps.best_lap_time is not None:
                                    payload["best_lap"] = float(ps.best_lap_time)
                            except Exception:
                                pass
                            try:
                                sock.send(json.dumps(payload).encode("utf-8"))
                            except Exception:
                                pass
                            _ai_results_sent[aid] = True
                except Exception:
                    pass
            if mode_result.get("stage_transition") == "leaderboard":
                stage1 = "leaderboard"; _prev_stage1 = "leaderboard"

        profiler.end("gamemode")

        # ────────────────────────────────────────────────────
        # PHASE 4 · UPDATE: PHYSICS
        # ────────────────────────────────────────────────────

        world_size = renderer.get_world_size(stage1 if stage1 != "leaderboard" else "mode1")

        profiler.begin("physics")
        if not skip_physics:
            movement_locked = bool(mode_result.get("movement_locked"))
            tutorial_single_player = stage1 == "mode_tutorial" and (not sock or code == "Offline") and len(remotes) == 0
            _allow_ai_takeover, _enable_qte, tutorial_rewind_enabled = _tutorial_profile_flags()

            if tutorial_single_player and not rewind_playback_active:
                rewind_history.append({
                    "t": time.monotonic(),
                    "x": my_car.x,
                    "y": my_car.y,
                    "vx": my_car.vx,
                    "vy": my_car.vy,
                    "angle": my_car.angle,
                    "v_angle": my_car.v_angle,
                    "target_angle": my_car.target_angle,
                    "tutorial": tutorial_ctrl.get_rewind_snapshot() if tutorial_ctrl is not None else None,
                })

            # Build remote views once for collision queries
            remotes_with_ai_for_player = dict(remotes)
            if I_AM_HOST:
                for i, ai in enumerate(ai_cars, start=1):
                    key = f"AI-{i}"
                    remotes_with_ai_for_player[key] = {"x": ai.x, "y": ai.y, "a": ai.angle, "vx": ai.vx, "vy": ai.vy, "drift_ratio": ai.drift_ratio, "name": ai.name}

            player_impact = 0.0

            if rewind_playback_active:
                steps_per_frame = max(1, int(rewind_playback_rate * dt * const.FPS))
                rewind_playback_idx = min(len(rewind_playback) - 1, rewind_playback_idx + steps_per_frame)
                snap = rewind_playback[rewind_playback_idx]
                my_car.x = snap["x"]
                my_car.y = snap["y"]
                my_car.vx = snap["vx"]
                my_car.vy = snap["vy"]
                my_car.angle = snap["angle"]
                my_car.v_angle = snap["v_angle"]
                my_car.target_angle = snap["target_angle"]
                controls = {"th": 0.0, "st": 0.0, "br": 0.0}
                player_impact = 0.0
                if rewind_playback_idx >= len(rewind_playback) - 1:
                    restored_t = float(snap.get("t", 0.0)) if isinstance(snap, dict) else 0.0
                    rewind_playback_active = False
                    rewind_playback = []
                    rewind_playback_idx = 0
                    if tutorial_ctrl is not None:
                        snap_tutorial = snap.get("tutorial") if isinstance(snap, dict) else None
                        if isinstance(snap_tutorial, dict):
                            tutorial_ctrl.apply_rewind_snapshot(snap_tutorial, my_car)
                        else:
                            tutorial_ctrl.on_rewind(my_car)
                        tutorial_frame_state = tutorial_ctrl.update(dt, time_scale, my_car, controls)

                    # Trim away all "future" frames that were recorded after
                    # the restored snapshot so chained rewinds cannot jump ahead.
                    if rewind_history:
                        maxlen = rewind_history.maxlen
                        rewind_history = deque(
                            [h for h in rewind_history if float(h.get("t", 0.0)) <= restored_t],
                            maxlen=maxlen,
                        )

                    # Seed the new timeline from the restored state.
                    rewind_history.append({
                        "t": time.monotonic(),
                        "x": my_car.x,
                        "y": my_car.y,
                        "vx": my_car.vx,
                        "vy": my_car.vy,
                        "angle": my_car.angle,
                        "v_angle": my_car.v_angle,
                        "target_angle": my_car.target_angle,
                        "tutorial": tutorial_ctrl.get_rewind_snapshot() if tutorial_ctrl is not None else None,
                    })
                    last_rewind_at = time.monotonic()
            elif movement_locked:
                controls = {"th": 0.0, "st": 0.0, "br": 0.0}
                my_car.vx, my_car.vy = 0.0, 0.0
                my_car.v_angle = 0.0
            else:
                player_impact = my_car.step(controls, dt_sim, remotes_with_ai_for_player, world_size, cam=cam, collision_mesh=_collision_mesh)

            if tutorial_single_player and tutorial_ctrl is not None and tutorial_rewind_enabled:
                now_mono = time.monotonic()
                if (not rewind_playback_active) and player_impact >= const.TUTORIAL_HARD_CRASH_THRESHOLD and now_mono - last_rewind_at >= const.TUTORIAL_REWIND_COOLDOWN_S and rewind_history:
                    target_t = now_mono - const.TUTORIAL_REWIND_SECONDS
                    rewind_segment = [snap for snap in rewind_history if snap["t"] >= target_t]
                    if not rewind_segment:
                        rewind_segment = [rewind_history[0]]
                    rewind_playback = list(reversed(rewind_segment))
                    rewind_playback_idx = 0
                    rewind_playback_active = True
                    renderer.clear_tire_marks()

            # End-zone completion: leave tutorial as soon as player reaches it.
            if stage1 == "mode_tutorial" and tutorial_end_zone is not None:
                try:
                    if tutorial_end_zone.collidepoint(my_car.x, my_car.y):
                        if tutorial_variant < 3:
                            tutorial_variant += 1
                            _init_tutorial_runtime(reset_variant=False)
                        else:
                            stage1 = "menu"
                            stage2 = ""
                            stage3 = ""
                            tutorial_ctrl = None
                            tutorial_frame_state = None
                            tutorial_end_zone = None
                            rewind_playback = []
                            rewind_playback_idx = 0
                            rewind_playback_active = False
                            rewind_history.clear()
                            time_scale = 1.0
                except Exception:
                    pass

            # Engine audio (single RPM computation, shared with UI HUD)
            try:
                if audio_initialized and (engine_audio is not None or shift_sound is not None):
                    speed_units = math.hypot(my_car.vx, my_car.vy)
                    th = clamp(controls.get("th", 0.0), -1.0, 1.0)
                    prev_rpm = engine_state.get("last_rpm")
                    rpm = calc_engine_rpm(
                        speed_units=speed_units, drift_ratio=my_car.drift_ratio,
                        throttle=th, prev_rpm=prev_rpm, dt=dt_sim,
                        params=my_car.rpm_params, _state=engine_state,
                    )
                    engine_state["last_rpm"] = rpm
                    if engine_audio is not None:
                        engine_audio.update(rpm=rpm, throttle=abs(th))
                    current_gear = engine_state.get("gear", 0)
                    if shift_sound is not None:
                        shift_sound.update(
                            current_gear=current_gear, rpm=rpm, throttle=abs(th),
                            drift_ratio=my_car.drift_ratio,
                            engine_sound_id=getattr(my_car, "engine_sound_id", ""),
                        )
            except Exception:
                pass

            # AI cars (skip in lobby – AI exists in room but is inactive)
            if I_AM_HOST and ai_cars and stage1 != "lobby":
                remotes_with_ai_for_ais = dict(remotes)
                remotes_with_ai_for_ais[f"PLAYER-{my_id}"] = {"x": my_car.x, "y": my_car.y, "a": my_car.angle, "vx": my_car.vx, "vy": my_car.vy, "drift_ratio": my_car.drift_ratio, "name": my_car.name}
                for i, ai in enumerate(ai_cars, start=1):
                    remotes_with_ai_for_ais[f"AI-{i}"] = {"x": ai.x, "y": ai.y, "a": ai.angle, "vx": ai.vx, "vy": ai.vy, "drift_ratio": ai.drift_ratio, "name": ai.name}
                for ai in ai_cars:
                    if movement_locked:
                        ai.vx, ai.vy = 0.0, 0.0
                        ai.v_angle = 0.0
                        ai.time_since_mouvement = time.time() # reset timer when no game is running
                    else:
                        try:
                            ai_controls = ai_algorithme(path_poly, ai)
                        except Exception:
                            ai_controls = {"th": 0.0, "st": 0.0, "br": 0.0}
                        ai.step(ai_controls, dt_sim, remotes_with_ai_for_ais, world_size, collision_mesh=_collision_mesh)

            cam.update(my_car, world_size)
        profiler.end("physics")

        # ────────────────────────────────────────────────────
        # PHASE 5 · DRAW: WORLD
        # ────────────────────────────────────────────────────

        profiler.begin("render_world")
        if not skip_physics:
            render_stage = stage1 if stage1 != "leaderboard" else "mode1"
            visible_ai = ai_cars if stage1 != "lobby" else []
            world_surf, resized, is_viewport = renderer.render_world(cam, render_stage, my_car, visible_ai, remotes, lights_on, car_sprites_cache)

            # If map changed while a previous discovery job is still pending,
            # drop the handle and queue discovery for the active map.
            if _path_future is not None and _path_future_map_num != const.MAP_NUM:
                _path_future = None
                _path_future_map_num = None

            # Ensure each map gets its own path discovery result.
            if (
                stage1 in ["lobby", "mode1", "mode2", "mode_tutorial", "leaderboard"]
                and _path_future is None
                and _path_poly_map_num != const.MAP_NUM
            ):
                _start_path_discovery_for_current_map()

            # Poll for async path discovery result
            if _path_future is not None and _path_future.done():
                try:
                    if _path_future_map_num == const.MAP_NUM:
                        path_poly = _path_future.result()
                        _path_poly_map_num = const.MAP_NUM
                except Exception:
                    path_poly = []
                    _path_poly_map_num = None
                _path_future = None
                _path_future_map_num = None

            if gpu_display is not None:
                final_surf = world_surf if is_viewport else cam.apply_no_scale(world_surf)
            else:
                final_surf = pygame.transform.scale(world_surf, (const.WINDOW_WIDTH, const.WINDOW_HEIGHT)) if is_viewport else cam.apply(world_surf)
        else:
            if _skip_surf is None or _skip_surf.get_size() != (const.WINDOW_WIDTH, const.WINDOW_HEIGHT):
                _skip_surf = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
                _skip_surf.fill(const.GREY_20)
            world_surf = _skip_surf
            final_surf = world_surf
        profiler.end("render_world")

        # ────────────────────────────────────────────────────
        # PHASE 6 · DRAW: UI + OVERLAYS
        # ────────────────────────────────────────────────────

        profiler.begin("ui")
        ui_surf.fill((0, 0, 0, 0))
        fps = clock.get_fps()
        ping_ms = my_car.ping_ms if my_car else None
        ui_checkpoints = renderer.checkpoints
        if game_mode is not None and stage1 in ["mode1", "leaderboard"]:
            ui_checkpoints = []
            
        # print(f"stage3 before: {stage3}")
        world_surf, button_results, menu_bar_rects, palette_picker_rects, game_options_rects = draw_stage_ui(
            ui_surf, stage1 if stage1 != "leaderboard" else "mode1",
            stage2, stage3, code, world_surf, world_size, ui_checkpoints,
            settings_buttons, error_msg, my_car, cam, gp, font_big, font_medium, font_small,
            controls, engine_state, fps, dt, I_AM_HOST, host_name, car_sprites_cache,
            room_clients_count=1 + len(remotes),
            ping_ms=ping_ms,
        )
        if const.MODE_CLICKED:
            const.MODE_CLICKED = False
            stage2 = ""
            stage3 = ""
            
        draw_engine_audio_debug(ui_surf, engine_audio)
        draw_chunk_minimap(ui_surf, renderer)
        draw_minimap(ui_surf, path_poly, world_size, my_car, remotes, ai_cars, stage1)
        if stage1 == "mode_tutorial":
            draw_tutorial_overlay(ui_surf, font_small, tutorial_frame_state)
        profiler.end("ui")

        # Game mode overlays
        _return_btn_rect = None
        if game_mode is not None:
            if stage1 == "leaderboard":
                # print("cerise activated ?")
                lb_result = game_mode.draw_leaderboard(ui_surf, font_big, font_medium, font_small, I_AM_HOST)
                _return_btn_rect = lb_result.get("return_btn_rect")
            elif stage1 in ("mode1", "mode2"):
                game_mode.draw_hud(ui_surf, cam, font_big, font_medium, font_small)

        if show_frame_analysis:
            draw_frame_analysis(ui_surf, profiler)

        if show_scoreboard:
            draw_scoreboard(ui_surf, font_medium, font_small, my_car, remotes, ai_cars)

        # Apply settings button results
        for res in button_results:
            if isinstance(res, tuple) and len(res) == 5:
                stage1, stage2, sock, code, remotes = res

        # AI path debug overlay
        if const.AI_PATH_FOLLOW and stage1 == "lobby" and ai_debug_surface is not None:
            try:
                top_left = cam.x - (const.WINDOW_WIDTH / 2) / cam.zoom, cam.y - (const.WINDOW_HEIGHT / 2) / cam.zoom
                camera_rect = pygame.Rect(top_left[0], top_left[1], const.WINDOW_WIDTH / cam.zoom, const.WINDOW_HEIGHT / cam.zoom)
                ui_surf.blit(ai_debug_surface.subsurface(camera_rect), (0, 0))
            except Exception:
                pass

        # ────────────────────────────────────────────────────
        # PHASE 7 · PRESENT
        # ────────────────────────────────────────────────────

        profiler.begin("present")
        if gpu_display is not None:
            try:
                gpu_display.present(final_surf, ui_surf, profiler=profiler)
            except Exception:
                pass
        else:
            screen.blit(final_surf, (0, 0))
            screen.blit(ui_surf, (0, 0))
            pygame.display.flip()
        profiler.end("present")

        profiler.commit()

if __name__ == "__main__":
    main()
