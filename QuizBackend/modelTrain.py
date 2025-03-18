import os
import random
import pandas as pd
import numpy as np
from stable_baselines3 import DQN
from stable_baselines3.common.env_util import make_vec_env
from gymnasium import Env, spaces

# Load dataset
dataset_path = os.path.join(os.getcwd(), "data", "Python_MCQ_with_Corrected_Answers.csv")
if os.path.exists(dataset_path):
    dataset = pd.read_csv(dataset_path)
else:
    print("ERROR: Dataset file not found at", dataset_path)
    exit(1)

if dataset.empty:
    print("ERROR: Dataset is empty. Please provide a valid dataset.")
    exit(1)

# Debugging: Print first few rows
print("Dataset loaded successfully. First few rows:")
print(dataset.head())

# Debugging: Check unique values in Difficulty column
if "Difficulty" not in dataset.columns:
    print("ERROR: 'Difficulty' column not found in dataset.")
    exit(1)

print("Unique values in 'Difficulty' column before processing:")
print(dataset["Difficulty"].unique())

# Convert difficulty levels to numeric values
difficulty_mapping = {"Easy": 1, "Medium": 2, "Hard": 3}
dataset["Difficulty"] = dataset["Difficulty"].map(difficulty_mapping)

# Handle any unmapped values
dataset["Difficulty"].fillna(1, inplace=True)  # Default to 1 if missing
dataset.reset_index(drop=True, inplace=True)

# Debugging: Check unique values in Difficulty column after processing
print("Unique values in 'Difficulty' column after conversion:")
print(dataset["Difficulty"].unique())

# Check again if dataset is empty after processing
if len(dataset) == 0:
    print("ERROR: No valid questions found in the dataset after preprocessing.")
    exit(1)

# Save the preprocessed dataset
preprocessed_dataset_path = os.path.join(os.getcwd(), "data", "preprocessed_dataset.csv")
dataset.to_csv(preprocessed_dataset_path, index=False)
print(f"Preprocessed dataset saved at {preprocessed_dataset_path}")

# Define the custom Quiz environment
class QuizEnvironment(Env):
    def __init__(self, dataset):
        super().__init__()
        self.dataset = dataset
        self.user_knowledge = 0.5  # Initial knowledge level
        self.asked_questions = set()
        
        self.action_space = spaces.Discrete(len(dataset))
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32)
        self.state = np.array([self.user_knowledge], dtype=np.float32)

    def step(self, action):
        if action in self.asked_questions:
            return self.state, -1.0, True, False, {}

        self.asked_questions.add(action)
        question = self.dataset.iloc[action]
        is_correct = random.random() < self.user_knowledge
        difficulty = question["Difficulty"]
        
        if not isinstance(difficulty, (int, float)):
            difficulty = 1  # Default to 1 if invalid
        
        reward = difficulty if is_correct else -difficulty
        self.user_knowledge += 0.1 * reward
        self.user_knowledge = np.clip(self.user_knowledge, 0.0, 1.0)
        self.state = np.array([self.user_knowledge], dtype=np.float32)
        done = len(self.asked_questions) >= 20
        return self.state, reward, done, False, {}

    def reset(self, seed=None, options=None):
        self.user_knowledge = 0.5
        self.asked_questions.clear()
        self.state = np.array([self.user_knowledge], dtype=np.float32)
        return self.state, {}

# Train the DQN Model
env = make_vec_env(lambda: QuizEnvironment(dataset), n_envs=1)
model = DQN('MlpPolicy', env, learning_rate=1e-4, buffer_size=10000, batch_size=64, gamma=0.99, verbose=1)

print("Training model...")
model.learn(total_timesteps=10000)

# Save the model
model_path = os.path.join(os.getcwd(), "data", "quiz_model.zip")
model.save(model_path)
print(f"Model saved at {model_path}")