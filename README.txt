======================================================================== 
LGU PERMITTING PORTAL - USER SETUP GUIDE
========================================================================

STATUS: Offline departmental prototype for feasibility testing only.

⚠️ PHYSICAL SECURITY WARNING (CRITICAL)

This database runs entirely off the main computer's hard drive.

  - YOU MUST set a strong password on the main computer's Windows account.
  - DO NOT allow unauthorized people to use or sit at the main computer.
  - DO NOT delete or lose your ".env" file; it contains the secret keys needed
    to decrypt and display handwritten signatures on the screen.



I.  PREREQUISITES (FOR THE MAIN SERVER PC)

1.  Download Python (recommended: Python 3.12.x or 3.13.x) from python.org.

2.  Run the installer and check the box at the very bottom:

    [X] Add python.exe to PATH

    (If you miss this step, the launch script will fail. Re-run the installer
    and check the box if needed).

3.  ⚠️ IMPORTANT OFFICIAL RECEIPT (O.R.) NUMBER RULE: The database strictly
    validates payment inputs. Official Receipt (O.R.) numbers MUST be entered in
    the exact format of a 7-digit number (for example: 1234567 or 9876543). If 
    you do not type it as exactly 7 digits, the system will block your save 
    and show an error.



II.  HOW TO SET UP THE DESKTOP SHORTCUT (SECURE HTTPS - PORT 443)

The portal is configured to run on secure HTTPS (Port 443). This encrypts all
data travelling over local office Wi-Fi. To run on Port 443, the script must be
launched with Administrator privileges.

Create a safe, dedicated desktop launcher:

1.  Right-click the file named "server_launcher.bat" inside this folder.
2.  Select "Create shortcut".
3.  Drag the new shortcut to your Desktop.
4.  Rename the shortcut to: "Launch Database Portal"
5.  Right-click the desktop shortcut and select "Properties".
6.  Under the "Shortcut" tab, click the "Advanced..." button.
7.  Check the box that says "Run as administrator".
8.  Click "OK", then click "Apply".



III.  FIRST-TIME LAUNCH

1.  Double-click your "Launch Database Portal" desktop shortcut.
2.  A black terminal window will open requesting admin permission.
3.  THE FIRST TIME YOU RUN THIS:
      - It will automatically download the local security certificates (mkcert), 
        install all required Python libraries, and build the "app_database.db".
      - This first-time setup may take a short while depending on your internet
        connection. DO NOT CLOSE the window until it finishes.
4.  SUBSEQUENT LAUNCHES:
      - The app will start almost instantly.
5.  Keep the black terminal window open in the background. Closing it turns off
    the database portal for everyone.



IV.  HOW OTHER COWORKERS CONNECT (OVER LOCAL WI-FI)

If your coworkers cannot connect to your main computer, your local office Wi-Fi
router is blocking them (usually due to a security setting called "AP/Client
Isolation").

You have two ways to connect your coworkers' devices:

METHOD A: WINDOWS MOBILE HOTSPOT (RECOMMENDED - EASIEST & 100% FREE)

If you do not have the password to your office's main Wi-Fi router, you can
bypass it completely. Your Server PC can broadcast its own local, high-speed
Wi-Fi hotspot.

1.  TURN ON HOTSPOT ON THE SERVER PC:
      - Click the Windows Start menu, open "Settings" -> "Network & Internet".
      - Click "Mobile Hotspot" and toggle it to "ON".
      - Note the network name and password displayed there.
2.  CONNECT COWORKERS:
      - On the other PCs, select the Wi-Fi network and enter the password.
3.  ACCESS THE PORTAL:
      - Open a browser on the client PC.
      - Enter your server PC's local IP address or name in the address bar.
      - TABS RENAME PRO-TIP: When printing/saving a record as a PDF, the browser
        automatically names the PDF file to match the applicant's name and WP/Registry
        details dynamically.
4.  WHY WE USE THIS:
      - It is 100% free and does not use mobile data.
      - It bypasses browser security restrictions.
      - The Server PC's IP address on this hotspot is locked by Windows to
        "192.168.137.1". Bookmark this address on client browsers so they never
        have to type it again:

        https://192.168.137.1

METHOD B: TINKERING WITH ROUTER SETTINGS (IF ROUTER IS ACCESSIBLE)

If you want coworkers to connect through your existing office Wi-Fi router, you
must configure three settings to allow communication:

1.  WINDOWS FIREWALL (ON THE SERVER PC):
      - Search your Windows Start Menu for "Windows Defender Firewall with
        Advanced Security" and open it.
      - Click "Inbound Rules" (left side) and select "New Rule..." (right side).
      - Select "Port" -> Click Next.
      - Select "TCP" and enter "443" -> Click Next.
      - Select "Allow the connection" -> Click Next.
      - Check all profile boxes (Domain, Private, Public) -> Click Next.
      - Name the rule "Streamlit Portal Port" and click Finish.
2.  NETWORK PROFILE SETTING (ON BOTH PCs):
      - Click your Wi-Fi signal icon in the bottom-right taskbar.
      - Select "Properties" on your active Wi-Fi connection.
      - Change your Network Profile Type from "Public" to "Private".
3.  AP/CLIENT ISOLATION (ON THE WIRELESS ROUTER):
      - Log into your Wi-Fi router's admin dashboard.
      - Search the wireless settings for a feature called "AP Isolation",
        "Client Isolation", or "Wireless Isolation" and set it to "Disabled".
4.  GET PERMANENT ACCESS LINK:
      - Once the local network is set to "Private", coworkers can connect using the
        server PC's name. If your computer name is "RYZEN-DESKTOP", they can
        simply type:

        https://RYZEN-DESKTOP.local



V.  EXCLUSIVE FEATURES GUIDE

The following features are now active in the portal to simplify daily use and
keep your directory clean:

  - MULTI-REGISTRY WORKSPACE: Toggle instantly between "Wiring Permits" and 
    "CFEI Records" using the sidebar. Searches, bulk edits, and imports isolate 
    themselves exclusively to your active selected registry.

  - 🟢 ACTIVE / 📁 ARCHIVED STATUS COLUMN: To prevent directory clutter, you can
    "Archive (Hide)" records that are unusable or old. Archived records vanish
    from the active search directory but are still counted in system auditing
    tallies and financial counters.

  - BULK EXCEL (XLSX) IMPORTER: Under the Add/Import tab, you can drag-and-drop 
    transmittal spreadsheets. It features an interactive column mapper and a 
    duplicate collision detector that highlights repeat names in yellow and 
    duplicate permit numbers in red.

  - PRE-PRINT QUANTITY PLANNER: Select any record (or multiple records) and click 
    "Prepare Print". This launches a planner where you can rapidly fill in 
    equipment counts and load values before generating a clean, watermarked PDF 
    form (OBO Copy, Applicant Copy, CFEI Copy).

  - FINANCIAL LEDGER & TALLY: Enable the financial ledger from the sidebar to 
    dynamically track "Total Cost" collected vs. unpaid based on specific custom 
    date ranges and building categories (e.g., Residential, Commercial, Fencing).

  - LAST MODIFIED SORTING & AUTO-RESET SEQUENCES: You can sort records by when 
    they were last updated. The 4-digit sequence at the end of Permits automatically
    restarts at "0001" at the beginning of every new calendar month.



VI.  INITIAL ADMIN LOGIN

If no active database administrator configurations are specified in your local
configuration (.env) file, log in using these default master credentials:

  - Username: admin
  - Password: TemporaryAdminPass123!

SECURITY STEP: Go to the "User Accounts Admin" tab immediately. Create your own
custom admin accounts, then change the password for this default fallback account 
to prevent security breaches.



VII.  MASTER SECURITY CONSOLE (ROOT-ADMIN ONLY)

Under the "User Accounts Admin" tab, the master System Administrator holds
exclusive buttons to activate system-wide interventions:

1.  Account Management Freeze: Prevents secondary administrators from modifying,
    deleting, or provisioning user accounts.
2.  Database System Lockdown (Panic Switch): Freezes the entire database in
    Read-Only mode. All additions, edits, and deletions are strictly blocked.
3.  Administrative Kick: Forces a logout on a specific user's terminal and 
    instantly clears any cloud locks they are holding over database records.



VIII.  HOW AUTOMATED DISASTER BACKUPS WORK

The database silently duplicates itself to your designated backup directory
locally inside the "backups" folder every time an action is saved.

To guarantee that backup files can never be corrupted, the portal runs an atomic 
OS swap process. A structural verification (PRAGMA integrity_check) is executed 
on temporary database clones before any existing backup file is replaced.

To enable automatic offsite disaster backups (highly recommended):

1.  Plug a secure USB flash drive (thumb drive) into the main computer.
2.  Note the drive letter Windows gives it (e.g. D: or E:).
3.  Open the hidden ".env" file inside this folder with Notepad.
4.  Find the line: BACKUP_DIR="backups"
5.  Change it to point to your USB drive (e.g., BACKUP_DIR="E:\App_Backups").
6.  Save the file. The portal will now automatically backup to your USB.



IX.  HOW TO ACTIVATE AUTOMATED CLOUD SYNC & MULTI-OFFICE COLLABORATION

The permitting portal includes a built-in decentralized cloud sync engine. 
When activated, it allows multiple computers in different offices to edit, 
update, and audit the database in real-time, syncing changes silently over the 
cloud using JSON changesets.

To activate Cloud Mode on any computer (Server or Client PCs):

1.  RUN THE CLOUD CONNECTOR SCRIPT:
      - Double-click the file named "install_gdrive.bat" inside this folder.
      - A terminal window will open, automatically download the official 
        Google Drive for Desktop client, and install it silently.
2.  LOG IN TO GOOGLE DRIVE:
      - Once the installation is complete, your web browser will open.
      - Log in to your department's official Tanza LGU Google Account.
      - Google Drive will map itself as a virtual disk (G:\ drive).
3.  VERIFY SYNC STATUS:
      - Launch your Permitting Portal shortcut.
      - Look at the sidebar. The portal will automatically detect your Google 
        Drive directory and toggle the status from "⚪ Local / Offline Mode" 
        to "🟢 Cloud Sync Connected".
4.  HOW MULTI-LOCK COLLABORATION WORKS:
      - When a coworker views or edits a record, the sync engine drops a 
        "flare" (edit lock) in the cloud folder.
      - If another coworker attempts to open or edit that same record, the 
        details panel will show a warning indicating exactly who is currently 
        editing it to prevent concurrent overwrites.
      - Once they close the panel, cancel changes, or log out, the lock is 
        instantly and automatically released for other users.
========================================================================