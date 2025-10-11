import pygame, string, math

# ======= CONFIGURATION =======
RELAY_PUBLIC_ENDPOINT = "william-allow.gl.at.ply.gg:4800"

# Global UI scale factor
# 1.0 = original size, 1.5 = 150% (50% bigger)
UI_SCALE = 1

# World dimensions
MAP_NUM = 1
WINDOW_WIDTH, WINDOW_HEIGHT = 1000, 700
TRACK_MARGIN = 40
TRACK_COLOR = (35, 40, 50)
TRACK_BORDER_COLOR = (80, 90, 100)
TRACK_BORDER_WIDTH = 4
FPS = 75
SEND_HZ = 60.0       # client -> relay state rate
PING_HZ = 1/5        # keepalive (~5 s)

# Colors
BLACK = (0, 0, 0)
GREY_20 = (20, 20, 20)
GREY_180 = (180, 180, 180)
GREY_200 = (200, 200, 200)
WHITE_240 = (240, 240, 240)
WHITE = (255, 255, 255)
RED = (200, 0, 0)
GREEN = (0, 200, 0)
BLUE = (0, 0, 200)
NAVY_BLUE = (5, 15, 28)

COLOR_BODY_DEFAULT = (250, 210, 120)
COLOR_NOSE_DEFAULT = (255, 120, 120)
COLOR_BODY_REMOTE = (255, 200, 120)
COLOR_MY_CAR = (200, 230, 255)
HEADLIGHT_COLOR = (200, 200, 200)

# Pygame surface flags
FLAGS = pygame.HWSURFACE | pygame.DOUBLEBUF

# key binds
UP_KEY = [pygame.K_UP, pygame.K_z]
DOWN_KEY = [pygame.K_DOWN, pygame.K_s]
LEFT_KEY = [pygame.K_LEFT, pygame.K_q]
RIGHT_KEY = [pygame.K_RIGHT, pygame.K_d]
BRAKE_KEY = pygame.K_SPACE
ESCAPE_KEY = pygame.K_ESCAPE
RESET_KEY = pygame.K_r
HOST_KEY = pygame.K_h
JOIN_KEY = pygame.K_j
CHANGE_CAR_KEY = pygame.K_c

# car
CAR_LEN = 38.0
CAR_WID = 20.0
TIRE_MARK_SMOKE = (255, 255, 255, 100)  # tire mark color at first step (smoke)
TIRE_MARK_GROUND = (220, 220, 220, 220)  # tire mark color at second step on the ground
HEADLIGHT_LEN = 150
HEADLIGHT_FOV = 25  # degrees per headlight cone (narrow beams)
GLOW_RADIUS = 10  # soft round glow around the car

# visual const
TOP_LINE_Y = 30
BOTTOM_LINE_Y = WINDOW_HEIGHT - 20
BTN_WIDTH, BTN_HEIGHT = 300, 75
FONT_SMALL_SIZE = 18
FONT_MEDIUM_SIZE = 26
FONT_BIG_SIZE = 40
TITLE_Y = 3
TIP1_Y = 8
TIP2_Y = 8
RELAY_Y = WINDOW_HEIGHT - 16

# username & room code
ROOM_ALPHABET = string.ascii_uppercase + string.digits
JOIN_CODE_LEN = 4
MAX_CODE_LENGTH = 12
KEY_REPEAT_DELAY = 250
KEY_REPEAT_INTERVAL = 35
MIN_NAME_LENGTH = 3
MAX_NAME_LENGTH = 12
PROFANITY_SET = {"NIGGER", "NIGGA", "NIGA"}

VIEW_ANGLE = 70 * math.pi / 180.0  # radians

# Car sprite configurations [shadow, main, headlights]
CAR_SPRITES = {
    "ae86": {
        "paths": [
            "assets/AE86/Shadow_Map/Image{i:04}.png",
            "assets/AE86/Diffuse/Image{i:04}.png", 
            "assets/AE86/Light_Spray/{i:04}.png"
        ]
    },
    "m5": {
        "paths": [
            "assets/M5/Shadow_Map/Image{i:04}.png",
            "assets/M5/Diffuse/Image{i:04}.png",
            "assets/M5/Light_Spray/{i:04}.png"
        ]
    }
}
