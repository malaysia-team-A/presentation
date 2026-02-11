@echo off
echo Installing required libraries (google-generativeai, faiss-cpu)...

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    echo [INFO] Activated .venv
) else if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
    echo [INFO] Activated venv
) else (
    echo [WARN] Virtual environment not found. Installing to system Python.
)

echo Installing required libraries...
python -m pip install google-generativeai faiss-cpu
echo.
echo Installation complete. Now run start_chatbot.bat again.
pause
