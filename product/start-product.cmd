@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

goto :main

:wait_for_service
powershell -NoProfile -ExecutionPolicy Bypass -Command "$expected='%EXPECTED_API_CONTRACT_VERSION%'; $urls=@('%HEALTH_URL%','%META_URL%'); $deadline=(Get-Date).AddSeconds(60); while ((Get-Date) -lt $deadline) { try { foreach ($url in $urls) { $payload=Invoke-RestMethod -UseBasicParsing -Uri $url -TimeoutSec 2; if ($null -eq $payload.api_contract_version -or [string]$payload.api_contract_version -ne $expected) { exit 2 } }; exit 0 } catch { if ($_.Exception.Response) { exit 2 }; Start-Sleep -Seconds 1 } }; exit 1"
exit /b %errorlevel%

:main
set "PRODUCT_DIR=%~dp0"
cd /d "%PRODUCT_DIR%"
if errorlevel 1 goto :error_directory

set "SHELL_EXE=%PRODUCT_DIR%local\desktop-shell\bin\Release\net10.0-windows10.0.17763.0\LoginShell.exe"
set "SHELL_SRC=%PRODUCT_DIR%src\services\desktop-shell\Program.cs"
rem PATH may point at the x86 dotnet without any SDK; prefer the x64 install.
set "DOTNET_EXE=%ProgramFiles%\dotnet\dotnet.exe"
if not exist "%DOTNET_EXE%" set "DOTNET_EXE=dotnet"

if not exist "%SHELL_EXE%" goto :build_shell
powershell -NoProfile -Command "if ((Get-Item '%SHELL_EXE%').LastWriteTime -lt (Get-Item '%SHELL_SRC%').LastWriteTime) { exit 1 }" >nul 2>&1
if errorlevel 1 goto :build_shell
goto :shell_ready

:build_shell
echo [INFO] Building the product shell: source is newer than the binary...
"%DOTNET_EXE%" build "%PRODUCT_DIR%src\services\desktop-shell\LoginShell.csproj" -c Release -v m
if errorlevel 1 goto :error_build
if not exist "%SHELL_EXE%" goto :error_shell

:shell_ready
set "PYTHON=%PRODUCT_DIR%.venv\Scripts\python.exe"
set "USE_VENV=0"
if exist "%PYTHON%" (
  set "USE_VENV=1"
  goto :python_ready
)
set "PYTHON=python"
where python >nul 2>&1
if errorlevel 1 goto :error_python

:python_ready
set "PYTHON_ARGS="
if "%USE_VENV%"=="1" (
  rem Python 3.12 on GBK Windows reads the UTF-8 editable .pth as locale text.
  rem Skip .pth processing and add the required paths explicitly instead.
  set "PYTHONPATH=%PRODUCT_DIR%.venv\Lib\site-packages;%PRODUCT_DIR%src\services\core;%PYTHONPATH%"
  set "PYTHON_ARGS=-S"
)
set "APP_URL=http://127.0.0.1:8765/"
set "HEALTH_URL=http://127.0.0.1:8765/health"
set "META_URL=http://127.0.0.1:8765/api/v1/meta"
rem Keep this mirror synchronized with app.meta.API_CONTRACT_VERSION. The
rem contract-version test parses this value before a release is accepted.
set "EXPECTED_API_CONTRACT_VERSION=2026-09-15.2"
set "PRODUCT_LOG_DIR=%PRODUCT_DIR%local\logs"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$expected='%EXPECTED_API_CONTRACT_VERSION%'; $urls=@('%HEALTH_URL%','%META_URL%'); try { foreach ($url in $urls) { $payload=Invoke-RestMethod -UseBasicParsing -Uri $url -TimeoutSec 2; if ($null -eq $payload.api_contract_version -or [string]$payload.api_contract_version -ne $expected) { exit 2 } }; exit 0 } catch { if ($_.Exception.Response) { exit 2 }; exit 1 }" >nul 2>&1
if not errorlevel 1 goto :service_ready
if errorlevel 2 goto :error_contract

:start_service
echo [INFO] Starting the local service...
rem 0.0.0.0 so LAN and Tailscale virtual NIC can reach the service; the
rem shell and health checks below still use 127.0.0.1 on purpose.
start "Multisource Knowledge Base" /b "%PYTHON%" %PYTHON_ARGS% -m uvicorn app.api.main:app --app-dir src/services/core --host 0.0.0.0 --port 8765

echo [INFO] Waiting for the service to become ready...
call :wait_for_service
if errorlevel 2 goto :error_contract
if errorlevel 1 goto :error_service
goto :service_ready

:service_ready
echo [INFO] Service logs: %PRODUCT_LOG_DIR%\backend.log
echo [INFO] Starting product shell: %SHELL_EXE%
start "Multisource Knowledge Base" "%SHELL_EXE%" --product "%APP_URL%"
echo [OK] Product shell started. Keep this CMD window open to view service logs.
goto :done

:error_directory
echo [ERROR] Could not enter product directory: %PRODUCT_DIR%
pause
exit /b 1

:error_python
echo [ERROR] Python was not found. Create product\.venv or add Python to PATH.
pause
exit /b 1

:error_build
echo [ERROR] Product shell build failed. Fix the build before starting the product.
echo         "%DOTNET_EXE%" build "%PRODUCT_DIR%src\services\desktop-shell\LoginShell.csproj" -c Release
pause
exit /b 1

:error_shell
echo [ERROR] Product shell was not found:
echo         %SHELL_EXE%
echo.
echo Build it first with:
echo   "%DOTNET_EXE%" build "%PRODUCT_DIR%src\services\desktop-shell\LoginShell.csproj" -c Release
pause
exit /b 1

:error_service
echo [ERROR] The service did not become ready within 60 seconds. Check %PRODUCT_LOG_DIR%\backend.log.
pause
exit /b 1

:error_contract
echo [ERROR] The service on port 8765 has an incompatible API contract.
echo [ERROR] Close the old product process and retry; it was not reused.
pause
exit /b 1

:done
endlocal
