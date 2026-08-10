"""
DeepTempo Core - Shared library for DeepTempo AI SOC projects.
"""

__version__ = "1.0.0"

from deeptempo_core.config import (
    get_config_dir,
    is_demo_mode,
    get_integration_config,
    is_integration_enabled,
)

from deeptempo_core.exceptions import (
    SOCError,
    ConfigError,
    ToolError,
    DatabaseError,
    AuthError,
    RateLimitError,
    ValidationError,
)

__all__ = [
    "__version__",
    "get_config_dir",
    "is_demo_mode",
    "get_integration_config",
    "is_integration_enabled",
    "SOCError",
    "ConfigError",
    "ToolError",
    "DatabaseError",
    "AuthError",
    "RateLimitError",
    "ValidationError",
]

