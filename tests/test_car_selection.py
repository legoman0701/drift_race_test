#!/usr/bin/env python3

# Test script to check if our car selection screen changes work

import pygame
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Initialize pygame
pygame.init()

# Test imports
try:
    from drift.ui.draw_stage import draw_new_game, _load_car_specs
    from tools.paths import asset_path
    print("✓ Imports successful")
except Exception as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)

# Test car specs loading
try:
    ae86_manufacturer, ae86_model = _load_car_specs("ae86")
    m5_manufacturer, m5_model = _load_car_specs("m5")
    print(f"✓ ae86: {ae86_manufacturer} {ae86_model}")
    print(f"✓ m5: {m5_manufacturer} {m5_model}")
except Exception as e:
    print(f"✗ Car specs loading error: {e}")
    sys.exit(1)

print("✓ All tests passed! Car selection modifications should work.")