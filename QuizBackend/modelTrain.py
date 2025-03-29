import os
import random
import pandas as pd
import numpy as np
from stable_baselines3 import DQN
from stable_baselines3.common.env_util import make_vec_env
from gymnasium import Env, spaces

# DEBUG: Show working directory
print("Current working directory:", os.getcwd())

# Load dataset
relative_path = os.path.join("QuizBackend", "data", "Python_MCQ.csv")
absolute_path = "/Users/kusalmadurayapa/Desktop/pythonQuiz/QuizBackend/data/Python_MCQ.csv"
dataset_path = relative_path if os.path.exists(relative_path) else absolute_path

if os.path.exists(dataset_path):
    try:
        dataset = pd.read_csv(dataset_path, encoding='ISO-8859-1')
    except Exception as e:
        print("ERROR reading dataset:", e)
        exit(1)
else:
    print("ERROR: Dataset file not found at:", dataset_path)
    exit(1)

if dataset.empty:
    print("ERROR: Dataset is empty. Please provide a valid dataset.")
    exit(1)

print("✅ Dataset loaded successfully. First few rows:")
print(dataset.head())

# Check for Difficulty column
if "Difficulty" not in dataset.columns:
    print("ERROR: 'Difficulty' column not found in dataset.")
    exit(1)

print("Unique values in 'Difficulty' column before processing:")
print(dataset["Difficulty"].unique())

# Convert difficulty levels to numeric values
difficulty_mapping = {"Easy": 1, "Medium": 2, "Hard": 3}
dataset["Difficulty"] = dataset["Difficulty"].map(difficulty_mapping).fillna(1).astype(int)

dataset.reset_index(drop=True, inplace=True)

print("✅ Difficulty column after conversion:")
print(dataset["Difficulty"].unique())

if len(dataset) == 0:
    print("ERROR: No valid questions found in the dataset after preprocessing.")
    exit(1)

# Save the preprocessed dataset
preprocessed_dataset_path = os.path.join("QuizBackend", "data", "preprocessed_dataset.csv")
dataset.to_csv(preprocessed_dataset_path, index=False)
print(f"✅ Preprocessed dataset saved at {preprocessed_dataset_path}")

# Define custom Quiz environment
class QuizEnvironment(Env):
    def __init__(self, dataset):
        super().__init__()
        self.dataset = dataset
        self.user_knowledge = 0.5
        self.asked_questions = set()

        self.action_space = spaces.Discrete(len(dataset))
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32)
        self.state = np.array([self.user_knowledge], dtype=np.float32)

    def step(self, action):
        if action in self.asked_questions:
            return self.state, -1.0, True, False, {}

        self.asked_questions.add(action)
        question = self.dataset.iloc[action]
        difficulty = question["Difficulty"]
        is_correct = random.random() < self.user_knowledge

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

print("🚀 Training model...")
model.learn(total_timesteps=10000)

# Save the model
model_path = os.path.join("QuizBackend", "data", "quiz_model.zip")
model.save(model_path)
print(f"✅ Model saved at {model_path}")
