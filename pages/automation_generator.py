import streamlit as st
import openai
import fitz
from docx import Document
import os
from dotenv import load_dotenv
import base64
import tempfile
import io
import json
from datetime import datetime
import atexit
import platform
import subprocess

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
    page_title="Facto AI Automation Generator",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize OpenAI securely
if USING_SECURE_CONFIG:
    setup_openai()
else:
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
    from google.cloud import firestore
    firestore.Client(project=os.getenv('GOOGLE_CLOUD_PROJECT'))
    
    from user_management import (
        check_authentication, login_form, get_current_user, has_permission,
        user_management_panel, logout, init_super_admin
    )
    USING_PRODUCTION_AUTH = True
    
except Exception as e:
    # Development authentication
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
        import docx2txt
        return docx2txt.process(filepath)
    except ImportError:
        try:
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
                        os.remove(txt_file)
                        return content
                
                raise Exception("LibreOffice conversion failed")
                
            except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
                raise Exception(
                    "Could not extract text from .doc file. "
                    "Please install docx2txt (pip install docx2txt) "
                    "or convert the file to .docx format first."
                )

def encode_image_to_base64(filepath) -> str:
    with open(filepath, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_automation_system_prompt(language: str, framework: str, selector_strategy: str, page_object: bool) -> str:
    """Generate system prompt for automation code generation"""
    
    base_prompt = f"""You are an expert test automation engineer specializing in {language} with {framework}.

Your task is to generate production-ready test automation code following these specifications:

**Language & Framework:** {language} with {framework}
**Selector Strategy:** {selector_strategy}
**Architecture:** {'Page Object Model (POM)' if page_object else 'Direct test implementation'}

**Code Requirements:**
1. Generate complete, runnable code with all necessary imports
2. Include proper setup/teardown methods
3. Use {selector_strategy} for element selectors
4. Add meaningful assertions and validation
5. Include error handling and wait strategies
6. Add clear comments explaining test logic
7. Follow best practices for {framework}
8. Make code maintainable and scalable

"""

    # Add framework-specific guidelines
    if framework == "Playwright":
        base_prompt += """
**Playwright-Specific Requirements:**
- Use async/await patterns
- Implement proper page fixtures
- Add auto-waiting strategies
- Include screenshot on failure
- Use page.locator() for element selection
- Add trace collection for debugging
"""
    elif framework == "Selenium":
        base_prompt += """
**Selenium-Specific Requirements:**
- Use WebDriverWait for explicit waits
- Implement proper driver management
- Add implicit/explicit wait strategies
- Include try-except for stability
- Use appropriate By locators
"""
    elif framework == "Pytest":
        base_prompt += """
**Pytest-Specific Requirements:**
- Use pytest fixtures for setup/teardown
- Add parametrize for data-driven tests
- Include proper assertions with messages
- Use conftest.py patterns
- Add markers for test categorization
"""
    elif framework == "Robot Framework":
        base_prompt += """
**Robot Framework-Specific Requirements:**
- Use keyword-driven approach
- Create reusable keywords
- Include proper test setup/teardown
- Add clear test documentation
- Use proper variable conventions
"""
    
    if page_object:
        base_prompt += """
**Page Object Model Requirements:**
- Create separate page classes
- Encapsulate locators in page objects
- Define action methods in page classes
- Keep tests clean and readable
- Make pages reusable
"""
    
    base_prompt += f"""
**Selector Strategy ({selector_strategy}):**
"""
    
    if selector_strategy == "data-testid":
        base_prompt += """- Prefer data-testid attributes for stable selectors
- Use format: [data-testid="element-name"]
- Generate suggested data-testid values
"""
    elif selector_strategy == "CSS":
        base_prompt += """- Use CSS selectors with proper specificity
- Prefer class and id selectors
- Avoid overly complex selectors
"""
    elif selector_strategy == "XPath":
        base_prompt += """- Use robust XPath expressions
- Prefer relative XPath over absolute
- Include text-based locators when appropriate
"""
    
    return base_prompt

def get_automation_user_prompt(test_description: str, context_text: str = "", framework: str = "Playwright") -> str:
    """Generate user prompt for automation code generation"""
    
    prompt = f"""Generate test automation code for the following scenario:

{test_description}
"""
    
    if context_text:
        prompt += f"""

**Additional Context/Requirements:**
{context_text}
"""
    
    prompt += f"""

**Output Requirements:**
1. Generate complete, production-ready code
2. Include all necessary imports and setup
3. Add clear comments and documentation
4. Implement proper wait strategies
5. Include meaningful test assertions
6. Add error handling
7. Make code copy-paste ready

Please provide the complete code implementation.
"""
    
    return prompt

def generate_automation_code(
    test_description: str,
    language: str,
    framework: str,
    selector_strategy: str,
    page_object: bool,
    context_text: str = "",
    image_base64: str = None,
    model: str = "gpt-4o"
) -> tuple:
    """Generate automation code using OpenAI API"""
    
    try:
        system_prompt = get_automation_system_prompt(language, framework, selector_strategy, page_object)
        user_prompt = get_automation_user_prompt(test_description, context_text, framework)
        
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Add user message with optional image
        if image_base64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}",
                            "detail": "high"
                        }
                    }
                ]
            })
        else:
            messages.append({
                "role": "user",
                "content": user_prompt
            })
        
        response = openai.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=4000
        )
        
        code = response.choices[0].message.content
        return code, None
        
    except Exception as e:
        return None, str(e)

def process_uploaded_image(uploaded_file) -> tuple:
    """Process uploaded image file"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
            TEMP_FILES.append(tmp_path)
        
        image_base64 = encode_image_to_base64(tmp_path)
        return image_base64, None
        
    except Exception as e:
        return None, str(e)

def process_uploaded_document(uploaded_file) -> tuple:
    """Process uploaded document file"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
            TEMP_FILES.append(tmp_path)
        
        file_ext = uploaded_file.name.lower().split('.')[-1]
        
        if file_ext == 'pdf':
            text = extract_text_from_pdf(tmp_path)
        elif file_ext == 'docx':
            text = extract_text_from_docx(tmp_path)
        elif file_ext == 'doc':
            text = extract_text_from_doc(tmp_path)
        else:
            return None, "Unsupported document format"
        
        return text, None
        
    except Exception as e:
        return None, str(e)

def get_file_extension(language: str) -> str:
    """Get file extension for language"""
    extensions = {
        "JavaScript": "js",
        "TypeScript": "ts",
        "Python": "py"
    }
    return extensions.get(language, "txt")

def get_language_for_code_block(language: str) -> str:
    """Get language identifier for code highlighting"""
    mapping = {
        "JavaScript": "javascript",
        "TypeScript": "typescript",
        "Python": "python"
    }
    return mapping.get(language, "text")

# --- Main Application ---
def main_app():
    """Main automation generator interface"""
    
    # Sidebar
    st.sidebar.title("🤖 Automation Generator")
    
    user_data = get_current_user()
    if user_data:
        st.sidebar.write(f"👤 **{user_data.get('email', 'User')}**")
        st.sidebar.write(f"🎭 Role: **{user_data.get('role', 'user').title()}**")
    
    st.sidebar.markdown("---")
    
    # Navigation
    st.sidebar.subheader("📱 Navigation")
    if st.sidebar.button("🧪 Test Case Generator"):
        st.switch_page("app.py")
    
    if has_permission('admin'):
        if st.sidebar.button("👥 User Management"):
            st.session_state.show_user_management = True
            st.rerun()
    
    if st.sidebar.button("🚪 Logout"):
        logout()
    
    st.sidebar.markdown("---")
    
    # Configuration Section
    st.sidebar.subheader("⚙️ Configuration")
    
    # Language selection
    language = st.sidebar.selectbox(
        "Programming Language",
        ["JavaScript", "TypeScript", "Python"],
        help="Select the programming language for generated code"
    )
    
    # Framework selection based on language
    framework_options = {
        "JavaScript": ["Playwright", "Selenium WebDriver", "Cypress", "Puppeteer"],
        "TypeScript": ["Playwright", "Selenium WebDriver", "Cypress", "Puppeteer"],
        "Python": ["Playwright", "Selenium WebDriver", "Pytest", "Robot Framework"]
    }
    
    framework = st.sidebar.selectbox(
        "Testing Framework",
        framework_options[language],
        help="Select the testing framework"
    )
    
    # Selector strategy
    selector_strategy = st.sidebar.selectbox(
        "Selector Strategy",
        ["data-testid", "CSS", "XPath", "ID/Class"],
        help="Preferred method for element selection"
    )
    
    # Page Object Model
    page_object = st.sidebar.checkbox(
        "Use Page Object Model",
        value=True,
        help="Generate code using Page Object Model pattern"
    )
    
    # Model selection
    model_choice = st.sidebar.selectbox(
        "AI Model",
        ["gpt-4o", "gpt-4o-mini"],
        help="Select OpenAI model (gpt-4o recommended for complex scenarios)"
    )
    
    st.sidebar.markdown("---")
    
    # Clear temp files button
    if st.sidebar.button("🗑️ Clear Temp Files"):
        cleanup_temp_files()
        st.sidebar.success("✅ Temp files cleared!")
        st.rerun()
    
    # Main content
    st.title("🤖 Test Automation Code Generator")
    st.markdown("Generate production-ready test automation code from descriptions or UI screenshots")
    
    # Show user management panel if requested
    if st.session_state.get('show_user_management', False):
        user_management_panel()
        if st.button("← Back to Automation Generator"):
            st.session_state.show_user_management = False
            st.rerun()
        return
    
    # Input method tabs
    tab1, tab2, tab3 = st.tabs(["📝 Text Description", "🖼️ UI Screenshot", "📄 Document + Screenshot"])
    
    with tab1:
        st.subheader("Describe Your Test Scenario")
        
        test_description = st.text_area(
            "Test Scenario Description",
            placeholder="""Example:
Test user login functionality:
1. Navigate to login page at /login
2. Enter valid username and password
3. Click login button
4. Verify user is redirected to dashboard
5. Verify welcome message is displayed""",
            height=200,
            help="Describe the test scenario in detail"
        )
        
        additional_context = st.text_area(
            "Additional Requirements (Optional)",
            placeholder="""Examples:
• Include test data setup
• Add negative test cases
• Test for specific error messages
• Include accessibility checks
• Add performance assertions""",
            height=150
        )
        
        if st.button("🚀 Generate Automation Code", key="gen_text", type="primary"):
            if not test_description:
                st.error("❌ Please provide a test scenario description")
            else:
                with st.spinner("Generating automation code..."):
                    code, error = generate_automation_code(
                        test_description=test_description,
                        language=language,
                        framework=framework,
                        selector_strategy=selector_strategy,
                        page_object=page_object,
                        context_text=additional_context,
                        model=model_choice
                    )
                    
                    if error:
                        st.error(f"❌ Error: {error}")
                    else:
                        display_generated_code(code, language, framework)
    
    with tab2:
        st.subheader("Upload UI Screenshot")
        
        uploaded_image = st.file_uploader(
            "Upload Screenshot",
            type=['png', 'jpg', 'jpeg', 'gif', 'webp'],
            help="Upload a screenshot of the UI to generate tests for"
        )
        
        if uploaded_image:
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.image(uploaded_image, caption="Uploaded Screenshot", use_container_width=True)
            
            with col2:
                test_description = st.text_area(
                    "Test Scenario Description",
                    placeholder="""Describe what you want to test in this UI:
• Login form validation
• Form submission workflow
• Button interactions
• Navigation flows
• etc.""",
                    height=200,
                    key="img_desc"
                )
                
                additional_context = st.text_area(
                    "Additional Requirements (Optional)",
                    placeholder="Any specific requirements or edge cases",
                    height=100,
                    key="img_context"
                )
        
        if uploaded_image and st.button("🚀 Generate from Screenshot", key="gen_img", type="primary"):
            if not test_description:
                st.error("❌ Please describe what you want to test")
            else:
                with st.spinner("Processing screenshot and generating code..."):
                    image_base64, img_error = process_uploaded_image(uploaded_image)
                    
                    if img_error:
                        st.error(f"❌ Error processing image: {img_error}")
                    else:
                        code, error = generate_automation_code(
                            test_description=test_description,
                            language=language,
                            framework=framework,
                            selector_strategy=selector_strategy,
                            page_object=page_object,
                            context_text=additional_context,
                            image_base64=image_base64,
                            model=model_choice
                        )
                        
                        if error:
                            st.error(f"❌ Error: {error}")
                        else:
                            display_generated_code(code, language, framework)
    
    with tab3:
        st.subheader("Upload Requirements Document + UI Screenshot")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            uploaded_doc = st.file_uploader(
                "Upload Requirements Document",
                type=['pdf', 'doc', 'docx'],
                help="Upload requirements or specification document"
            )
        
        with col2:
            uploaded_image_combo = st.file_uploader(
                "Upload UI Screenshot",
                type=['png', 'jpg', 'jpeg', 'gif', 'webp'],
                help="Upload a screenshot of the UI",
                key="combo_img"
            )
        
        if uploaded_doc or uploaded_image_combo:
            test_description = st.text_area(
                "Test Scenario Description",
                placeholder="Describe the specific test scenario you want to generate",
                height=150,
                key="combo_desc"
            )
            
            additional_context = st.text_area(
                "Additional Requirements (Optional)",
                placeholder="Any specific requirements or focus areas",
                height=100,
                key="combo_context"
            )
        
        if (uploaded_doc or uploaded_image_combo) and st.button("🚀 Generate from Documents", key="gen_combo", type="primary"):
            if not test_description:
                st.error("❌ Please describe what you want to test")
            else:
                with st.spinner("Processing documents and generating code..."):
                    doc_text = ""
                    image_base64 = None
                    
                    # Process document if provided
                    if uploaded_doc:
                        doc_text, doc_error = process_uploaded_document(uploaded_doc)
                        if doc_error:
                            st.error(f"❌ Error processing document: {doc_error}")
                            doc_text = ""
                    
                    # Process image if provided
                    if uploaded_image_combo:
                        image_base64, img_error = process_uploaded_image(uploaded_image_combo)
                        if img_error:
                            st.error(f"❌ Error processing image: {img_error}")
                            image_base64 = None
                    
                    # Combine context
                    combined_context = additional_context
                    if doc_text:
                        combined_context = f"""**Requirements Document Content:**
{doc_text[:3000]}

**Additional Context:**
{additional_context}"""
                    
                    code, error = generate_automation_code(
                        test_description=test_description,
                        language=language,
                        framework=framework,
                        selector_strategy=selector_strategy,
                        page_object=page_object,
                        context_text=combined_context,
                        image_base64=image_base64,
                        model=model_choice
                    )
                    
                    if error:
                        st.error(f"❌ Error: {error}")
                    else:
                        display_generated_code(code, language, framework)

def display_generated_code(code: str, language: str, framework: str):
    """Display generated automation code with download option"""
    
    st.success("✅ Automation code generated successfully!")
    
    # Show configuration summary
    with st.expander("⚙️ Code Configuration"):
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Language:** {language}")
            st.write(f"**Framework:** {framework}")
        with col2:
            st.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Display code
    st.subheader("Generated Code")
    
    # Clean code (remove markdown code blocks if present)
    clean_code = code
    if "```" in code:
        # Extract code from markdown blocks
        import re
        code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', code, re.DOTALL)
        if code_blocks:
            clean_code = '\n\n'.join(code_blocks)
    
    # Display with syntax highlighting
    st.code(clean_code, language=get_language_for_code_block(language))
    
    # Download button
    file_extension = get_file_extension(language)
    filename = f"test_automation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{file_extension}"
    
    st.download_button(
        label=f"📥 Download {language} Code",
        data=clean_code,
        file_name=filename,
        mime="text/plain"
    )
    
    # Copy to clipboard helper
    st.info("💡 Tip: Click the copy button in the top-right of the code block to copy to clipboard")

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