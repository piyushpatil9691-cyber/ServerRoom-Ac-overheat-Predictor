@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Server Room AC Overheat Predictor - Launcher
cd /d "%~dp0"

:: Refresh PATH from Windows registry so newly installed Docker/Python are detected
for /f "delims=" %%P in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"') do set "PATH=%%P"

echo ========================================================================
echo   Server Room AC Overheat Predictor
echo ========================================================================
echo.

:: Create .env from .env.example on first run and generate a Fernet key if needed
if not exist ".env" (
    if not exist ".env.example" (
        echo [ERROR] Neither .env nor .env.example was found in %CD%.
        pause
        exit /b 1
    )
    copy /y ".env.example" ".env" >nul
    echo [Setup] Created .env from .env.example.
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$envPath = '.env';" ^
  "$txt = Get-Content $envPath -Raw;" ^
  "$changed = $false;" ^
  "if ($txt -match 'REPLACE_WITH_32_BYTE_URLSAFE_BASE64_FERNET_KEY') {" ^
  "  $key = python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>$null;" ^
  "  if ($key) { $txt = $txt.Replace('REPLACE_WITH_32_BYTE_URLSAFE_BASE64_FERNET_KEY', $key.Trim()); $changed = $true; }" ^
  "}" ^
  "if ($txt -match 'change-this-operator-passcode') {" ^
  "  $txt = $txt.Replace('change-this-operator-passcode', 'operator-local-2026'); $changed = $true;" ^
  "}" ^
  "if ($changed) { Set-Content -Path $envPath -Value $txt -Encoding UTF8; Write-Host '[Setup] Generated local encryption key and operator passcode in .env.' }"

set "OP_KEY="
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="OPERATOR_ACCESS_KEY" set "OP_KEY=%%B"
)

:: Check if Docker CLI is available
where docker >nul 2>&1
if errorlevel 1 goto :local_python_mode

:: Ensure Docker Engine is running
docker info >nul 2>&1
if not errorlevel 1 goto :docker_ready

if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
    echo [Docker] Starting Docker Desktop in background...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
) else (
    echo [Docker] Waiting for Docker Engine...
)
set /a WAIT_COUNT=0

:wait_docker
timeout /t 3 /nobreak >nul
docker info >nul 2>&1
if not errorlevel 1 goto :docker_ready
set /a WAIT_COUNT+=1
if !WAIT_COUNT! GEQ 20 (
    echo [WARN] Docker Engine did not start in time. Falling back to local Python mode...
    goto :local_python_mode
)
goto :wait_docker

:docker_ready
echo [Docker] Building and starting services in background...
docker compose up -d --build
if errorlevel 1 (
    echo [ERROR] Failed to start Docker Compose services.
    pause
    exit /b 1
)

echo [Wait] Waiting for backend and dashboard health checks...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ok = $false;" ^
  "for ($i=0; $i -lt 40; $i++) {" ^
  "  try {" ^
  "    $h = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/v1/system/health' -UseBasicParsing -TimeoutSec 2;" ^
  "    $d = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 2;" ^
  "    if ($h.StatusCode -eq 200 -and $d.StatusCode -eq 200) { $ok = $true; break }" ^
  "  } catch {}" ^
  "  Start-Sleep -Seconds 2" ^
  "}" ^
  "if (-not $ok) { Write-Host '[WARN] Services are still warming up; check logs if needed.' }"

start "" "http://localhost:8501"
set "MODE=docker"
goto :status_menu

:local_python_mode
echo [Python] Starting backend, simulator, and dashboard silently in background...
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Neither Docker nor Python was found on PATH.
    pause
    exit /b 1
)

if not exist "ml\models\ac_failure_model.joblib" (
    echo [ML] Generating historical dataset and training model...
    python -m ml.generate_dataset
    python -m ml.train_model
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p1 = Start-Process -FilePath 'python' -ArgumentList '-m','uvicorn','backend.main:app','--host','0.0.0.0','--port','8000' -WorkingDirectory '%CD%' -WindowStyle Hidden -PassThru;" ^
  "Start-Sleep -Seconds 3;" ^
  "$p2 = Start-Process -FilePath 'python' -ArgumentList '-m','simulator.sensor_generator','--api-url','http://127.0.0.1:8000' -WorkingDirectory '%CD%' -WindowStyle Hidden -PassThru;" ^
  "$p3 = Start-Process -FilePath 'python' -ArgumentList '-m','streamlit','run','dashboard/app.py','--server.port=8501','--server.address=0.0.0.0','--server.headless=true' -WorkingDirectory '%CD%' -WindowStyle Hidden -PassThru;" ^
  "@($p1.Id, $p2.Id, $p3.Id) | Set-Content '.local_pids.txt';" ^
  "for ($i=0; $i -lt 30; $i++) {" ^
  "  try {" ^
  "    $h = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/v1/system/health' -UseBasicParsing -TimeoutSec 2;" ^
  "    $d = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 2;" ^
  "    if ($h.StatusCode -eq 200 -and $d.StatusCode -eq 200) { break }" ^
  "  } catch {}" ^
  "  Start-Sleep -Seconds 1" ^
  "}"

start "" "http://localhost:8501"
set "MODE=python"

:status_menu
cls
echo ========================================================================
echo   Server Room AC Overheat Predictor - Running in Background (%MODE%)
echo ========================================================================
echo.
echo   Dashboard URL    : http://localhost:8501
echo   API Swagger Docs : http://localhost:8000/docs
if defined OP_KEY echo   Operator Key     : %OP_KEY%
echo.
echo   All services are running in the background. Only this window stays open.
echo.
echo   [O] Open Dashboard in Browser
if "%MODE%"=="docker" echo   [L] View Recent Container Logs
if "%MODE%"=="docker" echo   [R] Restart Services
echo   [S] Stop All Services and Exit
echo   [Q] Close This Window (keep running in background)
echo.
set "CHOICE="
set /p "CHOICE=Select an option [O/L/R/S/Q]: "

if /i "%CHOICE%"=="O" (
    start "" "http://localhost:8501"
    goto :status_menu
)
if /i "%CHOICE%"=="L" (
    if "%MODE%"=="docker" (
        docker compose logs --tail 25
        pause
    )
    goto :status_menu
)
if /i "%CHOICE%"=="R" (
    if "%MODE%"=="docker" (
        echo Restarting containers...
        docker compose restart
        timeout /t 3 /nobreak >nul
    )
    goto :status_menu
)
if /i "%CHOICE%"=="S" (
    echo Stopping services...
    if "%MODE%"=="docker" (
        docker compose down
    ) else (
        if exist ".local_pids.txt" (
            for /f "usebackq delims=" %%P in (".local_pids.txt") do taskkill /PID %%P /T /F >nul 2>&1
            del /f /q ".local_pids.txt" >nul 2>&1
        )
    )
    echo Stopped.
    timeout /t 2 /nobreak >nul
    exit /b 0
)
if /i "%CHOICE%"=="Q" (
    exit /b 0
)
goto :status_menu
