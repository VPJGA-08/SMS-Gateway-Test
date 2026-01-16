"""
Safe command executor with timeout, resource limits, and security controls
"""
import sys
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass
import subprocess

from core.commands import registry, CommandDefinition
from core.config import settings

logger = logging.getLogger(__name__)

@dataclass
class ExecutionResult:
    """Result of a command execution"""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    started_at: str
    completed_at: str
    error_message: Optional[str] = None

class ConcurrencyLimiter:
    """Limit concurrent command executions"""
    
    def __init__(self, max_concurrent: int):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._current_count = 0
    
    async def __aenter__(self):
        if self._semaphore.locked():
            logger.warning("Max concurrent executions reached, request will wait")
        await self._semaphore.acquire()
        self._current_count += 1
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._semaphore.release()
        self._current_count -= 1
    
    @property
    def current_count(self) -> int:
        return self._current_count

class SafeExecutor:
    """Safely execute whitelisted commands with security controls"""
    
    def __init__(self):
        self.limiter = ConcurrencyLimiter(settings.MAX_CONCURRENT_EXECUTIONS)
    
    def _validate_timeout(self, timeout: int) -> int:
        """Validate and clamp timeout value"""
        if timeout < 1:
            return settings.DEFAULT_TIMEOUT
        if timeout > settings.MAX_TIMEOUT:
            return settings.MAX_TIMEOUT
        return timeout
    
    def _build_command(self, cmd_def: CommandDefinition, args: Dict[str, Any]) -> list[str]:
        """
        Build command array safely (no shell injection possible)
        """
        # Use absolute path to Python interpreter and script
        command = [
            sys.executable,  # Python interpreter
            str(cmd_def.script_path.resolve())  # Absolute path to script
        ]
        
        # Add arguments (if the command accepts them)
        # For now, our SMS scripts don't take CLI args, but this shows the pattern
        for key, value in args.items():
            # Convert to safe string representation
            command.extend([f"--{key}", str(value)])
        
        return command
    
    async def execute_command(
        self,
        command_name: str,
        args: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
        request_id: str = "unknown"
    ) -> ExecutionResult:
        """
        Execute a whitelisted command with security controls
        
        Args:
            command_name: Name from command registry
            args: Command arguments (validated against schema)
            timeout: Execution timeout in seconds
            request_id: Request ID for logging
        
        Returns:
            ExecutionResult with stdout, stderr, exit code, etc.
        """
        args = args or {}
        started_at = datetime.now(timezone.utc)
        
        # Get command definition
        cmd_def = registry.get_command(command_name)
        if not cmd_def:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="",
                exit_code=-1,
                duration_ms=0,
                started_at=started_at.isoformat(),
                completed_at=started_at.isoformat(),
                error_message=f"Command '{command_name}' not found in registry"
            )
        
        # Validate arguments
        is_valid, error_msg = registry.validate_command_args(command_name, args)
        if not is_valid:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="",
                exit_code=-1,
                duration_ms=0,
                started_at=started_at.isoformat(),
                completed_at=started_at.isoformat(),
                error_message=error_msg
            )
        
        # Set timeout
        exec_timeout = self._validate_timeout(
            timeout if timeout is not None else cmd_def.timeout_default
        )
        
        # Build command
        command = self._build_command(cmd_def, args)
        
        logger.info(
            f"[{request_id}] Executing command '{command_name}' "
            f"with timeout {exec_timeout}s"
        )
        
        # Execute with concurrency limit
        async with self.limiter:
            try:
                # Run subprocess asynchronously
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    # Security: no shell, controlled environment
                    env={
                        "PATH": "/usr/local/bin:/usr/bin:/bin",
                        "HOME": str(Path.home()),
                        "LANG": "en_US.UTF-8"
                    }
                )
                
                # Wait with timeout
                try:
                    stdout_data, stderr_data = await asyncio.wait_for(
                        process.communicate(),
                        timeout=exec_timeout
                    )
                    exit_code = process.returncode
                    
                except asyncio.TimeoutError:
                    # Kill the process on timeout
                    logger.error(f"[{request_id}] Command '{command_name}' timed out after {exec_timeout}s")
                    try:
                        process.kill()
                        await process.wait()
                    except Exception as e:
                        logger.exception(f"[{request_id}] Error killing timed-out process: {e}")
                    
                    completed_at = datetime.now(timezone.utc)
                    duration_ms = (completed_at - started_at).total_seconds() * 1000
                    
                    return ExecutionResult(
                        success=False,
                        stdout="",
                        stderr="",
                        exit_code=-1,
                        duration_ms=duration_ms,
                        started_at=started_at.isoformat(),
                        completed_at=completed_at.isoformat(),
                        error_message=f"Command exceeded timeout of {exec_timeout}s"
                    )
                
                # Decode output
                stdout = stdout_data.decode('utf-8', errors='replace').strip()
                stderr = stderr_data.decode('utf-8', errors='replace').strip()
                
                completed_at = datetime.now(timezone.utc)
                duration_ms = (completed_at - started_at).total_seconds() * 1000
                
                success = exit_code == 0
                
                if success:
                    logger.info(
                        f"[{request_id}] Command '{command_name}' completed successfully "
                        f"in {duration_ms:.0f}ms"
                    )
                else:
                    logger.warning(
                        f"[{request_id}] Command '{command_name}' failed with exit code {exit_code} "
                        f"in {duration_ms:.0f}ms"
                    )
                
                return ExecutionResult(
                    success=success,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                    duration_ms=duration_ms,
                    started_at=started_at.isoformat(),
                    completed_at=completed_at.isoformat(),
                    error_message=None if success else f"Command failed with exit code {exit_code}"
                )
                
            except Exception as e:
                logger.exception(f"[{request_id}] Unexpected error executing '{command_name}': {e}")
                completed_at = datetime.now(timezone.utc)
                duration_ms = (completed_at - started_at).total_seconds() * 1000
                
                return ExecutionResult(
                    success=False,
                    stdout="",
                    stderr=str(e),
                    exit_code=-1,
                    duration_ms=duration_ms,
                    started_at=started_at.isoformat(),
                    completed_at=completed_at.isoformat(),
                    error_message=f"Execution error: {str(e)}"
                )

# Global executor instance
executor = SafeExecutor()