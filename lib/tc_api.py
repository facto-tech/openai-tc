import openai
import fitz
from docx import Document
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize OpenAI client
openai.api_key = os.getenv("OPENAI_API_KEY")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "../docs")
OUTPUT_DIR = os.path.join(BASE_DIR, "../output")

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
{spec_text}
"""

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a QA engineer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=7500
    )

    return response['choices'][0]['message']['content']


# --- Main Script Function ---
def process_document(filename: str):
    filepath = os.path.join(DOCS_DIR, filename)

    if not os.path.isfile(filepath):
        print(f"Error: File '{filename}' not found in docs directory.")
        return

    try:
        print(f"Processing {filename}...")

        if filename.lower().endswith(".pdf"):
            extracted_text = extract_text_from_pdf(filepath)
        elif filename.lower().endswith(".docx"):
            extracted_text = extract_text_from_docx(filepath)
        else:
            print("Error: Only PDF and DOCX files are supported.")
            return

        print("Generating test cases with OpenAI...")
        test_cases = generate_test_cases(extracted_text)

        output_file = os.path.join(OUTPUT_DIR, f"{os.path.splitext(filename)[0]}_test_cases.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(test_cases)

        print(f"✅ Test cases written to {output_file}")

    except Exception as e:
        print(f"Error: {str(e)}")


# --- Main execution ---
if __name__ == "__main__":
    # Check if docs directory exists
    if not os.path.exists(DOCS_DIR):
        print(f"Creating docs directory at {DOCS_DIR}")
        os.makedirs(DOCS_DIR)
        print("Please place your PDF or DOCX files in the 'docs' folder and run the script again.")
        exit()

    # List available files
    files = [f for f in os.listdir(DOCS_DIR) if f.lower().endswith(('.pdf', '.docx'))]

    if not files:
        print("No PDF or DOCX files found in the 'docs' directory.")
        print("Please add some files and run the script again.")
        exit()

    print("Available files:")
    for i, file in enumerate(files, 1):
        print(f"{i}. {file}")

    # Process all files or let user choose
    choice = input("\nEnter file number to process (or 'all' for all files): ").strip()

    if choice.lower() == 'all':
        for file in files:
            process_document(file)
            print("-" * 50)
    else:
        try:
            file_index = int(choice) - 1
            if 0 <= file_index < len(files):
                process_document(files[file_index])
            else:
                print("Invalid file number.")
        except ValueError:
            print("Invalid input. Please enter a number or 'all'.")
