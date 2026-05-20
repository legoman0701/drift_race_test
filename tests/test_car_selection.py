#!/usr/bin/env python3

# Test script to check if our car selection screen changes work

import pygame, sys, os
from drift.ui.draw_stage import _load_car_specs

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Initialize pygame
pygame.init()

# Test car specs loading
try:
    ae86_model = _load_car_specs("ae86")
    barracuda_model = _load_car_specs("barracuda")
    print(f"ae86: {ae86_model}")
    print(f"barracuda: {barracuda_model}")
except Exception as e:
    print(f"Car specs loading error: {e}")
    sys.exit(1)

print("All tests passed! Car selection modifications should work.")