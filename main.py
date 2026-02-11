import os
# Force HuggingFace to use cached models only (no network calls)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.engines.db_engine_async import db_engine_async
from app.engines.rag_engine_async import rag_engine_async
from app.engines.index_manager import index_manager
import app.api.auth as auth
import app.api.admin as admin
import app.api.chat as chat  # Unified chat module with hybrid classifier


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up FastAPI...")
    await db_engine_async.connect()
    count = await rag_engine_async.index_mongodb_collections()
    index_manager.last_index_time = datetime.now()
    index_manager.last_index_count = count
    changes = await index_manager.check_data_changes()
    index_manager.last_index_hash = changes.get("current_hash")
    await index_manager.start_auto_reindex()
    print(f"Indexed {count} documents.")
    try:
        yield
    finally:
        await index_manager.stop_auto_reindex()


app = FastAPI(title="UCSI Chatbot", version="3.0.0", lifespan=lifespan)

# CORS
cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
cors_origins = [v.strip() for v in cors_origins_raw.split(",") if v.strip()] or ["*"]
cors_allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
if "*" in cors_origins and cors_allow_credentials:
    cors_allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix="/api", tags=["Auth"])
app.include_router(chat.router, prefix="/api", tags=["Chat"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])

# Static Files
# Mount specific folders to root to support relative paths in HTML (css/... and js/...)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/css", StaticFiles(directory="static/site/css"), name="css")
app.mount("/js", StaticFiles(directory="static/site/js"), name="js")

# Mount site assets if any other folders exist in static/site (images, etc)
# app.mount("/site", StaticFiles(directory="static/site"), name="site")

# Root
@app.get("/")
async def read_root():
    return FileResponse("static/site/code_hompage.html")


@app.get("/admin")
async def read_admin():
    admin_html = Path("static/admin/admin.html")
    if not admin_html.exists():
        return FileResponse("static/site/code_hompage.html")
    return FileResponse(str(admin_html))

if __name__ == "__main__":
    import uvicorn
    # Updated to main:app
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
