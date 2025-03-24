from flask import Flask, jsonify, request
import mysql.connector
import os
import random
import pandas as pd
from dotenv import load_dotenv

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

    # Query to get the top 10 questions with is_correct == 0 and the highest attempt_id for each question
    cursor.execute("""
        SELECT description, correct_answer, attempt_id, COUNT(*) AS attempt_count 
        FROM Question 
        WHERE is_correct = 0
        GROUP BY description, correct_answer, attempt_id
        HAVING attempt_id = (
            SELECT MAX(attempt_id) 
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

    # Structure the questions with fake answers
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
            "options": options
        })

    return jsonify({
        "status": "success",
        "questions_with_fake_answers": result
    })

# Endpoint to submit a quiz attempt
@app.route("/api/submit_quiz", methods=["POST"])
def submit_quiz():
    data = request.get_json()

    if not data or not isinstance(data, dict) or 'answers' not in data:
        return jsonify({"error": "Invalid data format or missing answers!"}), 400

    correct_answers_count = 0
    total_questions = len(data['answers'])
    answers_details = []

    # Iterate over the answers provided by the user and check against the correct answers
    for answer in data['answers']:
        question = answer.get('question')
        user_answer = answer.get('user_answer')

        if not question or not user_answer:
            continue

        # Fetch the correct answer from the database
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query to get the correct answer for the question
        cursor.execute("SELECT correct_answer FROM Question WHERE description = %s", (question,))
        result = cursor.fetchone()
        conn.close()

        if result and result['correct_answer'] == user_answer:
            correct_answers_count += 1
            answers_details.append({
                "question": question,
                "user_answer": user_answer,
                "correct_answer": result['correct_answer'],
                "is_correct": True
            })
        else:
            answers_details.append({
                "question": question,
                "user_answer": user_answer,
                "correct_answer": result['correct_answer'],
                "is_correct": False
            })

    # Calculate score percentage
    score_percentage = (correct_answers_count / total_questions) * 100 if total_questions > 0 else 0

    return jsonify({
        "status": "success",
        "correct_answers": correct_answers_count,
        "total_questions": total_questions,
        "score_percentage": score_percentage,
        "answers_details": answers_details
    })


# Run the Flask app on port 5000
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004, debug=True)