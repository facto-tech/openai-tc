import streamlit as st
import openai
import fitz
from docx import Document
import os
from dotenv import load_dotenv
import base64
import tempfile
import zipfile
import io
import json
from datetime import datetime
import subprocess
import platform
import time

# Load environment variables
load_dotenv()

# Page config
st.set_page_config(
    page_title="Facto AI Test Case Generator",
    page_icon="🧪",
    layout="wide"
)

# Initialize OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# --- Helper Functions ---
def extract_text_from_pdf(filepath) -> str:
    doc = fitz.open(filepath)
    text = "\n".join([page.get_text() for page in doc])
    doc.close()
    return text

def extract_text_from_docx(filepath) -> str:
    doc = Document(filepath)
    return "\n".join([para.text for para in doc.paragraphs])

def extract_text_from_doc(filepath) -> str:
    """Extract text from older .doc files"""
    try:
        # Method 1: Try python-docx2txt (recommended)
        import docx2txt
        return docx2txt.process(filepath)
    except ImportError:
        try:
            # Method 2: Try antiword (Linux/Mac)
            if platform.system() in ['Linux', 'Darwin']:
                result = subprocess.run(['antiword', filepath], 
                                      capture_output=True, text=True, encoding='utf-8')
                if result.returncode == 0:
                    return result.stdout
                else:
                    raise Exception("Antiword failed")
            else:
                raise Exception("Antiword not available on Windows")
        except (subprocess.SubprocessError, FileNotFoundError):
            try:
                # Method 3: Try LibreOffice conversion (if available)
                temp_dir = os.path.dirname(filepath)
                result = subprocess.run([
                    'libreoffice', '--headless', '--convert-to', 'txt', 
                    '--outdir', temp_dir, filepath
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    txt_file = os.path.splitext(filepath)[0] + '.txt'
                    if os.path.exists(txt_file):
                        with open(txt_file, 'r', encoding='utf-8') as f:
                            content = f.read()
                        os.remove(txt_file)  # Clean up
                        return content
                
                raise Exception("LibreOffice conversion failed")
                
            except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
                # Fallback: Suggest manual conversion
                raise Exception(
                    "Could not extract text from .doc file. "
                    "Please install docx2txt (pip install docx2txt) "
                    "or convert the file to .docx format first."
                )

def encode_image_to_base64(filepath) -> str:
    with open(filepath, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def process_image_with_vision(filepath) -> str:
    """Use OpenAI Vision API to analyze process maps/diagrams"""
    try:
        base64_image = encode_image_to_base64(filepath)
        
        file_extension = os.path.splitext(filepath)[1].lower()
        mime_type = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg', 
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }.get(file_extension, 'image/png')
        
        # Try GPT-4-Vision first
        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-4-vision-preview",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": """Analyze this process map/diagram and provide a detailed textual description including:
                                    1. Overall process flow and purpose
                                    2. Key steps and decision points
                                    3. Inputs and outputs
                                    4. Roles/actors involved
                                    5. Business rules and conditions
                                    6. Any error handling or exception paths"""
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{mime_type};base64,{base64_image}",
                                        "detail": "high"
                                    }
                                }
                            ]
                        }
                    ],
                    max_tokens=4000,
                    temperature=0.2
                )
                return response['choices'][0]['message']['content']
                
            except openai.error.InvalidRequestError as e:
                # Vision API not available
                if "vision" in str(e).lower() or "model" in str(e).lower():
                    raise Exception("Vision API not available on this account")
                else:
                    raise e
            except openai.error.RateLimitError as e:
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)  # 5, 10 second delays
                    st.warning(f"Vision API rate limit hit. Waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    raise e
                    
    except Exception as e:
        # Fallback: Return a template for manual description
        filename = os.path.basename(filepath)
        return f"""
PROCESS MAP ANALYSIS REQUIRED - {filename}

Since Vision API is not available, please manually describe this process map including:

1. OVERALL PROCESS FLOW AND PURPOSE:
   [Describe what this process accomplishes and its main objective]

2. KEY STEPS AND DECISION POINTS:
   [List the main steps in sequence and any decision/branching points]

3. INPUTS AND OUTPUTS:
   [What goes into the process and what comes out]

4. ROLES/ACTORS INVOLVED:
   [Who or what systems are involved in this process]

5. BUSINESS RULES AND CONDITIONS:
   [Any specific rules, conditions, or constraints]

6. ERROR HANDLING OR EXCEPTION PATHS:
   [How errors or exceptions are handled]

MANUAL INPUT NEEDED: Please replace the sections above with actual content from the process map, then re-run the test case generation.
"""

def generate_test_cases(spec_text: str, document_type: str, output_format: str, model: str = "gpt-3.5-turbo") -> str:
    format_instructions = {
        "markdown": "Format the output as clean Markdown tables",
        "csv": "Format the output as CSV with proper delimiters",
        "json": "Format the output as structured JSON with proper schema",
        "excel": "Format the output as tab-separated values suitable for Excel import"
    }
    
    prompt = f"""
You are a senior QA engineer. Based on the following {document_type}, generate comprehensive test cases.

{format_instructions[output_format]}

Use these columns: Test Case ID | Title | Description | Preconditions | Steps | Expected Result | Priority | Test Type

Include various test types: Functional, Boundary, Negative, Integration, User Acceptance

{document_type.title()}:
{spec_text}
"""
    
    # Add retry logic with exponential backoff
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = openai.ChatCompletion.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a senior QA engineer with expertise in test case design."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=4000 if model == "gpt-3.5-turbo" else 8000
            )
            return response['choices'][0]['message']['content']
            
        except openai.error.RateLimitError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                st.warning(f"Rate limit hit. Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            else:
                raise e
        except Exception as e:
            raise e

def process_uploaded_file(uploaded_file, output_format, model_choice, enable_vision):
    """Process a single uploaded file and return test cases"""
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{uploaded_file.name}") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        # Determine file type and extract content
        filename = uploaded_file.name.lower()
        
        if filename.endswith('.pdf'):
            extracted_text = extract_text_from_pdf(tmp_path)
            doc_type = "technical specification"
        elif filename.endswith('.docx'):
            extracted_text = extract_text_from_docx(tmp_path)
            doc_type = "technical specification"
        elif filename.endswith('.doc'):
            extracted_text = extract_text_from_doc(tmp_path)
            doc_type = "technical specification"
        elif filename.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            if enable_vision:
                extracted_text = process_image_with_vision(tmp_path)
            else:
                extracted_text = f"Process map file: {uploaded_file.name}\n\nVision analysis is disabled. Please enable 'Process Map Analysis' in the sidebar or manually describe the process flow."
            doc_type = "process map"
        else:
            return None, "Unsupported file format"
        
        # Generate test cases
        test_cases = generate_test_cases(extracted_text, doc_type, output_format, model_choice)
        
        # Clean up temp file
        os.unlink(tmp_path)
        
        return test_cases, None
        
    except Exception as e:
        return None, str(e)

# --- Streamlit UI ---
def main():
    st.image("assets/Facto_site_header.webp")
    st.title("🧪 Facto AI Test Case Generator")
    st.markdown("Upload your documents or process maps to automatically generate comprehensive test cases using AI.")
    
    # Sidebar for configuration
    st.sidebar.header("Configuration")
    
    # API Key check
    if not openai.api_key:
        st.sidebar.error("⚠️ API key not found. Please check and reload.")
        st.stop()
    else:
        st.sidebar.success("✅ API key loaded")
    
    # Model selection
    model_choice = st.sidebar.selectbox(
        "AI Model",
        ["gpt-3.5-turbo", "gpt-4", "gpt-4o"],
        index=0,  # Default to gpt-3.5-turbo
        help="Choose the AI model. GPT-3.5 is fastest and most reliable for most accounts."
    )
    
    # Vision API toggle
    enable_vision = st.sidebar.checkbox(
        "Enable Process Map Analysis",
        value=False,
        help="Requires GPT-4-Vision access. Uncheck if you get vision API errors."
    )
    
    # Output format selection
    output_format = st.sidebar.selectbox(
        "Output Format",
        ["markdown", "csv", "json", "excel"],
        help="Choose how you want the test cases formatted"
    )
    
    # File upload
    st.header("📁 Upload Documents")
    
    uploaded_files = st.file_uploader(
        "Choose files",
        type=['pdf', 'doc', 'docx', 'png', 'jpg', 'jpeg', 'gif', 'webp'],
        accept_multiple_files=True,
        help="Supported formats: PDF, DOC, DOCX, PNG, JPG, JPEG, GIF, WEBP"
    )
    
    if uploaded_files:
        st.success(f"✅ {len(uploaded_files)} file(s) uploaded successfully")
        
        # Show file details
        with st.expander("📋 File Details"):
            for file in uploaded_files:
                file_type = "🖼️ Process Map" if file.name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')) else "📄 Document"
                st.write(f"{file_type} **{file.name}** ({file.size:,} bytes)")
        
        # Process files button
        if st.button("🚀 Generate Test Cases", type="primary"):
            
            # Progress tracking
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            results = {}
            
            for i, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"Processing {uploaded_file.name}...")
                progress_bar.progress((i) / len(uploaded_files))
                
                # Add delay between files to respect rate limits
                if i > 0:
                    st.info("⏳ Waiting to respect API rate limits...")
                    time.sleep(2)  # 2-second delay between files
                
                test_cases, error = process_uploaded_file(uploaded_file, output_format, model_choice, enable_vision)
                
                if error:
                    st.error(f"❌ Error processing {uploaded_file.name}: {error}")
                else:
                    results[uploaded_file.name] = test_cases
            
            progress_bar.progress(1.0)
            status_text.text("✅ All files processed!")
            
            # Display results
            if results:
                st.header("📋 Generated Test Cases")
                
                # Create tabs for multiple files
                if len(results) > 1:
                    tabs = st.tabs(list(results.keys()))
                    
                    for tab, (filename, content) in zip(tabs, results.items()):
                        with tab:
                            display_results(filename, content, output_format)
                else:
                    filename, content = list(results.items())[0]
                    display_results(filename, content, output_format)
                
                # Download all results
                if len(results) > 1:
                    download_all_results(results, output_format)

def display_results(filename, content, output_format):
    """Display results for a single file"""
    
    st.subheader(f"Test Cases for: {filename}")
    
    # Display content based on format
    if output_format == "markdown":
        st.markdown(content)
    elif output_format == "json":
        try:
            # Try to parse and display as JSON
            json_data = json.loads(content)
            st.json(json_data)
        except:
            st.code(content, language="json")
    else:
        st.text_area("Generated Test Cases", content, height=400)
    
    # Download button for individual file
    file_extension = {
        "markdown": "md",
        "csv": "csv", 
        "json": "json",
        "excel": "tsv"
    }[output_format]
    
    filename_clean = os.path.splitext(filename)[0]
    download_filename = f"{filename_clean}_test_cases.{file_extension}"
    
    st.download_button(
        label=f"📥 Download Test Cases ({output_format.upper()})",
        data=content,
        file_name=download_filename,
        mime=f"text/{file_extension}"
    )

def download_all_results(results, output_format):
    """Create downloadable zip file with all results"""
    
    st.subheader("📦 Download All Results")
    
    # Create zip file in memory
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, content in results.items():
            file_extension = {
                "markdown": "md",
                "csv": "csv",
                "json": "json", 
                "excel": "tsv"
            }[output_format]
            
            filename_clean = os.path.splitext(filename)[0]
            download_filename = f"{filename_clean}_test_cases.{file_extension}"
            
            zip_file.writestr(download_filename, content)
    
    zip_buffer.seek(0)
    
    st.download_button(
        label="📦 Download All Test Cases (ZIP)",
        data=zip_buffer.getvalue(),
        file_name=f"test_cases_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
        mime="application/zip"
    )

if __name__ == "__main__":
    main()