"""Unit tests for the Modulo BBS event bus (core/events.py).

Tests are self-contained: each uses ``asyncio.run`` for its own event loop, so
no pytest-asyncio plugin or external dependency is required.
"""

import asyncio

from core.events import CORE_EVENTS, EventBus


def _run(coro):
    return asyncio.run(coro)


async def _drain(bus, event, data):
    """Emit and wait for all scheduled handler tasks to complete."""
    await asyncio.gather(*bus.emit(event, data))


# ---------------------------------------------------------------------------
# on() -- permanent handler
# ---------------------------------------------------------------------------


def test_on_handler_fires_with_data():
    async def scenario():
        bus = EventBus()
        received = []

        async def handler(data):
            received.append(data)

        bus.on("user:login", handler)
        await _drain(bus, "user:login", {"user": "alice"})
        return received

    assert _run(scenario()) == [{"user": "alice"}]


def test_on_handler_fires_every_emit():
    async def scenario():
        bus = EventBus()
        fired = []

        async def handler(data):
            fired.append(data["n"])

        bus.on("command:pre", handler)
        for n in range(3):
            await _drain(bus, "command:pre", {"n": n})
        return fired

    assert _run(scenario()) == [0, 1, 2]


# ---------------------------------------------------------------------------
# once() -- one-shot handler
# ---------------------------------------------------------------------------


def test_once_handler_fires_once_then_removed():
    async def scenario():
        bus = EventBus()
        fired = []

        async def handler(data):
            fired.append(data["n"])

        bus.once("user:login", handler)
        await _drain(bus, "user:login", {"n": 1})
        await _drain(bus, "user:login", {"n": 2})
        return fired, bus.handler_count("user:login")

    fired, count = _run(scenario())
    assert fired == [1]
    assert count == 0


# ---------------------------------------------------------------------------
# off() -- remove handler
# ---------------------------------------------------------------------------


def test_off_removes_handler():
    async def scenario():
        bus = EventBus()
        fired = []

        async def handler(data):
            fired.append(data["n"])

        bus.on("menu:select", handler)
        await _drain(bus, "menu:select", {"n": 1})
        bus.off("menu:select", handler)
        await _drain(bus, "menu:select", {"n": 2})
        return fired

    assert _run(scenario()) == [1]


def test_off_removes_once_handler():
    async def scenario():
        bus = EventBus()
        fired = []

        async def handler(data):
            fired.append(data["n"])

        bus.once("menu:select", handler)
        bus.off("menu:select", handler)
        await _drain(bus, "menu:select", {"n": 1})
        return fired, bus.handler_count("menu:select")

    fired, count = _run(scenario())
    assert fired == []
    assert count == 0


def test_off_unknown_handler_is_noop():
    """Removing a handler that was never registered must not raise."""

    def scenario():
        bus = EventBus()

        async def handler(data):
            pass

        bus.off("menu:open", handler)
        return True

    assert scenario()


# ---------------------------------------------------------------------------
# Multiple handlers / ordering / isolation
# ---------------------------------------------------------------------------


def test_multiple_handlers_all_fire_in_order():
    async def scenario():
        bus = EventBus()
        order = []

        async def first(data):
            order.append("first")

        async def second(data):
            order.append("second")

        async def third(data):
            order.append("third")

        bus.on("menu:open", first)
        bus.on("menu:open", second)
        bus.on("menu:open", third)
        await _drain(bus, "menu:open", {"menu_name": "main"})
        return order

    assert _run(scenario()) == ["first", "second", "third"]


def test_handler_exception_is_isolated():
    """A raising handler must not prevent other handlers or propagate to emit."""

    async def scenario():
        bus = EventBus()
        ok = []

        async def bad_handler(data):
            raise RuntimeError("plugin bug")

        async def good_handler(data):
            ok.append(data["option"])

        bus.on("menu:select", bad_handler)
        bus.on("menu:select", good_handler)
        await _drain(bus, "menu:select", {"option": "M"})
        return ok

    assert _run(scenario()) == ["M"]


def test_emit_with_no_handlers_returns_empty():
    def scenario():
        bus = EventBus()
        return bus.emit("menu:open", {})

    assert scenario() == []


# ---------------------------------------------------------------------------
# Core lifecycle events
# ---------------------------------------------------------------------------


def test_core_events_are_defined():
    assert set(CORE_EVENTS) == {
        "session:connect",
        "session:disconnect",
        "user:login",
        "user:logout",
        "menu:open",
        "menu:select",
        "command:pre",
        "command:post",
    }


def test_every_core_event_fires_handlers():
    async def scenario():
        bus = EventBus()
        fired = []

        async def record(name):
            async def handler(data):
                fired.append((name, data))
            return handler

        for event in CORE_EVENTS:
            bus.on(event, await record(event))

        for event in CORE_EVENTS:
            await _drain(bus, event, {"event": event})

        return fired

    fired = _run(scenario())
    assert [name for name, _ in fired] == list(CORE_EVENTS)
    # Every emit carried its own event name through the data payload.
    assert all(data["event"] == name for name, data in fired)


# ---------------------------------------------------------------------------
# Lifecycle-bus sanity: emit returns schedulable tasks
# ---------------------------------------------------------------------------


def test_emit_returns_tasks_that_can_be_awaited():
    async def scenario():
        bus = EventBus()
        received = []

        async def handler(data):
            await asyncio.sleep(0)
            received.append(data)

        bus.on("session:connect", handler)
        tasks = bus.emit("session:connect", {"session": "s1"})
        assert tasks, "emit should return handler tasks"
        await asyncio.gather(*tasks)
        return received

    assert _run(scenario()) == [{"session": "s1"}]


def test_default_data_is_empty_dict():
    async def scenario():
        bus = EventBus()
        received = []

        async def handler(data):
            received.append(data)

        bus.on("user:logout", handler)
        await _drain(bus, "user:logout", None)
        return received

    assert _run(scenario()) == [{}]