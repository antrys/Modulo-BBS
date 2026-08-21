"""
User model and manager for Modulo BBS core.

The User model is core infrastructure -- every plugin references it. This module
owns the data structure, CRUD operations, password hashing (bcrypt), and flat
JSON-file storage in the ``users/`` directory at the project root.

Per the plugin spec: auth *flows* (login/registration screens) are owned by the
auth plugin; the core owns the model and storage only. Plugins check access via
``user.has_flag()`` and ``user.has_permission()`` rather than inspecting flags.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import bcrypt


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class UserError(Exception):
    """Base class for user-model errors."""


class UserNotFoundError(UserError, KeyError):
    """Raised when an operation targets a user that does not exist."""


class UserExistsError(UserError, ValueError):
    """Raised when creating a user whose username is already taken."""


class InvalidFieldError(UserError, ValueError):
    """Raised when an update targets a read-only or unknown field."""


class PermissionDenied(UserError, PermissionError):
    """Raised when a user lacks the permission to do something.

    This is not raised by the model itself (plugins check ``has_permission``
    and decide how to respond) but is provided for callers that prefer raising.
    """


# ---------------------------------------------------------------------------
# Permission / flag semantics
# ---------------------------------------------------------------------------

# Access levels, low to high. The user's effective level is the max of their
# flags' levels; a permission is granted when the user's level is >= the
# permission's required level.
_FLAG_LEVEL = {"guest": 0, "user": 1, "mod": 2, "admin": 3, "sysop": 4}

# Namespaces that concern account/system administration. Any permission in
# these namespaces requires admin (e.g. "users:delete", "system:config").
_ADMIN_NAMESPACES = ("users", "system", "config", "auth")

# Action keywords that (outside admin namespaces) require moderation level.
_MOD_ACTIONS = {"delete", "edit", "moderate", "warn", "kick", "ban", "unban"}

# Action keywords available to guests (read-only access).
_GUEST_ACTIONS = {"read", "view", "list", "search"}


def _action_of(permission: str) -> str:
    """Return the trailing action token of a ``namespace:action`` permission."""
    return permission.rsplit(":", 1)[-1].lower()


def _required_level(permission: str) -> int:
    """The minimum access level needed to perform ``permission``."""
    ns, _, _ = permission.rpartition(":")
    action = _action_of(permission)

    # Self-service: "namespace:delete_own" / "edit_own" — any non-guest.
    if action.endswith("_own"):
        return _FLAG_LEVEL["user"]

    # Account / system administration is admin-level, period.
    if ns in _ADMIN_NAMESPACES:
        return _FLAG_LEVEL["admin"]

    # Content moderation (in any content namespace) is mod-level.
    if action in _MOD_ACTIONS:
        return _FLAG_LEVEL["mod"]

    # Read-only access is available to guests.
    if action in _GUEST_ACTIONS:
        return _FLAG_LEVEL["guest"]

    # Everything else (post, reply, upload, download, send, join, ...) is
    # standard-user level.
    return _FLAG_LEVEL["user"]


def _user_level(flags) -> int:
    """The user's highest access level across their flags."""
    level = 0
    for flag in (flags or []):
        level = max(level, _FLAG_LEVEL.get(flag, 0))
    return level


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------

def _now() -> datetime:
    """Timezone-aware current time (UTC)."""
    return datetime.now().astimezone()


def _parse_datetime(value) -> datetime:
    """Parse a datetime from raw JSON (ISO-8601 string or already a datetime)."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed
    raise TypeError(f"Cannot parse datetime from {value!r}")


@dataclass
class User:
    """A Modulo BBS user account.

    The ``username`` is the immutable primary key -- it identifies the account
    and names its storage file. It cannot be changed after creation; use the
    auth/registration flow to enforce this, and the manager refuses updates to
    it. All other fields are mutable.
    """

    username: str
    display_name: str
    password_hash: str
    email: str = ""
    created: datetime = field(default_factory=_now)
    last_login: datetime | None = field(default=None)
    flags: list[str] = field(default_factory=lambda: ["user"])
    stats: dict = field(default_factory=dict)
    preferences: dict = field(default_factory=dict)

    # -- convenience accessors --------------------------------------------

    def has_flag(self, flag: str) -> bool:
        """True if the user holds the given flag (e.g. ``"mod"``)."""
        return flag in self.flags

    def has_permission(self, permission: str) -> bool:
        """True if the user is allowed to perform ``permission``.

        ``permission`` has the form ``"namespace:action"``, e.g.
        ``"messageboard:delete"``. Authorization is hierarchical by flag level:

        * ``sysop``  -- everything.
        * ``admin``  -- also all user/system administration namespaces
          (``users:*``, ``system:*``, ``config:*``, ``auth:*``).
        * ``mod``    -- also content moderation actions in any namespace
          (delete, edit, moderate, warn, kick, ban).
        * ``user``   -- standard actions (post, reply, upload, download...).
        * ``guest``  -- read-only actions (read, view, list, search).

        A ``namespace:action_own`` permission (e.g. ``"messageboard:delete_own"``)
        allows any non-guest to act on their own content.
        """
        if not permission:
            return False

        return _user_level(self.flags) >= _required_level(permission)

    def verify_password(self, password: str) -> bool:
        """Verify a plaintext password against the stored bcrypt hash."""
        if not self.password_hash:
            return False
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"), self.password_hash.encode("utf-8")
            )
        except (ValueError, TypeError):
            return False

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        return {
            "username": self.username,
            "display_name": self.display_name,
            "password_hash": self.password_hash,
            "email": self.email,
            "created": self.created.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "flags": list(self.flags),
            "stats": dict(self.stats),
            "preferences": dict(self.preferences),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """Build a User from a dict (as loaded from JSON storage)."""
        return cls(
            username=data["username"],
            display_name=data["display_name"],
            password_hash=data["password_hash"],
            email=data.get("email", ""),
            created=_parse_datetime(data.get("created", _now())),
            last_login=(
                _parse_datetime(data["last_login"])
                if data.get("last_login") else None
            ),
            flags=list(data.get("flags", ["user"])),
            stats=dict(data.get("stats", {})),
            preferences=dict(data.get("preferences", {})),
        )


# ---------------------------------------------------------------------------
# User manager (storage)
# ---------------------------------------------------------------------------

class UserManager:
    """CRUD access to users, persisted as one JSON file per account.

    Storage layout: ``users/<username>.json`` at the project root. Usernames
    are the immutable primary key and therefore also the filename, so they must
    be filesystem-safe -- validated on create.
    """

    # Characters permitted in a username (kept conservative for filesystem use).
    _USERNAME_ALPHABET = set("abcdefghijklmnopqrstuvwxyz0123456789_-")

    # Fields that may be modified via update(); anything else is rejected.
    _UPDATABLE = {
        "display_name", "email", "password", "password_hash",
        "flags", "stats", "preferences", "last_login",
    }

    def __init__(self, users_dir: str | Path | None = None):
        if users_dir is None:
            # Default: "users/" at the project root (two levels up from this file).
            users_dir = Path(__file__).resolve().parent.parent / "users"
        self.users_dir = Path(users_dir)
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    # -- paths -------------------------------------------------------------

    def _path_for(self, username: str) -> Path:
        return self.users_dir / f"{username}.json"

    @staticmethod
    def _validate_username(username: str) -> str:
        if not isinstance(username, str) or not username:
            raise ValueError("Username must be a non-empty string.")
        if not UserManager._USERNAME_ALPHABET.issuperset(username):
            raise ValueError(
                "Username may only contain lowercase letters, digits, '_' and '-'."
            )
        return username

    # -- queries -----------------------------------------------------------

    async def get(self, username: str) -> User | None:
        """Fetch a user by username, or None if they do not exist."""
        return await self.get_or_raise(username, raise_if_missing=False)

    async def get_or_raise(self, username: str, raise_if_missing: bool = True) -> User | None:
        """Fetch a user, raising :class:`UserNotFoundError` when missing."""
        path = self._path_for(username)
        async with self._lock:
            if not path.exists():
                if raise_if_missing:
                    raise UserNotFoundError(f"User '{username}' not found.")
                return None
            try:
                with path.open("r", encoding="utf-8") as fh:
                    return User.from_dict(json.load(fh))
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                raise UserError(f"Corrupt user file for '{username}': {e}") from e

    async def list(self) -> list[User]:
        """Return all users, sorted by username."""
        async with self._lock:
            users = []
            for path in sorted(self.users_dir.glob("*.json")):
                try:
                    with path.open("r", encoding="utf-8") as fh:
                        users.append(User.from_dict(json.load(fh)))
                except (json.JSONDecodeError, KeyError, TypeError):
                    # Skip corrupt files rather than crashing the whole listing.
                    continue
            return users

    def list_sync(self) -> list[User]:
        """Synchronous convenience wrapper around :meth:`list`."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            raise RuntimeError(
                "list_sync() cannot run inside a running event loop; use await list()."
            )
        return asyncio.run(self.list())

    # -- mutations ---------------------------------------------------------

    async def create(
        self,
        username: str,
        password: str,
        display_name: str | None = None,
        email: str | None = None,
        flags: list[str] | None = None,
    ) -> User:
        """Create and persist a new user account.

        Passwords are stored as a bcrypt hash, never in plaintext. Raises
        :class:`UserExistsError` if the username is already taken.
        """
        username = self._validate_username(username)
        if not password:
            raise ValueError("Password must not be empty.")
        display_name = (display_name or username).strip() or username

        # Hash in a worker thread so the event loop stays responsive.
        password_hash = await asyncio.to_thread(self._hash_password, password)

        user = User(
            username=username,
            display_name=display_name,
            password_hash=password_hash,
            email=email or "",
            flags=list(flags) if flags is not None else ["user"],
        )

        async with self._lock:
            path = self._path_for(username)
            if path.exists():
                raise UserExistsError(f"User '{username}' already exists.")
            await self._write(path, user)

        return user

    async def update(self, *args, **fields) -> User:
        """Update a user's mutable fields and persist.

        The first positional argument is the ``username``; all keyword arguments
        are the fields to update (``username`` itself is immutable and rejected
        if passed). Allowed fields: ``display_name``, ``email``, ``password``
        (plaintext, hashed on write), ``password_hash`` (raw, must already be
        bcrypt), ``flags``, ``stats``, ``preferences``, ``last_login``.
        """
        if len(args) > 1:
            raise TypeError("update() takes at most one positional argument (username).")
        if len(args) == 0 and "username" not in fields:
            raise TypeError("update() missing required argument: 'username'")

        # username is immutable: refuse any attempt to set it as a field.
        if "username" in fields:
            raise InvalidFieldError("'username' is immutable and cannot be updated.")

        username = args[0]
        username = self._validate_username(username)

        unknown = set(fields) - self._UPDATABLE
        if unknown:
            raise InvalidFieldError(
                f"Unknown or immutable field(s): {', '.join(sorted(unknown))}"
            )

        async with self._lock:
            user = await self._load_unlocked(username)
            if not user:
                raise UserNotFoundError(f"User '{username}' not found.")

            if "password" in fields:
                user.password_hash = await asyncio.to_thread(
                    self._hash_password, fields["password"]
                )
            elif "password_hash" in fields:
                user.password_hash = fields["password_hash"]

            if "display_name" in fields:
                user.display_name = fields["display_name"]
            if "email" in fields:
                user.email = fields["email"]
            if "flags" in fields:
                user.flags = list(fields["flags"])
            if "stats" in fields:
                user.stats = fields["stats"]
            if "preferences" in fields:
                user.preferences = fields["preferences"]
            if "last_login" in fields:
                user.last_login = _parse_datetime(fields["last_login"])

            await self._write(self._path_for(username), user)
        return user

    async def delete(self, username: str) -> bool:
        """Delete a user account. Returns True if it existed, False otherwise."""
        username = self._validate_username(username)
        path = self._path_for(username)
        async with self._lock:
            if not path.exists():
                return False
            path.unlink()
            return True

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _hash_password(password: str) -> str:
        """Hash a plaintext password with bcrypt (blocking; call via to_thread)."""
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    async def _load_unlocked(self, username: str) -> User | None:
        """Load a user without acquiring the lock (caller must hold it)."""
        path = self._path_for(username)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                return User.from_dict(json.load(fh))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise UserError(f"Corrupt user file for '{username}': {e}") from e

    @staticmethod
    async def _write(path: Path, user: User):
        """Atomically persist a user to ``path`` via a temp file + rename."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(user.to_dict(), indent=2), encoding="utf-8"
        )
        tmp.replace(path)