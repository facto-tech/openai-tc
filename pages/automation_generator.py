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

def extract_code_from_file(uploaded_file) -> tuple:
    """Extract code content from uploaded JS/TS/Python reference files"""
    try:
        # Read file content as text
        content = uploaded_file.getvalue().decode('utf-8')
        file_name = uploaded_file.name
        file_ext = file_name.split('.')[-1].lower()
        
        # Identify file type
        file_type_map = {
            'js': 'JavaScript',
            'ts': 'TypeScript',
            'py': 'Python'
        }
        
        file_type = file_type_map.get(file_ext, 'Unknown')
        
        return {
            'content': content,
            'filename': file_name,
            'file_type': file_type,
            'extension': file_ext
        }, None
        
    except UnicodeDecodeError:
        return None, f"Unable to read {uploaded_file.name}. File might be binary or use unsupported encoding."
    except Exception as e:
        return None, f"Error reading file {uploaded_file.name}: {str(e)}"

def analyze_reference_code(reference_files: list) -> dict:
    """Analyze reference code files and extract key patterns"""
    analysis = {
        'has_pom': False,
        'classes': [],
        'methods': [],
        'locators': [],
        'imports': [],
        'patterns': []
    }
    
    all_content = ""
    
    for ref_file in reference_files:
        content = ref_file['content']
        all_content += f"\n\n--- {ref_file['filename']} ---\n{content}"
        
        # Detect Page Object Model patterns
        if 'class' in content.lower() and ('page' in content.lower() or 'pom' in content.lower()):
            analysis['has_pom'] = True
        
        # Extract class names (simplified)
        import re
        
        # Python/JS/TS class patterns
        class_pattern = r'class\s+(\w+)'
        classes = re.findall(class_pattern, content)
        analysis['classes'].extend(classes)
        
        # Method/function patterns
        method_patterns = [
            r'def\s+(\w+)',  # Python
            r'async\s+(\w+)',  # JS/TS async
            r'function\s+(\w+)',  # JS function
            r'(\w+)\s*\([^)]*\)\s*{',  # JS/TS method
        ]
        
        for pattern in method_patterns:
            methods = re.findall(pattern, content)
            analysis['methods'].extend(methods)
        
        # Common locator patterns
        locator_patterns = [
            r'data-testid["\s]*[:=]["\s]*([^"]+)',
            r'#(\w+)',  # ID selectors
            r'\.(\w+)',  # Class selectors
        ]
        
        for pattern in locator_patterns:
            locators = re.findall(pattern, content)
            analysis['locators'].extend(locators)
    
    return analysis, all_content

def get_automation_system_prompt(
    language: str, 
    framework: str, 
    selector_strategy: str, 
    page_object: bool,
    reference_context: str = None
) -> str:
    """Generate optimized system prompt for automation code generation"""
    
    base_prompt = f"""You are an expert test automation engineer with deep expertise in {language} and {framework}.

Your mission: Generate production-ready, maintainable test automation code that follows industry best practices.

**TECHNICAL SPECIFICATIONS:**
━━━━━━━━━━━━━━━━━━━━━━━━━━
• Language: {language}
• Framework: {framework}
• Selector Strategy: {selector_strategy}
• Architecture: {'Page Object Model (POM)' if page_object else 'Direct test implementation'}

**CORE REQUIREMENTS:**
━━━━━━━━━━━━━━━━━━━━━━━━━━
1. CODE COMPLETENESS
   - Include ALL necessary imports and dependencies
   - Provide complete setup/teardown with proper cleanup
   - Make code immediately runnable (copy-paste ready)

2. RELIABILITY & RESILIENCE
   - Implement smart waiting strategies (avoid hard sleeps)
   - Add comprehensive error handling with meaningful messages
   - Include retry logic for flaky operations
   - Handle edge cases and race conditions

3. MAINTAINABILITY
   - Use {selector_strategy} consistently for element selection
   - Write self-documenting code with clear naming
   - Add comments only for complex logic
   - Follow {framework} conventions and idioms

4. ASSERTIONS & VALIDATION
   - Add meaningful, descriptive assertions
   - Validate both positive and negative scenarios
   - Check element states (visible, enabled, text content)
   - Include soft assertions where appropriate

5. DEBUGGING & OBSERVABILITY
   - Add strategic logging at key checkpoints
   - Include screenshots on failure
   - Provide clear failure messages
   - Add test metadata (tags, descriptions)
"""

    # Framework-specific optimizations
    if framework == "Playwright":
        base_prompt += """
**PLAYWRIGHT BEST PRACTICES:**
━━━━━━━━━━━━━━━━━━━━━━━━━━
• Use auto-waiting features (page.locator() waits automatically)
• Implement page fixtures for reusability
• Leverage built-in assertions (expect(locator).toBeVisible())
• Use page.waitForLoadState() for navigation
• Enable tracing for debugging (context.tracing.start())
• Utilize parallel execution capabilities
• Take screenshots: await page.screenshot()
• Use strict mode for selectors

Example Pattern:
```typescript
await expect(page.locator('[data-testid="submit"]')).toBeVisible();
await page.locator('[data-testid="submit"]').click();
```
"""
    elif framework == "Selenium":
        base_prompt += """
**SELENIUM BEST PRACTICES:**
━━━━━━━━━━━━━━━━━━━━━━━━━━
• Use WebDriverWait with ExpectedConditions
• Implement proper driver lifecycle management
• Add explicit waits over implicit waits
• Use By locators appropriately
• Handle stale elements gracefully
• Implement WebDriver singleton pattern
• Take screenshots on failure
• Clear cookies/cache between tests

Example Pattern:
```python
wait = WebDriverWait(driver, 10)
element = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="submit"]')))
element.click()
```
"""
    elif framework == "Cypress":
        base_prompt += """
**CYPRESS BEST PRACTICES:**
━━━━━━━━━━━━━━━━━━━━━━━━━━
• Use cy.intercept() for API mocking
• Leverage automatic waiting and retry
• Use custom commands for reusability
• Implement proper test isolation
• Use data-* attributes for selectors
• Add aliases for commonly used elements
• Use .should() for assertions

Example Pattern:
```javascript
cy.get('[data-testid="submit"]')
  .should('be.visible')
  .and('be.enabled')
  .click();
```
"""
    elif framework == "Pytest":
        base_prompt += """
**PYTEST BEST PRACTICES:**
━━━━━━━━━━━━━━━━━━━━━━━━━━
• Use fixtures for setup/teardown
• Implement parametrize for data-driven tests
• Add markers for test categorization (@pytest.mark.smoke)
• Use conftest.py for shared fixtures
• Leverage pytest-html for reporting
• Add docstrings for test documentation
• Use assert with descriptive messages

Example Pattern:
```python
@pytest.fixture
def browser():
    # setup
    yield driver
    # teardown
```
"""

    if page_object:
        base_prompt += """
**PAGE OBJECT MODEL (POM) ARCHITECTURE:**
━━━━━━━━━━━━━━━━━━━━━━━━━━
• Separate Concerns: One class per page/component
• Encapsulate Locators: Store all selectors in page classes
• Action Methods: Create methods for user interactions
• Return New Pages: Methods that navigate should return page objects
• Keep Tests Clean: Tests should read like user stories
• Reusability: Make page objects reusable across tests

Structure:
```
pages/
  ├── base_page.py (common methods)
  ├── login_page.py
  └── dashboard_page.py
tests/
  └── test_login.py (uses page objects)
```
"""

    base_prompt += f"""
**SELECTOR STRATEGY: {selector_strategy}**
━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    if selector_strategy == "data-testid":
        base_prompt += """• PREFER: [data-testid="element-name"] attributes
• Use descriptive, semantic names
• Suggest data-testid values if not provided in UI
• Format: [data-testid="feature-action-element"]
  Examples: [data-testid="login-submit-button"]
            [data-testid="user-profile-dropdown"]
"""
    elif selector_strategy == "CSS":
        base_prompt += """• Use CSS selectors with appropriate specificity
• Prefer: ID > Class > Tag
• Avoid overly complex selectors
• Use child combinators (>) over descendant
• Leverage attribute selectors: [type="submit"]
"""
    elif selector_strategy == "XPath":
        base_prompt += """• Use relative XPath over absolute
• Leverage text content: //button[text()='Submit']
• Use contains() for partial matches
• Avoid brittle paths with multiple levels
• Consider axes: following-sibling, parent, ancestor
"""

    # Add reference code context if provided
    if reference_context:
        base_prompt += f"""
**REFERENCE CODE PROVIDED:**
━━━━━━━━━━━━━━━━━━━━━━━━━━
The user has provided reference code files (POM classes, utilities, etc.) that should inform your implementation.
Follow the patterns, naming conventions, and structure from these reference files.

{reference_context}

IMPORTANT: Use the patterns, class structures, and coding style from the reference code above.
"""
    
    return base_prompt

def get_automation_user_prompt(
    test_description: str, 
    context_text: str = "", 
    framework: str = "Playwright",
    reference_summary: dict = None
) -> str:
    """Generate optimized user prompt for automation code generation"""
    
    prompt = f"""**TEST AUTOMATION REQUEST**

**Scenario to Automate:**
{test_description}
"""
    
    if reference_summary and reference_summary.get('has_pom'):
        prompt += f"""
**Reference Code Analysis:**
- Page Object Model detected: Yes
- Classes found: {', '.join(reference_summary.get('classes', [])[:5])}
- Key methods: {', '.join(reference_summary.get('methods', [])[:10])}

Please follow the Page Object Model structure from the reference code.
"""
    
    if context_text:
        prompt += f"""
**Additional Requirements:**
{context_text}
"""
    
    prompt += """
**DELIVERABLES:**
━━━━━━━━━━━━━━━━━━━━━━━━━━
Generate complete, production-ready code with:

1. ✅ All imports and setup code
2. ✅ Page Object classes (if using POM)
3. ✅ Test class/function with proper structure
4. ✅ Setup and teardown methods
5. ✅ Wait strategies for all interactions
6. ✅ Comprehensive assertions with messages
7. ✅ Error handling and logging
8. ✅ Comments for complex logic only
9. ✅ Code formatting following best practices

**CODE QUALITY CHECKLIST:**
- [ ] No hardcoded waits (sleep/Thread.sleep)
- [ ] All interactions have explicit waits
- [ ] Assertions include descriptive messages
- [ ] Error handling for potential failures
- [ ] Code is immediately runnable
- [ ] Follows framework conventions
- [ ] Uses recommended patterns

Please provide the complete implementation now.
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
    reference_files: list = None,
    model: str = "gpt-4o"
) -> tuple:
    """Generate automation code using OpenAI API with reference code support"""
    
    try:
        # Process reference files if provided
        reference_context = None
        reference_summary = None
        
        if reference_files:
            reference_summary, reference_context = analyze_reference_code(reference_files)
        
        # Build prompts with reference context
        system_prompt = get_automation_system_prompt(
            language, 
            framework, 
            selector_strategy, 
            page_object,
            reference_context
        )
        
        user_prompt = get_automation_user_prompt(
            test_description, 
            context_text, 
            framework,
            reference_summary
        )
        
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
        
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=4000
        )
        
        code = response['choices'][0]['message']['content']
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

def main_app():
    """Main application interface"""
    
    st.title("🤖 Facto AI - Automation Code Generator")
    st.markdown("Generate production-ready test automation code from requirements, screenshots, or descriptions")
    
    # Sidebar configuration
    st.sidebar.header("⚙️ Configuration")
    
    # User info
    user_data = get_current_user()
    if user_data:
        st.sidebar.success(f"👤 {user_data.get('email', 'User')}")
        st.sidebar.caption(f"Role: {user_data.get('role', 'user').replace('_', ' ').title()}")
        
        if st.sidebar.button("🚪 Logout"):
            logout()
    
    # Model selection
    model_options = {
        "GPT-4o (Recommended)": "gpt-4o",
        "GPT-4o-mini (Faster)": "gpt-4o-mini",
        "GPT-4 Turbo": "gpt-4-turbo-preview"
    }
    
    model_display_choice = st.sidebar.selectbox(
        "AI Model",
        options=list(model_options.keys()),
        index=0,
        help="GPT-4o is recommended for best code quality"
    )
    model_choice = model_options[model_display_choice]
    
    # Language selection
    language = st.sidebar.selectbox(
        "Programming Language",
        ["Python", "JavaScript", "TypeScript"],
        help="Select your preferred automation language"
    )
    
    # Framework selection based on language
    framework_options = {
        "Python": ["Playwright", "Selenium", "Pytest", "Robot Framework"],
        "JavaScript": ["Playwright", "Cypress", "WebDriverIO", "TestCafe"],
        "TypeScript": ["Playwright", "Cypress", "WebDriverIO", "TestCafe"]
    }
    
    framework = st.sidebar.selectbox(
        "Testing Framework",
        framework_options[language],
        help="Select your testing framework"
    )
    
    # Selector strategy
    selector_strategy = st.sidebar.selectbox(
        "Selector Strategy",
        ["data-testid", "CSS", "XPath"],
        help="Preferred method for locating elements"
    )
    
    # Page Object Model
    page_object = st.sidebar.checkbox(
        "Use Page Object Model (POM)",
        value=True,
        help="Generate code using Page Object Model pattern for better maintainability"
    )
    
    st.sidebar.markdown("---")
    
    # Reference Files Upload Section (NEW FEATURE)
    st.sidebar.header("📎 Reference Files")
    st.sidebar.markdown("Upload existing POM files or utilities as reference")
    
    reference_files_uploaded = st.sidebar.file_uploader(
        "Upload Reference Code (Optional)",
        type=['js', 'ts', 'py'],
        accept_multiple_files=True,
        help="Upload your Page Object Model files, utility classes, or helper functions to use as reference",
        key="reference_files"
    )
    
    reference_files_data = []
    if reference_files_uploaded:
        st.sidebar.success(f"✅ {len(reference_files_uploaded)} reference file(s) uploaded")
        
        with st.sidebar.expander("📋 Reference Files Details"):
            for ref_file in reference_files_uploaded:
                file_data, error = extract_code_from_file(ref_file)
                if error:
                    st.error(f"❌ {error}")
                else:
                    reference_files_data.append(file_data)
                    st.write(f"📄 **{file_data['filename']}** ({file_data['file_type']})")
                    st.caption(f"{len(file_data['content'])} characters")
    
    st.sidebar.markdown("---")
    
    # Clean temp files button
    if st.sidebar.button("🗑️ Clear Temp Files"):
        cleanup_temp_files()
        st.sidebar.success("✅ Temp files cleared!")
        st.rerun()
    
    # Main content area with tabs
    tab1, tab2, tab3 = st.tabs([
        "📝 Text Description", 
        "🖼️ Screenshot Upload", 
        "📄 Document + Screenshot"
    ])
    
    with tab1:
        st.subheader("Describe Your Test Scenario")
        
        test_description = st.text_area(
            "Test Scenario Description",
            placeholder="""Example:
Test the login functionality:
1. Navigate to login page
2. Enter valid credentials (username: testuser, password: Test123!)
3. Click login button
4. Verify user is redirected to dashboard
5. Check that welcome message is displayed
6. Test logout functionality""",
            height=200,
            help="Describe what you want to test in detail",
            key="text_desc"
        )
        
        additional_context = st.text_area(
            "Additional Context/Requirements (Optional)",
            placeholder="""Examples:
• URL: https://app.example.com
• Test data: Use credentials from config file
• Handle 2FA flow
• Add screenshot on failure
• Test for mobile viewport""",
            height=150,
            key="text_context"
        )
        
        if test_description and st.button("🚀 Generate Code", key="gen_text", type="primary"):
            with st.spinner("Generating automation code..."):
                code, error = generate_automation_code(
                    test_description=test_description,
                    language=language,
                    framework=framework,
                    selector_strategy=selector_strategy,
                    page_object=page_object,
                    context_text=additional_context,
                    reference_files=reference_files_data if reference_files_data else None,
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
                            reference_files=reference_files_data if reference_files_data else None,
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
                        reference_files=reference_files_data if reference_files_data else None,
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