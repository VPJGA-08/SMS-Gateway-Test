"""
Health check endpoint (no authentication required)
"""
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Request

from core.config import settings

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check(request: Request):
    """
    Health check endpoint
    
    Returns service status, uptime, and version information.
    No authentication required.
    """
    startup_time = getattr(request.app.state, "startup_time", time.time())
    uptime_seconds = int(time.time() - startup_time)
    
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": uptime_seconds,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT
    }
