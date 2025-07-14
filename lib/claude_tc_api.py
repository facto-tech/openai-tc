import anthropic
import fitz 
from docx import Document
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize Anthropic client
client = anthropic.Anthropic(
    api_key=os.getenv("CLAUDE_API_KEY")
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

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


def extract_text_from_file(filepath: str) -> tuple[str, str]:
    """Extract text from a file and return (filename, content)"""
    filename = os.path.basename(filepath)
    
    if filepath.lower().endswith(".pdf"):
        content = extract_text_from_pdf(filepath)
    elif filepath.lower().endswith(".docx"):
        content = extract_text_from_docx(filepath)
    else:
        raise ValueError(f"Unsupported file format: {filename}")
    
    return filename, content


def generate_test_cases(documents: list[tuple[str, str]]) -> str:
    """Generate test cases from multiple documents"""
    
    # Prepare the combined document content
    combined_content = ""
    for filename, content in documents:
        combined_content += f"\n\n=== DOCUMENT: {filename} ===\n"
        combined_content += content
        combined_content += f"\n=== END OF {filename} ===\n"
    
    # List the files being processed
    file_list = ", ".join([filename for filename, _ in documents])
    
    prompt = f"""
You are a QA engineer. I have provided you with {len(documents)} document(s) ({file_list}) that contain specifications and requirements for an Oracle Fusion Fixed Assets implementation.

Please read through ALL the provided documents and generate a comprehensive test case suite that covers all the requirements mentioned across all documents.

Generate test cases in a table format with the following columns:
Test Case ID | Title | Description | Preconditions | Steps | Expected Result

Requirements:
1. Create test cases that are suitable for both manual and automated testing
2. Cover all functional requirements mentioned in the documents
3. Include integration test cases between different modules (Procurement, Payables, Fixed Assets, GL)
4. Include both positive and negative test scenarios
5. Focus on Oracle Fusion specific functionality
6. Group related test cases logically (e.g., CIP Asset Management, Asset Creation, etc.)
7. Ensure test cases are traceable back to the original requirements
8. Include data validation and error handling scenarios

Ignore any character limits and generate full output file.

Combined Document Content:
{combined_content}
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=10000,
        temperature=0.2,
        system="You are an experienced QA engineer specializing in Oracle Fusion applications and ERP testing.",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response.content[0].text


# --- Main Script Function ---
def process_multiple_documents(filenames: list[str]):
    """Process multiple documents and generate combined test cases"""
    
    if not filenames:
        print("No files provided for processing.")
        return
    
    documents = []
    processed_files = []
    
    print(f"Processing {len(filenames)} file(s)...")
    
    for filename in filenames:
        filepath = os.path.join(DOCS_DIR, filename)
        
        if not os.path.isfile(filepath):
            print(f"Warning: File '{filename}' not found in docs directory. Skipping...")
            continue
        
        try:
            print(f"  Reading {filename}...")
            file_name, content = extract_text_from_file(filepath)
            documents.append((file_name, content))
            processed_files.append(filename)
            
        except Exception as e:
            print(f"Error processing {filename}: {str(e)}")
            continue
    
    if not documents:
        print("No documents were successfully processed.")
        return
    
    try:
        print("\nGenerating comprehensive test cases with Claude...")
        test_cases = generate_test_cases(documents)
        
        # Create output filename based on processed files
        if len(processed_files) == 1:
            output_name = f"{os.path.splitext(processed_files[0])[0]}_test_cases.txt"
        else:
            output_name = f"combined_test_cases_{len(processed_files)}_files.txt"
        
        output_file = os.path.join(OUTPUT_DIR, output_name)
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"Test Cases Generated from: {', '.join(processed_files)}\n")
            f.write(f"Generated on: {os.path.basename(__file__)}\n")
            f.write("=" * 80 + "\n\n")
            f.write(test_cases)

        print(f"✅ Test cases written to {output_file}")
        print(f"✅ Processed {len(processed_files)} file(s) successfully")
        
    except Exception as e:
        print(f"Error generating test cases: {str(e)}")


def select_files(available_files: list[str]) -> list[str]:
    """Allow user to select multiple files"""
    
    print("\nSelect files to process:")
    print("Enter numbers separated by commas (e.g., 1,3,5) or 'all' for all files")
    
    choice = input("Your choice: ").strip()
    
    if choice.lower() == 'all':
        return available_files
    
    try:
        # Parse comma-separated numbers
        selected_indices = [int(x.strip()) - 1 for x in choice.split(',')]
        selected_files = []
        
        for index in selected_indices:
            if 0 <= index < len(available_files):
                selected_files.append(available_files[index])
            else:
                print(f"Warning: Invalid file number {index + 1}. Skipping...")
        
        return selected_files
        
    except ValueError:
        print("Invalid input format. Please enter numbers separated by commas or 'all'.")
        return []


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
    
    # Let user select multiple files
    selected_files = select_files(files)
    
    if selected_files:
        print(f"\nSelected files: {', '.join(selected_files)}")
        process_multiple_documents(selected_files)
    else:
        print("No valid files selected.")