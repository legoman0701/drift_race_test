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

# Import from drift module
try:
    import drift.config.const as const
    from drift.tools.paths import asset_path, get_track_base_image_path
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
        
        # Collision mesh - multiple shapes (world coordinates)
        self.shapes = [[]]  # List of shapes, each shape is a list of (x, y) tuples
        self.current_shape = 0  # Index of currently active shape
        self.selected_vertex = None  # Index of currently selected vertex
        self.hover_vertex = None  # Index of vertex under mouse
        
        # UI colors
        self.bg_color = (30, 30, 30)
        self.grid_color = (60, 60, 60)
        self.vertex_color = (255, 50, 50)
        self.vertex_hover_color = (255, 150, 50)
        self.vertex_selected_color = (50, 255, 50)
        self.line_color = (100, 200, 255)
        self.inactive_vertex_color = (120, 50, 50)
        self.inactive_line_color = (60, 100, 120)
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

    def _switch_map(self, delta):
        """Switch to previous/next map number and reload image + mesh."""
        total_maps = max(1, int(getattr(const, "TOTAL_MAPS", 1)))
        next_map = ((self.map_num - 1 + delta) % total_maps) + 1
        if next_map == self.map_num:
            return

        self.map_num = next_map
        pygame.display.set_caption(f"Collision Mesh Editor - Map {self.map_num}")
        self.map_image = self._load_map_image()
        self._load_collision_mesh()
        self.selected_vertex = None
        self.hover_vertex = None
        self.dragging_vertex = False
        print(f"Switched to map {self.map_num}/{total_maps}")
        
    def _load_map_image(self):
        """Load and compose track layers for editing (bg + fg when available)."""
        try:
            map_key = f"map{self.map_num}"
            bg_path = asset_path("track", map_key, "main_bg.png")
            fg_path = asset_path("track", map_key, "main_fg.png")

            bg_img = pygame.image.load(bg_path).convert_alpha() if os.path.exists(bg_path) else None
            fg_img = pygame.image.load(fg_path).convert_alpha() if os.path.exists(fg_path) else None

            if bg_img is not None or fg_img is not None:
                # Compose visible layers into one preview image.
                ref = bg_img if bg_img is not None else fg_img
                width, height = ref.get_width(), ref.get_height()
                image = pygame.Surface((width, height), pygame.SRCALPHA)
                if bg_img is not None:
                    image.blit(bg_img, (0, 0))
                if fg_img is not None:
                    image.blit(fg_img, (0, 0))
                image = image.convert_alpha()
                loaded_layers = []
                if bg_img is not None:
                    loaded_layers.append("main_bg.png")
                if fg_img is not None:
                    loaded_layers.append("main_fg.png")
                print(f"Loaded map layers: {', '.join(loaded_layers)} ({width}x{height})")
                return image

            # Fallback to main image when layered files are absent.
            map_path = get_track_base_image_path(map_key)
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
        if self.current_shape >= len(self.shapes):
            return None
        
        threshold_world = threshold / self.zoom
        vertices = self.shapes[self.current_shape]
        for i, (vx, vy) in enumerate(vertices):
            dist = math.sqrt((vx - world_x)**2 + (vy - world_y)**2)
            if dist < threshold_world:
                return i
        return None
    
    def _load_collision_mesh(self):
        """Load collision mesh from map_meta.json"""
        # Reset first so maps without collision_mesh do not keep previous data
        self.shapes = [[]]
        self.current_shape = 0
        self.selected_vertex = None

        try:
            meta_path = asset_path("track", f"map{self.map_num}", "map_meta.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "collision_mesh" in data:
                        mesh_data = data["collision_mesh"]
                        # Support both old format (single shape) and new format (multiple shapes)
                        if mesh_data and len(mesh_data) > 0:
                            if isinstance(mesh_data[0][0], list):
                                # New format: array of shapes
                                self.shapes = [[tuple(v) for v in shape] for shape in mesh_data]
                            else:
                                # Old format: single shape (array of vertices)
                                self.shapes = [[tuple(v) for v in mesh_data]]
                        
                        if not self.shapes:
                            self.shapes = [[]]
                        
                        total_vertices = sum(len(shape) for shape in self.shapes)
                        print(f"Loaded {len(self.shapes)} shape(s) with {total_vertices} total vertices")
        except Exception as e:
            print(f"Error loading collision mesh: {e}")
            self.shapes = [[]]
    
    def _save_collision_mesh(self):
        """Save collision mesh to map_meta.json"""
        try:
            meta_path = asset_path("track", f"map{self.map_num}", "map_meta.json")
            
            # Load existing metadata or create new
            data = {}
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            
            # Update collision mesh - convert to list of shapes
            # Filter out empty shapes
            non_empty_shapes = [shape for shape in self.shapes if len(shape) > 0]
            data["collision_mesh"] = [[[int(x), int(y)] for x, y in shape] for shape in non_empty_shapes]
            
            # Save with custom formatting (compact objects in arrays)
            with open(meta_path, "w", encoding="utf-8") as f:
                f.write(self._format_json(data))
            
            total_vertices = sum(len(shape) for shape in non_empty_shapes)
            print(f"Saved {len(non_empty_shapes)} shape(s) with {total_vertices} total vertices to {meta_path}")
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
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_PAGEUP:
                    self._switch_map(-1)
                elif event.key == pygame.K_PAGEDOWN:
                    self._switch_map(1)
                elif event.key == pygame.K_g:
                    self.show_grid = not self.show_grid
                    print(f"Grid: {'ON' if self.show_grid else 'OFF'}")
                elif event.key == pygame.K_s:
                    if self._save_collision_mesh():
                        print("Collision mesh saved successfully!")
                elif event.key == pygame.K_l:
                    self._load_collision_mesh()
                    print("Collision mesh reloaded")
                elif event.key == pygame.K_c:
                    self.shapes[self.current_shape].clear()
                    print(f"Cleared all vertices in shape {self.current_shape}")
                elif event.key == pygame.K_n:
                    # Create new shape
                    self.shapes.append([])
                    self.current_shape = len(self.shapes) - 1
                    self.selected_vertex = None
                    print(f"Created new shape {self.current_shape}")
                elif event.key == pygame.K_TAB:
                    # Switch between shapes
                    if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                        # Shift+Tab: previous shape
                        self.current_shape = (self.current_shape - 1) % len(self.shapes)
                    else:
                        # Tab: next shape
                        self.current_shape = (self.current_shape + 1) % len(self.shapes)
                    self.selected_vertex = None
                    print(f"Switched to shape {self.current_shape}")
                elif event.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
                    # Delete current shape
                    if len(self.shapes) > 1:
                        deleted_idx = self.current_shape
                        self.shapes.pop(self.current_shape)
                        self.current_shape = min(self.current_shape, len(self.shapes) - 1)
                        self.selected_vertex = None
                        print(f"Deleted shape {deleted_idx}, now on shape {self.current_shape}")
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
                    vertex_idx = self._get_vertex_at_position(world_x, world_y)
                    if vertex_idx is not None:
                        # Select and start dragging existing vertex
                        self.selected_vertex = vertex_idx
                        self.dragging_vertex = True
                    else:
                        # Place new vertex in current shape
                        snapped_x, snapped_y = self._snap_to_grid(world_x, world_y)
                        self.shapes[self.current_shape].append((snapped_x, snapped_y))
                        self.selected_vertex = len(self.shapes[self.current_shape]) - 1
                        print(f"Placed vertex at ({snapped_x}, {snapped_y}) in shape {self.current_shape}")
                
                # Right mouse button - delete vertex
                elif event.button == 3:
                    vertex_idx = self._get_vertex_at_position(world_x, world_y)
                    if vertex_idx is not None:
                        self.shapes[self.current_shape].pop(vertex_idx)
                        if self.selected_vertex == vertex_idx:
                            self.selected_vertex = None
                        elif self.selected_vertex is not None and self.selected_vertex > vertex_idx:
                            self.selected_vertex -= 1
                        print(f"Deleted vertex from shape {self.current_shape}")
                
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
                elif self.dragging_vertex and self.selected_vertex is not None:
                    world_x, world_y = self._screen_to_world(mouse_x, mouse_y)
                    snapped_x, snapped_y = self._snap_to_grid(world_x, world_y)
                    self.shapes[self.current_shape][self.selected_vertex] = (snapped_x, snapped_y)
                
                # Update hover state
                else:
                    world_x, world_y = self._screen_to_world(mouse_x, mouse_y)
                    self.hover_vertex = self._get_vertex_at_position(world_x, world_y)
    
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
        """Draw the collision mesh vertices and lines"""
        # Draw all shapes
        for shape_idx, vertices in enumerate(self.shapes):
            if len(vertices) == 0:
                continue
            
            is_current = (shape_idx == self.current_shape)
            
            # Choose colors based on whether this is the active shape
            if is_current:
                line_color = self.line_color
                vertex_color = self.vertex_color
                vertex_hover_color = self.vertex_hover_color
                vertex_selected_color = self.vertex_selected_color
            else:
                line_color = self.inactive_line_color
                vertex_color = self.inactive_vertex_color
                vertex_hover_color = self.inactive_vertex_color
                vertex_selected_color = self.inactive_vertex_color
            
            # Draw lines connecting vertices
            if len(vertices) > 1:
                screen_points = []
                for vx, vy in vertices:
                    sx, sy = self._world_to_screen(vx, vy)
                    screen_points.append((sx, sy))
                
                # Draw lines
                for i in range(len(screen_points)):
                    p1 = screen_points[i]
                    p2 = screen_points[(i + 1) % len(screen_points)]
                    width = 2 if is_current else 1
                    pygame.draw.line(self.screen, line_color, p1, p2, width)
            
            # Draw vertices
            for i, (vx, vy) in enumerate(vertices):
                sx, sy = self._world_to_screen(vx, vy)
                
                # Choose color based on state (only for current shape)
                if is_current:
                    if i == self.selected_vertex:
                        color = vertex_selected_color
                        radius = 8
                    elif i == self.hover_vertex:
                        color = vertex_hover_color
                        radius = 7
                    else:
                        color = vertex_color
                        radius = 6
                else:
                    color = vertex_color
                    radius = 4
                
                # Draw vertex
                pygame.draw.circle(self.screen, color, (int(sx), int(sy)), radius)
                if is_current:
                    pygame.draw.circle(self.screen, (255, 255, 255), (int(sx), int(sy)), radius, 1)
                
                # Draw vertex number for current shape only
                if is_current and self.zoom > 0.8:
                    text = self.font.render(str(i), True, (255, 255, 255))
                    self.screen.blit(text, (int(sx) + 10, int(sy) - 10))
    
    def draw_ui(self):
        """Draw UI overlay with controls and info"""
        # Semi-transparent background for text
        ui_surface = pygame.Surface((400, 340), pygame.SRCALPHA)
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
            "S: Save mesh",
            "L: Load mesh",
            "C: Clear current shape",
            "N: New shape",
            "TAB: Next shape",
            "SHIFT+TAB: Previous shape",
            "DELETE/BACKSPACE: Delete shape",
            "PageUp: Previous map",
            "PageDown: Next map",
            "ESC: Exit",
            "",
            f"Current Shape: {self.current_shape} / {len(self.shapes) - 1}",
            f"Vertices in shape: {len(self.shapes[self.current_shape])}",
            f"Total shapes: {len(self.shapes)}",
            f"Map: {self.map_num} / {max(1, int(getattr(const, 'TOTAL_MAPS', 1)))}",
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
        
        if not self.panning and self.hover_vertex is None:
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
        print("Use PageUp/PageDown to switch maps")
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
