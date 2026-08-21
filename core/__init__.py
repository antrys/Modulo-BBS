"""Modulo BBS core package.

Contains the game-loop internals the plugins build on: the event bus,
user model, plugin loader, and session management.
"""

from .events import CORE_EVENTS, EventBus
from .user import (
    InvalidFieldError,
    PermissionDenied,
    User,
    UserError,
    UserExistsError,
    UserManager,
    UserNotFoundError,
)

__all__ = [
    "CORE_EVENTS",
    "EventBus",
    "User",
    "UserManager",
    "UserError",
    "UserNotFoundError",
    "UserExistsError",
    "InvalidFieldError",
    "PermissionDenied",
]