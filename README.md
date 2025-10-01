# Pygame Drift Car Racing — AI & Multiplayer

Top-down drift racing game built with **pygame-ce**, featuring:
- **Online multiplayer** (host or join via code; the host’s PC acts as the server)
- **AI driving** (player auto-drive and AI opponents)
- **Track chunking** for very large maps
- **Camera zoom/pan** and quality-of-life settings

---

## Controls

### Car
- **Up / Z** — accelerate
- **Down / S** — reverse
- **Left / Q** — steer left
- **Right / D** — steer right
- **Space** — handbrake
- **Cursor-follow mode** — the car follows the mouse cursor *(enable in Settings)*
- **AI pathfinding mode** — the car drives itself using the AI pathfinder *(enable in Settings)*

> Note: Both **ZQSD** and **arrow keys** are supported.

### Lobby Menu
- **H** — host a new game
- **J** — join a game

### In-Game
- **Esc** — open Settings
- **N** — spawn an AI car

---

## Getting Started

### Requirements
- Python 3.11+ (3.12 tested)
- `pygame-ce` 2.5.x
- (Optional) Controller support enabled in-game

### Multiplayer
- The player who hosts acts as the server (peer-hosted).
- The other player(s) join using the generated code.
- Tunneling via playit.gg is supported to reach hosts behind NAT.

---

## Features

### AI modes
- Player auto-drive via pathfinding
- Spawnable AI opponents (N) in both offline and multiplayer
### Drift system
- Drift detection, scoring objects, and tire marks that fade over time
### Large track support
- Image auto-slicing into tiles (slice_map.py)
- Chunked rendering and boundary collisions across tiles
### Camera
- Smooth zoom/dezoom and clamped panning via a camera object
### Audio
- Engine RPM simulation and sound system (gauges, temp sounds)
### UI
- Lobby + in-game settings, improved menus, 64-rotation car sprites (car/shadow/headlights)

---

## Changelog

### oct 01 2025
- v0.6.5 : improved camera logic ; adjusted scaling method for chunk mode
- clean : better track managing
- debug : chunk system tested on a 12k track map
- v0.6.4 : slice_map.py to autoslice track map into tiles
- v0.6.3 : boundary collisions in chunk map system (v2)

### sep 30 2025
- v0.6.2 : new chunk map system (v1)
- v0.6.1 : new 64 rotations car assets (car, shadow, headlights)
- v0.5.15 settings update
- patch : settings -> fixed
- issue : settings ui and functionning
- clean : use of substage for settings instead of stage
- patch : ai cars wasnt being cleared after an error screen -> fixed
- v0.5.14 : better ai (account for speed)
- clean : split files
- v0.5.13 : collisions update ; car data visible in ai mode ; engine sound update
- v0.5.12 : new rpm drift system

### sep 29 2025
- v0.5.11 : new engine sound system
- v0.5.10 : rpm gauges and temporary sounds assets
- v0.5.9 : engine rpm (sound system)
- v0.5.8 : offline mode

### sep 28 2025
- clean : split main.py into multiple files
- v0.5.7 (patch) : detection getting stuck at the track map's end/start points -> fixed
- v0.5.6 (patch) : ai debug surface (red lines) -> fixed
- v0.5.5 : settings update
- v0.5.4 : ai cars now work in multiplayer
- v0.5.3 : ai mode in settings (player car can autodrive)
- v0.5.2 : drift points object (?) and 'N' to spawn ai cars
- v0.5.1 : new ai and path finding algorithm
- v0.4.2/3 : ui updates
- v0.4.1 : new drift detection system ; cursor follow mode ; better menu buttons
- patch : tire pos & duplicate lines -> fixed
- v0.3.11 : switch from pygame to pygame-ce
- patch : "leave room" button -> fixed
- patch : player username input -> fixed

### sep 27 2025
- patch : collision system -> fixed
- patch : camera clamp -> fixed
- patch : tire marks -> fixed
- issue : collision system temporary disabled 
- patch : view fix
- v0.3.10 : new track map and camera clamp fix
- clean : remove unused assets/ae86/image0031.png
- v0.3.9 : ui system rework
- v0.3.8 : new assets (car, shadow and headlights)
- v0.3.7 : headlights via pygame functions (todo: switch to images for perf)
- v0.3.6 : ui menu update
- patch : "leave room" button crashes the game -> fixed
- v0.3.5 : "leave room" button update
- clean : seperate functions
- v0.3.4 : button class ; quick settings upgrade needed to be adjusted
- clean : seperate files ; use of constants

### sep 26 2025
- patch : zoom clamp crash -> fixed
- v0.3.3 : camera object for zoom/dezoom
- v0.3.2 : controller support ; light physics upgrade
- v0.3.1 : ae86 prototype with 32 rotations
- patch : drift_ratio communication -> fixed
- v0.2.4 : tire marks that fade over time
- v0.2.3 : allow higher server tick for better performance and lower latency
- v0.2.2 : collisions upgrade
- debug : auto_run_game.py to launch 2 instances connecting to the same host
- patch : identations issue
- v0.2.1 : better server
- v0.1.5 : physic enhancement ; error handling
- v0.1.4 : Settings in menu ; in-game (Esc)
- clean : comments

### sep 25 2025
- v0.1.3 : better drift detection
- patch : collisions system broken -> fixed
- v0.1.2 : add of collisions system
- v0.1.1 : new physic, drift system enhancement
- v0.1.0 : pygame init

---

## Misc

### Known Issues
- racing ai behavior and not drift racing behavior

### To-Do List
- optimize drift/engine sounds
- multiple car models (ae86, dodge...)
- multiple track maps
- customize keybinds

---

## Demo assets (🚧 update needed 🚧)

### v0.3
![v3-1](assets/demo/v3-1.png)
![v3-2](assets/demo/v3-2.png)
![v3-3](assets/demo/v3-3.png)

### v0.2
![v2-1](assets/demo/v2-1.png)
![v2-2](assets/demo/v2-2.png)
![v2-3](assets/demo/v2-3.png)

### v0.1
![v1-1](assets/demo/v1-1.png)
![v1-2](assets/demo/v1-2.png)
![v1-3](assets/demo/v1-3.png)
