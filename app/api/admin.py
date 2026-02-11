from pathlib import Path
import os
from datetime import timedelta
from hmac import compare_digest

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.engines.db_engine_async import db_engine_async
from app.engines.rag_engine_async import rag_engine_async
from app.engines.index_manager import index_manager
from app.engines.monitoring import get_dashboard_data
from app.engines.unanswered_analyzer import unanswered_analyzer
from app.utils.auth_utils import create_access_token, decode_access_token

router = APIRouter()


class AdminLoginRequest(BaseModel):
    password: str


def _admin_password() -> str:
    return str(os.getenv("ADMIN_PASSWORD") or "").strip()


def _admin_token_ttl_hours() -> int:
    raw = str(os.getenv("ADMIN_TOKEN_EXPIRE_HOURS", "12")).strip()
    try:
        value = int(raw)
    except Exception:
        value = 12
    return min(max(value, 1), 72)


async def require_admin(request: Request) -> dict:
    auth_header = str(request.headers.get("Authorization") or "").strip()
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    role = str(payload.get("role") or "").strip().lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return payload


@router.post("/login")
async def admin_login(request: AdminLoginRequest):
    configured_password = _admin_password()
    if not configured_password:
        return JSONResponse(
            status_code=503,
            content={"success": False, "message": "ADMIN_PASSWORD is not configured"},
        )

    provided = str(request.password or "")
    if not provided or not compare_digest(provided, configured_password):
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": "Invalid admin credentials"},
        )

    expires = timedelta(hours=_admin_token_ttl_hours())
    token = create_access_token(
        data={"sub": "admin", "name": "Administrator", "role": "admin"},
        expires_delta=expires,
    )
    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "expires_in_seconds": int(expires.total_seconds()),
    }


@router.post("/logout")
async def admin_logout(_: dict = Depends(require_admin)):
    # Stateless JWT logout: client should discard the token.
    return {"success": True, "message": "Logged out"}


@router.get("/stats")
async def get_stats(_: dict = Depends(require_admin)):
    student_stats = await db_engine_async.get_student_stats()

    total_feedbacks = 0
    positive_feedbacks = 0
    rlhf_labeled_feedbacks = 0
    unanswered_logs = []
    recent_feedbacks = []

    db = db_engine_async.db
    if db is not None:
        try:
            total_feedbacks = await db.Feedback.count_documents({})
            positive_feedbacks = await db.Feedback.count_documents(
                {"$or": [{"rating": "positive"}, {"score": {"$gte": 4}}]}
            )
            rlhf_labeled_feedbacks = await db.Feedback.count_documents(
                {"reward": {"$in": [1, 1.0, -1, -1.0]}}
            )
        except Exception:
            pass

        try:
            unanswered_logs = await db.unanswered.find({}, {"_id": 0}).sort("timestamp", -1).limit(10).to_list(length=10)
        except Exception:
            unanswered_logs = []

        try:
            recent_feedbacks = await db.Feedback.find({}, {"_id": 0}).sort("timestamp", -1).limit(10).to_list(length=10)
        except Exception:
            recent_feedbacks = []

    satisfaction_rate = 0
    if total_feedbacks > 0:
        satisfaction_rate = round((positive_feedbacks / total_feedbacks) * 100, 2)

    return {
        "status": "ok",
        "db_connected": db is not None,
        "total_students": student_stats.get("total_students", 0),
        "gender": student_stats.get("gender", {}),
        "top_nationalities": student_stats.get("top_nationalities", {}),
        # Keep legacy admin panel keys.
        "satisfaction_rate": satisfaction_rate,
        "total_feedbacks": total_feedbacks,
        "rlhf_labeled_feedbacks": rlhf_labeled_feedbacks,
        "unanswered_count": len(unanswered_logs),
        "unanswered_logs": unanswered_logs,
        "recent_feedbacks": recent_feedbacks,
    }


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), _: dict = Depends(require_admin)):
    if not file or not file.filename:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "No file provided"},
        )

    safe_name = Path(file.filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".pdf", ".txt", ".csv"}:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Only PDF/TXT/CSV files are supported"},
        )

    content = await file.read()
    kb_dir = Path("data/knowledge_base")
    kb_dir.mkdir(parents=True, exist_ok=True)
    save_path = kb_dir / safe_name
    with open(save_path, "wb") as f:
        f.write(content)

    success = await rag_engine_async.ingest_file(str(save_path))
    if not success:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "File saved but indexing failed"},
        )

    return {
        "success": True,
        "filename": safe_name,
        "status": "Uploaded and Indexed",
        "message": f"Successfully ingested {safe_name}",
    }


@router.post("/reindex")
async def reindex_mongodb(_: dict = Depends(require_admin)):
    count = await rag_engine_async.index_mongodb_collections()
    return {
        "success": True,
        "status": "reindexed",
        "indexed_documents": count,
    }


@router.get("/files")
async def list_files(_: dict = Depends(require_admin)):
    kb_dir = Path("data/knowledge_base")
    if not kb_dir.exists():
        return {"files": []}

    files = []
    for p in kb_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() in {".pdf", ".txt", ".csv", ".docx"}:
            files.append(p.name)

    files.sort(key=str.lower)
    return {"files": files}


@router.delete("/files")
async def delete_file(body: dict = Body(default={}), _: dict = Depends(require_admin)):
    filename = str((body or {}).get("filename") or "").strip()
    if not filename:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Filename required"},
        )

    safe_name = Path(filename).name
    file_path = Path("data/knowledge_base") / safe_name
    if not file_path.exists() or not file_path.is_file():
        return JSONResponse(
            status_code=404,
            content={"success": False, "message": "File not found"},
        )

    try:
        file_path.unlink()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Delete failed: {e}"},
        )

    # Trigger re-index after deletion
    await index_manager.reindex(force=True, triggered_by="file_deletion")
    return {"success": True, "deleted": safe_name, "reindexed": True}


# =============================================================================
# INDEX MANAGEMENT
# =============================================================================

@router.get("/index/status")
async def get_index_status(_: dict = Depends(require_admin)):
    """Get current index status and health."""
    status = await index_manager.get_status()
    return {"success": True, **status}


@router.post("/index/reindex")
async def trigger_reindex(
    body: dict = Body(default={}),
    _: dict = Depends(require_admin),
):
    """Trigger a manual re-index."""
    force = bool(body.get("force", False))
    result = await index_manager.reindex(force=force, triggered_by="admin_manual")
    return result


@router.get("/index/history")
async def get_index_history(_: dict = Depends(require_admin)):
    """Get indexing history."""
    history = index_manager.get_history(limit=20)
    return {"success": True, "history": history}


@router.get("/index/changes")
async def check_data_changes(_: dict = Depends(require_admin)):
    """Check if data has changed since last index."""
    changes = await index_manager.check_data_changes()
    return {"success": True, **changes}


# =============================================================================
# MONITORING
# =============================================================================

@router.get("/monitoring/dashboard")
async def get_monitoring_dashboard(
    hours: int = 24,
    _: dict = Depends(require_admin),
):
    """Get monitoring dashboard data."""
    hours = min(max(hours, 1), 168)  # 1 hour to 7 days
    data = await get_dashboard_data(hours)
    return {"success": True, **data}


# =============================================================================
# UNANSWERED ANALYSIS
# =============================================================================

@router.get("/unanswered/analysis")
async def get_unanswered_analysis(
    days: int = 7,
    _: dict = Depends(require_admin),
):
    """Get analysis of unanswered questions."""
    days = min(max(days, 1), 30)  # 1 to 30 days
    analysis = await unanswered_analyzer.analyze(days=days)
    return {"success": True, **analysis}


@router.get("/unanswered/report")
async def get_unanswered_report(
    days: int = 7,
    format: str = "markdown",
    _: dict = Depends(require_admin),
):
    """Get a formatted report of unanswered questions."""
    days = min(max(days, 1), 30)
    format = format if format in ("text", "markdown") else "markdown"
    report = await unanswered_analyzer.generate_report(days=days, format=format)
    return {"success": True, "report": report, "format": format}


# =============================================================================
# HEALTH CHECK (PUBLIC)
# =============================================================================

@router.get("/health")
async def health_check():
    """Public health check endpoint."""
    db_connected = db_engine_async.db is not None

    # Quick check
    if db_connected:
        try:
            await db_engine_async.client.admin.command('ping')
        except Exception:
            db_connected = False

    return {
        "status": "healthy" if db_connected else "degraded",
        "db_connected": db_connected,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
