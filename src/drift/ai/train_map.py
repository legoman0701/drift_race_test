#!/usr/bin/env python3
"""Train drift AI per map: python -m drift.ai.train_map --map 1 --difficulty hard --generations 80"""

import argparse
import os
import sys
from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import drift.config.const as const
from drift.tools.paths import asset_path, normalize_asset_path
from ai_env import AITrainingEnv, GeneticAlgorithm, create_black_mask

DIFFICULTY_REWARD_SCALE = {
    "easy": {"drift": 0.4, "speed": 0.7},
    "medium": {"drift": 1.0, "speed": 1.0},
    "hard": {"drift": 1.6, "speed": 1.2},
}


class MapDriftTrainingEnv(AITrainingEnv):
    def __init__(self, track_mask, num_cars, difficulty):
        super().__init__(track_mask, num_cars=num_cars)
        self.scale = DIFFICULTY_REWARD_SCALE.get(difficulty, DIFFICULTY_REWARD_SCALE["medium"])

    def calculate_reward(self, car_obj, prev_speed, prev_x, prev_y):
        reward = super().calculate_reward(car_obj, prev_speed, prev_x, prev_y)
        import math
        forward_v = car_obj.vx * math.cos(car_obj.angle) + car_obj.vy * math.sin(car_obj.angle)
        if 0.35 < car_obj.drift_ratio < 0.85 and forward_v > 70:
            reward += 2.0 * car_obj.drift_ratio * self.scale["drift"]
        if forward_v > 40:
            reward += forward_v * 0.02 * self.scale["speed"]
        return reward


def train(map_num, difficulty, generations, population):
    pygame.init()
    ring_path = normalize_asset_path("track", f"map{map_num}", "ring.png")
    mask = create_black_mask(pygame.image.load(ring_path).convert())
    env = MapDriftTrainingEnv(mask, population, difficulty)
    ga = GeneticAlgorithm(population_size=population)

    for gen in range(1, generations + 1):
        obs = env.reset()
        fitness = [0.0] * ga.population_size
        done = False
        steps = 0
        while not done and steps < env.max_episode_steps:
            actions = [ga.population[i].forward(obs[i % len(obs)]) for i in range(ga.population_size)]
            obs, rewards, dones, _ = env.step(actions)
            for i, r in enumerate(rewards):
                fitness[i] += r
            done = bool(dones[0])
            steps += 1
        for i, f in enumerate(fitness):
            ga.evaluate_fitness(i, f)
        ga.evolve()
        print(f"Gen {gen}/{generations} best={ga.best_fitness:.3f}")

    out_dir = asset_path("ai_models")
    os.makedirs(out_dir, exist_ok=True)
    ga.save_best(str(out_dir / f"map{map_num}_{difficulty}.pkl"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--map", type=int, default=const.MAP_NUM)
    p.add_argument("--difficulty", choices=["easy", "medium", "hard"], default="medium")
    p.add_argument("--generations", type=int, default=80)
    p.add_argument("--population", type=int, default=30)
    args = p.parse_args()
    train(args.map, args.difficulty, args.generations, args.population)


if __name__ == "__main__":
    main()