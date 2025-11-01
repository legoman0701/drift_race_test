import pygame, string, math

# ======= CONFIGURATION =======
RELAY_PUBLIC_ENDPOINT = "william-allow.gl.at.ply.gg:4800"
VERSION = "0.8-alpha"

# Global UI scale factor
# 1.0 = original size, 1.5 = 150% (50% bigger)
UI_SCALE = 1

# Modes
DEBUG = False
CURSOR_FOLLOW = False
AI_PATH_FOLLOW = False

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
GREEN = (50, 200, 50)
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
RETURN_KEYS = [pygame.K_RETURN, pygame.K_KP_ENTER]
ESCAPE_KEY = pygame.K_ESCAPE # open settings / pause menu
UP_KEY = [pygame.K_UP, pygame.K_z] # accelerate
DOWN_KEY = [pygame.K_DOWN, pygame.K_s] # reverse
LEFT_KEY = [pygame.K_LEFT, pygame.K_q] # steer left
RIGHT_KEY = [pygame.K_RIGHT, pygame.K_d] # steer right
BRAKE_KEY = pygame.K_SPACE # handbrake
RESET_KEY = pygame.K_r # reset car position
HOST_KEY = pygame.K_h # host game
JOIN_KEY = pygame.K_j # join game
CHANGE_CAR_KEY = pygame.K_c # change car
DEBUG_TOGGLE_KEY = pygame.K_F3 # toggle debug mode

# car
CAR_LEN = 38.0
CAR_WID = 20.0
TIRE_MARK_SMOKE = (255, 255, 255, 100)  # tire mark color at first step (smoke)
TIRE_MARK_GROUND = (220, 220, 220, 220)  # tire mark color at second step on the ground
STEER_BIAS = 1.0  # how much the car automatically steers into the drift 

# visual const
TOP_LINE_Y = 30
BOTTOM_LINE_Y = WINDOW_HEIGHT - 20
BTN_WIDTH, BTN_HEIGHT = 300, 60
TITLE_Y = 3
NAVBAR_Y = 10
RELAY_Y = WINDOW_HEIGHT - 16

# font sizes (fonts will be created after pygame.init() in app.py)
FONT_SMALL_SIZE = 18
FONT_MEDIUM_SIZE = 26
FONT_BIG_SIZE = 36

# username & room code
ROOM_ALPHABET = string.ascii_uppercase + string.digits
JOIN_CODE_LEN = 4
MAX_CODE_LENGTH = 12
KEY_REPEAT_DELAY = 250
KEY_REPEAT_INTERVAL = 35
MIN_NAME_LENGTH = 3
MAX_NAME_LENGTH = 12
PROFANITY_SET = {"ON VA EVITER"}

VIEW_ANGLE = 70 * math.pi / 180.0  # radians

# Car sprite configurations [shadow, main, headlights]
CAR_SPRITES = {
    "ae86": {
        "paths": [
            "cars/AE86/Shadow_Map/Image{i:04}.png",
            "cars/AE86/Diffuse/Image{i:04}.png", 
            "cars/AE86/Light_Spray/{i:04}.png"
        ]
    },
    "m5": {
        "paths": [
            "cars/M5/Shadow_Map/Image{i:04}.png",
            "cars/M5/Diffuse/Image{i:04}.png",
            "cars/M5/Light_Spray/{i:04}.png"
        ]
    }
}
