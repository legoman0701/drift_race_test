import pygame
import sys
from pathlib import Path

# Ensure package src path is importable when running this top-level script directly
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from drift.audio.turbo_sound import TurboSound

# Initialize Pygame
pygame.init()

# Constants
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# Create the display
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Pygame Template")
clock = pygame.time.Clock()

pygame.mixer.init()

# Turbo sound system instance
turbo = TurboSound("turbo_03.wav", min_pitch=0.5, max_pitch=2.0, cache_size=48)

def main():
    running = True
    # Prime initial sound
    turbo.play(1.0, volume=0.5)
    
    while running:
        # Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
        
        # Update game logic here
        # Handle keyboard input for RPM
        keys = pygame.key.get_pressed()
        rpm = 1000  # Base RPM
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            rpm = 6000
        elif keys[pygame.K_DOWN] or keys[pygame.K_s]:
            rpm = 500

        volume = max(0.1, min(1.0, (rpm - 500) / 5500))  # Scale volume between 0.1 and 1.0
        pitch_factor = max(0.5, min(2.0, rpm / 3000))    # Scale pitch between 0.5x and 2.0x

        turbo.play(pitch_factor, volume)

        # Draw everything
        screen.fill(WHITE)
        
        
        
        # Draw your objects here
        
        # Update the display
        pygame.display.flip()
        clock.tick(FPS)
    
    turbo.stop()
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()