try: import pygame_ce as pygame # type: ignore
except Exception: import pygame # type: ignore
import sys

# Initialize pygame and joystick
pygame.init()
pygame.joystick.init()

# Set up your joystick(s)
joysticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
for j in joysticks:
    j.init()

if not joysticks:
    print("No joystick detected.")
    sys.exit(0)

# Deadzone to avoid small movements being detected
DEADZONE = 0.15

def deadzone(value, dz=DEADZONE):
    return 0.0 if abs(value) < dz else value

# Set up the clock for controlling the frame rate
clock = pygame.time.Clock()

# Game loop
running = True
while running:
    # Check for exit condition
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Poll joystick values continuously
    for j in joysticks:
        # Example: Reading axes (left stick)
        if j.get_numaxes() >= 2:
            lx = deadzone(j.get_axis(0))  # Left stick X
            ly = deadzone(j.get_axis(1))  # Left stick Y
            print(f"Left Stick X: {lx:.3f}, Left Stick Y: {ly:.3f}")

        # Example: Reading buttons (A button on most controllers is button 0)
        if j.get_numbuttons() > 0:
            a_button = j.get_button(0)  # Button 0 is typically the A button
            print(f"A Button: {'Pressed' if a_button else 'Released'}")

        # Example: Reading triggers (usually axes 2 and 3 on most controllers)
        if j.get_numaxes() > 2:
            left_trigger = j.get_axis(2)  # Left trigger
            right_trigger = j.get_axis(3)  # Right trigger
            print(f"Left Trigger: {left_trigger:.3f}, Right Trigger: {right_trigger:.3f}")

    # Cap the frame rate
    clock.tick(60)

pygame.quit()
