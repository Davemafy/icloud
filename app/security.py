from fastapi import Header, HTTPException
from .config import SETTINGS


def require_api_key(x_api_key: str = Header(default="", alias="X-API-Key")) -> None:
    if not SETTINGS.api_key or SETTINGS.api_key == "change-me":
        raise HTTPException(status_code=503, detail="CLOUD_EA_API_KEY is not configured")
    if x_api_key != SETTINGS.api_key:
        raise HTTPException(status_code=401, detail="Invalid X-API-Key")
