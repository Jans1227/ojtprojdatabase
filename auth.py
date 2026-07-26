import os
import bcrypt
import cloud_sync
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from database import get_db, User, AuditLog

load_dotenv()

ROLE_PERMISSIONS = {
    "Super Admin": {
        "can_view_data": True,
        "can_add_data": True,
        "can_edit_all": True,
        "can_edit_own_only": False,
        "can_delete": True,
        "can_view_logs": True,
        "can_manage_users": True,
    },
    "Manager": {
        "can_view_data": True,
        "can_add_data": True,
        "can_edit_all": True,       
        "can_edit_own_only": False,
        "can_delete": True,         
        "can_view_logs": True,
        "can_manage_users": False,
    },
    "Auditor": {
        "can_view_data": True,
        "can_add_data": False,
        "can_edit_all": False,
        "can_edit_own_only": False,
        "can_delete": False,
        "can_view_logs": True,
        "can_manage_users": False,
    },
    "Power Viewer": {
        "can_view_data": True,
        "can_add_data": False,
        "can_edit_all": False,
        "can_edit_own_only": False,
        "can_delete": False,
        "can_view_logs": False,
        "can_manage_users": False,
    },
    "Contributor": {
        "can_view_data": True,
        "can_add_data": True,
        "can_edit_all": False,
        "can_edit_own_only": True,  
        "can_delete": False,
        "can_view_logs": False,
        "can_manage_users": False,
    },
    "Basic Viewer": {
        "can_view_data": True,
        "can_add_data": False,
        "can_edit_all": False,
        "can_edit_own_only": False,
        "can_delete": False,
        "can_view_logs": False,
        "can_manage_users": False,
    }
}


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False


def check_permission(role: str, action: str) -> bool:
    if role not in ROLE_PERMISSIONS:
        return False
    return ROLE_PERMISSIONS[role].get(action, False)


# ==========================================
# SECURED ACCOUNT OPERATIONS (WITH AUDIT TRAIL LOGGING)
# ==========================================
# ==========================================
# SECURED ACCOUNT OPERATIONS (WITH AUDIT TRAIL LOGGING & FREEZE CHECKS)
# ==========================================
def log_admin_action(db: Session, admin_username: str, details: str, client_ip: str = None, device_info: str = None):
    admin_user = db.query(User).filter(User.username == admin_username).first()
    role_label = f" ({admin_user.role})" if admin_user else ""

    log_entry = AuditLog(
        timestamp=datetime.now(timezone.utc),
        operator=f"{admin_username}{role_label}",
        action="USER_ADMIN",
        target_record_id=None,
        change_details=details,
        client_ip=client_ip,
        device_info=device_info
    )
    db.add(log_entry)
    db.flush()

    # Broadcast admin actions globally so all terminals see security events
    if cloud_sync.SYNC_ACTIVE:
        payload = {c.name: getattr(log_entry, c.name) for c in log_entry.__table__.columns if c.name != "timestamp"}
        payload["timestamp"] = log_entry.timestamp.isoformat() # Convert time to safe text for JSON
        payload["_sync_table"] = "audit_log"
        cloud_sync.export_changeset("audit_log", log_entry.id, payload)
    
    from database import backup_database
    backup_database()


def authenticate_user(username_input: str, password_input: str) -> dict | None:
    with get_db() as db:
        user = db.query(User).filter(User.username == username_input).first()
        if user and verify_password(password_input, user.password_hash):
            return {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "password_hash": user.password_hash  # Captured to track password resets in real-time
            }
    return None


def create_user(admin_username: str, new_username: str, password_plain: str, role: str, client_ip: str = None, device_info: str = None) -> str:
    if not new_username or not password_plain or not role:
        return "Error: Missing required fields."

    primary_admin = os.getenv("INITIAL_ADMIN_USER", "admin")

    # SECURITY LOCK: If account management is frozen, block everyone except the Root Admin
    if os.path.exists("account_freeze.txt") and admin_username != primary_admin:
        return "Error: Security Lock Active. Account Management is currently frozen by the Root Admin."

    if role not in ROLE_PERMISSIONS:
        return f"Error: '{role}' is not a valid system role."

    with get_db() as db:
        creator = db.query(User).filter(User.username == admin_username).first()
        if not creator or not check_permission(creator.role, "can_manage_users"):
            return "Error: Unauthorized. Only Super Admins can manage users."

        existing_user = db.query(User).filter(User.username == new_username).first()
        if existing_user:
            return "Error: Username already exists."

        hashed = hash_password(password_plain)
        new_user = User(username=new_username, password_hash=hashed, role=role)
        db.add(new_user)
        db.flush()
        
        # Sync user profile across all 10 servers
        if cloud_sync.SYNC_ACTIVE:
            payload = {
                "id": new_user.id,
                "username": new_user.username,
                "password_hash": new_user.password_hash,
                "role": new_user.role,
                "_sync_table": "user"
            }
            cloud_sync.export_changeset("user", new_user.id, payload)
        
        log_admin_action(db, admin_username, f"Created user '{new_username}' with clearance role '{role}'.", client_ip, device_info)
        return "Success: User created successfully."


def reset_user_password(admin_username: str, target_username: str, new_password_plain: str, client_ip: str = None, device_info: str = None) -> str:
    if not target_username or not new_password_plain:
        return "Error: Missing required fields."

    primary_admin = os.getenv("INITIAL_ADMIN_USER", "admin")

    # SECURITY LOCK: If account management is frozen, block everyone except the Root Admin
    if os.path.exists("account_freeze.txt") and admin_username != primary_admin:
        return "Error: Security Lock Active. Account Management is currently frozen by the Root Admin."

    with get_db() as db:
        admin = db.query(User).filter(User.username == admin_username).first()
        if not admin or not check_permission(admin.role, "can_manage_users"):
            return "Error: Unauthorized. Only Super Admins can reset passwords."

        primary_admin = "admin"
        if target_username == primary_admin and admin_username != primary_admin:
            return "Error: Security Lock active. The Primary System Admin account cannot be modified by other administrators."

        user = db.query(User).filter(User.username == target_username).first()
        if not user:
            return "Error: Target user not found."

        if target_username == admin_username:
            return "Error: Cannot reset your own active admin password from here."

        user.password_hash = hash_password(new_password_plain)
        db.flush()
        
        # Sync password change across all 10 servers
        if cloud_sync.SYNC_ACTIVE:
            payload = {
                "id": user.id,
                "username": user.username,
                "password_hash": user.password_hash,
                "role": user.role,
                "_sync_table": "user"
            }
            cloud_sync.export_changeset("user", user.id, payload)
        
        log_admin_action(db, admin_username, f"Overwrote and reset password for user '{target_username}'.", client_ip, device_info)
        return f"Success: Password for '{target_username}' has been reset successfully."


def change_user_role(admin_username: str, target_username: str, new_role: str, client_ip: str = None, device_info: str = None) -> str:
    if not target_username or not new_role:
        return "Error: Missing required fields."
        
    if new_role not in ROLE_PERMISSIONS:
        return "Error: Invalid clearance role selection."

    primary_admin = "admin"

    # SECURITY LOCK: If account management is frozen, block everyone except the Root Admin
    if os.path.exists("account_freeze.txt") and admin_username != primary_admin:
        return "Error: Security Lock Active. Account Management is currently frozen by the Root Admin."

    with get_db() as db:
        admin = db.query(User).filter(User.username == admin_username).first()
        if not admin or not check_permission(admin.role, "can_manage_users"):
            return "Error: Unauthorized."

        if target_username == primary_admin and admin_username != primary_admin:
            return "Error: Security Lock active. The Primary System Admin's clearance level cannot be modified by other administrators."

        user = db.query(User).filter(User.username == target_username).first()
        if not user:
            return "Error: Target user not found."

        if target_username == admin_username:
            return "Error: You cannot modify your own administrator clearance level."

        # Bypass writes and duplicate logs if the role is already assigned
        if user.role == new_role:
            return f"Success: Clearance level for '{target_username}' is already '{new_role}'."

        old_role = user.role
        user.role = new_role
        db.flush()
            
        # Sync role change across all 10 servers
        if cloud_sync.SYNC_ACTIVE:
            payload = {
                "id": user.id,
                "username": user.username,
                "password_hash": user.password_hash,
                "role": user.role,
                "_sync_table": "user"
            }
            cloud_sync.export_changeset("user", user.id, payload)
        
        log_admin_action(db, admin_username, f"Updated role of '{target_username}' from '{old_role}' to '{new_role}'.", client_ip, device_info)
        return f"Success: Clearance level for '{target_username}' changed to '{new_role}'."


def delete_user(admin_username: str, target_username: str, client_ip: str = None, device_info: str = None) -> str:
    if not target_username:
        return "Error: Missing target username."

    primary_admin = "admin"

    # SECURITY LOCK: If account management is frozen, block everyone except the Root Admin
    if os.path.exists("account_freeze.txt") and admin_username != primary_admin:
        return "Error: Security Lock Active. Account Management is currently frozen by the Root Admin."

    with get_db() as db:
        admin = db.query(User).filter(User.username == admin_username).first()
        if not admin or not check_permission(admin.role, "can_manage_users"):
            return "Error: Unauthorized."

        if target_username == primary_admin and admin_username != primary_admin:
            return "Error: Security Lock active. The Primary System Admin account cannot be deleted."

        user = db.query(User).filter(User.username == target_username).first()
        if not user:
            return "Error: User not found."

        if target_username == admin_username:
            return "Error: You cannot delete your own logged-in administrator account."

        db.delete(user)
        
        log_admin_action(db, admin_username, f"Deleted and revoked access for user account '{target_username}'.", client_ip, device_info)
        return f"Success: User account '{target_username}' has been removed from the system."


def seed_initial_admin():
    """
    Checks if the primary administrator already exists in the database.
    If missing or administratively locked, it seeds or restores the account securely.
    """
    env_user = "admin"
    
    try:
        with get_db() as db:
            existing_admin = db.query(User).filter(User.username == env_user).first()
            
            # Auto-heal/restore if admin is missing or hash was scrambled by a legacy kick
            is_scrambled = existing_admin and existing_admin.password_hash and existing_admin.password_hash.startswith("KICKED_BY_ADMIN_")
            
            if not existing_admin or is_scrambled:
                env_pass = os.getenv("INITIAL_ADMIN_PASSWORD", "TemporaryAdminPass123!")
                hashed_pass = hash_password(env_pass)
                
                if is_scrambled:
                    existing_admin.password_hash = hashed_pass
                    print(f"DATABASE INITIALIZATION: Master Admin '{env_user}' password hash restored securely.")
                else:
                    admin_user = User(
                        username=env_user,
                        password_hash=hashed_pass,
                        role="Super Admin"
                    )
                    db.add(admin_user)
                    print(f"DATABASE INITIALIZATION: Master Admin '{env_user}' created securely.")
    except Exception as e:
        # Catch concurrency collisions during the context exit commit phase
        if "unique constraint" in str(e).lower() or "integrityerror" in str(e).lower():
            pass
        else:
            raise e