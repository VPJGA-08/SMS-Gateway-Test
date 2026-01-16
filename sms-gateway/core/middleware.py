"""
Middleware for authentication, request tracking, and IP filtering
"""
import secrets
import logging
from fastapi import Request, status
from fastapi.responses import JSONResponse
from core.config import settings

logger = logging.getLogger(__name__)

# Paths that don't require authentication
UNAUTHENTICATED_PATHS = ["/health", "/docs", "/redoc", "/openapi.json"]

async def api_key_middleware(request: Request, call_next):
    """
    Middleware for API key authentication and request tracking
    """
    # Generate request ID
    request_id = secrets.token_hex(8)
    request.state.request_id = request_id
    
    # Skip auth for health check and docs
    if request.url.path in UNAUTHENTICATED_PATHS:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    
    # Check IP whitelist (if configured)
    allowed_ips = settings.get_allowed_ips()
    if allowed_ips:
        client_ip = request.client.host
        if client_ip not in allowed_ips:
            logger.warning(
                f"[{request_id}] Blocked request from unauthorized IP: {client_ip}"
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "request_id": request_id,
                    "status": "error",
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "Access denied: IP not whitelisted"
                    }
                },
                headers={"X-Request-ID": request_id}
            )
    
    # Validate API key
    api_key = request.headers.get(settings.API_KEY_HEADER)
    
    if not api_key:
        logger.warning(f"[{request_id}] Missing API key from {request.client.host}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "request_id": request_id,
                "status": "error",
                "error": {
                    "code": "MISSING_API_KEY",
                    "message": f"API key required in {settings.API_KEY_HEADER} header"
                }
            },
            headers={"X-Request-ID": request_id}
        )
    
    if api_key != settings.API_KEY:
        logger.warning(
            f"[{request_id}] Invalid API key from {request.client.host}: "
            f"{api_key[:8]}..."
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "request_id": request_id,
                "status": "error",
                "error": {
                    "code": "INVALID_API_KEY",
                    "message": "Invalid API key"
                }
            },
            headers={"X-Request-ID": request_id}
        )
    
    # Log authenticated request
    logger.info(
        f"[{request_id}] {request.method} {request.url.path} from {request.client.host}"
    )
    
    # Process request
    response = await call_next(request)
    
    # Add request ID to response headers
    response.headers["X-Request-ID"] = request_id
    
    return response