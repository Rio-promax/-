@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

set "PRODUCT_DIR=%~dp0"
set "APP_URL=http://127.0.0.1:8765/"
set "HEALTH_URL=http://127.0.0.1:8765/health"
set "SHELL_EXE=%PRODUCT_DIR%local\desktop-shell\bin\Release\net10.0-windows10.0.17763.0\LoginShell.exe"

if not exist "%SHELL_EXE%" (
  echo [ERROR] Product shell was not found:
  echo         %SHELL_EXE%
  echo.
  echo Build it first with:
  echo   dotnet build "%PRODUCT_DIR%src\services\desktop-shell\LoginShell.csproj" -c Release
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $payload=Invoke-RestMethod -UseBasicParsing -Uri '%HEALTH_URL%' -TimeoutSec 2; if ($payload.status -eq 'ok') { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] The product backend is not running at %APP_URL%
  echo.
  echo Start product\start-product.cmd first, keep it running, and then retry this launcher.
  pause
  exit /b 1
)

start "Multisource Knowledge Base" "%SHELL_EXE%" --product "%APP_URL%"
exit /b 0
