import pygame
from typing import Dict, Tuple, Optional, Iterable
import os, drift.config.const as const
import json
from drift.tools.paths import asset_path
from drift.tools.slice_map import slice_map

class ChunkedMap:
    """
    Lazy-loading tiled map. Tiles live in assets/track/map{x}/chunks as PNGs named: {ix}_{iy}.png
    - World coords (x,y) -> tile indices (ix,iy) via floor division by tile_size.
    - Missing tiles render as a flat color (background).
    """
    def __init__(self,
                 root: str = None,
                 tile_size: int = const.TILE_SIZE, # 512x512
                 default_color=(28, 28, 28),
                 max_cached_chunks: int = 64) -> None:
        
        if root is None: root = asset_path("track", f"map{const.MAP_NUM}", "chunks")
        self.root = root
        self.tile_size = tile_size
        self.default_color = default_color
        self.max_cached_chunks = max_cached_chunks
        self._cache: Dict[Tuple[int, int], pygame.Surface] = {} # {(x, y): surface}
        self._cache_access_order: Dict[Tuple[int, int], int] = {}  # Track LRU
        self._access_counter = 0
        for map_num in range(1, const.TOTAL_MAPS + 1):
            slice_map(input_path = asset_path("track", f"map{map_num}", "main.png"),
                outdir = asset_path("track", f"map{map_num}", "chunks"),
                tile = const.TILE_SIZE,
                indexing = "zero",
                prefix = "",
                pad_color = (28, 28, 28, 255),
                force = False)
        self._world_size = self._compute_world_size()

    def _compute_world_size(self) -> Tuple[int, int]:
        """Prefer exact map dimensions, fallback to chunk coverage."""
        # option 1 : meta data json file
        map_size = self._read_world_size_from_metadata()
        if map_size is not None: return map_size
        # option 2 : main.png file size
        map_size = self._read_world_size_from_main_png()
        if map_size is not None: return map_size
        # option 3 : sum of chunks sizes
        return self._compute_world_size_from_chunks()

    def _read_world_size_from_metadata(self) -> Optional[Tuple[int, int]]:
        """Read world size from optional map metadata JSON in map folder."""
        map_dir = os.path.dirname(str(self.root))
        meta_path = os.path.join(map_dir, "map_meta.json")
        try:
            # print(f"Attempting to read map size from metadata: {meta_path}")
            if not os.path.exists(meta_path): return None
            with open(meta_path, "r", encoding="utf-8") as fh: meta = json.load(fh)
            width = int(meta.get("width", 0))
            height = int(meta.get("height", 0))
            # print(f"Map metadata found. Width: {width}, Height: {height}")
            if width > 0 and height > 0: return width, height
        except Exception as e: print(f"Error reading map metadata: {e}")
        return None

    def _read_world_size_from_main_png(self) -> Optional[Tuple[int, int]]:
        """Read world size directly from map main.png file."""
        map_dir = os.path.dirname(str(self.root))
        main_png_path = os.path.join(map_dir, "main.png")
        try:
            if not os.path.exists(main_png_path): return None
            main_surf = pygame.image.load(main_png_path)
            return main_surf.get_width(), main_surf.get_height()
        except Exception as e: print(f"Error reading main.png size: {e}"); return None

    def _compute_world_size_from_chunks(self) -> Tuple[int, int]:
        """Compute finite world size from available chunk indices."""
        root_path = str(self.root)
        max_ix, max_iy = -1, -1
        try:
            for name in os.listdir(root_path):
                if not name.endswith(".png"): continue
                stem = os.path.splitext(name)[0]
                if "_" not in stem: continue
                xs, ys = stem.split("_", 1)
                ix, iy = int(xs), int(ys)
                if ix > max_ix: max_ix = ix
                if iy > max_iy: max_iy = iy
        except Exception as e: print(f"Error computing world size from chunks: {e}")

        if max_ix < 0 or max_iy < 0: return const.WINDOW_WIDTH, const.WINDOW_HEIGHT

        return (max_ix + 1) * self.tile_size, (max_iy + 1) * self.tile_size

    def get_world_size(self) -> Tuple[int, int]:
        """Return world dimensions in pixels derived from chunk coverage."""
        return self._world_size

    def _load_tile(self, ix: int, iy: int) -> pygame.Surface:
        # root is already a Path object, so we can use / operator or joinpath
        link = self.root / f"{ix}_{iy}.png" if hasattr(self.root, '__truediv__') else os.path.join(str(self.root), f"{ix}_{iy}.png")
        surf: Optional[pygame.Surface] = None
        if os.path.exists(link):
            try: surf = pygame.image.load(link).convert()
            except Exception as e: print(f"Error loading tile {link}: {e}")
        if surf is None:
            surf = pygame.Surface((self.tile_size, self.tile_size)) # surface : 512x512
            surf.fill(self.default_color)
        self._cache[(ix, iy)] = surf # add it to cache
        return surf

    def get_tile(self, ix: int, iy: int) -> pygame.Surface:
        key = (ix, iy)
        # Update access tracking for LRU
        self._access_counter += 1
        self._cache_access_order[key] = self._access_counter
        
        # Get or load tile
        tile = self._cache.get(key)
        if tile is None:
            tile = self._load_tile(ix, iy)
            self._evict_old_chunks()
        
        return tile
    
    def _evict_old_chunks(self) -> None:
        """Remove least recently used chunks when cache exceeds max size."""
        if len(self._cache) <= self.max_cached_chunks:
            return
        
        # Sort by access order (oldest first)
        sorted_chunks = sorted(self._cache_access_order.items(), key=lambda kv: kv[1])
        to_remove = len(self._cache) - self.max_cached_chunks
        
        for key, _ in sorted_chunks[:to_remove]:
            self._cache.pop(key, None)
            self._cache_access_order.pop(key, None)

    def world_to_tile(self, x: float, y: float) -> Tuple[int, int]:
        return int(x // self.tile_size), int(y // self.tile_size) # get the tile according to car's real pos

    def tiles_for_rect(self, rect: pygame.Rect) -> Iterable[Tuple[int, int]]:
        ix0, iy0 = self.world_to_tile(rect.left, rect.top)
        ix1, iy1 = self.world_to_tile(rect.right - 1, rect.bottom - 1)
        for iy in range(iy0, iy1 + 1):
            for ix in range(ix0, ix1 + 1):
                yield ix, iy

    def render_to(self, dest: pygame.Surface, camera_rect: pygame.Rect) -> None:
        """Blit all tiles overlapped by camera_rect into dest at (tile_origin - camera_rect.topleft)."""
        ts = self.tile_size
        offx, offy = camera_rect.left, camera_rect.top # offset
        for ix, iy in self.tiles_for_rect(camera_rect):
            tile = self.get_tile(ix, iy)
            dest.blit(tile, (ix * ts - offx, iy * ts - offy))


class TireMarkGrid:
    """
    Tire marks stored per chunk (same grid as the map).
    Keeps memory bounded by evicting old far-away chunks.
    """
    def __init__(self, tile_size: int, max_kept: int = 256):
        self.tile_size = tile_size
        self.max_kept = max_kept
        self._marks: Dict[Tuple[int, int], pygame.Surface] = {} # {(x, y): surface}
        self._last_used: Dict[Tuple[int, int], int] = {} # {(x, y): t}
        self._use_counter = 0

    def _get_chunk(self, ix: int, iy: int) -> pygame.Surface:
        key = (ix, iy)
        surf = self._marks.get(key) # -> {key: surface}
        if surf is None:
            surf = pygame.Surface((self.tile_size, self.tile_size), pygame.SRCALPHA)
            surf.fill((255, 255, 255, 0)) # transparent
            self._marks[key] = surf
        self._last_used[key] = self._use_counter
        return surf

    def _ensure_budget(self) -> None:
        if len(self._marks) <= self.max_kept:
            return
        # evict the least recently used chunks
        items = sorted(self._last_used.items(), key=lambda kv: kv[1])
        to_remove = len(self._marks) - self.max_kept
        for (key, _score) in items[:to_remove]:
            self._marks.pop(key, None)
            self._last_used.pop(key, None)

    def fade(self, color_mult=(240, 240, 240, 255)) -> None:
        """Slow fade towards 'ground' each frame by multiply-blend."""
        for surf in self._marks.values():
            surf.fill(color_mult, special_flags=pygame.BLEND_RGBA_MULT)

    def draw_line_world(self, p0, p1, color, width, tile_size) -> None:
        """Draw a line (world coords) across potentially multiple chunks."""
        self._use_counter += 1
        ts = self.tile_size
        # naive but effective: render on both endpoint chunks; acceptable for short dt lines
        for px, py in (p0, p1):
            ix, iy = int(px // ts), int(py // ts)
            loc = self._get_chunk(ix, iy)
            ox, oy = ix * ts, iy * ts
            pygame.draw.line(loc, color, (p0[0] - ox, p0[1] - oy), (p1[0] - ox, p1[1] - oy), width)
        self._ensure_budget()

    def blit_visible(self, dest: pygame.Surface, camera_rect: pygame.Rect) -> None:
        ts = self.tile_size
        offx, offy = camera_rect.left, camera_rect.top
        for iy in range(int(camera_rect.top // ts), int((camera_rect.bottom - 1) // ts) + 1):
            for ix in range(int(camera_rect.left // ts), int((camera_rect.right - 1) // ts) + 1):
                key = (ix, iy)
                surf = self._marks.get(key)
                if surf:
                    dest.blit(surf, (ix * ts - offx, iy * ts - offy))

    def fade_visible(self, camera_rect: pygame.Rect, color_mult=(200, 200, 200, 255)) -> None:
        """" Apply fade to visible chunks. """
        ts = self.tile_size # 512x512
        # Calculate tile indices for the camera rect
        ix0 = int(camera_rect.left // ts)
        iy0 = int(camera_rect.top // ts)
        ix1 = int((camera_rect.right - 1) // ts)
        iy1 = int((camera_rect.bottom - 1) // ts)
        # Iterate only over visible tiles
        for iy in range(iy0, iy1 + 1):
            for ix in range(ix0, ix1 + 1):
                surf = self._marks.get((ix, iy))
                if surf: # apply fade
                    surf.fill(color_mult, special_flags=pygame.BLEND_RGBA_MULT)

