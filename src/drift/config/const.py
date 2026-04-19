import pygame, string, math
from drift.tools.paths import get_available_cars

# ======= APPLICATION INFO =======
VERSION = "0.7.1"

# ======= NETWORK =======
RELAY_PUBLIC_ENDPOINT = "william-allow.gl.at.ply.gg:4800"
SEND_HZ = 30.0       # client -> relay state rate
PING_HZ = 1/5        # keepalive (~5 s)

# ======= DISPLAY & WINDOW =======
WINDOW_WIDTH, WINDOW_HEIGHT = 1200, 900
WINDOW_WIDTH_W, WINDOW_HEIGHT_W = 1200, 900
FPS = 300
FLAGS = pygame.HWSURFACE | pygame.DOUBLEBUF

# UI scale factor (1.0 = original, 1.5 = 150%)
UI_SCALE = 1

# UI layout positions
TOP_LINE_Y = 30
BOTTOM_LINE_Y = 20
TITLE_Y = 3
NAVBAR_Y = 10
RELAY_Y = WINDOW_HEIGHT - 16
BTN_WIDTH, BTN_HEIGHT = 300, 60

# Font sizes
FONT_SMALL_SIZE = 18
FONT_MEDIUM_SIZE = 26
FONT_BIG_SIZE = 36

# ======= COLORS =======
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

# Car colors
COLOR_BODY_DEFAULT = (250, 210, 120)
COLOR_NOSE_DEFAULT = (255, 120, 120)
COLOR_BODY_REMOTE = (255, 200, 120)
COLOR_MY_CAR = (200, 230, 255)
HEADLIGHT_COLOR = (200, 200, 200)

# Track colors
TRACK_COLOR = (35, 40, 50)
TRACK_BORDER_COLOR = (80, 90, 100)

# Tire mark colors
TIRE_MARK_SMOKE = (255, 255, 255, 100)     # smoke while drifting
TIRE_MARK_GROUND = (220, 220, 220, 220)    # marks on ground

# ======= MAP & TRACK =======
MAP_NUM = 1
TOTAL_MAPS = 2 # new map flag
TILE_SIZE = 512  # Tile size for map chunks
TRACK_MARGIN = 40
TRACK_BORDER_WIDTH = 4

# ======= CAR PHYSICS =======
CAR_LEN = 38.0
CAR_WID = 20.0
STEER_BIAS = 1.0  # how much the car automatically steers into the drift
VIEW_ANGLE = 70 * math.pi / 180.0  # radians

# ======= CAR SPRITES =======
AVAILABLE_CARS = get_available_cars()
CAR_SPRITES = {}
for car in AVAILABLE_CARS:
    CAR_SPRITES[car] = {
        "paths": [ # [shadow, diffuse (main), headlights]
            f"cars/{car}/Shadow_Map/Image{{i:04}}.png",
            f"cars/{car}/Diffuse/Image{{i:04}}.png", 
            f"cars/{car}/Light_Spray/Image{{i:04}}.png",
            f"cars/{car}/Palette/Image{{i:04}}.png"
        ]
    },
DEFAULT_CAR_ID = "911"
DEFAULT_CAR_NAME = "911 SC"

# ======= CONTROLS =======
# Menu controls
RETURN_KEYS = [pygame.K_RETURN, pygame.K_KP_ENTER]
ESCAPE_KEY = pygame.K_ESCAPE  # open settings / pause menu

# Car controls
UP_KEY = [pygame.K_UP, pygame.K_z]      # accelerate
DOWN_KEY = [pygame.K_DOWN, pygame.K_s]  # reverse
LEFT_KEY = [pygame.K_LEFT, pygame.K_q]  # steer left
RIGHT_KEY = [pygame.K_RIGHT, pygame.K_d] # steer right
BRAKE_KEY = pygame.K_SPACE              # handbrake
RESET_KEY = pygame.K_r                  # reset car position
RESTART_KEY = pygame.K_t                # restart current race

# Game controls
CHANGE_CAR_KEY = pygame.K_c             # change car
HOST_KEY = pygame.K_h                   # host game
JOIN_KEY = pygame.K_j                   # join game
AI_KEY = pygame.K_n                     # add AI car

# Debug controls
DEBUG_TOGGLE_KEY = pygame.K_F3          # toggle debug mode
# FULLSCREEN_KEY = pygame.K_f             # toggle fullscreen mode
FULLSCREEN_KEY = []                     # disabled

# ======= USERNAME & ROOM CODE =======
ROOM_ALPHABET = string.ascii_uppercase + string.digits
JOIN_CODE_LEN = 4
MAX_CODE_LENGTH = 12
MIN_NAME_LENGTH = 3
MAX_NAME_LENGTH = 12
PROFANITY_SET = {"cerise", "fraise"} # unused

# Keyboard input settings
KEY_REPEAT_DELAY = 250
KEY_REPEAT_INTERVAL = 35

# ======= DEBUG MODES =======
DEBUG = False
CURSOR_FOLLOW = False
AI_PATH_FOLLOW = False
AI_DEBUG = False