@echo off
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 app.py
) else (
    python app.py
)

if %errorlevel% neq 0 (
    echo.
    echo Khemik no pudo iniciarse.
    echo Revisa el mensaje anterior e instala las dependencias con:
    echo py -3 -m pip install -r requirements.txt
    pause
)
