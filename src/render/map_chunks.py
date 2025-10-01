from typing import Dict, Tuple, Optional, Iterable
import os, config.const as const
try: import pygame_ce as pygame  # type: ignore
except Exception: import pygame  # type: ignore

class ChunkedMap:
    """
    Lazy-loading tiled map. Tiles live in assets/Map/Map1_chunks as PNGs named: {ix}_{iy}.png
    - World coords (x,y) -> tile indices (ix,iy) via floor division by tile_size.
    - Missing tiles render as a flat color (background).
    """
    def __init__(self,
                 root: str = f"assets/Map/Map{const.MAP_NUM}_chunks",
                 tile_size: int = 1024, # 1024x1024
                 default_color=(28, 28, 28)) -> None:
        self.root = root
        self.tile_size = tile_size
        self.default_color = default_color
        self._cache: Dict[Tuple[int, int], pygame.Surface] = {} # {(x, y): surface}

    def _load_tile(self, ix: int, iy: int) -> pygame.Surface:
        link = os.path.join(self.root, f"{ix}_{iy}.png") # ./assets/Map/Map0_chunks/
        surf: Optional[pygame.Surface] = None
        if os.path.exists(link):
            try: surf = pygame.image.load(link).convert()
            except Exception: pass
        if surf is None:
            surf = pygame.Surface((self.tile_size, self.tile_size)) # surface : 1024x1024
            surf.fill(self.default_color)
        self._cache[(ix, iy)] = surf # add it to cache
        return surf

    def get_tile(self, ix: int, iy: int) -> pygame.Surface:
        return self._cache.get((ix, iy)) or self._load_tile(ix, iy) # if in cache else load it

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
