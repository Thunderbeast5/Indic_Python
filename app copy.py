from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq
import cohere
import re
import threading
import time

app = Flask(__name__)
CORS(app)

# API Keys
GROQ_API_KEY = "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"  # Replace with your actual API key
COHERE_API_KEY = "c4mOumKst3aQmG9rIpFFvFrtpCDwnCIt8MrcupdG"  # Replace with your actual Cohere API key

# Initialize API clients
groq_client = Groq(api_key=GROQ_API_KEY)
cohere_client = cohere.Client(COHERE_API_KEY)

# Boilerplate message
BOILERPLATE_MESSAGE = """
Hello from INDIC! 🌟
I am here to assist you with all your queries, doubts, and questions.
I can help with anything related to:
- Your language learning journey.
- Queries about the syllabus.
- Fun games that can make learning more exciting!🎮
- Or any feedback you have for the platform!

Feel free to ask me anything within these topics, and let's get started on your learning path!
"""

# Chat state tracking for multi-turn conversations
chat_states = {}

# Cache for generated syllabi
syllabus_cache = {}

@app.route('/test', methods=['GET'])
def test_connection():
    return jsonify({"status": "success", "message": "Backend is running!"})

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('userMessage', '').strip()
        user_id = data.get('userId', 'default_user')  # For tracking conversation state
        
        # If the user message is empty, return the boilerplate message
        if not user_message:
            return jsonify({"reply": BOILERPLATE_MESSAGE})
            
        # Check if syllabus generation is already in progress for this user
        if user_id in chat_states:
            state = chat_states[user_id]
            
            if state['expecting'] == 'syllabus_confirm':
                if re.search(r'yes|yeah|sure|ok|okay|generate|proceed', user_message.lower()):
                    # User confirmed, now ask for proficiency
                    chat_states[user_id] = {'expecting': 'proficiency', 'syllabus_data': {}}
                    return jsonify({"reply": "Great! What proficiency level do you need? (beginner, intermediate, advanced)"})
                else:
                    # User declined, reset state
                    chat_states.pop(user_id, None)
                    return jsonify({"reply": "No problem! Let me know if you need anything else."})
                    
            elif state['expecting'] == 'proficiency':
                # Store proficiency and ask for language
                state['syllabus_data']['proficiency'] = user_message.lower()
                state['expecting'] = 'language'
                return jsonify({"reply": "Which language would you like to learn?"})
                
            elif state['expecting'] == 'language':
                # Store language and ask for purpose
                state['syllabus_data']['language'] = user_message
                state['expecting'] = 'purpose'
                return jsonify({"reply": "What is your purpose for learning this language? (e.g., travel, business, general knowledge)"})
                
            elif state['expecting'] == 'purpose':
                # Get all parameters and generate syllabus
                state['syllabus_data']['purpose'] = user_message
                syllabus_data = state['syllabus_data']
                
                # Check if we have this syllabus in cache already
                cache_key = f"{syllabus_data['proficiency']}_{syllabus_data['language']}_{syllabus_data['purpose']}"
                if cache_key in syllabus_cache:
                    # Use cached syllabus
                    formatted_syllabus = syllabus_cache[cache_key]
                    # Clear the state
                    chat_states.pop(user_id, None)
                    return jsonify({"reply": formatted_syllabus})
                
                # Generate the syllabus
                try:
                    # Use a shorter version for faster generation during testing
                    syllabus = generate_syllabus_shorter(
                        syllabus_data['proficiency'],
                        syllabus_data['language'],
                        syllabus_data['purpose']
                    )
                    
                    # Format the syllabus for chat display
                    formatted_syllabus = format_syllabus_for_chat(syllabus)
                    
                    # Cache the result
                    syllabus_cache[cache_key] = formatted_syllabus
                    
                    # Clear the state
                    chat_states.pop(user_id, None)
                    
                    return jsonify({"reply": formatted_syllabus})
                except Exception as e:
                    chat_states.pop(user_id, None)
                    return jsonify({"reply": f"Sorry, I couldn't generate the syllabus: {str(e)}"})
        
        # Check if this is a request to generate a syllabus
        if re.search(r'(create|generate|make|build|design).*syllabus', user_message.lower()):
            chat_states[user_id] = {'expecting': 'syllabus_confirm'}
            return jsonify({
                "reply": "Would you like me to create a customized language learning syllabus for you?"
            })
            
        # For all other messages, use Groq API
        response = generate_groq_response(user_message)
        return jsonify({"reply": response})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"reply": "Sorry, something went wrong on the server. Please try again later."}), 500

# Function to interact with Groq API
def generate_groq_response(user_message):
    try:
        # Prepare the chat request
        messages = [
            {"role": "system", "content": "You are a helpful assistant for a language learning platform called INDIC."},
            {"role": "user", "content": user_message}
        ]

        # Send request to Groq's LLaMA 3.3-70B model
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_completion_tokens=150,
            stream=False  # Disable streaming for a simple response
        )

        return completion.choices[0].message.content.strip()

    except Exception as e:
        print(f"Groq API Error: {e}")
        return "Sorry, I couldn't generate a response. Please try again later."

# Function to generate syllabus using Cohere - optimized for testing
def generate_syllabus_shorter(proficiency, language, purpose):
    # Construct the input prompt for Cohere API - shorter for testing
    input_prompt = (
        f"Generate a brief learning conversation script (5 exchanges) for learning {language} "
        f"at the {proficiency} level, focusing on {purpose}. Use this format:\n\n"
        f"Teacher: [Dialogue]\n"
        f"Student: [Response]\n\n"
    )

    # Call Cohere API with fewer tokens and higher temperature for faster response
    response = cohere_client.generate(
        model='command',
        prompt=input_prompt,
        max_tokens=500,  # Reduced token count
        temperature=0.9,  # Higher temperature for faster but more variable responses
    )

    # Extract generated text from the response
    output_text = response.generations[0].text.strip()

    # Format the output into a structured array
    structured_syllabus = []
    exchanges = output_text.split("Teacher:")  # Split by teacher's dialogue to separate exchanges

    # Process each exchange from the generated text
    for exchange in exchanges:
        lines = exchange.strip().split("\n")
        if len(lines) >= 2:
            # Extract teacher's dialogue and student's expected response
            teacher_dialogue = lines[0].strip()
            student_response = lines[1].replace("Student:", "").strip()

            # Append each exchange as a dictionary to the list
            structured_syllabus.append({
                "text": teacher_dialogue,  # Teacher's dialogue
                "expected": student_response,  # Student's expected response
                "english": "",  # Placeholder for English translation
                "animation": ""  # Placeholder for animation
            })

    return structured_syllabus

# Original full syllabus generator (use this in production)
def generate_syllabus(proficiency, language, purpose):
    # Construct the input prompt for Cohere API
    input_prompt = (
        f"Generate a structured learning conversation script for learning {language} "
        f"at the {proficiency} level, focusing on {purpose}. The dialogue should be engaging and realistic, mimicking "
        f"a real classroom session where the teacher explains concepts, asks questions, and the student responds. "
        f"Format each exchange as follows:\n\n"
        f"Teacher: [Dialogue explaining a concept and prompting the student on what to say].\n"
        f"Student: [Expected Response]\n\n"
        f"Ensure at least 10 structured exchanges, with clear interactions."
    )

    # Call Cohere API to generate the content
    response = cohere_client.generate(
        model='command',  # Use the appropriate model ID for Cohere
        prompt=input_prompt,
        max_tokens=1024,  # Limit the number of tokens to avoid overloading
        temperature=0.7,  # Adjust temperature for creativity
    )

    # Extract generated text from the response
    output_text = response.generations[0].text.strip()

    # Format the output into a structured array
    structured_syllabus = []
    exchanges = output_text.split("Teacher:")  # Split by teacher's dialogue to separate exchanges

    # Process each exchange from the generated text
    for exchange in exchanges:
        lines = exchange.strip().split("\n")
        if len(lines) >= 2:
            # Extract teacher's dialogue and student's expected response
            teacher_dialogue = lines[0].strip()
            student_response = lines[1].replace("Student:", "").strip()

            # Append each exchange as a dictionary to the list
            structured_syllabus.append({
                "text": teacher_dialogue,  # Teacher's dialogue
                "expected": student_response,  # Student's expected response
                "english": "",  # Placeholder for English translation
                "animation": ""  # Placeholder for animation
            })

    return structured_syllabus

# Format syllabus for chat display
def format_syllabus_for_chat(syllabus):
    formatted_text = f"Here's your personalized syllabus:\n\n"
    
    for i, item in enumerate(syllabus):
        if item["text"]:  # Skip empty entries
            formatted_text += f"Lesson {i+1}:\n"
            formatted_text += f"Teacher: {item['text']}\n"
            formatted_text += f"Student: {item['expected']}\n\n"
    
    formatted_text += "You can follow this curriculum to improve your language skills. Would you like to practice any specific lesson?"
    
    return formatted_text

# Run Flask app
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)