import pygame
import drift.config.const as const

class Slider:
    """A horizontal slider UI component for numeric values."""
    
    def __init__(self, x, y, width, height, min_val, max_val, current_val, label, font):
        self.rect = pygame.Rect(x, y, width, height)
        self.min_val = min_val
        self.max_val = max_val
        self._value = current_val
        self.label = label
        self.font = font
        
        # Visual properties
        self.track_color = (60, 60, 70)
        self.handle_color = (180, 180, 190)
        self.handle_hover_color = (220, 220, 230)
        self.handle_pressed_color = (160, 160, 170)
        self.track_height = 8
        self.handle_radius = 12
        
        # State
        self.dragging = False
        self.hovered = False
        
        # Calculate handle position
        self._update_handle_pos()
        
    @property
    def value(self):
        """Get current slider value."""
        return self._value
    
    @value.setter
    def value(self, val):
        """Set slider value (clamped to min/max range and snapped to 0.1 increments)."""
        # Snap to 0.1 increments
        snapped_val = round(val * 10) / 10
        self._value = max(self.min_val, min(self.max_val, snapped_val))
        self._update_handle_pos()
    
    def _update_handle_pos(self):
        """Update handle position based on current value."""
        progress = (self._value - self.min_val) / (self.max_val - self.min_val)
        track_start = self.rect.x + self.handle_radius
        track_end = self.rect.x + self.rect.width - self.handle_radius
        self.handle_x = track_start + progress * (track_end - track_start)
        self.handle_y = self.rect.centery
    
    def handle_event(self, event):
        """Handle mouse events for slider interaction."""
        mouse_pos = pygame.mouse.get_pos()
        
        # Check if mouse is over handle
        handle_rect = pygame.Rect(
            self.handle_x - self.handle_radius, 
            self.handle_y - self.handle_radius,
            self.handle_radius * 2, 
            self.handle_radius * 2
        )
        
        self.hovered = handle_rect.collidepoint(mouse_pos)
        
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1 and self.hovered:  # Left click
                self.dragging = True
                
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:  # Left click release
                self.dragging = False
                
        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                # Update value based on mouse position
                track_start = self.rect.x + self.handle_radius
                track_end = self.rect.x + self.rect.width - self.handle_radius
                track_width = track_end - track_start
                
                if track_width > 0:
                    progress = (mouse_pos[0] - track_start) / track_width
                    progress = max(0.0, min(1.0, progress))  # Clamp to 0-1
                    new_val = self.min_val + progress * (self.max_val - self.min_val)
                    # Snap to 0.1 increments
                    self.value = round(new_val * 10) / 10
                    
        return self._value
    
    def draw(self, surface):
        """Draw the slider on the given surface."""
        # Draw label
        if self.label:
            label_surf = self.font.render(self.label, True, const.WHITE_240)
            label_rect = label_surf.get_rect()
            label_rect.midright = (self.rect.x - 10, self.rect.centery)
            surface.blit(label_surf, label_rect)
        
        # Draw value text
        value_text = f"{self._value:.1f}"
        value_surf = self.font.render(value_text, True, const.WHITE_240)
        value_rect = value_surf.get_rect()
        value_rect.midleft = (self.rect.right + 10, self.rect.centery)
        surface.blit(value_surf, value_rect)
        
        # Draw track
        track_rect = pygame.Rect(
            self.rect.x + self.handle_radius,
            self.rect.centery - self.track_height // 2,
            self.rect.width - 2 * self.handle_radius,
            self.track_height
        )
        pygame.draw.rect(surface, self.track_color, track_rect, border_radius=4)
        
        # Draw handle
        handle_color = self.handle_color
        if self.dragging:
            handle_color = self.handle_pressed_color
        elif self.hovered:
            handle_color = self.handle_hover_color
            
        pygame.draw.circle(surface, handle_color, (int(self.handle_x), int(self.handle_y)), self.handle_radius)
        
        # Draw handle border
        pygame.draw.circle(surface, (100, 100, 110), (int(self.handle_x), int(self.handle_y)), self.handle_radius, 2)