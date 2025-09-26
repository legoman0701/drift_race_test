import subprocess
import sys
import time
import random
import string
import os

PYTHON = sys.executable
GAME_PATH = os.path.abspath("main.py")

def rand_code(n=4):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

def rand_name():
    return "Player" + ''.join(random.choices(string.digits, k=4))

room_code = rand_code()
host_name = rand_name()
join_name = rand_name()

# Launch host (mode=host)
host_proc = subprocess.Popen([
    PYTHON, GAME_PATH, "--mode", "host", "--code", room_code, "--name", host_name
])

# Wait a bit for host to create the room
time.sleep(2)

# Launch joiner (mode=join)
join_proc = subprocess.Popen([
    PYTHON, GAME_PATH, "--mode", "join", "--code", room_code, "--name", join_name
])

print(f"Host room code: {room_code}")
print(f"Host name: {host_name}")
print(f"Join name: {join_name}")

# Optional: Wait for both to finish (or comment out if you want to close manually)
host_proc.wait()
join_proc.wait()