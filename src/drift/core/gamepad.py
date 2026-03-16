# input_manager.py
import pygame

class Gamepad:
    def __init__(self):
        self.joystick = None
        self.selected_index = None

    def connect_gamepad(self, idx):
        """Handles the connection and stores the object internally."""
        # print(f"Connecting gamepad index: {idx}")
        self.joystick = pygame.joystick.Joystick(idx)
        self.joystick.init()
        self.selected_index = idx
