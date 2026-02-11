"""
Compatibility entrypoint.

Use `python main.py` as the primary startup path.
This file is kept for scripts or users that still run `python main_fastapi.py`.
"""

from main import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
