from fastapi import FastAPI
from fastapi.responses import JSONResponse
import openai
import fitz 
from docx import Document
import os

app = FastAPI()

openai.api_key = "<INSERT_API_KEY>" #change to your OpenAI API key
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "../docs")
OUTPUT_DIR = os.path.join(BASE_DIR, "../output")

# --- Helper Functions ---
def extract_text_from_pdf(filepath) -> str:
    doc = fitz.open(filepath)
    text = "\n".join([page.get_text() for page in doc])
    doc.close()
    return text


def extract_text_from_docx(filepath) -> str:
    doc = Document(filepath)
    return "\n".join([para.text for para in doc.paragraphs])


def generate_test_cases(spec_text: str) -> str:
    prompt = f"""
You are a QA engineer. Based on the following technical specification, generate a list of test cases which are suitable, or
if possible be used for automation in a table format with the following columns:

Test Case ID | Title | Description | Preconditions | Steps | Expected Result

Technical Specification:
""" + spec_text

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a QA engineer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=1500
    )

    return response['choices'][0]['message']['content']


# --- Main Script Function ---
def process_document(filename: str):
    filepath = os.path.join(DOCS_DIR, filename)

    if not os.path.isfile(filepath):
        return {"error": f"File '{filename}' not found in docs directory."}

    try:
        if filename.lower().endswith(".pdf"):
            extracted_text = extract_text_from_pdf(filepath)
        elif filename.lower().endswith(".docx"):
            extracted_text = extract_text_from_docx(filepath)
        else:
            return {"error": "Only PDF and DOCX files are supported."}

        test_cases = generate_test_cases(extracted_text)

        output_file = os.path.join(OUTPUT_DIR, f"{os.path.splitext(filename)[0]}_test_cases.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(test_cases)

        return {"message": f"Test cases written to {output_file}"}
    except Exception as e:
        return {"error": str(e)}


