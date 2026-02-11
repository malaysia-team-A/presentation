from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader
from app.utils.auth_utils import decode_access_token, verify_password
from app.engines.db_engine_async import db_engine_async
from typing import Optional

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login", auto_error=False)
header_scheme = APIKeyHeader(name="Authorization", auto_error=False)

async def get_db():
    return db_engine_async

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Remove 'Bearer ' prefix if present (OAuth2PasswordBearer usually handles this, but just in case)
    if token.startswith("Bearer "):
        token = token.split(" ", 1)[1]
        
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload

async def get_current_user_optional(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[dict]:
    if not token:
        return None
    # OAuth2PasswordBearer extracts token value if header is "Bearer <token>"
    # If using APIKeyHeader, it returns the whole string.
    # Check if token is "Bearer ..." manually or just try decoding
    if token.startswith("Bearer "):
         token = token.split(" ", 1)[1]
         
    try:
        payload = decode_access_token(token)
        return payload
    except:
        return None
