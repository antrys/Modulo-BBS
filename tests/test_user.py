"""Tests for the core User model and UserManager.

These cover dataclass behavior, permission/flag semantics, bcrypt password
hashing, and JSON-file storage. Tests use a ``tmp_path`` scratch directory so
they never touch the real ``users/`` directory.
"""

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


import asyncio

def run(coro):
    return asyncio.run(coro)

# ---------------------------------------------------------------------------
# Helpers
import asyncio

def run(coro):
    return asyncio.run(coro)

# ---------------------------------------------------------------------------

@pytest.fixture
def manager(tmp_path):
    """A UserManager backed by a throwaway directory per test."""
    return UserManager(users_dir=tmp_path / "users")


import asyncio

def run(coro):
    return asyncio.run(coro)

# ---------------------------------------------------------------------------
# User dataclass + accessors
import asyncio

def run(coro):
    return asyncio.run(coro)

# ---------------------------------------------------------------------------

def test_default_fields():
    u = User(username="alice", display_name="Alice", password_hash="abc123")
    assert u.username == "alice"
    assert u.display_name == "Alice"
    assert u.groups == ["user"]
    assert u.stats == {}
    assert u.preferences == {}
    assert u.email == ""


def test_default_user_group():
    u = User("bob", "Bob", "h")
    assert u.groups == ["user"]
    assert u.in_group("user") is True
    assert u.in_group("sysop") is False


def test_explicit_groups_membership():
    u = User("carla", "Carla", "h", groups=["Moderator", "veterans"])
    # case-insensitive membership
    assert u.in_group("moderator") is True
    assert u.in_group("VETERANS") is True
    assert u.in_group("sysop") is False


def test_sysop_group_has_everything():
    owner = User("o", "Owner", "h", groups=["sysop"])
    plain = User("p", "Plain", "h")          # groups=["user"]

    # sysop passes any gate, even ones naming unknown groups
    for req in ([], ["moderators"], ["secret-club"], ["traders", "veterans"]):
        assert owner.can_access(req) is True

    # a plain user only passes public and own-group gates
    assert plain.can_access([]) is True
    assert plain.can_access(["user"]) is True
    assert plain.can_access(["moderators"]) is False


def test_can_access_any_of_semantics():
    u = User("d", "D", "h", groups=["traders", "veterans"])
    assert u.can_access(["traders"]) is True
    assert u.can_access(["something-else", "Veterans"]) is True  # any-of
    assert u.can_access(["secret-club"]) is False
    assert u.can_access(None) is True       # None = public
    assert u.can_access([]) is True         # empty = public


def test_gate_helper_is_the_only_mechanism():
    # Plugin gates (menu items, actions, areas) all use can_access with the
    # configured requirement -- there is no second permission system.
    doors = User("door", "Door", "h", groups=["gamers"])
    assert doors.can_access(["gamers"]) is True      # door-menu game gate
    board = User("mb", "MB", "h", groups=[])         # default user
    assert board.can_access(["gamers"]) is False


def test_verify_password_bcrypt():
    pwd_hash = UserManager._hash_password("s3cret")
    u = User("y", "Y", pwd_hash)
    assert u.verify_password("s3cret") is True
    assert u.verify_password("wrong") is False


import asyncio

def run(coro):
    return asyncio.run(coro)

# ---------------------------------------------------------------------------
# Serialization round-trip
import asyncio

def run(coro):
    return asyncio.run(coro)

# ---------------------------------------------------------------------------

def test_to_from_dict_round_trip():
    u = User(
        username="roundtrip",
        display_name="RT",
        password_hash="hash",
        email="rt@example.com",
        groups=["moderator", "veterans"],
        stats={"posts": 3},
        preferences={"theme": "dark"},
    )
    restored = User.from_dict(u.to_dict())
    assert restored.username == u.username
    assert restored.display_name == u.display_name
    assert restored.password_hash == u.password_hash
    assert restored.email == u.email
    assert restored.groups == u.groups
    assert restored.stats == u.stats
    assert restored.preferences == u.preferences
    assert restored.created == u.created


import asyncio

def run(coro):
    return asyncio.run(coro)

# ---------------------------------------------------------------------------
# UserManager CRUD
import asyncio

def run(coro):
    return asyncio.run(coro)

# ---------------------------------------------------------------------------

def test_create_and_get(manager):
    async def _test():
        user = await manager.create("tester", "hunter2", "Tester User", "t@x.com")
        assert user.username == "tester"
        assert user.groups == ["user"]
        assert await manager.get("tester") == user
        assert (await manager.get("tester")).verify_password("hunter2") is True
        # Wait for the coroutine to fully complete before asserting on the file.
        stored = await manager.get("tester")
        assert stored.password_hash != "hunter2"  # never store plaintext

    run(_test())


def test_create_default_display_name_and_email(manager):
    async def _test():
        user = await manager.create("anon", "pw")
        # display_name is now optional: blank means "fall back to username"
        assert user.display_name == ""
        assert user.shown_name() == "anon"
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
            groups=["moderator"],
            preferences={"theme": "light"},
            stats={"posts": 10},
        )
        user = await manager.get("u")
        assert user.display_name == "New Name"
        assert user.email == "new@x.com"
        assert user.groups == ["moderator"]
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


import asyncio

def run(coro):
    return asyncio.run(coro)

# ---------------------------------------------------------------------------
# Storage layout
import asyncio

def run(coro):
    return asyncio.run(coro)

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

# ---------------------------------------------------------------------------
# Groups / area access
# ---------------------------------------------------------------------------

def test_groups_membership_and_access():
    u = User(username="dave", display_name="", password_hash="x",
             groups=["Veterans", "linux-users"])

    # membership is case-insensitive
    assert u.in_group("veterans")
    assert u.in_group("LINUX-USERS")
    assert not u.in_group("mods-only")

    # can_access: empty requirement = public
    assert u.can_access(None)
    assert u.can_access([])

    # intersection grants
    assert u.can_access(["veterans"])
    assert u.can_access(["something-else", "Linux-Users"])  # any-of, not all-of
    assert not u.can_access(["secret-club"])


def test_sysop_group_bypasses_group_requirements():
    sysop = User(username="s", display_name="", password_hash="x",
                 groups=["sysop"])
    plain = User(username="p", display_name="", password_hash="x")

    assert sysop.can_access(["secret-club"])       # sysop group sees everything
    assert not plain.can_access(["secret-club"])   # non-member denied
    assert plain.can_access([])                    # but public areas fine


def test_groups_persist_roundtrip(tmp_path):
    manager = UserManager(users_dir=tmp_path / "users")

    async def _test():
        await manager.create("alice", "pw", groups=["veterans"])
        fetched = await manager.get("alice")
        assert fetched.groups == ["veterans"]
        # update() accepts the groups field
        updated = await manager.update("alice", groups=["Vets", "traders"])
        assert updated.groups == ["vets", "traders"]   # normalised to lowercase

    run(_test())


def test_legacy_user_file_without_groups_loads(tmp_path):
    # A users/dave.json written before groups existed must still load.
    users_dir = tmp_path / "users"
    users_dir.mkdir(parents=True)
    legacy = {
        "username": "dave", "display_name": "Dave",
        "password_hash": "$2b$12$x" * 4, "email": "",
        "created": "2026-01-01T00:00:00+00:00", "last_login": None,
        "flags": ["user"], "stats": {}, "preferences": {},
    }
    (users_dir / "dave.json").write_text(json.dumps(legacy), encoding="utf-8")
    manager = UserManager(users_dir=users_dir)

    async def _test():
        u = await manager.get("dave")
        assert u is not None
        # Legacy file had no groups key; user now defaults to the standard
        # "user" group (a sysop can reassign, e.g. to ["sysop"], as needed).
        assert u.groups == ["user"]

    run(_test())
