from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import get_current_user
from app.core.session import high_security_sessions
from app.schemas import LoginRequest, VerifyPasswordRequest
from app.engines.db_engine_async import db_engine_async
from app.utils.auth_utils import create_access_token, decode_access_token, verify_password

router = APIRouter()


def _resolve_student_name(student: dict) -> str:
    for key in ("STUDENT_NAME", "Student_Name", "name", "Name"):
        value = student.get(key)
        if value:
            return str(value).strip()
    return ""


def _resolve_password_hash(student: dict) -> str:
    for key in ("PASSWORD", "Password", "password"):
        value = student.get(key)
        if value:
            return str(value)
    return ""


@router.post("/login")
async def login(request: LoginRequest):
    input_name = str(request.name or request.username or "").strip()
    if not request.student_number or not input_name:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "student_number and name are required"},
        )

    student = await db_engine_async.get_student_by_number(request.student_number)
    if not student:
        return JSONResponse(
            status_code=401, content={"success": False, "message": "Invalid credentials"}
        )

    db_name = _resolve_student_name(student)
    if not db_name or db_name.lower() != input_name.lower():
        return JSONResponse(
            status_code=401, content={"success": False, "message": "Invalid credentials"}
        )

    student_number = str(student.get("STUDENT_NUMBER") or request.student_number).strip()
    high_security_sessions.pop(student_number, None)

    access_token_expires = timedelta(minutes=60)
    access_token = create_access_token(
        data={
            "sub": student_number,
            "student_number": student_number,
            "name": db_name,
            "role": "student",
        },
        expires_delta=access_token_expires,
    )
    # Keep both legacy and FastAPI-shaped keys for compatibility.
    return {
        "success": True,
        "token": access_token,
        "user": {"name": db_name, "student_number": student_number},
        "access_token": access_token,
        "token_type": "bearer",
        "student_name": db_name,
    }


@router.post("/verify_password")
async def verify_pass(
    request: VerifyPasswordRequest, current_user: dict = Depends(get_current_user)
):
    token_student_number = str(
        current_user.get("sub") or current_user.get("student_number") or ""
    ).strip()
    body_student_number = str(request.student_number or "").strip()
    student_number = token_student_number or body_student_number

    if not student_number:
        return JSONResponse(
            status_code=401,
            content={"success": False, "verified": False, "message": "Unauthorized"},
        )
    if body_student_number and token_student_number and body_student_number != token_student_number:
        return JSONResponse(
            status_code=403,
            content={"success": False, "verified": False, "message": "Student mismatch"},
        )

    student = await db_engine_async.get_student_by_number(student_number)
    if not student:
        return JSONResponse(
            status_code=404,
            content={"success": False, "verified": False, "message": "Student not found"},
        )

    stored_password_hash = _resolve_password_hash(student)
    if not stored_password_hash:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "verified": False,
                "message": "No password is set for this account",
            },
        )

    if verify_password(request.password, stored_password_hash):
        high_security_sessions[student_number] = datetime.now() + timedelta(minutes=10)
        return {
            "success": True,
            "verified": True,
            "message": "Identity verified",
            "expires_in_seconds": 600,
        }

    return JSONResponse(
        status_code=401,
        content={"success": False, "verified": False, "message": "Incorrect password"},
    )

@router.post("/logout")
async def logout(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        payload = decode_access_token(auth_header.split(" ", 1)[1].strip())
        if payload:
            student_number = str(
                payload.get("sub") or payload.get("student_number") or ""
            ).strip()
            if student_number:
                high_security_sessions.pop(student_number, None)
    return {"success": True, "message": "Logged out successfully"}
