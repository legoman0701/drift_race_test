import pygame, string, math
from drift.tools.paths import get_available_cars, get_track_folders

# ======= APPLICATION INFO =======
VERSION = "0.7.4"

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
BLUE_MAT = (70, 120, 230)
NAVY_BLUE = (5, 15, 28)

# Car colors
COLOR_BODY_DEFAULT = (250, 210, 120)
COLOR_NOSE_DEFAULT = (255, 120, 120)
COLOR_BODY_REMOTE = (255, 200, 120)
COLOR_MY_CAR = (200, 230, 255)
HEADLIGHT_COLOR = (200, 200, 200)

# palettes
PALETTES = {}

# Track colors
TRACK_COLOR = (35, 40, 50)
TRACK_BORDER_COLOR = (80, 90, 100)

# Tire mark colors
TIRE_MARK_SMOKE = (255, 255, 255, 100)     # smoke while drifting
TIRE_MARK_GROUND = (220, 220, 220, 220)    # marks on ground

# ======= MODES =======
MODE_INDEX = 0
MODES_NAMES = ["Classic Race", "Best Lap", "Drift Race"]
MODES_OPTION_STR = ["Laps", "Timer", "Timer"]
MODES_CHOICES = {
    0: [1, 2, 3, 4, 5], # laps
    1: [30, 60, 120, 180, 300], # timer
    2: [30, 60, 120, 180, 300], # timer
}

# ======= MAP & TRACK =======
MAP_NUM = 1
TOTAL_MAPS = max(1, len(get_track_folders()))  # Numbered tracks map to map_index order
TILE_SIZE = 512  # Tile size for map chunks
TRACK_MARGIN = 40
TRACK_BORDER_WIDTH = 4

# ======= CAR PHYSICS =======
CAR_LEN = 38.0
CAR_WID = 20.0
VIEW_ANGLE = 70 * math.pi / 180.0  # radians
AI_RESET_DELAY = 3.0

# ======= CAR SPRITES =======
def get_car_name(car_id):
    match car_id:
        case "AE86": return "AE86"
        case "911": return "911 SC"
        case "barracuda": return "Barracuda 440"
        case "mustang": return "Mustang 289"
        case "r34": return "GTR R34"
        case "s1e2": return "Quattro S1 E2"
        case _: return car_id
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
CAR_ID = "AE86"

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
PROFANITY_SET = {"cerise", "orange"} # unused

# Keyboard input settings
KEY_REPEAT_DELAY = 250
KEY_REPEAT_INTERVAL = 35

# ======= DEBUG MODES =======
DEBUG = False
CURSOR_FOLLOW = False
AI_PATH_FOLLOW = False

# ======= FLAGS =======
MODE_CLICKED = False

# ======= STATS =======
USERNAME = None

# ======= TUTORIAL =======
TUTORIAL_MIN_TIME_SCALE = 0.0
TUTORIAL_SLOWDOWN_RATE = 8.0
TUTORIAL_SPEEDUP_RATE = 5.0
TUTORIAL_ACTION_MIN_HOLD_S = 0.35
TUTORIAL_HEADING_DELTA_MIN_RAD = 0.12
TUTORIAL_BRAKE_SPEED_DROP_MIN = 28.0
TUTORIAL_ACCEL_SPEED_GAIN_MIN = 10.0
TUTORIAL_STEER_INPUT_THRESHOLD = 0.45
TUTORIAL_BRAKE_INPUT_THRESHOLD = 0.60
TUTORIAL_ACCEL_INPUT_THRESHOLD = 0.50
TUTORIAL_MIN_TURN_YAW_RATE = 0.40
TUTORIAL_TURN_ONLY_MIN_TIME_SCALE = 0.0
TUTORIAL_ACCEL_ONLY_MIN_TIME_SCALE = 0.0
TUTORIAL_TURN_INPUT_ONLY_SPEED_MAX = 45.0
TUTORIAL_REALTIME_HOLD_STEP = 1.0 / 60.0
TUTORIAL_REALTIME_HOLD_DECAY = 1.0 / 90.0
TUTORIAL_POST_QTE_USER_CONTROL_S = 2.0

TUTORIAL_REWIND_SECONDS = 3.0
TUTORIAL_HARD_CRASH_THRESHOLD = 40.0
TUTORIAL_REWIND_COOLDOWN_S = 1.2

# ======= AI SETTINGS =======
AI_DIFFICULTY = "hard"
AI_USE_LEARNED = False