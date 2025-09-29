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
import atexit
import shutil
import gc

# Load environment variables for development
load_dotenv()

# Import secure configuration
try:
    from secure_config import setup_openai
    USING_SECURE_CONFIG = True
    CONFIG_TYPE = "AWS"
except ImportError:
    try:
        from gcp_secure_config import setup_openai
        USING_SECURE_CONFIG = True
        CONFIG_TYPE = "GCP"
    except ImportError:
        USING_SECURE_CONFIG = False
        CONFIG_TYPE = "LOCAL"

# Page config
st.set_page_config(
    page_title="Facto AI Test Case Generator",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize OpenAI securely
if USING_SECURE_CONFIG:
    # Production: Use secure configuration
    setup_openai()
else:
    # Development: Use environment variable
    openai.api_key = os.getenv("OPENAI_API_KEY")

# Global temp directory tracking
TEMP_FILES = []

def cleanup_temp_files():
    """Clean up all temporary files"""
    global TEMP_FILES
    for temp_file in TEMP_FILES:
        try:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
        except:
            pass
    TEMP_FILES.clear()

# Register cleanup function to run on exit
atexit.register(cleanup_temp_files)

# Import user management system
try:
    # Check if we're in production (Firestore available)
    from google.cloud import firestore
    firestore.Client(project=os.getenv('GOOGLE_CLOUD_PROJECT'))
    
    # If we get here, Firestore is available - use production auth
    from user_management import (
        check_authentication, login_form, get_current_user, has_permission,
        user_management_panel, logout, init_super_admin
    )
    USING_PRODUCTION_AUTH = True
    
except Exception as e:
    # Firestore not available - use development auth
    # Simple development authentication
    def check_authentication():
        return st.session_state.get('dev_authenticated', False)
    
    def login_form():
        st.title("🔐 Facto AI - Development Login")
        st.warning("🧪 Running in development mode (Firestore unavailable)")
        
        if st.button("Quick Login (Admin)"):
            st.session_state.dev_authenticated = True
            st.session_state.user_data = {
                'email': 'admin@facto.com.au', 
                'role': 'super_admin',
                'login_count': 1
            }
            st.rerun()
    
    def get_current_user():
        return st.session_state.get('user_data', {})
    
    def has_permission(role='user'):
        return check_authentication()
    
    def logout():
        st.session_state.dev_authenticated = False
        st.session_state.user_data = None
        st.rerun()
    
    def user_management_panel():
        st.header("👥 User Management")
        st.warning("🧪 Development mode - user management disabled")
        st.info("Enable Firestore to access full user management features")
    
    def init_super_admin():
        pass
    
    USING_PRODUCTION_AUTH = False

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

def process_image_with_vision(filepath, model="gpt-4o") -> str:
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
        
        # Use the selected model for vision analysis
        vision_model = model if model in ["gpt-4o", "gpt-4", "gpt-4-vision-preview"] else "gpt-4o"
        
        # Try vision analysis
        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = openai.ChatCompletion.create(
                    model=vision_model,
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
                    raise Exception(f"Vision API not available with model {vision_model}")
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

Vision analysis failed ({str(e)}). Please manually describe this process map including:

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

def generate_test_cases(spec_text: str, document_type: str, output_format: str, model: str = "gpt-3.5-turbo", target_system: str = None) -> str:
    format_instructions = {
        "markdown": "Format the output as clean Markdown tables",
        "csv": "Format the output as CSV with proper delimiters",
        "json": "Format the output as structured JSON with proper schema",
        "excel": "Format the output as tab-separated values suitable for Excel import"
    }
    
    # System-specific context
    system_context = ""
    if target_system and target_system != "General":
        system_contexts = {
            "Oracle": """
Consider Oracle-specific aspects:
- Database integrity constraints and triggers
- PL/SQL stored procedures and packages
- Oracle Forms/APEX UI validation
- Concurrent program execution
- Data security and user privileges
- Performance implications of queries
""",
            "SAP": """
Consider SAP-specific aspects:
- Transaction codes (T-codes) and user exits
- ABAP custom code and BAPIs
- Authorization objects and roles
- Integration with other SAP modules
- Batch job processing
- Customizing and configuration tables
""",
            "Salesforce": """
Consider Salesforce-specific aspects:
- Validation rules and field dependencies
- Workflow rules and process builder flows
- Apex triggers and classes
- Profile and permission set security
- Lightning component functionality
- API integration limits
- Governor limits and bulk processing
""",
            "MuleSoft": """
Consider MuleSoft-specific aspects:
- API endpoint validation
- Data transformation and mapping
- Error handling and retry logic
- Authentication and security policies
- Rate limiting and throttling
- Integration flow orchestration
- Message payload validation
"""
        }
        system_context = system_contexts.get(target_system, "")
    
    system_info = f"\n\nTarget System: {target_system}\n{system_context}" if target_system and target_system != "General" else ""
    
    prompt = f"""
You are a senior QA engineer with expertise in enterprise systems testing. Based on the following {document_type}, generate comprehensive test cases.

{format_instructions[output_format]}

Use these columns: Test Case ID | Title | Description | Preconditions | Steps | Expected Result | Priority | Test Type
{system_info}

Include various test types: Functional, Boundary, Negative, Integration, User Acceptance, System-Specific

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
                    {"role": "system", "content": f"You are a senior QA engineer with expertise in test case design{' and ' + target_system + ' systems' if target_system and target_system != 'General' else ''}."},
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

def process_uploaded_file(uploaded_file, output_format, model_choice, enable_vision, target_system):
    """Process a single uploaded file and return test cases"""
    global TEMP_FILES
    tmp_path = None
    
    try:
        # Create temporary file with better cleanup tracking
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{uploaded_file.name}") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
            TEMP_FILES.append(tmp_path)  # Track for cleanup
        
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
                extracted_text = process_image_with_vision(tmp_path, model_choice)
            else:
                extracted_text = f"Process map file: {uploaded_file.name}\n\nVision analysis is disabled. Please enable 'Process Map Analysis' in the sidebar or manually describe the process flow."
            doc_type = "process map"
        else:
            return None, "Unsupported file format"
        
        # Generate test cases with system context
        test_cases = generate_test_cases(extracted_text, doc_type, output_format, model_choice, target_system)
        
        return test_cases, None
        
    except Exception as e:
        return None, str(e)
    
    finally:
        # Ensure cleanup happens even if there's an error
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
                if tmp_path in TEMP_FILES:
                    TEMP_FILES.remove(tmp_path)
            except:
                pass
        
        # Force garbage collection for large files
        gc.collect()

# --- Main Application ---
def main_app():
    """Main application after authentication"""
    
    current_user = get_current_user()
    user_email = current_user.get('email', 'Unknown')
    user_role = current_user.get('role', 'user')
    
    # Header with user info
    col1, col2, col3 = st.columns([3, 2, 1])
    with col1:
        # Handle missing header image gracefully
        header_path = "assets/Facto_site_header.webp"
        if os.path.exists(header_path):
            st.image(header_path)
        else:
            st.markdown("# 🧪 FACTO AI")
    with col2:
        st.write(f"👤 **Logged in as:** {user_email}")
        st.write(f"🏷️ **Role:** {user_role.replace('_', ' ').title()}")
    with col3:
        if st.button("🚪 Logout"):
            logout()

    st.title("🧪 Facto AI Test Case Generator")
    st.markdown("Upload your documents or process maps to automatically generate comprehensive test cases using AI.")
    
    # Sidebar for navigation and configuration
    st.sidebar.header("🧭 Navigation")
    
    # Navigation menu
    if has_permission('admin'):
        nav_options = ["🧪 Test Case Generator", "👥 User Management"]
    else:
        nav_options = ["🧪 Test Case Generator"]
    
    selected_nav = st.sidebar.radio("Select Section:", nav_options)
    
    if selected_nav == "👥 User Management":
        user_management_panel()
        return
    
    # Main test case generator interface
    test_case_generator_interface()

def test_case_generator_interface():
    """Test case generator interface"""
    
    # Sidebar for configuration
    st.sidebar.markdown("---")
    st.sidebar.header("⚙️ Configuration")
    
    # Show auth status
    if USING_PRODUCTION_AUTH:
        st.sidebar.success("✅ Production mode (Firestore)")
    else:
        st.sidebar.warning("⚠️ Development mode")
    
    # API Key check
    if USING_SECURE_CONFIG:
        st.sidebar.success(f"✅ API key loaded securely ({CONFIG_TYPE})")
    elif openai.api_key:
        st.sidebar.success("✅ API key loaded (development)")
    else:
        st.sidebar.error("⚠️ API key not found. Please check configuration.")
        st.stop()
    
    # Vision API toggle
    enable_vision = st.sidebar.checkbox(
        "Enable Process Map Analysis",
        value=False,
        help="Automatically uses GPT-4-Vision for process map analysis. Requires Vision API access."
    )
    
    # Model selection with smart defaults
    if enable_vision:
        # If vision is enabled, default to gpt-4o but allow manual override
        model_options = ["gpt-4o", "gpt-4", "gpt-4-vision-preview", "gpt-3.5-turbo"]
        default_index = 0  # Default to gpt-4o when vision is enabled
        help_text = "Vision analysis enabled - using GPT-4o (recommended) or select another model."
    else:
        # Standard options when vision is disabled
        model_options = ["gpt-3.5-turbo", "gpt-4o", "gpt-4"]
        default_index = 0  # Default to gpt-3.5-turbo when vision is disabled
        help_text = "Choose the AI model. GPT-3.5 is fastest and most reliable."
    
    model_choice = st.sidebar.selectbox(
        "AI Model",
        model_options,
        index=default_index,
        help=help_text
    )
    
    # Show info about vision capability
    if enable_vision and model_choice not in ["gpt-4", "gpt-4o", "gpt-4-vision-preview"]:
        st.sidebar.warning("⚠️ Selected model may not support vision analysis. Consider GPT-4o for best results.")
    
    # Target system selection
    st.sidebar.markdown("---")
    st.sidebar.subheader("🎯 Target System")
    
    target_system = st.sidebar.selectbox(
        "Select System",
        ["General", "Oracle", "SAP", "Salesforce", "MuleSoft"],
        help="Select the target system for more specific test cases"
    )
    
    if target_system != "General":
        st.sidebar.info(f"✅ Generating {target_system}-specific test cases")
    
    # Output format selection
    output_format = st.sidebar.selectbox(
        "Output Format",
        ["markdown", "csv", "json", "excel"],
        help="Choose how you want the test cases formatted"
    )
    
    # Usage statistics for current user
    current_user = get_current_user()
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Your Usage")
    st.sidebar.info(f"Login Count: {current_user.get('login_count', 0)}")
    if current_user.get('last_login'):
        try:
            st.sidebar.info(f"Last Login: {current_user['last_login'].strftime('%Y-%m-%d %H:%M')}")
        except:
            st.sidebar.info("Last Login: Available")
    
    # Storage management section
    st.sidebar.markdown("---")
    st.sidebar.subheader("🧹 Storage Management")
    
    # Show temp file count
    temp_file_count = len([f for f in TEMP_FILES if os.path.exists(f)])
    if temp_file_count > 0:
        st.sidebar.warning(f"⚠️ {temp_file_count} temp files in memory")
    
    # Manual cleanup button
    if st.sidebar.button("🗑️ Clear Temp Files"):
        cleanup_temp_files()
        st.sidebar.success("✅ Temp files cleared!")
        st.rerun()
    
    # Clear Streamlit cache
    if st.sidebar.button("🔄 Clear Cache"):
        st.cache_data.clear()
        st.sidebar.success("✅ Cache cleared!")
    
    st.sidebar.markdown("---")
    
    # File upload section
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
                
                test_cases, error = process_uploaded_file(uploaded_file, output_format, model_choice, enable_vision, target_system)
                
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

# --- Main Application Logic ---
def main():
    """Main application entry point"""
    
    # Initialize super admin on first run
    if 'super_admin_initialized' not in st.session_state:
        init_super_admin()
        st.session_state.super_admin_initialized = True
    
    # Check authentication
    if not check_authentication():
        login_form()
    else:
        main_app()

if __name__ == "__main__":
    main()