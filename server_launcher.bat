@echo off
:: Forces Windows to change directory to where this batch file is located
cd /d "%~dp0"

:: Verify if port 443 is actively LISTENING on your local machine (ignoring outbound HTTPS connections)
netstat -ano | findstr /R ":443 " | findstr LISTENING >nul 2>&1
if %errorlevel% equ 0 (
    echo ===================================================
    echo [WARNING] Port 443 is currently in use!
    echo This could be a lingering zombie process from a previous crash.
    echo ===================================================
    echo.
    set /p "kill_zombie=Would you like to force close lingering Python server instances? [Y/N]: "
    if /i "%kill_zombie%"=="Y" (
        taskkill /f /im python.exe /t >nul 2>&1
        taskkill /f /im streamlit.exe /t >nul 2>&1
        timeout /t 2 >nul
    ) else (
        echo Please close any other software using Port 443 before running.
        pause
        exit /b
    )
)

:: 1. CHECK AND AUTOMATICALLY GENERATE SECURE HTTPS CERTIFICATES
if not exist cert.pem (
    echo ===================================================
    echo [0/3] Setting Up Secure Local HTTPS Certificates...
    echo ===================================================
    echo Downloading official secure mkcert utility from GitHub...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; Invoke-WebRequest -Uri 'https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-windows-amd64.exe' -OutFile 'mkcert.exe'"
    
    echo.
    echo Installing Local Certificate Authority in Windows Vault...
    mkcert.exe -install
    
    echo.
    echo Generating SSL certificates specifically bound to this PC name...
    mkcert.exe -cert-file cert.pem -key-file key.pem localhost %COMPUTERNAME% 127.0.0.1
    
    echo.
    echo Cleaning up setup files...
    del /q mkcert.exe
    echo HTTPS Certificates successfully generated and secured!
    echo.
)

:: Automatically locks down the database file so only the current Windows user can touch it
if exist app_database.db icacls app_database.db /inheritance:r /grant "%USERNAME%":F >nul 2>&1

:: Automatically locks down the .env file so only the active Windows user can read it
if exist .env icacls .env /inheritance:r /grant "%USERNAME%":F >nul 2>&1


echo ===================================================
echo [1/3] Setting up Python Virtual Environment...
echo ===================================================
if not exist venv (
    python -m venv venv
)

echo.
echo ===================================================
echo [2/3] Installing/Updating Safe Dependencies...
echo ===================================================
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ===================================================
echo [3/3] Starting Secure Server on HTTPS (Port 443)...
echo ===================================================
streamlit run app.py --server.port=443 --server.sslCertFile=cert.pem --server.sslKeyFile=key.pem --server.headless true

pause