import pygame

class Button:
    # Class-level font cache to avoid creating fonts per button
    _font_cache = {}
    
    @classmethod
    def _get_font(cls, size):
        """Get or create a cached font"""
        if size not in cls._font_cache:
            cls._font_cache[size] = pygame.font.SysFont(None, size)
        return cls._font_cache[size]
    
    def __init__(self, text, x, y, width, height, color, stage_path, action=None):
        self.rect = pygame.Rect(x, y, width, height)
        self.color = color
        self.hover_color = self._lighten_color(color, 30)
        self.press_color = self._darken_color(color, 20)
        self.stage_paths = stage_path
        self._text = text
        self.action = action
        self.font = self._get_font(36)
        self.old_state = False
        
        # Cache text surfaces for performance (MAJOR FPS BOOST)
        self._text_cache = {}
        self._cache_text_surfaces()
        
        # Visual enhancement properties
        self.border_radius = 8
        self.shadow_offset = 4
        self.hover_scale = 1.05
    
    @property
    def text(self):
        return self._text
    
    @text.setter
    def text(self, value):
        """Update text and regenerate cached surfaces"""
        if self._text != value:
            self._text = value
            self._cache_text_surfaces()
    
    def _cache_text_surfaces(self):
        """Pre-render text surfaces to avoid expensive render calls every frame"""
        self._text_cache = {
            'normal': self.font.render(self._text, True, (255, 255, 255)),
            'hover': self.font.render(self._text, True, (255, 255, 255)),
            'pressed': self.font.render(self._text, True, (230, 230, 230))
        }
    
    def _lighten_color(self, color, amount):
        """Lighten a color by a given amount"""
        return tuple(min(255, c + amount) for c in color)
    
    def _darken_color(self, color, amount):
        """Darken a color by a given amount"""
        return tuple(max(0, c - amount) for c in color)
    
    def _draw_rounded_rect(self, surface, color, rect, radius):
        """Draw a rounded rectangle with gradient-like effect"""
        # Main body
        pygame.draw.rect(surface, color, rect, border_radius=radius)
        
        # Subtle gradient effect using alpha blending
        gradient_rect = pygame.Rect(rect.x, rect.y, rect.width, rect.height // 2)
        gradient_surf = pygame.Surface((rect.width, rect.height // 2), pygame.SRCALPHA)
        gradient_surf.fill((*self._lighten_color(color, 15), 40))
        surface.blit(gradient_surf, gradient_rect.topleft)

    def draw(self, screen, stage_path):
        if stage_path not in self.stage_paths: 
            return None
        
        mouse_pos = pygame.mouse.get_pos()
        clicked = pygame.mouse.get_pressed()[0]
        is_hovered = self.rect.collidepoint(mouse_pos)
        
        # Determine button state
        if is_hovered and clicked:
            # Pressed state
            button_color = self.press_color
            text_surf = self._text_cache['pressed']
            offset_y = 2  # Press effect
        elif is_hovered:
            # Hover state
            button_color = self.hover_color
            text_surf = self._text_cache['hover']
            offset_y = -1  # Slight lift effect
        else:
            # Normal state
            button_color = self.color
            text_surf = self._text_cache['normal']
            offset_y = 0
        
        # Draw shadow (only when not pressed)
        if not (is_hovered and clicked):
            shadow_rect = self.rect.copy()
            shadow_rect.x += self.shadow_offset
            shadow_rect.y += self.shadow_offset
            shadow_surf = pygame.Surface((shadow_rect.width, shadow_rect.height), pygame.SRCALPHA)
            pygame.draw.rect(shadow_surf, (0, 0, 0, 60), shadow_surf.get_rect(), border_radius=self.border_radius)
            screen.blit(shadow_surf, shadow_rect.topleft)
        
        # Draw button with rounded corners
        button_rect = self.rect.copy()
        button_rect.y += offset_y
        self._draw_rounded_rect(screen, button_color, button_rect, self.border_radius)
        
        # Draw subtle border
        border_color = self._lighten_color(button_color, 40)
        pygame.draw.rect(screen, border_color, button_rect, width=2, border_radius=self.border_radius)
        
        # Draw cached text (NO font.render() call here = MAJOR PERFORMANCE GAIN)
        text_rect = text_surf.get_rect(center=(button_rect.centerx, button_rect.centery))
        screen.blit(text_surf, text_rect)
        
        # Handle click action
        if is_hovered and clicked and self.action and not self.old_state:
            self.old_state = True
            return self.action()
        if not clicked:
            self.old_state = False
        
        return None

