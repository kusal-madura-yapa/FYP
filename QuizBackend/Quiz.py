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
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash
# Load environment variables
load_dotenv()

# Flask app setup
app = Flask(__name__)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SECRET_KEY"] = "supersecretkey"
app.config["SESSION_PERMANENT"] = False
Session(app)

# Allow frontend access
CORS(app, origins=["http://localhost:3000"], supports_credentials=True)

# Load data/model if available
dataset_path = "QuizBackend/data/preprocessed_dataset.csv"
model_path = "QuizBackend/data/quiz_model.zip"
dataset = pd.read_csv(dataset_path) if os.path.exists(dataset_path) else pd.DataFrame()
model = DQN.load(model_path) if os.path.exists(model_path) else None

# Constants
MIN_QUESTIONS = 10

# Database connection helper
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )

# Session user check
def get_logged_in_user_id():
    user_id = session.get("user_id")
    if user_id is None:
        raise PermissionError("User not logged in.")
    return user_id

# 🔐 LOGIN
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE user_name = %s", (username,))
    user = cursor.fetchone()
    conn.close()

    if user and check_password_hash(user["password"], password):
        session.clear()  # Clean any old session
        session["user_id"] = user["user_id"]
        session["username"] = user["user_name"]
        return jsonify({"message": "Login successful", "user_id": user["user_id"]})
    else:
        return jsonify({"error": "Invalid username or password"}), 401

# 🚪 LOGOUT
@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})

# 🚀 START QUIZ
@app.route("/api/start_quiz", methods=["POST"])
def start_quiz():
    try:
        user_id = get_logged_in_user_id()
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401

    conn = get_db_connection()
    cursor = conn.cursor()

    # Clean video track data for this user
    cursor.execute("DELETE FROM VideoTrack WHERE user_id = %s", (user_id,))

    # Create new quiz entry
    initial_knowledge = 0.5
    initial_score = 0
    attempt_id = 1  # You might want to calculate this dynamically later
    cursor.execute(
        "INSERT INTO Quiz (user_id, knowledge_level, score, weakareas, attempt_id) VALUES (%s, %s, %s, %s, %s)",
        (user_id, initial_knowledge, initial_score, json.dumps({}), attempt_id)
    )
    quiz_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Store quiz session state
    session.update({
        "quiz_id": quiz_id,
        "knowledge_level": initial_knowledge,
        "score": initial_score,
        "questions_asked": [],
        "weak_areas": {},
        "attempt_id": attempt_id
    })

    return jsonify({
        "message": "Quiz started!",
        "quiz_id": quiz_id,
        "knowledge_level": initial_knowledge
    })


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    hashed_password = generate_password_hash(password)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if username already exists
        cursor.execute("SELECT * FROM users WHERE user_name = %s", (username,))
        if cursor.fetchone():
            return jsonify({"error": "Username already taken"}), 409

        # ✅ Get the max user_id and increment it
        cursor.execute("SELECT MAX(user_id) FROM users")
        result = cursor.fetchone()
        next_user_id = (result[0] or 0) + 1  # if None, start at 1

        # Insert with manual user_id
        cursor.execute(
            "INSERT INTO users (user_id, user_name, password) VALUES (%s, %s, %s)",
            (next_user_id, username, hashed_password)
        )
        conn.commit()
        conn.close()

        return jsonify({"message": "User registered successfully", "user_id": next_user_id}), 201

    except Exception as e:
        print("Error during registration:", e)
        return jsonify({"error": "Server error during registration"}), 500


@app.route("/api/leaderboard", methods=["GET"])
def leaderboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # ✅ Return the best scoring attempt per user
    cursor.execute("""
        SELECT 
            u.user_id,
            u.user_name,
            q.quiz_id,
            q.attempt_id,
            q.score,
            q.knowledge_level,
            q.weakareas
        FROM users u
        LEFT JOIN (
            SELECT *
            FROM Quiz q1
            WHERE (user_id, score) IN (
                SELECT user_id, MAX(score)
                FROM Quiz
                GROUP BY user_id
            )
        ) q ON u.user_id = q.user_id
        ORDER BY q.score DESC;
    """)

    data = cursor.fetchall()
    conn.close()

    return jsonify({
        "status": "success",
        "total": len(data),
        "leaderboard": data
    })


@app.route("/api/clear_all_data", methods=["POST"])
def clear_all_data():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Delete all quiz-related data first (respect FK constraints)
        cursor.execute("DELETE FROM VideoTrack")
        cursor.execute("DELETE FROM Question")
        cursor.execute("DELETE FROM Quiz")

        # Optional: Delete from VideoResources
        # cursor.execute("DELETE FROM VideoResources")

        # Delete users (last, due to FK)
        cursor.execute("DELETE FROM users")

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "message": "All database records have been cleared."
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to clear data: {str(e)}"
        }), 500

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
    try:
        user_id = get_logged_in_user_id()
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401

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

@app.route("/api/reset_data", methods=["POST"])
def reset_data():
    global model

    try:
        user_id = get_logged_in_user_id()
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401

    model_path = "QuizBackend/data/quiz_model.zip"
    model = DQN.load(model_path) if os.path.exists(model_path) else None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 🧹 Only delete this user's data
        cursor.execute("DELETE FROM VideoTrack WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM Question WHERE quiz_id IN (SELECT quiz_id FROM Quiz WHERE user_id = %s)", (user_id,))
        cursor.execute("DELETE FROM Quiz WHERE user_id = %s", (user_id,))
        
        conn.commit()
        conn.close()

        return jsonify({
            "message": "Your quiz data and model session have been reset.",
            "model_status": "Model reset successfully." if model else "Model file not found. Reset failed."
        })

    except Exception as e:
        return jsonify({"error": f"Error resetting data: {str(e)}"}), 500


# Get previous quiz records
@app.route("/api/previous_records", methods=["GET"])
def previous_records():
    try:
        user_id = get_logged_in_user_id()
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401

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
            "attempt_id": quiz["attempt_id"],
            "total_questions": len(questions),
            "final_score": quiz["score"],
            "final_knowledge_level": quiz["knowledge_level"],
            "weak_areas": weak_areas,
            "correct_answers": correct_answers,
            "incorrect_answers": incorrect_answers
        })

    conn.close()
    return jsonify({"history": records})

@app.route("/api/weak_areas", methods=["GET"])
def weak_areas():
    try:
        user_id = get_logged_in_user_id()
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # ✅ Get the latest quiz attempt for the user
    cursor.execute("""
        SELECT * FROM Quiz 
        WHERE user_id = %s 
        ORDER BY attempt_id DESC 
        LIMIT 1
    """, (user_id,))
    latest_quiz = cursor.fetchone()

    if not latest_quiz:
        conn.close()
        return jsonify({"error": "No quiz attempts found for this user!"}), 404

    weak_areas = json.loads(latest_quiz["weakareas"]) if latest_quiz["weakareas"] else {}
    video_suggestions = {}

    if weak_areas:
        placeholders = ', '.join(['%s'] * len(weak_areas))
        cursor.execute(
            f"SELECT * FROM VideoResources WHERE weakarea IN ({placeholders})",
            list(weak_areas.keys())
        )
        videos = cursor.fetchall()

        for v in videos:
            wa = v["weakarea"]
            video_suggestions.setdefault(wa, []).append({
                "video_id": v["video_id"],
                "title": v["video_title"],
                "url": v["video_url"],
                "description": v["description"]
            })

    conn.close()

    return jsonify({
        "quiz_id": latest_quiz["quiz_id"],
        "attempt_id": latest_quiz["attempt_id"],
        "weak_areas": weak_areas,
        "suggested_videos": video_suggestions
    })


@app.route("/api/get_quiz_questions_re", methods=["GET"])
def get_quiz_questions():
    try:
        user_id = get_logged_in_user_id()
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 🔍 Step 1: Get latest attempt_id for this user
    cursor.execute("SELECT MAX(attempt_id) AS latest FROM Quiz WHERE user_id = %s", (user_id,))
    latest_attempt = cursor.fetchone()["latest"]

    if not latest_attempt:
        conn.close()
        return jsonify({"error": "No attempts found for user!"}), 404

    # 🔍 Step 2: Get all incorrect questions from latest attempt
    cursor.execute("""
        SELECT description, correct_answer, weakarea, COUNT(*) AS attempt_count 
        FROM Question 
        WHERE is_correct = 0 AND quiz_id IN (
            SELECT quiz_id FROM Quiz WHERE user_id = %s AND attempt_id = %s
        )
        GROUP BY description, correct_answer, weakarea
        ORDER BY attempt_count DESC
        LIMIT 10;
    """, (user_id, latest_attempt))
    questions = cursor.fetchall()
    conn.close()

    if not questions:
        return jsonify({"error": "No incorrect questions found for latest attempt!"}), 404

    # 🔄 Step 3: Build fake answers
    result = []
    for question in questions:
        correct_answer = question["correct_answer"]
        wrong_answers = dataset[dataset["Correct Answer"] != correct_answer]["Correct Answer"].unique().tolist()
        wrong_answers = random.sample(wrong_answers, min(len(wrong_answers), 3))
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
    try:
        user_id = get_logged_in_user_id()
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401

    data = request.get_json()
    if not data or 'answers' not in data:
        return jsonify({"error": "Missing answers in request!"}), 400

    user_answers = data['answers']
    # ... (same rest of the code but remove user_id references from body and use the session one)


    # Step 0: Connect to DB
    conn = get_db_connection()
    cursor = conn.cursor()

    # Step 0.1: Delete previous video tracking for this user (to reset history for this new quiz)
    cursor.execute("DELETE FROM VideoTrack WHERE user_id = %s", (user_id,))

    # Step 1: Get the latest attempt_id for the user
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
    try:
        user_id = get_logged_in_user_id()
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Step 1: Get the latest quiz attempt
    cursor.execute("""
        SELECT weakareas, quiz_id, attempt_id 
        FROM Quiz 
        WHERE user_id = %s 
        ORDER BY attempt_id DESC 
        LIMIT 1
    """, (user_id,))
    
    result = cursor.fetchone()
    if not result:
        conn.close()
        return jsonify({"error": "No quiz attempts found for this user!"}), 404

    quiz_id = result["quiz_id"]
    weakareas = json.loads(result["weakareas"]) if result["weakareas"] else {}

    # Step 2: Get relevant videos from VideoResources
    video_suggestions = {}
    if weakareas:
        placeholders = ', '.join(['%s'] * len(weakareas))
        cursor.execute(
            f"SELECT * FROM VideoResources WHERE weakarea IN ({placeholders})",
            list(weakareas.keys())
        )
        videos = cursor.fetchall()

        # Step 3: Get watched status from VideoTrack
        cursor.execute("""
            SELECT video_id, watched FROM VideoTrack
            WHERE user_id = %s AND quiz_id = %s
        """, (user_id, quiz_id))
        watch_data = cursor.fetchall()
        watched_map = {row["video_id"]: row["watched"] for row in watch_data}

        for v in videos:
            wa = v["weakarea"]
            vid = v["video_id"]
            video_suggestions.setdefault(wa, []).append({
                "video_id": vid,
                "title": v["video_title"],
                "url": v["video_url"],
                "description": v["description"],
                "watched": watched_map.get(vid, False)
            })

    conn.close()

    return jsonify({
        "quiz_id": quiz_id,
        "attempt_id": result["attempt_id"],
        "weak_areas": weakareas,
        "suggested_videos": video_suggestions
    })


@app.route("/api/track_video", methods=["POST"])
def track_video():
    data = request.get_json()
    try:
        user_id = get_logged_in_user_id()
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401
    
    video_id = data.get("video_id")
    quiz_id = data.get("quiz_id")
    watched = data.get("watched", True)

    if not all([user_id, video_id, quiz_id]):
        return jsonify({"error": "Missing fields!"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # ✅ Use the correct column name: track_id
    cursor.execute("""
        SELECT track_id FROM VideoTrack
        WHERE user_id = %s AND video_id = %s AND quiz_id = %s
    """, (user_id, video_id, quiz_id))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE VideoTrack SET watched = %s, clicked_at = NOW()
            WHERE track_id = %s
        """, (watched, existing[0]))  # or existing["track_id"] if using dictionary=True
    else:
        cursor.execute("""
            INSERT INTO VideoTrack (user_id, video_id, quiz_id, watched)
            VALUES (%s, %s, %s, %s)
        """, (user_id, video_id, quiz_id, watched))

    conn.commit()
    conn.close()

    return jsonify({"status": "updated", "watched": watched})

@app.route("/api/video_history", methods=["GET"])
def video_history():
    try:
        user_id = get_logged_in_user_id()
    except PermissionError as e:
        return jsonify({"error": str(e)}), 401

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch all video tracking info with video details
    cursor.execute("""
        SELECT 
            vt.quiz_id,
            vt.video_id,
            vr.weakarea,
            vr.video_title,
            vr.video_url,
            vr.description,
            vt.watched,
            vt.clicked_at
        FROM VideoTrack vt
        JOIN VideoResources vr ON vt.video_id = vr.video_id
        WHERE vt.user_id = %s
        ORDER BY vt.quiz_id DESC, vt.clicked_at DESC
    """, (user_id,))
    
    rows = cursor.fetchall()
    conn.close()

    # Group by quiz_id
    history = {}
    for row in rows:
        quiz_id = row["quiz_id"]
        if quiz_id not in history:
            history[quiz_id] = []
        history[quiz_id].append({
            "video_id": row["video_id"],
            "title": row["video_title"],
            "url": row["video_url"],
            "weakarea": row["weakarea"],
            "description": row["description"],
            "watched": row["watched"],
            "clicked_at": row["clicked_at"].strftime('%Y-%m-%d %H:%M:%S')
        })

    return jsonify({"user_id": user_id, "video_history": history})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
