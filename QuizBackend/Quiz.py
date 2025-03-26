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

# # Get users
# @app.route("/api/users", methods=["GET"])
# def get_users():
#     conn = get_db_connection()
#     cursor = conn.cursor(dictionary=True)
#     cursor.execute("SELECT * FROM users")
#     users = cursor.fetchall()
#     conn.close()
#     return jsonify(users)

# Endpoint to retrieve quiz questions with fake answers
@app.route("/api/get_quiz_questions_re", methods=["GET"])
def get_quiz_questions():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get the latest 10 frequently incorrect questions by max attempt_id per question
    cursor.execute("""
        SELECT description, correct_answer, attempt_id, weakarea, COUNT(*) AS attempt_count 
        FROM Question 
        WHERE is_correct = 0
        GROUP BY description, correct_answer, weakarea, attempt_id
        HAVING attempt_id = (
            SELECT MAX(q2.attempt_id)
            FROM Question q2
            WHERE q2.description = Question.description
              AND q2.correct_answer = Question.correct_answer
        )
        ORDER BY attempt_count DESC
        LIMIT 10;
    """)
    questions = cursor.fetchall()
    conn.close()

    if not questions:
        return jsonify({"error": "No questions found!"}), 404

    result = []

    for question in questions:
        correct_answer = question["correct_answer"]

        # Get fake answers from dataset, excluding the correct one
        wrong_answers = dataset[dataset["Correct Answer"] != correct_answer]["Correct Answer"].unique().tolist()
        wrong_answers = random.sample(wrong_answers, min(len(wrong_answers), 3))

        # Shuffle all options
        options = [correct_answer] + wrong_answers
        random.shuffle(options)

        result.append({
            "question": question["description"],
            "correct_answer": correct_answer,
            "options": options,
            "weakarea": question["weakarea"]
        })

    return jsonify({
        "status": "success",
        "questions_with_fake_answers": result
    })


@app.route("/api/submit_quiz_re", methods=["POST"])
def submit_quiz():
    data = request.get_json()

    if not data or 'answers' not in data or 'user_id' not in data:
        return jsonify({"error": "Missing answers or user_id in request!"}), 400

    user_id = data['user_id']
    user_answers = data['answers']

    # Step 1: Get the latest attempt_id for the user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(attempt_id) FROM Quiz WHERE user_id = %s", (user_id,))
    latest_attempt = cursor.fetchone()[0]
    attempt_id = (latest_attempt or 0) + 1

    # Step 2: Create a new Quiz entry (temp values for score and weakareas)
    cursor.execute("""
        INSERT INTO Quiz (user_id, knowledge_level, score, weakareas, attempt_id)
        VALUES (%s, %s, %s, %s, %s)
    """, (user_id, 0, 0, json.dumps({}), attempt_id))
    quiz_id = cursor.lastrowid

    # Step 3: Initialize tracking
    correct_answers_count = 0
    total_questions = len(user_answers)
    answers_details = []
    weakarea_tracker = {}

    # Step 4: Loop through answers
    for ans in user_answers:
        question_desc = ans.get("question")
        user_answer = ans.get("user_answer")

        if not question_desc or not user_answer:
            continue

        # ✅ Use dataset as ground truth instead of Question table
        row = dataset[dataset["Question"] == question_desc]
        if row.empty:
            continue  # skip if question not found

        correct_answer = row.iloc[0]["Correct Answer"]
        weakarea = row.iloc[0].get("Category", "Unknown")
        is_correct = int(correct_answer == user_answer)

        if not is_correct:
            weakarea_tracker[weakarea] = weakarea_tracker.get(weakarea, 0) + 1
        else:
            correct_answers_count += 1

        # Store answered question into Question table (for logging only)
        cursor.execute("""
            INSERT INTO Question (quiz_id, attempt_id, description, correct_answer, is_correct, weakarea)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (quiz_id, attempt_id, question_desc, correct_answer, is_correct, weakarea))

        answers_details.append({
            "question": question_desc,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "is_correct": bool(is_correct),
            "weakarea": weakarea
        })

    # Step 5: Calculate final metrics
    score_percentage = (correct_answers_count / total_questions) * 100 if total_questions > 0 else 0
    knowledge_level = correct_answers_count / total_questions if total_questions > 0 else 0.0
    weakareas_json = json.dumps(weakarea_tracker)
    weakareas_summary = sorted(weakarea_tracker.items(), key=lambda x: x[1], reverse=True)

    # Step 6: Update quiz record
    cursor.execute("""
        UPDATE Quiz 
        SET score = %s, knowledge_level = %s, weakareas = %s 
        WHERE quiz_id = %s
    """, (score_percentage, knowledge_level, weakareas_json, quiz_id))

    # Step 7: Commit and return response
    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "attempt_id": attempt_id,
        "correct_answers": correct_answers_count,
        "total_questions": total_questions,
        "score_percentage": score_percentage,
        "answers_details": answers_details,
        "weakareas_summary": weakareas_summary
    })

@app.route("/api/weak_areas_latest", methods=["GET"])
def get_weak_areas_latest():
    user_id = request.args.get("userid")
    if not user_id:
        return jsonify({"error": "User ID is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get the quiz with the latest attempt_id for the user
    cursor.execute("""
        SELECT weakareas, quiz_id, attempt_id 
        FROM Quiz 
        WHERE user_id = %s 
        ORDER BY attempt_id DESC 
        LIMIT 1
    """, (user_id,))
    
    result = cursor.fetchone()
    conn.close()

    if not result:
        return jsonify({"error": "No quiz attempts found for this user!"}), 404

    weakareas = json.loads(result["weakareas"]) if result["weakareas"] else {}

    return jsonify({
        "quiz_id": result["quiz_id"],
        "attempt_id": result["attempt_id"],
        "weak_areas": weakareas
    })



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
