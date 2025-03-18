# from flask import Flask, jsonify, request
# import mysql.connector
# import os
# import random
# import pandas as pd
# from dotenv import load_dotenv

# # Load environment variables
# load_dotenv()

# # Flask setup for the second app
# app = Flask(__name__)

# # Load the dataset
# dataset_path = "QuizBackend/data/preprocessed_dataset.csv"
# dataset = pd.read_csv(dataset_path) if os.path.exists(dataset_path) else pd.DataFrame()

# # Database connection function
# def get_db_connection():
#     return mysql.connector.connect(
#         host=os.getenv('DB_HOST'),
#         user=os.getenv('DB_USER'),
#         password=os.getenv('DB_PASSWORD'),
#         database=os.getenv('DB_NAME')
#     )


# # Get questions with the maximum attempts and fake answers
# @app.route("/api/get_max_attempts_questions", methods=["GET"])
# def get_max_attempts_questions():
#     conn = get_db_connection()
#     cursor = conn.cursor(dictionary=True)

#     # Query to get the questions with the maximum attempts
#     cursor.execute("""
#         SELECT description, correct_answer, COUNT(*) AS attempt_count 
#         FROM Question 
#         GROUP BY description, correct_answer 
#         ORDER BY attempt_count DESC
#         LIMIT 10;
#     """)
#     questions = cursor.fetchall()
#     conn.close()

#     if not questions:
#         return jsonify({"error": "No questions found with attempts!"}), 404

#     # For each question, generate fake answers from the dataset
#     result = []
#     for question in questions:
#         correct_answer = question["correct_answer"]
#         wrong_answers = dataset[dataset["Correct Answer"] != correct_answer]["Correct Answer"].unique().tolist()
#         wrong_answers = random.sample(wrong_answers, min(len(wrong_answers), 3))

#         options = [correct_answer] + wrong_answers
#         random.shuffle(options)

#         result.append({
#             "question": question["description"],
#             "correct_answer": correct_answer,
#             "options": options
#         })

#     return jsonify({"questions_with_fake_answers": result})



# # Run the Flask app on port 5000
# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5003, debug=True)

# # from flask import Flask, jsonify, request
# # import mysql.connector
# # import os
# # import random
# # import pandas as pd
# # from dotenv import load_dotenv

# # # Load environment variables
# # load_dotenv()

# # # Flask setup
# # app = Flask(__name__)

# # # Load the dataset for generating fake answers
# # dataset_path = "QuizBackend/data/preprocessed_dataset.csv"
# # dataset = pd.read_csv(dataset_path) if os.path.exists(dataset_path) else pd.DataFrame()

# # # Database connection function
# # def get_db_connection():
# #     return mysql.connector.connect(
# #         host=os.getenv('DB_HOST'),
# #         user=os.getenv('DB_USER'),
# #         password=os.getenv('DB_PASSWORD'),
# #         database=os.getenv('DB_NAME')
# #     )


# # # 1. Start Quiz - Sends the first question
# # @app.route("/api/start_quiz", methods=["POST"])
# # def start_quiz():
# #     data = request.get_json()
# #     user_id = data["user_id"]
# #     quiz_id = data["quiz_id"]

# #     conn = get_db_connection()
# #     cursor = conn.cursor(dictionary=True)

# #     # Query to get the first question for the quiz
# #     cursor.execute("""
# #         SELECT * FROM Question WHERE quiz_id = %s LIMIT 1
# #     """, (quiz_id,))
# #     question = cursor.fetchone()
    
# #     conn.close()

# #     if not question:
# #         return jsonify({"error": "No questions found for the quiz!"}), 404

# #     return jsonify({
# #         "question_id": question["question_id"],
# #         "description": question["description"],
# #         "options": [question["correct_answer"], "Option A", "Option B", "Option C"]  # Fake options for example
# #     }), 200


# # # 2. Submit Answer and Get Next Question - Validates the answer, saves it, and continues the quiz
# # @app.route("/api/submit_answer", methods=["POST"])
# # def submit_answer():
# #     data = request.get_json()
# #     user_id = data["user_id"]
# #     quiz_id = data["quiz_id"]
# #     question_id = data["question_id"]
# #     user_answer = data["user_answer"]

# #     conn = get_db_connection()
# #     cursor = conn.cursor()

# #     # Query the question to get the correct answer
# #     cursor.execute("""
# #         SELECT * FROM Question WHERE question_id = %s AND quiz_id = %s
# #     """, (question_id, quiz_id))
# #     question = cursor.fetchone()

# #     if not question:
# #         return jsonify({"error": "Invalid question!"}), 404

# #     correct_answer = question["correct_answer"]
# #     is_correct = (user_answer == correct_answer)

# #     # Save the result of this question
# #     cursor.execute("""
# #         INSERT INTO Question (quiz_id, description, is_correct, correct_answer)
# #         VALUES (%s, %s, %s, %s)
# #     """, (quiz_id, question["description"], is_correct, correct_answer))

# #     conn.commit()

# #     # Update user's score if they answered correctly
# #     if is_correct:
# #         cursor.execute("""
# #             UPDATE Quiz SET user_score = user_score + 10 WHERE quiz_id = %s AND user_id = %s
# #         """, (quiz_id, user_id))
# #         conn.commit()

# #     # Query the next question
# #     cursor.execute("""
# #         SELECT * FROM Question WHERE quiz_id = %s AND question_id > %s LIMIT 1
# #     """, (quiz_id, question_id))
# #     next_question = cursor.fetchone()

# #     conn.close()

# #     # If no more questions, return the final result
# #     if not next_question:
# #         return jsonify({
# #             "result": "Quiz finished",
# #             "message": "You have completed the quiz!",
# #             "score": get_final_score(user_id, quiz_id)  # Fetch user's final score
# #         }), 200

# #     # Send the next question and options
# #     return jsonify({
# #         "question_id": next_question["question_id"],
# #         "description": next_question["description"],
# #         "options": [next_question["correct_answer"], "Option A", "Option B", "Option C"]  # Fake options for example
# #     }), 200


# # # 3. Get Final Score after Quiz Completion
# # def get_final_score(user_id, quiz_id):
# #     conn = get_db_connection()
# #     cursor = conn.cursor(dictionary=True)

# #     cursor.execute("""
# #         SELECT user_score FROM Quiz WHERE quiz_id = %s AND user_id = %s
# #     """, (quiz_id, user_id))
# #     result = cursor.fetchone()

# #     conn.close()

# #     if result:
# #         return result["user_score"]
# #     return 0


# # # 4. Get Max Attempts Questions (For Fake Answer Generation)
# # @app.route("/api/get_max_attempts_questions", methods=["GET"])
# # def get_max_attempts_questions():
# #     conn = get_db_connection()
# #     cursor = conn.cursor(dictionary=True)

# #     # Query to get the questions with the maximum attempts
# #     cursor.execute("""
# #         SELECT description, correct_answer, COUNT(*) AS attempt_count 
# #         FROM Question 
# #         GROUP BY description, correct_answer 
# #         ORDER BY attempt_count DESC
# #         LIMIT 10;
# #     """)
# #     questions = cursor.fetchall()
# #     conn.close()

# #     if not questions:
# #         return jsonify({"error": "No questions found with attempts!"}), 404

# #     # For each question, generate fake answers from the dataset
# #     result = []
# #     for question in questions:
# #         correct_answer = question["correct_answer"]
# #         wrong_answers = dataset[dataset["Correct Answer"] != correct_answer]["Correct Answer"].unique().tolist()
# #         wrong_answers = random.sample(wrong_answers, min(len(wrong_answers), 3))

# #         options = [correct_answer] + wrong_answers
# #         random.shuffle(options)

# #         result.append({
# #             "question": question["description"],
# #             "correct_answer": correct_answer,
# #             "options": options
# #         })

# #     return jsonify({"questions_with_fake_answers": result})


# # # Run the Flask app on port 5000
# # if __name__ == "__main__":
# #     app.run(host="0.0.0.0", port=5003, debug=True)


# # from flask import Flask, jsonify, request
# # import mysql.connector
# # import os
# # import random
# # import pandas as pd
# # from dotenv import load_dotenv

# # # Load environment variables
# # load_dotenv()

# # # Flask setup
# # app = Flask(__name__)

# # # Load the dataset for generating fake answers
# # dataset_path = "QuizBackend/data/preprocessed_dataset.csv"
# # dataset = pd.read_csv(dataset_path) if os.path.exists(dataset_path) else pd.DataFrame()

# # # Database connection function
# # def get_db_connection():
# #     return mysql.connector.connect(
# #         host=os.getenv('DB_HOST'),
# #         user=os.getenv('DB_USER'),
# #         password=os.getenv('DB_PASSWORD'),
# #         database=os.getenv('DB_NAME')
# #     )


# # # 1. Start Quiz - Sends the first question
# # @app.route("/api/start_quiz", methods=["POST"])
# # def start_quiz():
# #     data = request.get_json()
# #     user_id = data["user_id"]
# #     quiz_id = data["quiz_id"]

# #     conn = get_db_connection()
# #     cursor = conn.cursor(dictionary=True)

# #     # Query to get the first question for the quiz
# #     cursor.execute("""
# #         SELECT * FROM Question WHERE quiz_id = %s LIMIT 1
# #     """, (quiz_id,))
# #     question = cursor.fetchone()
    
# #     conn.close()

# #     if not question:
# #         return jsonify({"error": "No questions found for the quiz!"}), 404

# #     return jsonify({
# #         "question_id": question["question_id"],
# #         "description": question["description"],
# #         "options": [question["correct_answer"], "Option A", "Option B", "Option C"]  # Fake options for example
# #     }), 200


# # # 2. Submit Answer and Get Next Question - Validates the answer, saves it, and continues the quiz
# # @app.route("/api/submit_answer", methods=["POST"])
# # def submit_answer():
# #     data = request.get_json()
# #     user_id = data["user_id"]
# #     quiz_id = data["quiz_id"]
# #     question_id = data["question_id"]
# #     user_answer = data["user_answer"]

# #     conn = get_db_connection()
# #     cursor = conn.cursor()

# #     # Query the question to get the correct answer
# #     cursor.execute("""
# #         SELECT * FROM Question WHERE question_id = %s AND quiz_id = %s
# #     """, (question_id, quiz_id))
# #     question = cursor.fetchone()

# #     if not question:
# #         return jsonify({"error": "Invalid question!"}), 404

# #     correct_answer = question["correct_answer"]
# #     is_correct = (user_answer == correct_answer)

# #     # Save the result of this question
# #     cursor.execute("""
# #         INSERT INTO Question (quiz_id, description, is_correct, correct_answer)
# #         VALUES (%s, %s, %s, %s)
# #     """, (quiz_id, question["description"], is_correct, correct_answer))

# #     conn.commit()

# #     # Update user's score if they answered correctly
# #     if is_correct:
# #         cursor.execute("""
# #             UPDATE Quiz SET user_score = user_score + 10 WHERE quiz_id = %s AND user_id = %s
# #         """, (quiz_id, user_id))
# #         conn.commit()

# #     # Query the next question
# #     cursor.execute("""
# #         SELECT * FROM Question WHERE quiz_id = %s AND question_id > %s LIMIT 1
# #     """, (quiz_id, question_id))
# #     next_question = cursor.fetchone()

# #     conn.close()

# #     # If no more questions, return the final result
# #     if not next_question:
# #         return jsonify({
# #             "result": "Quiz finished",
# #             "message": "You have completed the quiz!",
# #             "score": get_final_score(user_id, quiz_id)  # Fetch user's final score
# #         }), 200

# #     # Send the next question and options
# #     return jsonify({
# #         "question_id": next_question["question_id"],
# #         "description": next_question["description"],
# #         "options": [next_question["correct_answer"], "Option A", "Option B", "Option C"]  # Fake options for example
# #     }), 200


# # # 3. Get Final Score after Quiz Completion
# # def get_final_score(user_id, quiz_id):
# #     conn = get_db_connection()
# #     cursor = conn.cursor(dictionary=True)

# #     cursor.execute("""
# #         SELECT user_score FROM Quiz WHERE quiz_id = %s AND user_id = %s
# #     """, (quiz_id, user_id))
# #     result = cursor.fetchone()

# #     conn.close()

# #     if result:
# #         return result["user_score"]
# #     return 0


# # # 4. Get Max Attempts Questions (For Fake Answer Generation)
# # @app.route("/api/get_max_attempts_questions", methods=["GET"])
# # def get_max_attempts_questions():
# #     conn = get_db_connection()
# #     cursor = conn.cursor(dictionary=True)

# #     # Query to get the questions with the maximum attempts
# #     cursor.execute("""
# #         SELECT description, correct_answer, COUNT(*) AS attempt_count 
# #         FROM Question 
# #         GROUP BY description, correct_answer 
# #         ORDER BY attempt_count DESC
# #         LIMIT 10;
# #     """)
# #     questions = cursor.fetchall()
# #     conn.close()

# #     if not questions:
# #         return jsonify({"error": "No questions found with attempts!"}), 404

# #     # For each question, generate fake answers from the dataset
# #     result = []
# #     for question in questions:
# #         correct_answer = question["correct_answer"]
# #         wrong_answers = dataset[dataset["Correct Answer"] != correct_answer]["Correct Answer"].unique().tolist()
# #         wrong_answers = random.sample(wrong_answers, min(len(wrong_answers), 3))

# #         options = [correct_answer] + wrong_answers
# #         random.shuffle(options)

# #         result.append({
# #             "question": question["description"],
# #             "correct_answer": correct_answer,
# #             "options": options
# #         })

# #     return jsonify({"questions_with_fake_answers": result})


# # # Run the Flask app on port 5000
# # if __name__ == "__main__":
# #     app.run(host="0.0.0.0", port=5003, debug=True)