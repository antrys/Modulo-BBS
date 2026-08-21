"""
Tests for the core User model and UserManager.

These cover dataclass behavior, permission/flag semantics, bcrypt password
hashing, and JSON-file storage. Tests use a ``tmp_path`` scratch directory so
they never touch the real ``users/`` directory.
"""

import asyncio
import json

import pytest

from core.user import (
    User,
    UserManager,
    UserNotFoundError,
    UserExistsError,
    InvalidFieldError,
    UserError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine to completion in a fresh event loop."""
    return asyncio.run(coro)


@pytest.fixture
def manager(tmp_path):
    """A UserManager backed by a throwaway directory per test."""
    return UserManager(users_dir=tmp_path / "users")


# ---------------------------------------------------------------------------
# User dataclass + accessors
# ---------------------------------------------------------------------------

def test_default_fields():
    u = User(username="alice", display_name="Alice", password_hash="abc123")
    assert u.username == "alice"
    assert u.display_name == "Alice"
    assert u.flags == ["user"]
    assert u.stats == {}
    assert u.preferences == {}
    assert u.email == ""


def test_has_flag():
    u = User("bob", "Bob", "h", flags=["user", "mod"])
    assert u.has_flag("mod") is True
    assert u.has_flag("user") is True
    assert u.has_flag("sysop") is False


def test_default_user_can_basic_actions():
    u = User("carla", "Carla", "h")  # flags=["user"]
    assert u.has_permission("messageboard:read") is True
    assert u.has_permission("messageboard:post") is True
    assert u.has_permission("files:download") is True
    assert u.has_permission("chat:message") is True  # default non-admin action
    assert u.has_permission("messageboard:delete") is False  # moderation


def test_guest_is_read_only():
    u = User("g", "Guest", "h", flags=["guest"])
    assert u.has_permission("messageboard:read") is True
    assert u.has_permission("messageboard:post") is False
    assert u.has_permission("files:upload") is False


def test_mod_gets_moderation_actions():
    u = User("d", "Dave", "h", flags=["user", "mod"])
    assert u.has_permission("messageboard:delete") is True  # admin action, mod=>no
    assert u.has_permission("messageboard:edit") is True
    assert u.has_permission("messageboard:moderate") is True


def test_admin_gets_admin_and_user_management():
    u = User("e", "Eve", "h", flags=["admin"])
    assert u.has_permission("users:delete") is True
    assert u.has_permission("system:config") is True
    assert u.has_permission("messageboard:read") is True


def test_sysop_has_everything():
    u = User("o", "Owner", "h", flags=["sysop"])
    assert u.has_permission("anything:atall") is True
    assert u.has_permission("system:wipe") is True


def test_own_action_available_to_any_non_guest():
    user = User("f", "Faye", "h")
    assert user.has_permission("messageboard:delete_own") is True
    guest = User("g", "Guest", "h", flags=["guest"])
    assert guest.has_permission("messageboard:delete_own") is False


def test_empty_or_garbage_permission():
    u = User("x", "X", "h")
    assert u.has_permission("") is False
    assert u.has_permission(None) is False


def test_verify_password_bcrypt():
    pwd_hash = UserManager._hash_password("s3cret")
    u = User("y", "Y", pwd_hash)
    assert u.verify_password("s3cret") is True
    assert u.verify_password("wrong") is False


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

def test_to_from_dict_round_trip():
    u = User(
        username="roundtrip",
        display_name="RT",
        password_hash="hash",
        email="rt@example.com",
        flags=["user", "mod"],
        stats={"posts": 3},
        preferences={"theme": "dark"},
    )
    restored = User.from_dict(u.to_dict())
    assert restored.username == u.username
    assert restored.display_name == u.display_name
    assert restored.password_hash == u.password_hash
    assert restored.email == u.email
    assert restored.flags == u.flags
    assert restored.stats == u.stats
    assert restored.preferences == u.preferences
    assert restored.created == u.created


# ---------------------------------------------------------------------------
# UserManager CRUD
# ---------------------------------------------------------------------------

def test_create_and_get(manager):
    async def _test():
        user = await manager.create("tester", "hunter2", "Tester User", "t@x.com")
        assert user.username == "tester"
        assert user.flags == ["user"]
        assert await manager.get("tester") == user
        assert (await manager.get("tester")).verify_password("hunter2") is True
        # Wait for the coroutine to fully complete before asserting on the file.
        stored = await manager.get("tester")
        assert stored.password_hash != "hunter2"  # never store plaintext

    run(_test())


def test_create_default_display_name_and_email(manager):
    async def _test():
        user = await manager.create("anon", "pw")
        assert user.display_name == "anon"
        assert user.email == ""

    run(_test())


def test_create_duplicate_raises(manager):
    async def _test():
        await manager.create("dup", "pw", "Dup")
        with pytest.raises(UserExistsError):
            await manager.create("dup", "other", "Other")

    run(_test())


def test_get_missing_returns_none(manager):
    async def _test():
        assert await manager.get("ghost") is None

    run(_test())


def test_username_validation(manager):
    async def _test():
        for bad in ("", "UPPER", "has space", "a/b", 123, None):
            with pytest.raises(ValueError):
                await manager.create(bad, "pw")
            with pytest.raises(ValueError):
                await manager.create("ok", "pw")
                await manager.update(bad, display_name="x")

    run(_test())


def test_update_password_hashes(manager):
    async def _test():
        await manager.create("p", "oldpass", "P")
        await manager.update("p", password="newpass")
        user = await manager.get("p")
        assert user.verify_password("newpass") is True
        assert user.verify_password("oldpass") is False

    run(_test())


def test_update_other_fields(manager):
    async def _test():
        await manager.create("u", "pw", "Old Name")
        await manager.update(
            "u",
            display_name="New Name",
            email="new@x.com",
            flags=["user", "mod"],
            preferences={"theme": "light"},
            stats={"posts": 10},
        )
        user = await manager.get("u")
        assert user.display_name == "New Name"
        assert user.email == "new@x.com"
        assert user.flags == ["user", "mod"]
        assert user.preferences == {"theme": "light"}
        assert user.stats == {"posts": 10}

    run(_test())


def test_username_immutable(manager):
    async def _test():
        await manager.create("alice", "pw", "Alice")
        with pytest.raises(InvalidFieldError):
            await manager.update("alice", username="bob")
        # Old account still intact under the original name.
        assert (await manager.get("alice")) is not None

    run(_test())


def test_update_unknown_field_rejected(manager):
    async def _test():
        await manager.create("u", "pw", "U")
        with pytest.raises(InvalidFieldError):
            await manager.update("u", magic_field=42)

    run(_test())


def test_update_missing_user_raises(manager):
    async def _test():
        with pytest.raises(UserNotFoundError):
            await manager.update("nobody", display_name="X")

    run(_test())


def test_delete(manager):
    async def _test():
        await manager.create("gone", "pw", "Gone")
        assert await manager.delete("gone") is True
        assert await manager.get("gone") is None
        # Deleting a nonexistent user returns False, not an error.
        assert await manager.delete("gone") is False

    run(_test())


def test_list(manager):
    async def _test():
        for name in ("zeta", "alpha", "mid"):
            await manager.create(name, "pw", name.title())
        names = [u.username for u in await manager.list()]
        assert names == ["alpha", "mid", "zeta"]

    run(_test())


# ---------------------------------------------------------------------------
# Storage layout
# ---------------------------------------------------------------------------

def test_storage_layout_one_file_per_user(manager):
    async def _test():
        await manager.create("alice", "pw", "Alice")
        path = manager._path_for("alice")
        assert path.exists()
        data = json.loads(path.read_text("utf-8"))
        assert data["username"] == "alice"
        assert data["display_name"] == "Alice"
        assert "password_hash" in data

    run(_test())


def test_corrupt_file_skipped_in_list(manager):
    async def _test():
        (manager.users_dir / "broken.json").write_text("{not json", encoding="utf-8")
        await manager.create("good", "pw", "Good")
        names = [u.username for u in await manager.list()]
        assert names == ["good"]

    run(_test())


def test_corrupt_file_raises_on_get(manager):
    async def _test():
        (manager.users_dir / "broken.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(UserError):
            await manager.get("broken")

    run(_test())