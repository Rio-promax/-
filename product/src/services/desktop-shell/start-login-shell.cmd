@echo off
chcp 65001 >nul
setlocal
set "HERE=%~dp0"
set "EXE=%HERE%..\..\..\local\desktop-shell\bin\Release\net10.0-windows10.0.17763.0\LoginShell.exe"
if not exist "%EXE%" (
  echo.
  echo LoginShell.exe was not found.
  echo Build it first:
  echo    dotnet build "%HERE%LoginShell.csproj" -c Release
  echo.
  pause
  exit /b 1
)
start "" "%EXE%"
exit /b 0
