#!/usr/bin/env python3

# ======= IMPORTS =======

# global imports
import pygame, sys, math, pickle, os, numpy as np

# local imports (only what's needed for local play)
from drift.tools.paths import normalize_asset_path
import drift.config.const as const, drift.core.car as car
from drift.core.helpers import clamp

# ======= CONFIGURATION =======

flags = const.FLAGS

# ======= NEURAL NETWORK AND GENETIC ALGORITHM =======

class LowPassFilter:
    """Simple low pass filter for smoothing AI outputs"""
    
    def __init__(self, alpha=0.1):
        """
        Initialize low pass filter
        
        Args:
            alpha (float): Smoothing factor (0-1). Higher values = less smoothing, more responsive.
                          0.5 = equal weight to current and previous
                          0.8 = more weight to current (less smoothing)
                          0.3 = more weight to previous (more smoothing)
        """
        self.alpha = alpha
        self.previous_output = None
        
    def filter(self, current_input):
        """Apply low pass filter to input"""
        if self.previous_output is None:
            # First call - no previous output to filter with
            self.previous_output = np.array(current_input)
            return self.previous_output.copy()
        
        # Low pass filter: output = alpha * current + (1-alpha) * previous
        filtered_output = self.alpha * np.array(current_input) + (1 - self.alpha) * self.previous_output
        self.previous_output = filtered_output.copy()
        return filtered_output
    
    def reset(self):
        """Reset filter state"""
        self.previous_output = None

class NeuralNetwork:
    """Simple feedforward neural network for car control"""
    
    def __init__(self, input_size=15, hidden_sizes=[20, 15], output_size=3):
        self.input_size = input_size
        self.hidden_sizes = hidden_sizes
        self.output_size = output_size
        self.layers = []
        
        # Initialize network layers
        layer_sizes = [input_size] + hidden_sizes + [output_size]
        for i in range(len(layer_sizes) - 1):
            # Xavier initialization
            weight = np.random.randn(layer_sizes[i], layer_sizes[i+1]) * np.sqrt(2.0 / layer_sizes[i])
            bias = np.zeros((1, layer_sizes[i+1]))
            self.layers.append({'weight': weight, 'bias': bias})
    
    def forward(self, inputs):
        """Forward pass through the network"""
        x = np.array(inputs).reshape(1, -1)
        
        for i, layer in enumerate(self.layers):
            x = np.dot(x, layer['weight']) + layer['bias']
            # Use tanh activation for hidden layers, sigmoid for output
            if i < len(self.layers) - 1:
                x = np.tanh(x)
            else:
                # Custom activation for output: tanh for throttle/steering, sigmoid for brake
                x = np.concatenate([
                    np.tanh(x[:, :2]),  # throttle and steering (-1 to 1)
                    1.0 / (1.0 + np.exp(-x[:, 2:]))  # brake (0 to 1)
                ], axis=1)
        
        return x.flatten()
    
    def get_weights(self):
        """Get all weights and biases as a flat array"""
        weights = []
        for layer in self.layers:
            weights.extend(layer['weight'].flatten())
            weights.extend(layer['bias'].flatten())
        return np.array(weights)
    
    def set_weights(self, weights):
        """Set weights and biases from a flat array"""
        idx = 0
        for layer in self.layers:
            w_size = layer['weight'].size
            b_size = layer['bias'].size
            
            layer['weight'] = weights[idx:idx+w_size].reshape(layer['weight'].shape)
            idx += w_size
            layer['bias'] = weights[idx:idx+b_size].reshape(layer['bias'].shape)
            idx += b_size
    
    def mutate(self, mutation_rate=0.1, mutation_strength=0.2, targeted=False):
        """Mutate the network weights with improved strategy"""
        for i, layer in enumerate(self.layers):
            # Use different mutation strategies
            if targeted:
                # For targeted mutation, focus more on later layers (output layers)
                layer_factor = (i + 1) / len(self.layers)
                effective_rate = mutation_rate * (0.5 + layer_factor)
                effective_strength = mutation_strength * (0.8 + 0.4 * layer_factor)
            else:
                effective_rate = mutation_rate
                effective_strength = mutation_strength
            
            # Mutate weights with adaptive Gaussian noise
            mask = np.random.random(layer['weight'].shape) < effective_rate
            # Use both small and large mutations for diversity
            small_mutations = np.random.normal(0, effective_strength * 0.5, layer['weight'].shape)
            large_mutations = np.random.normal(0, effective_strength * 2.0, layer['weight'].shape)
            mutation_choice = np.random.random(layer['weight'].shape) < 0.8  # 80% small, 20% large
            mutations = np.where(mutation_choice, small_mutations, large_mutations)
            layer['weight'] += mask * mutations
            
            # Mutate biases
            mask = np.random.random(layer['bias'].shape) < effective_rate
            small_mutations = np.random.normal(0, effective_strength * 0.5, layer['bias'].shape)
            large_mutations = np.random.normal(0, effective_strength * 2.0, layer['bias'].shape)
            mutation_choice = np.random.random(layer['bias'].shape) < 0.8
            mutations = np.where(mutation_choice, small_mutations, large_mutations)
            layer['bias'] += mask * mutations
    
    def copy(self):
        """Create a copy of this network"""
        new_net = NeuralNetwork(self.input_size, self.hidden_sizes, self.output_size)
        new_net.set_weights(self.get_weights())
        return new_net

class GeneticAlgorithm:
    """Genetic algorithm for evolving neural networks"""
    
    def __init__(self, population_size=50, input_size=15, hidden_sizes=[20, 15], output_size=3):
        self.population_size = population_size
        self.generation = 0
        self.input_size = input_size
        self.hidden_sizes = hidden_sizes
        self.output_size = output_size
        
        # Create initial population
        self.population = []
        self.fitness_scores = []
        
        for _ in range(population_size):
            network = NeuralNetwork(input_size, hidden_sizes, output_size)
            self.population.append(network)
        
        self.fitness_scores = [0.0] * population_size
        self.best_fitness = float('-inf')
        self.best_network = None
        
    def evaluate_fitness(self, network_idx, fitness):
        """Update fitness score for a network"""
        self.fitness_scores[network_idx] = fitness
        
        if fitness > self.best_fitness:
            self.best_fitness = fitness
            self.best_network = self.population[network_idx].copy()
    
    def evolve(self):
        """Evolve the population to the next generation"""
        self.generation += 1
        
        # Sort population by fitness
        sorted_indices = np.argsort(self.fitness_scores)[::-1]
        
        
        # Keep top performers (elitism)
        elite_count = max(1, self.population_size // 10)
        new_population = []
        
        # Keep elite
        for i in range(elite_count):
            new_population.append(self.population[sorted_indices[i]].copy())
        
        # Calculate adaptive mutation parameters
        base_mutation_rate = 0.005
        base_mutation_strength = 0.003
        
        # Determine fitness thresholds for targeted mutation
        fitness_array = np.array(self.fitness_scores)
        median_fitness = np.median(fitness_array)
        top_25_fitness = np.percentile(fitness_array, 75)
        
        # Fill rest with offspring
        explorer_count = 0  # Track high-mutation explorers
        while len(new_population) < self.population_size:
            # Tournament selection
            parent1 = self.tournament_select()
            parent2 = self.tournament_select()
            
            # Crossover
            child = self.crossover(parent1, parent2)
            
            # Determine mutation strategy based on position in population
            current_position = len(new_population)
            
            if explorer_count < 5:  # Ensure 5 high-mutation explorers
                # High mutation for exploration
                mutation_rate = base_mutation_rate * 3.0
                mutation_strength = base_mutation_strength * 2.5
                child.mutate(mutation_rate=mutation_rate, mutation_strength=mutation_strength, targeted=False)
                explorer_count += 1
            elif current_position < elite_count + self.population_size * 0.3:  # Top 30% get targeted mutation
                # Lower mutation for fine-tuning
                mutation_rate = base_mutation_rate * 0.6
                mutation_strength = base_mutation_strength * 0.7
                child.mutate(mutation_rate=mutation_rate, mutation_strength=mutation_strength, targeted=True)
            else:  # Rest get standard adaptive mutation
                child.mutate(mutation_rate=base_mutation_rate, mutation_strength=base_mutation_strength, targeted=False)
            
            new_population.append(child)
        
        self.population = new_population
        self.fitness_scores = [0.0] * self.population_size
    
    def tournament_select(self, tournament_size=3):
        """Tournament selection for choosing parents"""
        tournament_indices = np.random.choice(len(self.population), tournament_size, replace=False)
        tournament_fitness = [self.fitness_scores[i] for i in tournament_indices]
        winner_idx = tournament_indices[np.argmax(tournament_fitness)]
        return self.population[winner_idx]
    
    def crossover(self, parent1, parent2):
        """Create offspring through crossover"""
        child = NeuralNetwork(self.input_size, self.hidden_sizes, self.output_size)
        
        weights1 = parent1.get_weights()
        weights2 = parent2.get_weights()
        
        # Uniform crossover
        mask = np.random.random(len(weights1)) < 0.5
        child_weights = np.where(mask, weights1, weights2)
        
        child.set_weights(child_weights)
        return child
    
    def save_best(self, filename="best_network.pkl"):
        """Save the best network to file"""
        if self.best_network is not None:
            with open(normalize_asset_path(filename), 'wb') as f:
                pickle.dump({
                    'weights': self.best_network.get_weights(),
                    'architecture': {
                        'input_size': self.input_size,
                        'hidden_sizes': self.hidden_sizes,
                        'output_size': self.output_size
                    },
                    'generation': self.generation,
                    'fitness': self.best_fitness
                }, f)
            print(f"Saved best network (fitness: {self.best_fitness:.3f}) to {filename}")
    
    def load_best(self, filename="best_network.pkl"):
        """Load the best network from file"""
        # Handle relative paths by adding ai_models/ if needed
        if not filename.startswith('ai_models/') and not os.path.isabs(filename):
            if not filename.startswith('ai_models\\'):
                filename = f"ai_models/{filename}"
        
        if os.path.exists(filename):
            try:
                with open(normalize_asset_path(filename), 'rb') as f:
                    data = pickle.load(f)
                    
                arch = data['architecture']
                self.best_network = NeuralNetwork(arch['input_size'], arch['hidden_sizes'], arch['output_size'])
                self.best_network.set_weights(data['weights'])
                self.best_fitness = data['fitness']
                self.generation = data['generation']
                
                print(f"Loaded network (fitness: {self.best_fitness:.3f}) from generation {self.generation}")
                return True
            except Exception as e:
                print(f"Error loading {filename}: {e}")
                return False
        else:
            print(f"File not found: {filename}")
            return False

# ======= GENERATION LOADING UTILITIES =======

def get_available_generations():
    """Get list of available generation files"""
    models_dir = "ai_models"
    if not os.path.exists(models_dir):
        return []
    
    generation_files = []
    for filename in os.listdir(models_dir):
        if filename.startswith("generation_") and filename.endswith(".pkl"):
            try:
                gen_num = int(filename.replace("generation_", "").replace(".pkl", ""))
                generation_files.append((gen_num, filename))
            except ValueError:
                continue
    
    # Also check for best_network.pkl and final_generation files
    if os.path.exists(os.path.join(models_dir, "best_network.pkl")):
        generation_files.append((-1, "best_network.pkl"))  # -1 for best
    
    for filename in os.listdir(models_dir):
        if filename.startswith("final_generation_") and filename.endswith(".pkl"):
            try:
                gen_num = int(filename.replace("final_generation_", "").replace(".pkl", ""))
                generation_files.append((gen_num, filename, True))  # True for final
            except ValueError:
                continue
    
    return sorted(generation_files)

def select_generation_to_load():
    """Interactive generation selection"""
    available = get_available_generations()
    
    if not available:
        print("No saved generations found.")
        return None
    
    print("\nAvailable generations:")
    print("0. Start fresh (no loading)")
    
    for i, item in enumerate(available):
        if len(item) == 3:  # final generation
            gen_num, filename, is_final = item
            print(f"{i+1}. Generation {gen_num} (FINAL) - {filename}")
        elif item[0] == -1:  # best network
            print(f"{i+1}. Best Network - {item[1]}")
        else:
            gen_num, filename = item
            print(f"{i+1}. Generation {gen_num} - {filename}")
    
    while True:
        try:
            choice = input(f"\nSelect generation to load (0-{len(available)}): ").strip()
            choice_num = int(choice)
            
            if choice_num == 0:
                return None
            elif 1 <= choice_num <= len(available):
                selected = available[choice_num - 1]
                filename = selected[1]
                return os.path.join("ai_models", filename)
            else:
                print(f"Please enter a number between 0 and {len(available)}")
        except ValueError:
            print("Please enter a valid number")
        except KeyboardInterrupt:
            print("\nCancelled.")
            return None

def load_generation_from_args():
    """Load generation from command line arguments"""
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        
        # Check if it's a generation number
        try:
            gen_num = int(arg)
            filename = f"ai_models/generation_{gen_num}.pkl"
            if os.path.exists(filename):
                return filename
            else:
                print(f"Generation {gen_num} not found: {filename}")
                return None
        except ValueError:
            # Check if it's a filename
            if arg.endswith('.pkl'):
                if not arg.startswith('ai_models/'):
                    filename = f"ai_models/{arg}"
                else:
                    filename = arg
                
                if os.path.exists(filename):
                    return filename
                else:
                    print(f"File not found: {filename}")
                    return None
            else:
                print(f"Invalid argument: {arg}")
                print("Usage: python ai_env.py [generation_number] or [filename.pkl]")
                return None
    
    return None

# ======= AI TRAINING ENVIRONMENT =======

class AITrainingEnv:
    """Training environment for AI cars using speed, angle, drift_ratio, angular_velocity + raycasting"""
    
    def __init__(self, track_mask, num_cars=1):
        self.track_mask = track_mask
        self.num_cars = num_cars
        self.cars = []
        self.crashed_cars = set()  # Track which cars have crashed
        self.raycast_angles = [-80, -40, -20, -10, -5, 0, 5, 10, 20, 40, 80]  # degrees
        self.raycast_radians = [math.radians(a) for a in self.raycast_angles]
        self.max_raycast_dist = 400.0
        self.episode_steps = 0
        self.max_episode_steps = 2000
        
        # Initialize low pass filters for each car's AI output
        # Separate filters for throttle, steering, brake with different smoothing
        self.output_filters = []
        for _ in range(num_cars):
            car_filters = {
                'throttle': LowPassFilter(alpha=0.8),  # Less smoothing for throttle (more responsive)
                'steering': LowPassFilter(alpha=0.8),  # More smoothing for steering (reduce oscillation)
                'brake': LowPassFilter(alpha=0.8)      # Less smoothing for brake (quick response needed)
            }
            self.output_filters.append(car_filters)
        
        # Initialize cars at random valid positions
        self.reset()
        
    def reset(self):
        """Reset environment and place cars at valid starting positions"""
        self.cars = []
        self.crashed_cars = set()
        self.episode_steps = 0
        
        # Reset all output filters
        for car_filters in self.output_filters:
            for filter_obj in car_filters.values():
                filter_obj.reset()
        
        for i in range(self.num_cars):
            # All cars spawn at (1000, 450) with angle 0
            new_car = car.Car(1000, 450, f"AI_{i}", is_ai=True)
            new_car.angle = 0
            # Initialize some forward velocity
            new_car.vx = math.cos(new_car.angle) * 100
            new_car.vy = math.sin(new_car.angle) * 100
            self.cars.append(new_car)
        
        return self.get_observations()
    
    def get_observations(self):
        """Get current state observations for all cars
        
        Returns:
            list or array: Observations for each car containing:
                - speed_x (normalized)
                - speed_y (normalized)
                - angle_cos (normalized vector component)
                - angle_sin (normalized vector component)
                - drift_ratio
                - angular_velocity (normalized)
                - 9 raycast distances (normalized)
        """
        observations = []
        
        for i in range(len(self.cars)):
            car_obj = self.cars[i]
            # Get basic car state
            forward_v = (car_obj.vx * math.cos(car_obj.angle) + car_obj.vy * math.sin(car_obj.angle))
            forward_v = clamp(forward_v / 1000.0, -1.0, 1.0)  # normalize to [-1, 1]
            lateral_v = (-car_obj.vx * math.sin(car_obj.angle) + car_obj.vy * math.cos(car_obj.angle))/1000
            
            state = [
                forward_v,
                lateral_v,
                car_obj.drift_ratio,  # already in [0,1]
                clamp(car_obj.v_angle / 100.0, -1.0, 1.0),  # normalize angular velocity
            ]
            
            # Add raycasting data
            raycast_distances = []
            for ray_angle in self.raycast_radians:
                rx, ry, dist, hit = raycast_black_mask(
                    self.track_mask, 
                    car_obj.x * 0.5,  # scale to match mask
                    car_obj.y * 0.5,
                    car_obj.angle + ray_angle, 
                    self.max_raycast_dist
                )
                # Normalize distance
                normalized_dist = dist / self.max_raycast_dist if hit else 1.0
                raycast_distances.append(normalized_dist)
            
            # Combine car state + raycast data (6 + 9 = 15 total inputs)
            full_observation = state + raycast_distances
            observations.append(np.array(full_observation, dtype=np.float32))
        
        return observations
    
    def step(self, actions):
        """Step the environment with AI actions, removing crashed cars
        
        Args:
            actions: List of action arrays [throttle, steering, brake] for each active car
                    or single action array if only one car
        
        Returns:
            tuple: (observations, rewards, dones, info)
        """
        dt = 1.0 / const.FPS
        self.episode_steps += 1
        
        # Ensure actions is a list for multiple cars
        if not isinstance(actions, list):
            actions = [actions]
        
        rewards = []
        dones = []
        info = []
        
        # Process all cars (including crashed ones)
        for car_idx in range(min(len(self.cars), len(actions))):
            car_obj = self.cars[car_idx]
            action = actions[car_idx]
            
            # Apply low pass filtering to AI output for smoother control
            if car_idx < len(self.output_filters):
                filters = self.output_filters[car_idx]
                
                # Filter each output component separately
                filtered_throttle = filters['throttle'].filter([action[0]])[0]
                filtered_steering = filters['steering'].filter([action[1]])[0]
                filtered_brake = filters['brake'].filter([action[2]])[0]
                
                # Create filtered action
                filtered_action = [filtered_throttle, filtered_steering, filtered_brake]
            else:
                # Fallback if no filter available
                filtered_action = action
            
            # Convert AI output to car inputs
            inputs = {
                "th": clamp(filtered_action[0], 0.0, 1.0),  # throttle
                "st": clamp(filtered_action[1], -1.0, 1.0),  # steering  
                "br": clamp(filtered_action[2], 0.0, 1.0)   # brake
            }
            
            # Store previous state for reward calculation
            prev_speed = math.sqrt(car_obj.vx**2 + car_obj.vy**2)
            prev_x, prev_y = car_obj.x, car_obj.y
            
            # Only step the car if it hasn't crashed
            if car_idx not in self.crashed_cars:
                car_obj.step(inputs, dt, {}, (50000, 50000))
            
            # Check if car crashed (went off track)
            crashed = self.is_done(car_obj)
            
            
            
            if crashed:
                # Give large negative reward for crashing but don't remove from pool
                reward = -200.0
                # Mark as crashed but keep in genetic pool
                if car_idx not in self.crashed_cars:
                    self.crashed_cars.add(car_idx)
                    print(f"Car {car_idx} crashed!")
            elif car_idx in self.crashed_cars:
                # Car was already crashed, give small continuing penalty
                reward = -1.0
            else:
                # Calculate normal reward
                reward = self.calculate_reward(car_obj, prev_speed, prev_x, prev_y)
            
            rewards.append(reward)
            dones.append(crashed)
            
            # Additional info for debugging
            current_speed = math.sqrt(car_obj.vx**2 + car_obj.vy**2)
            info.append({
                'speed': current_speed,
                'drift_ratio': car_obj.drift_ratio,
                'episode_steps': self.episode_steps,
                'car_index': car_idx,
                'crashed': crashed
            })
        
        # Don't remove crashed cars - they stay in genetic pool with poor fitness
        # Remove cars_to_remove logic since we're keeping all cars
        
        # Check if episode should end (max steps reached or all cars have crashed)
        all_cars_crashed = len(self.crashed_cars) == self.num_cars
        episode_done = all_cars_crashed or self.episode_steps >= self.max_episode_steps
        
        observations = self.get_observations()
        
        return observations, rewards, [episode_done], info
    
    def calculate_reward(self, car_obj, prev_speed, prev_x, prev_y):
        """Calculate reward for a car's current state"""
        reward = 0.0
        
        # Current state
        #current_speed = math.sqrt(car_obj.vx**2 + car_obj.vy**2)
        forward_v = (car_obj.vx * math.cos(car_obj.angle) + car_obj.vy * math.sin(car_obj.angle))
        distance_moved = math.sqrt((car_obj.x - prev_x)**2 + (car_obj.y - prev_y)**2)
        
        if forward_v < 0: forward_v*=5
        
        # Reward for maintaining speed (encourage movement)
        
        if forward_v > 30 or forward_v < 0:
            reward += forward_v * 0.05
        
        # Reward for distance traveled
        #reward += distance_moved * 0.01
        
        # Get closest wall distance
        min_wall_distance = float('inf')
        for ray_angle in self.raycast_radians:
            _, _, dist, hit = raycast_black_mask(
                self.track_mask,
                car_obj.x * 0.5,
                car_obj.y * 0.5,
                car_obj.angle + ray_angle,
                self.max_raycast_dist
            )
            if hit and dist < min_wall_distance:
                min_wall_distance = dist
        
        if min_wall_distance < 10:
            reward -= 1
            
        # Bonus for controlled drifting at speed
        if 0.5 < car_obj.drift_ratio and forward_v > 100:
            reward += car_obj.drift_ratio
        
        # Penalty for excessive drifting
        if 0.5 < car_obj.drift_ratio and forward_v < 50:
            reward -= 0.2
        
        # Penalty for going too slow
        if forward_v < 30:
            reward -= 0.5
        
        return reward
    
    def is_done(self, car_obj):
        """Check if episode should end for this car"""
        # Check collision with walls
        car_x, car_y = int(car_obj.x * 0.5), int(car_obj.y * 0.5)
        
        # Check bounds
        if (car_x < 0 or car_x >= self.track_mask.get_size()[0] or 
            car_y < 0 or car_y >= self.track_mask.get_size()[1]):
            return True
            
        # Check wall collision
        if self.track_mask.get_at((car_x, car_y)):
            return True
            
        return False
    
    def get_observation_space_size(self):
        """Get the size of the observation space (for neural network input layer)"""
        return 15  # 4 car state + 9 raycast distances
    
    def get_action_space_size(self):
        """Get the size of the action space (for neural network output layer)"""
        return 3  # throttle, steering, brake
    
    def get_active_cars(self):
        """Get list of all cars for rendering (crashed cars are still rendered)"""
        return self.cars
    
    def get_num_active_cars(self):
        """Get number of cars that haven't crashed yet"""
        return self.num_cars - len(self.crashed_cars)

# ======= MAIN LOOP =======

# Ultra-fast car drawing: oriented filled rectangle + small nose tick.
# Avoids per-car surface creation/rotation and minimizes Python overhead.
def draw_cars_fast(surface: pygame.Surface, cars_list):
    draw_polygon = pygame.draw.polygon
    draw_line = pygame.draw.line
    COLOR_BODY = const.COLOR_BODY_DEFAULT
    COLOR_NOSE = const.COLOR_NOSE_DEFAULT
    halfL = car.CAR_LEN * 0.5
    halfW = car.CAR_WID * 0.5
    int_ = int
    cos, sin = math.cos, math.sin

    for c in cars_list:
        x, y, a = c.x, c.y, c.angle
        ca, sa = cos(a), sin(a)

        # Compute 4 oriented corners (manual unroll for speed)
        # Local corners: (+L,+W), (+L,-W), (-L,-W), (-L,+W)
        pts = []
        rx = (+halfL) * ca - (+halfW) * sa; ry = (+halfL) * sa + (+halfW) * ca; pts.append((int_((x + rx) * 0.5), int_((y + ry) * 0.5)))
        rx = (+halfL) * ca - (-halfW) * sa; ry = (+halfL) * sa + (-halfW) * ca; pts.append((int_((x + rx) * 0.5), int_((y + ry) * 0.5)))
        rx = (-halfL) * ca - (-halfW) * sa; ry = (-halfL) * sa + (-halfW) * ca; pts.append((int_((x + rx) * 0.5), int_((y + ry) * 0.5)))
        rx = (-halfL) * ca - (+halfW) * sa; ry = (-halfL) * sa + (+halfW) * ca; pts.append((int_((x + rx) * 0.5), int_((y + ry) * 0.5)))

        draw_polygon(surface, COLOR_BODY, pts)

        # Nose line from front center
        fx, fy = ca, sa
        front_x = x + fx * halfL
        front_y = y + fy * halfL
        nose_x = front_x + fx * 8.0
        nose_y = front_y + fy * 8.0
        draw_line(surface, COLOR_NOSE, (int_(front_x * 0.5), int_(front_y * 0.5)), (int_(nose_x * 0.5), int_(nose_y * 0.5)), 2)


# ======= FAST RAYCASTING (mask-based) =======

def create_black_mask(mask_surface: pygame.Surface) -> pygame.Mask:
    """Return a pygame.Mask where a bit is set for black (near-black) pixels.

    This lets us query "is this pixel black?" with fast C-level bit lookups.
    Expectation: The provided surface uses black for collision and non-black for free space.
    """
    # Ensure the surface matches display format for fastest pixel access first.
    # Note: convert() requires a display surface to be set. We call this after set_mode in main.
    surf = mask_surface.convert()
    # from_threshold picks pixels within a color difference threshold from the target color.
    # Using a tiny threshold to include near-black compression artifacts.
    black_mask = pygame.mask.from_threshold(surf, (0, 0, 0), (2, 2, 2))
    return black_mask


def raycast_black_mask(mask: pygame.Mask, x0: float, y0: float, angle: float, max_dist: float):
    # Convert to integer grid start
    x_start = int(x0)
    y_start = int(y0)

    # Compute end point using angle and max distance (rounded to nearest pixel)
    ca = math.cos(angle)
    sa = math.sin(angle)

    # If already on black, immediate hit
    if mask.get_at((x_start, y_start)):
        return x_start, y_start, 0.0, True

    # Integer Bresenham setup
    x_finder = x_start
    y_finder = y_start

    # Precompute squared max distance to allow early stop
    max_dist_sq = max_dist * max_dist

    while True:
        x_finder += ca*20
        y_finder += sa*20
        
        dist_x = x_finder - x_start
        dist_y = y_finder - y_start
        
        if (dist_x * dist_x + dist_y * dist_y) > max_dist_sq:
            dist = math.hypot(x_finder - x_start, y_finder - y_start)
            return x_finder, y_finder, dist, False

        # Check black hit
        if mask.get_at((int(x_finder), int(y_finder))):
            for i in range(20):
                x_finder -= ca
                y_finder -= sa
                if not mask.get_at((int(x_finder), int(y_finder))):
                    dist = math.hypot(x_finder - x_start, y_finder - y_start)
                    return x_finder, y_finder, dist, True
            dist = math.hypot(x_finder - x_start, y_finder - y_start)
            return x_finder, y_finder, dist, True
def main():
    pygame.init()
    pygame.joystick.init()

    # Load image before setting the display; convert after display is initialized
    track_image = pygame.image.load(normalize_asset_path("track", f"map{const.MAP_NUM}", "main.png"))
    track_mask_img = pygame.image.load(normalize_asset_path("track", f"map{const.MAP_NUM}", "ring.png"))
    scaled_track = pygame.transform.scale_by(track_image, (0.5, 0.5))

    pygame.display.set_caption("Drift Race - AI Training with Neural Network")
    screen = pygame.display.set_mode((scaled_track.get_width(), scaled_track.get_height()))
    track_image = track_image.convert()
    screen = pygame.display.set_mode((scaled_track.get_width(), scaled_track.get_height()), const.FLAGS)
    track_image = track_image.convert()
    scaled_track = scaled_track.convert()

    # Build a collision mask from the ring image, and scale to match render scale (0.5x)
    track_mask_img = track_mask_img.convert()
    full_mask = create_black_mask(track_mask_img)
    mask_surf = full_mask.to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
    mask_surf = mask_surf.convert_alpha()
    scaled_mask_surf = pygame.transform.scale_by(mask_surf, (0.5, 0.5))
    scaled_mask = pygame.mask.from_surface(scaled_mask_surf)

    # Initialize AI Training Environment and Genetic Algorithm
    population_size = 100
    training_env = AITrainingEnv(scaled_mask, population_size)
    genetic_algo = GeneticAlgorithm(
        population_size=population_size,
        input_size=training_env.get_observation_space_size(),
        hidden_sizes=[24, 18],
        output_size=training_env.get_action_space_size()
    )
    
    # Load generation (command line args, interactive, or default)
    model_to_load = load_generation_from_args()
    
    if model_to_load is None:
        # No command line argument, offer interactive selection
        print("\n" + "="*50)
        print("AI NEURAL NETWORK TRAINING - GENERATION LOADER")
        print("="*50)
        model_to_load = select_generation_to_load()
    
    # Load the selected model
    if model_to_load:
        if genetic_algo.load_best(model_to_load):
            print(f"Successfully loaded: {model_to_load}")
        else:
            print(f"Failed to load: {model_to_load}")
            print("Starting with fresh population.")
    else:
        print("Starting with fresh population.")
    
    # Training variables
    generation_episodes = 1  # Episodes per generation
    current_episode = 0
    episode_steps = 0
    max_episode_steps = 2000
    car_fitness_scores = [0.0] * population_size
    episode_rewards = [[] for _ in range(population_size)]
    quit_requested = False  # Flag for graceful shutdown
    
    print(f"\nStarting Neural Network Training")
    print(f"Usage: python ai_env.py [generation_number] or [filename.pkl]")
    print(f"Population size: {population_size}")
    print(f"Observation space: {training_env.get_observation_space_size()} dimensions")
    print(f"Action space: {training_env.get_action_space_size()} dimensions")
    print(f"Network architecture: {training_env.get_observation_space_size()} -> 24 -> 18 -> {training_env.get_action_space_size()}")
    
    # Create models directory
    os.makedirs("ai_models", exist_ok=True)
    
    clock = pygame.time.Clock()
    
    # Reset environment for first episode
    observations = training_env.reset()
    
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                if not quit_requested:
                    quit_requested = True
                    print("\nQuit requested! Waiting for current generation to complete...")
                    print(f"Current: Generation {genetic_algo.generation}, Episode {current_episode}/{generation_episodes}")
        
        # Get actions from neural networks (for all cars)
        actions = []
        
        for car_idx in range(len(training_env.cars)):
            if car_idx < len(observations):
                obs = observations[car_idx] if isinstance(observations, list) else observations
                action = genetic_algo.population[car_idx].forward(obs)
                actions.append(action)
        
        # Step the environment
        next_observations, rewards, dones, info = training_env.step(actions)
        
        # Accumulate rewards for fitness calculation
        for i, reward in enumerate(rewards):
            if i < len(episode_rewards):
                episode_rewards[i].append(reward)
                car_fitness_scores[i] += reward
        
        episode_steps += 1
        observations = next_observations
        
        # Check if episode should end
        episode_done = any(dones) or episode_steps >= max_episode_steps
        
        if episode_done:
            current_episode += 1
            episode_steps = 0
            
            # Calculate final fitness scores for this episode
            final_fitness = []
            for i in range(population_size):
                # Fitness = sum of rewards + bonus for surviving longer
                survival_bonus = len(episode_rewards[i]) * 0.1
                total_reward = sum(episode_rewards[i]) if episode_rewards[i] else 0
                fitness = total_reward + survival_bonus
                final_fitness.append(fitness)
            
            print(f"Episode {current_episode}/{generation_episodes} completed")
            print(f"Best episode fitness: {max(final_fitness):.3f}, Avg: {np.mean(final_fitness):.3f}")
            
            # Check if generation is complete
            if current_episode >= generation_episodes:
                # Calculate average fitness for each network across all episodes
                for i in range(population_size):
                    avg_fitness = car_fitness_scores[i] / generation_episodes
                    genetic_algo.evaluate_fitness(i, avg_fitness)
                
                # Evolve to next generation
                genetic_algo.evolve()
                
                # Save best network every few generations
                if genetic_algo.generation % 5 == 0:
                    genetic_algo.save_best(f"ai_models/generation_{genetic_algo.generation}.pkl")
                
                # Check if quit was requested - exit gracefully after generation completion
                if quit_requested:
                    print(f"\nGeneration {genetic_algo.generation} completed. Saving final model and exiting...")
                    genetic_algo.save_best("ai_models/best_network.pkl")
                    genetic_algo.save_best(f"ai_models/final_generation_{genetic_algo.generation}.pkl")
                    pygame.quit()
                    sys.exit(0)
                
                # Reset for next generation
                current_episode = 0
                car_fitness_scores = [0.0] * population_size
                episode_rewards = [[] for _ in range(population_size)]
            
            # Reset environment for next episode
            observations = training_env.reset()
        
        # Visualization
        screen.blit(scaled_track, (0, 0))
        active_cars = training_env.get_active_cars()

        # Draw only the top N cars by current episode score (fallback to first N if no scores yet)
        TOP_N = 20
        # Compute current scores (sum of episode rewards so far per car)
        current_scores_for_draw = []
        if episode_rewards:
            for rewards_list in episode_rewards:
                current_scores_for_draw.append(sum(rewards_list) if rewards_list else float('-inf'))
        else:
            current_scores_for_draw = [float('-inf')] * len(active_cars)

        if current_scores_for_draw and all(s == float('-inf') for s in current_scores_for_draw):
            # No progress yet – just draw the first TOP_N cars
            top_indices = list(range(min(TOP_N, len(active_cars))))
        else:
            # Pick indices of the best-scoring cars
            top_indices = sorted(range(len(current_scores_for_draw)), key=lambda i: current_scores_for_draw[i], reverse=True)[:TOP_N]

        cars_to_draw = [active_cars[i] for i in top_indices if i < len(active_cars)]
        draw_cars_fast(screen, cars_to_draw)
        
        # Draw raycasts for one of the top cars (if available) to stay consistent with filtered rendering
        if active_cars and cars_to_draw and genetic_algo.best_network is not None:
            # Choose the highest-scoring car among the selected top_indices for ray visualization
            chosen_idx = top_indices[0]
            if current_scores_for_draw and any(s != float('-inf') for s in current_scores_for_draw):
                chosen_idx = max(top_indices, key=lambda i: current_scores_for_draw[i] if i < len(current_scores_for_draw) else float('-inf'))

            if chosen_idx < len(active_cars):
                c0 = active_cars[chosen_idx]
                for ray_angle in training_env.raycast_radians:
                    rx, ry, rd, hit = raycast_black_mask(scaled_mask, c0.x * 0.5, c0.y * 0.5, c0.angle+ray_angle, 400.0)
                    if hit:
                        pygame.draw.circle(screen, (0, 255, 0), (int(rx), int(ry)), 2)
                        pygame.draw.line(screen, (0, 255, 0), (int(c0.x*0.5), int(c0.y*0.5)), (int(rx), int(ry)), 1)
        
        # Draw info
        font = pygame.font.Font(None, 24)
        num_active = training_env.get_num_active_cars()
        num_crashed = len(training_env.crashed_cars)
        
        info_lines = [
            f"Generation: {genetic_algo.generation} | Episode: {current_episode}/{generation_episodes}",
            f"Population: {population_size} | Active: {num_active} | Crashed: {num_crashed}",
            f"Best Fitness: {genetic_algo.best_fitness:.3f}",
            f"Episode Steps: {episode_steps}/{max_episode_steps}"
        ]
        
        if quit_requested:
            info_lines.append(">>> QUIT REQUESTED - Finishing generation... <<<")
        
        for i, line in enumerate(info_lines):
            text = font.render(line, True, (255, 255, 255))
            screen.blit(text, (10, 10 + i * 25))
        
        # Draw current episode fitness
        if episode_rewards:
            current_scores = []
            for rewards_list in episode_rewards:
                if rewards_list:
                    current_scores.append(sum(rewards_list))
            
            if current_scores:
                avg_current = np.mean(current_scores)
                best_current = max(current_scores)
                fitness_text = font.render(f"Current Avg: {avg_current:.3f} | Best: {best_current:.3f}", True, (255, 255, 0))
                screen.blit(fitness_text, (10, 110))
    
        pygame.display.flip()
        clock.tick(const.FPS)


if __name__ == "__main__":
    main()