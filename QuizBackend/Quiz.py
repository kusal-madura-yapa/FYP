from flask import Flask, request, jsonify, session
from flask_session import Session
from flask_cors import CORS
import os
from dotenv import load_dotenv
import random
import pandas as pd
import mysql.connector
import json
from stable_baselines3 import DQN

# Load environment variables
load_dotenv()

# Flask setup
app = Flask(__name__)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SECRET_KEY"] = "supersecretkey"
app.config["SESSION_PERMANENT"] = False
Session(app)

# Allow CORS for React frontend
CORS(app, origins=["http://localhost:3000"], supports_credentials=True)

# Load dataset and model
dataset_path = "QuizBackend/data/preprocessed_dataset.csv"
model_path = "QuizBackend/data/quiz_model.zip"
dataset = pd.read_csv(dataset_path) if os.path.exists(dataset_path) else pd.DataFrame()
model = DQN.load(model_path) if os.path.exists(model_path) else None

# Set a minimum number of questions
MIN_QUESTIONS = 10

# Database connection
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

# Start quiz
@app.route("/api/start_quiz", methods=["POST"])
def start_quiz():
    data = request.get_json()
    user_id = data.get("user_id")

    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO Quiz (user_id, knowledge_level, score, weakareas, attempt_id) VALUES (%s, %s, %s, %s, %s)",
                   (user_id, 0.5, 0, json.dumps({}), 1))
    quiz_id = cursor.lastrowid
    conn.commit()
    conn.close()

    session.update({
        "quiz_id": quiz_id,
        "user_id": user_id,
        "knowledge_level": 0.5,
        "questions_asked": [],
        "score": 0,
        "weak_areas": {},
        "attempt_id": 1
    })

    return jsonify({"message": "Quiz started!", "quiz_id": quiz_id, "knowledge_level": 0.5})

# Next question
@app.route("/api/next_question", methods=["GET"])
def next_question():
    if "quiz_id" not in session:
        return jsonify({"error": "Start the quiz first!"}), 400

    questions_asked = session.get("questions_asked", [])

    if len(questions_asked) >= MIN_QUESTIONS:
        return jsonify({"message": "Quiz completed!", "results": save_quiz_results()}), 200

    available_questions = dataset[~dataset.index.isin(questions_asked)].copy()

    if available_questions.empty:
        return jsonify({"message": "No more available questions!"}), 200

    if len(questions_asked) == 0:
        selected_question = available_questions.sample(1).iloc[0]
    else:
        target_difficulty = session["knowledge_level"] * 3
        available_questions["diff_delta"] = (available_questions["Difficulty"] - target_difficulty).abs()
        top_n = available_questions.sort_values("diff_delta").head(5)
        selected_question = top_n.sample(1).iloc[0]


    session["questions_asked"].append(int(selected_question.name))

    correct_answer = selected_question["Correct Answer"]
    wrong_answers = dataset[dataset["Correct Answer"] != correct_answer]["Correct Answer"].unique().tolist()
    wrong_answers = random.sample(wrong_answers, min(len(wrong_answers), 3))

    options = [correct_answer] + wrong_answers
    random.shuffle(options)

    return jsonify({
        "question_id": int(selected_question.name),
        "question": selected_question["Question"],
        "options": options,
        "correct_answer": correct_answer
    })

# Submit answer
@app.route("/api/submit_answer", methods=["POST"])
def submit_answer():
    data = request.json
    user_answer = data.get("answer")

    if "questions_asked" not in session or not session["questions_asked"]:
        return jsonify({"error": "No active question found!"}), 400

    last_question_index = session["questions_asked"][-1]
    question_data = dataset.iloc[last_question_index]
    correct_answer = question_data["Correct Answer"]
    is_correct = user_answer == correct_answer
    difficulty = int(question_data["Difficulty"])
    attempt_id = session["attempt_id"]
    weak_area = question_data.get("Category", "Unknown")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Question (quiz_id, attempt_id, description, is_correct, correct_answer, weakarea) VALUES (%s, %s, %s, %s, %s, %s)",
        (session["quiz_id"], attempt_id, question_data["Question"], is_correct, correct_answer, weak_area)
    )

    if is_correct:
        session["score"] += difficulty
        session["knowledge_level"] = min(1.0, session["knowledge_level"] + 0.1)
    else:
        session["score"] -= difficulty * 0.5
        session["knowledge_level"] = max(0.0, session["knowledge_level"] - 0.1)
        session["weak_areas"][weak_area] = session["weak_areas"].get(weak_area, 0) + 1

    cursor.execute("UPDATE Quiz SET score = %s, knowledge_level = %s WHERE quiz_id = %s",
                   (session["score"], session["knowledge_level"], session["quiz_id"]))
    conn.commit()
    conn.close()

    session.modified = True

    return jsonify({
        "correct": is_correct,
        "message": "Correct!" if is_correct else f"Incorrect! The correct answer was {correct_answer}",
        "score": session["score"]
    })

# Save quiz results
def save_quiz_results():
    conn = get_db_connection()
    cursor = conn.cursor()
    weakareas_json = json.dumps(session.get("weak_areas", {}))

    cursor.execute("UPDATE Quiz SET knowledge_level = %s, score = %s, weakareas = %s WHERE quiz_id = %s",
                   (session["knowledge_level"], session["score"], weakareas_json, session["quiz_id"]))
    conn.commit()
    conn.close()

    return {
        "quiz_id": session["quiz_id"],
        "total_questions": len(session.get("questions_asked", [])),
        "final_score": session["score"],
        "final_knowledge_level": session["knowledge_level"],
        "weak_areas": session.get("weak_areas", {})
    }

# Get quiz results
@app.route("/api/quiz_results", methods=["GET"])
def quiz_results():
    if "quiz_id" not in session:
        return jsonify({"error": "No active quiz!"}), 400

    return jsonify(save_quiz_results())

# Reset quiz data
@app.route("/api/reset_data", methods=["POST"])
def reset_data():
    global model

    model_path = "QuizBackend/data/quiz_model.zip"
    model = DQN.load(model_path) if os.path.exists(model_path) else None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Question")
        cursor.execute("DELETE FROM Quiz")
        conn.commit()
        conn.close()

        return jsonify({
            "message": "Database cleaned and model reset.",
            "model_status": "Model reset successfully." if model else "Model file not found. Reset failed."
        })

    except Exception as e:
        return jsonify({"error": f"Error resetting data: {str(e)}"}), 500

# Get previous quiz records
@app.route("/api/previous_records", methods=["GET"])
def previous_records():
    user_id = request.args.get("userid")
    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Quiz WHERE user_id = %s ORDER BY quiz_id DESC", (user_id,))
    quizzes = cursor.fetchall()

    records = []
    for quiz in quizzes:
        cursor.execute("SELECT * FROM Question WHERE quiz_id = %s", (quiz["quiz_id"],))
        questions = cursor.fetchall()
        weak_areas = json.loads(quiz["weakareas"]) if quiz["weakareas"] else {}

        correct_answers = [q["description"] for q in questions if q["is_correct"]]
        incorrect_answers = [{"question": q["description"], "correct_answer": q["correct_answer"]} for q in questions if not q["is_correct"]]

        records.append({
            "quiz_id": quiz["quiz_id"],
            "attempt_id": quiz["attempt_id"],  # Add this line
            "total_questions": len(questions),
            "final_score": quiz["score"],
            "final_knowledge_level": quiz["knowledge_level"],
            "weak_areas": weak_areas,
            "correct_answers": correct_answers,
            "incorrect_answers": incorrect_answers
        })


    conn.close()
    return jsonify({"history": records})

# Get weak areas
@app.route("/api/weak_areas", methods=["GET"])
def weak_areas():
    user_id = request.args.get("userid")
    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Quiz WHERE user_id = %s ORDER BY quiz_id DESC", (user_id,))
    quizzes = cursor.fetchall()

    weak_areas_records = []
    for quiz in quizzes:
        weak_areas = json.loads(quiz["weakareas"]) if quiz["weakareas"] else {}

        weak_areas_records.append({
            "quiz_id": quiz["quiz_id"],
            "weak_areas": weak_areas
        })

    conn.close()
    return jsonify({"history": weak_areas_records})

# Get users
@app.route("/api/users", methods=["GET"])
def get_users():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    conn.close()
    return jsonify(users)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
