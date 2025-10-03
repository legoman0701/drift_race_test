#!/usr/bin/env python3
"""
Test script to run the best trained AI network
"""

import pygame
import sys
import math
import numpy as np
import pickle
import os

# Import from our main AI environment
from ai_env import AITrainingEnv, NeuralNetwork, create_black_mask, draw_cars_fast, raycast_black_mask
import const, car

def load_best_network(filename="ai_models\generation_105.pkl"):
    """Load the best trained network"""
    if os.path.exists(filename):
        with open(filename, 'rb') as f:
            data = pickle.load(f)
            
        arch = data['architecture']
        network = NeuralNetwork(arch['input_size'], arch['hidden_sizes'], arch['output_size'])
        network.set_weights(data['weights'])
        
        print(f"Loaded best network (fitness: {data['fitness']:.3f}) from generation {data['generation']}")
        return network
    else:
        print(f"No saved network found at {filename}")
        return None

def main():
    pygame.init()
    
    # Load track
    track_image = pygame.image.load(f"assets/Map/Map{const.MAP_NUM}.png")
    track_mask_img = pygame.image.load(f"assets/Map/Map{const.MAP_NUM}_ring.png")
    scaled_track = pygame.transform.scale_by(track_image, (0.5, 0.5))

    pygame.display.set_caption("Drift Race - Best AI Demo")
    screen = pygame.display.set_mode((scaled_track.get_width(), scaled_track.get_height()))
    track_image = track_image.convert()
    scaled_track = scaled_track.convert()

    # Create mask
    track_mask_img = track_mask_img.convert()
    full_mask = create_black_mask(track_mask_img)
    mask_surf = full_mask.to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
    mask_surf = mask_surf.convert_alpha()
    scaled_mask_surf = pygame.transform.scale_by(mask_surf, (0.5, 0.5))
    scaled_mask = pygame.mask.from_surface(scaled_mask_surf)

    # Load best AI
    best_network = load_best_network()
    if best_network is None:
        print("No trained network found. Please run ai_env.py first to train a network.")
        return

    # Create environment with single car
    training_env = AITrainingEnv(scaled_mask, 1)
    clock = pygame.time.Clock()
    
    print("Running best AI network...")
    print("Press ESC to exit")
    
    observations = training_env.reset()
    episode_reward = 0
    episode_steps = 0
    
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit(0)
                elif ev.key == pygame.K_SPACE:
                    # Reset on spacebar
                    observations = training_env.reset()
                    episode_reward = 0
                    episode_steps = 0
                    print("Environment reset")
        
        # Get AI action
        if isinstance(observations, list):
            obs = observations[0]
        else:
            obs = observations
            
        action = best_network.forward(obs)
        
        # Step environment
        next_observations, rewards, dones, info = training_env.step([action])
        
        episode_reward += rewards[0]
        episode_steps += 1
        observations = next_observations
        
        # Reset if done
        if dones[0] or episode_steps >= 2000:
            print(f"Episode finished! Steps: {episode_steps}, Reward: {episode_reward:.3f}")
            observations = training_env.reset()
            episode_reward = 0
            episode_steps = 0
        
        # Visualization
        screen.blit(scaled_track, (0, 0))
        draw_cars_fast(screen, training_env.cars)
        
        # Draw raycasts
        if training_env.cars:
            c0 = training_env.cars[0]
            for ray_angle in training_env.raycast_radians:
                rx, ry, rd, hit = raycast_black_mask(scaled_mask, c0.x * 0.5, c0.y * 0.5, c0.angle+ray_angle, 400.0)
                if hit:
                    pygame.draw.circle(screen, (0, 255, 0), (int(rx), int(ry)), 2)
                    pygame.draw.line(screen, (0, 255, 0), (int(c0.x*0.5), int(c0.y*0.5)), (int(rx), int(ry)), 1)
        
        # Draw info
        font = pygame.font.Font(None, 24)
        info_lines = [
            f"Best AI Demo - Steps: {episode_steps}",
            f"Episode Reward: {episode_reward:.3f}",
            f"Speed: {math.sqrt(training_env.cars[0].vx**2 + training_env.cars[0].vy**2):.1f}" if training_env.cars else "",
            "Press SPACE to reset, ESC to exit"
        ]
        
        for i, line in enumerate(info_lines):
            text = font.render(line, True, (255, 255, 255))
            screen.blit(text, (10, 10 + i * 25))
    
        pygame.display.flip()
        clock.tick(const.FPS)

if __name__ == "__main__":
    main()