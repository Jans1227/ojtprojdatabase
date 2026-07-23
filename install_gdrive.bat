@echo off
setlocal

echo ===================================================
echo   TANZA LGU - AUTO CLOUD DRIVE INSTALLER
echo ===================================================
echo.

:: Dynamically scan the Google directory to locate GoogleDriveFS.exe or googledrive.exe
set "EXE_PATH="
for /f "delims=" %%F in ('dir /b /s "C:\Program Files\Google\GoogleDriveFS.exe" "C:\Program Files\Google\googledrive.exe" 2^>nul') do (
    set "EXE_PATH=%%F"
)
set "INSTALLER_FILE=GoogleDriveSetup.exe"

:: Check if Google Drive is already mounted (virtual drive G:) or currently running
if exist "G:\" (
    echo [INFO] Google Drive virtual drive (G:\) is already mounted and active.
    goto LAUNCH
)
tasklist /fi "imagename eq googledrive.exe" | findstr /i "googledrive.exe" >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Google Drive software is already running on this PC.
    goto LAUNCH
)

REM Clear variables to ensure clean prompts
set "choice="
set "reinstall="
set "use_existing="
set "delete_old="
set "delete_corrupt="

REM -----------------------------------------------------
REM STEP 1: Check if Google Drive is already installed
REM -----------------------------------------------------
if not exist "%EXE_PATH%" goto CHECK_LOCAL_FILE

echo [INFO] Google Drive is already installed on this PC.
echo Location: "%EXE_PATH%"
echo.
set /p "choice=Would you like to launch Google Drive now? [Y/N]: "
if /i "%choice%"=="Y" goto LAUNCH

set /p "reinstall=Do you want to proceed with a reinstallation anyway? [Y/N]: "
if /i "%reinstall%"=="Y" goto CHECK_LOCAL_FILE

echo Exiting installer...
pause
exit /b


:CHECK_LOCAL_FILE
REM -----------------------------------------------------
REM STEP 2: Check if installer file already exists locally
REM -----------------------------------------------------
set "DOWNLOAD_NEEDED=Y"
set "DELETE_AFTER_INSTALL=Y"

if not exist "%INSTALLER_FILE%" goto DOWNLOAD_SECTION

echo [INFO] Verifying local installer file digital signature...
powershell -Command "$sig = Get-AuthenticodeSignature '%INSTALLER_FILE%'; if ($sig.Status -eq 'Valid' -and $sig.SignerCertificate.Subject -like '*O=Google LLC*') { exit 0 } else { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Official Google LLC cryptographic signature verified. File is complete and intact.
    goto VALID_FILE_FOUND
)

echo [WARNING] An existing "%INSTALLER_FILE%" was found, but it seems incomplete (%FILE_SIZE% bytes).
set /p "delete_corrupt=Delete the partial file and redownload? [Y/N]: "
if /i "%delete_corrupt%"=="Y" del /q "%INSTALLER_FILE%"
if /i "%delete_corrupt%"=="Y" goto DOWNLOAD_SECTION

echo Cancelled. Exiting...
pause
exit /b


:VALID_FILE_FOUND
echo [INFO] A valid installer "%INSTALLER_FILE%" was found locally.
echo.
set /p "use_existing=Use the existing local installer instead of redownloading? [Y/N]: "
if /i "%use_existing%"=="Y" set "DOWNLOAD_NEEDED=N"
if /i "%use_existing%"=="Y" set "DELETE_AFTER_INSTALL=N"
if /i "%use_existing%"=="Y" goto INSTALL_SECTION

set /p "delete_old=Would you like to delete and redownload the installer? [Y/N]: "
if /i "%delete_old%"=="Y" del /q "%INSTALLER_FILE%"
if /i "%delete_old%"=="Y" goto DOWNLOAD_SECTION

echo Cancelled. Exiting...
pause
exit /b


:DOWNLOAD_SECTION
REM -----------------------------------------------------
REM STEP 3: Download
REM -----------------------------------------------------
echo.
echo [1/3] Downloading official Google Drive for Desktop...
echo.

REM -L tells curl to follow download redirects
REM -C - automatically resumes interrupted downloads from where they left off
REM -f --fail prevents curl from writing HTML error pages to our file on HTTP failures
REM -o tells curl to save the download as our designated filename
curl.exe -L -C - -f -o "%INSTALLER_FILE%" "https://dl.google.com/drive-file-stream/GoogleDriveSetup.exe"

:: Block installation if the download command failed or was blocked by -f
if %errorlevel% neq 0 (
    echo [ERROR] Google Drive download failed or was aborted (Exit Code: %errorlevel%).
    echo Please check your network connection and try again.
    pause
    exit /b
)

if not exist "%INSTALLER_FILE%" echo [ERROR] Download failed. Please check your internet connection and try again.
if not exist "%INSTALLER_FILE%" pause
if not exist "%INSTALLER_FILE%" exit /b


:INSTALL_SECTION
REM -----------------------------------------------------
REM STEP 4: Install
REM -----------------------------------------------------
echo.
echo [2/3] Installing Google Drive silently (Please wait)...
"%INSTALLER_FILE%" --silent --desktop_shortcut

REM Give the system a brief moment to finish file writing
timeout /t 5 >nul


REM -----------------------------------------------------
REM STEP 5: Clean up (Only if newly downloaded)
REM -----------------------------------------------------
echo.
echo [3/3] Cleaning up installer files...
if "%DELETE_AFTER_INSTALL%"=="Y" if exist "%INSTALLER_FILE%" del /q "%INSTALLER_FILE%"
if "%DELETE_AFTER_INSTALL%"=="Y" echo Local installer file cleared.
if "%DELETE_AFTER_INSTALL%"=="N" echo Keeping local "%INSTALLER_FILE%" as requested.


:LAUNCH
echo.
echo ===================================================
echo INSTALLATION / LAUNCH SEQUENCE COMPLETE!
echo Launching Google Drive now...
echo ===================================================
echo.
echo ATTENTION LGU STAFF:
echo A web browser will now open. Please log in to the 
echo official Tanza LGU Google Account to connect this PC.
echo.

REM Starts the Google Drive application if it exists
if exist "%EXE_PATH%" start "" "%EXE_PATH%"
if not exist "%EXE_PATH%" echo [ERROR] Google Drive executable was not found at "%EXE_PATH%".
if not exist "%EXE_PATH%" echo Please verify if the installation completed successfully.

pause