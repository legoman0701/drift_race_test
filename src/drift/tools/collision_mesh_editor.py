#!/usr/bin/env python3
"""
Collision Mesh Editor - Visual tool for creating collision meshes for drift race tracks

Usage:
    python -m drift.tools.collision_mesh_editor [--map MAP_NUM]
    
Controls:
    Left Mouse: Place/Move vertex
    Right Mouse: Delete vertex
    Middle Mouse + Drag: Pan the map
    Mouse Wheel: Zoom in/out
    G: Toggle grid visibility
    S: Save collision mesh
    L: Load collision mesh
    C: Clear current shape
    M: Toggle edit mode (collision mesh / drift zones)
    N: New shape
    TAB: Switch to next shape
    SHIFT+TAB: Switch to previous shape
    DELETE/BACKSPACE: Delete current shape
    ESC: Exit editor
"""

import pygame
import sys
import json
import os
import math
from pathlib import Path

# Import from drift module
try:
    import drift.config.const as const
    from drift.tools.paths import asset_path, normalize_asset_path
except ImportError:
    print("Error: Could not import drift modules. Make sure you're running from the project root.")
    sys.exit(1)


class CollisionMeshEditor:
    def __init__(self, map_num=1):
        pygame.init()
        
        # Window setup
        self.screen_width = 1400
        self.screen_height = 900
        self.screen = pygame.display.set_mode((self.screen_width, self.screen_height))
        pygame.display.set_caption(f"Collision Mesh Editor - Map {map_num}")
        
        # Map setup
        self.map_num = map_num
        self.map_image = self._load_map_image()
        
        # Camera/viewport
        self.camera_x = 0
        self.camera_y = 0
        self.zoom = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 4.0
        
        # Grid settings
        self.grid_size = 5  # 5x5 pixel grid
        self.show_grid = True
        
        # Panning
        self.panning = False
        self.pan_start_x = 0
        self.pan_start_y = 0
        # Arrow-key panning speed (world units per second)
        self.pan_key_speed = 500
        
        # Two independent editable datasets in world coordinates.
        # Mode values: "collision" and "drift_zones"
        self.mode = "collision"
        self.mode_data = {
            "collision": {
                "shapes": [[]],
                "current_shape": 0,
                "selected_vertex": None,
                "hover_vertex": None,
            },
            "drift_zones": {
                "shapes": [[]],
                "current_shape": 0,
                "selected_vertex": None,
                "hover_vertex": None,
            },
        }
        
        # UI colors
        self.bg_color = (30, 30, 30)
        self.grid_color = (60, 60, 60)
        self.vertex_color = (255, 50, 50)
        self.vertex_hover_color = (255, 150, 50)
        self.vertex_selected_color = (50, 255, 50)
        self.line_color = (100, 200, 255)
        self.inactive_vertex_color = (120, 50, 50)
        self.inactive_line_color = (60, 100, 120)
        self.drift_line_color = (255, 170, 70)
        self.drift_vertex_color = (255, 120, 70)
        self.drift_hover_color = (255, 210, 120)
        self.drift_selected_color = (255, 240, 140)
        self.drift_inactive_vertex_color = (120, 80, 50)
        self.drift_inactive_line_color = (140, 100, 60)
        self.snap_indicator_color = (255, 255, 0)
        
        # UI state
        self.dragging_vertex = False
        self.clock = pygame.time.Clock()
        self.running = True
        
        # Load existing mesh if available
        self._load_collision_mesh()
        
        # Font for UI
        self.font = pygame.font.SysFont("Arial", 14)
        self.font_large = pygame.font.SysFont("Arial", 18)
        
    def _load_map_image(self):
        """Load the track map image"""
        try:
            map_path = normalize_asset_path("track", f"map{self.map_num}", "main.png")
            image = pygame.image.load(map_path).convert()
            print(f"Loaded map: {map_path} ({image.get_width()}x{image.get_height()})")
            return image
        except Exception as e:
            print(f"Error loading map: {e}")
            # Create a placeholder image
            placeholder = pygame.Surface((2000, 2000))
            placeholder.fill((40, 40, 40))
            return placeholder
    
    def _snap_to_grid(self, x, y):
        """Snap coordinates to the nearest grid point"""
        snapped_x = round(x / self.grid_size) * self.grid_size
        snapped_y = round(y / self.grid_size) * self.grid_size
        return snapped_x, snapped_y
    
    def _screen_to_world(self, screen_x, screen_y):
        """Convert screen coordinates to world coordinates"""
        world_x = (screen_x - self.screen_width / 2) / self.zoom + self.camera_x
        world_y = (screen_y - self.screen_height / 2) / self.zoom + self.camera_y
        return world_x, world_y
    
    def _world_to_screen(self, world_x, world_y):
        """Convert world coordinates to screen coordinates"""
        screen_x = (world_x - self.camera_x) * self.zoom + self.screen_width / 2
        screen_y = (world_y - self.camera_y) * self.zoom + self.screen_height / 2
        return screen_x, screen_y
    
    def _get_vertex_at_position(self, world_x, world_y, threshold=10):
        """Find vertex near the given position in current shape (returns index or None)"""
        state = self.mode_data[self.mode]
        shapes = state["shapes"]
        cur = state["current_shape"]
        if cur >= len(shapes):
            return None
        
        threshold_world = threshold / self.zoom
        vertices = shapes[cur]
        for i, (vx, vy) in enumerate(vertices):
            dist = math.sqrt((vx - world_x)**2 + (vy - world_y)**2)
            if dist < threshold_world:
                return i
        return None

    def _sanitize_mode_shapes(self):
        """Ensure each edit mode has at least one shape and valid indices."""
        for mode_key in ("collision", "drift_zones"):
            state = self.mode_data[mode_key]
            if not state["shapes"]:
                state["shapes"] = [[]]
            state["current_shape"] = min(state["current_shape"], len(state["shapes"]) - 1)
            if state["current_shape"] < 0:
                state["current_shape"] = 0
            sel = state["selected_vertex"]
            if sel is not None and sel >= len(state["shapes"][state["current_shape"]]):
                state["selected_vertex"] = None

    def _toggle_mode(self):
        self.mode = "drift_zones" if self.mode == "collision" else "collision"
        self._sanitize_mode_shapes()
        print(f"Mode: {'Collision Mesh' if self.mode == 'collision' else 'Drift Zones'}")

    def _active_colors(self):
        if self.mode == "collision":
            return {
                "line": self.line_color,
                "vertex": self.vertex_color,
                "hover": self.vertex_hover_color,
                "selected": self.vertex_selected_color,
                "inactive_line": self.inactive_line_color,
                "inactive_vertex": self.inactive_vertex_color,
            }
        return {
            "line": self.drift_line_color,
            "vertex": self.drift_vertex_color,
            "hover": self.drift_hover_color,
            "selected": self.drift_selected_color,
            "inactive_line": self.drift_inactive_line_color,
            "inactive_vertex": self.drift_inactive_vertex_color,
        }
    
    def _load_collision_mesh(self):
        """Load collision mesh and drift zones from map_meta.json"""
        try:
            meta_path = asset_path("track", f"map{self.map_num}", "map_meta.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    def parse_shapes(mesh_data):
                        # Support both old format (single shape) and new format (multiple shapes)
                        if not mesh_data:
                            return [[]]
                        if isinstance(mesh_data[0][0], list):
                            return [[tuple(v) for v in shape] for shape in mesh_data]
                        return [[tuple(v) for v in mesh_data]]

                    if "collision_mesh" in data:
                        self.mode_data["collision"]["shapes"] = parse_shapes(data["collision_mesh"])
                    if "drift_zones" in data:
                        self.mode_data["drift_zones"]["shapes"] = parse_shapes(data["drift_zones"])

                    self._sanitize_mode_shapes()
                    c_shapes = self.mode_data["collision"]["shapes"]
                    d_shapes = self.mode_data["drift_zones"]["shapes"]
                    c_vertices = sum(len(shape) for shape in c_shapes)
                    d_vertices = sum(len(shape) for shape in d_shapes)
                    print(
                        f"Loaded collision={len(c_shapes)} shape(s), {c_vertices} vertices | "
                        f"drift_zones={len(d_shapes)} shape(s), {d_vertices} vertices"
                    )
        except Exception as e:
            print(f"Error loading collision mesh: {e}")
            self.mode_data["collision"]["shapes"] = [[]]
            self.mode_data["drift_zones"]["shapes"] = [[]]
            self._sanitize_mode_shapes()
    
    def _save_collision_mesh(self):
        """Save collision mesh and drift zones to map_meta.json"""
        try:
            meta_path = asset_path("track", f"map{self.map_num}", "map_meta.json")
            
            # Load existing metadata or create new
            data = {}
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            
            # Update collision mesh and drift zones - convert to list of shapes
            non_empty_collision = [shape for shape in self.mode_data["collision"]["shapes"] if len(shape) > 0]
            non_empty_drift = [shape for shape in self.mode_data["drift_zones"]["shapes"] if len(shape) > 0]

            data["collision_mesh"] = [[[int(x), int(y)] for x, y in shape] for shape in non_empty_collision]
            data["drift_zones"] = [[[int(x), int(y)] for x, y in shape] for shape in non_empty_drift]
            
            # Save with custom formatting (compact objects in arrays)
            with open(meta_path, "w", encoding="utf-8") as f:
                f.write(self._format_json(data))
            
            c_vertices = sum(len(shape) for shape in non_empty_collision)
            d_vertices = sum(len(shape) for shape in non_empty_drift)
            print(
                f"Saved collision={len(non_empty_collision)} shape(s), {c_vertices} vertices | "
                f"drift_zones={len(non_empty_drift)} shape(s), {d_vertices} vertices -> {meta_path}"
            )
            return True
        except Exception as e:
            print(f"Error saving collision mesh: {e}")
            return False
    
    def _format_json(self, data, indent=0):
        """Format JSON with compact arrays of objects"""
        lines = []
        indent_str = "    " * indent
        
        if isinstance(data, dict):
            lines.append("{")
            items = list(data.items())
            for i, (key, value) in enumerate(items):
                comma = "," if i < len(items) - 1 else ""
                
                if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                    # Array of objects - format each object on one line
                    lines.append(f'{indent_str}    "{key}": [')
                    for j, item in enumerate(value):
                        item_comma = "," if j < len(value) - 1 else ""
                        lines.append(f'{indent_str}        {json.dumps(item)}{item_comma}')
                    lines.append(f'{indent_str}    ]{comma}')
                elif isinstance(value, list) and len(value) > 0 and isinstance(value[0], list):
                    # Check if it's array of arrays (collision mesh shapes)
                    if len(value[0]) > 0 and isinstance(value[0][0], list):
                        # Array of shapes (array of arrays of arrays)
                        lines.append(f'{indent_str}    "{key}": [')
                        for j, shape in enumerate(value):
                            shape_comma = "," if j < len(value) - 1 else ""
                            lines.append(f'{indent_str}        [')
                            for k, vertex in enumerate(shape):
                                vertex_comma = "," if k < len(shape) - 1 else ""
                                lines.append(f'{indent_str}            {json.dumps(vertex)}{vertex_comma}')
                            lines.append(f'{indent_str}        ]{shape_comma}')
                        lines.append(f'{indent_str}    ]{comma}')
                    else:
                        # Array of arrays - format each sub-array on one line
                        lines.append(f'{indent_str}    "{key}": [')
                        for j, item in enumerate(value):
                            item_comma = "," if j < len(value) - 1 else ""
                            lines.append(f'{indent_str}        {json.dumps(item)}{item_comma}')
                        lines.append(f'{indent_str}    ]{comma}')
                elif isinstance(value, (dict, list)):
                    # Nested structure - recurse
                    formatted_value = self._format_json(value, indent + 1)
                    lines.append(f'{indent_str}    "{key}": {formatted_value}{comma}')
                else:
                    # Simple value
                    lines.append(f'{indent_str}    "{key}": {json.dumps(value)}{comma}')
            lines.append(f'{indent_str}}}')
            return "\n".join(lines)
        
        elif isinstance(data, list):
            if len(data) == 0:
                return "[]"
            lines.append("[")
            for i, item in enumerate(data):
                comma = "," if i < len(data) - 1 else ""
                if isinstance(item, (dict, list)):
                    formatted_item = self._format_json(item, indent + 1)
                    # Add proper indentation for nested items
                    indented_item = "\n".join(f'{indent_str}    {line}' if j > 0 else line 
                                             for j, line in enumerate(formatted_item.split("\n")))
                    lines.append(f'{indent_str}    {indented_item}{comma}')
                else:
                    lines.append(f'{indent_str}    {json.dumps(item)}{comma}')
            lines.append(f'{indent_str}]')
            return "\n".join(lines)
        
        else:
            return json.dumps(data)
    
    def handle_events(self):
        """Handle pygame events"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            
            elif event.type == pygame.KEYDOWN:
                state = self.mode_data[self.mode]
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_g:
                    self.show_grid = not self.show_grid
                    print(f"Grid: {'ON' if self.show_grid else 'OFF'}")
                elif event.key == pygame.K_s:
                    if self._save_collision_mesh():
                        print("Collision mesh saved successfully!")
                elif event.key == pygame.K_l:
                    self._load_collision_mesh()
                    print("Collision mesh reloaded")
                elif event.key == pygame.K_m:
                    self._toggle_mode()
                elif event.key == pygame.K_c:
                    state["shapes"][state["current_shape"]].clear()
                    state["selected_vertex"] = None
                    print(f"Cleared all vertices in {self.mode} shape {state['current_shape']}")
                elif event.key == pygame.K_n:
                    # Create new shape
                    state["shapes"].append([])
                    state["current_shape"] = len(state["shapes"]) - 1
                    state["selected_vertex"] = None
                    print(f"Created new {self.mode} shape {state['current_shape']}")
                elif event.key == pygame.K_TAB:
                    # Switch between shapes
                    if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                        # Shift+Tab: previous shape
                        state["current_shape"] = (state["current_shape"] - 1) % len(state["shapes"])
                    else:
                        # Tab: next shape
                        state["current_shape"] = (state["current_shape"] + 1) % len(state["shapes"])
                    state["selected_vertex"] = None
                    print(f"Switched to {self.mode} shape {state['current_shape']}")
                elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
                    # Delete current shape
                    if len(state["shapes"]) > 1:
                        deleted_idx = state["current_shape"]
                        state["shapes"].pop(state["current_shape"])
                        state["current_shape"] = min(state["current_shape"], len(state["shapes"]) - 1)
                        state["selected_vertex"] = None
                        print(f"Deleted {self.mode} shape {deleted_idx}, now on shape {state['current_shape']}")
                    else:
                        print("Cannot delete the last shape")
            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mouse_x, mouse_y = event.pos
                world_x, world_y = self._screen_to_world(mouse_x, mouse_y)
                
                # Middle mouse button - start panning
                if event.button == 2:
                    self.panning = True
                    self.pan_start_x = mouse_x
                    self.pan_start_y = mouse_y
                
                # Left mouse button - place or select vertex
                elif event.button == 1:
                    state = self.mode_data[self.mode]
                    vertex_idx = self._get_vertex_at_position(world_x, world_y)
                    if vertex_idx is not None:
                        # Select and start dragging existing vertex
                        state["selected_vertex"] = vertex_idx
                        self.dragging_vertex = True
                    else:
                        # Place new vertex in current shape
                        snapped_x, snapped_y = self._snap_to_grid(world_x, world_y)
                        state["shapes"][state["current_shape"]].append((snapped_x, snapped_y))
                        state["selected_vertex"] = len(state["shapes"][state["current_shape"]]) - 1
                        print(f"Placed vertex at ({snapped_x}, {snapped_y}) in {self.mode} shape {state['current_shape']}")
                
                # Right mouse button - delete vertex
                elif event.button == 3:
                    state = self.mode_data[self.mode]
                    vertex_idx = self._get_vertex_at_position(world_x, world_y)
                    if vertex_idx is not None:
                        state["shapes"][state["current_shape"]].pop(vertex_idx)
                        if state["selected_vertex"] == vertex_idx:
                            state["selected_vertex"] = None
                        elif state["selected_vertex"] is not None and state["selected_vertex"] > vertex_idx:
                            state["selected_vertex"] -= 1
                        print(f"Deleted vertex from {self.mode} shape {state['current_shape']}")
                
                # Mouse wheel - zoom
                elif event.button == 4:  # Scroll up
                    self.zoom = min(self.max_zoom, self.zoom * 1.1)
                elif event.button == 5:  # Scroll down
                    self.zoom = max(self.min_zoom, self.zoom / 1.1)
            
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 2:
                    self.panning = False
                elif event.button == 1:
                    self.dragging_vertex = False
            
            elif event.type == pygame.MOUSEMOTION:
                mouse_x, mouse_y = event.pos
                
                # Panning
                if self.panning:
                    dx = (mouse_x - self.pan_start_x) / self.zoom
                    dy = (mouse_y - self.pan_start_y) / self.zoom
                    self.camera_x -= dx
                    self.camera_y -= dy
                    self.pan_start_x = mouse_x
                    self.pan_start_y = mouse_y
                
                # Dragging vertex
                elif self.dragging_vertex and self.mode_data[self.mode]["selected_vertex"] is not None:
                    state = self.mode_data[self.mode]
                    world_x, world_y = self._screen_to_world(mouse_x, mouse_y)
                    snapped_x, snapped_y = self._snap_to_grid(world_x, world_y)
                    state["shapes"][state["current_shape"]][state["selected_vertex"]] = (snapped_x, snapped_y)
                
                # Update hover state
                else:
                    world_x, world_y = self._screen_to_world(mouse_x, mouse_y)
                    self.mode_data[self.mode]["hover_vertex"] = self._get_vertex_at_position(world_x, world_y)
    
    def draw_grid(self):
        """Draw the background grid"""
        if not self.show_grid or self.zoom < 0.5:
            return
        
        # Calculate visible world bounds
        top_left_world = self._screen_to_world(0, 0)
        bottom_right_world = self._screen_to_world(self.screen_width, self.screen_height)
        
        # Calculate grid line positions
        start_x = int(top_left_world[0] / self.grid_size) * self.grid_size
        end_x = int(bottom_right_world[0] / self.grid_size + 1) * self.grid_size
        start_y = int(top_left_world[1] / self.grid_size) * self.grid_size
        end_y = int(bottom_right_world[1] / self.grid_size + 1) * self.grid_size
        
        # Draw vertical lines
        for x in range(start_x, end_x + self.grid_size, self.grid_size):
            screen_x1, screen_y1 = self._world_to_screen(x, start_y)
            screen_x2, screen_y2 = self._world_to_screen(x, end_y)
            pygame.draw.line(self.screen, self.grid_color, 
                           (screen_x1, screen_y1), (screen_x2, screen_y2), 1)
        
        # Draw horizontal lines
        for y in range(start_y, end_y + self.grid_size, self.grid_size):
            screen_x1, screen_y1 = self._world_to_screen(start_x, y)
            screen_x2, screen_y2 = self._world_to_screen(end_x, y)
            pygame.draw.line(self.screen, self.grid_color,
                           (screen_x1, screen_y1), (screen_x2, screen_y2), 1)
    
    def draw_map(self):
        """Draw the track map"""
        # Only draw the visible portion of the map to avoid costly full-image scaling
        map_w = self.map_image.get_width()
        map_h = self.map_image.get_height()

        # Visible world bounds (top-left and bottom-right)
        top_left_world = self._screen_to_world(0, 0)
        bottom_right_world = self._screen_to_world(self.screen_width, self.screen_height)

        # Compute intersection of visible area with the map bounds (in world/pixel coords)
        src_left = max(0, int(math.floor(top_left_world[0])))
        src_top = max(0, int(math.floor(top_left_world[1])))
        src_right = min(map_w, int(math.ceil(bottom_right_world[0])))
        src_bottom = min(map_h, int(math.ceil(bottom_right_world[1])))

        # If nothing of the map is visible, skip drawing
        if src_right <= src_left or src_bottom <= src_top:
            return

        src_w = src_right - src_left
        src_h = src_bottom - src_top

        # Extract the visible subimage and scale only that portion to the destination size
        try:
            sub = self.map_image.subsurface((src_left, src_top, src_w, src_h)).copy()
        except Exception:
            # Fallback to full image if subsurface isn't available for some surface types
            sub = self.map_image
            src_left, src_top, src_w, src_h = 0, 0, map_w, map_h

        dest_x, dest_y = self._world_to_screen(src_left, src_top)
        dest_w = int(src_w * self.zoom)
        dest_h = int(src_h * self.zoom)

        if dest_w <= 0 or dest_h <= 0:
            return

        scaled = pygame.transform.scale(sub, (dest_w, dest_h))
        self.screen.blit(scaled, (int(dest_x), int(dest_y)))
    
    def draw_collision_mesh(self):
        """Draw vertices and lines for the active mode and muted inactive mode."""
        active_state = self.mode_data[self.mode]
        inactive_mode = "drift_zones" if self.mode == "collision" else "collision"
        inactive_state = self.mode_data[inactive_mode]

        active_colors = self._active_colors()
        inactive_colors = {
            "line": active_colors["inactive_line"],
            "vertex": active_colors["inactive_vertex"],
            "hover": active_colors["inactive_vertex"],
            "selected": active_colors["inactive_vertex"],
        }

        def draw_set(state, colors, is_active):
            shapes = state["shapes"]
            current_shape = state["current_shape"]
            selected_vertex = state["selected_vertex"]
            hover_vertex = state["hover_vertex"]

            for shape_idx, vertices in enumerate(shapes):
                if len(vertices) == 0:
                    continue

                shape_is_current = is_active and (shape_idx == current_shape)

                line_color = colors["line"] if shape_is_current else colors["line"]
                vertex_color = colors["vertex"]
                vertex_hover_color = colors["hover"]
                vertex_selected_color = colors["selected"]

                if len(vertices) > 1:
                    screen_points = []
                    for vx, vy in vertices:
                        sx, sy = self._world_to_screen(vx, vy)
                        screen_points.append((sx, sy))

                    for i in range(len(screen_points)):
                        p1 = screen_points[i]
                        p2 = screen_points[(i + 1) % len(screen_points)]
                        width = 2 if shape_is_current else 1
                        pygame.draw.line(self.screen, line_color, p1, p2, width)

                for i, (vx, vy) in enumerate(vertices):
                    sx, sy = self._world_to_screen(vx, vy)

                    if shape_is_current:
                        if i == selected_vertex:
                            color = vertex_selected_color
                            radius = 8
                        elif i == hover_vertex:
                            color = vertex_hover_color
                            radius = 7
                        else:
                            color = vertex_color
                            radius = 6
                    else:
                        color = vertex_color
                        radius = 4

                    pygame.draw.circle(self.screen, color, (int(sx), int(sy)), radius)
                    if shape_is_current:
                        pygame.draw.circle(self.screen, (255, 255, 255), (int(sx), int(sy)), radius, 1)

                    if shape_is_current and self.zoom > 0.8:
                        text = self.font.render(str(i), True, (255, 255, 255))
                        self.screen.blit(text, (int(sx) + 10, int(sy) - 10))

        draw_set(inactive_state, inactive_colors, is_active=False)
        draw_set(active_state, active_colors, is_active=True)
    
    def draw_ui(self):
        """Draw UI overlay with controls and info"""
        active_state = self.mode_data[self.mode]
        collision_shapes = self.mode_data["collision"]["shapes"]
        drift_shapes = self.mode_data["drift_zones"]["shapes"]
        mode_name = "Collision Mesh" if self.mode == "collision" else "Drift Zones"

        # Semi-transparent background for text
        ui_surface = pygame.Surface((430, 390), pygame.SRCALPHA)
        ui_surface.fill((0, 0, 0, 180))
        self.screen.blit(ui_surface, (10, 10))
        
        # Title
        title = self.font_large.render(f"Collision Mesh Editor - Map {self.map_num}", True, (255, 255, 255))
        self.screen.blit(title, (20, 20))
        
        # Controls
        y_offset = 50
        controls = [
            "CONTROLS:",
            "Left Click: Place/Move vertex",
            "Right Click: Delete vertex",
            "Middle Click + Drag: Pan map",
            "Arrow Keys: Pan map",
            "Mouse Wheel: Zoom",
            "",
            "KEYBOARD:",
            "G: Toggle grid",
            "S: Save map meta",
            "L: Load map meta",
            "C: Clear current shape",
            "M: Toggle mode (collision/drift)",
            "N: New shape",
            "TAB: Next shape",
            "SHIFT+TAB: Previous shape",
            "DELETE/BACKSPACE: Delete shape",
            "ESC: Exit",
            "",
            f"Edit Mode: {mode_name}",
            f"Current Shape: {active_state['current_shape']} / {len(active_state['shapes']) - 1}",
            f"Vertices in shape: {len(active_state['shapes'][active_state['current_shape']])}",
            f"Total shapes (mode): {len(active_state['shapes'])}",
            f"Collision shapes: {len(collision_shapes)}",
            f"Drift zone shapes: {len(drift_shapes)}",
            f"Zoom: {self.zoom:.2f}x",
            f"Grid: {self.grid_size}px ({'ON' if self.show_grid else 'OFF'})",
        ]
        
        for line in controls:
            text = self.font.render(line, True, (200, 200, 200) if line.startswith(" ") else (255, 255, 255))
            self.screen.blit(text, (20, y_offset))
            y_offset += 16
        
        # Draw snap indicator at mouse position
        mouse_x, mouse_y = pygame.mouse.get_pos()
        world_x, world_y = self._screen_to_world(mouse_x, mouse_y)
        snapped_x, snapped_y = self._snap_to_grid(world_x, world_y)
        snap_screen_x, snap_screen_y = self._world_to_screen(snapped_x, snapped_y)
        
        if not self.panning and self.mode_data[self.mode]["hover_vertex"] is None:
            pygame.draw.circle(self.screen, self.snap_indicator_color, 
                             (int(snap_screen_x), int(snap_screen_y)), 3, 1)
    
    def run(self):
        """Main editor loop"""
        print("\n" + "="*60)
        print("Collision Mesh Editor Started")
        print("="*60)
        print("Use Left Click to place vertices")
        print("Use Right Click to delete vertices")
        print("Use Middle Click + Drag to pan")
        print("Press M to switch between collision mesh and drift zone drawing")
        print("Press N to create new shape, TAB to switch shapes")
        print("Press S to save, L to load, C to clear, ESC to exit")
        print("="*60 + "\n")
        
        while self.running:
            # Cap frame rate and get delta time
            dt = self.clock.tick(60) / 1000.0

            self.handle_events()

            # Arrow-key panning (continuous while held)
            keys = pygame.key.get_pressed()
            if keys[pygame.K_LEFT]:
                self.camera_x -= (self.pan_key_speed * dt) / max(self.zoom, 0.0001)
            if keys[pygame.K_RIGHT]:
                self.camera_x += (self.pan_key_speed * dt) / max(self.zoom, 0.0001)
            if keys[pygame.K_UP]:
                self.camera_y -= (self.pan_key_speed * dt) / max(self.zoom, 0.0001)
            if keys[pygame.K_DOWN]:
                self.camera_y += (self.pan_key_speed * dt) / max(self.zoom, 0.0001)

            # Clear screen
            self.screen.fill(self.bg_color)

            # Draw everything
            self.draw_grid()
            self.draw_map()
            self.draw_collision_mesh()
            self.draw_ui()

            # Update display
            pygame.display.flip()
        
        # Cleanup
        pygame.quit()
        print("\nCollision Mesh Editor Closed")


def main():
    """Entry point for the collision mesh editor"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Collision Mesh Editor for Drift Race")
    parser.add_argument("--map", type=int, default=1, help="Map number to edit (default: 1)")
    args = parser.parse_args()
    
    editor = CollisionMeshEditor(map_num=args.map)
    editor.run()


if __name__ == "__main__":
    main()
