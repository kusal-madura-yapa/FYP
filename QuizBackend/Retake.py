from flask import Flask, jsonify, request
import mysql.connector
import os
import random
import pandas as pd
from dotenv import load_dotenv
import json  # Required for safe JSON conversion


# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Load the dataset for generating fake answers
dataset_path = "QuizBackend/data/preprocessed_dataset.csv"
dataset = pd.read_csv(dataset_path) if os.path.exists(dataset_path) else pd.DataFrame()

# Database connection function
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )



# Endpoint to retrieve quiz questions with fake answers
@app.route("/api/get_quiz_questions", methods=["GET"])
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


# Endpoint to submit a quiz attempt
from flask import jsonify, request
import json  # Required for safe JSON conversion
import mysql.connector

@app.route("/api/submit_quiz", methods=["POST"])
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
    """, (user_id, 0, 0, json.dumps([]), attempt_id))
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

        # Get the latest version of this question from DB
        cursor.execute("""
            SELECT correct_answer, weakarea 
            FROM Question 
            WHERE description = %s 
            ORDER BY attempt_id DESC 
            LIMIT 1
        """, (question_desc,))
        result = cursor.fetchone()

        if not result:
            continue

        correct_answer, weakarea = result
        is_correct = int(correct_answer == user_answer)

        if not is_correct:
            weakarea_tracker[weakarea] = weakarea_tracker.get(weakarea, 0) + 1
        else:
            correct_answers_count += 1

        # Store each answered question in the Question table
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

    # Step 5: Update score and weakareas in Quiz
    score_percentage = (correct_answers_count / total_questions) * 100 if total_questions > 0 else 0
    weakareas_summary = sorted(weakarea_tracker.items(), key=lambda x: x[1], reverse=True)
    weakareas_json = json.dumps([w[0] for w in weakareas_summary])  # JSON fix!

    cursor.execute("""
        UPDATE Quiz 
        SET score = %s, knowledge_level = %s, weakareas = %s 
        WHERE quiz_id = %s
    """, (score_percentage, 0, weakareas_json, quiz_id))

    # Commit changes
    conn.commit()
    conn.close()

    # Return the response
    return jsonify({
        "status": "success",
        "attempt_id": attempt_id,
        "correct_answers": correct_answers_count,
        "total_questions": total_questions,
        "score_percentage": score_percentage,
        "answers_details": answers_details,
        "weakareas_summary": weakareas_summary
    })


# Run the Flask app on port 5000
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004, debug=True)