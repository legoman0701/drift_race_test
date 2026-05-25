#!/usr/bin/env python3
"""
Checkpoint Editor - Visual tool for creating checkpoints and start positions
for drift race tracks.

Usage:
    python -m drift.tools.checkpoint_editor [--map MAP_NUM]

Controls:
    1 / C key  : Switch to Checkpoint editing mode
    2 / T key  : Switch to Start position editing mode

    --- CHECKPOINT MODE ---
    Left Click (empty area, drag): Create new checkpoint rectangle
    Left Click (inside rect):      Select / move checkpoint
    Left Click (corner handle):    Resize checkpoint from that corner
    Right Click:                   Delete checkpoint under cursor
    Enter / F2:                    Rename selected checkpoint (type name, Enter to confirm)

    --- START MODE ---
    Left Click (empty area):       Place new start position
    Left Click (existing):         Select / move start position
    Right Click:                   Delete start under cursor
    Q / Mouse Wheel (selected):    Rotate angle CCW
    E / Mouse Wheel (selected):    Rotate angle CW

    --- SHARED ---
    Middle Mouse + Drag:           Pan the map
    Arrow Keys:                    Pan the map
    Mouse Wheel:                   Zoom (when no start selected)
    G:                             Toggle grid
    F:                             Toggle foreground layer
    S:                             Save to map_meta.json
    L:                             Reload from map_meta.json
    PageUp / PageDown:             Switch to previous / next map
    ESC:                           Exit editor
"""

import pygame
import sys
import json
import os
import math

try:
    import drift.config.const as const
    from drift.tools.paths import asset_path, get_track_base_image_path
except ImportError:
    print("Error: Could not import drift modules. Make sure you're running from the project root.")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────────────────
EDIT_CHECKPOINT = 0
EDIT_START = 1

HANDLE_RADIUS = 8      # px – corner resize handle radius on screen
CORNER_NAMES = ("NW", "NE", "SW", "SE")

START_RADIUS = 10      # px – start-position circle radius on screen
ARROW_LENGTH = 30      # px – direction arrow length on screen

ANGLE_STEP_COARSE = 0.05   # radians per scroll tick / Q-E press
ANGLE_STEP_FINE   = 0.005  # with Shift held


# ──────────────────────────────────────────────────────────
#  Editor class
# ──────────────────────────────────────────────────────────
class CheckpointEditor:
    def __init__(self, map_num: int = 1):
        pygame.init()

        self.screen_width  = 1400
        self.screen_height = 900
        self.screen = pygame.display.set_mode((self.screen_width, self.screen_height))
        pygame.display.set_caption(f"Checkpoint Editor – Map {map_num}")

        self.map_num   = map_num
        self.map_image = self._load_map_image()

        # Camera / viewport
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.zoom     = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 4.0

        # Grid
        self.grid_size = 5
        self.show_grid = True
        self.show_fg   = True

        # Layer surfaces
        self.map_bg_image = None
        self.map_fg_image = None

        # Panning
        self.panning       = False
        self.pan_start_x   = 0
        self.pan_start_y   = 0
        self.pan_key_speed = 500   # world-units / second

        # Edit mode
        self.mode = EDIT_CHECKPOINT

        # Data ────────────────────────────────────────────────
        # checkpoints: list of dicts  {id, name, x, y, width, height}
        # starts:      list of dicts  {id, x, y, a}
        # _lines_raw:  list of dicts  – preserved from file, not visually edited
        self.checkpoints = []
        self.starts      = []
        self._lines_raw  = []

        # Checkpoint editing state
        self.sel_cp_idx    = None   # selected checkpoint index
        self.drag_cp_idx   = None   # checkpoint being dragged/resized
        self.drag_handle   = None   # None = move-body | "NW"|"NE"|"SW"|"SE"
        self.drag_offset   = (0, 0) # mouse offset from top-left on body-drag
        # New-rect creation state
        self.creating_cp   = False
        self.create_start  = None   # (wx, wy) world coords
        self.create_cur    = None   # (wx, wy) current drag end

        # Start editing state
        self.sel_st_idx    = None
        self.drag_st_idx   = None
        self.drag_st_offset = (0, 0)

        # Rename state
        self.renaming      = False
        self.rename_text   = ""

        # Hover
        self.hover_cp_idx  = None
        self.hover_st_idx  = None

        self._load_data()

        # Fonts / clock
        self.font       = pygame.font.SysFont("Arial", 14)
        self.font_large = pygame.font.SysFont("Arial", 18)
        self.clock      = pygame.time.Clock()
        self.running    = True

    # ──────────────────────────────────────────────────────
    #  Map loading
    # ──────────────────────────────────────────────────────
    def _load_map_image(self):
        try:
            map_key = f"map{self.map_num}"
            bg_path = asset_path("track", map_key, "main_bg.png")
            fg_path = asset_path("track", map_key, "main_fg.png")

            bg_img = pygame.image.load(bg_path).convert_alpha() if os.path.exists(bg_path) else None
            fg_img = pygame.image.load(fg_path).convert_alpha() if os.path.exists(fg_path) else None

            self.map_bg_image = bg_img
            self.map_fg_image = fg_img

            if bg_img is not None or fg_img is not None:
                ref = bg_img if bg_img is not None else fg_img
                image = ref.convert_alpha()
                return image

            map_path = get_track_base_image_path(map_key)
            image = pygame.image.load(map_path).convert()
            self.map_bg_image = image
            self.map_fg_image = None
            return image
        except Exception as e:
            print(f"Error loading map: {e}")
            placeholder = pygame.Surface((2000, 2000))
            placeholder.fill((40, 40, 40))
            self.map_bg_image = placeholder
            self.map_fg_image = None
            return placeholder

    # ──────────────────────────────────────────────────────
    #  Coordinate helpers
    # ──────────────────────────────────────────────────────
    def _snap(self, x, y):
        sx = round(x / self.grid_size) * self.grid_size
        sy = round(y / self.grid_size) * self.grid_size
        return sx, sy

    def _s2w(self, sx, sy):
        wx = (sx - self.screen_width  / 2) / self.zoom + self.camera_x
        wy = (sy - self.screen_height / 2) / self.zoom + self.camera_y
        return wx, wy

    def _w2s(self, wx, wy):
        sx = (wx - self.camera_x) * self.zoom + self.screen_width  / 2
        sy = (wy - self.camera_y) * self.zoom + self.screen_height / 2
        return sx, sy

    # ──────────────────────────────────────────────────────
    #  Hit-testing
    # ──────────────────────────────────────────────────────
    def _cp_screen_rect(self, cp):
        sx, sy = self._w2s(cp["x"], cp["y"])
        sw = cp["width"]  * self.zoom
        sh = cp["height"] * self.zoom
        return pygame.Rect(int(sx), int(sy), int(sw), int(sh))

    def _cp_corners_screen(self, cp):
        """Returns dict NW/NE/SW/SE → (sx, sy) in screen space."""
        x, y, w, h = cp["x"], cp["y"], cp["width"], cp["height"]
        nw = self._w2s(x,     y    )
        ne = self._w2s(x + w, y    )
        sw = self._w2s(x,     y + h)
        se = self._w2s(x + w, y + h)
        return {"NW": nw, "NE": ne, "SW": sw, "SE": se}

    def _hit_cp_corner(self, mx, my, cp):
        """Returns corner name if (mx,my) is within HANDLE_RADIUS of a corner, else None."""
        corners = self._cp_corners_screen(cp)
        for name, (cx, cy) in corners.items():
            if math.hypot(mx - cx, my - cy) <= HANDLE_RADIUS + 2:
                return name
        return None

    def _hit_cp_body(self, mx, my, cp):
        r = self._cp_screen_rect(cp)
        return r.collidepoint(mx, my)

    def _get_cp_at(self, mx, my):
        """Returns (idx, handle_name) – handle_name is None for body hit."""
        # Reverse order so topmost (last drawn) is hit first
        for i in range(len(self.checkpoints) - 1, -1, -1):
            cp = self.checkpoints[i]
            h = self._hit_cp_corner(mx, my, cp)
            if h:
                return i, h
            if self._hit_cp_body(mx, my, cp):
                return i, None
        return None, None

    def _get_start_at(self, mx, my):
        threshold = START_RADIUS + 4
        for i in range(len(self.starts) - 1, -1, -1):
            s = self.starts[i]
            sx, sy = self._w2s(s["x"], s["y"])
            if math.hypot(mx - sx, my - sy) <= threshold:
                return i
        return None

    # ──────────────────────────────────────────────────────
    #  Data I/O
    # ──────────────────────────────────────────────────────
    def _meta_path(self):
        return asset_path("track", f"map{self.map_num}", "map_meta.json")

    def _load_data(self):
        self.checkpoints = []
        self.starts      = []
        self._lines_raw  = []
        self.sel_cp_idx  = None
        self.sel_st_idx  = None
        self.creating_cp = False
        self.renaming    = False

        path = self._meta_path()
        if not os.path.exists(path):
            print(f"No map_meta.json found at {path}")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.checkpoints = list(data.get("checkpoints", []) or [])
            self.starts      = list(data.get("start", []) or [])
            self._lines_raw  = list(data.get("lines", []) or [])
            print(f"Loaded {len(self.checkpoints)} checkpoint(s), "
                  f"{len(self.starts)} start(s) from map {self.map_num}")
        except Exception as e:
            print(f"Error loading data: {e}")

    def _save_data(self):
        path = self._meta_path()
        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass

        # Re-index IDs to be sequential
        for i, cp in enumerate(self.checkpoints):
            cp["id"] = i
        for i, s in enumerate(self.starts):
            s["id"] = i

        data["checkpoints"] = [
            {"id": cp["id"], "name": cp.get("name", f"cp {cp['id']}"),
             "x": int(cp["x"]), "y": int(cp["y"]),
             "width": int(cp["width"]), "height": int(cp["height"])}
            for cp in self.checkpoints
        ]
        data["start"] = [
            {"id": s["id"], "x": int(s["x"]), "y": int(s["y"]),
             "a": round(float(s["a"]), 4)}
            for s in self.starts
        ]
        # Preserve existing lines (filter to only those whose id still exists)
        valid_ids = {cp["id"] for cp in self.checkpoints}
        data["lines"] = [ln for ln in self._lines_raw if ln.get("id") in valid_ids]

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._format_json(data))
            print(f"Saved {len(self.checkpoints)} checkpoint(s), "
                  f"{len(self.starts)} start(s) to {path}")
            return True
        except Exception as e:
            print(f"Error saving: {e}")
            return False

    def _format_json(self, data, indent=0):
        """Compact-friendly JSON formatter (same style as collision_mesh_editor)."""
        lines = []
        ind = "    " * indent

        if isinstance(data, dict):
            lines.append("{")
            items = list(data.items())
            for i, (key, value) in enumerate(items):
                comma = "," if i < len(items) - 1 else ""
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    lines.append(f'{ind}    "{key}": [')
                    for j, item in enumerate(value):
                        ic = "," if j < len(value) - 1 else ""
                        lines.append(f'{ind}        {json.dumps(item)}{ic}')
                    lines.append(f'{ind}    ]{comma}')
                elif isinstance(value, list) and value and isinstance(value[0], list):
                    if value[0] and isinstance(value[0][0], list):
                        # array of shapes
                        lines.append(f'{ind}    "{key}": [')
                        for j, shape in enumerate(value):
                            sc = "," if j < len(value) - 1 else ""
                            lines.append(f'{ind}        [')
                            for k, v in enumerate(shape):
                                vc = "," if k < len(shape) - 1 else ""
                                lines.append(f'{ind}            {json.dumps(v)}{vc}')
                            lines.append(f'{ind}        ]{sc}')
                        lines.append(f'{ind}    ]{comma}')
                    else:
                        lines.append(f'{ind}    "{key}": [')
                        for j, item in enumerate(value):
                            ic = "," if j < len(value) - 1 else ""
                            lines.append(f'{ind}        {json.dumps(item)}{ic}')
                        lines.append(f'{ind}    ]{comma}')
                elif isinstance(value, (dict, list)):
                    fv = self._format_json(value, indent + 1)
                    lines.append(f'{ind}    "{key}": {fv}{comma}')
                else:
                    lines.append(f'{ind}    "{key}": {json.dumps(value)}{comma}')
            lines.append(f'{ind}}}')
            return "\n".join(lines)

        elif isinstance(data, list):
            if not data:
                return "[]"
            lines.append("[")
            for i, item in enumerate(data):
                comma = "," if i < len(data) - 1 else ""
                if isinstance(item, (dict, list)):
                    fi = self._format_json(item, indent + 1)
                    indented = "\n".join(
                        f'{ind}    {ln}' if j > 0 else ln
                        for j, ln in enumerate(fi.split("\n"))
                    )
                    lines.append(f'{ind}    {indented}{comma}')
                else:
                    lines.append(f'{ind}    {json.dumps(item)}{comma}')
            lines.append(f'{ind}]')
            return "\n".join(lines)

        return json.dumps(data)

    # ──────────────────────────────────────────────────────
    #  Map switching
    # ──────────────────────────────────────────────────────
    def _switch_map(self, delta):
        total = max(1, int(getattr(const, "TOTAL_MAPS", 1)))
        nxt = ((self.map_num - 1 + delta) % total) + 1
        if nxt == self.map_num:
            return
        self.map_num = nxt
        pygame.display.set_caption(f"Checkpoint Editor – Map {self.map_num}")
        self.map_image = self._load_map_image()
        self._load_data()
        print(f"Switched to map {self.map_num}/{total}")

    # ──────────────────────────────────────────────────────
    #  Events
    # ──────────────────────────────────────────────────────
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            # ── Rename text input ─────────────────────────
            elif self.renaming and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
                    if self.sel_cp_idx is not None and self.sel_cp_idx < len(self.checkpoints):
                        self.checkpoints[self.sel_cp_idx]["name"] = self.rename_text
                        print(f"Renamed to '{self.rename_text}'")
                    self.renaming = False
                elif event.key == pygame.K_ESCAPE:
                    self.renaming = False
                elif event.key == pygame.K_BACKSPACE:
                    self.rename_text = self.rename_text[:-1]
                else:
                    if event.unicode and event.unicode.isprintable():
                        self.rename_text += event.unicode
                return  # swallow all events while renaming

            elif event.type == pygame.KEYDOWN:
                self._handle_keydown(event)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                self._handle_mousedown(event)

            elif event.type == pygame.MOUSEBUTTONUP:
                self._handle_mouseup(event)

            elif event.type == pygame.MOUSEMOTION:
                self._handle_mousemotion(event)

    def _handle_keydown(self, event):
        key = event.key
        mods = pygame.key.get_mods()

        if key == pygame.K_ESCAPE:
            self.running = False
        elif key == pygame.K_PAGEUP:
            self._switch_map(-1)
        elif key == pygame.K_PAGEDOWN:
            self._switch_map(1)
        elif key in (pygame.K_1, pygame.K_c):
            self.mode = EDIT_CHECKPOINT
            self.sel_st_idx = None
            print("Mode: Checkpoint editing")
        elif key in (pygame.K_2, pygame.K_t):
            self.mode = EDIT_START
            self.sel_cp_idx = None
            self.creating_cp = False
            print("Mode: Start position editing")
        elif key == pygame.K_g:
            self.show_grid = not self.show_grid
        elif key == pygame.K_f:
            self.show_fg = not self.show_fg
        elif key == pygame.K_s and not (mods & pygame.KMOD_CTRL):
            self._save_data()
        elif key == pygame.K_l:
            self._load_data()
            print("Reloaded data")
        elif key in (pygame.K_RETURN, pygame.K_F2):
            if self.mode == EDIT_CHECKPOINT and self.sel_cp_idx is not None:
                cp = self.checkpoints[self.sel_cp_idx]
                self.rename_text = cp.get("name", "")
                self.renaming = True
        # Start angle rotation
        elif self.mode == EDIT_START and self.sel_st_idx is not None:
            step = ANGLE_STEP_FINE if (mods & pygame.KMOD_SHIFT) else ANGLE_STEP_COARSE
            if key == pygame.K_q:
                self.starts[self.sel_st_idx]["a"] = round(
                    self.starts[self.sel_st_idx]["a"] - step, 6)
            elif key == pygame.K_e:
                self.starts[self.sel_st_idx]["a"] = round(
                    self.starts[self.sel_st_idx]["a"] + step, 6)

    def _handle_mousedown(self, event):
        mx, my = event.pos
        wx, wy = self._s2w(mx, my)

        # Middle mouse → pan
        if event.button == 2:
            self.panning    = True
            self.pan_start_x = mx
            self.pan_start_y = my
            return

        mods = pygame.key.get_mods()

        # ── CHECKPOINT MODE ───────────────────────────────
        if self.mode == EDIT_CHECKPOINT:
            if event.button == 1:
                idx, handle = self._get_cp_at(mx, my)
                if idx is not None:
                    self.sel_cp_idx  = idx
                    self.drag_cp_idx = idx
                    self.drag_handle = handle
                    if handle is None:
                        # Body drag – record offset from top-left
                        cp = self.checkpoints[idx]
                        cpsx, cpsy = self._w2s(cp["x"], cp["y"])
                        self.drag_offset = (mx - cpsx, my - cpsy)
                    self.creating_cp = False
                else:
                    # Begin creating a new rect
                    snx, sny = self._snap(wx, wy)
                    self.creating_cp   = True
                    self.create_start  = (snx, sny)
                    self.create_cur    = (snx, sny)
                    self.sel_cp_idx    = None

            elif event.button == 3:
                idx, _ = self._get_cp_at(mx, my)
                if idx is not None:
                    name = self.checkpoints[idx].get("name", str(idx))
                    del self.checkpoints[idx]
                    if self.sel_cp_idx == idx:
                        self.sel_cp_idx = None
                    elif self.sel_cp_idx is not None and self.sel_cp_idx > idx:
                        self.sel_cp_idx -= 1
                    print(f"Deleted checkpoint '{name}'")

            # Scroll to zoom when not start-selected
            elif event.button == 4:
                self.zoom = min(self.max_zoom, self.zoom * 1.1)
            elif event.button == 5:
                self.zoom = max(self.min_zoom, self.zoom / 1.1)

        # ── START MODE ────────────────────────────────────
        elif self.mode == EDIT_START:
            if event.button == 1:
                idx = self._get_start_at(mx, my)
                if idx is not None:
                    self.sel_st_idx   = idx
                    self.drag_st_idx  = idx
                    s = self.starts[idx]
                    ssx, ssy = self._w2s(s["x"], s["y"])
                    self.drag_st_offset = (mx - ssx, my - ssy)
                else:
                    # Place new start
                    snx, sny = self._snap(wx, wy)
                    new_id = max((s["id"] for s in self.starts), default=-1) + 1
                    self.starts.append({"id": new_id, "x": int(snx), "y": int(sny), "a": 0.0})
                    self.sel_st_idx = len(self.starts) - 1
                    print(f"Placed start {new_id} at ({snx}, {sny})")

            elif event.button == 3:
                idx = self._get_start_at(mx, my)
                if idx is not None:
                    del self.starts[idx]
                    if self.sel_st_idx == idx:
                        self.sel_st_idx = None
                    elif self.sel_st_idx is not None and self.sel_st_idx > idx:
                        self.sel_st_idx -= 1
                    print("Deleted start")

            # Scroll → rotate selected start, else zoom
            elif event.button in (4, 5):
                if self.sel_st_idx is not None and self.sel_st_idx < len(self.starts):
                    mods = pygame.key.get_mods()
                    step = ANGLE_STEP_FINE if (mods & pygame.KMOD_SHIFT) else ANGLE_STEP_COARSE
                    delta = -step if event.button == 4 else step
                    self.starts[self.sel_st_idx]["a"] = round(
                        self.starts[self.sel_st_idx]["a"] + delta, 6)
                else:
                    if event.button == 4:
                        self.zoom = min(self.max_zoom, self.zoom * 1.1)
                    else:
                        self.zoom = max(self.min_zoom, self.zoom / 1.1)

    def _handle_mouseup(self, event):
        if event.button == 2:
            self.panning = False

        elif event.button == 1:
            # Finish checkpoint creation
            if self.mode == EDIT_CHECKPOINT and self.creating_cp:
                if self.create_start and self.create_cur:
                    x0, y0 = self.create_start
                    x1, y1 = self.create_cur
                    rx, ry = min(x0, x1), min(y0, y1)
                    rw, rh = abs(x1 - x0), abs(y1 - y0)
                    if rw >= self.grid_size and rh >= self.grid_size:
                        new_id = max((c["id"] for c in self.checkpoints), default=-1) + 1
                        cp = {"id": new_id, "name": f"cp {new_id}",
                              "x": int(rx), "y": int(ry),
                              "width": int(rw), "height": int(rh)}
                        self.checkpoints.append(cp)
                        self.sel_cp_idx = len(self.checkpoints) - 1
                        print(f"Created checkpoint '{cp['name']}' "
                              f"({rw}×{rh}) at ({rx},{ry})")
                self.creating_cp = False

            self.drag_cp_idx = None
            self.drag_handle = None
            self.drag_st_idx = None

    def _handle_mousemotion(self, event):
        mx, my = event.pos
        wx, wy = self._s2w(mx, my)

        # Pan
        if self.panning:
            dx = (mx - self.pan_start_x) / self.zoom
            dy = (my - self.pan_start_y) / self.zoom
            self.camera_x -= dx
            self.camera_y -= dy
            self.pan_start_x = mx
            self.pan_start_y = my
            return

        # Drag checkpoint body / corner
        if self.drag_cp_idx is not None and self.drag_cp_idx < len(self.checkpoints):
            cp = self.checkpoints[self.drag_cp_idx]
            if self.drag_handle is None:
                # Move body: compute new top-left from drag offset
                tlsx = mx - self.drag_offset[0]
                tlsy = my - self.drag_offset[1]
                tlwx, tlwy = self._s2w(tlsx, tlsy)
                snx, sny = self._snap(tlwx, tlwy)
                cp["x"] = int(snx)
                cp["y"] = int(sny)
            else:
                snx, sny = self._snap(wx, wy)
                h = self.drag_handle
                ox = cp["x"] + cp["width"]   # opposite x
                oy = cp["y"] + cp["height"]  # opposite y
                if h == "NW":
                    cp["x"]     = int(min(snx, ox - self.grid_size))
                    cp["y"]     = int(min(sny, oy - self.grid_size))
                    cp["width"]  = int(ox - cp["x"])
                    cp["height"] = int(oy - cp["y"])
                elif h == "NE":
                    cp["y"]     = int(min(sny, oy - self.grid_size))
                    cp["width"]  = int(max(self.grid_size, int(snx) - cp["x"]))
                    cp["height"] = int(oy - cp["y"])
                elif h == "SW":
                    cp["x"]     = int(min(snx, ox - self.grid_size))
                    cp["width"]  = int(ox - cp["x"])
                    cp["height"] = int(max(self.grid_size, int(sny) - cp["y"]))
                elif h == "SE":
                    cp["width"]  = int(max(self.grid_size, int(snx) - cp["x"]))
                    cp["height"] = int(max(self.grid_size, int(sny) - cp["y"]))
            return

        # Drag start position
        if self.drag_st_idx is not None and self.drag_st_idx < len(self.starts):
            # Back-calculate world pos from screen minus offset
            target_sx = mx - self.drag_st_offset[0]
            target_sy = my - self.drag_st_offset[1]
            twx, twy = self._s2w(target_sx, target_sy)
            snx, sny = self._snap(twx, twy)
            self.starts[self.drag_st_idx]["x"] = int(snx)
            self.starts[self.drag_st_idx]["y"] = int(sny)
            return

        # New checkpoint creation preview
        if self.creating_cp:
            snx, sny = self._snap(wx, wy)
            self.create_cur = (snx, sny)
            return

        # Update hover
        if self.mode == EDIT_CHECKPOINT:
            idx, _ = self._get_cp_at(mx, my)
            self.hover_cp_idx = idx
        elif self.mode == EDIT_START:
            self.hover_st_idx = self._get_start_at(mx, my)

    # ──────────────────────────────────────────────────────
    #  Drawing
    # ──────────────────────────────────────────────────────
    def draw_grid(self):
        if not self.show_grid or self.zoom < 0.5:
            return
        tl = self._s2w(0, 0)
        br = self._s2w(self.screen_width, self.screen_height)
        sx = int(tl[0] / self.grid_size) * self.grid_size
        ex = int(br[0] / self.grid_size + 1) * self.grid_size
        sy = int(tl[1] / self.grid_size) * self.grid_size
        ey = int(br[1] / self.grid_size + 1) * self.grid_size
        gc = (60, 60, 60)
        for x in range(sx, ex + self.grid_size, self.grid_size):
            p1 = self._w2s(x, sy); p2 = self._w2s(x, ey)
            pygame.draw.line(self.screen, gc, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), 1)
        for y in range(sy, ey + self.grid_size, self.grid_size):
            p1 = self._w2s(sx, y); p2 = self._w2s(ex, y)
            pygame.draw.line(self.screen, gc, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), 1)

    def draw_map(self):
        layer_ref = self.map_bg_image if self.map_bg_image is not None else self.map_image
        map_w = layer_ref.get_width()
        map_h = layer_ref.get_height()
        tl = self._s2w(0, 0)
        br = self._s2w(self.screen_width, self.screen_height)
        sl = max(0, int(math.floor(tl[0])))
        st = max(0, int(math.floor(tl[1])))
        sr = min(map_w, int(math.ceil(br[0])))
        sb = min(map_h, int(math.ceil(br[1])))
        if sr <= sl or sb <= st:
            return
        sw, sh = sr - sl, sb - st
        dx, dy = self._w2s(sl, st)
        dw, dh = int(sw * self.zoom), int(sh * self.zoom)
        if dw <= 0 or dh <= 0:
            return

        def _blit(layer):
            if layer is None:
                return
            try:
                sub = layer.subsurface((sl, st, sw, sh)).copy()
            except Exception:
                sub = layer
            scaled = pygame.transform.scale(sub, (dw, dh))
            self.screen.blit(scaled, (int(dx), int(dy)))

        _blit(self.map_bg_image if self.map_bg_image is not None else self.map_image)
        if self.show_fg:
            _blit(self.map_fg_image)

    def draw_checkpoints(self):
        # Draw creation preview
        if self.creating_cp and self.create_start and self.create_cur:
            x0, y0 = self.create_start
            x1, y1 = self.create_cur
            rx, ry = min(x0, x1), min(y0, y1)
            rw, rh = abs(x1 - x0), abs(y1 - y0)
            if rw > 0 and rh > 0:
                psx, psy = self._w2s(rx, ry)
                psw = rw * self.zoom
                psh = rh * self.zoom
                prev_surf = pygame.Surface((int(psw), int(psh)), pygame.SRCALPHA)
                prev_surf.fill((100, 200, 255, 50))
                self.screen.blit(prev_surf, (int(psx), int(psy)))
                pygame.draw.rect(self.screen, (100, 200, 255),
                                 pygame.Rect(int(psx), int(psy), int(psw), int(psh)), 2)

        for i, cp in enumerate(self.checkpoints):
            is_sel  = (i == self.sel_cp_idx)
            is_hov  = (i == self.hover_cp_idx)

            if is_sel:
                fill_col  = (100, 200, 255, 50)
                line_col  = (100, 200, 255)
                handle_col = (50, 255, 50)
            elif is_hov:
                fill_col  = (255, 200, 100, 40)
                line_col  = (255, 200, 100)
                handle_col = (255, 200, 100)
            else:
                fill_col  = (60, 120, 180, 30)
                line_col  = (60, 120, 180)
                handle_col = (60, 120, 180)

            r = self._cp_screen_rect(cp)

            # Filled rect
            fill_surf = pygame.Surface((max(1, r.width), max(1, r.height)), pygame.SRCALPHA)
            fill_surf.fill(fill_col)
            self.screen.blit(fill_surf, (r.x, r.y))
            pygame.draw.rect(self.screen, line_col, r, 2)

            # ID + name label
            if self.zoom > 0.5:
                lbl = self.font.render(
                    f"{cp['id']}: {cp.get('name', '')}", True, (255, 255, 255))
                self.screen.blit(lbl, (r.x + 4, r.y + 4))

            # Corner handles (only when selected or hovered)
            if is_sel or is_hov:
                corners = self._cp_corners_screen(cp)
                for name, (cx, cy) in corners.items():
                    pygame.draw.circle(self.screen, handle_col, (int(cx), int(cy)), HANDLE_RADIUS)
                    pygame.draw.circle(self.screen, (255, 255, 255), (int(cx), int(cy)), HANDLE_RADIUS, 1)

            # Rename indicator
            if is_sel and self.renaming:
                rlbl = self.font.render(f"> {self.rename_text}|", True, (255, 255, 100))
                self.screen.blit(rlbl, (r.x + 4, r.y + r.height + 4))

    def draw_starts(self):
        for i, s in enumerate(self.starts):
            is_sel = (i == self.sel_st_idx)
            is_hov = (i == self.hover_st_idx)

            if is_sel:
                circle_col = (50, 255, 120)
                arrow_col  = (50, 255, 120)
            elif is_hov:
                circle_col = (255, 220, 50)
                arrow_col  = (255, 220, 50)
            else:
                circle_col = (220, 120, 50)
                arrow_col  = (220, 120, 50)

            sx, sy = self._w2s(s["x"], s["y"])
            sx, sy = int(sx), int(sy)
            angle  = s["a"]

            # Body circle
            pygame.draw.circle(self.screen, circle_col, (sx, sy), START_RADIUS)
            pygame.draw.circle(self.screen, (255, 255, 255), (sx, sy), START_RADIUS, 1)

            # Direction arrow
            ax = sx + int(ARROW_LENGTH * math.cos(angle))
            ay = sy - int(ARROW_LENGTH * math.sin(angle))  # y-axis inverted in screen space
            pygame.draw.line(self.screen, arrow_col, (sx, sy), (ax, ay), 2)
            # Arrowhead
            head_angle = math.atan2(sy - ay, ax - sx)
            for d in (-0.4, 0.4):
                hx = ax - int(8 * math.cos(head_angle + d))
                hy = ay + int(8 * math.sin(head_angle + d))
                pygame.draw.line(self.screen, arrow_col, (ax, ay), (hx, hy), 2)

            # ID label
            if self.zoom > 0.4:
                lbl = self.font.render(
                    f"S{s['id']}  a={s['a']:.3f}", True, (255, 255, 255))
                self.screen.blit(lbl, (sx + START_RADIUS + 4, sy - 8))

    def draw_ui(self):
        panel_h = 420
        ui_surf = pygame.Surface((420, panel_h), pygame.SRCALPHA)
        ui_surf.fill((0, 0, 0, 180))
        self.screen.blit(ui_surf, (10, 10))

        mode_name = "CHECKPOINT" if self.mode == EDIT_CHECKPOINT else "START POSITION"
        title = self.font_large.render(
            f"Checkpoint Editor – Map {self.map_num}  [{mode_name}]",
            True, (255, 255, 255))
        self.screen.blit(title, (20, 20))

        y = 50
        lines = [
            "MODE:",
            "  1 / C : Checkpoint mode",
            "  2 / T : Start position mode",
            "",
            "CHECKPOINT MODE:",
            "  LClick drag (empty): Create rect",
            "  LClick (rect body): Move",
            "  LClick (corner): Resize",
            "  RClick: Delete",
            "  Enter / F2: Rename selected",
            "",
            "START MODE:",
            "  LClick (empty): Place start",
            "  LClick (existing): Move",
            "  RClick: Delete",
            "  Q / E: Rotate CCW / CW",
            "  Scroll (selected): Rotate",
            "  Shift: Fine rotation",
            "",
            "SHARED:",
            "  Middle drag / Arrow keys: Pan",
            "  Scroll: Zoom",
            "  G: Grid  F: Foreground",
            "  S: Save  L: Reload",
            "  PageUp/Down: Switch map",
            "  ESC: Exit",
            "",
            f"Checkpoints: {len(self.checkpoints)}",
            f"Starts: {len(self.starts)}",
            f"Map: {self.map_num} / {max(1, int(getattr(const, 'TOTAL_MAPS', 1)))}",
            f"Zoom: {self.zoom:.2f}x",
            f"Grid: {'ON' if self.show_grid else 'OFF'}  FG: {'ON' if self.show_fg else 'OFF'}",
        ]
        for ln in lines:
            col = (200, 200, 200) if ln.startswith("  ") else (255, 255, 255)
            txt = self.font.render(ln, True, col)
            self.screen.blit(txt, (20, y))
            y += 14

        # Snap crosshair at mouse
        mx, my = pygame.mouse.get_pos()
        wx, wy = self._s2w(mx, my)
        snx, sny = self._snap(wx, wy)
        ssx, ssy = self._w2s(snx, sny)
        if not self.panning:
            pygame.draw.circle(self.screen, (255, 255, 0), (int(ssx), int(ssy)), 3, 1)

        # Selected checkpoint info panel (bottom-right)
        if self.mode == EDIT_CHECKPOINT and self.sel_cp_idx is not None \
                and self.sel_cp_idx < len(self.checkpoints):
            cp = self.checkpoints[self.sel_cp_idx]
            info_lines = [
                f"Selected CP #{cp['id']}",
                f"  Name  : {cp.get('name', '')}",
                f"  x,y   : {cp['x']}, {cp['y']}",
                f"  w × h : {cp['width']} × {cp['height']}",
                "  Enter / F2 to rename",
            ]
            if self.renaming:
                info_lines.append(f"  Rename > {self.rename_text}|")
            iw = 260
            ih = len(info_lines) * 18 + 12
            ix = self.screen_width - iw - 10
            iy = self.screen_height - ih - 10
            inf_surf = pygame.Surface((iw, ih), pygame.SRCALPHA)
            inf_surf.fill((0, 0, 0, 200))
            self.screen.blit(inf_surf, (ix, iy))
            for j, il in enumerate(info_lines):
                c = (255, 255, 100) if self.renaming and j == len(info_lines) - 1 else (220, 220, 220)
                t = self.font.render(il, True, c)
                self.screen.blit(t, (ix + 8, iy + 6 + j * 18))

        # Selected start info panel (bottom-right)
        if self.mode == EDIT_START and self.sel_st_idx is not None \
                and self.sel_st_idx < len(self.starts):
            s = self.starts[self.sel_st_idx]
            info_lines = [
                f"Selected Start #{s['id']}",
                f"  x, y  : {s['x']}, {s['y']}",
                f"  angle : {s['a']:.4f} rad  ({math.degrees(s['a']):.1f}°)",
                "  Q/E or Scroll to rotate",
                "  Shift for fine rotation",
            ]
            iw = 280
            ih = len(info_lines) * 18 + 12
            ix = self.screen_width - iw - 10
            iy = self.screen_height - ih - 10
            inf_surf = pygame.Surface((iw, ih), pygame.SRCALPHA)
            inf_surf.fill((0, 0, 0, 200))
            self.screen.blit(inf_surf, (ix, iy))
            for j, il in enumerate(info_lines):
                t = self.font.render(il, True, (220, 220, 220))
                self.screen.blit(t, (ix + 8, iy + 6 + j * 18))

    # ──────────────────────────────────────────────────────
    #  Main loop
    # ──────────────────────────────────────────────────────
    def run(self):
        print("\n" + "=" * 60)
        print("Checkpoint Editor Started")
        print("=" * 60)
        print("1/C → Checkpoint mode | 2/T → Start mode")
        print("S → Save | L → Reload | ESC → Exit")
        print("=" * 60 + "\n")

        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self.handle_events()

            # Arrow-key panning
            keys = pygame.key.get_pressed()
            spd = self.pan_key_speed * dt / max(self.zoom, 1e-4)
            if keys[pygame.K_LEFT]:  self.camera_x -= spd
            if keys[pygame.K_RIGHT]: self.camera_x += spd
            if keys[pygame.K_UP]:    self.camera_y -= spd
            if keys[pygame.K_DOWN]:  self.camera_y += spd

            self.screen.fill((30, 30, 30))
            self.draw_grid()
            self.draw_map()
            self.draw_checkpoints()
            self.draw_starts()
            self.draw_ui()
            pygame.display.flip()

        pygame.quit()
        print("\nCheckpoint Editor Closed")


# ──────────────────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Checkpoint Editor for Drift Race")
    parser.add_argument("--map", type=int, default=1, help="Map number to edit (default: 1)")
    args = parser.parse_args()
    CheckpointEditor(map_num=args.map).run()


if __name__ == "__main__":
    main()
