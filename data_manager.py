from datetime import datetime, timezone, timedelta

# Define Philippine Standard Time (UTC+8)
PHT = timezone(timedelta(hours=8), 'PHT')

from sqlalchemy.orm import Session
from sqlalchemy import or_
from database import get_db, MainRecord, AuditLog, User, WiringPermitRecord
from auth import check_permission
import os
from cryptography.fernet import Fernet
import re
import cloud_sync

def _get_model(record_type: str):
    """Returns the correct database model representing either Wiring Permits (wp) or CFEI (cfei)."""
    return WiringPermitRecord if record_type == "wp" else MainRecord

def get_next_wp_sequence(record_type: str = "cfei", target_date: datetime = None) -> str:
    """Finds the highest 4-digit WP sequence number for the given month in the DB and returns the next one
    (e.g., '0001'). Suffix resets to 0001 at the start of a new month."""
    if target_date is None:
        target_date = datetime.now(timezone.utc)
    current_prefix = f"WP-{target_date.strftime('%m-%y')}-" # Generates "WP-MM-YY-" dynamically

    Model = _get_model(record_type)
    with get_db() as db:        # Only query records created during the current month
        records = db.query(Model).filter(Model.wp_number.like(f"{current_prefix}%")).all()
        highest = 0
        for r in records:
            if r.wp_number:
                match = re.search(r'(\d{4})$', r.wp_number.strip())
                if match:
                    num = int(match.group(1))
                    if num > highest:
                        highest = num
        next_num = highest + 1
        return f"{next_num:04d}"

def get_next_bp_sequence(prefix: str, month_str: str = None, year_str: str = None, record_type: str = "cfei") -> str:
    """Finds the highest 4-digit BP sequence number for the chosen prefix, month, and year."""
    now = datetime.now(timezone.utc)
    m = month_str if month_str else now.strftime('%m')
    y = year_str if year_str else now.strftime('%y')
    current_prefix = f"{prefix.upper()}-{m}-{y}-"

    Model = _get_model(record_type)
    with get_db() as db:
        records = db.query(Model).filter(Model.bp_number.like(f"{current_prefix}%")).all()
        highest = 0
        for r in records:
            if r.bp_number:
                match = re.search(r'(\d{4})$', r.bp_number.strip())
                if match:
                    num = int(match.group(1))
                    if num > highest:
                        highest = num
        next_num = highest + 1
        return f"{next_num:04d}"

# Load signature encryption key from your secure .env file
sig_key = os.getenv("SIGNATURE_KEY")
if sig_key:
    # Strip invisible trailing spaces, newlines, or literal quotes from your .env
    sig_key = sig_key.strip().strip("'").strip('"')

cipher = None
if sig_key:
    try:
        cipher = Fernet(sig_key.encode())
    except Exception as e:
        # Prevents a broken key from crashing the entire server on startup
        print(f"\n⚠️ SECURITY WARNING: Invalid SIGNATURE_KEY in .env. {e}\n")

def encrypt_signature(sig_base64: str | None) -> str | None:
    if not sig_base64 or not cipher:
        return sig_base64
    # Encrypts the base64 string using AES-128
    return cipher.encrypt(sig_base64.encode('utf-8')).decode('utf-8')

def decrypt_signature(sig_encrypted: str | None) -> str | None:
    if not sig_encrypted or not cipher:
        return sig_encrypted
    try:
        # Decrypts the raw database string back to base64
        return cipher.decrypt(sig_encrypted.encode('utf-8')).decode('utf-8')
    except Exception:
        return sig_encrypted  # Fallback if the database record was already plain-text

def log_action(db: Session, operator_username_with_role: str, action: str, record_id: str | None, details: str, client_ip: str = None, device_info: str = None):
    log_entry = AuditLog(
        timestamp=datetime.now(timezone.utc),
        operator=operator_username_with_role,
        action=action,
        target_record_id=record_id,
        change_details=details,
        client_ip=client_ip,
        device_info=device_info
    )
    db.add(log_entry)
    db.flush()
    
    import cloud_sync
    if cloud_sync.SYNC_ACTIVE:
        payload = {c.name: getattr(log_entry, c.name) for c in log_entry.__table__.columns if c.name != "timestamp"}
        payload["timestamp"] = log_entry.timestamp.isoformat() # Convert time to safe text for JSON
        payload["_sync_table"] = "audit_log"
        cloud_sync.export_changeset("audit_log", log_entry.id, payload)
    
    # Silently clone the DB locally
    from database import backup_database
    backup_database()
# ==========================================
# SYSTEM LOCKDOWN SECURITY CHECK
# ==========================================
def is_system_locked(operator_username: str) -> bool:
    """Returns True if the system lockdown is active on disk and the user is NOT the Root Admin."""
    primary_admin = os.getenv("INITIAL_ADMIN_USER", "admin")
    if os.path.exists("system_lock.txt") and operator_username != primary_admin:
        return True
    return False

def clean_numeric_cost(value) -> float:
    """Safely converts string or float currency values (e.g., ₱1,500.00) to clean floats."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        import math
        return float(value) if not math.isnan(value) else 0.0
    try:
        # Strip Peso signs, commas, and trailing whitespaces
        clean_str = str(value).replace("₱", "").replace(",", "").strip()
        return float(clean_str) if clean_str else 0.0
    except ValueError:
        return 0.0

def create_record(operator: dict, record_type: str, wp_number: str, applicant_name: str,
                  address: str, barangay: str, occupancy: str, installation: str,
                  bp_number: str = "", coo_number: str = "", remarks: str = "",
                  or_number: str = "", signature_base64: str = None, client_ip: str = None,
                  device_info: str = None, total_cost: float = 0.0, import_batch_id: str = "",
                  created_at: datetime = None) -> str:
    # SECURITY LOCK: If system is locked, block writes for everyone but Root Admin
    if is_system_locked(operator["username"]):
        return "Error: System Lockdown Active. The database is currently frozen in Read-Only mode by the Root Admin."

    if not check_permission(operator["role"], "can_add_data"):
        return "Error: Your role does not have permission to add records."

    # Clean empty/NaN values first so we can validate them accurately
    def sanitize_field(val: str) -> str:
        if val is None:
            return ""
        s = str(val).strip().upper()
        return "" if s in ("NAN", "NONE", "<NA>", "NAT", "NULL", "") else s

    # Enforce ALL CAPS and sanitize string inputs
    wp_clean = sanitize_field(wp_number)
    name_clean = sanitize_field(applicant_name)
    addr_clean = sanitize_field(address)
    brgy_clean = sanitize_field(barangay)
    occ_clean = sanitize_field(occupancy)
    inst_clean = sanitize_field(installation)
    bp_clean = sanitize_field(bp_number)
    coo_clean = sanitize_field(coo_number)
    rem_clean = sanitize_field(remarks)
    or_clean = sanitize_field(or_number)
    batch_clean = sanitize_field(import_batch_id)

    # NOW run validations on the cleaned variables to block empty "NAN" inputs
    if not wp_clean or not name_clean or not addr_clean or not brgy_clean or not occ_clean or not inst_clean:
        return "Error: Missing mandatory data fields."

    # Parse and clean numeric cost safely
    parsed_cost = clean_numeric_cost(total_cost)

    # Strict OR Number Format Validation (7 Digits)
    if or_clean:
        if not re.match(r'^\d{7}$', or_clean):
            return "Error: OR Number must be exactly 7 digits (e.g., 1234567)."

    Model = _get_model(record_type)
    with get_db() as db:
        new_record = Model(
            wp_number=wp_clean,
            applicant_name=name_clean,
            address=addr_clean,
            barangay=brgy_clean,
            occupancy=occ_clean,
            installation=inst_clean,
            bp_number=bp_clean,
            coo_number=coo_clean,
            remarks=rem_clean,
            or_number=or_clean,
            signature_base64=encrypt_signature(signature_base64),
            total_cost=parsed_cost, # Fixed: Map the clean parsed_cost variable!
            import_batch_id=batch_clean,
            created_by=operator["username"]
        )
        if created_at:
            new_record.created_at = created_at
            new_record.updated_at = created_at
        db.add(new_record)
        db.flush()

        label_type = "WIRING PERMIT" if record_type == "wp" else "CFEI"
        log_msg = f"Created {label_type} record '{wp_clean}' for '{name_clean}'."
        if operator["role"] == "Manager":
            log_msg = f"[FLAGGED - MANAGER ACTION] {log_msg}"

        log_action(db, f"{operator['username']} ({operator['role']})", "INSERT", new_record.id, log_msg, client_ip, device_info)
        
        if cloud_sync.SYNC_ACTIVE:
            payload = {c.name: getattr(new_record, c.name) for c in new_record.__table__.columns if c.name != "created_at" and c.name != "updated_at"}
            payload["_sync_table"] = record_type
            cloud_sync.export_changeset(record_type, new_record.id, payload)
            
        return f"Success: Record '{wp_clean}' successfully created."


def update_record(operator: dict, record_id: int, record_type: str, wp_number: str, applicant_name: str,
                  address: str, barangay: str, occupancy: str, installation: str, bp_number: str = "",
                  coo_number: str = "", remarks: str = "", or_number: str = "",
                  new_signature_base64: str = None,
                  client_ip: str = None, device_info: str = None, total_cost: float = 0.0) -> str:
    # SECURITY LOCK: If system is locked, block writes for everyone but Root Admin
    if is_system_locked(operator["username"]):
        return "Error: System Lockdown Active. The database is currently frozen in Read-Only mode by the Root Admin."

    # Strict OR Number Format Validation (7-digit number)
    if or_number and or_number.strip():
        or_clean = or_number.strip()
        if not re.match(r'^\d{7}$', or_clean):
            return "Error: OR Number must be exactly 7 digits (e.g., 1234567)."

    Model = _get_model(record_type)
    with get_db() as db:
        record = db.query(Model).filter(Model.id == record_id).first()
            
        if not record:
            return "Error: Record not found."

        is_admin_or_manager = check_permission(operator["role"], "can_edit_all")
        is_owner = (record.created_by == operator["username"])
        can_edit_own = check_permission(operator["role"], "can_edit_own_only")

        if not is_admin_or_manager:
            if not (can_edit_own and is_owner):
                return "Error: Unauthorized. You can only edit records you originally created."

        # Enforce ALL CAPS on update inputs
        wp_clean = wp_number.strip().upper()
        name_clean = applicant_name.strip().upper()
        addr_clean = address.strip().upper()
        brgy_clean = barangay.strip().upper()
        occ_clean = occupancy.strip().upper()
        inst_clean = installation.strip().upper()
        bp_clean = bp_number.strip().upper() if bp_number else ""
        coo_clean = coo_number.strip().upper() if coo_number else ""
        rem_clean = remarks.strip().upper() if remarks else ""
        or_clean = or_number.strip().upper() if or_number else ""

        # Safely compare and log exact changes
        changes = []
        fields = [
            ("wp_number", record.wp_number, wp_clean, "WP Number"),
            ("applicant_name", record.applicant_name, name_clean, "Applicant"),
            ("address", record.address, addr_clean, "Address"),
            ("barangay", record.barangay, brgy_clean, "Barangay"),
            ("occupancy", record.occupancy, occ_clean, "Occupancy"),
            ("installation", record.installation, inst_clean, "Installation"),
            ("bp_number", record.bp_number, bp_clean, "BP"),
            ("coo_number", record.coo_number, coo_clean, "COO"),
            ("remarks", record.remarks, rem_clean, "Remarks"),
            ("or_number", record.or_number, or_clean, "OR Number"),
            ("total_cost", record.total_cost, total_cost, "Total Cost")
        ]
        for attr, old_val, new_val, label in fields:
            if old_val != new_val:
                # Format float values cleanly as currency, and cast other types to string safely
                old_str = f"₱{old_val:,.2f}" if isinstance(old_val, (int, float)) else str(old_val) if old_val is not None else "None"
                new_str = f"₱{new_val:,.2f}" if isinstance(new_val, (int, float)) else str(new_val) if new_val is not None else "None"
                
                old_disp = f"{old_str[:12]}..." if len(old_str) > 15 else old_str
                new_disp = f"{new_str[:12]}..." if len(new_str) > 15 else new_str
                
                changes.append(f"{label}: '{old_disp}' -> '{new_disp}'")
                setattr(record, attr, new_val)

        if new_signature_base64:
            if new_signature_base64.startswith("gAAAAA"):
                if record.signature_base64 != new_signature_base64:
                    record.signature_base64 = new_signature_base64
                    changes.append("Signature updated.")
            else:
                encrypted_sig = encrypt_signature(new_signature_base64)
                if record.signature_base64 != encrypted_sig:
                    record.signature_base64 = encrypted_sig
                    changes.append("Signature updated.")
        else:
            encrypted_sig = encrypt_signature(new_signature_base64)
            if record.signature_base64 != encrypted_sig:
                record.signature_base64 = encrypted_sig
                changes.append("Signature updated.")

        if not changes:
            return "Success: No changes detected."

        record.updated_at = datetime.now(timezone.utc) # Track exact update moment
        change_summary = ", ".join(changes)
        label_type = "Wiring Permit" if record_type == "wp" else "CFEI"
        log_msg = f"Modified {label_type} {record.wp_number}: {change_summary}"
        
        if operator["role"] == "Manager":
            log_msg = f"[FLAGGED - MANAGER ACTION] {log_msg}"

        log_action(db, f"{operator['username']} ({operator['role']})", "UPDATE", record.id, log_msg, client_ip, device_info)
        
        if cloud_sync.SYNC_ACTIVE:
            payload = {c.name: getattr(record, c.name) for c in record.__table__.columns if c.name != "created_at" and c.name != "updated_at"}
            payload["_sync_table"] = record_type
            cloud_sync.export_changeset(record_type, record.id, payload)
            
        return "Success: Record updated successfully."

def delete_record(operator: dict, record_id: int, record_type: str, client_ip: str = None, device_info: str = None) -> str:
    # SECURITY LOCK: If system is locked, block writes for everyone but Root Admin
    if is_system_locked(operator["username"]):
        return "Error: System Lockdown Active. The database is currently frozen in Read-Only mode by the Root Admin."
    if not check_permission(operator["role"], "can_delete"):
        return "Error: Unauthorized. Only Admins and Managers can delete entries."

    Model = _get_model(record_type)
    with get_db() as db:
        record = db.query(Model).filter(Model.id == record_id).first()
        if not record:
            return "Error: Record not found."

        label_type = "Wiring Permit" if record_type == "wp" else "CFEI"
        log_msg = f"Deleted {label_type} ID {record.id}: '{record.wp_number}' for '{record.applicant_name}'."
        if operator["role"] == "Manager":
            log_msg = f"[FLAGGED - MANAGER ACTION] {log_msg}"

        log_action(db, f"{operator['username']} ({operator['role']})", "DELETE", record.id, log_msg, client_ip, device_info)
        
        # --- TOMBSTONE WIPE LOGIC ---
        record.is_deleted = True
        record.updated_at = datetime.now(timezone.utc)
        
        # Wipe sensitive details and assign a guaranteed unique deleted string using the record's ID
        record.wp_number = f"DELETED-{record.id[:8]}"
        record.applicant_name = f"DELETED-{record.id[:8]}"
        record.address = ""
        record.barangay = ""
        record.occupancy = ""
        record.installation = ""
        record.bp_number = ""
        record.coo_number = ""
        record.remarks = "RECORD PURGED"
        record.or_number = ""
        record.signature_base64 = None
        record.total_cost = 0.0
        
        # Also wipe table-specific fields based on record_type
        if record_type == "wp":
            record.qty_main_switch = 0
            record.qty_socket = 0
            record.qty_conv_outlet = 0
            record.qty_switch = 0
            record.qty_others = ""
            record.wp_qty_units = ""
            record.wp_service_type = ""
        else:
            record.cei_number = ""
            record.cfei_switchboard_qty = ""
            record.cfei_meter_qty = ""
            record.cfei_service_type = ""
            record.cfei_wiring_method = ""
            record.cfei_qty_light = 0
            record.cfei_qty_range = 0
            record.cfei_qty_acu = 0
            record.cfei_qty_switch = 0
            record.cfei_qty_motor = 0
            record.cfei_qty_misc = 0
            record.cfei_qty_conv = 0
            record.cfei_qty_bell = 0
            record.cfei_qty_others = ""
        
        # Sync the tombstone out to the cloud JSON outbox immediately
        import cloud_sync
        if cloud_sync.SYNC_ACTIVE:
            payload = {c.name: getattr(record, c.name) for c in record.__table__.columns if c.name != "created_at" and c.name != "updated_at"}
            payload["_sync_table"] = record_type
            cloud_sync.export_changeset(record_type, record.id, payload)
        
        # Clean up lock file automatically on delete
        if cloud_sync.SYNC_ACTIVE:
            cloud_sync.release_edit_lock(str(record_id))
            
        return "Success: Record deleted."

def search_records(query_str: str = None, barangay_filter: str = None, occupancy_filter: str = None, installation_filter: str = None, remarks_keyword: str = None, include_hidden: bool = False, record_type: str = "cfei") -> list:
    Model = _get_model(record_type)
    with get_db() as db:
        q = db.query(Model)
        
        # 1. Universal text search bar (Google-style with "", AND, and OR logic)
        if query_str and query_str.strip():
            # Extract AND clauses, respecting double quotes
            and_terms_raw = re.findall(r'(?:[^,"]|"[^"]*")+', query_str)
            
            for raw_and in and_terms_raw:
                and_term = raw_and.strip()
                if not and_term:
                    continue
                
                # For each AND term, look for OR clauses (split by |), respecting quotes
                or_terms_raw = re.findall(r'(?:[^|"]|"[^"]*")+', and_term)
                or_clauses = []
                
                for raw_or in or_terms_raw:
                    clean_raw = raw_or.strip()
                    is_exact = clean_raw.startswith('"') and clean_raw.endswith('"') and len(clean_raw) >= 2
                    term = clean_raw.strip('"').strip().upper()
                    if not term:
                        continue

                    if is_exact:
                        or_clauses.append(or_(
                            Model.wp_number == term,
                            Model.applicant_name == term,
                            Model.address == term,
                            Model.barangay == term,
                            Model.occupancy == term,
                            Model.installation == term,
                            Model.bp_number == term,
                            Model.coo_number == term,
                            Model.remarks == term,
                            Model.or_number == term
                        ))
                    else:
                        like_term = f"%{term}%"
                        or_clauses.append(or_(
                            Model.wp_number.like(like_term),
                            Model.applicant_name.like(like_term),
                            Model.address.like(like_term),
                            Model.barangay.like(like_term),
                            Model.occupancy.like(like_term),
                            Model.installation.like(like_term),
                            Model.bp_number.like(like_term),
                            Model.coo_number.like(like_term),
                            Model.remarks.like(like_term),
                            Model.or_number.like(like_term)
                        ))
                
                if or_clauses:
                    q = q.filter(or_(*or_clauses))
        
        # 2. Strict category dropdown filters (restored - exact match to prevent substring overlaps)
        if barangay_filter and barangay_filter != "All Barangays":
            q = q.filter(Model.barangay == barangay_filter)
            
        if occupancy_filter and occupancy_filter != "All Occupancy Types":
            q = q.filter(Model.occupancy.like(f"%{occupancy_filter}%"))
            
        if installation_filter and installation_filter != "All Installation Types":
            q = q.filter(Model.installation.like(f"%{installation_filter}%"))
            
        # 3. Filter out hidden/archived items unless requested
        if not include_hidden:
            q = q.filter(Model.is_hidden == False)
            
        # 4. STRICTLY filter out all deleted tombstones so they never appear in UI
        q = q.filter(Model.is_deleted == False)
        
        results = q.all()
        valid_installs = {"NEW", "TEMPORARY", "REMODEL", "RELOCATION", "SEPARATION", "RECONNECTION"}
        return [
            {
                "id": r.id,
                "wp_number": r.wp_number,
                "applicant_name": r.applicant_name,
                "address": r.address,
                "barangay": r.barangay,
                "occupancy": r.occupancy,
                "installation": r.installation if r.installation in valid_installs else f"[LEGACY: {r.installation}]",
                "bp_number": r.bp_number,
                "coo_number": r.coo_number,
                "remarks": r.remarks,
                "or_number": r.or_number,
                "signature_base64": decrypt_signature(r.signature_base64),
                "total_cost": r.total_cost,
                "created_by": r.created_by,
                "created_at": r.created_at.replace(tzinfo=timezone.utc).astimezone(PHT).strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": (r.updated_at if r.updated_at else r.created_at).replace(tzinfo=timezone.utc).astimezone(PHT).strftime("%Y-%m-%d %H:%M:%S"),
                "is_hidden": r.is_hidden,
                "import_batch_id": getattr(r, "import_batch_id", "")
            }
            for r in results
        ]

def get_audit_logs(operator: dict) -> list:
    if not check_permission(operator["role"], "can_view_logs"):
        return []

    with get_db() as db:
        logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).all()
        return [
            {
                "id": l.id,
                "timestamp": l.timestamp.replace(tzinfo=timezone.utc).astimezone(PHT).strftime("%Y-%m-%d %I:%M %p"),
                "operator": l.operator,
                "action": l.action,
                "target_record_id": l.target_record_id,
                "change_details": l.change_details,
                "client_ip": l.client_ip,
                "device_info": l.device_info
            }
            for l in logs
        ]

def hide_record(operator: dict, record_id: int, record_type: str, is_hidden_val: bool, client_ip: str = None, device_info: str = None) -> str:
    """Toggles the soft-archived (hidden) status of a specific record in the system."""
    if is_system_locked(operator["username"]):
        return "Error: System Lockdown Active. The database is currently frozen in Read-Only mode by the Root Admin."

    Model = _get_model(record_type)
    with get_db() as db:
        record = db.query(Model).filter(Model.id == record_id).first()
        if not record:
            return "Error: Record not found."

        # Perform update
        record.is_hidden = is_hidden_val
        record.updated_at = datetime.now(timezone.utc)
        
        status_text = "ARCHIVED" if is_hidden_val else "UNARCHIVED"
        label_type = "Wiring Permit" if record_type == "wp" else "CFEI"
        log_msg = f"{status_text} {label_type} {record.wp_number} (Hidden from main table, payment records preserved)."
        
        log_action(db, f"{operator['username']} ({operator['role']})", status_text, record.id, log_msg, client_ip, device_info)
        
        # Clean up lock file automatically on hide/archive
        if cloud_sync.SYNC_ACTIVE:
            cloud_sync.release_edit_lock(str(record_id))
            
        return "Success: Record archive state modified successfully."