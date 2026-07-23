"""
FLARE-BASED CLOUD SYNC ENGINE (RCLONE / GDRIVE COMPATIBLE)
This module isolates all cloud synchronization logic. It prevents collisions using
"Flares" (edit locks) and "Turfs" (merge locks), passing tiny JSON changesets over flaky networks.
"""
import os
import json
import glob
import time
from datetime import datetime, timezone
import random
import uuid
import socket
import atexit
from dotenv import load_dotenv

# Ensure local .env file variables are loaded on startup
load_dotenv()

# Check if the Google Drive / rclone path actually exists on this PC.
# Change this path to wherever your actual shared drive is mapped!
CLOUD_SYNC_DIR = os.getenv("CLOUD_SYNC_DIR", r"G:\My Drive\Tanza_DB_Sync")

# Developer override to force offline mode for testing/debugging
FORCE_OFFLINE = os.getenv("DISABLE_CLOUD_SYNC", "False").strip().upper() == "TRUE"

# --- NETWORK VERSION CONTROL ---
APP_VERSION = 2

# --- MERGE SAFETY LOCK ---
# Strictly prevents a node from overwriting the Cloud Master database 
# if its local reconciliation loop failed or is currently offline.
RECONCILIATION_SUCCESS = False

# --- MULTI-SESSION REGISTRY ---
import threading
SESSION_LOCK = threading.Lock()
ACTIVE_SESSIONS = {}

# Expose a fast memory flag to the UI sidebar so we don't run slow file I/O on every click
NETWORK_MERGER_ALIVE = False

def register_session(session_id: str, role: str):
    with SESSION_LOCK:
        ACTIVE_SESSIONS[session_id] = role

def deregister_session(session_id: str):
    with SESSION_LOCK:
        ACTIVE_SESSIONS.pop(session_id, None)

def is_any_session_admin() -> bool:
    """Returns True if at least one connected session has administrative clearance to run merges."""
    import auth # Local import to prevent circular import loops on boot
    with SESSION_LOCK:
        # Copy dictionary values to a list to prevent "dictionary changed size" iteration crashes
        roles = list(ACTIVE_SESSIONS.values())
    return any(
        auth.check_permission(role, "can_view_logs")
        for role in roles
    )

def check_true_internet():
    """Pings a reliable backbone to verify ACTUAL internet access, preventing GDrive caching illusions."""
    if FORCE_OFFLINE: return False
    try:
        # Fast 3-second timeout socket connection to Google Public DNS
        socket.create_connection(("8.8.8.8", 53), timeout=3.0)
        return True
    except OSError:
        return False

# Auto-detect if we are connected to the cloud AND truly online
if FORCE_OFFLINE:
    SYNC_ACTIVE = False
elif os.path.exists(CLOUD_SYNC_DIR):
    SYNC_ACTIVE = check_true_internet()
else:
    # If the sync folder doesn't exist yet, check if the parent drive (G:\My Drive) exists.
    parent_dir = os.path.dirname(CLOUD_SYNC_DIR)
    if os.path.exists(parent_dir):
        try:
            # Auto-create the folder and activate sync!
            os.makedirs(CLOUD_SYNC_DIR, exist_ok=True)
            SYNC_ACTIVE = check_true_internet()
        except Exception:
            SYNC_ACTIVE = False
    else:
        SYNC_ACTIVE = False

# IN-MEMORY THREAD-SAFE CACHE: Wipes network-path lag from UI thread
LOCK_CACHE = {}

# ACTIVE CLEARANCE LEVEL: Tracks the role currently logged into this specific browser tab
ACTIVE_ROLE = None

# LEADER RECOGNITION STATE: Tracks if this terminal process is currently the master cloud merger
AM_I_LEADER = False

def is_active_merger() -> bool:
    """Checks if this specific terminal process is currently the active cloud merger."""
    if not SYNC_ACTIVE:
        return False
    turf_file = os.path.join(DIRS["sync_lock"], "active_merger.txt")
    if os.path.exists(turf_file):
        try:
            with open(turf_file, "r") as f:
                current_leader = f.readline().strip()
            return current_leader == MY_NODE_ID
        except Exception:
            pass
    return False

def refresh_lock_cache():
    """Reads GDrive lock files on a background thread and updates memory."""
    global LOCK_CACHE
    if not SYNC_ACTIVE:
        LOCK_CACHE = {}
        return
    
    new_cache = {}
    try:
        # 1. Update in-memory lock states
        lock_files = glob.glob(os.path.join(DIRS["edit_locks"], "*.lock"))
        for lf in lock_files:
            try:
                rec_id = os.path.basename(lf).replace(".lock", "")
                with open(lf, "r") as f:
                    data = json.load(f)
                    # Exclude expired locks
                    if (time.time() - data.get("timestamp", 0)) <= 60:
                        new_cache[rec_id] = {
                            "username": data.get("username", "Unknown"),
                            "node_id": data.get("node_id", "")
                        }
            except Exception:
                pass
                
    except Exception:
        pass
    LOCK_CACHE = new_cache
DIRS = {
    "outbox": os.path.join(CLOUD_SYNC_DIR, "outbox"),
    "edit_locks": os.path.join(CLOUD_SYNC_DIR, "edit_locks"),
    "sync_lock": os.path.join(CLOUD_SYNC_DIR, "sync_lock"),
    "master_db": os.path.join(CLOUD_SYNC_DIR, "master_db"),
}
def init_sync_folders():
    """Ensures the cloud directory structure exists."""
    for path in DIRS.values():
        os.makedirs(path, exist_ok=True)

def is_record_locked(record_id: str, node_id: str) -> str:
    """Reads from local cache memory, returning owner only if locked by a DIFFERENT browser tab/session."""
    lock_data = LOCK_CACHE.get(record_id)
    if lock_data:
        # If the lock belongs to a different browser session/tab, return the owner name (blocks us)
        if lock_data.get("node_id") != node_id:
            return lock_data.get("username", "Unknown User")
    # If un-locked or owned by our local session, return None (unblocks us)
    return None

def acquire_edit_lock(record_id: str, username: str, node_id: str):
    """Drops a flare in the cloud to tell other servers 'I am editing this'."""
    init_sync_folders()
    lock_file = os.path.join(DIRS["edit_locks"], f"{record_id}.lock")
    payload = {
        "username": username,
        "node_id": node_id, # Anchors this lock strictly to this specific browser tab/session
        "timestamp": time.time()
    }
    try:
        with open(lock_file, "w") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno()) # Force-dump to disk to trigger instant Google Drive upload [18, 20]
    except Exception:
        pass

def release_edit_lock(record_id: str):
    """Removes the flare when you are done editing or cancel out."""
    lock_file = os.path.join(DIRS["edit_locks"], f"{record_id}.lock")
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
        except Exception:
            pass

def export_changeset(table_name: str, record_id: str, data_dict: dict):
    """
    Instead of uploading a massive SQLite file, we dump a tiny JSON changeset.
    Uses 'Atomic Renaming' (.tmp to .json) so the Main Server never reads a half-uploaded file.
    """
    init_sync_folders()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    filename = f"change_{table_name}_{record_id}_{timestamp}.json"
    filepath = os.path.join(DIRS["outbox"], filename)
    temp_filepath = filepath + ".tmp"
    
    # Inject Last-Write-Wins (LWW) Timestamp
    data_dict["_sync_updated_at"] = time.time()
    
    try:
        # 1. Write the incomplete data to a .tmp file (Main Server ignores this)
        with open(temp_filepath, "w") as f:
            json.dump(data_dict, f)
            f.flush()
            os.fsync(f.fileno()) # Force-dump to disk before renaming [18, 20]
            
        # 2. Instantly rename it to .json when finished.
        # Google Drive syncs this rename, making it appear whole and complete instantly.
        os.replace(temp_filepath, filepath)
        
    except Exception as e:
        print(f"Sync Export Error: {e}")
        # Cleanup broken temp files if writing fails midway
        try:
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
        except Exception:
            pass

# Generate a unique ID for this specific PC session when the app launches
MY_NODE_ID = uuid.uuid4().hex

def clean_stale_locks_physically():
    """Janitor Loop: Only the active leader deletes physical .lock files that are older than 60 seconds."""
    if not AM_I_LEADER: return
    try:
        lock_files = glob.glob(os.path.join(DIRS["edit_locks"], "*.lock"))
        for lf in lock_files:
            try:
                with open(lf, "r") as f:
                    data = json.load(f)
                if (time.time() - data.get("timestamp", 0)) > 60:
                    os.remove(lf)
            except Exception:
                pass
    except Exception:
        pass

def clean_stale_locks_physically():
    """Janitor Loop: Only the active leader deletes physical .lock files that are older than 60 seconds."""
    if not AM_I_LEADER: return
    try:
        lock_files = glob.glob(os.path.join(DIRS["edit_locks"], "*.lock"))
        for lf in lock_files:
            try:
                with open(lf, "r") as f:
                    data = json.load(f)
                if (time.time() - data.get("timestamp", 0)) > 60:
                    os.remove(lf)
            except Exception:
                pass
    except Exception:
        pass

def claim_main_server_turf(server_name: str) -> bool:
    """
    Two-Phase Leader Election (Coup-Proof):
    Uses a 15-second claim, a 10-second cooldown, and a microsecond pre-flight check.
    """
    init_sync_folders()
    turf_file = os.path.join(DIRS["sync_lock"], "active_merger.txt")
    
    if os.path.exists(turf_file):
        try:
            file_age = time.time() - os.path.getmtime(turf_file)
            if file_age > 120:  
                # Calculate a stable back-off delay based on Node ID to prevent simultaneous election races
                delay_slot = 10.0 + (int(MY_NODE_ID[:2], 16) % 20) # 10 to 35 seconds
                time.sleep(delay_slot)
                
                if (time.time() - os.path.getmtime(turf_file)) < 120:
                    return False
                try:
                    os.remove(turf_file)
                except Exception:
                    pass
            else:
                return False 
        except Exception:
            return False
        
    try:
        # Phase 1: The Bid
        with open(turf_file, "w") as f:
            f.write(f"{MY_NODE_ID}\nActive Server: {server_name}\nTimestamp: {time.time()}")
            f.flush()
            os.fsync(f.fileno()) # Force-dump to disk to establish immediate server authority [18, 20]
            
        # Phase 2: The Cooldown Offset (Let the network settle to expose any split-brain claims)
        time.sleep(15.0)
            
        # Phase 3: The Pre-Flight Check
        with open(turf_file, "r") as f:
            current_leader = f.readline().strip()
            
        global AM_I_LEADER
        if current_leader == MY_NODE_ID:
            # We survived the offset. We are the official Main Server.
            try:
                for conflict_file in glob.glob(os.path.join(DIRS["sync_lock"], "active_merger (*).txt")):
                    os.remove(conflict_file)
            except Exception:
                pass
                
            if not AM_I_LEADER:
                print("\n>>> [CLOUD SYNC] PROMOTED: This terminal is now the Active Merger Server! 🟢\n")
                AM_I_LEADER = True
                
            clean_stale_locks_physically() # Run janitor duties
            return True 
        else:
            if AM_I_LEADER:
                print("\n>>> [CLOUD SYNC] STANDING DOWN (COUP DETECTED): Another terminal claimed the turf. ⚪\n")
                AM_I_LEADER = False
            return False 
    except Exception:
        return False

def release_main_server_turf():
    """Deletes or overwrites the Turf file so other computers can assume leadership."""
    global AM_I_LEADER
    turf_file = os.path.join(DIRS["sync_lock"], "active_merger.txt")
    if os.path.exists(turf_file):
        try:
            # Windows Fix: Overwriting the file with "STAND_DOWN" is much safer and less prone to 
            # permission locks from Google Drive than physically trying to delete the file [16]
            with open(turf_file, "w") as f:
                f.write("STAND_DOWN")
                f.flush()
                os.fsync(f.fileno())
            if AM_I_LEADER:
                print("\n>>> [CLOUD SYNC] SHUTDOWN: Releasing active merger turf. ⚪\n")
                AM_I_LEADER = False
        except Exception:
            pass

# Forcefully release the master lock if the terminal window is closed or crashes
atexit.register(release_main_server_turf)

def parse_and_merge_changesets(db_session):
    """
    The Main Server runs this. It safely reads JSON changes, updates the local SQLite DB, 
    and handles Audit Logs alongside Permits.
    """
    if not SYNC_ACTIVE or not claim_main_server_turf("Local_Master_Node"):
        return # Drive disconnected or someone else is merging

    changesets = []
    try:
        init_sync_folders()
        changesets = glob.glob(os.path.join(DIRS["outbox"], "*.json"))
        
        from database import MainRecord, WiringPermitRecord, AuditLog
        
        for file_path in changesets:
            # Lease Renewal: Tell the network we are still alive and actively working!
            try:
                os.utime(os.path.join(DIRS["sync_lock"], "active_merger.txt"), None)
            except Exception:
                pass
                
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
                
                table = data.get("_sync_table")
                rec_id = data.get("id")
                
                if table == "wp":
                    Model = WiringPermitRecord
                elif table == "cfei":
                    Model = MainRecord
                elif table == "audit_log":
                    Model = AuditLog
                elif table == "user":
                    from database import User
                    Model = User
                else:
                    os.remove(file_path)
                    continue
                
                # Check if record already exists
                existing = db_session.query(Model).filter(Model.id == rec_id).first()
                
                # Data cleanup (convert timestamp text back to Python datetime for Audit Logs)
                clean_data = {k: v for k, v in data.items() if not k.startswith("_sync_")}
                if table == "audit_log" and "timestamp" in clean_data and isinstance(clean_data["timestamp"], str):
                    clean_data["timestamp"] = datetime.fromisoformat(clean_data["timestamp"])
                
                if existing:
                    # Last-Write-Wins (LWW) check
                    existing_time = existing.updated_at.timestamp() if hasattr(existing, 'updated_at') and existing.updated_at else 0
                    if data.get("_sync_updated_at", 0) > existing_time:
                        for key, val in clean_data.items():
                            if hasattr(existing, key):
                                setattr(existing, key, val)
                else:
                    new_rec = Model(**clean_data)
                    db_session.add(new_rec)
                
                db_session.commit()
                os.remove(file_path)
                
            except Exception as e:
                print(f"Failed to merge {file_path}: {e}")
                db_session.rollback()
        
        # BROADCAST: Use SQLite Native Backup API to safely consolidate WAL files before uploading!
        if changesets:
            global RECONCILIATION_SUCCESS
            if not RECONCILIATION_SUCCESS:
                print("[CLOUD SYNC] Merge write blocked: Local node is not successfully in sync with cloud master.")
                return

            master_backup = os.path.join(DIRS["master_db"], "master_database.db.bak")
            temp_backup = master_backup + ".tmp"
            try:
                import sqlite3
                # This safely locks the DB briefly to write a completely clean, unified file
                src = sqlite3.connect("app_database.db")
                dst = sqlite3.connect(temp_backup)
                with dst:
                    src.backup(dst)
                src.close()
                dst.close()

                # ZERO-CORRUPTION LOCK: Verify structural integrity before allowing Google Drive to sync it
                check_conn = sqlite3.connect(temp_backup)
                integrity = check_conn.execute("PRAGMA integrity_check;").fetchone()[0]
                check_conn.close()

                if integrity.lower() == "ok":
                    # FINAL PRE-UPLOAD CHECK: Did we get couped while compiling the DB?
                    still_leader = False
                    try:
                        with open(os.path.join(DIRS["sync_lock"], "active_merger.txt"), "r") as f:
                            if f.readline().strip() == MY_NODE_ID: still_leader = True
                    except Exception:
                        pass
                        
                    if still_leader:
                        # Atomic OS swap ensures Google Drive only ever uploads a perfect file
                        os.replace(temp_backup, master_backup)
                    else:
                        print("Upload Blocked: Lost leadership during DB compilation. Aborting upload to prevent corruption.")
                        global AM_I_LEADER
                        AM_I_LEADER = False
                        if os.path.exists(temp_backup):
                            try:
                                os.remove(temp_backup)
                            except Exception:
                                pass
                else:
                    print("Cloud Broadcast Blocked: Backup integrity check failed.")
                    if os.path.exists(temp_backup):
                        os.remove(temp_backup)

            except Exception as e:
                print(f"Broadcast Error: {e}")
                if os.path.exists(temp_backup):
                    try:
                        os.remove(temp_backup)
                    except Exception:
                        pass
                            
    finally:
        release_main_server_turf()

def download_master_db_on_startup():
    """
    Client PCs run this ONCE when they launch the app.
    It ONLY downloads the Master DB if the PC is brand new and missing a local database.
    """
    if not SYNC_ACTIVE:
        return
        
    master_backup = os.path.join(DIRS["master_db"], "master_database.db.bak")
    if os.path.exists(master_backup):
        import shutil
        
        # SAFEGUARD: Only copy if the local database literally does not exist.
        # If it exists, we leave it alone and let the Two-Way Reconciliation Engine handle it.
        if not os.path.exists("app_database.db"):
            try:
                shutil.copy2(master_backup, "app_database.db")
                print("Fresh node detected: Downloaded master database from cloud.")
            except Exception as e:
                print(f"Startup Download Error: {e}")

def enforce_version_control() -> bool:
    """Checks if the local app version meets the network's required version."""
    if not SYNC_ACTIVE: 
        return True
        
    init_sync_folders()
    version_file = os.path.join(DIRS["sync_lock"], "network_version.txt")
    
    try:
        if os.path.exists(version_file):
            with open(version_file, "r") as f:
                content = f.read().strip()
                if not content:
                    return False # Empty version file is a critical failure, enforce lockout [18]
                network_version = int(content)
                
            # --- FIX 17: STRICT VERSION MATCH PARITY ---
            # Enforce exact version parity to prevent database schema mismatches [1]
            if APP_VERSION != network_version:
                return False
            
        else:
            # First time setup: declare the baseline network version
            with open(version_file, "w") as f:
                f.write(str(APP_VERSION))
    except Exception as e:
        print(f"[CLOUD SYNC] Version check exception: {e}")
        return False # Safe Lockout: Block connection on any read errors or file corruption [18]
        
    return True

def parse_and_merge_changesets_direct(db_session):
    """Executes database queries, leaving turf verification logic to background threads."""
    changesets = []
    try:
        init_sync_folders()
        changesets = glob.glob(os.path.join(DIRS["outbox"], "*.json"))
        
        from database import MainRecord, WiringPermitRecord, AuditLog
        
        for file_path in changesets:
            try:
                # Renew the active merger file timestamp to keep the lock held
                try:
                    os.utime(os.path.join(DIRS["sync_lock"], "active_merger.txt"), None)
                except Exception:
                    pass
                    
                with open(file_path, "r") as f:
                    data = json.load(f)
                
                table = data.get("_sync_table")
                rec_id = data.get("id")
                
                if table == "wp":
                    Model = WiringPermitRecord
                elif table == "cfei":
                    Model = MainRecord
                elif table == "audit_log":
                    Model = AuditLog
                else:
                    os.remove(file_path)
                    continue
                
                existing = db_session.query(Model).filter(Model.id == rec_id).first()
                clean_data = {k: v for k, v in data.items() if not k.startswith("_sync_")}
                if table == "audit_log" and "timestamp" in clean_data and isinstance(clean_data["timestamp"], str):
                    clean_data["timestamp"] = datetime.fromisoformat(clean_data["timestamp"])
                
                if existing:
                    existing_time = existing.updated_at.timestamp() if hasattr(existing, 'updated_at') and existing.updated_at else 0
                    if data.get("_sync_updated_at", 0) > existing_time:
                        for key, val in clean_data.items():
                            if hasattr(existing, key):
                                setattr(existing, key, val)
                else:
                    new_rec = Model(**clean_data)
                    db_session.add(new_rec)
                
                db_session.commit()
                os.remove(file_path)
                
            except Exception as e:
                db_session.rollback()
                print(f"Merge Error for {file_path}: {e}")
                
        # Consolidate fallback backup copies on disk
        if changesets:
            global RECONCILIATION_SUCCESS
            if not RECONCILIATION_SUCCESS:
                print("[CLOUD SYNC] Mefrge write blocked: Local node is not successfully in sync with cloud master.")
                return

            master_backup = os.path.join(DIRS["master_db"], "master_database.db.bak")
            temp_backup = master_backup + ".tmp"
            try:
                import sqlite3
                src = sqlite3.connect("app_database.db")
                dst = sqlite3.connect(temp_backup)
                with dst:
                    src.backup(dst)
                src.close()
                dst.close()
            
                # ZERO-CORRUPTION LOCK: Fallback check
                check_conn = sqlite3.connect(temp_backup)
                integrity = check_conn.execute("PRAGMA integrity_check;").fetchone()[0]
                check_conn.close()
            
                if integrity.lower() == "ok":
                    # FINAL PRE-UPLOAD CHECK
                    still_leader = False
                    try:
                        with open(os.path.join(DIRS["sync_lock"], "active_merger.txt"), "r") as f:
                            if f.readline().strip() == MY_NODE_ID: still_leader = True
                    except Exception:
                        pass
                        
                    if still_leader:
                        os.replace(temp_backup, master_backup)
                    else:
                        print("Upload Blocked: Lost leadership during direct DB compilation.")
                        global AM_I_LEADER
                        AM_I_LEADER = False
                        if os.path.exists(temp_backup):
                            try:
                                os.remove(temp_backup)
                            except Exception:
                                pass
                else:
                    if os.path.exists(temp_backup):
                        os.remove(temp_backup)
            except Exception:
                if os.path.exists(temp_backup):
                    try:
                        os.remove(temp_backup)
                    except Exception:
                        pass
                        
    except Exception as e:
        print(f"Parsing process warning: {e}")

def register_administrative_kick(username: str):
    """Plants a temporary kick file (works both online over GDrive and offline locally)."""
    target_dir = DIRS["edit_locks"] if SYNC_ACTIVE else "backups"
    os.makedirs(target_dir, exist_ok=True)
    kick_file = os.path.join(target_dir, f"kicked_{username}.kick")
    try:
        with open(kick_file, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass

def check_and_consume_kick(username: str) -> bool:
    """Checks if a user was kicked, consumes the file, and returns True."""
    target_dir = DIRS["edit_locks"] if SYNC_ACTIVE else "backups"
    kick_file = os.path.join(target_dir, f"kicked_{username}.kick")
    if os.path.exists(kick_file):
        print(f"\n>>> [SECURITY] KICK DETECTED: Forcibly logging out user '{username}'.\n")
        try:
            os.remove(kick_file)
            return True
        except Exception:
            return True # Returns True even if file deletion delayed so they are logged out
    return False

def run_two_way_reconciliation():
    """
    Background Synchronization Engine:
    Performs Set Math on local and cloud databases to instantaneously identify missing 
    records, conflict resolutions, and tombstone propagation without freezing the UI.
    Optimized with robust timezone handling and a local sandbox copy process to bypass GDrive locks.
    """
    global RECONCILIATION_SUCCESS
    if not SYNC_ACTIVE:
        RECONCILIATION_SUCCESS = False
        return

    import sqlite3
    import shutil
    import database
    
    master_backup = os.path.join(DIRS["master_db"], "master_database.db.bak")
    if not os.path.exists(master_backup):
        # --- FIX 8B: RESTRICTED SEEDING (Admins Only) ---
        # Only allow authorized Admin nodes to seed a missing cloud master database [8]
        if not is_any_session_admin():
            RECONCILIATION_SUCCESS = False
            return
            
        # If no cloud master exists yet, this local node seeds it by uploading its active DB [8]
        if os.path.exists("app_database.db"):

            try:
                import sqlite3
                temp_init = master_backup + ".tmp"
                src = sqlite3.connect("app_database.db")
                dst = sqlite3.connect(temp_init)
                with dst:
                    src.backup(dst)
                src.close()
                dst.close()
                
                # Run structural integrity test before publishing to prevent cloud corruption [8]
                check_conn = sqlite3.connect(temp_init)
                integrity = check_conn.execute("PRAGMA integrity_check;").fetchone()[0]
                check_conn.close()
                
                if integrity.lower() == "ok":
                    os.replace(temp_init, master_backup)
                    print("[CLOUD SYNC] Initialized fresh cloud master database baseline.")
                else:
                    if os.path.exists(temp_init):
                        os.remove(temp_init)
                    RECONCILIATION_SUCCESS = False
                    return
            except Exception as e:
                print(f"[CLOUD SYNC] Seeding master database failed: {e}")
                RECONCILIATION_SUCCESS = False
                return
        else:
            RECONCILIATION_SUCCESS = False
            return

    # Use a simple local relative file path as our sandbox DB
    temp_local_db = "temp_reconcile.db"

    # 1. Sandbox Clone Process (Bypasses Windows %20 spaces & GDrive locking entirely)
    copied_successfully = False
    for attempt in range(3):
        try:
            shutil.copy2(master_backup, temp_local_db)
            copied_successfully = True
            break
        except Exception:
            time.sleep(1.0)
            
    if not copied_successfully:
        # Silently abort and wait for the next background cycle
        RECONCILIATION_SUCCESS = False
        return

    cloud_conn = None
    try:
        # Safe Background I/O: Check if another node's cloud merger is alive on GDrive
        global NETWORK_MERGER_ALIVE
        try:
            turf_file = os.path.join(DIRS["sync_lock"], "active_merger.txt")
            if os.path.exists(turf_file):
                if (time.time() - os.path.getmtime(turf_file)) < 120:
                    NETWORK_MERGER_ALIVE = True
                else:
                    NETWORK_MERGER_ALIVE = False
            else:
                NETWORK_MERGER_ALIVE = False
        except Exception:
            NETWORK_MERGER_ALIVE = False

        def to_timestamp(val):
            if not val: return 0.0
            if isinstance(val, (int, float)): return float(val)
            try:
                clean_str = str(val).split('+')[0].strip()
                fmt = "%Y-%m-%d %H:%M:%S" if " " in clean_str else "%Y-%m-%dT%H:%M:%S"
                dt = datetime.strptime(clean_str.split(".")[0], fmt)
                return dt.replace(tzinfo=timezone.utc).timestamp()
            except Exception:
                return 0.0

        # Open the local sandbox DB using standard, bulletproof local paths
        cloud_conn = sqlite3.connect(temp_local_db, timeout=5.0)

        tables_to_sync = {
            "cfei": (database.MainRecord, "main_records"),
            "wp": (database.WiringPermitRecord, "wiring_permits"),
            "audit_log": (database.AuditLog, "audit_logs"),
            "user": (database.User, "users")
        }

        with database.get_db() as db_session:
            # Idempotent Check: Get list of already pending JSONs to prevent outbox spam
            outbox_files = glob.glob(os.path.join(DIRS["outbox"], "*.json"))
            pending_exports = set()
            for f in outbox_files:
                parts = os.path.basename(f).split('_')
                if len(parts) >= 4:
                    pending_exports.add(f"{parts[1]}_{parts[2]}") # table_id

            cloud_cursor = cloud_conn.cursor()

            for table_key, (ModelClass, table_name) in tables_to_sync.items():
                time_col = "timestamp" if table_key == "audit_log" else "updated_at"
                
                # A. Fetch Cloud IDs & Timestamps
                cloud_states = {}
                try:
                    cloud_cursor.execute(f"SELECT id, {time_col} FROM {table_name}")
                    for row in cloud_cursor.fetchall():
                        cloud_states[row[0]] = to_timestamp(row[1])
                except Exception:
                    continue

                # B. Fetch Local IDs & Timestamps (Safely aligned to UTC)
                local_states = {}
                time_attr = getattr(ModelClass, time_col)
                for rec in db_session.query(ModelClass.id, time_attr).all():
                    val = rec[1]
                    if val:
                        # Ensure naive local database datetimes are safely treated as UTC
                        if val.tzinfo is None:
                            val = val.replace(tzinfo=timezone.utc)
                        local_states[rec[0]] = val.timestamp()
                    else:
                        local_states[rec[0]] = 0.0

                # C. Set Mathematics
                local_ids = set(local_states.keys())
                cloud_ids = set(cloud_states.keys())

                local_only = local_ids - cloud_ids
                cloud_only = cloud_ids - local_ids
                both = local_ids & cloud_ids

                # 1. LOCAL ONLY: Missing in cloud -> Export to Outbox
                for rec_id in local_only:
                    if f"{table_key}_{rec_id}" not in pending_exports:
                        obj = db_session.query(ModelClass).filter(ModelClass.id == rec_id).first()
                        if obj:
                            payload = {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in ("created_at", "updated_at", "timestamp")}
                            if table_key == "audit_log":
                                payload["timestamp"] = obj.timestamp.isoformat()
                            payload["_sync_table"] = table_key
                            export_changeset(table_key, rec_id, payload)
                
                # 2. CLOUD ONLY: Missing locally -> Pull from Cloud DB and inject
                for rec_id in cloud_only:
                    try:
                        cloud_cursor.execute(f"SELECT * FROM {table_name} WHERE id = ?", (rec_id,))
                        row = cloud_cursor.fetchone()
                        if row:
                            col_names = [description[0] for description in cloud_cursor.description]
                            row_dict = dict(zip(col_names, row))
                            
                            # Safely cast string times back to Python UTC datetimes for SQLAlchemy
                            for date_col in ["created_at", "updated_at", "timestamp"]:
                                if date_col in row_dict and row_dict[date_col] and isinstance(row_dict[date_col], str):
                                    try:
                                        clean_str = row_dict[date_col].split('+')[0].strip()
                                        fmt = "%Y-%m-%d %H:%M:%S" if " " in clean_str else "%Y-%m-%dT%H:%M:%S"
                                        row_dict[date_col] = datetime.strptime(clean_str.split(".")[0], fmt).replace(tzinfo=timezone.utc)
                                    except Exception:
                                        pass
                            
                            # --- USERNAME COLLISION SELF-HEALER ---
                            # If a user is being downloaded but their username already exists locally with a different UUID,
                            # resolve the conflict and align their UUIDs to heal the database.
                            if table_key == "user":
                                existing_local_user = db_session.query(ModelClass).filter(ModelClass.username == row_dict['username']).first()
                                if existing_local_user:
                                    local_time = existing_local_user.updated_at.timestamp() if existing_local_user.updated_at else 0.0
                                    cloud_time = to_timestamp(row_dict['updated_at'])
                                    
                                    if cloud_time > local_time:
                                        # Cloud account is newer: overwrite/replace local with cloud data
                                        db_session.delete(existing_local_user)
                                        db_session.flush() # Force deletion to satisfy unique username constraint
                                        new_obj = ModelClass(**row_dict)
                                        db_session.add(new_obj)
                                    else:
                                        # Local account is newer: Keep local data but align its UUID with the cloud's UUID.
                                        # To prevent SQLAlchemy Identity Map confusion, we extract the newer local data,
                                        # delete the old record, flush, and insert a fresh object with the cloud's ID.
                                        local_data = {
                                            "id": row_dict['id'], # Align with cloud primary key
                                            "username": existing_local_user.username,
                                            "password_hash": existing_local_user.password_hash,
                                            "role": existing_local_user.role,
                                            "updated_at": existing_local_user.updated_at
                                        }
                                        db_session.delete(existing_local_user)
                                        db_session.flush() # Purge the old entity completely from session memory
                                        
                                        new_obj = ModelClass(**local_data)
                                        db_session.add(new_obj)
                                    continue
                            # --------------------------------------
                            
                            new_obj = ModelClass(**row_dict)
                            db_session.add(new_obj)
                    except Exception as e:
                        print(f"Sync Import Error [{rec_id}]: {e}")

                # 3. BOTH EXIST (Conflict Resolution via Last-Write-Wins)
                for rec_id in both:
                    local_time = local_states[rec_id]
                    cloud_time = cloud_states[rec_id]
                    
                    # If local is at least 1 second newer, export our changes to outbox
                    if local_time > cloud_time + 1.0:
                        if f"{table_key}_{rec_id}" not in pending_exports:
                            obj = db_session.query(ModelClass).filter(ModelClass.id == rec_id).first()
                            if obj:
                                payload = {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in ("created_at", "updated_at", "timestamp")}
                                if table_key == "audit_log":
                                    payload["timestamp"] = obj.timestamp.isoformat()
                                payload["_sync_table"] = table_key
                                export_changeset(table_key, rec_id, payload)
                    
                    # If cloud is at least 1 second newer, overwrite local row (applies Tombstones!)
                    elif cloud_time > local_time + 1.0:
                        try:
                            cloud_cursor.execute(f"SELECT * FROM {table_name} WHERE id = ?", (rec_id,))
                            row = cloud_cursor.fetchone()
                            if row:
                                col_names = [description[0] for description in cloud_cursor.description]
                                row_dict = dict(zip(col_names, row))
                                
                                obj = db_session.query(ModelClass).filter(ModelClass.id == rec_id).first()
                                if obj:
                                    for k, v in row_dict.items():
                                        if k in ["created_at", "updated_at", "timestamp"] and v and isinstance(v, str):
                                            try:
                                                clean_str = str(v).split('+')[0].strip()
                                                fmt = "%Y-%m-%d %H:%M:%S" if " " in clean_str else "%Y-%m-%dT%H:%M:%S"
                                                v = datetime.strptime(clean_str.split(".")[0], fmt).replace(tzinfo=timezone.utc)
                                            except Exception:
                                                pass
                                        if hasattr(obj, k):
                                            setattr(obj, k, v)
                        except Exception as e:
                            print(f"Sync Overwrite Error [{rec_id}]: {e}")

        # Declare absolute synchronization success!
        RECONCILIATION_SUCCESS = True

    except Exception as e:
        print(f"Reconciliation Engine Failure: {e}")
        RECONCILIATION_SUCCESS = False
    finally:
        if cloud_conn:
            cloud_conn.close()
        # Clean up the local sandbox copy immediately to keep disk clean
        if os.path.exists(temp_local_db):
            try:
                os.remove(temp_local_db)
            except Exception:
                pass

def get_db_sync_status() -> str:
    """
    Checks connection, reconciliation success, and pending outbox changesets 
    to return a precise database synchronization status string.
    """
    if not SYNC_ACTIVE:
        return "OFFLINE"
    
    # Fast, lock-free check for any pending changesets in the outbox
    outbox_files = []
    try:
        outbox_files = glob.glob(os.path.join(DIRS["outbox"], "*.json"))
    except Exception:
        pass
        
    if not RECONCILIATION_SUCCESS:
        return "FAILED_RECONCILE"
        
    if len(outbox_files) > 0:
        return "PENDING_MERGE"
        
    return "SYNCED"
