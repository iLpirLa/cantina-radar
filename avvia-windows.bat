@echo off
title Cantina Radar
cd /d "%~dp0"
set "PY="
where py >nul 2>nul
if %errorlevel%==0 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if %errorlevel%==0 set "PY=python"
)
if not defined PY goto nopython
if not exist ".venv\Scripts\python.exe" (
  echo Prima installazione, attendi qualche minuto...
  %PY% -m venv .venv || goto nopython
)
call ".venv\Scripts\activate.bat"
python -m pip install -q --disable-pip-version-check -r requirements.txt
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo Si apre il file .env: inserisci token del bot e chat id, salva e chiudi il Blocco note.
  notepad ".env"
)
python -m cwmon start --lan
pause
exit /b

:nopython
echo.
echo Python non e' installato.
echo Scaricalo da https://www.python.org/downloads/ e durante l'installazione
echo spunta la casella "Add python.exe to PATH". Poi riapri questo file.
pause
