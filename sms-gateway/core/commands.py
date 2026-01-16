"""
Command Registry - Whitelist of allowed commands with validation schemas
"""
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from core.config import settings

class CommandDefinition(BaseModel):
    """Definition of an allowed command"""
    name: str
    script_path: Path
    description: str
    timeout_default: int = 30
    args_schema: Dict[str, Any] = Field(default_factory=dict)
    
    def validate_args(self, args: Dict[str, Any]) -> bool:
        """
        Validate arguments against schema (basic validation)
        For production, consider using jsonschema or pydantic models
        """
        if not self.args_schema:
            return len(args) == 0
        
        # Basic type checking
        for key, expected_type in self.args_schema.items():
            if key in args:
                if not isinstance(args[key], expected_type):
                    return False
        return True

class CommandRegistry:
    """Registry of whitelisted commands"""
    
    def __init__(self):
        self._commands: Dict[str, CommandDefinition] = {}
        self._initialize_commands()
    
    def _initialize_commands(self):
        """Initialize the command whitelist"""
        scripts_dir = settings.SCRIPTS_DIR
        
        # Define whitelisted commands
        commands = [
            CommandDefinition(
                name="send_alert_power",
                script_path=scripts_dir / "send_alert_power_sms.py",
                description="Send power outage alert SMS to configured recipients",
                timeout_default=60,
                args_schema={}
            ),
            CommandDefinition(
                name="send_alert_network",
                script_path=scripts_dir / "send_alert_network_sms.py",
                description="Send network outage alert SMS to configured recipients",
                timeout_default=60,
                args_schema={}
            ),
            CommandDefinition(
                name="send_reminder",
                script_path=scripts_dir / "send_reminder_sms.py",
                description="Send reminder SMS about ongoing outage",
                timeout_default=60,
                args_schema={}
            ),
            CommandDefinition(
                name="send_clear",
                script_path=scripts_dir / "send_clear_sms.py",
                description="Send clear/recovery SMS notification",
                timeout_default=60,
                args_schema={}
            ),
            # Add more commands as needed
            # CommandDefinition(
            #     name="custom_command",
            #     script_path=scripts_dir / "custom_script.py",
            #     description="Custom command with arguments",
            #     timeout_default=30,
            #     args_schema={
            #         "message": str,
            #         "count": int
            #     }
            # )
        ]
        
        # Verify all scripts exist
        for cmd in commands:
            if not cmd.script_path.exists():
                raise FileNotFoundError(
                    f"Script for command '{cmd.name}' not found: {cmd.script_path}"
                )
            self._commands[cmd.name] = cmd
    
    def get_command(self, name: str) -> Optional[CommandDefinition]:
        """Get command definition by name"""
        return self._commands.get(name)
    
    def list_commands(self) -> list[CommandDefinition]:
        """List all available commands"""
        return list(self._commands.values())
    
    def is_valid_command(self, name: str) -> bool:
        """Check if command exists in registry"""
        return name in self._commands
    
    def validate_command_args(self, name: str, args: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate command arguments
        Returns (is_valid, error_message)
        """
        cmd = self.get_command(name)
        if not cmd:
            return False, f"Command '{name}' not found"
        
        if not cmd.validate_args(args):
            return False, f"Invalid arguments for command '{name}'"
        
        return True, None

# Global registry instance
registry = CommandRegistry()