"""
Command execution endpoints
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.config import settings
from core.commands import registry
from core.executor import executor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/commands", tags=["Commands"])

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Request/Response models
class ExecuteCommandRequest(BaseModel):
    """Request to execute a command"""
    command: str = Field(..., description="Command name from registry")
    args: Dict[str, Any] = Field(default_factory=dict, description="Command arguments")
    timeout: Optional[int] = Field(None, description="Execution timeout in seconds", ge=1, le=120)
    mode: str = Field("sync", description="Execution mode: 'sync' (default)")

class CommandInfo(BaseModel):
    """Command information for discovery"""
    name: str
    description: str
    timeout_default: int
    args_schema: Dict[str, Any]

@router.get("")
@limiter.limit(settings.RATE_LIMIT_PER_MINUTE)
async def list_commands(request: Request):
    """
    List all available commands
    
    Returns a list of registered commands with their metadata.
    """
    request_id = request.state.request_id
    logger.info(f"[{request_id}] Listing available commands")
    
    commands = [
        CommandInfo(
            name=cmd.name,
            description=cmd.description,
            timeout_default=cmd.timeout_default,
            args_schema=cmd.args_schema
        )
        for cmd in registry.list_commands()
    ]
    
    return {
        "request_id": request_id,
        "commands": [cmd.model_dump() for cmd in commands]
    }

@router.post("/execute")
@limiter.limit(settings.RATE_LIMIT_PER_MINUTE)
async def execute_command(request: Request, cmd_request: ExecuteCommandRequest):
    """
    Execute a whitelisted command synchronously
    
    Executes the specified command with provided arguments and returns
    stdout, stderr, exit code, and execution metadata.
    
    Rate limited to prevent abuse.
    """
    request_id = request.state.request_id
    
    logger.info(
        f"[{request_id}] Execute request: command='{cmd_request.command}', "
        f"args={cmd_request.args}, timeout={cmd_request.timeout}"
    )
    
    # Validate command exists
    if not registry.is_valid_command(cmd_request.command):
        logger.warning(f"[{request_id}] Invalid command: '{cmd_request.command}'")
        available = [cmd.name for cmd in registry.list_commands()]
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "request_id": request_id,
                "status": "error",
                "error": {
                    "code": "INVALID_COMMAND",
                    "message": f"Command '{cmd_request.command}' not found in registry",
                    "details": {
                        "available_commands": available
                    }
                }
            }
        )
    
    # Check mode (only sync supported in v1)
    if cmd_request.mode != "sync":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "request_id": request_id,
                "status": "error",
                "error": {
                    "code": "INVALID_MODE",
                    "message": "Only 'sync' mode is currently supported",
                    "details": {
                        "supported_modes": ["sync"]
                    }
                }
            }
        )
    
    # Execute command
    result = await executor.execute_command(
        command_name=cmd_request.command,
        args=cmd_request.args,
        timeout=cmd_request.timeout,
        request_id=request_id
    )
    
    # Build response
    if result.error_message:
        # Determine appropriate status code
        if "timeout" in result.error_message.lower():
            http_status = status.HTTP_408_REQUEST_TIMEOUT
            error_code = "EXECUTION_TIMEOUT"
        elif "not found" in result.error_message.lower():
            http_status = status.HTTP_400_BAD_REQUEST
            error_code = "INVALID_COMMAND"
        else:
            http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
            error_code = "EXECUTION_FAILED"
        
        return JSONResponse(
            status_code=http_status,
            content={
                "request_id": request_id,
                "status": "error",
                "command": cmd_request.command,
                "error": {
                    "code": error_code,
                    "message": result.error_message,
                    "details": {
                        "exit_code": result.exit_code,
                        "stdout": result.stdout,
                        "stderr": result.stderr
                    } if result.stderr else None
                },
                "execution": {
                    "duration_ms": round(result.duration_ms, 2),
                    "started_at": result.started_at,
                    "completed_at": result.completed_at
                }
            }
        )
    
    # Success response
    return {
        "request_id": request_id,
        "status": "completed",
        "command": cmd_request.command,
        "result": {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code
        },
        "execution": {
            "duration_ms": round(result.duration_ms, 2),
            "started_at": result.started_at,
            "completed_at": result.completed_at
        }
    }