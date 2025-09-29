import streamlit as st
import os
from google.cloud import secretmanager
from google.auth.exceptions import DefaultCredentialsError

def get_openai_api_key():
    """
    Get OpenAI API key from multiple sources in order of preference:
    1. Google Secret Manager (production)
    2. Environment variable (development)
    3. Streamlit secrets (alternative)
    """
    
    # Try Google Secret Manager first (production)
    try:
        client = secretmanager.SecretManagerServiceClient()
        project_id = os.getenv('GOOGLE_CLOUD_PROJECT', 'facto-ai-project')
        
        if project_id:
            secret_name = f"projects/{project_id}/secrets/openai-api-key/versions/latest"
            response = client.access_secret_version(request={"name": secret_name})
            return response.payload.data.decode("UTF-8")
    except (DefaultCredentialsError, Exception) as e:
        # Log the error for debugging in development
        if os.getenv('ENVIRONMENT') == 'development':
            st.sidebar.info(f"Secret Manager not available: {str(e)}")
    
    # Try Streamlit secrets (good for Streamlit Cloud)
    try:
        return st.secrets["OPENAI_API_KEY"]
    except (KeyError, FileNotFoundError):
        pass
    
    # Fall back to environment variable (development only)
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return api_key
    
    # No key found
    return None

def setup_openai():
    """Initialize OpenAI with secure key retrieval"""
    import openai
    
    api_key = get_openai_api_key()
    if not api_key:
        st.error("🚨 OpenAI API key not found! Please configure it properly.")
        st.markdown("""
        **For production deployment (facto-ai.facto.com.au):**
        1. Store your API key in Google Secret Manager
        2. Set secret name: `openai-api-key`
        3. Grant Secret Manager access to Cloud Run service
        
        **For local development:**
        1. Use .env file with OPENAI_API_KEY
        2. Or use Streamlit secrets in .streamlit/secrets.toml
        """)
        st.stop()
    
    # Clean the API key - remove any extra whitespace or newlines
    api_key = api_key.strip()
    
    # Validate API key format
    if not api_key.startswith('sk-'):
        st.error("🚨 Invalid OpenAI API key format. API key should start with 'sk-'")
        st.stop()
    
    openai.api_key = api_key
    return True