try:
    from pygame._sdl2.video import Window, Renderer, Texture
    _HAS_SDL2 = True
except Exception:
    Window = None
    Renderer = None
    Texture = None
    _HAS_SDL2 = False

import pygame
from typing import Optional, Tuple


class GPUDisplay:
    """Hardware-accelerated presentation layer using pygame._sdl2.

    Pipeline:
      1. Game renders to regular ``pygame.Surface`` objects (world, ui).
      2. ``present()`` uploads each directly to a re-used streaming texture
         (no CPU-side compositing — zero intermediate blits).
      3. The GPU composites them (world first, then alpha-blended UI on top).
      4. ``Renderer.present()`` page-flips.
    """

    def __init__(self, size: Tuple[int, int], title: str = "Drift Race") -> None:
        if not _HAS_SDL2:
            raise ImportError("pygame._sdl2.video is not available")
        self.size = size
        self.win: Window = None
        self.renderer: Renderer = None

        # Register a pixel format for .convert() / .convert_alpha().
        # We create a tiny hidden pygame display — it never conflicts with the
        # SDL2 Window because it's a separate native window.
        if not pygame.display.get_surface():
            try:
                pygame.display.set_mode((1, 1), pygame.HIDDEN)
            except Exception:
                pygame.display.set_mode((1, 1), pygame.NOFRAME)

        # --- Create SDL2 Window -----------------------------------------------
        try:
            self.win = Window(title, size)
        except Exception as exc:
            raise ImportError(f"Could not create SDL2 Window: {exc}")

        # --- Create hardware Renderer ----------------------------------------
        self.renderer = Renderer(self.win, accelerated=1, vsync=0)

        # --- Texture pool (re-created lazily when size changes) ---------------
        self._textures: list = []  # list[Texture]
        # 32-bit conversion buffers keyed by (w,h) — avoids alloc per frame
        self._conv_bufs: dict = {}
        self._log_gpu_info()

    # ------------------------------------------------------------------
    def _log_gpu_info(self) -> None:
        try:
            from pygame import _sdl2 as sdl2
            num = sdl2.get_num_render_drivers()
            names = [sdl2.get_render_driver_name(i) for i in range(num)]
            print(f"  SDL2 render drivers: {', '.join(names)}")
        except Exception:
            pass

    def _get_tex(self, idx: int, w: int, h: int, blend: bool) -> "Texture":
        """Return or create a streaming texture at *idx* with the right size."""
        while len(self._textures) <= idx:
            self._textures.append(None)
        tex = self._textures[idx]
        if tex is None or tex.width != w or tex.height != h:
            tex = Texture(self.renderer, size=(w, h), streaming=True)
            if blend:
                tex.blend_mode = 1  # SDL_BLENDMODE_BLEND
            self._textures[idx] = tex
        return tex

    # ------------------------------------------------------------------
    def _ensure_32bit(self, surf: pygame.Surface) -> pygame.Surface:
        """Return a 32-bit RGBA surface. Reuses a cached buffer to avoid alloc."""
        if surf.get_bitsize() == 32:
            return surf
        key = surf.get_size()
        buf = self._conv_bufs.get(key)
        if buf is None or buf.get_size() != key:
            buf = pygame.Surface(key, pygame.SRCALPHA)
            self._conv_bufs[key] = buf
        buf.fill((0, 0, 0, 0))
        buf.blit(surf, (0, 0))
        return buf

    # ------------------------------------------------------------------
    def present(self, *surfaces: pygame.Surface, profiler=None) -> None:
        """Upload each surface to its own GPU texture and composite on the GPU.

        Typically called as ``gpu_display.present(world_surf, ui_surf)``.
        The first surface (world) may be smaller than the screen — the GPU
        will upscale it.  Subsequent surfaces are drawn with alpha blending.
        No CPU-side compositing is performed.
        """
        _names = ("p.clear", "p.world", "p.ui", "p.surf2", "p.surf3")

        def _begin(tag):
            if profiler is not None:
                profiler.begin(tag)
        def _end(tag):
            if profiler is not None:
                profiler.end(tag)

        r = self.renderer

        _begin("p.clear")
        r.draw_color = (0, 0, 0, 255)
        r.clear()
        _end("p.clear")

        tw, th = self.size
        for i, surf in enumerate(surfaces):
            tag = _names[min(i + 1, len(_names) - 1)]
            _begin(tag)
            surf32 = self._ensure_32bit(surf)
            sw, sh = surf32.get_size()
            tex = self._get_tex(i, sw, sh, blend=(i > 0))
            tex.update(surf32)
            if sw != tw or sh != th:
                tex.draw(dstrect=(0, 0, tw, th))  # GPU upscale
            else:
                tex.draw()
            _end(tag)

        _begin("p.flip")
        r.present()
        _end("p.flip")
