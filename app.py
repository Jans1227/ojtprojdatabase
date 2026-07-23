import streamlit as st
import pandas as pd
import io
import base64
import difflib
import os
import re
import uuid
import glob
from collections import Counter
from PIL import Image, ImageFilter
from datetime import datetime, timezone, timedelta
PHT = timezone(timedelta(hours=8), 'PHT')
from streamlit_drawable_canvas import st_canvas

import database
import auth
import data_manager

# ==============================================================================
# SILENCE HARMLESS WINDOWS ASYNCIO SPAM (WinError 10054)
# ==============================================================================
import asyncio
import sys
import logging

def silence_windows_proactor_spam():
    """Intercepts and silences harmless asyncio connection drops in Windows console."""
    if sys.platform == 'win32':
        # Silence standard asyncio event loop logging
        logging.getLogger("asyncio").setLevel(logging.CRITICAL)
        
        try:
            loop = asyncio.get_event_loop()
            def custom_exception_handler(loop, context):
                exception = context.get('exception')
                # Catch and silently discard standard Windows connection resets
                if isinstance(exception, (ConnectionResetError, ConnectionAbortedError)):
                    return
                # Allow actual critical errors to pass through
                loop.default_exception_handler(context)
            loop.set_exception_handler(custom_exception_handler)
        except Exception:
            pass

silence_windows_proactor_spam()

# Set up page configurations
st.set_page_config(page_title="Secure Enterprise Portal", layout="wide")

# ==============================================================================
# NETWORK VERSION CONTROL LOCKOUT
# ==============================================================================
import cloud_sync
# CACHE FIX: Only read from the network drive once when the tab is first opened
if "version_check_passed" not in st.session_state:
    st.session_state.version_check_passed = cloud_sync.enforce_version_control()

if not st.session_state.version_check_passed:
    st.markdown("""
        <div style="background-color: #f8f9fa; padding: 30px; border-radius: 12px; margin-top: 50px; border: 2px solid #e9ecef; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
            <h1 style="color: #dc3545; margin: 0;">🔄 System Update Required</h1>
            <h3 style="color: #495057; margin-top: 15px;">Your local terminal is using an outdated version.</h3>
            <p style="color: #6c757d; font-size: 1.1em; max-width: 600px; margin: 20px auto;">
                The central cloud network has been upgraded. To prevent data issues, your access has been safely paused. Don't worry, no data was lost!
            </p>
            <div style="background-color: #e3f2fd; padding: 15px; border-radius: 8px; display: inline-block; text-align: left;">
                <h4 style="margin-top: 0; color: #0d47a1;">🛠️ Action Required:</h4>
                <p style="margin-bottom: 0; color: #0d47a1; font-weight: bold;">
                    Please contact your System Administrator to apply the latest system patch to this computer.
                </p>
            </div>
            <p style="color: #adb5bd; margin-top: 25px; font-size: 0.9em;">Need help? Contact the LGU IT Department.</p>
        </div>
    """, unsafe_allow_html=True)
    st.stop() # Physically halts all further Streamlit rendering and script execution

import time as pytime
st.session_state["last_main_execution"] = pytime.time()

# Ensure all session state variables are initialized before any read operations occur
if "success_msg" not in st.session_state:
    st.session_state.success_msg = None
if "user" not in st.session_state:
    st.session_state.user = None
if "session_node_id" not in st.session_state:
    st.session_state.session_node_id = uuid.uuid4().hex
if "selected_uuids" not in st.session_state:
    st.session_state.selected_uuids = set() # Global startup initialization
if "processed_file_names" not in st.session_state:
    st.session_state.processed_file_names = set() # Tracks parsed spreadsheets
if "persistent_active_registry" not in st.session_state:
    st.session_state.persistent_active_registry = "🏢 CFEI Records"
if "active_registry_selection" not in st.session_state:
    st.session_state.active_registry_selection = st.session_state.persistent_active_registry
# ==============================================================================
# CUSTOM CSS & JS: STICKY TABS, SIGNATURE SAFETY, & PRECISION ACTION LOCKS
# ==============================================================================
st.markdown(r"""
<style>
/* Freezes the tabs at the top as you scroll */
div[data-testid="stTabs"] [role="tablist"] {
    position: -webkit-sticky !important;
    position: sticky !important;
    top: 0 !important;
    z-index: 999 !important;
    background-color: var(--background-color, #ffffff) !important;
    padding-top: 10px !important;
    padding-bottom: 10px !important;
}

/* Completely hides the "View fullscreen" hover button on all images */
button[data-testid="StyledFullScreenButton"],
button[title="View fullscreen"],
button[title="View fullscreen"]:hover,
.overlayBtn,
.element-container .overlayBtn {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    height: 0 !important;
    width: 0 !important;
}

/* Prevents right-click dragging of authorization signatures */
img {
    pointer-events: none !important;
    -webkit-user-drag: none !important;
    user-select: none !important;
    -moz-user-select: none !important;
    -webkit-user-select: none !important;
    -ms-user-select: none !important;
}

/* Hides the hover download and search toolbar from all database tables */
[data-testid="stElementToolbar"] {
    display: none !important;
}
</style>

<script>
// --- IRONCLAD MONEY & NUMBER INPUT SANITIZER ---
if (!window.customAppListenersRegistered) {
    function isProtectedInput(target) {
        if (!target || target.tagName !== 'INPUT') return false;
        if (target.type === 'number') return true;
        var info = (target.id || '') + ' ' + (target.name || '') + ' ' + (target.getAttribute('aria-label') || '');
        return /cost|money|total|amount|₱/i.test(info);
    }

    // 1. Instantly block 'e', 'E', '+', '-' keypresses on all numeric/cost inputs
    document.addEventListener('keydown', function(e) {
        if (isProtectedInput(e.target)) {
            if (['e', 'E', '+', '-'].includes(e.key)) {
                e.preventDefault();
            }
        }
    }, true);

    // 2. Instantly strip 'e', 'E', '+', '-' if pasted into cost/number inputs
    document.addEventListener('input', function(e) {
        if (isProtectedInput(e.target)) {
            if (/[eE+-]/.test(e.target.value)) {
                e.target.value = e.target.value.replace(/[eE+-]/g, '');
            }
        }
    }, true);

    window.customAppListenersRegistered = true;
}
</script>
""", unsafe_allow_html=True)
# ==========================================
# 1. INITIALIZE DATABASE ON LAUNCH
# ==========================================
try:
    import cloud_sync
    cloud_sync.download_master_db_on_startup()
except Exception:
    pass

database.init_db()
auth.seed_initial_admin()

# ==============================================================================
# NATIVE BACKGROUND SYNC THREAD (0-DELAY UI RENDERING)
# ==============================================================================
import threading
import time as pytime

def background_sync_worker():
    """Handles GDrive parsing, locks, and changesets in parallel without blocking."""
    last_merge_run = 0
    while True:
        try:
            import cloud_sync
            import database
            
            # 1. Scans Google Drive locks to update local memory (runs every 3 seconds)
            cloud_sync.refresh_lock_cache()
            
            # 2. Periodically negotiates turf and merges databases (runs every 15 seconds)
            current_time = pytime.time()
            if (current_time - last_merge_run) > 15:
                    
                    # --- DECENTRALIZED RECONCILIATION ENGINE ---
                    # Every active node independently compares its local DB to the cloud master
                if cloud_sync.SYNC_ACTIVE:
                    try:
                        cloud_sync.run_two_way_reconciliation()
                    except Exception as e:
                        print(f"[CLOUD SYNC] Reconciliation Error: {e}")
                    # -------------------------------------------

                    # Verify that at least one active browser session on this server has administrative clearance
                is_authorized_merger = cloud_sync.is_any_session_admin()

                if is_authorized_merger:
                    # Negotiates lock outside of active database sessions (retaining turf file on disk)
                    if cloud_sync.SYNC_ACTIVE and cloud_sync.claim_main_server_turf("Local_Master_Node"):
                        try:
                            # Opens database session ONLY when ready to execute writes
                            with database.get_db() as sync_db:
                                cloud_sync.parse_and_merge_changesets_direct(sync_db)
                        except Exception as e:
                            print(f"[CLOUD SYNC] Merge Execution Error: {e}")
                else:
                    # --- FIX 16: SYSTEM-WIDE STAND DOWN ON ADMINISTRATIVE LOGOUT [16] ---
                    # If no connected session on this server has admin rights, release the active merger lock [16]
                    if cloud_sync.AM_I_LEADER:
                        cloud_sync.release_main_server_turf()
                
                last_merge_run = current_time
                
        except Exception as e:
            print(f"Background Sync Thread Error: {e}")
        pytime.sleep(3) # Safe polling cycle

# Spin up the sync worker once on launch
if "sync_thread_active" not in st.session_state:
    t = threading.Thread(target=background_sync_worker, daemon=True)
    t.start()
    st.session_state.sync_thread_active = True

# ==============================================================================
# SILENT BACKGROUND SECURITY HEARTBEAT (RUNS EVERY 10 SECONDS)
# ==============================================================================
@st.fragment(run_every=10)
def run_silent_heartbeat():
    import cloud_sync
    # Safe Fallback: If session ID is somehow missing, generate a unique ID on the fly
    sess_id = st.session_state.get("session_node_id", uuid.uuid4().hex)
    
    if not st.session_state.get("user"):
        cloud_sync.deregister_session(sess_id)
        return

    # Register this browser tab's session ID and role to prevent process-level collisions
    cloud_sync.register_session(sess_id, st.session_state.user["role"])
    # Print live heartbeat ticks to standard output for real-time confirmation
    from datetime import datetime
    print(f">>> [HEARTBEAT] {datetime.now().strftime('%H:%M:%S')} - Active session check for '{st.session_state.user['username']}'...")

    # LOCK RENEWAL (PING): Keep all our active multi-locks alive on GDrive
    active_locks = st.session_state.get("current_locked_ids", [])
    if active_locks:
        try:
            import cloud_sync
            if cloud_sync.SYNC_ACTIVE:
                for lock_id in active_locks:
                    cloud_sync.acquire_edit_lock(lock_id, st.session_state.user["username"], st.session_state.session_node_id)
        except Exception:
            pass

    u = st.session_state.user

    # SECURITY CHECK: Force logout if an admin planted a kick file for this session
    import cloud_sync
    if cloud_sync.check_and_consume_kick(u["username"]):
        st.session_state.user = None
        st.session_state.success_msg = "⚠️ Security Alert: You have been administratively kicked by the System Admin."
        st.rerun()

    try:
        with database.get_db() as db:
            current_user_db = db.query(database.User).filter(database.User.id == u["id"]).first()
            
            if current_user_db is None:
                st.session_state.user = None
                st.session_state.success_msg = "⚠️ Security Alert: Your account has been deleted."
                st.rerun()
            elif u.get("password_hash") != current_user_db.password_hash:
                st.session_state.user = None
                st.session_state.success_msg = "⚠️ Security Alert: Your password was updated."
                st.rerun()
            elif u["role"] != current_user_db.role:
                st.session_state.user["role"] = current_user_db.role
                st.rerun()

            # REAL-TIME SYNC POLL: Scan if the background daemon thread has merged new cloud data
            try:
                import sqlalchemy as sa
                # Identify which database table is currently viewed on screen
                target_reg = st.session_state.get("persistent_active_registry", "🏢 CFEI Records")
                active_model = database.WiringPermitRecord if target_reg == "⚡ Wiring Permits" else database.MainRecord
                
                # Fetch total count and max updated_at timestamp in a single indexed query (<1ms)
                res = db.query(sa.func.count(active_model.id), sa.func.max(active_model.updated_at)).first()
                current_count = res[0] or 0
                current_max_time = res[1].timestamp() if res[1] else 0.0

                # Use registry-specific state keys to prevent false triggers when switching tabs
                count_key = f"last_db_count_{target_reg}"
                time_key = f"last_db_max_time_{target_reg}"

                last_count = st.session_state.get(count_key)
                last_max_time = st.session_state.get(time_key)

                # Initialize states on first launch
                if last_count is None or last_max_time is None:
                    st.session_state[count_key] = current_count
                    st.session_state[time_key] = current_max_time
                elif current_count != last_count or current_max_time != last_max_time:
                    # Intercept: Only refresh if the operator is NOT actively typing or inside the bulk wizard
                    add_in_progress = any(
                        str(st.session_state.get(k, "")).strip() 
                        for k in st.session_state.keys() 
                        if k.startswith("add_") and "select" not in k and "total_cost" not in k
                    )
                    is_typing = st.session_state.get("active_select_id") is not None or st.session_state.get("bulk_edit_active", False) or add_in_progress
                    if not is_typing:
                        st.session_state[count_key] = current_count
                        st.session_state[time_key] = current_max_time
            
                        import time as pytime
                        # Prevent double-rerun loop: Skip if the main script literally just ran a local CRUD action
                        if pytime.time() - st.session_state.get("last_main_execution", 0) > 3.0:
                            st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                            st.rerun()

            except Exception:
                pass
    except Exception as e:
        # Safely swallow database lockup operational exceptions on standard heartbeats
        print(f"[HEARTBEAT WARN] SQLite database is currently locked: {e}")


# Activate the background heartbeat
run_silent_heartbeat()

# Show persistent success messages at the top of the dashboard if they exist
msg_placeholder = st.empty()
if st.session_state.success_msg:
    msg_placeholder.success(st.session_state.success_msg)
    st.session_state.success_msg = None

# ==========================================
# 1.5 Extra
# ==========================================

def get_client_metadata():
    """Reads client IP and Device OS/Browser from browser headers."""
    headers = st.context.headers
    # Standard proxy check, falls back to direct remote host IP
    ip = headers.get("X-Forwarded-For", headers.get("Remote-Host", "Local-Server"))
    # Extracts OS/Browser details
    user_agent = headers.get("User-Agent", "Unknown Device")
    # Shorten user agent string so it doesn't clutter logs
    short_agent = user_agent.split(" (")[0] if " (" in user_agent else user_agent
    return ip, short_agent

# Session state to track which record's signature has been authorized for decryption
if "unblurred_id" not in st.session_state:
    st.session_state.unblurred_id = None

def blur_signature_base64(sig_base64_str: str, radius: int = 18) -> str:
    """
    Applies mathematically irreversible Gaussian blur on the server-side (Python).
    The client browser only receives the scrambled, blurred image bytes.
    """
    try:
        img_data = base64.b64decode(sig_base64_str)
        img = Image.open(io.BytesIO(img_data))
        # Performs the math on the server PC before sending to network
        blurred_img = img.filter(ImageFilter.GaussianBlur(radius))
        buffered = io.BytesIO()
        blurred_img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")
    except Exception:
        return sig_base64_str

# ==============================================================================
# CUSTOM CSS: STICKY FROZEN TABS, HIDE FULLSCREEN, & HIDE HEARTBEAT BUTTONS
# ==============================================================================
st.markdown("""
<style>
/* Freezes the tabs at the top as you scroll */
div[data-testid="stTabs"] {
    position: -webkit-sticky;
    position: sticky;
    top: 0;
    z-index: 999;
    background-color: inherit;
    padding-top: 10px;
    padding-bottom: 10px;
}

/* Completely hides the "View fullscreen" hover button on all images to prevent getting stuck */
button[data-testid="StyledFullScreenButton"],
button[title="View fullscreen"],
button[title="View fullscreen"]:hover,
.overlayBtn,
.element-container .overlayBtn {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    height: 0 !important;
    width: 0 !important;
}

/* Completely masks the heartbeat trigger button from human eyes without blocking JS clicks */
.hidden-container {
    position: absolute !important;
    opacity: 0 !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    pointer-events: none !important;
}
</style>
""", unsafe_allow_html=True)


# ==========================================
# 2. SESSION STATE MANAGEMENT
# ==========================================
if "user" not in st.session_state:
    st.session_state.user = None  # Tracks active logged-in user

if "search_query_val" not in st.session_state:
    st.session_state.search_query_val = ""  # For spelling suggestions

if "success_msg" not in st.session_state:
    st.session_state.success_msg = None  # For green notifications banner

# Ensure all session state variables are initialized before any read operations occur
if "user" not in st.session_state:
    st.session_state.user = None

# Bypassing the StreamlitAPIException with the "Form Key Suffix" trick
if "form_id" not in st.session_state:
    st.session_state.form_id = 0

# Dynamic Key Suffix to programmatically clear active table highlights
if "table_id" not in st.session_state:
    st.session_state.table_id = 0

    # Permanent Selection Lock to prevent the Modify panel from vanishing
if "active_select_id" not in st.session_state:
    st.session_state.active_select_id = None

# Guided Bulk Modify Wizard Session State
if "bulk_edit_active" not in st.session_state:
    st.session_state.bulk_edit_active = False
if "bulk_edit_ids" not in st.session_state:
    st.session_state.bulk_edit_ids = []
if "bulk_edit_index" not in st.session_state:
    st.session_state.bulk_edit_index = 0

# Helper to convert canvas signature data to Base64
def convert_canvas_to_base64(canvas_raw):
    if canvas_raw is not None and canvas_raw.image_data is not None:
        import numpy as np
        # Robust Blank Check: Look for any drawn black strokes (pixels less than white 255)
        # or any non-transparent pixels (in case background is transparent)
        has_drawn_strokes = np.any(canvas_raw.image_data[:, :, :3] < 255) or np.any(canvas_raw.image_data[:, :, 3] > 0)
        
        if has_drawn_strokes:
            img = Image.fromarray(canvas_raw.image_data.astype('uint8'), 'RGBA')
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            return base64.b64encode(buffered.getvalue()).decode("utf-8")
    return None


# Helper to generate beautiful, unified printable HTML certificate documents with bleed prevention
def generate_print_html(records_list, record_type="cfei") -> str:
    if not records_list:
        return "<html><body>No records selected to print.</body></html>"

    # Define paths pointing directly into your print_assets folder
    assets_dir = os.path.join(os.path.dirname(__file__), "print_assets")
    
    # Dynamically select the template and stylesheet files based on active selection
    if record_type == "wp":
        template_file = "print_template(wiring).html"
        css_file = "stylesheet2.css"
    else:
        template_file = "print_template(cfei).html"
        css_file = "stylesheet.css"
        
    template_path = os.path.join(assets_dir, template_file)

    try:
        # Load the custom 1:1 Excel HTML template from the print_assets folder
        with open(template_path, "r", encoding="utf-8") as f:
            base_template = f.read()
    except Exception as e:
        return f"<html><body>Error loading {template_file} from print_assets disk: {e}</body></html>"

    # 2. INLINE THE STYLESHEET TO BYPASS BROWSER CORS RESTRICTIONS
    try:
        css_path = os.path.join(assets_dir, css_file)
        with open(css_path, "r", encoding="utf-8") as f_css:
            css_content = f_css.read()
        # Replace external CSS link reference with inline style blocks
        base_template = base_template.replace(f'<link rel=Stylesheet href="print_assets/{css_file}">', f"<style>{css_content}</style>")
        base_template = base_template.replace(f'<link rel=Stylesheet href={css_file}>', f"<style>{css_content}</style>")
        base_template = base_template.replace('<link rel=Stylesheet href="print_assets/stylesheet.css">', f"<style>{css_content}</style>")
        base_template = base_template.replace('<link rel=Stylesheet href=stylesheet.css>', f"<style>{css_content}</style>")
        base_template = base_template.replace('<link rel=Stylesheet href="print_assets/stylesheet2.css">', f"<style>{css_content}</style>")
        base_template = base_template.replace('<link rel=Stylesheet href=stylesheet2.css>', f"<style>{css_content}</style>")
    except Exception:
        pass
    # 3. INLINE THE IMAGES (LOGOS) AS BASE64 DATA URIs
    for img_num in ["001", "002", "003", "004", "005", "006", "007", "008", "009"]:
        img_file = f"image{img_num}.png"
        img_path = os.path.join(assets_dir, img_file)
        if os.path.exists(img_path):
            try:
                with open(img_path, "rb") as f_img:
                    img_b64 = base64.b64encode(f_img.read()).decode("utf-8")
                # Swap local image links with self-contained base64 images
                base_template = base_template.replace(f'src="print_assets/{img_file}"', f'src="data:image/png;base64,{img_b64}"')
                base_template = base_template.replace(f'src=print_assets/{img_file}', f'src="data:image/png;base64,{img_b64}"')
                base_template = base_template.replace(f'src="{img_file}"', f'src="data:image/png;base64,{img_b64}"')
                base_template = base_template.replace(f'src={img_file}', f'src="data:image/png;base64,{img_b64}"')
            except Exception:
                pass

    # CHOOSE BACKGROUND IMAGE (Loads image1 as the full page template backdrop)
    watermark_b64 = ""
    for ext in ["png", "jpeg", "jpg"]:
        bg_path = os.path.join(assets_dir, f"image1.{ext}")
        if os.path.exists(bg_path):
            try:
                with open(bg_path, "rb") as f_w:
                    watermark_b64 = base64.b64encode(f_w.read()).decode("utf-8")
                break
            except Exception:
                pass

    # DYNAMIC PDF FILENAME SETUP
    if len(records_list) == 1:
        r = records_list[0]
        # Generate clean name file slug
        clean_name = "".join(c for c in r.get('applicant_name', '') if c.isalnum() or c in (' ', '-', '_')).strip().replace(" ", "_")
        file_title = f"Wiring_Permit_{r.get('wp_number', 'Record')}_{clean_name}"
    else:
        file_title = f"Wiring_Permits_Bulk_Export_{len(records_list)}_Records"

    certificates_html = ""
    for r in records_list:
        # Format the creation date safely and robustly
        date_str = r.get("created_at", "")
        formatted_date = "PENDING"
        if date_str:
            try:
                clean_date_str = date_str.split(" UTC")[0].split("+")[0].strip()
                dt = datetime.strptime(clean_date_str, "%Y-%m-%d %H:%M:%S")
                formatted_date = dt.strftime("%B %d, %Y").upper()
            except Exception:
                formatted_date = date_str.upper()
            
        # Determine installation checkboxes dynamically
        inst = r.get("installation", "").upper()
        a_check = "X" if "NEW" in inst else "&nbsp;"
        b_check = "X" if "TEMPORARY" in inst else "&nbsp;"
        c_check = "X" if "REMODEL" in inst else "&nbsp;"
        d_check = "X" if "RELOCATION" in inst else "&nbsp;"
        e_check = "X" if "SEPARATION" in inst else "&nbsp;"
        f_check = "X" if "RECONNECTION" in inst else "&nbsp;"

        # Prepare values for replacement
        wp_number = r.get("wp_number", "").upper()
        applicant_name = r.get("applicant_name", "").upper()
        address_barangay = f"{r.get('address', '')}, {r.get('barangay', '')}".upper()
        bp_val = str(r.get("bp_number") or "").strip().upper()
        bp_number = bp_val if bp_val and bp_val not in ("PENDING", "NONE") else ""

        coo_val = str(r.get("coo_number") or "").strip().upper()
        coo_number = coo_val if coo_val and coo_val not in ("PENDING", "NONE") else ""
        
        # --- FIX 5: DYNAMIC OCCUPANCY CHECKBOXES FOR PRINT PREVIEWS ---
        occ_type = str(r.get("occupancy", "")).upper()
        res_check = "X" if "RESIDENTIAL" in occ_type else "&nbsp;"
        comm_check = "X" if "COMMERCIAL" in occ_type else "&nbsp;"
        ind_check = "X" if "INDUSTRIAL" in occ_type else "&nbsp;"
        inst_check = "X" if "INSTITUTIONAL" in occ_type else "&nbsp;"
        gov_check = "X" if "GOVERNMENT" in occ_type else "&nbsp;"
        
        raw_remarks = r.get("remarks", "").upper()
        
        # Proper Legal Suffix Mapping
        inst_phrase = inst
        if "NEW" in inst: inst_phrase = "NEW CONNECTION"
        elif "TEMPORARY" in inst: inst_phrase = "TEMPORARY CONNECTION"
        elif "REMODEL" in inst: inst_phrase = "REMODEL OF SERVICE ENTRANCE"
        elif "RELOCATION" in inst: inst_phrase = "RELOCATION OF SERVICE ENTRANCE"
        elif "SEPARATION" in inst: inst_phrase = "SEPARATION OF SERVICE ENTRANCE"
        elif "RECONNECTION" in inst: inst_phrase = "RECONNECTION OF SERVICE ENTRANCE"
        elif "NET METERING" in inst: inst_phrase = "NET METERING"

        # Clean remarks formatting (Wiring Permits show raw remarks/blank; CFEI includes APPROVED FOR prefix)
        if record_type == "wp":
            remarks_inline = raw_remarks if raw_remarks and raw_remarks != "NONE" else ""
        else:
            if not raw_remarks or raw_remarks == "NONE":
                remarks_inline = f"APPROVED FOR {inst_phrase}"
            else:
                if raw_remarks.startswith("APPROVED FOR"):
                    remarks_inline = raw_remarks
                else:
                    remarks_inline = f"APPROVED FOR {inst_phrase} - {raw_remarks}"

        # --- FIX 15: DEFENSIVE QUANTITY ZERO-PADDING SANITIZER [15] ---
        def fmt_qty(val):
            if val is None or val == "":
                return "&nbsp;"
            try:
                # Strip spaces and cast to float to catch variations like "000", "0.00", or "0" [15]
                if float(str(val).strip()) == 0.0:
                    return "&nbsp;"
            except ValueError:
                pass # Keep text labels like "PENDING" intact
            return str(val)

        record_base = base_template
        
        if record_type == "wp":
            record_base = record_base.replace("{qty_main_switch}", fmt_qty(r.get("qty_main_switch")))
            record_base = record_base.replace("{qty_socket}", fmt_qty(r.get("qty_socket")))
            record_base = record_base.replace("{qty_conv_outlet}", fmt_qty(r.get("qty_conv_outlet")))
            record_base = record_base.replace("{qty_switch}", fmt_qty(r.get("qty_switch")))
            q_oth = str(r.get("qty_others") or "")
            if not q_oth.strip() or q_oth.strip().upper() == "NONE":
                q_oth = "&nbsp;"
            record_base = record_base.replace("{qty_others}", q_oth)
        else:
            record_base = record_base.replace("{cei_number}", str(r.get("cei_number") or ""))
            record_base = record_base.replace("{cfei_switchboard_qty}", fmt_qty(r.get("cfei_switchboard_qty")))
            record_base = record_base.replace("{cfei_meter_qty}", fmt_qty(r.get("cfei_meter_qty")))
            record_base = record_base.replace("{cfei_service_type}", str(r.get("cfei_service_type") or "Single Phase"))
            record_base = record_base.replace("{cfei_wiring_method}", str(r.get("cfei_wiring_method") or "CONCEALED WIRING INSTALLATION"))
            
            record_base = record_base.replace("{cfei_qty_light}", fmt_qty(r.get("cfei_qty_light")))
            record_base = record_base.replace("{cfei_qty_range}", fmt_qty(r.get("cfei_qty_range")))
            record_base = record_base.replace("{cfei_qty_acu}", fmt_qty(r.get("cfei_qty_acu")))
            record_base = record_base.replace("{cfei_qty_switch}", fmt_qty(r.get("cfei_qty_switch")))
            record_base = record_base.replace("{cfei_qty_motor}", fmt_qty(r.get("cfei_qty_motor")))
            record_base = record_base.replace("{cfei_qty_misc}", fmt_qty(r.get("cfei_qty_misc")))
            record_base = record_base.replace("{cfei_qty_conv}", fmt_qty(r.get("cfei_qty_conv")))
            record_base = record_base.replace("{cfei_qty_bell}", fmt_qty(r.get("cfei_qty_bell")))
            c_oth = str(r.get("cfei_qty_others") or "")
            if not c_oth.strip() or c_oth.strip().upper() == "NONE":
                c_oth = "&nbsp;"
            record_base = record_base.replace("{cfei_qty_others}", c_oth)
        record_base = record_base.replace("{wp_number}", wp_number)
        record_base = record_base.replace("{created_at}", formatted_date)
        record_base = record_base.replace("{applicant_name}", applicant_name)
        record_base = record_base.replace("{address_barangay}", address_barangay)
        record_base = record_base.replace("{bp_number}", bp_number)
        record_base = record_base.replace("{coo_number}", coo_number)
        record_base = record_base.replace("{remarks}", remarks_inline)
        record_base = record_base.replace("{installation}", inst)
        record_base = record_base.replace("{a_check}", a_check)
        record_base = record_base.replace("{b_check}", b_check)
        record_base = record_base.replace("{c_check}", c_check)
        record_base = record_base.replace("{d_check}", d_check)
        record_base = record_base.replace("{e_check}", e_check)
        record_base = record_base.replace("{f_check}", f_check)
        
        # --- FIX 5: REPLACE OCCUPANCY PLACEHOLDERS ---
        record_base = record_base.replace("{res_check}", res_check)
        record_base = record_base.replace("{comm_check}", comm_check)
        record_base = record_base.replace("{ind_check}", ind_check)
        record_base = record_base.replace("{inst_check}", inst_check)
        record_base = record_base.replace("{gov_check}", gov_check)
        
        # Stack 3 vertical pages per record (OBO, APPLICANT, CFEI)
        for copy_name in ["OBO COPY", "", "CFEI COPY"]:
            final_page = record_base.replace("{copy_label}", copy_name)
            
            # Inject Floating Red Stamp ONLY for non-applicant copies on Wiring Permit
            red_stamp_html = ""
            if copy_name != "" and record_type == "wp":
                units = str(r.get("wp_qty_units") or "1")
                occ = str(r.get("occupancy") or "RESIDENTIAL").upper()
                svc = str(r.get("wp_service_type") or "1Ø ELECTRICAL SERVICE").upper()
                red_stamp_html = f"""
                <div style="position: absolute; right: 0.8in; bottom: 2.0in; width: 3in; text-align: center; color: red; font-family: Arial, sans-serif; font-weight: bold; z-index: 100;">
                    <div style="font-size: 11pt;">{units} {occ} UNIT/S</div>
                    <div style="font-size: 11pt;">{svc}</div>
                    <div style="height: 0.25in;"></div>
                    <div style="font-size: 11pt;">{wp_number}</div>
                    <div style="font-size: 18pt; margin-top: 8px;">{copy_name}</div>
                </div>
                """
            
            certificates_html += f"""
            <div class="print-page-wrapper">
                {final_page}
                {red_stamp_html}
            </div>
            """
            
    # Determine the scale zoom factor dynamically (Wiring Permit needs a tighter shrink to prevent footer bleed)
    p_zoom = "0.85" if record_type == "wp" else "0.87"
        
    # Return the records wrapped inside a single master document with the dynamic title
    return f"""
    <html>
    <head>
        <title>{file_title}</title>
        <style>
            /* 1. PORTRAIT LEGAL / F4 PAPER PRINT FORMATTING */
            @media print {{
                @page {{
                    size: 8.5in 13in;
                    margin: 0;
                }}
                body {{
                    margin: 0;
                    padding: 0;
                    background-color: #ffffff;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }}
                .print-page-wrapper {{
                    width: 8.5in !important;
                    height: 13in !important;
                    position: relative !important;
                    page-break-inside: avoid;
                    break-inside: avoid;
                    page-break-after: always;
                    break-after: page;
                    padding: 0.3in 0.5in !important; /* Standard print safety padding */
                    box-sizing: border-box;
                    background-image: url("data:image/png;base64,{watermark_b64}") !important;
                    background-size: 100% 100% !important;
                    background-repeat: no-repeat !important;
                    background-position: center !important;
                }}
                .print-page-wrapper .page-footer-container {{
                    position: absolute !important;
                    bottom: 0.4in !important; /* Anchors content to background image footer scale */
                    left: 0.5in !important;
                    right: 0.5in !important;
                }}
            }}
            
            /* FLAT ON-SCREEN PREVIEW */
            body {{
                background-color: #ffffff;
                margin: 0;
                padding: 0;
            }}
            .print-page-wrapper {{
                background-color: #ffffff;
                margin: 0 auto;
                width: 100% !important;
                max-width: 8.5in !important;
                height: 13in !important;
                position: relative !important;
                padding: 0.3in 0.5in !important;
                box-sizing: border-box;
                border-bottom: 2px dashed #cccccc;
                background-image: url("data:image/png;base64,{watermark_b64}") !important;
                background-size: 100% 100% !important;
                background-repeat: no-repeat !important;
                background-position: center !important;
            }}
            .print-page-wrapper .page-footer-container {{
                position: absolute !important;
                bottom: 0.4in !important;
                left: 0.5in !important;
                right: 0.5in !important;
            }}
            .print-page-wrapper table {{
                width: 100% !important;
                zoom: {p_zoom}; /* Keeps screen preview layout identical to printed sheets */
                transform-origin: top center;
            }}
        </style>
    </head>
    <body>
        {certificates_html}
    </body>
    </html>
    """
@st.dialog("🖨️ Pre-Print Quantity Planner", width="large")
def quantity_planner_dialog(record_type):
    # --- CALLBACK FUNCTIONS ---
    def cb_apply_master():
        to_move = []
        for r in list(st.session_state.print_pending):
            if st.session_state.get(f"chk_{r['id']}", False):
                if record_type == "wp":
                    r['qty_main_switch'] = st.session_state.mst_ms
                    r['qty_socket'] = st.session_state.mst_s
                    r['qty_conv_outlet'] = st.session_state.mst_co
                    r['qty_switch'] = st.session_state.mst_sw
                    r['qty_others'] = st.session_state.mst_oth
                    r['wp_qty_units'] = st.session_state.mst_units
                    r['wp_service_type'] = st.session_state.mst_svct
                else:
                    r['cei_number'] = st.session_state.mst_cei
                    r['cfei_switchboard_qty'] = st.session_state.mst_swb
                    r['cfei_meter_qty'] = st.session_state.mst_mtr
                    r['cfei_service_type'] = st.session_state.mst_srv
                    r['cfei_wiring_method'] = st.session_state.mst_wir
                    
                    r['cfei_qty_light'] = st.session_state.mst_lgt
                    r['cfei_qty_range'] = st.session_state.mst_rng
                    r['cfei_qty_acu'] = st.session_state.mst_acu
                    r['cfei_qty_switch'] = st.session_state.mst_csw
                    r['cfei_qty_motor'] = st.session_state.mst_mtr_qty
                    r['cfei_qty_misc'] = st.session_state.mst_msc
                    r['cfei_qty_conv'] = st.session_state.mst_ccv
                    r['cfei_qty_bell'] = st.session_state.mst_bel
                    r['cfei_qty_others'] = st.session_state.mst_coth
                to_move.append(r)
        for r in to_move:
            st.session_state.print_pending.remove(r)
            st.session_state.print_ready.append(r)
            st.session_state[f"chk_{r['id']}"] = False

    def cb_select_all(val):
        for r in st.session_state.print_pending:
            st.session_state[f"chk_{r['id']}"] = val

    def cb_done(r_id):
        r = next(item for item in st.session_state.print_pending if item["id"] == r_id)
        if record_type == "wp":
            r['qty_main_switch'] = st.session_state[f"ims_{r_id}"]
            r['qty_socket'] = st.session_state[f"is_{r_id}"]
            r['qty_conv_outlet'] = st.session_state[f"ico_{r_id}"]
            r['qty_switch'] = st.session_state[f"isw_{r_id}"]
            r['qty_others'] = st.session_state[f"ioth_{r_id}"]
            r['wp_qty_units'] = st.session_state[f"iuni_{r_id}"]
            r['wp_service_type'] = st.session_state[f"isvc_{r_id}"]
        else:
            r['cei_number'] = st.session_state[f"icei_{r_id}"]
            r['cfei_switchboard_qty'] = st.session_state[f"iswb_{r_id}"]
            r['cfei_meter_qty'] = st.session_state[f"imtr_qty_{r_id}"]
            r['cfei_service_type'] = st.session_state[f"isrv_{r_id}"]
            r['cfei_wiring_method'] = st.session_state[f"iwir_{r_id}"]
            
            r['cfei_qty_light'] = st.session_state[f"ilgt_{r_id}"]
            r['cfei_qty_range'] = st.session_state[f"irng_{r_id}"]
            r['cfei_qty_acu'] = st.session_state[f"iacu_{r_id}"]
            r['cfei_qty_switch'] = st.session_state[f"icsw_{r_id}"]
            r['cfei_qty_motor'] = st.session_state[f"imtr_val_{r_id}"]
            r['cfei_qty_misc'] = st.session_state[f"imsc_{r_id}"]
            r['cfei_qty_conv'] = st.session_state[f"iccv_{r_id}"]
            r['cfei_qty_bell'] = st.session_state[f"ibel_{r_id}"]
            r['cfei_qty_others'] = st.session_state[f"icoth_{r_id}"]
            
        st.session_state.print_pending.remove(r)
        st.session_state.print_ready.append(r)
        st.session_state[f"chk_{r_id}"] = False

    def cb_undo(r_id):
        r = next(item for item in st.session_state.print_ready if item["id"] == r_id)
        st.session_state.print_ready.remove(r)
        st.session_state.print_pending.append(r)

    # UI RENDERING
    if record_type == "wp":
        st.markdown("### ⚡ Master Quantity Override")
        cols = st.columns(6)
        cols[0].number_input("Main Switch", value=1, min_value=0, key="mst_ms")
        cols[1].number_input("Sockets", value=4, min_value=0, key="mst_s")
        cols[2].number_input("Conv. Outlet", value=4, min_value=0, key="mst_co")
        cols[3].number_input("Switches", value=4, min_value=0, key="mst_sw")
        cols[4].text_input("Others", value="", key="mst_oth")
        cols[5].write("##"); cols[5].button("✔️ Apply", type="primary", use_container_width=True, on_click=cb_apply_master)
        
        m_col1, m_col2, _ = st.columns([1.5, 2.5, 2])
        m_col1.number_input("Units (Checklist)", value=1, min_value=1, key="mst_units")
        m_col2.text_input("Service Type (Checklist)", value="1Ø ELECTRICAL SERVICE", key="mst_svct")
    else:
        st.markdown("### 🏢 Master Load Override")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.text_input("CEI No.", value="", key="mst_cei")
        m2.number_input("Light", value=4, min_value=0, key="mst_lgt")
        m3.number_input("Range", value=0, min_value=0, key="mst_rng")
        m4.number_input("A.C.U.", value=0, min_value=0, key="mst_acu")
        m5.number_input("T.Switch", value=4, min_value=0, key="mst_csw")
        m6.button("✔️ Apply", type="primary", use_container_width=True, on_click=cb_apply_master)
        
        m7, m8, m9, m10, m11, m12 = st.columns(6)
        m7.number_input("Motor", value=0, min_value=0, key="mst_mtr_qty")
        m8.number_input("Misc", value=0, min_value=0, key="mst_msc")
        m9.number_input("Conv", value=4, min_value=0, key="mst_ccv")
        m10.number_input("Bell Tel", value=0, min_value=0, key="mst_bel")
        m11.text_input("Others", value="", key="mst_coth")
        
        m13, m14, m15, m16, _ = st.columns([1, 1, 2, 2, 0.5])
        m13.text_input("Switchboard Qty", value="", key="mst_swb")
        m14.text_input("Meter Qty", value="1", key="mst_mtr")
        m15.text_input("Service Type", value="Single Phase", key="mst_srv")
        m16.text_input("Wiring Method", value="CONCEALED WIRING INSTALLATION", key="mst_wir")

    st.markdown("---")
    st.markdown("### 📋 Pending Review Queue")
    
    if not st.session_state.print_pending:
        st.success("✓ All records primed! You can now proceed to print below.")
    else:
        act1, act2, act3 = st.columns([1, 1, 2])
        act1.button("☑️ Select All", use_container_width=True, on_click=cb_select_all, args=(True,))
        act2.button("☐ Deselect All", use_container_width=True, on_click=cb_select_all, args=(False,))
        is_expanded = act3.toggle("🔽 Expand All Details", key="expand_all")
        st.write("")
        
        for r in st.session_state.print_pending:
            row_col1, row_col2 = st.columns([0.5, 11.5])
            with row_col1:
                st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
                st.checkbox("Sel", key=f"chk_{r['id']}", label_visibility="collapsed")
            with row_col2:
                with st.expander(f"📝 {r['applicant_name']} ({'WP' if record_type == 'wp' else 'CFEI'}: {r.get('wp_number','')})", expanded=is_expanded):
                    if record_type == "wp":
                        # Initialize WP State Keys safely
                        for k, v in [
                            (f"ims_{r['id']}", r.get('qty_main_switch', 1) if r.get('qty_main_switch', 1) is not None else 1),
                            (f"is_{r['id']}", r.get('qty_socket', 4) if r.get('qty_socket', 4) is not None else 4),
                            (f"ico_{r['id']}", r.get('qty_conv_outlet', 4) if r.get('qty_conv_outlet', 4) is not None else 4),
                            (f"isw_{r['id']}", r.get('qty_switch', 4) if r.get('qty_switch', 4) is not None else 4),
                            (f"ioth_{r['id']}", r.get('qty_others', "") or ""),
                            (f"iuni_{r['id']}", int(r.get('wp_qty_units', 1) or 1)),
                            (f"isvc_{r['id']}", r.get('wp_service_type', "1Ø ELECTRICAL SERVICE") or "1Ø ELECTRICAL SERVICE")
                        ]:
                            if k not in st.session_state:
                                st.session_state[k] = v

                        sc1, sc2, sc3, sc4, sc5 = st.columns([1, 1, 1, 1, 1.5])
                        sc1.number_input("Main", min_value=0, key=f"ims_{r['id']}")
                        sc2.number_input("Sock", min_value=0, key=f"is_{r['id']}")
                        sc3.number_input("Conv", min_value=0, key=f"ico_{r['id']}")
                        sc4.number_input("Swit", min_value=0, key=f"isw_{r['id']}")
                        sc5.text_input("Others", key=f"ioth_{r['id']}")
                        
                        sd1, sd2, sd3 = st.columns([1, 2, 1])
                        sd1.number_input("Units", min_value=1, key=f"iuni_{r['id']}")
                        sd2.text_input("Service Type", key=f"isvc_{r['id']}")
                        sd3.write("##")
                        sd3.button("Done", key=f"done_{r['id']}", use_container_width=True, on_click=cb_done, args=(r['id'],))
                    else:
                        # Initialize CFEI State Keys safely
                        for k, v in [
                            (f"icei_{r['id']}", r.get('cei_number', "") or ""),
                            (f"ilgt_{r['id']}", r.get('cfei_qty_light', 4) if r.get('cfei_qty_light', 4) is not None else 4),
                            (f"irng_{r['id']}", r.get('cfei_qty_range', 0) if r.get('cfei_qty_range', 0) is not None else 0),
                            (f"iacu_{r['id']}", r.get('cfei_qty_acu', 0) if r.get('cfei_qty_acu', 0) is not None else 0),
                            (f"icsw_{r['id']}", r.get('cfei_qty_switch', 4) if r.get('cfei_qty_switch', 4) is not None else 4),
                            (f"imtr_val_{r['id']}", r.get('cfei_qty_motor', 0) if r.get('cfei_qty_motor', 0) is not None else 0),
                            (f"imsc_{r['id']}", r.get('cfei_qty_misc', 0) if r.get('cfei_qty_misc', 0) is not None else 0),
                            (f"iccv_{r['id']}", r.get('cfei_qty_conv', 4) if r.get('cfei_qty_conv', 4) is not None else 4),
                            (f"ibel_{r['id']}", r.get('cfei_qty_bell', 0) if r.get('cfei_qty_bell', 0) is not None else 0),
                            (f"icoth_{r['id']}", r.get('cfei_qty_others', "") or ""),
                            (f"iswb_{r['id']}", r.get('cfei_switchboard_qty', "") or ""),
                            (f"imtr_qty_{r['id']}", r.get('cfei_meter_qty', "1") or "1"),
                            (f"isrv_{r['id']}", r.get('cfei_service_type', "Single Phase") or "Single Phase"),
                            (f"iwir_{r['id']}", r.get('cfei_wiring_method', "CONCEALED WIRING INSTALLATION") or "CONCEALED WIRING INSTALLATION")
                        ]:
                            if k not in st.session_state:
                                st.session_state[k] = v

                        c1, c2, c3, c4, c5 = st.columns(5)
                        c1.text_input("CEI No.", key=f"icei_{r['id']}")
                        c2.number_input("Light", min_value=0, key=f"ilgt_{r['id']}")
                        c3.number_input("Range", min_value=0, key=f"irng_{r['id']}")
                        c4.number_input("A.C.U.", min_value=0, key=f"iacu_{r['id']}")
                        c5.number_input("T.Switch", min_value=0, key=f"icsw_{r['id']}")
                        
                        c7, c8, c9, c10, c11 = st.columns(5)
                        c7.number_input("Motor", min_value=0, key=f"imtr_val_{r['id']}")
                        c8.number_input("Misc", min_value=0, key=f"imsc_{r['id']}")
                        c9.number_input("Conv", min_value=0, key=f"iccv_{r['id']}")
                        c10.number_input("Bell", min_value=0, key=f"ibel_{r['id']}")
                        c11.text_input("Others", key=f"icoth_{r['id']}")
                        
                        c12, c13, c14, c15, c16 = st.columns([1, 1, 2, 2, 1.2])
                        c12.text_input("Switchboard Qty", key=f"iswb_{r['id']}")
                        c13.text_input("Meter Qty", key=f"imtr_qty_{r['id']}")
                        c14.text_input("Service Type", key=f"isrv_{r['id']}")
                        c15.text_input("Wiring Method", key=f"iwir_{r['id']}")
                        c16.write("##")
                        c16.button("Done", key=f"done_{r['id']}", use_container_width=True, on_click=cb_done, args=(r['id'],))

    if st.session_state.print_ready:
        st.markdown("---")
        with st.expander(f"🟢 Ready to Print ({len(st.session_state.print_ready)} items)", expanded=True):
            for r in st.session_state.print_ready:
                cols = st.columns([5, 1])
                cols[0].write(f"✓ **{r['applicant_name']}** ({r.get('wp_number','')}) - Primed")
                cols[1].button("↩️ Undo", key=f"undo_{r['id']}", use_container_width=True, on_click=cb_undo, args=(r['id'],))
                    
        if not st.session_state.print_pending:
            if st.button("🖨️ Save Quantities & Open Print Dialog", type="primary", use_container_width=True):
                with database.get_db() as db:
                    ModelClass = database.WiringPermitRecord if record_type == "wp" else database.MainRecord
                    for r in st.session_state.print_ready:
                        db_rec = db.query(ModelClass).filter(ModelClass.id == r['id']).first()
                        if db_rec:
                            if record_type == "wp":
                                db_rec.qty_main_switch = r['qty_main_switch']
                                db_rec.qty_socket = r['qty_socket']
                                db_rec.qty_conv_outlet = r['qty_conv_outlet']
                                db_rec.qty_switch = r['qty_switch']
                                db_rec.qty_others = r['qty_others']
                                db_rec.wp_qty_units = r['wp_qty_units']
                                db_rec.wp_service_type = r['wp_service_type']
                            else:
                                db_rec.cei_number = r['cei_number']
                                db_rec.cfei_switchboard_qty = r['cfei_switchboard_qty']
                                db_rec.cfei_meter_qty = r['cfei_meter_qty']
                                db_rec.cfei_service_type = r['cfei_service_type']
                                db_rec.cfei_wiring_method = r['cfei_wiring_method']
                                
                                db_rec.cfei_qty_light = r['cfei_qty_light']
                                db_rec.cfei_qty_range = r['cfei_qty_range']
                                db_rec.cfei_qty_acu = r['cfei_qty_acu']
                                db_rec.cfei_qty_switch = r['cfei_qty_switch']
                                db_rec.cfei_qty_motor = r['cfei_qty_motor']
                                db_rec.cfei_qty_misc = r['cfei_qty_misc']
                                db_rec.cfei_qty_conv = r['cfei_qty_conv']
                                db_rec.cfei_qty_bell = r['cfei_qty_bell']
                                db_rec.cfei_qty_others = r['cfei_qty_others']
                
                st.session_state.print_html_payload = generate_print_html(st.session_state.print_ready, record_type)
                st.session_state.print_title_payload = f"Export_{len(st.session_state.print_ready)}_Records"
                st.session_state.print_pending = []
                st.session_state.print_ready = []
                st.rerun()

# [EXECUTE PRINT OUTSIDE DIALOG SANDBOX]
if st.session_state.get("print_html_payload"):
    st.iframe(f"""
    <iframe srcdoc="{st.session_state.print_html_payload.replace('"', '&quot;')}" style="display:none;" onload="this.contentWindow.focus(); this.contentWindow.print();"></iframe>
    <!-- {datetime.now(timezone.utc).timestamp()} -->
    """, height=1)
    st.session_state.print_html_payload = None

def file_to_base64(uploaded_file):
    if uploaded_file is not None:
        bytes_data = uploaded_file.read()
        encoded = base64.b64encode(bytes_data).decode("utf-8")
        return encoded
    return None

# ==========================================
# 3. LOGIN INTERFACE (NO SIGN-UP ALLOWED)
# ==========================================
if st.session_state.user is None:
    st.markdown("<h1 style='text-align: center;'>🔐 Secure Database Portal</h1>", unsafe_allow_html=True)
    # FIXED: Centered the login description text nicely to match the header
    st.markdown("<div style='text-align: center; color: gray; margin-bottom: 20px;'>Please enter your system administrator-provided credentials to access the secure records.</div>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Authenticate Connection")

            if submit:
                user_session = auth.authenticate_user(username, password)
                if user_session:
                    st.session_state.user = user_session
                            
                    # CRITICAL FIX: Destroy any lingering offline kick files so they don't get booted instantly
                    import cloud_sync
                    cloud_sync.check_and_consume_kick(username)
                            
                    st.success("Authorized! Redirecting...")
                    st.rerun()
                else:
                    st.error("Access Denied: Invalid credentials.")
    st.stop()


# ==========================================
# 4. MAIN SYSTEM DASHBOARD
# ==========================================
user = st.session_state.user

if os.path.exists("system_lock.txt") and user:
    is_root_user = (user["username"] == "admin")
    if not is_root_user:
        # Instantly wipe any decrypted signature IDs from the active session state
        st.session_state.unblurred_id = None

form_key = st.session_state.form_id  # Unique suffix used to completely clear forms

# Sidebar Profile & Logout
st.sidebar.markdown(f"### 👤 Logged In: `{user['username']}`")

# Render active merger and network status indicators
import cloud_sync

is_leader = cloud_sync.is_active_merger()

# Safely read GDrive state from our background thread's fast memory flag (0.01ms)
network_merger_alive = cloud_sync.NETWORK_MERGER_ALIVE

# Check if any active user on this specific local server has admin credentials
has_local_admin = cloud_sync.is_any_session_admin()

if is_leader:
    st.sidebar.markdown(f"**Role:** `{user['role']}`  \n🟢 *(Active Consolidation Server)*")
elif network_merger_alive:
    st.sidebar.markdown(f"**Role:** `{user['role']}`  \n🟡 *(Cloud Merger active on another PC)*")
elif cloud_sync.SYNC_ACTIVE and not has_local_admin:
    st.sidebar.markdown(f"**Role:** `{user['role']}`  \n🔴 *(No Active Merger - Viewer Accounts Only)*")
else:
    st.sidebar.markdown(f"**Role:** `{user['role']}`  \n⚪ *(Local/Offline Mode)*")# Global Financial Master Toggle (Allows users to completely hide/show financial tools)
show_financials = st.sidebar.toggle("💰 Enable Financial Ledger", value=st.session_state.get("show_financials", False))
st.session_state["show_financials"] = show_financials

# Master Registry Selector
st.sidebar.markdown("---")
st.sidebar.markdown("### 🌐 Synchronization Center")

import cloud_sync
if cloud_sync.SYNC_ACTIVE:
    st.sidebar.success("🟢 **Cloud Sync Connected**")
else:
    st.sidebar.info("⚪ **Local / Offline Mode**")

# INTELLECTUAL DATABASE RECONCILIATION STATUS
import cloud_sync
sync_status = cloud_sync.get_db_sync_status()

if sync_status == "OFFLINE":
    st.sidebar.info("📂 **Database: Local Copy Only**")
elif sync_status == "PENDING_MERGE":
    st.sidebar.warning("⏳ **Database: Merging Changes...**")
elif sync_status == "FAILED_RECONCILE":
    st.sidebar.warning("⚠️ **Database: Out-of-Sync / Pending**")
elif sync_status == "SYNCED":
    st.sidebar.success("🔄 **Database: Synced & Current**")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📂 Active Database Table")

# Restores the active registry if Streamlit's fragment garbage collector wiped it
if "active_registry_selection" not in st.session_state:
    st.session_state.active_registry_selection = st.session_state.persistent_active_registry

def cb_registry_change():
    st.session_state.persistent_active_registry = st.session_state.active_registry_selection

# Dynamically calculate the index from state to prevent Streamlit from resetting selections on reloads
registry_options = ["🏢 CFEI Records", "⚡ Wiring Permits"]
saved_registry = st.session_state.get("persistent_active_registry", "🏢 CFEI Records")
default_index = registry_options.index(saved_registry) if saved_registry in registry_options else 0

st.sidebar.radio(
        "Select Target Registry:",
        registry_options,
        index=default_index,
        key="active_registry_selection",
        on_change=cb_registry_change
)
    
# FORCE the app to use our persistent state, ignoring Streamlit's temporary widget amnesia during reruns
strict_registry = st.session_state.get("persistent_active_registry", "🏢 CFEI Records")
record_type = "wp" if strict_registry == "⚡ Wiring Permits" else "cfei"

# Wipes old selection cache when flipping between WP and CFEI
if st.session_state.get("last_record_type") != record_type:
    st.session_state.last_record_type = record_type
    st.session_state.active_select_id = None
    st.session_state.bulk_edit_active = False
    st.session_state.bulk_edit_ids = []
    st.session_state.bulk_edit_index = 0
    st.session_state.selected_uuids = set() # Clears Set Math basket

if st.sidebar.button("Secure Logout", type="primary"): 
    # --- FIX 16: INSTANT MERGER RELEASE ON ADMINISTRATIVE LOGOUT [16] ---
    import cloud_sync
    sess_id = st.session_state.get("session_node_id", uuid.uuid4().hex)
    cloud_sync.deregister_session(sess_id)
    if not cloud_sync.is_any_session_admin() and cloud_sync.AM_I_LEADER:
        cloud_sync.release_main_server_turf()
        
    st.session_state.user = None
    st.rerun()
st.title("📂 Enterprise Record Registry")

# [SCREAMING BANNER] Automatically locked to the top of every tab when the Root Admin triggers the freeze
if os.path.exists("system_lock.txt"):
    st.markdown(
        """
        <div style="background-color: #ff4b4b; padding: 15px; border-radius: 5px; margin-bottom: 20px; border: 2px solid darkred;">
            <h3 style="color: white; margin: 0; text-align: center;"> 🚨 CRITICAL SYSTEM WARNING: DATABASE LOCKDOWN ACTIVE 🚨 </h3>
            <p style="color: white; margin: 5px 0 0 0; text-align: center; font-size: 1.1em;">
                The database has been frozen in <b>READ-ONLY MODE</b> by the Root Administrator. All records, additions, modifications, and deletions are locked.
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

# Granular tabs based on role permissions
tab_list = ["Records Directory", "Add / Bulk Import Records"]
if auth.check_permission(user["role"], "can_view_logs"):
    tab_list.append("Audit Action Logs")
if auth.check_permission(user["role"], "can_manage_users"):
    tab_list.append("User Accounts Admin")

# Dynamic Screaming Header Banners to prevent operator eyestrain errors
if record_type == "wp":
    st.markdown(
        """
        <div style="background-color: #ff9800; padding: 12px; border-radius: 5px; margin-bottom: 15px; border: 2px solid #e65100;">
            <h3 style="color: black; margin: 0; text-align: center;">⚡ ACTIVE DATABASE: WIRING PERMITS REGISTRY ⚡</h3>
            <p style="color: black; margin: 3px 0 0 0; text-align: center; font-size: 0.95em; font-weight: bold;">
                All directory searches, modifications, and new submissions will operate EXCLUSIVELY on the Wiring Permits table.
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )
else:
    st.markdown(
        """
        <div style="background-color: #1e88e5; padding: 12px; border-radius: 5px; margin-bottom: 15px; border: 2px solid #0d47a1;">
            <h3 style="color: white; margin: 0; text-align: center;">🏢 ACTIVE DATABASE: CFEI RECORDS REGISTRY 🏢</h3>
            <p style="color: white; margin: 3px 0 0 0; text-align: center; font-size: 0.95em; font-weight: bold;">
                All directory searches, modifications, and new submissions will operate EXCLUSIVELY on the CFEI Records table.
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

tabs = st.tabs(tab_list)


# ------------------------------------------
# TAB 1: RECORDS DIRECTORY (MULTI-SELECT, BULK EDIT, BULK DELETE)
# ------------------------------------------
with tabs[0]:
    # Always fetch raw items at the top of the tab so they are available to filters, directory, single edit, and bulk edit wizard
    all_raw_items = data_manager.search_records(include_hidden=True, record_type=record_type)
    selected_rows = []

    if not st.session_state.bulk_edit_active:
        st.subheader("Data Directory")
        st.markdown("<p style='font-size: 0.9em; color: gray;'>Pro-tip: Hold 'Ctrl' or 'Shift' to select multiple rows at once for guided bulk edits or deletions.</p>", unsafe_allow_html=True)

        # 2. BUILD POPULARITY-SORTED AND ALPHABETICAL DROPDOWNS (WITH NO-DUPLICATE FALLBACKS)
        # A. Barangay Options
        db_barangays = [item["barangay"] for item in all_raw_items if item["barangay"]]
        brgy_counts = Counter(db_barangays)
        sorted_brgys = [f"{brgy} ({count} entries)" for brgy, count in brgy_counts.most_common()]
        default_brgys = [
            "AMAYA I", "AMAYA II", "AMAYA III", "AMAYA IV", "AMAYA V", "AMAYA VI", "AMAYA VII", "AMAYA VI-VII", 
            "DAANG AMAYA I", "DAANG AMAYA II", "DAANG AMAYA III", "BAGTAS", "BIGA", "BIWAS", "BUCAL", "BUNGA", 
            "CALIBUYO", "CAPIPISA", "HALAYHAY", "HALAYHAY/SAHUD-ULAN", "SAHUD-ULAN", "JULUGAN I", "JULUGAN II", 
            "JULUGAN III", "JULUGAN IV", "JULUGAN V", "JULUGAN VI", "JULUGAN VII", "JULUGAN VIII", "LAMBINGAN", 
            "MULAWIN", "SANJA MAYOR", "SANTOL", "TANAUAN", "TRES CRUSES", "POBLACION I", "POBLACION II", 
            "POBLACION III", "POBLACION IV", "PARADAHAN I", "PARADAHAN II", "PUNTA I", "PUNTA II"
        ]
        raw_brgys_in_db = [b.rsplit(" (", 1)[0] for b in sorted_brgys]
        brgy_defaults_clean = [b for b in default_brgys if b not in raw_brgys_in_db]
        barangay_options = ["All Barangays"] + sorted_brgys + brgy_defaults_clean

        # B. Occupancy Options
        db_occupancies = [item["occupancy"] for item in all_raw_items if item["occupancy"]]
        occ_counts = Counter(db_occupancies)
        sorted_occs = [f"{occ} ({count} entries)" for occ, count in occ_counts.most_common()]
        default_occs = ["COMMERCIAL", "GOVERNMENT", "INDUSTRIAL", "INSTITUTIONAL", "RESIDENTIAL"]
        raw_occs_in_db = [o.rsplit(" (", 1)[0] for o in sorted_occs]
        occ_defaults_clean = [o for o in default_occs if o not in raw_occs_in_db]
        occupancy_options = ["All Occupancy Types"] + sorted_occs + occ_defaults_clean

        # C. Installation Options
        db_installations = [item["installation"] for item in all_raw_items if item["installation"]]
        inst_counts = Counter(db_installations)
        sorted_insts = [f"{inst} ({count} entries)" for inst, count in inst_counts.most_common()]
        default_insts = ["NEW", "RECONNECTION", "RELOCATION", "REMODEL", "SEPARATION", "TEMPORARY", "UPGRADING", "NET METERING"]
        raw_insts_in_db = [i.rsplit(" (", 1)[0] for i in sorted_insts]
        inst_defaults_clean = [i for i in default_insts if i not in raw_insts_in_db]
        installation_options = ["All Installation Types"] + sorted_insts + inst_defaults_clean

        # 3. UNIFIED SEARCH BAR INTERFACE (ONLY ONE MAIN TEXT INPUT TO TYPE WORDS IN)
        search_query = st.text_input(
            "🔍 Universal Search Registry (Press Enter)",
            value=st.session_state.search_query_val,
            placeholder="Type name, barangay, installation... (e.g., JUAN, AMAYA, NEW)"
        )
        st.caption("💡 **Advanced Search Rules:** Use `,` for AND logic (must match all), `|` for OR logic (matches any), and `\"quotes\"` for exact phrases (e.g., `\"JUAN DELA CRUZ\", AMAYA | BAGTAS`).")

        # 4. RESTORED CATEGORY DROPDOWN FILTERS
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
        with filter_col1:
            selected_brgy_disp = st.selectbox("📍 Filter by Barangay (Searchable)", barangay_options)
            selected_brgy = "All Barangays" if selected_brgy_disp == "All Barangays" else selected_brgy_disp.rsplit(" (", 1)[0]
        with filter_col2:
            selected_occ_disp = st.selectbox("🏢 Filter by Occupancy Type", occupancy_options)
            selected_occ = "All Occupancy Types" if selected_occ_disp == "All Occupancy Types" else selected_occ_disp.rsplit(" (", 1)[0]
        with filter_col3:
            selected_inst_disp = st.selectbox("⚡ Filter by Installation Type", installation_options)
            selected_inst = "All Installation Types" if selected_inst_disp == "All Installation Types" else selected_inst_disp.rsplit(" (", 1)[0]
        with filter_col4:
            db_batches = sorted(list(set([item.get("import_batch_id") for item in all_raw_items if item.get("import_batch_id")])))
            selected_batch = st.selectbox("📦 Filter by Import Batch", ["All Batches"] + db_batches)

        # 5. CONTROL BAR LAYOUT
        ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1.5, 2, 1])

        with ctrl_col1:
            st.write("") # spacing offset
        
        # Restores the archive toggle if Streamlit's fragment garbage collector wiped it
            if "persistent_show_archived" not in st.session_state:
                st.session_state.persistent_show_archived = False
            if "show_archived_val" not in st.session_state:
                st.session_state.show_archived_val = st.session_state.persistent_show_archived

            def cb_show_archived():
                st.session_state.persistent_show_archived = st.session_state.show_archived_val

            st.checkbox("   Include Hidden/Archived Records in Search",
                        key="show_archived_val", 
                        on_change=cb_show_archived)
        
            # FORCE the app to use our persistent state, ignoring Streamlit's temporary widget amnesia
            strict_show_archived = st.session_state.get("persistent_show_archived", False)

        with ctrl_col2:
            if st.session_state.get("show_financials", True):
                tally_period = st.selectbox("📅 OR Audit Tally", ["All Time", "This Month", "This Year", "Custom Range"], key="tally_period_select")
                tally_category = st.selectbox("🏷️ Tally Category", ["All Categories", "R - RESIDENTIAL", "F - FENCING", "C - COMMERCIAL", "ID - INDUSTRIAL", "E - ELECTRICAL", "IT - INSTITUTIONAL"], key="tally_category_select")
                from_month_idx, from_year, to_month_idx, to_year = 1, 2026, 12, 2026
                range_valid = True

                if tally_period == "Custom Range":
                    months = ["January", "February", "March", "April", "May", "June", "July",
                              "August", "September", "October", "November", "December"]
                    years = list(range(2020, 2031))
                    r_col1, r_col2 = st.columns(2)
                    with r_col1:
                        f_m = st.selectbox("From Month", months, index=0)
                        from_month_idx = months.index(f_m) + 1
                        from_year = st.selectbox("From Year", years, index=years.index(2026))
                    with r_col2:
                        t_m = st.selectbox("To Month", months, index=datetime.now().month - 1)
                        to_month_idx = months.index(t_m) + 1
                        to_year = st.selectbox("To Year", years, index=years.index(2026))
                    if (from_year * 12 + from_month_idx) > (to_year * 12 + to_month_idx):
                        st.markdown('<p style="color:red; font-size:0.85em; margin-top:-5px;">❌ Invalid Range!</p>', unsafe_allow_html=True)
                        range_valid = False
            else:
                range_valid = False
            
    # Calculate Audits & Revenue metrics dynamically from active dataset
        paid_sum = 0.0
        unpaid_sum = 0.0
        paid_count = 0
        unpaid_records = []
        missing_cost_records = []
        legacy_records = []

        if st.session_state.get("show_financials", True) and range_valid:
            today = datetime.now(PHT).date()
            for item in all_raw_items:
                # Filter by dynamic BP prefix if a specific category is selected
                bp_num = item.get("bp_number") or ""
                if tally_category != "All Categories":
                    prefix_code = tally_category.split(" - ")[0]
                    cat_name = tally_category.split(" - ")[1].strip().upper()
                    occ = (item.get("occupancy") or "").upper()
                    
                    # Matches if BP starts with prefix OR if Occupancy matches the category name
                    if not (bp_num.upper().startswith(prefix_code + "-") or occ == cat_name):
                        continue
                # --- FIX 13: UNIFIED & CRASH-PROOF DATE EXTRACTOR [8, 10] ---
                # Defensive casting protects against SQL NULL (None) values crashing re.search [8, 10]
                wp_num = str(item.get("wp_number") or "").strip().upper()
                bp_num = str(item.get("bp_number") or "").strip().upper()
                
                import re
                # Prioritize B.P. numbers on BOTH registries since category fees are tied to B.P.
                date_match = re.search(r'-(\d{2})-(\d{2})-', bp_num)
                if not date_match:
                    # Fall back to checking W.P. if B.P. is legacy or missing
                    date_match = re.search(r'-(\d{2})-(\d{2})-', wp_num)
                
                if date_match:
                    item_month = int(date_match.group(1))
                    item_year = 2000 + int(date_match.group(2))
                    item_date = datetime(item_year, item_month, 1).date()
                else:
                    # Catch legacy records lacking modern date sequences
                    legacy_records.append(item)
                    continue

                is_match = False

                if tally_period == "All Time":
                    is_match = True
                elif tally_period == "This Month" and item_year == today.year and item_month == today.month:
                    is_match = True
                elif tally_period == "This Year" and item_year == today.year:
                    is_match = True
                elif tally_period == "Custom Range":
                    from_val = from_year * 12 + from_month_idx
                    to_val = to_year * 12 + to_month_idx
                    item_val = item_year * 12 + item_month
                    if from_val <= item_val <= to_val:
                        is_match = True
                        
                if is_match:
                    or_val = item.get("or_number")
                    cost_val = item.get("total_cost") or 0.0
                    is_paid = or_val and isinstance(or_val, str) and or_val.strip() and or_val.strip().upper() != "NONE"
                    
                    if is_paid:
                        paid_sum += float(cost_val)
                        paid_count += 1
                    else:
                        unpaid_sum += float(cost_val)
                        unpaid_records.append(item)
                        
                    if float(cost_val) <= 0.0:
                        missing_cost_records.append(item)
                        
        # Render non-cluttered financial overview metrics with both Sum and Count
        if st.session_state.get("show_financials", True):
            if len(unpaid_records) > 0 or len(missing_cost_records) > 0:
                st.markdown(f"**Tally: `₱{paid_sum:,.2f}` Collected (`{paid_count}` Paid)** | ₱{unpaid_sum:,.2f} Pending ⚠️ *Partial Tally*")
            else:
                st.markdown(f"**Tally: `₱{paid_sum:,.2f}` Collected (`{paid_count}` Paid)** ✅ *Max Tallied*")

        if legacy_records:
            # Since both track B.P. first, show both examples in the warning
            with st.expander(f"⚠️ Action Required: {len(legacy_records)} Legacy / Monthless Records Excluded"):
                st.error("The following records lack a modern month-year sequence (e.g., R-MM-YY-0000 or WP-MM-YY-0000) and cannot be accurately tallied. Please modify and modernize their sequences to include them.")
                for l_item in legacy_records:
                    st.write(f"- UUID `{l_item['id']}` ({l_item['applicant_name']}) — WP: `{l_item.get('wp_number') or 'None'}` | BP: `{l_item.get('bp_number') or 'None'}`")

        # Render interactive expandable compliance list to prevent visual clutter
        if len(unpaid_records) > 0 or len(missing_cost_records) > 0:
            with st.expander("🔍 Show Pending Receipts / Missing Costs Details"):
                    if unpaid_records:
                        st.markdown("**Pending / Unpaid Permits:**")
                        for r_item in unpaid_records:
                            st.write(f"- UUID #{r_item['id']} ({r_item['applicant_name']}) — BP: `{r_item['bp_number'] or 'None'}`")
                    if missing_cost_records:
                        st.markdown("**Permits Missing Cost Valuation:**")
                        for c_item in missing_cost_records:
                            st.write(f"- UUID #{c_item['id']} ({c_item['applicant_name']}) — Cost: `₱0.00` / Unspecified")

        # Keep Sync & Refresh visible at all times, independent of financials setting
        with ctrl_col3:
            st.write("##")
            if st.button("🔄 Sync & Refresh", use_container_width=True, key="sync_dir_btn"):
                st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                st.toast("✓ Directory synced with server database.")
                st.rerun()

        # 6. RETRIEVE FILTERED PERMIT RECORDS FROM THE DATA MANAGER
        records_data = data_manager.search_records(search_query, selected_brgy,
        selected_occ, selected_inst, include_hidden=strict_show_archived, record_type=record_type)
        
        # Filter by Batch in Python (No database query overhead)
        if selected_batch != "All Batches":
            records_data = [r for r in records_data if r.get("import_batch_id") == selected_batch]

        # 5. SPELL SUGGESTION AUTOFILL SYSTEM
        if search_query and not records_data:
            all_names = list(set([item["applicant_name"] for item in all_raw_items if item["applicant_name"]]))
            matches = difflib.get_close_matches(search_query, all_names, n=1, cutoff=0.4)
            if matches:
                st.warning(f"No exact matches found. Did you mean: **{matches[0]}**?")
                if st.button(f"Auto-fill search with '{matches[0]}'"):
                    st.session_state.search_query_val = matches[0]
                    st.rerun()

        if not records_data:
            st.info("No permit records found matching current criteria.")
        else:
            df = pd.DataFrame(records_data)
            
            # Signatures are fully deactivated: exclude the raw base64 column entirely
            if "signature_base64" in df.columns:
                df_display = df.drop(columns=["signature_base64"])
            else:
                df_display = df.copy()

            # Map Active vs Archived status emojis for high visibility
            if "is_hidden" in df.columns:
                df_display["Status"] = df["is_hidden"].apply(
                    lambda x: "📁 Archived" if x else "🟢 Active"
                )
                df_display = df_display.drop(columns=["is_hidden"])
            else:
                df_display["Status"] = "🟢 Active"

            # Sequential column layout - completely removed obsolete "Signature" column
            cols_order = [
                "id", "Status", "wp_number", "applicant_name", "bp_number",
                "coo_number", "or_number", "total_cost", "remarks", "address", "barangay",
                "occupancy", "installation", "created_by", "created_at", "updated_at"
            ]
            if not st.session_state.get("show_financials", True):
                if "total_cost" in cols_order:
                    cols_order.remove("total_cost")
                    
            existing_cols = [c for c in cols_order if c in df_display.columns]
            df_display = df_display[existing_cols]

            # 6. EXHAUSTIVE COLUMN CAP-WIDTH CONFIGURATIONS
            column_configurations = {
                "id": st.column_config.TextColumn("UUID", width="medium"), # Swapped to TextColumn for UUID string
                "Status": st.column_config.TextColumn("Status", width="small"),
                "wp_number": st.column_config.TextColumn("WP Number", width="medium"),
                "applicant_name": st.column_config.TextColumn("Applicant Name", width="large"),
                "bp_number": st.column_config.TextColumn("Building Permit (B.P) Number", width="medium"),
                "coo_number": st.column_config.TextColumn("Cert. of Occupancy (C.O.O) Number", width="medium"),
                "or_number": st.column_config.TextColumn("Official Receipt (O.R.) Number", width="medium"),
                "total_cost": st.column_config.NumberColumn("Total Cost", format="₱%,.2f", width="medium"),
                "remarks": st.column_config.TextColumn("Remarks / Notes / Overrides", width="large"),
                "address": st.column_config.TextColumn("Physical Address", width="large"),
                "barangay": st.column_config.TextColumn("Barangay", width="medium"),
                "occupancy": st.column_config.TextColumn("Occupancy Type", width="medium"),
                "installation": st.column_config.TextColumn("Installation Type", width="medium"),
                "created_by": st.column_config.TextColumn("Recorded By", width="small"),
                "created_at": st.column_config.TextColumn("Timestamp", width="medium"),
                "updated_at": st.column_config.TextColumn("Last Modified", width="medium")
            }

            # Dynamic Table Sorting Interface
            sort_cols1, sort_cols2 = st.columns([2, 1])
            with sort_cols1:
                sort_by = st.selectbox(
                    "   Sort Records By", 
                    ["Date Created (Default)", "UUID", "Record Status", "Applicant Name", "WP Number", "Barangay", "Occupancy", "Last Modified"], 
                    index=0
                )
            with sort_cols2:
                sort_dir = st.radio("Sorting Direction", ["Descending ⬇️", "Ascending ⬆️"], horizontal=True)

            asc = (sort_dir == "Ascending ⬆️")
            sort_map = {
                "Date Created (Default)": "created_at",
                "UUID": "id",
                "Record Status": "Status",
                "Applicant Name": "applicant_name",
                "WP Number": "wp_number",
                "Barangay": "barangay",
                "Occupancy": "occupancy",
                "Last Modified": "updated_at"
            }
            sort_col_key = sort_map[sort_by]

            if sort_col_key in df_display.columns:
                df_display = df_display.sort_values(by=sort_col_key, ascending=asc)
                df = df.loc[df_display.index]
                
            if "selected_uuids" not in st.session_state:
                st.session_state.selected_uuids = set()

            editor_key = f"records_editor_{record_type}"

            def sync_checkboxes():
                edits = st.session_state[editor_key].get("edited_rows", {})
                for row_idx_str, changes in edits.items():
                    if "Select" in changes:
                        row_idx = int(row_idx_str)
                        row_id = df_display.iloc[row_idx]["id"]
                        if changes["Select"]:
                            st.session_state.selected_uuids.add(row_id)
                        else:
                            st.session_state.selected_uuids.discard(row_id)

            if "Select" in df_display.columns:
                df_display = df_display.drop(columns=["Select"])
            df_display.insert(0, "Select", df_display["id"].isin(st.session_state.selected_uuids))

            sel_col1, sel_col2, _ = st.columns([1, 1, 4])
            with sel_col1:
                if st.button("☑️ Select All Visible", key=f"sel_all_{st.session_state.table_id}", use_container_width=True):
                    st.session_state.selected_uuids.update(df_display["id"])
                    st.rerun()
            with sel_col2:
                if st.button("☐ Deselect Visible", key=f"desel_all_{st.session_state.table_id}", use_container_width=True):
                    st.session_state.selected_uuids.difference_update(df_display["id"])
                    st.rerun()

            disabled_cols = [c for c in df_display.columns if c != "Select"]
            column_configurations["Select"] = st.column_config.CheckboxColumn("Select", width="small", default=False)

            st.data_editor(
                df_display,
                column_config=column_configurations,
                disabled=disabled_cols,
                width="stretch",
                hide_index=True,
                key=editor_key,
                on_change=sync_checkboxes
            )
            selected_ids = list(st.session_state.selected_uuids)
            selected_rows = [df.index[df['id'] == uid].tolist()[0] for uid in selected_ids if not df[df['id'] == uid].empty]
            
            if len(st.session_state.selected_uuids) > 0:
                st.caption(f"🛒 **Selection Basket:** {len(st.session_state.selected_uuids)} total items selected.")
                if st.button("🗑️ Clear All Selections"):
                    st.session_state.selected_uuids = set()
                    st.rerun()



            # ===================================================================
            # SECURE CSV EXPORT (ROLE-RESTRICTED & AUDITED)
            # ===================================================================

            if user["role"] in ["Super Admin", "Manager", "Auditor"]:
                # 1. Grab the rows
                export_df = df.iloc[selected_rows].copy() if len(selected_rows) > 0 else df.copy()
                
                # Dynamic mapping to support both raw database columns and pre-cleaned display columns
                column_mapping = {
                    "wp_number": "WP Number", "WP Number": "WP Number",
                    "applicant_name": "Applicant", "Name": "Applicant",  # Resolves the "Name" conflict
                    "address": "Address", "Address": "Address",
                    "barangay": "Barangay", "Barangay": "Barangay",
                    "occupancy": "Occupancy", "Occupancy": "Occupancy",
                    "installation": "Installation", "Installation": "Installation"
                }
                
                # Slice columns safely without duplicates
                target_cols = list(column_mapping.keys())
                existing_cols = list(dict.fromkeys([col for col in target_cols if col in export_df.columns]))
                
                print_df = export_df[existing_cols].copy()
                print_df = print_df.rename(columns=column_mapping)
                
                # 3. Inject the empty columns for physical handwriting/printing
                print_df["BP / C.O.O / O.R"] = ""
                print_df["Date Release"] = ""
                print_df["Name"] = ""  # Now safely creates a new blank column without overwriting "Applicant"
                print_df["Signature"] = ""
                
                export_label = f"Export {len(selected_rows)} Selected Rows" if len(selected_rows) > 0 else f"Export All {len(print_df)} Filtered Rows"
                
                # 4. Secure Audit Logging Hook
                def log_csv_export():
                    ip_addr, device_name = get_client_metadata()
                    operator_str = f"{user['username']} ({user['role']})"
                    with database.get_db() as db:
                        data_manager.log_action(db, operator_str, "CSV_EXPORT", None, f"Downloaded Print-Formatted CSV containing {len(print_df)} records.", ip_addr, device_name)
                        db.commit()

                st.download_button(
                    label=f"📥 {export_label} to CSV",
                    data=print_df.to_csv(index=False).encode('utf-8'),
                    file_name=f"Enterprise_Records_Export_{datetime.now(PHT).strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    on_click=log_csv_export,
                    type="secondary"
                )
                st.markdown("<br>", unsafe_allow_html=True)

            # Multi-selection Lock Manager (Supports manual and header Select All clicks)
            new_selections = selected_ids
            old_locked_ids = st.session_state.get("current_locked_ids", [])

            import cloud_sync
            import threading

            def process_locks_bg(removes, adds, u_name, n_id):
                if not cloud_sync.SYNC_ACTIVE: return
                for r_id in removes:
                    cloud_sync.release_edit_lock(r_id)
                for a_id in adds:
                    cloud_sync.acquire_edit_lock(a_id, u_name, n_id)

            removes = []
            adds = []
            current_locked_list = []

            for old_id in old_locked_ids:
                if old_id not in new_selections:
                    removes.append(old_id)

            for db_id in new_selections:
                holder = cloud_sync.is_record_locked(db_id, st.session_state.session_node_id)
                if not holder:
                    adds.append(db_id)
                    current_locked_list.append(db_id)
                else:
                    # Keep it in our list if we already owned it
                    if db_id in old_locked_ids:
                        current_locked_list.append(db_id)

            st.session_state["current_locked_ids"] = current_locked_list

            if removes or adds:
                threading.Thread(target=process_locks_bg, args=(removes, adds, user["username"], st.session_state.session_node_id), daemon=True).start()

            # Apply single-row reference if exactly 1 is selected
            st.session_state.active_select_id = selected_ids[0] if len(selected_ids) == 1 else None
            
            # Retrieve active lock status for the single selected record
            lock_owner = None
            if st.session_state.active_select_id:
                lock_owner = cloud_sync.is_record_locked(st.session_state.active_select_id, st.session_state.session_node_id) if cloud_sync.SYNC_ACTIVE else None

            # ===================================================================
            # SINGLE ROW WORKFLOW
            # ===================================================================
            if st.session_state.active_select_id is not None:
                db_id = st.session_state.active_select_id
                with database.get_db() as db:
                    # Dynamically load from CFEI or Wiring Permits depending on selection
                    ModelClass = database.WiringPermitRecord if record_type == "wp" else database.MainRecord
                    record_db = db.query(ModelClass).filter(ModelClass.id == db_id).first()
                    if record_db:
                        record_item = {
                            "id": record_db.id,
                            "wp_number": record_db.wp_number,
                            "applicant_name": record_db.applicant_name,
                            "address": record_db.address,
                            "barangay": record_db.barangay,
                            "occupancy": record_db.occupancy,
                            "installation": record_db.installation,
                            "bp_number": record_db.bp_number,
                            "coo_number": record_db.coo_number,
                            "remarks": record_db.remarks,
                            "or_number": record_db.or_number,
                            "signature_base64": record_db.signature_base64,
                            "created_by": record_db.created_by,
                            "is_hidden": record_db.is_hidden if record_db.is_hidden is not None else False,
                            "created_at": record_db.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if record_db.created_at else "",
                            "qty_main_switch": getattr(record_db, "qty_main_switch", None),
                            "qty_socket": getattr(record_db, "qty_socket", None),
                            "qty_conv_outlet": getattr(record_db, "qty_conv_outlet", None),
                            "qty_switch": getattr(record_db, "qty_switch", None),
                            "qty_others": getattr(record_db, "qty_others", None),
                            "cei_number": getattr(record_db, "cei_number", ""),
                            "cfei_switchboard_qty": getattr(record_db, "cfei_switchboard_qty", ""),
                            "cfei_meter_qty": getattr(record_db, "cfei_meter_qty", ""),
                            "cfei_service_type": getattr(record_db, "cfei_service_type", ""),
                            "cfei_wiring_method": getattr(record_db, "cfei_wiring_method", ""),
                            "wp_qty_units": getattr(record_db, "wp_qty_units", "1"),
                            "wp_service_type": getattr(record_db, "wp_service_type", "1Ø ELECTRICAL SERVICE"),
                            "cfei_qty_light": getattr(record_db, "cfei_qty_light", None),
                            "cfei_qty_range": getattr(record_db, "cfei_qty_range", None),
                            "cfei_qty_acu": getattr(record_db, "cfei_qty_acu", None),
                            "cfei_qty_switch": getattr(record_db, "cfei_qty_switch", None),
                            "cfei_qty_motor": getattr(record_db, "cfei_qty_motor", None),
                            "cfei_qty_misc": getattr(record_db, "cfei_qty_misc", None),
                            "cfei_qty_conv": getattr(record_db, "cfei_qty_conv", None),
                            "cfei_qty_bell": getattr(record_db, "cfei_qty_bell", None),
                            "cfei_qty_others": getattr(record_db, "cfei_qty_others", None)
                        }
                    else:
                        record_item = None

                if record_item:
                    st.markdown(f"### 📍 Selected Entry: UUID `{db_id}`")
                    
                    st.markdown("---")
                    st.markdown("### 🖨️ Export & Print Certificate")
                    # Compliance audit checks
                    missing_fields = []
                    if not record_item.get("wp_number"): missing_fields.append("Wiring Permit (WP) Number")
                    if not record_item.get("applicant_name"): missing_fields.append("Applicant Name")
                    if not record_item.get("or_number") or record_item.get("or_number") == "NONE":
                        missing_fields.append("Official Receipt (O.R.) Number")
                    
                    if missing_fields:
                        st.warning(f"⚠️ Warning: This record is missing important details: {', '.join(missing_fields)}.")
                    
                    if st.button("🖨️ Prepare Print & Load Quantities", key=f"single_print_btn_{db_id}", type="primary"):
                        st.session_state.print_pending = [record_item]
                        st.session_state.print_ready = []
                        quantity_planner_dialog(record_type)
                        
                    st.caption("💡 **Tip:** Ensure **'Background graphics'** is turned **ON** in your browser's print options menu for the municipal background seal to show up on the paper.")
                    
                    col_mod, col_del = st.columns(2)
                    with col_mod:
                        st.markdown("#### ✏️ Modify Record")
                        
                        import cloud_sync
                        lock_owner = cloud_sync.is_record_locked(str(db_id), st.session_state.session_node_id) if cloud_sync.SYNC_ACTIVE else None
                        
                        can_edit = auth.check_permission(user["role"], "can_edit_all") or (
                            auth.check_permission(user["role"], "can_edit_own_only") and
                            record_item["created_by"] == user["username"]
                        )
                        
                        # Lock evaluation managed natively by terminal node_id caching
                        if lock_owner:
                            st.error(f"⚠️ Locked: {lock_owner} is currently viewing/editing this record on another PC.")
                            if st.button("🔄 Refresh Lock Status", key=f"refresh_lock_{db_id}"):
                                st.rerun()
                        elif can_edit:
                            if cloud_sync.SYNC_ACTIVE:
                                cloud_sync.acquire_edit_lock(str(db_id), user["username"], st.session_state.session_node_id)
                            edit_wp_number = st.text_input("WP Number", value=record_item["wp_number"], key="edit_wp_val")
                            edit_name = st.text_input("Applicant Name", value=record_item["applicant_name"], key="edit_name_val")
                            edit_address = st.text_input("Address", value=record_item["address"], key="edit_address_val")
                            
                            # Barangay Edit Dropdown (Vanishing Layout with "Other" at top + Custom DB values at bottom)
                            edit_brgy_presets = [
                                "AMAYA I", "AMAYA II", "AMAYA III", "AMAYA IV", "AMAYA V", "AMAYA VI", "AMAYA VII", "AMAYA VI-VII",
                                "DAANG AMAYA I", "DAANG AMAYA II", "DAANG AMAYA III", "BAGTAS", "BIGA", "BIWAS", "BUCAL", "BUNGA",
                                "CALIBUYO", "CAPIPISA", "HALAYHAY", "HALAYHAY/SAHUD-ULAN", "SAHUD-ULAN", "JULUGAN I", "JULUGAN II",
                                "JULUGAN III", "JULUGAN IV", "JULUGAN V", "JULUGAN VI", "JULUGAN VII", "JULUGAN VIII", "LAMBINGAN",
                                "MULAWIN", "SANJA MAYOR", "SANTOL", "TANAUAN", "TRES CRUSES", "POBLACION I", "POBLACION II",
                                "POBLACION III", "POBLACION IV", "PARADAHAN I", "PARADAHAN II", "PUNTA I", "PUNTA II"
                            ]
                            # Query all other unique barangay names currently saved in DB that aren't in the root presets
                            db_brgys = sorted(list(set([item["barangay"].strip().upper() for item in all_raw_items if item["barangay"]])))
                            custom_brgys = [b for b in db_brgys if b not in edit_brgy_presets]
                            edit_brgy_options = ["Other (Write manually below)"] + edit_brgy_presets + custom_brgys
                            
                            if record_item["barangay"] in (edit_brgy_presets + custom_brgys):
                                initial_brgy_idx = edit_brgy_options.index(record_item["barangay"])
                            else:
                                initial_brgy_idx = 0  # Defaults to "Other (Write manually below)"
                                
                            edit_brgy_select = st.selectbox("Barangay", edit_brgy_options, index=initial_brgy_idx, key="edit_brgy_select_val")
                            edit_brgy_manual = ""
                            if edit_brgy_select == "Other (Write manually below)":
                                edit_brgy_manual = st.text_input("Specify Custom Barangay Name", value=record_item["barangay"], key="edit_brgy_manual_val")
                            edit_barangay = edit_brgy_manual if edit_brgy_select == "Other (Write manually below)" else edit_brgy_select

                            # Occupancy Edit Dropdown (Vanishing Layout with "Other" at top + Custom DB values at bottom)
                            if record_type == "wp":
                                edit_occ_presets = ["COMMERCIAL", "GOVERNMENT", "INDUSTRIAL", "INSTITUTIONAL", "RESIDENTIAL"]
                            else:
                                edit_occ_presets = ["COMMERCIAL", "INDUSTRIAL", "INSTITUTIONAL", "RESIDENTIAL"]
                            db_occs = sorted(list(set([item["occupancy"].strip().upper() for item in all_raw_items if item["occupancy"]])))
                            custom_occs = [o for o in db_occs if o not in edit_occ_presets]
                            edit_occ_options = ["Other (Write manually below)"] + edit_occ_presets + custom_occs
                            
                            if record_item["occupancy"] in (edit_occ_presets + custom_occs):
                                initial_occ_idx = edit_occ_options.index(record_item["occupancy"])
                            else:
                                initial_occ_idx = 0  # Defaults to "Other (Write manually below)"
                                
                            edit_occ_select = st.selectbox("Occupancy Type", edit_occ_options, index=initial_occ_idx, key="edit_occ_select_val")
                            edit_occ_manual = ""
                            if edit_occ_select == "Other (Write manually below)":
                                edit_occ_manual = st.text_input("Specify Custom Occupancy", value=record_item["occupancy"], key="edit_occ_manual_val")
                            edit_occupancy = edit_occ_manual if edit_occ_select == "Other (Write manually below)" else edit_occ_select

                            # Locked Installation Edit Dropdown
                            if record_type == "wp":
                                edit_inst_options = ["NEW", "TEMPORARY", "REMODEL", "RELOCATION", "SEPARATION", "RECONNECTION"]
                            else:
                                edit_inst_options = ["NEW", "TEMPORARY", "RELOCATION", "SEPARATION", "RECONNECTION"]
                            if record_item["installation"] in edit_inst_options:
                                initial_inst_idx = edit_inst_options.index(record_item["installation"])
                            else:
                                initial_inst_idx = 0
                                
                            edit_installation = st.selectbox("Installation Type", edit_inst_options, index=initial_inst_idx, key="edit_inst_select_val")

                            edit_bp_number = st.text_input("Building Permit (B.P) Number", value=record_item["bp_number"], key="edit_bp_number_val")
                            edit_coo_number = st.text_input("Cert. of Occupancy (C.O.O) Number", value=record_item["coo_number"], key="edit_coo_number_val")
                            edit_or_number = st.text_input("Official Receipt (O.R.) Number (7 Digits)", value=record_item["or_number"], key="edit_or_number_val")
                            
                            if st.session_state.get("show_financials", True):
                                cost_str = st.text_input("Total Cost (₱)", value=str(record_item.get("total_cost") or "0.0"), key="edit_total_cost_val")
                                try:
                                    clean_cost_str = re.sub(r'[^0-9.]', '', cost_str.replace("₱", "").replace(",", "").strip())
                                    total_cost = float(clean_cost_str) if clean_cost_str else 0.0
                                except Exception:
                                    total_cost = 0.0
                            else:
                                edit_total_cost = float(record_item.get("total_cost") or 0.0)
                                
                            edit_remarks = st.text_input("Remarks / Notes / Overrides", value=record_item["remarks"], key="edit_remarks_val")
                            
                            final_sig = None
                            final_sig = None
                            ip_addr, device_name = get_client_metadata()
                            col_edit_act1, col_edit_act2 = st.columns(2)
                            
                            # --- FIX: HARD-LOCK BUFFERED CLICK SPAM BLOCKER ---
                            err_key = f"edit_error_{db_id}"
                            if err_key in st.session_state and st.session_state[err_key]:
                                st.error(st.session_state[err_key])
                                
                            is_committed = st.session_state.get(f"edit_committed_{db_id}", False)
                            edit_btn_text = "⏳ Saving..." if is_committed else "Confirm Changes"
                            
                            with col_edit_act1:
                                if st.button(edit_btn_text, type="secondary", key=f"edit_submit_btn_{db_id}", use_container_width=True, disabled=is_committed):
                                    if st.session_state.get(f"edit_committed_{db_id}", False):
                                        st.stop() # Drop buffered duplicate clicks
                                    st.session_state[f"edit_committed_{db_id}"] = True
                                    
                                    # Final latency check: Ensure we still own the lock before committing the write
                                    fresh_owner = cloud_sync.is_record_locked(str(db_id), st.session_state.session_node_id) if cloud_sync.SYNC_ACTIVE else None
                                    if fresh_owner:
                                        st.session_state[err_key] = f"❌ Submission Blocked: '{fresh_owner}' acquired the lock."
                                        st.session_state[f"edit_committed_{db_id}"] = False
                                        st.rerun()
                                    elif not edit_wp_number or not edit_wp_number.strip():
                                        st.session_state[err_key] = "❌ Edit Denied: WP Number cannot be blank."
                                        st.session_state[f"edit_committed_{db_id}"] = False
                                        st.rerun()
                                    elif not edit_name or not edit_name.strip():
                                        st.session_state[err_key] = "❌ Edit Denied: Applicant Name cannot be blank."
                                        st.session_state[f"edit_committed_{db_id}"] = False
                                        st.rerun()
                                    elif not edit_address or not edit_address.strip():
                                        st.session_state[err_key] = "❌ Edit Denied: Address cannot be blank."
                                        st.session_state[f"edit_committed_{db_id}"] = False
                                        st.rerun()
                                    else:
                                        try:
                                            result = data_manager.update_record(
                                                user, db_id, record_type,
                                                edit_wp_number.strip(), edit_name.strip(), edit_address.strip(),
                                                edit_barangay, edit_occupancy, edit_installation,
                                                edit_bp_number.strip() if edit_bp_number else "",
                                                edit_coo_number.strip() if edit_coo_number else "",
                                                edit_remarks.strip() if edit_remarks else "",
                                                edit_or_number.strip() if edit_or_number else "",
                                                final_sig, ip_addr, device_name, total_cost=edit_total_cost
                                            )
                                            if "Success" in result:
                                                if cloud_sync.SYNC_ACTIVE:
                                                    cloud_sync.release_edit_lock(str(db_id))
                                                st.session_state.active_select_id = None
                                                st.session_state.success_msg = f"Record UUID {db_id} successfully modified!"
                                                st.session_state.unblurred_id = None
                                                st.session_state.search_query_val = ""
                                                st.session_state[err_key] = None
                                                st.session_state[f"is_editing_{db_id}"] = False
                                                st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                                                st.rerun()
                                            else:
                                                st.session_state[err_key] = result
                                                st.session_state[f"is_editing_{db_id}"] = False
                                                st.rerun()
                                        except Exception as e:
                                            # Force release editing lock on the cloud to prevent orphaning, and unfreeze the UI
                                            if cloud_sync.SYNC_ACTIVE:
                                                cloud_sync.release_edit_lock(str(db_id))
                                            st.session_state[err_key] = f"❌ Database System Error: {str(e)}"
                                            st.session_state[f"is_editing_{db_id}"] = False
                                            st.rerun()
                                
                            with col_edit_act2:
                                if st.button("Cancel & Close ❌", key="edit_cancel_btn", use_container_width=True):
                                    if cloud_sync.SYNC_ACTIVE:
                                        cloud_sync.release_edit_lock(str(db_id))
                                    st.session_state.active_select_id = None
                                    st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                                    st.rerun()



                        else:
                            st.warning("⚠️ You are not authorized to edit this record.")
                    with col_del:
                        # Strictly block deletions/archiving if another operator is editing
                        if lock_owner:
                            st.markdown("#### 📁 Archive Record")
                            st.warning(f"🔒 Locked: Cannot archive while '{lock_owner}' is editing.")
                            st.write("---")
                            st.markdown("#### 🗑️ Delete Record")
                            st.warning(f"🔒 Locked: Cannot delete while '{lock_owner}' is editing.")
                        else:
                            st.markdown("#### 📁 Archive Record")
                            # Fail-safe state checker (handles SQLite boolean, integer, or string driver serialization quirks)
                            is_currently_hidden = record_item.get("is_hidden") in (True, 1, "True", "1")
                            archive_btn_label = "Unarchive (Show) Record" if is_currently_hidden else "Archive (Hide) Record"
                            archive_btn_type = "secondary" if is_currently_hidden else "primary"
                            
                            if st.button(archive_btn_label, type=archive_btn_type, key=f"archive_record_btn_{db_id}", use_container_width=True):
                                ip_addr, device_name = get_client_metadata()
                                result = data_manager.hide_record(user, db_id, record_type, not is_currently_hidden, ip_addr, device_name)
                                if "Success" in result:
                                    # Cleanly release edit lock and close panel on success
                                    if cloud_sync.SYNC_ACTIVE:
                                        cloud_sync.release_edit_lock(str(db_id))
                                    st.session_state.active_select_id = None
                                    
                                    st.session_state.success_msg = f"Record UUID {db_id} successfully {'restored to active view' if is_currently_hidden else 'archived'}."
                                    st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                                    st.rerun()
                                else:
                                    st.error(result)

                            st.write("---")

                            st.markdown("#### 🗑️ Delete Record")
                            if auth.check_permission(user["role"], "can_delete"):
                                st.error("Warning: Deletion is permanent and logged immediately.")
                                confirm_delete = st.checkbox(f"I confirm that I want to delete Record UUID: {db_id}")
                                if st.button("Permanently Remove Record", type="primary", disabled=not confirm_delete, key="delete_record_btn"):
                                    ip_addr, device_name = get_client_metadata()
                                    result = data_manager.delete_record(user, db_id, record_type, ip_addr, device_name)
                                    if "Success" in result:
                                        # Cleanly release edit lock and close panel on success
                                        if cloud_sync.SYNC_ACTIVE:
                                            cloud_sync.release_edit_lock(str(db_id))
                                        st.session_state.active_select_id = None
                                        
                                        # --- FIX: PURGE ID FROM SELECTION BASKET MEMORY ---
                                        if "selected_uuids" in st.session_state:
                                            st.session_state.selected_uuids.discard(db_id)
                                        
                                        st.session_state.success_msg = f"Record UUID {db_id} permanently deleted."
                                        st.session_state.search_query_val = ""
                                        st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                                        st.rerun()
                                    else:
                                        st.error(result)
                            else:
                                st.warning("🔒 Only System Admins and Managers can delete records.")

            # ===================================================================
            # BULK OPERATION SELECT PANEL
            # ===================================================================
            if len(selected_ids) > 1:
                st.markdown(f"### ⚙️ Bulk Action Board ({len(selected_ids)} Items Highlighted)")
                selected_names = [df[df['id'] == uid]["applicant_name"].values[0] for uid in selected_ids if not df[df['id'] == uid].empty]
                st.write(f"**Highlighting permit records:** {', '.join([f'{name} (UUID: {idx})' for name, idx in zip(selected_names, selected_ids)])}")

                # Check if any selected record is currently locked by another terminal
                import cloud_sync
                active_bulk_locks = {}
                if cloud_sync.SYNC_ACTIVE:
                    for db_id in selected_ids:
                        holder = cloud_sync.is_record_locked(db_id, st.session_state.session_node_id)
                        if holder:
                            # Find the applicant's name for friendly display
                            match_row = df_display[df_display["id"] == db_id]
                            name_val = match_row.iloc[0]["applicant_name"] if not match_row.empty else db_id
                            active_bulk_locks[name_val] = holder

                # Render a prominent block warning if a lock is detected
                bypass_locks = False
                if active_bulk_locks:
                    lock_details = ", ".join([f"'{name}' (edited by {holder})" for name, holder in active_bulk_locks.items()])
                    st.error(f"🔒 Concurrency Lock: Selected records contain locked rows: {lock_details}.")
                    bypass_locks = st.checkbox("⚠️ Bypass locked records (Automatically skip locks and apply bulk actions to the remaining safe items)", value=False, key=f"bulk_bypass_chk_{record_type}")
                
                # Determine disabling status for bulk buttons based on locks and bypass choices
                bulk_disabled = bool(active_bulk_locks) and not bypass_locks
                
                # Retrieve full objects for selected rows to audit missing elements
                selected_records = []
                with database.get_db() as db:
                    ModelClass = database.WiringPermitRecord if record_type == "wp" else database.MainRecord
                    for db_id in selected_ids:
                        rec_db = db.query(ModelClass).filter(ModelClass.id == db_id).first()
                        if rec_db:
                            selected_records.append({
                                "id": rec_db.id,
                                "wp_number": rec_db.wp_number,
                                "applicant_name": rec_db.applicant_name,
                                "address": rec_db.address,
                                "barangay": rec_db.barangay,
                                "occupancy": rec_db.occupancy,
                                "installation": rec_db.installation,
                                "bp_number": rec_db.bp_number,
                                "coo_number": rec_db.coo_number,
                                "remarks": rec_db.remarks,
                                "or_number": rec_db.or_number,
                                "signature_base64": rec_db.signature_base64,
                                "created_at": rec_db.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if rec_db.created_at else "",
                                "qty_main_switch": getattr(rec_db, "qty_main_switch", None),
                                "qty_socket": getattr(rec_db, "qty_socket", None),
                                "qty_conv_outlet": getattr(rec_db, "qty_conv_outlet", None),
                                "qty_switch": getattr(rec_db, "qty_switch", None),
                                "qty_others": getattr(rec_db, "qty_others", None),
                                "cei_number": getattr(rec_db, "cei_number", ""),
                                "cfei_switchboard_qty": getattr(rec_db, "cfei_switchboard_qty", ""),
                                "cfei_meter_qty": getattr(rec_db, "cfei_meter_qty", ""),
                                "cfei_service_type": getattr(rec_db, "cfei_service_type", ""),
                                "cfei_wiring_method": getattr(rec_db, "cfei_wiring_method", ""),
                                "wp_qty_units": getattr(rec_db, "wp_qty_units", "1"),
                                "wp_service_type": getattr(rec_db, "wp_service_type", "1Ø ELECTRICAL SERVICE"),
                                "cfei_qty_light": getattr(rec_db, "cfei_qty_light", None),
                                "cfei_qty_range": getattr(rec_db, "cfei_qty_range", None),
                                "cfei_qty_acu": getattr(rec_db, "cfei_qty_acu", None),
                                "cfei_qty_switch": getattr(rec_db, "cfei_qty_switch", None),
                                "cfei_qty_motor": getattr(rec_db, "cfei_qty_motor", None),
                                "cfei_qty_misc": getattr(rec_db, "cfei_qty_misc", None),
                                "cfei_qty_conv": getattr(rec_db, "cfei_qty_conv", None),
                                "cfei_qty_bell": getattr(rec_db, "cfei_qty_bell", None),
                                "cfei_qty_others": getattr(rec_db, "cfei_qty_others", None)
                            })

                st.markdown("### 🖨️ Bulk Export Certificate Forms")
                bulk_missing = []
                for r in selected_records:
                    m_list = []
                    if not r.get("wp_number"): m_list.append("WP Number")
                    if not r.get("or_number") or r.get("or_number") == "NONE": m_list.append("O.R. Number")
                    if m_list:
                        bulk_missing.append(f"UUID #{r['id']} ({r['applicant_name'][:15]}) is missing: {', '.join(m_list)}")
                
                if bulk_missing:
                    with st.expander("⚠️ Compliance Alert: Some selected records are missing details"):
                        for m in bulk_missing:
                            st.write(f"- {m}")
                
                if st.button(f"🖨️ Prepare Print & Load Quantities for {len(selected_ids)} Items", key="bulk_print_trigger_btn", type="primary"):
                    st.session_state.print_pending = selected_records
                    st.session_state.print_ready = []
                    quantity_planner_dialog(record_type)

                st.caption("💡 **Tip:** Ensure **'Background graphics'** is turned **ON** in your browser's print options menu for the municipal background seal to show up on the paper.")
                
                col_bulk_edit, col_bulk_del, col_bulk_archive = st.columns(3)
                
                # BULK ARCHIVING / RESTORATION CONTROL
                with col_bulk_archive:
                    st.markdown("#### 📁 Bulk Archive Control")
                    if auth.check_permission(user["role"], "can_edit_all"):
                        st.write("Temporarily hide or restore multiple selected records from active directory views.")
                        
                        col_arch, col_unarch = st.columns(2)
                        with col_arch:
                            if st.button("Archive Items", type="primary", key="bulk_archive_submit_btn", use_container_width=True, disabled=bulk_disabled):
                                success_count = 0
                                skipped_count = 0
                                for db_id in selected_ids:
                                    # Pass session_node_id and check for other PC locks natively
                                    holder = cloud_sync.is_record_locked(db_id, st.session_state.session_node_id)
                                    if holder:
                                        skipped_count += 1
                                        continue
                                    
                                    ip_addr, device_name = get_client_metadata()
                                    res = data_manager.hide_record(user, db_id, record_type, True, ip_addr, device_name)
                                    if "Success" in res:
                                        success_count += 1
                                    else:
                                        st.error(res)
                                        break

                                if "Success" in res or success_count > 0:
                                    skip_text = f" (skipped {skipped_count} locked records)" if skipped_count else ""
                                    st.session_state.success_msg = f"Successfully hidden/archived {success_count} records{skip_text} from the active view."
                                    st.session_state.active_select_id = None
                                    st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                                    st.rerun()
                                
                        with col_unarch:
                            if st.button("Restore Items", type="secondary", key="bulk_unarchive_submit_btn", use_container_width=True, disabled=bulk_disabled):
                                success_count = 0
                                skipped_count = 0
                                for db_id in selected_ids:
                                    # Pass session_node_id and check for other PC locks natively
                                    holder = cloud_sync.is_record_locked(db_id, st.session_state.session_node_id)
                                    if holder:
                                        skipped_count += 1
                                        continue
                                        
                                    ip_addr, device_name = get_client_metadata()
                                    res = data_manager.hide_record(user, db_id, record_type, False, ip_addr, device_name)
                                    if "Success" in res:
                                        success_count += 1
                                    else:
                                        st.error(res)
                                        break

                                if "Success" in res or success_count > 0:
                                    skip_text = f" (skipped {skipped_count} locked records)" if skipped_count else ""
                                    st.session_state.success_msg = f"Successfully restored {success_count} records{skip_text} back to active directory views."
                                    st.session_state.active_select_id = None
                                    st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                                    st.rerun()
                    else:
                        st.warning("🔒 Only System Admins and Managers can run bulk archiving/restoration.")
               
                # WIZARD STARTER
                with col_bulk_edit:
                    st.markdown("#### ✏️ Guided Bulk Modification")
                    if auth.check_permission(user["role"], "can_edit_all"):
                        st.write("Modify names, custom locations, installation types, and signatures step-by-step.")
                        if st.button("🚀 Start Guided Bulk Modification", type="secondary", key="start_bulk_btn", disabled=bulk_disabled):
                            # Pre-filter selected IDs to completely exclude locks on wizard load
                            safe_ids = []
                            for db_id in selected_ids:
                                holder = cloud_sync.is_record_locked(db_id, st.session_state.session_node_id)
                                if holder:
                                    continue
                                safe_ids.append(db_id)
                                
                            if not safe_ids:
                                st.error("❌ Action Blocked: No unlocked records available in this selection.")
                            else:
                                st.session_state.bulk_edit_active = True
                                st.session_state.bulk_edit_ids = safe_ids
                                st.session_state.bulk_edit_index = 0
                                st.rerun()
                    else:
                        st.warning("🔒 Only System Admins and Managers can run bulk modifications.")
                
                # BULK DELETE
                # BULK DELETE
                with col_bulk_del:
                    st.markdown("#### 🗑️ Bulk Delete Records")
                    if auth.check_permission(user["role"], "can_delete"):
                        st.error("Warning: You are about to permanently delete multiple records. This will trigger individual audit logs for each deleted ID.")
                        
                        # Disable confirmation checkbox and buttons if locks are active and bypass is off
                        confirm_bulk_del = st.checkbox(f"I confirm that I want to permanently delete these {len(selected_ids)} records", disabled=bulk_disabled)
                        delete_disabled = (not confirm_bulk_del) or bulk_disabled
                        
                        if st.button(f"Permanently Delete {len(selected_ids)} Items", type="primary", disabled=delete_disabled, key="bulk_delete_submit_btn"):
                            success_count = 0
                            skipped_count = 0
                            result = ""  # <--- FIX: Initialize result to prevent NameError
                            
                            for db_id in selected_ids:
                                # Pass session_node_id and check for other PC locks natively
                                holder = cloud_sync.is_record_locked(db_id, st.session_state.session_node_id)
                                if holder:
                                    skipped_count += 1
                                    continue
                                    
                                ip_addr, device_name = get_client_metadata()
                                result = data_manager.delete_record(user, db_id, record_type, ip_addr, device_name)
                                if "Success" in result:
                                    success_count += 1
                                    
                                    # --- FIX: PURGE ID FROM SELECTION BASKET SAFELY ---
                                    if "selected_uuids" in st.session_state:
                                        if isinstance(st.session_state.selected_uuids, set):
                                            st.session_state.selected_uuids.discard(db_id)
                                        elif isinstance(st.session_state.selected_uuids, list) and db_id in st.session_state.selected_uuids:
                                            st.session_state.selected_uuids.remove(db_id)
                                else:
                                    st.error(result)
                                    break

                            if "Success" in result or success_count > 0:
                                skip_text = f" (skipped {skipped_count} locked records)" if skipped_count else ""
                                st.session_state.success_msg = f"Successfully deleted {success_count} records{skip_text} from database."
                                st.session_state.active_select_id = None
                                st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                                st.rerun()
                    else:
                        st.warning("🔒 Only System Admins and Managers can run bulk deletions.")

# ===================================================================
# GUIDED BULK MODIFICATION WIZARD VIEW (OUTSIDE SELECTION TO PREVENT VANISHING)
# ===================================================================
if st.session_state.bulk_edit_active:
    # Anchor point for responsiveness
    st.markdown('<div id="bulk_wizard_top"></div>', unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("### 🚀 Guided Bulk Modification Wizard")
    
    current_idx = st.session_state.bulk_edit_index
    total_items = len(st.session_state.bulk_edit_ids)
    
    if current_idx < total_items:
        current_db_id = st.session_state.bulk_edit_ids[current_idx]
        with database.get_db() as db:
            ModelClass = database.WiringPermitRecord if record_type == "wp" else database.MainRecord
            record_db = db.query(ModelClass).filter(ModelClass.id == current_db_id).first()         
            if record_db:
                record_obj = {
                    "id": record_db.id,
                    "wp_number": record_db.wp_number,
                    "applicant_name": record_db.applicant_name,
                    "address": record_db.address,
                    "barangay": record_db.barangay,
                    "occupancy": record_db.occupancy,
                    "installation": record_db.installation,
                    "bp_number": record_db.bp_number,
                    "coo_number": record_db.coo_number,
                    "remarks": record_db.remarks,
                    "or_number": record_db.or_number,
                    "signature_base64": record_db.signature_base64,
                    "created_by": record_db.created_by,
                    "is_hidden": record_db.is_hidden
                }
            else:
                record_obj = None

        if record_obj:
            import cloud_sync
            lock_holder = cloud_sync.is_record_locked(str(current_db_id), st.session_state.session_node_id) if cloud_sync.SYNC_ACTIVE else None
            
            st.markdown(f"**Modifying Entry {current_idx + 1} of {total_items}** (Database UUID: `{current_db_id}` | Originally Created By: `{record_obj['created_by']}`)")
            
            # If another administrator holds the lock, show warning, skip, and stop further rendering
            if lock_holder:
                st.error(f"⚠️ Warning: Record UUID {current_db_id} is currently locked by '{lock_holder}'. Modifying this may overwrite active modifications.")
                st.write("Please wait for them to finish, or skip this entry below.")
                st.write("---")
                col_locked_btn1, col_locked_btn2 = st.columns(2)
                with col_locked_btn1:
                    if st.button("Skip Locked Entry ⏭️", key=f"bulk_skip_locked_{current_db_id}", use_container_width=True):
                        st.session_state.bulk_edit_index += 1
                        st.rerun()
                with col_locked_btn2:
                    if st.button("Exit Wizard 🛑", key=f"bulk_exit_locked_{current_db_id}", type="secondary", use_container_width=True):
                        st.session_state.bulk_edit_active = False
                        st.session_state.bulk_edit_ids = []
                        st.session_state.bulk_edit_index = 0
                        st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                        st.rerun()
                st.stop() # Safely halts execution here to prevent loading input forms or namespace errors below
            
            # If free, place our active lock on GDrive and register it with the background pinger
            if cloud_sync.SYNC_ACTIVE:
                cloud_sync.acquire_edit_lock(str(current_db_id), user["username"], st.session_state.session_node_id)
                st.session_state["current_locked_id"] = str(current_db_id)


            bulk_edit_wp = st.text_input("WP Number", value=record_obj["wp_number"], key=f"bulk_wp_{current_db_id}")
            bulk_edit_name = st.text_input("Applicant Name", value=record_obj["applicant_name"], key=f"bulk_name_{current_db_id}")
            bulk_edit_address = st.text_input("Address", value=record_obj["address"], key=f"bulk_address_{current_db_id}")
            
            # Barangay Bulk Dropdown Option (Vanishing Layout with "Other" at top + Custom DB values at bottom)
            bulk_brgy_presets = [
                "AMAYA I", "AMAYA II", "AMAYA III", "AMAYA IV", "AMAYA V", "AMAYA VI", "AMAYA VII", "AMAYA VI-VII",
                "DAANG AMAYA I", "DAANG AMAYA II", "DAANG AMAYA III", "BAGTAS", "BIGA", "BIWAS", "BUCAL", "BUNGA",
                "CALIBUYO", "CAPIPISA", "HALAYHAY", "HALAYHAY/SAHUD-ULAN", "SAHUD-ULAN", "JULUGAN I", "JULUGAN II",
                "JULUGAN III", "JULUGAN IV", "JULUGAN V", "JULUGAN VI", "JULUGAN VII", "JULUGAN VIII", "LAMBINGAN",
                "MULAWIN", "SANJA MAYOR", "SANTOL", "TANAUAN", "TRES CRUSES", "POBLACION I", "POBLACION II",
                "POBLACION III", "POBLACION IV", "PARADAHAN I", "PARADAHAN II", "PUNTA I", "PUNTA II"
            ]
            bulk_db_brgys = sorted(list(set([item["barangay"].strip().upper() for item in all_raw_items if item["barangay"]])))
            bulk_custom_brgys = [b for b in bulk_db_brgys if b not in bulk_brgy_presets]
            bulk_brgy_options = ["Other (Write manually below)"] + bulk_brgy_presets + bulk_custom_brgys
            
            if record_obj["barangay"] in (bulk_brgy_presets + bulk_custom_brgys):
                bulk_brgy_idx = bulk_brgy_options.index(record_obj["barangay"])
            else:
                bulk_brgy_idx = bulk_brgy_options.index("Other (Write manually below)")

            bulk_edit_brgy_select = st.selectbox("Barangay Preset Options", bulk_brgy_options, index=bulk_brgy_idx, key=f"bulk_brgy_select_{current_db_id}")
            bulk_brgy_manual = ""
            if bulk_edit_brgy_select == "Other (Write manually below)":
                bulk_brgy_manual = st.text_input("Specify Custom Barangay Name", value=record_obj["barangay"], key=f"bulk_brgy_manual_{current_db_id}")
            bulk_edit_barangay = bulk_brgy_manual if bulk_edit_brgy_select == "Other (Write manually below)" else bulk_edit_brgy_select

            # Occupancy Bulk Dropdown Option (Vanishing Layout with "Other" at top + Custom DB values at bottom)
            if record_type == "wp":
                bulk_occ_presets = ["COMMERCIAL", "GOVERNMENT", "INDUSTRIAL", "INSTITUTIONAL", "RESIDENTIAL"]
            else:
                bulk_occ_presets = ["COMMERCIAL", "INDUSTRIAL", "INSTITUTIONAL", "RESIDENTIAL"]
            bulk_db_occs = sorted(list(set([item["occupancy"].strip().upper() for item in all_raw_items if item["occupancy"]])))
            bulk_custom_occs = [o for o in bulk_db_occs if o not in bulk_occ_presets]
            bulk_occ_options = ["Other (Write manually below)"] + bulk_occ_presets + bulk_custom_occs
            
            if record_obj["occupancy"] in (bulk_occ_presets + bulk_custom_occs):
                bulk_occ_idx = bulk_occ_options.index(record_obj["occupancy"])
            else:
                bulk_occ_idx = bulk_occ_options.index("Other (Write manually below)")

            bulk_edit_occ_select = st.selectbox("Occupancy Type Preset Options", bulk_occ_options, index=bulk_occ_idx, key=f"bulk_occ_select_{current_db_id}")
            bulk_occ_manual = ""
            if bulk_edit_occ_select == "Other (Write manually below)":
                bulk_occ_manual = st.text_input("Specify Custom Occupancy Type", value=record_obj["occupancy"], key=f"bulk_occ_manual_{current_db_id}")
            bulk_edit_occupancy = bulk_occ_manual if bulk_edit_occ_select == "Other (Write manually below)" else bulk_edit_occ_select

            # Locked Bulk Installation Dropdown Option
            if record_type == "wp":
                bulk_inst_options = ["NEW", "TEMPORARY", "REMODEL", "RELOCATION", "SEPARATION", "RECONNECTION"]
            else:
                bulk_inst_options = ["NEW", "TEMPORARY", "RELOCATION", "SEPARATION", "RECONNECTION"]
            if record_obj["installation"] in bulk_inst_options:
                bulk_inst_idx = bulk_inst_options.index(record_obj["installation"])
            else:
                bulk_inst_idx = 0

            bulk_edit_installation = st.selectbox("Installation Type Options", bulk_inst_options, index=bulk_inst_idx, key=f"bulk_inst_select_{current_db_id}")

            bulk_edit_bp = st.text_input("Building Permit (B.P) Number", value=record_obj["bp_number"], key=f"bulk_bp_{current_db_id}")
            bulk_edit_coo = st.text_input("Cert. of Occupancy (C.O.O) Number", value=record_obj["coo_number"], key=f"bulk_coo_{current_db_id}")
            bulk_edit_or = st.text_input("Official Receipt (O.R.) Number (7 Digits)", value=record_obj["or_number"], key=f"bulk_or_{current_db_id}")
            
            if st.session_state.get("show_financials", True):
                bulk_edit_total_cost = st.number_input("Total Cost (₱)", min_value=0.0, step=100.0, value=float(record_obj.get("total_cost") or 0.0), key=f"bulk_total_cost_{current_db_id}")
            else:
                bulk_edit_total_cost = float(record_obj.get("total_cost") or 0.0)
                
            bulk_edit_remarks = st.text_input("Remarks / Notes / Overrides", value=record_obj["remarks"], key=f"bulk_remarks_{current_db_id}")
            bulk_final_sig = None
            st.write("---")
            col_wizard_btn1, col_wizard_btn2, col_wizard_btn3 = st.columns([1, 1, 2])
            with col_wizard_btn1:
                ip_addr, device_name = get_client_metadata()
                if st.button("Confirm & Next ➡️", key=f"bulk_confirm_btn_{current_db_id}", type="primary"):
                    if not bulk_edit_wp or not bulk_edit_wp.strip():
                        st.error("❌ Edit Denied: WP Number cannot be blank.")
                    elif not bulk_edit_name or not bulk_edit_name.strip():
                        st.error("❌ Edit Denied: Applicant Name cannot be blank.")
                    elif not bulk_edit_address or not bulk_edit_address.strip():
                        st.error("❌ Edit Denied: Address cannot be blank.")
                    else:
                        res = data_manager.update_record(
                            user, current_db_id, record_type,
                            bulk_edit_wp.strip(), bulk_edit_name.strip(), bulk_edit_address.strip(),
                            bulk_edit_barangay, bulk_edit_occupancy, bulk_edit_installation,
                            bulk_edit_bp.strip() if bulk_edit_bp else "",
                            bulk_edit_coo.strip() if bulk_edit_coo else "",
                            bulk_edit_remarks.strip() if bulk_edit_remarks else "",
                            bulk_edit_or.strip() if bulk_edit_or else "",
                            bulk_final_sig, ip_addr, device_name, total_cost=bulk_edit_total_cost
                        )
                        if "Success" in res:
                            # Cleanly release lock before moving index forward
                            if cloud_sync.SYNC_ACTIVE:
                                cloud_sync.release_edit_lock(str(current_db_id))
                            st.session_state["current_locked_id"] = None
                            
                            st.session_state.bulk_edit_index += 1
                            st.session_state.unblurred_id = None
                            if st.session_state.bulk_edit_index >= total_items:
                                st.session_state.bulk_edit_active = False
                                st.session_state.success_msg = f"✓ Completed bulk modification of {total_items} entries."
                            st.rerun()
                        else:
                            st.error(res)
            
            with col_wizard_btn2:
                if st.button("Skip This Entry ⏭️", key=f"bulk_skip_btn_{current_db_id}"):
                    # Cleanly release lock before skipping
                    if cloud_sync.SYNC_ACTIVE:
                        cloud_sync.release_edit_lock(str(current_db_id))
                    st.session_state["current_locked_id"] = None
                    
                    st.session_state.bulk_edit_index += 1
                    if st.session_state.bulk_edit_index >= total_items:
                        st.session_state.bulk_edit_active = False
                        st.session_state.success_msg = "✓ Completed bulk wizard (skipped items unchanged)."
                    st.rerun()
            
            with col_wizard_btn3:
                st.caption("ℹ️ Already confirmed edits will remain saved.")
                if st.button("Exit Wizard 🛑", key=f"bulk_cancel_all_btn_{current_db_id}", type="secondary", help="Stops editing the remaining queue. Previously confirmed modifications will not be undone."):
                    # Cleanly release lock before exiting
                    if cloud_sync.SYNC_ACTIVE:
                        cloud_sync.release_edit_lock(str(current_db_id))
                    st.session_state["current_locked_id"] = None
                    
                    st.session_state.bulk_edit_active = False
                    st.session_state.bulk_edit_ids = []
                    st.session_state.bulk_edit_index = 0
                    st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                    st.rerun()

            # AUTOMATIC RESPONSIVE SMOOTH SCROLL TO WIZARD HEADER
            st.components.v1.html(
                f"""
                <script>
                    var element = window.parent.document.getElementById("bulk_wizard_top");
                    if (element) {{
                        element.scrollIntoView({{behavior: 'smooth'}});
                    }}
                </script>
                <!-- {datetime.now(timezone.utc).timestamp()} -->
                """,
                height=1,
            )
    else:
        st.session_state.bulk_edit_active = False
        st.rerun()
# ------------------------------------------
# TAB 2: ADD NEW RECORD OR BULK IMPORT (DYNAMIC AUTOFILL & ALL-CAPS FORMS)
# ------------------------------------------
with tabs[1]:
    st.subheader("➕ Add or Import Permit Records")
    if auth.check_permission(user["role"], "can_add_data"):
        
        mode = st.radio("Entry Method", ["Manual Form Entry", "Bulk Excel (XLSX) Transmittal Import"], horizontal=True, key="importer_entry_mode")
        
        # --- FIX 12: ERROR-PROOF CACHE WIPE ON MODE TRANSITION ---
        if "last_entry_mode" not in st.session_state:
            st.session_state.last_entry_mode = mode
            
        if st.session_state.last_entry_mode != mode:
            st.session_state.last_entry_mode = mode
            st.session_state.import_df = None
            st.session_state.active_edited_df = None
            st.session_state.processed_file_names = set()
            # Force-increment the version to completely destroy and empty the sticky file uploader cache [11]
            st.session_state.uploader_key_version = st.session_state.get("uploader_key_version", 0) + 1
            st.rerun()
            
        st.write("---")
        # Retrieve latest database records to compile autofill dropdowns
        all_db_items = data_manager.search_records(record_type=record_type)
        
        if mode == "Bulk Excel (XLSX) Transmittal Import":
            st.markdown("#### 📂 Drag-and-Drop Transmittal Importer")
            st.caption("Upload one or more Excel files. Map your column headers below, then click Parse to load them into the editable preview.")
            
            # Enable multi-file uploading with a dynamic key version to prevent sticky file caches [11]
            uploader_ver = st.session_state.get("uploader_key_version", 0)
            uploaded_files = st.file_uploader("Upload XLSX / XLS File(s)", type=["xlsx", "xls"], accept_multiple_files=True, key=f"excel_file_uploader_v{uploader_ver}")
            
            if "import_df" not in st.session_state:
                st.session_state.import_df = None

            if uploaded_files:
                import pandas as pd
                
                # Read columns of the first file to compile the interactive mapper
                try:
                    sample_df = pd.read_excel(uploaded_files[0])
                    raw_cols = ["-- Select / None --"] + [str(c) for c in sample_df.columns]
                    
                    # Fuzzy Auto-Selector Helper
                    def find_fuzzy_match(target_keywords, columns):
                        for idx, col in enumerate(columns):
                            c_lower = col.lower()
                            if any(k in c_lower for k in target_keywords):
                                return idx
                        return 0
                        
                    st.markdown("##### 🗺️ Interactive Column Header Mapper")
                    st.caption("Verify or map which column headers in your Excel sheet match our database fields:")
                    
                    map_col1, map_col2, map_col3, map_col4 = st.columns(4)
                    with map_col1:
                        map_name = st.selectbox("Applicant Name Column", raw_cols, index=find_fuzzy_match(["buyer", "applicant", "name"], raw_cols))
                        map_addr = st.selectbox("Address / Location Column", raw_cols, index=find_fuzzy_match(["subdivision", "location", "address"], raw_cols))
                    with map_col2:
                        map_cost = st.selectbox("Cost / Fee Column", raw_cols, index=find_fuzzy_match(["cost", "price", "amount", "fee"], raw_cols))
                        map_wp = st.selectbox("WP Number Column", raw_cols, index=find_fuzzy_match(["wp", "permit"], raw_cols))
                    with map_col3:
                        map_bp = st.selectbox("BP Number Column (Optional)", raw_cols, index=find_fuzzy_match(["bp", "b.p"], raw_cols))
                        map_coo = st.selectbox("COO Number Column (Optional)", raw_cols, index=find_fuzzy_match(["coo", "c.o.o"], raw_cols))
                    with map_col4:
                        map_date = st.selectbox("Date / Time Column (Optional)", raw_cols, index=find_fuzzy_match(["date", "time", "created"], raw_cols))
                        missing_wp_action = st.selectbox("For Empty WP Numbers:", ["Auto-Generate (WP-MM-YY...)", "Leave Blank (Require Manual Entry)"])
                        
                    st.write("")
                    
                    # TRANSACTIONAL GATES: Buttons controlling exactly when parsing happens
                    act_col1, act_col2, _ = st.columns([1.5, 1.8, 3])
                    
                    # Setup parse flags
                    run_parse_new = False
                    run_parse_append = False
                    
                    with act_col1:
                        if st.button("📂 Parse & Load as New Queue", use_container_width=True):
                            run_parse_new = True
                    with act_col2:
                        # Append is only enabled if there's already active data on screen to protect
                        append_disabled = st.session_state.import_df is None or len(st.session_state.import_df) == 0
                        if st.button("➕ Parse & Append to Current Queue", use_container_width=True, disabled=append_disabled, help="Parses the newly uploaded files and appends them to the end of your current edited list without losing your previous edits."):
                            run_parse_append = True
                            
                    # EXECUTING TRANSACTIONS (DUPES-PROOFED)
                    if run_parse_new or run_parse_append:
                        # Defensive initialization
                        if "processed_file_names" not in st.session_state:
                            st.session_state.processed_file_names = set()
                        all_parsed_dfs = []
                        files_to_parse = []
                        
                        if run_parse_new:
                            files_to_parse = uploaded_files
                            st.session_state.processed_file_names = set() # Reset for clean queue
                        elif run_parse_append:
                            # Filter files: Only parse spreadsheets that ARE NOT in our file register
                            files_to_parse = [f for f in uploaded_files if f.name not in st.session_state.processed_file_names]
                            
                        if not files_to_parse:
                            if run_parse_append:
                                st.warning("⚠️ All uploaded files are already parsed and inside the queue. No new files to append!")
                        else:
                            for uploaded_file in files_to_parse:
                                raw_df = pd.read_excel(uploaded_file)
                                clean_df = pd.DataFrame(index=range(len(raw_df)))
                                clean_df["Select"] = True
                                
                                # Map columns using the user's dropdown selections
                                def get_mapped_val(col_sel, default_val=""):
                                    if col_sel == "-- Select / None --": return pd.Series([default_val]*len(raw_df))
                                    return raw_df.get(col_sel, pd.Series([default_val]*len(raw_df))).fillna(default_val)
                                    
                                clean_df["applicant_name"] = get_mapped_val(map_name, "").astype(str).str.strip().str.upper()
                                clean_df["applicant_name"] = clean_df["applicant_name"].apply(lambda x: "" if x in ("0", "0.0", "NAN", "NONE") else x)
                                
                                # Rule 6: Handle Empty WP Numbers based on user preference
                                raw_wp_col = get_mapped_val(map_wp, "").astype(str).str.strip().str.upper()
                                if missing_wp_action == "Auto-Generate (WP-MM-YY...)":
                                    clean_df["wp_number"] = raw_wp_col.apply(lambda x: "PENDING (AUTO)" if not x or x in ("NAN", "NONE") else x)
                                else:
                                    clean_df["wp_number"] = raw_wp_col.apply(lambda x: "" if not x or x in ("NAN", "NONE") else x)
                                
                                # Store raw date for later auto-generation mapping (hidden column)
                                clean_df["_raw_date"] = get_mapped_val(map_date, "").astype(str)
                                
                                # Barangay Extraction Logic
                                import re
                                official_brgys = [
                                    "AMAYA I", "AMAYA II", "AMAYA III", "AMAYA IV", "AMAYA V", "AMAYA VI", "AMAYA VII", "AMAYA VI-VII", 
                                    "DAANG AMAYA I", "DAANG AMAYA II", "DAANG AMAYA III", "BAGTAS", "BIGA", "BIWAS", "BUCAL", "BUNGA", 
                                    "CALIBUYO", "CAPIPISA", "HALAYHAY", "SAHUD-ULAN", "JULUGAN I", "JULUGAN II", 
                                    "JULUGAN III", "JULUGAN IV", "JULUGAN V", "JULUGAN VI", "JULUGAN VII", "JULUGAN VIII", "LAMBINGAN", 
                                    "MULAWIN", "SANJA MAYOR", "SANTOL", "TANAUAN", "TRES CRUSES", "POBLACION I", "POBLACION II", 
                                    "POBLACION III", "POBLACION IV", "PARADAHAN I", "PARADAHAN II", "PUNTA I", "PUNTA II"
                                ]
                                brgy_pattern = re.compile(r'\b(' + '|'.join([b.replace(" ", r"\s+") for b in official_brgys]) + r')\b', re.IGNORECASE)
                                
                                extracted_brgys = []
                                clean_addresses = []
                                raw_addr_col = get_mapped_val(map_addr, "").astype(str).str.strip().str.upper()
                                
                                for addr in raw_addr_col:
                                    if addr in ("NAN", "NONE", ""):
                                        extracted_brgys.append("-- Select Barangay --")
                                        clean_addresses.append("")
                                        continue
                                    match = brgy_pattern.search(addr)
                                    if match:
                                        found_b = re.sub(r'\s+', ' ', match.group(0).upper())
                                        extracted_brgys.append(found_b)
                                        clean_addr = brgy_pattern.sub("", addr).strip(" ,-")
                                        clean_addr = re.sub(r',\s*,', ',', clean_addr).strip(" ,-")
                                        clean_addresses.append(clean_addr)
                                    else:
                                        extracted_brgys.append("-- Select Barangay --")
                                        clean_addresses.append(addr)
                                        
                                clean_df["address"] = clean_addresses
                                clean_df["barangay"] = extracted_brgys
                                clean_df["occupancy"] = "RESIDENTIAL"
                                clean_df["installation"] = "NEW"
                                
                                clean_df["bp_number"] = get_mapped_val(map_bp, "").astype(str).str.strip().str.upper().replace("NAN", "")
                                clean_df["coo_number"] = get_mapped_val(map_coo, "").astype(str).str.strip().str.upper().replace("NAN", "")
                                clean_df["or_number"] = ""
                                
                                # Map cost safely using our cleanCost converter
                                cost_series = get_mapped_val(map_cost, 0.0)
                                clean_df["total_cost"] = cost_series.apply(data_manager.clean_numeric_cost)
                                
                                # --- FIX 11: DEFENSIVE TRAFFIC LIGHT DUPLICATE IDENTIFIER ---
                              
                                # --- Safe Coercion to Prevent 'NoneType' AttributeErrors ---
                                existing_wps = {
    (str(item.get("wp_number") or "") if isinstance(item, dict) else str(getattr(item, "wp_number", "") or "")).strip().upper()
                                    for item in all_db_items if item
                                }
                                existing_names = {
    (str(item.get("applicant_name") or "") if isinstance(item, dict) else str(getattr(item, "applicant_name", "") or "")).strip().upper()
                                    for item in all_db_items if item
                                }

                                existing_wps.discard("")
                                existing_names.discard("")

                                
                                statuses = []
                                selections = []
                                for idx, row in clean_df.iterrows():
                                    wp_val = row["wp_number"]
                                    name_val = row["applicant_name"]
                                    
                                    if wp_val and wp_val not in ("PENDING (AUTO)", "") and wp_val in existing_wps:
                                        statuses.append("🔴 DUP WP")
                                        selections.append(False) # Keep hard duplicate permit numbers unchecked
                                    elif name_val and name_val in existing_names:
                                        statuses.append("🟡 DUP NAME")
                                        selections.append(True)  # UX Upgrade: Keep repeat clients checked, just show yellow flag
                                    else:
                                        statuses.append("🟢 NEW")
                                        selections.append(True)
                                        
                                clean_df.insert(1, "Status", statuses)
                                clean_df["Select"] = selections
                                
                                all_parsed_dfs.append(clean_df)
                                # Log filename into our processed file register
                                st.session_state.processed_file_names.add(uploaded_file.name)
                                
                            if all_parsed_dfs:
                                newly_parsed_df = pd.concat(all_parsed_dfs, ignore_index=True)
                                
                                if run_parse_new:
                                    st.session_state.import_df = newly_parsed_df
                                    st.toast("📂 Loaded new import queue successfully!")
                                elif run_parse_append:
                                    # Append directly to the active, edited data editor frame to protect edits!
                                    st.session_state.import_df = pd.concat([st.session_state.get("active_edited_df"), newly_parsed_df], ignore_index=True)
                                    st.toast("➕ Appended new records successfully!")
                                    
                            st.rerun()
                        
                except Exception as e:
                    st.error(f"Failed to read column structures from uploaded Excel file: {e}")
                    
            if st.session_state.get("import_df") is not None:
                st.markdown("---")
                st.markdown("##### 📝 Editable Data Preview")
                st.info("Review the extracted data below. You can fix missing Barangays or edit typos directly inside the table before committing.")
                
                official_brgys_list = [
                        "AMAYA I", "AMAYA II", "AMAYA III", "AMAYA IV", "AMAYA V", "AMAYA VI", "AMAYA VII", "AMAYA VI-VII", 
                        "DAANG AMAYA I", "DAANG AMAYA II", "DAANG AMAYA III", "BAGTAS", "BIGA", "BIWAS", "BUCAL", "BUNGA", 
                        "CALIBUYO", "CAPIPISA", "HALAYHAY", "SAHUD-ULAN", "JULUGAN I", "JULUGAN II", 
                        "JULUGAN III", "JULUGAN IV", "JULUGAN V", "JULUGAN VI", "JULUGAN VII", "JULUGAN VIII", "LAMBINGAN", 
                        "MULAWIN", "SANJA MAYOR", "SANTOL", "TANAUAN", "TRES CRUSES", "POBLACION I", "POBLACION II", 
                        "POBLACION III", "POBLACION IV", "PARADAHAN I", "PARADAHAN II", "PUNTA I", "PUNTA II"
                ]
                
                # Render interactive Data Editor for spot-editing
                edited_import_df = st.data_editor(
                    st.session_state.import_df,
                    column_config={
                        "Select": st.column_config.CheckboxColumn("Import?", width="small"),
                        "Status": st.column_config.TextColumn("Status", width="small", disabled=True),
                        "_raw_date": None, # Hide internal mapping field
                        "barangay": st.column_config.SelectboxColumn("Barangay", options=["-- Select Barangay --"] + official_brgys_list, required=True),
                        "occupancy": st.column_config.SelectboxColumn("Occupancy", options=["RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL", "INSTITUTIONAL"], required=True),
                        "installation": st.column_config.SelectboxColumn("Installation", options=["NEW", "TEMPORARY", "REMODEL", "RELOCATION", "SEPARATION", "RECONNECTION"], required=True),
                        "total_cost": st.column_config.NumberColumn("Total Cost", format="₱%,.2f")
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="import_data_editor"
                )
                
                # Save edits to a temporary session state variable so we can append to them if needed
                st.session_state.active_edited_df = edited_import_df
                
                rows_to_import = edited_import_df[edited_import_df["Select"] == True]
                missing_info = rows_to_import[
                    (rows_to_import["barangay"] == "-- Select Barangay --") | 
                    (rows_to_import["applicant_name"].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"])) |
                    (rows_to_import["address"].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"])) |
                    (rows_to_import["wp_number"].astype(str).str.strip().str.upper() == "") # Blocks blank WPs
                ]
                # --- FIX: RESTORED COLUMN DEFINITIONS & COMMIT LOOP ---
                imp_col1, imp_col2 = st.columns([1, 2])
                with imp_col1:
                    err_key = "import_batch_error"
                    if err_key in st.session_state and st.session_state[err_key]:
                        st.error(st.session_state[err_key])
                        
                    def lock_import_btn():
                        st.session_state.is_importing_batch = True
                        st.session_state[err_key] = None
                        
                    is_importing = st.session_state.get("is_importing_batch", False)
                    btn_disabled = is_importing or len(missing_info) > 0 or len(rows_to_import) == 0
                    btn_label = "⏳ Committing to Database..." if is_importing else f"🚀 Commit {len(rows_to_import)} Records to Database"
                    
                    st.button(btn_label, type="primary", disabled=btn_disabled, on_click=lock_import_btn, key="commit_import_btn")
                    
                    if is_importing:
                        try:
                            batch_id = f"BATCH-{datetime.now(PHT).strftime('%Y%m%d-%H%M')}"
                            success_count = 0
                            ip_addr, device_name = get_client_metadata()
                            
                            current_wp_seqs = {} # Cache sequences for different month/year prefixes
                            
                            for idx, row in rows_to_import.iterrows():
                                final_wp = str(row["wp_number"]).strip()
                                
                                # --- FIX 4: AUTO-INCREMENT FOR ANY PENDING OR BLANK WP ---
                                if final_wp in ("PENDING", "PENDING (AUTO)", "", "NONE", "NAN") or "PENDING" in final_wp.upper():

                                    target_date = datetime.now(timezone.utc)
                                    raw_d = str(row.get("_raw_date", "")).strip()
                                    if raw_d and raw_d not in ("NAN", "NONE"):
                                        try:
                                            import pandas as pd
                                            parsed = pd.to_datetime(raw_d, errors='coerce')
                                            if not pd.isna(parsed):
                                                target_date = parsed.to_pydatetime().replace(tzinfo=timezone.utc)
                                        except Exception:
                                            pass
                                            
                                    wp_prefix = f"WP-{target_date.strftime('%m-%y')}-"
                                    if wp_prefix not in current_wp_seqs:
                                        current_wp_seqs[wp_prefix] = int(data_manager.get_next_wp_sequence(record_type=record_type, target_date=target_date))
                                        
                                    final_wp = f"{wp_prefix}{current_wp_seqs[wp_prefix]:04d}"
                                    current_wp_seqs[wp_prefix] += 1
                                    
                                res = data_manager.create_record(
                                    operator=user, 
                                    record_type=record_type, 
                                    wp_number=final_wp, 
                                    applicant_name=str(row["applicant_name"]), 
                                    address=str(row["address"]),
                                    barangay=str(row["barangay"]), 
                                    occupancy=str(row["occupancy"]), 
                                    installation=str(row["installation"]),
                                    bp_number=str(row["bp_number"]), 
                                    coo_number=str(row["coo_number"]), 
                                    remarks="", 
                                    or_number=str(row["or_number"]), 
                                    signature_base64=None, 
                                    client_ip=ip_addr, 
                                    device_info=device_name, 
                                    total_cost=row["total_cost"],
                                    import_batch_id=batch_id
                                )
                                if "Success" in res:
                                    success_count += 1
                                    
                            st.session_state.success_msg = f"✅ Successfully imported {success_count} records! (Batch ID: {batch_id})"
                            st.session_state.import_df = None
                            st.session_state.active_edited_df = None
                            st.session_state[err_key] = None
                            st.session_state.is_importing_batch = False
                            st.session_state.table_id = st.session_state.get("table_id", 0) + 1
                            st.rerun()
                            
                        except Exception as e:
                            st.session_state[err_key] = f"❌ System Import Error: {str(e)}"
                            st.session_state.is_importing_batch = False
                            st.rerun()
                        
                with imp_col2:
                    if len(missing_info) > 0:
                        st.error(f"⚠️ {len(missing_info)} selected records are missing a Barangay, Name, or Address. Please fix them in the table above before committing.")
                    elif len(rows_to_import) == 0:
                        st.warning("Select at least one row to import.")
                    else:
                        st.success("All selected rows look valid and ready to import!")
        else:
            # Row 1: Permit & Applicant Information
            col1, col2 = st.columns(2)
            with col1:
                # Calculate default incremental format (e.g., WP-07-26-0005)
                now = datetime.now(timezone.utc)
                wp_prefix = f"WP-{now.strftime('%m-%y')}-"
                next_seq = data_manager.get_next_wp_sequence(record_type=record_type)
                default_wp = f"{wp_prefix}{next_seq}"
                
                # Single editable input with default pre-population
                wp_number = st.text_input("Wiring Permit (WP) Number", value=default_wp, placeholder="e.g., WP-07-26-0001", key=f"wp_number_input_{form_key}").strip().upper()
            
            with col2:
                existing_names = sorted(list(set([item["applicant_name"] for item in all_db_items if item["applicant_name"]])))
                name_select = st.selectbox(
                    "Applicant Name (Search existing or select 'New' below)",
                    ["-- Create New Applicant --"] + existing_names,
                    key=f"add_name_select_{form_key}"
                )
                applicant_name = ""
                if name_select == "-- Create New Applicant --":
                    applicant_name = st.text_input("Enter New Applicant Name", key=f"add_applicant_name_{form_key}")
                else:
                    applicant_name = name_select
                
                # Duplicate Detection Flow
                if applicant_name and applicant_name.strip():
                    normalized_name = applicant_name.strip().upper()
                    existing_record = next((item for item in all_db_items if item["applicant_name"].strip().upper() == normalized_name), None)
                    if existing_record:
                        st.warning(f"⚠️ Name Alert: An active record for '{applicant_name}' already exists in the system!")
                        col_dup1, col_dup2, col_dup3 = st.columns(3)
                        with col_dup1:
                            if st.button("Auto-Fill Matching Fields", key=f"dup_fill_{form_key}", use_container_width=True):
                                st.session_state[f"add_address_{form_key}"] = existing_record["address"]
                                st.session_state[f"add_brgy_select_{form_key}"] = existing_record["barangay"]
                                st.session_state[f"add_occ_select_{form_key}"] = existing_record["occupancy"]
                                st.session_state[f"add_inst_select_{form_key}"] = existing_record["installation"]
                                st.session_state[f"add_bp_number_{form_key}"] = existing_record["bp_number"]
                                st.session_state[f"add_coo_number_{form_key}"] = existing_record["coo_number"]
                                st.session_state[f"add_remarks_{form_key}"] = existing_record["remarks"]
                                st.session_state[f"add_or_number_{form_key}"] = existing_record["or_number"]
                                st.session_state[f"add_total_cost_{form_key}"] = str(existing_record.get("total_cost", "0.0"))
                                st.rerun()
                        with col_dup2:
                            if st.button("❌ Clear and Start Over", key=f"dup_clear_{form_key}", use_container_width=True):
                                st.session_state.form_id = st.session_state.get("form_id", 0) + 1
                                st.rerun()
                        with col_dup3:
                            st.info("To ignore this warning and save anyway, simply proceed.")
            
            # Row 2: Physical Address & Location Mapping
            col3, col4 = st.columns(2)
            with col3:
                default_address = st.session_state.get(f"add_address_{form_key}", "")
                address = st.text_input("Physical Address / Block / Lot", value=default_address, placeholder="e.g. Sitio Batumbakal", key=f"add_address_{form_key}")
            with col4:
                existing_brgys = sorted(list(set([item["barangay"] for item in all_db_items if item["barangay"]])))
                default_brgys = [
                    "AMAYA I", "AMAYA II", "AMAYA III", "AMAYA IV", "AMAYA V", "AMAYA VI",
                    "AMAYA VII", "AMAYA VI-VII", "DAANG AMAYA I", "DAANG AMAYA II", "DAANG AMAYA III", "BAGTAS",
                    "BIGA", "BIWAS", "BUCAL", "BUNGA", "CALIBUYO", "CAPIPISA", "HALAYHAY",
                    "HALAYHAY/SAHUD-ULAN", "SAHUD-ULAN", "JULUGAN I", "JULUGAN II", "JULUGAN III", "JULUGAN IV",
                    "JULUGAN V", "JULUGAN VI", "JULUGAN VII", "JULUGAN VIII", "LAMBINGAN", "MULAWIN", "SANJA MAYOR",
                    "SANTOL", "TANAUAN", "TRES CRUSES", "POBLACION I", "POBLACION II", "POBLACION III", "POBLACION IV",
                    "PARADAHAN I", "PARADAHAN II", "PUNTA I", "PUNTA II"
                ]
                all_brgy_options = sorted(list(set(default_brgys + existing_brgys)))
                default_brgy_val = st.session_state.get(f"add_brgy_select_{form_key}", "-- Select Barangay --")
                brgy_list = ["-- Select Barangay --"] + all_brgy_options
                brgy_index = brgy_list.index(default_brgy_val) if default_brgy_val in brgy_list else 0
                brgy_select = st.selectbox("Select Barangay", brgy_list, index=brgy_index, key=f"add_brgy_select_{form_key}")
                barangay = ""
                if brgy_select == "-- Select Barangay --":
                    default_manual_brgy = st.session_state.get(f"add_brgy_manual_{form_key}", "")
                    if default_brgy_val not in brgy_list and default_brgy_val != "-- Select Barangay --":
                        default_manual_brgy = default_brgy_val
                    barangay = st.text_input("Specify Custom Barangay Name", value=default_manual_brgy, key=f"add_brgy_manual_{form_key}")
                else:
                    barangay = brgy_select
            
            # Row 3: Classifications (Occupancy & Installation Types)
            col5, col6 = st.columns(2)
            with col5:
                existing_occs = sorted(list(set([item["occupancy"] for item in all_db_items if item["occupancy"]])))
                if record_type == "wp":
                    default_occs = ["COMMERCIAL", "GOVERNMENT", "INDUSTRIAL", "INSTITUTIONAL", "RESIDENTIAL"]
                else:
                    default_occs = ["COMMERCIAL", "INDUSTRIAL", "INSTITUTIONAL", "RESIDENTIAL"]
                all_occ_options = sorted(list(set(default_occs + existing_occs)))
                default_occ_val = st.session_state.get(f"add_occ_select_{form_key}", "-- Select Occupancy Type --")
                occ_list = ["-- Select Occupancy Type --"] + all_occ_options
                occ_index = occ_list.index(default_occ_val) if default_occ_val in occ_list else 0
                occ_select = st.selectbox("Select Occupancy Type", occ_list, index=occ_index, key=f"add_occ_select_{form_key}")
                occupancy = ""
                if occ_select == "-- Select Occupancy Type --":
                    default_manual_occ = st.session_state.get(f"add_occ_manual_{form_key}", "")
                    if default_occ_val not in occ_list and default_occ_val != "-- Select Occupancy Type --":
                        default_manual_occ = default_occ_val
                    occupancy = st.text_input("Specify Custom Occupancy Type", value=default_manual_occ, key=f"add_occ_manual_{form_key}")
                else:
                    occupancy = occ_select
            
            with col6:
                if record_type == "wp":
                    inst_list = ["-- Select Installation Type --", "NEW", "TEMPORARY", "REMODEL", "RELOCATION", "SEPARATION", "RECONNECTION"]
                else:
                    inst_list = ["-- Select Installation Type --", "NEW", "TEMPORARY", "RELOCATION", "SEPARATION", "RECONNECTION"]
                default_inst_val = st.session_state.get(f"add_inst_select_{form_key}", "-- Select Installation Type --")
                inst_index = inst_list.index(default_inst_val) if default_inst_val in inst_list else 0
                inst_select = st.selectbox("Select Installation Type", inst_list, index=inst_index, key=f"add_inst_select_{form_key}")
                installation = "" if inst_select == "-- Select Installation Type --" else inst_select
            
            # Row 5: Auxiliary LGU Permit Fields
            col10, col11, col12 = st.columns(3)
            with col10:
                st.markdown("**Building Permit (B.P.) Number**")
                
                # Initialize B.P. session states safely
                if "last_bp_prefix" not in st.session_state:
                    st.session_state["last_bp_prefix"] = "R"
                if "last_auto_bp_state" not in st.session_state:
                    st.session_state["last_auto_bp_state"] = False
                    
                now_utc = datetime.now(timezone.utc)
                
                # Clean auto-sync trigger checkbox
                auto_bp = st.checkbox("🔄 Auto-sync sequence generator", value=st.session_state["last_auto_bp_state"], key=f"auto_bp_chk_{form_key}")
                st.session_state["last_auto_bp_state"] = auto_bp
                
                if auto_bp:
                    # Dynamically map the selected occupancy to the correct BP Prefix
                    occ_to_prefix = {
                        "RESIDENTIAL": "R",
                        "COMMERCIAL": "C",
                        "INDUSTRIAL": "ID",
                        "INSTITUTIONAL": "IT",
                        "ELECTRICAL": "E",
                        "FENCING": "F"
                    }
                
                    # Read the active occupancy string and default to "R" if it's custom/unrecognized
                    active_occ = occupancy.strip().upper()
                    auto_prefix = occ_to_prefix.get(active_occ, "R")
                    st.session_state["last_bp_prefix"] = auto_prefix

                    bp_month = now_utc.strftime('%m')
                    bp_year = now_utc.strftime('%y')
                    
                    # Fetch next sequential ID automatically to prevent duplicates
                    bp_seq_val = data_manager.get_next_bp_sequence(st.session_state["last_bp_prefix"], bp_month, bp_year, record_type=record_type)
                    
                    # Construct final string and render locked, singular auto-box
                    bp_number_val = f"{st.session_state['last_bp_prefix']}-{bp_month}-{bp_year}-{bp_seq_val}"
                    bp_number = st.text_input("B.P. Number (Locked Auto-Sync)", value=bp_number_val, disabled=True, key=f"add_bp_number_auto_{form_key}")
                    bp_valid = True
                else:
                    # Unlock the singular box completely for custom legacy inputs
                    active_occ_hint = occupancy.strip().upper() if 'occupancy' in locals() else "R"
                    prefix_hint = {"RESIDENTIAL": "R", "COMMERCIAL": "C", "INDUSTRIAL": "ID", "INSTITUTIONAL": "IT", "ELECTRICAL": "E", "FENCING": "F"}.get(active_occ_hint, "R")
                    bp_number = st.text_input("Enter B.P. Number (Manual Override)", placeholder=f"e.g., {prefix_hint}-{now_utc.strftime('%y')}-0001", key=f"add_bp_number_manual_{form_key}")
                    bp_valid = True
            with col11:
                default_coo = st.session_state.get(f"add_coo_number_{form_key}", "")
                coo_number = st.text_input("Cert. of Occupancy (C.O.O) Number", value=default_coo, placeholder="e.g. O-2026-9811", key=f"add_coo_number_{form_key}")
            with col12:
                default_or = st.session_state.get(f"add_or_number_{form_key}", "")
                or_number = st.text_input("Official Receipt (O.R.) Number (7 Digits)", value=default_or, placeholder="e.g. 1234567", key=f"add_or_number_{form_key}")
            
            # Row 6: Remarks & Special Instructions (and Total Cost)
            if st.session_state.get("show_financials", True):
                col_cost, col_rem = st.columns([1, 2])
                with col_cost:
                    default_cost = st.session_state.get(f"add_total_cost_{form_key}", "0.0")
                    cost_str = st.text_input("Total Cost (₱)", value=str(default_cost), key=f"add_total_cost_{form_key}")
                    try:
                        clean_edit_str = re.sub(r'[^0-9.]', '', cost_str.replace("₱", "").replace(",", "").strip())
                        edit_total_cost = float(clean_edit_str) if clean_edit_str else 0.0
                    except Exception:
                        edit_total_cost = 0.0

                with col_rem:
                    default_remarks = st.session_state.get(f"add_remarks_{form_key}", "")
                    remarks = st.text_input("Remarks / Notes / Overrides", value=default_remarks, placeholder="e.g. AUTHORITY TO MOVE-IN (PAG-IBIG)", key=f"add_remarks_{form_key}")
            else:
                total_cost = 0.0
                default_remarks = st.session_state.get(f"add_remarks_{form_key}", "")
                remarks = st.text_input("Remarks / Notes / Overrides", value=default_remarks, placeholder="e.g. AUTHORITY TO MOVE-IN (PAG-IBIG)", key=f"add_remarks_{form_key}")
            
            sig_base64 = None
            st.write("---")
            ip_addr, device_name = get_client_metadata()
        
        # --- FIX: HARD-LOCK BUFFERED CLICK SPAM BLOCKER ---
            err_key = f"add_error_{form_key}"
            if err_key in st.session_state and st.session_state[err_key]:
                st.error(st.session_state[err_key])
            
            is_committed = st.session_state.get(f"committed_{form_key}", False)
            btn_text = "⏳ Saving..." if is_committed else "Commit Entry to Registry"
            
            if st.button(btn_text, type="primary", key=f"add_submit_record_btn_{form_key}", disabled=is_committed):
                # If Streamlit buffered multiple clicks during a freeze, instantly drop the duplicates
                if st.session_state.get(f"committed_{form_key}", False):
                    st.stop()
                
                # Lock the gate
                st.session_state[f"committed_{form_key}"] = True
                
                # Ironclad validations to block default/empty commits
                if not wp_number or not wp_number.strip():
                    st.session_state[err_key] = "❌ Submission Denied: Wiring Permit (WP) Number cannot be blank."
                    st.session_state[f"committed_{form_key}"] = False
                    st.rerun()
                elif not bp_valid:
                    st.session_state[err_key] = "❌ Submission Denied: Invalid Building Permit sequence."
                    st.session_state[f"committed_{form_key}"] = False
                    st.rerun()
                elif not applicant_name or not applicant_name.strip() or applicant_name == "-- Create New Applicant --":
                    st.session_state[err_key] = "❌ Submission Denied: Applicant Name cannot be blank."
                    st.session_state[f"committed_{form_key}"] = False
                    st.rerun()
                elif not address or not address.strip():
                    st.session_state[err_key] = "❌ Submission Denied: Physical Address cannot be blank."
                    st.session_state[f"committed_{form_key}"] = False
                    st.rerun()
                elif not barangay or not barangay.strip() or barangay == "-- Select Barangay --":
                    st.session_state[err_key] = "❌ Submission Denied: Barangay selection cannot be blank."
                    st.session_state[f"committed_{form_key}"] = False
                    st.rerun()
                elif not occupancy or not occupancy.strip() or occupancy == "-- Select Occupancy Type --":
                    st.session_state[err_key] = "❌ Submission Denied: Occupancy Type selection cannot be blank."
                    st.session_state[f"committed_{form_key}"] = False
                    st.rerun()
                elif not installation or not installation.strip() or installation == "-- Select Installation Type --":
                    st.session_state[err_key] = "❌ Submission Denied: Installation Type selection cannot be blank."
                    st.session_state[f"committed_{form_key}"] = False
                    st.rerun()
                else:
                    try:
                        # --- REAL-TIME LATENCY & CONCURRENCY COLLISION CHECK ---
                        clean_wp_check = wp_number.strip().upper()
                        clean_bp_check = bp_number.strip().upper() if (bp_number and bp_number.strip()) else ""
                        
                        with database.get_db() as check_db:
                            ModelClass = database.WiringPermitRecord if record_type == "wp" else database.MainRecord
                            dup_wp_rec = check_db.query(ModelClass).filter(ModelClass.wp_number == clean_wp_check, ModelClass.is_deleted == False).first()
                            dup_bp_rec = check_db.query(ModelClass).filter(ModelClass.bp_number == clean_bp_check, ModelClass.is_deleted == False).first() if clean_bp_check else None

                        if dup_wp_rec:
                            st.session_state[err_key] = f"⚠️ Concurrency Conflict: WP Number '{clean_wp_check}' was just saved by another operator! Please change the WP sequence number above and re-submit."
                            st.session_state[f"committed_{form_key}"] = False
                            st.rerun()
                        elif dup_bp_rec:
                            st.session_state[err_key] = f"⚠️ Concurrency Conflict: Building Permit Number '{clean_bp_check}' was just saved by another operator! Please change the B.P. sequence number above and re-submit."
                            st.session_state[f"committed_{form_key}"] = False
                            st.rerun()
                        else:
                            result = data_manager.create_record(
                                operator=user,
                                record_type=record_type,
                                wp_number=wp_number,
                                applicant_name=applicant_name,
                                address=address,
                                barangay=barangay,
                                occupancy=occupancy,
                                installation=installation,
                                bp_number=bp_number,
                                coo_number=coo_number,
                                remarks=remarks,
                                or_number=or_number,
                                signature_base64=sig_base64,
                                client_ip=ip_addr,
                                device_info=device_name,
                                total_cost=total_cost
                            )
                        if "Success" in result:
                            st.session_state["last_auto_bp_state"] = auto_bp
                            st.session_state.form_id = st.session_state.get("form_id", 0) + 1
                            st.session_state.success_msg = f"Record for '{applicant_name.strip().upper()}' successfully added!"
                            st.session_state[err_key] = None
                            st.session_state[f"is_saving_{form_key}"] = False
                            st.rerun()
                        else:
                            st.session_state[err_key] = result
                            st.session_state[f"is_saving_{form_key}"] = False
                            st.rerun()
                    except Exception as e:
                        # Catch and route any raw SQLite database locking crashes
                        st.session_state[err_key] = f"❌ Database System Error: {str(e)}"
                        st.session_state[f"is_saving_{form_key}"] = False
                        st.rerun()
    else:
        st.warning("🔒 Your current role does not have adding privileges.")

# ------------------------------------------
# TAB 3: SYSTEM AUDIT LOGS (ADMIN, MANAGER, AUDITOR ONLY)
# ------------------------------------------
if "Audit Action Logs" in tab_list:
    with tabs[tab_list.index("Audit Action Logs")]:
        st.subheader("🛡️ System Audit Logs")
        st.write("This table tracks real-time database modifications directly from the server. No 'viewing' actions are captured.")
        
        logs = data_manager.get_audit_logs(user)
        if logs:
            st.dataframe(pd.DataFrame(logs), width="stretch", hide_index=True)
        else:
            st.info("No logs present in the database.")


# ------------------------------------------
# TAB 4: USER ACCOUNTS ADMIN (SUPER ADMIN ONLY)
# ------------------------------------------
if "User Accounts Admin" in tab_list:
    with tabs[tab_list.index("User Accounts Admin")]:
        st.subheader("👥 User Account Provisions & Management")
        st.write("As a Super Admin, you can provision new accounts, modify clearances, delete accounts, or reset lost passwords.")
        
        st.write("---")
        
        # ==============================================================================
        # 🛡️ THE SECURITY & ACCESS CONTROL CONSOLE (ROOT-ADMIN ONLY EXCLUSIVE PANEL)
        # ==============================================================================
        st.markdown("### 🛡️ Master Security & Access Control Console")
        
        primary_admin = "admin"
        is_root = (user["username"] == primary_admin)
        
        acc_freeze_file = "account_freeze.txt"
        sys_lock_file = "system_lock.txt"
        
        is_acc_frozen = os.path.exists(acc_freeze_file)
        is_sys_locked = os.path.exists(sys_lock_file)
        
        if not is_root:
            # Secondary Super Admins cannot see or toggle these buttons. They only see read-only warnings.
            st.warning("🔒 Root Security Locks are currently managed by the Primary System Creator. You do not possess the clearance to toggle administrative freezes.")
            col_warn1, col_warn2 = st.columns(2)
            with col_warn1:
                if is_acc_frozen:
                    st.error("⚠️ Account Management is currently FROZEN by the Root Admin.")
                else:
                    st.success("✓ Account Management is Normal (Unfrozen).")
            with col_warn2:
                if is_sys_locked:
                    st.error("⚠️ Database write access is currently LOCKED DOWN by the Root Admin.")
                else:
                    st.success("✓ Database write access is Normal (Unlocked).")
        else:
            # ONLY the Root Admin (primary_admin) can see, interact with, and toggle these buttons!
            st.info(f"Welcome, Root Administrator `{primary_admin}`. You hold exclusive authority to freeze or lock down the system.")
            
            col_sec_1, col_sec_2 = st.columns(2)
            
            # CONSOLE 1: ACCOUNT MANAGEMENT FREEZE (FULLY AUDITED)
            with col_sec_1:
                st.markdown("#### 👤 Account Management Freeze")
                st.write("Freezes all user account provisions, role changes, password resets, and account deletions for everyone except yourself.")
                
                if is_acc_frozen:
                    st.error("🔒 STATUS: ACCOUNT FREEZE ACTIVE (All secondary admins blocked)")
                    if st.button("🔓 UNFREEZE ACCOUNT MANAGEMENT", key="unfreeze_acc_btn", type="primary"):
                        try:
                            os.remove(acc_freeze_file)
                            ip_addr, device_name = get_client_metadata()
                            # Writes a secure, traceable log of the freeze lifting
                            with database.get_db() as db:
                                auth.log_admin_action(db, user["username"], "Account management freeze lifted. Permissions restored to normal.", ip_addr, device_name)
                            st.success("✓ Account freeze lifted.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                else:
                    st.success("✓ STATUS: ACCOUNT MANAGEMENT NORMAL")
                    if st.button("🔒 FREEZE ACCOUNT MANAGEMENT", key="freeze_acc_btn", type="secondary"):
                        try:
                            with open(acc_freeze_file, "w") as f:
                                f.write(f"Frozen by Root Admin at {datetime.now(timezone.utc)}")
                            ip_addr, device_name = get_client_metadata()
                            # Writes a secure, traceable log of the account freeze
                            with database.get_db() as db:
                                auth.log_admin_action(db, user["username"], "ACCOUNT MANAGEMENT FREEZE TRIGGERED. Secondary admin operations locked.", ip_addr, device_name)
                            st.warning("Account management frozen successfully.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

            # CONSOLE 2: SYSTEM DATABASE LOCKDOWN (FULLY AUDITED)
            with col_sec_2:
                st.markdown("#### 🚨 Database System Lockdown (Panic Switch)")
                st.write("Freezes the entire database in Read-Only mode for everyone except yourself. All inserts, edits, and deletions will be strictly blocked.")
                
                if is_sys_locked:
                    st.error("🛑 STATUS: SYSTEM DATABASE LOCKDOWN ACTIVE")
                    confirm_unlock = st.checkbox("I confirm that I want to lift the secure database lockdown.", key="confirm_unlock_checkbox")
                    if st.button("🔓 LIFT DATABASE LOCKDOWN", key="unlock_sys_btn", type="primary", disabled=not confirm_unlock):
                        try:
                            os.remove(sys_lock_file)
                            ip_addr, device_name = get_client_metadata()
                            # Writes a secure, traceable log of the database unlocking
                            with database.get_db() as db:
                                auth.log_admin_action(db, user["username"], "Critical database lockdown lifted. Write access restored.", ip_addr, device_name)
                            st.success("✓ Database lockdown lifted successfully.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                else:
                    st.success("✓ STATUS: DATABASE WRITE ACCESS NORMAL")
                    # To prevent "oopsies" and accidental clicks, the lockdown button is completely disabled until checked
                    confirm_lock = st.checkbox("⚠️ Check this box to enable the Lockdown trigger button.", key="confirm_lock_checkbox")
                    if st.button("🚨 TRIGGER SYSTEM DATABASE LOCKDOWN", key="lock_sys_btn", type="primary", disabled=not confirm_lock, help="Requires checking the confirmation box first."):
                        try:
                            with open(sys_lock_file, "w") as f:
                                f.write(f"Locked down by Root Admin at {datetime.now(timezone.utc)}")
                            ip_addr, device_name = get_client_metadata()
                            # Writes a secure, traceable log of the database lockdown
                            with database.get_db() as db:
                                auth.log_admin_action(db, user["username"], "CRITICAL DATABASE LOCKDOWN TRIGGERED. System frozen in Read-Only mode.", ip_addr, device_name)
                            st.error("System database lockdown triggered successfully.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                            
        st.write("---")
        col_create, col_manage = st.columns(2)
        
        # Column A: Create New User
        with col_create:
            st.markdown("#### ➕ Create New Account")
            with st.form("create_user_form", clear_on_submit=True):
                new_username = st.text_input("New Username")
                new_password = st.text_input("New User Password", type="password")
                new_role = st.selectbox("Role Assignment Clearance", list(auth.ROLE_PERMISSIONS.keys()))
                
                submit_user = st.form_submit_button("Generate Secure Credentials")
                
                if submit_user:
                    ip_addr, device_name = get_client_metadata()
                    result = auth.create_user(user["username"], new_username, new_password, new_role, ip_addr, device_name)
                    if "Success" in result:
                        st.success(result)
                    else:
                        st.error(result)

        # Column B: Modify Clearances, Delete, and Reset Passwords
        with col_manage:
            st.markdown("#### 🔧 Manage Existing Accounts")
            
            with database.get_db() as db:
                all_users = db.query(database.User).all()
                user_list = [u.username for u in all_users if u.username != user["username"]]
            
            if not user_list:
                st.info("No other user accounts exist on the server database to manage.")
            else:
                target_user = st.selectbox("Select Target User Account", user_list, key="manage_user_dropdown")
                
                # Retrieve current details of chosen target user
                with database.get_db() as db:
                    target_obj = db.query(database.User).filter(database.User.username == target_user).first()
                    current_role = target_obj.role if target_obj else "Contributor"
                
                # Section B1: Update Clearance Level
                st.markdown("##### 🔰 Edit Clearance Level")
                role_options = list(auth.ROLE_PERMISSIONS.keys())
                role_index = role_options.index(current_role) if current_role in role_options else 0
                edit_user_role = st.selectbox("Change Security Role", role_options,
index=role_index, key=f"change_user_role_select_{target_user}")
                
                if st.button("Apply New Clearance Role", key="apply_role_btn"):
                    ip_addr, device_name = get_client_metadata()
                    res = auth.change_user_role(user["username"], target_user, edit_user_role, ip_addr, device_name)
                    if "Success" in res:
                        st.success(res)
                        st.rerun()
                    else:
                        st.error(res)
                
                st.write("---")
                
                # Section B2: Overwrite Password
                st.markdown("##### 🔑 Overwrite Lost Password")
                temp_password = st.text_input("Enter Temporary New Password", type="password", key="reset_pass_input")
                
                if st.button("Reset Account Password", type="primary", key="reset_pass_btn"):
                    ip_addr, device_name = get_client_metadata()
                    res = auth.reset_user_password(user["username"], target_user, temp_password, ip_addr, device_name)
                    if "Success" in res:
                        st.success(res)
                    else:
                        st.error(res)
                
                st.write("---")
                
                # Section B3: Revoke Access (Delete User)
                st.markdown("##### 🗑️ Revoke Account Access")
                st.warning(f"Permanently deleting '{target_user}' is un-doable and logged on the server.")
                confirm_revoke = st.checkbox(f"I confirm that I want to delete the user account '{target_user}'")
                
                if st.button(f"Delete Account '{target_user}'", type="primary", disabled=not confirm_revoke, key="delete_user_btn"):
                    ip_addr, device_name = get_client_metadata()
                    res = auth.delete_user(user["username"], target_user, ip_addr, device_name)
                    if "Success" in res:
                        st.success(res)
                        st.rerun()
                    else:
                        st.error(res)

                st.write("---")

                # Section B4: Kick User & Force Logout
                st.markdown("##### ⚡ Administrative Kick & Release Locks")
                st.write("Forces an immediate logout on the target user's terminal and releases all database locks they are currently holding.")
                
                # Root Protection: Prevent any user from kicking the primary/root administrator
                primary_admin = os.getenv("INITIAL_ADMIN_USER", "admin")
                is_target_root = (target_user == primary_admin)
                
                if is_target_root:
                    st.warning("🔒 Protection Active: The primary system administrator cannot be kicked.")
                
                if st.button(f"Kick User '{target_user}'", type="primary", key="kick_user_btn", disabled=is_target_root):
                    ip_addr, device_name = get_client_metadata()
                    
                    # 1. Register administrative kick (completely non-destructive, leaves database credentials intact)
                    import cloud_sync as cs
                    cs.register_administrative_kick(target_user)
                    
                    # Write trace to log
                    import database as app_database
                    import auth as security_auth
                    with app_database.get_db() as db:
                        security_auth.log_admin_action(db, user["username"], f"ADMIN KICK: Planted logout flag for '{target_user}'.", ip_addr, device_name)
                            
                    # 2. Delete all lock files associated with this user on Google Drive
                    released_count = 0
                    if cs.SYNC_ACTIVE:
                        try:
                            lock_files = glob.glob(os.path.join(cs.DIRS["edit_locks"], "*.lock"))
                            for lf in lock_files:
                                with open(lf, "r") as f:
                                    data = json.load(f)
                                    if data.get("username") == target_user:
                                        os.remove(lf)
                                        released_count += 1
                        except Exception as e:
                            print(f"Error releasing lock files: {e}")
                    
                    # Show success without triggering a global DOM shift (prevents the UI from teleporting out of the tab)
                    lock_txt = f" and released {released_count} locked records" if released_count else ""
                    st.success(f"✓ Kicked '{target_user}' successfully{lock_txt}.")

