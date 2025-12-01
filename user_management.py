import streamlit as st
import json
import hashlib
import secrets
import time
from datetime import datetime, timedelta
from google.cloud import firestore
from google.auth.exceptions import DefaultCredentialsError
import os

# Initialize Firestore client
def get_firestore_client():
    try:
        return firestore.Client(project=os.getenv('GOOGLE_CLOUD_PROJECT', 'facto-ai-project'))
    except DefaultCredentialsError:
        st.error("Firestore not available in development mode")
        return None

# User roles
USER_ROLES = {
    'super_admin': 'Super Administrator',
    'admin': 'Administrator', 
    'user': 'Standard User'
}

class UserManager:
    def __init__(self):
        self.db = get_firestore_client()
        self.collection_name = 'facto_users'
        
    def hash_password(self, password: str) -> str:
        """Hash password with salt"""
        salt = secrets.token_hex(32)
        pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
        return f"{salt}${pwdhash.hex()}"
    
    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against hash"""
        try:
            salt, pwdhash = hashed.split('$')
            return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex() == pwdhash
        except:
            return False
    
    def create_user(self, email: str, password: str, role: str = 'user', created_by: str = None) -> bool:
        """Create a new user"""
        if not self.db:
            return False
            
        try:
            # Check if user already exists
            if self.get_user(email):
                return False
                
            user_data = {
                'email': email.lower(),
                'password_hash': self.hash_password(password),
                'role': role,
                'created_at': datetime.utcnow(),
                'created_by': created_by,
                'is_active': True,
                'last_login': None,
                'login_count': 0
            }
            
            self.db.collection(self.collection_name).document(email.lower()).set(user_data)
            return True
        except Exception as e:
            st.error(f"Error creating user: {str(e)}")
            return False
    
    def get_user(self, email: str) -> dict:
        """Get user data"""
        if not self.db:
            return None
            
        try:
            doc = self.db.collection(self.collection_name).document(email.lower()).get()
            return doc.to_dict() if doc.exists else None
        except:
            return None
    
    def authenticate_user(self, email: str, password: str) -> dict:
        """Authenticate user and return user data if valid"""
        user = self.get_user(email)
        if user and user.get('is_active', False) and self.verify_password(password, user['password_hash']):
            # Update login info
            self.update_login_info(email)
            return user
        return None
    
    def update_login_info(self, email: str):
        """Update user's last login time and count"""
        if not self.db:
            return
            
        try:
            user_ref = self.db.collection(self.collection_name).document(email.lower())
            user_ref.update({
                'last_login': datetime.utcnow(),
                'login_count': firestore.Increment(1)
            })
        except:
            pass
    
    def get_all_users(self) -> list:
        """Get all users (admin only)"""
        if not self.db:
            return []
            
        try:
            users = []
            docs = self.db.collection(self.collection_name).stream()
            for doc in docs:
                user_data = doc.to_dict()
                user_data['email'] = doc.id
                # Remove sensitive data
                user_data.pop('password_hash', None)
                users.append(user_data)
            return sorted(users, key=lambda x: x.get('created_at', datetime.min), reverse=True)
        except:
            return []
    
    def update_user_role(self, email: str, new_role: str, updated_by: str) -> bool:
        """Update user role"""
        if not self.db:
            return False
            
        try:
            user_ref = self.db.collection(self.collection_name).document(email.lower())
            user_ref.update({
                'role': new_role,
                'updated_at': datetime.utcnow(),
                'updated_by': updated_by
            })
            return True
        except:
            return False
    
    def deactivate_user(self, email: str, deactivated_by: str) -> bool:
        """Deactivate user"""
        if not self.db:
            return False
            
        try:
            user_ref = self.db.collection(self.collection_name).document(email.lower())
            user_ref.update({
                'is_active': False,
                'deactivated_at': datetime.utcnow(),
                'deactivated_by': deactivated_by
            })
            return True
        except:
            return False
    
    def reset_user_password(self, email: str, new_password: str, reset_by: str) -> bool:
        """Reset user password"""
        if not self.db:
            return False
            
        try:
            user_ref = self.db.collection(self.collection_name).document(email.lower())
            user_ref.update({
                'password_hash': self.hash_password(new_password),
                'password_reset_at': datetime.utcnow(),
                'password_reset_by': reset_by,
                'force_password_change': True  # Force user to change on next login
            })
            return True
        except:
            return False
    
    def change_own_password(self, email: str, old_password: str, new_password: str) -> bool:
        """Allow user to change their own password"""
        if not self.db:
            return False
            
        try:
            # Verify old password first
            user = self.get_user(email)
            if not user or not self.verify_password(old_password, user['password_hash']):
                return False
                
            user_ref = self.db.collection(self.collection_name).document(email.lower())
            user_ref.update({
                'password_hash': self.hash_password(new_password),
                'password_changed_at': datetime.utcnow(),
                'force_password_change': False
            })
            return True
        except:
            return False

def init_super_admin():
    """Initialize super admin if not exists"""
    user_manager = UserManager()
    
    # Debug info
    # st.write("🔧 Debug: Initializing super admin...")
    # st.write(f"🔧 Debug: Firestore client available: {user_manager.db is not None}")
    
    # Check if super admin exists
    super_admin_email = "admin@facto.com.au"  # Change this to your email
    existing_user = user_manager.get_user(super_admin_email)
    # st.write(f"🔧 Debug: Existing user check: {existing_user is not None}")
    
    if not existing_user:
        # Create super admin with default password
        default_password = "FactoAdmin2024!"  # Change this immediately after first login
        st.write(f"🔧 Debug: Attempting to create user...")
        if user_manager.create_user(super_admin_email, default_password, 'super_admin'):
            st.success(f"✅ Super admin created: {super_admin_email}")
            st.warning(f"⚠️ Default password: {default_password}")
            st.warning("🔒 Please change the password immediately after first login!")
            return True
        else:
            st.error("❌ Failed to create super admin user")
            return False
    else:
        st.info(f"✅ Super admin already exists: {super_admin_email}")
        return False

def check_authentication():
    """Check if user is authenticated"""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.user_data = None
    
    return st.session_state.authenticated

def get_current_user():
    """Get current user data"""
    return st.session_state.get('user_data', {})

def has_permission(required_role: str = 'user') -> bool:
    """Check if current user has required permission level"""
    if not check_authentication():
        return False
    
    user_role = get_current_user().get('role', 'user')
    
    role_hierarchy = {
        'user': 1,
        'admin': 2,
        'super_admin': 3
    }
    
    return role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 1)

def login_form():
    """Display login form"""
    st.title("🔐 Facto AI - User Login")
    
    # Check if user needs to change password
    if 'force_password_change' in st.session_state and st.session_state.force_password_change:
        password_change_form()
        return
    
    with st.form("login_form"):
        email = st.text_input("Email", placeholder="your.email@facto.com.au")
        password = st.text_input("Password", type="password")
        submit_button = st.form_submit_button("Login")
        
        if submit_button:
            if email and password:
                user_manager = UserManager()
                user_data = user_manager.authenticate_user(email, password)
                
                if user_data:
                    st.session_state.authenticated = True
                    st.session_state.user_data = user_data
                    
                    # Check if password change is required
                    if user_data.get('force_password_change', False):
                        st.session_state.force_password_change = True
                        st.warning("🔒 You must change your password before continuing")
                        st.rerun()
                    else:
                        st.success(f"✅ Welcome, {email}!")
                        st.rerun()
                else:
                    st.error("❌ Invalid credentials or inactive account")
            else:
                st.error("❌ Please enter both email and password")

def password_change_form():
    """Force password change form"""
    st.title("🔒 Password Change Required")
    st.warning("You must change your password before accessing the application")
    
    current_user = st.session_state.get('user_data', {})
    
    with st.form("forced_password_change"):
        new_password = st.text_input("New Password", type="password")
        confirm_password = st.text_input("Confirm New Password", type="password")
        change_button = st.form_submit_button("Change Password")
        
        if change_button:
            if new_password and confirm_password:
                if new_password != confirm_password:
                    st.error("❌ Passwords don't match")
                elif len(new_password) < 8:
                    st.error("❌ Password must be at least 8 characters long")
                else:
                    user_manager = UserManager()
                    user_ref = user_manager.db.collection(user_manager.collection_name).document(current_user['email'].lower())
                    user_ref.update({
                        'password_hash': user_manager.hash_password(new_password),
                        'password_changed_at': datetime.utcnow(),
                        'force_password_change': False
                    })
                    
                    # Update session
                    st.session_state.force_password_change = False
                    st.session_state.user_data['force_password_change'] = False
                    
                    st.success("✅ Password changed successfully!")
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("❌ Please enter and confirm your new password")

def user_management_panel():
    """Admin panel for user management"""
    if not has_permission('admin'):
        st.error("❌ Access denied. Admin privileges required.")
        return
    
    st.header("👥 User Management")
    current_user = get_current_user()
    user_manager = UserManager()
    
    # Tabs for different admin functions
    tab1, tab2, tab3, tab4 = st.tabs(["👤 Add User", "📋 Manage Users", "🔑 Password Management", "📊 User Statistics"])
    
    with tab1:
        st.subheader("Add New User")
        with st.form("add_user_form"):
            new_email = st.text_input("Email Address")
            new_password = st.text_input("Temporary Password", type="password", 
                                        help="User should change this on first login")
            new_role = st.selectbox("Role", options=list(USER_ROLES.keys()), 
                                   format_func=lambda x: USER_ROLES[x])
            
            # Only super admin can create other super admins
            if current_user.get('role') != 'super_admin' and new_role == 'super_admin':
                st.error("❌ Only Super Admin can create other Super Admins")
                new_role = 'user'
            
            submit_add = st.form_submit_button("Create User")
            
            if submit_add:
                if new_email and new_password:
                    if user_manager.create_user(new_email, new_password, new_role, current_user.get('email')):
                        st.success(f"✅ User {new_email} created successfully!")
                        st.info(f"📧 Send these credentials to the user:")
                        st.code(f"Email: {new_email}\nTemporary Password: {new_password}")
                    else:
                        st.error("❌ Failed to create user. User may already exist.")
                else:
                    st.error("❌ Please fill in all fields")
    
    with tab2:
        st.subheader("Manage Existing Users")
        users = user_manager.get_all_users()
        
        if users:
            for user in users:
                with st.expander(f"👤 {user['email']} - {USER_ROLES.get(user['role'], user['role'])}"):
                    col1, col2, col3 = st.columns([2, 1, 1])
                    
                    with col1:
                        st.write(f"**Email:** {user['email']}")
                        st.write(f"**Role:** {USER_ROLES.get(user['role'], user['role'])}")
                        st.write(f"**Status:** {'✅ Active' if user.get('is_active', False) else '❌ Inactive'}")
                        st.write(f"**Created:** {user.get('created_at', 'Unknown')}")
                        st.write(f"**Last Login:** {user.get('last_login', 'Never')}")
                        st.write(f"**Login Count:** {user.get('login_count', 0)}")
                    
                    with col2:
                        if user['email'] != current_user.get('email'):  # Can't modify self
                            new_role = st.selectbox(f"Change Role", 
                                                   options=list(USER_ROLES.keys()),
                                                   index=list(USER_ROLES.keys()).index(user['role']),
                                                   key=f"role_{user['email']}")
                            
                            if st.button(f"Update Role", key=f"update_{user['email']}"):
                                if user_manager.update_user_role(user['email'], new_role, current_user.get('email')):
                                    st.success("✅ Role updated!")
                                    st.rerun()  # Fixed - was st.experimental_rerun()
                    
                    with col3:
                        if user['email'] != current_user.get('email'):  # Can't deactivate self
                            if user.get('is_active', False):
                                if st.button(f"🚫 Deactivate", key=f"deactivate_{user['email']}"):
                                    if user_manager.deactivate_user(user['email'], current_user.get('email')):
                                        st.success("✅ User deactivated!")
                                        st.rerun()  # Fixed - was st.experimental_rerun()
                            else:
                                if st.button(f"✅ Activate", key=f"activate_{user['email']}"):
                                    if user_manager.activate_user(user['email'], current_user.get('email')):
                                        st.success("✅ User activated!")
                                        st.rerun()  # Fixed - was st.experimental_rerun()
        else:
            st.info("No users found.")
    
    with tab3:
        st.subheader("🔑 Password Management")
        
        # User's own password change
        st.markdown("### Change Your Password")
        with st.form("change_own_password"):
            old_password = st.text_input("Current Password", type="password")
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")
            change_own = st.form_submit_button("Change My Password")
            
            if change_own:
                if old_password and new_password and confirm_password:
                    if new_password != confirm_password:
                        st.error("❌ New passwords don't match")
                    elif len(new_password) < 8:
                        st.error("❌ Password must be at least 8 characters long")
                    else:
                        if user_manager.change_own_password(current_user.get('email'), old_password, new_password):
                            st.success("✅ Password changed successfully!")
                        else:
                            st.error("❌ Failed to change password. Check your current password.")
                else:
                    st.error("❌ Please fill in all password fields")
        
        # Admin password reset
        if has_permission('admin'):
            st.markdown("---")
            st.markdown("### Reset User Password (Admin)")
            
            # Get list of users for dropdown
            all_users = user_manager.get_all_users()
            user_emails = [user['email'] for user in all_users if user['email'] != current_user.get('email')]
            
            if user_emails:
                with st.form("admin_password_reset"):
                    reset_user_email = st.selectbox("Select User", user_emails)
                    temp_password = st.text_input("Temporary Password", 
                                                 value=f"TempPass{datetime.now().strftime('%m%d')}!",
                                                 help="User will be prompted to change this on next login")
                    reset_submit = st.form_submit_button("Reset Password")
                    
                    if reset_submit and reset_user_email and temp_password:
                        if len(temp_password) < 8:
                            st.error("❌ Password must be at least 8 characters long")
                        else:
                            if user_manager.reset_user_password(reset_user_email, temp_password, current_user.get('email')):
                                st.success(f"✅ Password reset for {reset_user_email}")
                                st.info("📧 Send these credentials to the user:")
                                st.code(f"Email: {reset_user_email}\nTemporary Password: {temp_password}")
                                st.warning("⚠️ User will be prompted to change password on next login")
                            else:
                                st.error("❌ Failed to reset password")
            else:
                st.info("No other users available for password reset")

    with tab4:
        st.subheader("User Statistics")
        if users:
            active_users = len([u for u in users if u.get('is_active', False)])
            total_users = len(users)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Users", total_users)
            with col2:
                st.metric("Active Users", active_users)
            with col3:
                st.metric("Inactive Users", total_users - active_users)
            
            # Role distribution
            role_counts = {}
            for user in users:
                role = user.get('role', 'user')
                role_counts[role] = role_counts.get(role, 0) + 1
            
            st.subheader("Role Distribution")
            for role, count in role_counts.items():
                st.write(f"**{USER_ROLES.get(role, role)}:** {count}")

def logout():
    """Logout current user"""
    st.session_state.authenticated = False
    st.session_state.user_data = None
    st.rerun()  # Fixed - was st.experimental_rerun()