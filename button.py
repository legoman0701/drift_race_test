try: import pygame_ce as pygame
except Exception: import pygame

class Button:
    def __init__(self, text, x, y, width, height, color, hover_color, action=None):
        self.rect = pygame.Rect(x, y, width, height)
        self.color = color
        self.hover_color = hover_color
        self.text = text
        self.action = action
        self.font = pygame.font.SysFont(None, 36)
        self.old_state = False

    def draw(self, screen):
        mouse_pos = pygame.mouse.get_pos()
        clicked = pygame.mouse.get_pressed()[0]

        if self.rect.collidepoint(mouse_pos):
            pygame.draw.rect(screen, self.hover_color, self.rect)
            if clicked and self.action and not self.old_state:
                # Call action and return its result (if any) so callers can react to state changes
                self.old_state = True
                return self.action()
            if not clicked:
                self.old_state = False
        else:
            pygame.draw.rect(screen, self.color, self.rect)

        text_surf = self.font.render(self.text, True, (255, 255, 255))
        text_rect = text_surf.get_rect(center=self.rect.center)
        screen.blit(text_surf, text_rect)
        return None

