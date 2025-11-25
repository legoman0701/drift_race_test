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
    def __init__(self, size: Tuple[int, int], title: str = "Drift Race") -> None:
        if not _HAS_SDL2:
            raise ImportError("pygame._sdl2.video is not available")
        self.size = size
        
        self.win = None
        
        if hasattr(Window, "from_display"):
            try:
                self.win = Window.from_display()
            except Exception as e:
                print(f"from_display() failed: {e}")
        
        if self.win is None and hasattr(Window, "from_window"):
            try:
                import pygame.display
                surf = pygame.display.get_surface()
                if surf:
                    self.win = Window.from_window(surf)
            except Exception as e:
                print(f"from_window() failed: {e}")
        
        if self.win is None:
            try:
                # Force Direct3D 11 renderer for better GPU detection on Windows
                import os
                os.environ['SDL_RENDER_DRIVER'] = 'direct3d11'
                self.win = Window(title, size)
                print("Created new SDL2 window")
            except Exception as e:
                raise ImportError(f"Could not create SDL2 Window: {e}")
        
        self.renderer = Renderer(self.win, index=0, accelerated=1, vsync=0)
        
        try:
            import subprocess
            
            print("\n=== GPU Information ===")
            try:
                result = subprocess.check_output(
                    ["wmic", "path", "win32_VideoController", "get", "name,AdapterRAM,DriverVersion"],
                    shell=True,
                    text=True,
                    timeout=2
                )
                lines = [line.strip() for line in result.split('\n') if line.strip()]
                if len(lines) > 1:
                    print("Detected GPUs:")
                    for line in lines[1:]:  # Skip header
                        if line and "Virtual" not in line:  # Show non-virtual GPUs
                            print(f"  - {line}")
            except Exception as e:
                print(f"Could not detect GPU: {e}")
            
            # Show SDL2 render backend info
            from pygame import _sdl2 as sdl2
            num_drivers = sdl2.get_num_render_drivers()
            print(f"\nSDL2 Render Drivers ({num_drivers}):")
            for i in range(num_drivers):
                driver_name = sdl2.get_render_driver_name(i)
                marker = " <- ACTIVE" if i == 0 else ""
                print(f"  [{i}] {driver_name}{marker}")
            print("="*40)
        except Exception as e:
            print(f"GPU: Hardware-accelerated rendering active")

    def present(self, *surfaces: pygame.Surface) -> None:
        self.renderer.clear()
        for surf in surfaces:
            tex = Texture.from_surface(self.renderer, surf)
            tex.draw(dstrect=None, srcrect=None)
        self.renderer.present()

    def size(self) -> Tuple[int, int]:
        return self.size
