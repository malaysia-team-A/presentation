import os
import sys
import asyncio

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

db_engine_async = None
try:
    from app.engines.db_engine_async import db_engine_async  # type: ignore[assignment]
    print("Import Successful: db_engine_async is valid.")
except SyntaxError as e:
    print(f"Syntax Error: {e}")
except Exception as e:
    print(f"Import Failed: {e}")


async def _check_connect():
    if db_engine_async is None:
        print("Skipping DB connect check (engine import failed).")
        return
    await db_engine_async.connect()
    print(f"Connected: {db_engine_async.db is not None}")


if __name__ == "__main__":
    asyncio.run(_check_connect())
