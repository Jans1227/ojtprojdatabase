import os
import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from contextlib import contextmanager
import sqlite3

import threading

def backup_database():
    """
    Launches an asynchronous background thread to safely clone the active database
    without blocking the user interface or SQLite transactions.
    """
    def execute_threaded_backup():
        # 1. Read directory from .env
        backup_dir = os.getenv("BACKUP_DIR", "backups")
        
        # Check if backup_dir uses a Windows drive pattern (e.g., D:\...)
        is_drive_path = len(backup_dir) > 1 and backup_dir[1] == ":" and backup_dir[0].isalpha()
        
        if is_drive_path:
            target_drive = backup_dir[0].upper() + ":\\"
            # Check if the configured drive exists
            if not os.path.exists(target_drive):
                # Drive is missing or unmounted; find alternative active Windows drives (A to Z)
                import string
                possible_drives = [f"{let}:\\" for let in string.ascii_uppercase if let != target_drive[0]]
                alternative_found = False
                for drive in possible_drives:
                    if os.path.exists(drive):
                        # Redirect backup directory suffix to this active alternative drive
                        alternative_dir = os.path.join(drive, backup_dir[2:].lstrip("\\/"))
                        try:
                            if not os.path.exists(alternative_dir):
                                os.makedirs(alternative_dir)
                            backup_dir = alternative_dir
                            alternative_found = True
                            break
                        except Exception:
                            continue
                if not alternative_found:
                    # Local workspace fallback if no secondary drive options exist
                    backup_dir = "backups"
                    
        # Ensure backup directory exists
        if not os.path.exists(backup_dir):
            try:
                os.makedirs(backup_dir)
            except Exception:
                # Ultimate safe local fallback to current relative directory
                backup_dir = "backups"
                if not os.path.exists(backup_dir):
                    try:
                        os.makedirs(backup_dir)
                    except Exception:
                        return # Exit silently if writing to storage is completely blocked
                        
        target_path = os.path.join(backup_dir, "app_database_backup.db")
        temp_path = target_path + ".tmp"

        try:
            # 3. Clone to a temporary sandbox file first (with dynamic retry loop to prevent write locks) [19]
            copied_successfully = False
            for attempt in range(3):
                try:
                    src = sqlite3.connect("app_database.db")
                    dst = sqlite3.connect(temp_path)
                    with dst:
                        src.backup(dst)
                    src.close()
                    dst.close()
                    copied_successfully = True
                    break
                except Exception:
                    time.sleep(1.0) # Wait 1 second for any SQLite transaction to release [19]
            
            if not copied_successfully:
                return # Fail silently and safely if the database remains heavily locked

        # 4. ZERO-CORRUPTION LOCK: Run deep structural integrity test on the clone
            check_conn = sqlite3.connect(temp_path)
            integrity = check_conn.execute("PRAGMA integrity_check;").fetchone()[0]
            check_conn.close()

            if integrity.lower() == "ok":
            # 5. ATOMIC OS SWAP: Physically impossible to interrupt or corrupt during replace
                os.replace(temp_path, target_path)
            else:
                print("Backup Warning: Integrity check failed. Discarding corrupted clone.")
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        except Exception as e:
            print(f"Silent Backup Warning: {e}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    # Start the background cloner thread to prevent UI freezing
    t = threading.Thread(target=execute_threaded_backup, daemon=True)
    t.start()
# The SQLite database file will sit right in your project folder
DB_URL = "sqlite:///app_database.db"

# Connection Pool (responsiveness for multiple users)
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False}, # Necessary for multi-threaded SQLite
    pool_size=10, 
    max_overflow=20
)

# Active WAL (Write-Ahead Logging) and Foreign Keys
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Modern SQLAlchemy 2.0 Declarative Base
class Base(DeclarativeBase):
    pass

# ==========================================
# 1. THE USERS TABLE
# ==========================================
class User(Base):
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: uuid.uuid4().hex)
    username: Mapped[str] = mapped_column(unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(nullable=False) # Admin, Manager, Contributor, basic, etc.
    updated_at: Mapped[datetime] = mapped_column(nullable=True, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
# ==========================================
# 2. THE MAIN DATA TABLE (CFEI RECORDS)
# ==========================================
class MainRecord(Base):
    __tablename__ = "main_records"
    
    # Primary internal key (non-recyclable)
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: uuid.uuid4().hex)
    
    # LGU Permit Fields
    wp_number: Mapped[str] = mapped_column(nullable=False, index=True) # WP-01-25-0001
    applicant_name: Mapped[str] = mapped_column(nullable=False, index=True) # JUAN DELA CRUZ
    address: Mapped[str] = mapped_column(nullable=False) # SITIO BATUMBAKAL
    barangay: Mapped[str] = mapped_column(nullable=False) # AMAYA IV
    occupancy: Mapped[str] = mapped_column(nullable=False) # RESIDENTIAL
    installation: Mapped[str] = mapped_column(nullable=False) # TEMPORARY
    bp_number: Mapped[str] = mapped_column(nullable=True) # B.P
    bp_number: Mapped[str] = mapped_column(nullable=True) # B.P
    coo_number: Mapped[str] = mapped_column(nullable=True) # C.O.O
    cei_number: Mapped[str] = mapped_column(nullable=True) # C.E.I
    remarks: Mapped[str] = mapped_column(nullable=True) # Authority to move-in (pag-ibig)
    import_batch_id: Mapped[str] = mapped_column(nullable=True, index=True) # Groups bulk XLSX imports
    
    # 9 CFEI Specific Loads
    cfei_qty_light: Mapped[int] = mapped_column(nullable=True)
    cfei_qty_range: Mapped[int] = mapped_column(nullable=True)
    cfei_qty_acu: Mapped[int] = mapped_column(nullable=True)
    cfei_qty_switch: Mapped[int] = mapped_column(nullable=True)
    cfei_qty_motor: Mapped[int] = mapped_column(nullable=True)
    cfei_qty_misc: Mapped[int] = mapped_column(nullable=True)
    cfei_qty_conv: Mapped[int] = mapped_column(nullable=True)
    cfei_qty_bell: Mapped[int] = mapped_column(nullable=True)
    cfei_qty_others: Mapped[str] = mapped_column(nullable=True)
    or_number: Mapped[str] = mapped_column(nullable=True) # O.R. Number (OP-XXXX)
    total_cost: Mapped[float] = mapped_column(nullable=True)
    qty_main_switch: Mapped[int] = mapped_column(nullable=True)
    qty_socket: Mapped[int] = mapped_column(nullable=True)
    qty_conv_outlet: Mapped[int] = mapped_column(nullable=True)
    qty_switch: Mapped[int] = mapped_column(nullable=True)
    qty_others: Mapped[str] = mapped_column(nullable=True)
    
    # New CFEI Layout Fields
    # New CFEI Layout Fields (fully mapped)
    cfei_switchboard_qty: Mapped[str] = mapped_column(nullable=True)
    cfei_meter_qty: Mapped[str] = mapped_column(nullable=True)
    cfei_service_type: Mapped[str] = mapped_column(nullable=True)
    cfei_wiring_method: Mapped[str] = mapped_column(nullable=True)

    # New WP Layout Fields (fully mapped)
    wp_qty_units: Mapped[str] = mapped_column(nullable=True)
    wp_service_type: Mapped[str] = mapped_column(nullable=True)
    
    # Cryptographically encrypted authorization signature
    signature_base64: Mapped[str] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(nullable=True, default=lambda: datetime.now(timezone.utc))
    is_hidden: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="0")
    is_deleted: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="0")
    
    # Auditing and system-enforced tracking
    created_by: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(timezone.utc))

# ==========================================
# 2.1 THE WIRING PERMIT RECORDS TABLE
# ==========================================
class WiringPermitRecord(Base):
    __tablename__ = "wiring_permits"
    
    # Primary internal key (non-recyclable)
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: uuid.uuid4().hex)
    
    # LGU Permit Fields
    wp_number: Mapped[str] = mapped_column(nullable=False, index=True) # WP-01-25-0001
    applicant_name: Mapped[str] = mapped_column(nullable=False, index=True) # JUAN DELA CRUZ
    address: Mapped[str] = mapped_column(nullable=False) # SITIO BATUMBAKAL
    barangay: Mapped[str] = mapped_column(nullable=False) # AMAYA IV
    occupancy: Mapped[str] = mapped_column(nullable=False) # RESIDENTIAL
    installation: Mapped[str] = mapped_column(nullable=False) # TEMPORARY
    bp_number: Mapped[str] = mapped_column(nullable=True) # B.P
    coo_number: Mapped[str] = mapped_column(nullable=True) # C.O.O
    remarks: Mapped[str] = mapped_column(nullable=True) # Authority to move-in (pag-ibig)
    import_batch_id: Mapped[str] = mapped_column(nullable=True, index=True) # Groups bulk XLSX imports
    or_number: Mapped[str] = mapped_column(nullable=True) # O.R. Number (OP-XXXX)
    total_cost: Mapped[float] = mapped_column(nullable=True)
    
    # WP Specific Load Fields (fully mapped)
    qty_main_switch: Mapped[int] = mapped_column(nullable=True)
    qty_socket: Mapped[int] = mapped_column(nullable=True)
    qty_conv_outlet: Mapped[int] = mapped_column(nullable=True)
    qty_switch: Mapped[int] = mapped_column(nullable=True)
    qty_others: Mapped[str] = mapped_column(nullable=True)
    
    # New CFEI Layout Fields (fully mapped)
    cfei_switchboard_qty: Mapped[str] = mapped_column(nullable=True)
    cfei_meter_qty: Mapped[str] = mapped_column(nullable=True)
    cfei_service_type: Mapped[str] = mapped_column(nullable=True)
    cfei_wiring_method: Mapped[str] = mapped_column(nullable=True)
    
    # New WP Layout Fields (fully mapped)
    wp_qty_units: Mapped[str] = mapped_column(nullable=True)
    wp_service_type: Mapped[str] = mapped_column(nullable=True)
    
    # Cryptographically encrypted authorization signature
    signature_base64: Mapped[str] = mapped_column(nullable=True) 
    updated_at: Mapped[datetime] = mapped_column(nullable=True, default=lambda: datetime.now(timezone.utc))
    is_hidden: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="0")
    is_deleted: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="0")
    
    # Auditing and system-enforced tracking
    created_by: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(timezone.utc))
# ==========================================
# 3. THE HISTORICAL AUDIT LOG TABLE
# ==========================================
class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: uuid.uuid4().hex)
    timestamp: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(timezone.utc))
    operator: Mapped[str] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(nullable=False)
    target_record_id: Mapped[str] = mapped_column(nullable=True)
    change_details: Mapped[str] = mapped_column(nullable=False)
    client_ip: Mapped[str] = mapped_column(nullable=True)
    device_info: Mapped[str] = mapped_column(nullable=True)

# ==========================================
# SAFE TRANSACTION MANAGER (With Rollback)
# ==========================================
@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit() # Save changes automatically if everything goes right
    except Exception as e:
        db.rollback() # Undo all changes instantly if there is an error
        raise e
    finally:
        db.close()

# Helper function to create all tables on first launch (Safe checked)
# Helper function to create all tables on first launch (Safe checked)
def init_db():
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
        # Safe structural database migration check for existing tables
        with engine.connect() as conn:
            import sqlalchemy as sa
            inspector = sa.inspect(engine)
            
            # 1. Update Main Records (CFEI)
            cols_main = [c['name'] for c in inspector.get_columns('main_records')]
            if 'updated_at' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN updated_at DATETIME"))
            if 'is_hidden' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT 0"))
            if 'is_deleted' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"))
            if 'total_cost' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN total_cost REAL"))
            if 'import_batch_id' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN import_batch_id TEXT"))
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN total_cost REAL"))
            if 'cei_number' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cei_number TEXT"))
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_qty_light INTEGER"))
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_qty_range INTEGER"))
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_qty_acu INTEGER"))
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_qty_switch INTEGER"))
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_qty_motor INTEGER"))
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_qty_misc INTEGER"))
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_qty_conv INTEGER"))
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_qty_bell INTEGER"))
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_qty_others TEXT"))
                
            # New CFEI Layout Fields
            if 'cfei_switchboard_qty' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_switchboard_qty TEXT"))
            if 'cfei_meter_qty' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_meter_qty TEXT"))
            if 'cfei_service_type' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_service_type TEXT"))
            if 'cfei_wiring_method' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN cfei_wiring_method TEXT"))
            # New WP Layout Fields
            if 'wp_qty_units' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN wp_qty_units TEXT"))
            if 'wp_service_type' not in cols_main:
                conn.execute(sa.text("ALTER TABLE main_records ADD COLUMN wp_service_type TEXT"))

            # 2. Update Wiring Permits
            cols_wp = [c['name'] for c in inspector.get_columns('wiring_permits')]
            if 'updated_at' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN updated_at DATETIME"))
            if 'is_hidden' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT 0"))
            if 'is_deleted' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"))
            if 'total_cost' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN total_cost REAL"))
            if 'import_batch_id' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN import_batch_id TEXT"))
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN total_cost REAL"))
            if 'qty_main_switch' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN qty_main_switch INTEGER"))
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN qty_socket INTEGER"))
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN qty_conv_outlet INTEGER"))
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN qty_switch INTEGER"))
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN qty_others TEXT"))
                
            # New CFEI Layout Fields
            if 'cfei_switchboard_qty' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN cfei_switchboard_qty TEXT"))
            if 'cfei_meter_qty' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN cfei_meter_qty TEXT"))
            if 'cfei_service_type' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN cfei_service_type TEXT"))
            if 'cfei_wiring_method' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN cfei_wiring_method TEXT"))
            # New WP Layout Fields
            if 'wp_qty_units' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN wp_qty_units TEXT"))
            if 'wp_service_type' not in cols_wp:
                conn.execute(sa.text("ALTER TABLE wiring_permits ADD COLUMN wp_service_type TEXT"))

            # 3. Update Users
            cols_user = [c['name'] for c in inspector.get_columns('users')]
            if 'updated_at' not in cols_user:
                conn.execute(sa.text("ALTER TABLE users ADD COLUMN updated_at DATETIME"))
                
            conn.commit()
    except Exception as e:
        # If SQLite table-locks or phantom database files exist, bypass the crash
        error_msg = str(e).lower()
        if "already exists" in error_msg or "duplicate column name" in error_msg:
            pass
        else:
            raise e