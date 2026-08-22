"""Doors plugin: sysop-configurable door game catalog with group gates."""
from __future__ import annotations

import json
import logging

from plugins.base import Plugin

logger = logging.getLogger("modulo.plugins.doors")

DEFAULT_KEYS = {"QUIT": "Q"}


class DoorsPlugin(Plugin):
    """Door game launcher menu.

    The catalog lives in data/doors.json (sysop-editable):
      [{"id": "tradewars", "name": "TradeWars 2002", "requires": ["veterans"]}]
    Hotkeys come from the keys file, mapping KEY -> door id. A door missing
    from the keys file is hidden entirely; a keys line naming an unknown
    door id is skipped with a warning.
    """

    name = "doors"
    version = "1.0.0"
    description = "Door game launcher menu"
    menu_label = "[D] Doors"
    menu_key = "D"
    menu_order = 30

    def __init__(self):
        self.bbs = None
        self.catalog: list[dict] = []
        self.keys: dict[str, str] = {}  # key -> door_id

    def on_load(self, bbs):
        self.bbs = bbs
        d = bbs.storage.dir("doors")
        cj = d / "doors.json"
        if cj.exists():
            try:
                self.catalog = json.loads(cj.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("doors catalog unreadable (%s); empty", e)
                self.catalog = []
        else:
            sample = [{"id": "tradewars", "name": "TradeWars 2002", "requires": []}]
            cj.write_text(json.dumps(sample, indent=2), encoding="utf-8")
            self.catalog = sample
        # keys file maps NAME -> KEY where NAME is the uppercased door id
        # (loader contract); we invert to KEY -> door id here. A keys line
        # naming a door not in the catalog is skipped with a warning by the
        # loader itself (unknown command), so anything bound here is valid;
        # catalog doors missing from the file are hidden (disabled).
        defaults = {d["id"].upper(): d["id"].upper()[:1] for d in self.catalog}
        bound = bbs.keys_for("doors", defaults)
        by_upper = {d["id"].upper(): d for d in self.catalog}
        for name, key in bound.items():
            door = by_upper.get(name)
            if door is None:
                logger.warning("doors keys: unknown door id %r skipped", name)
                continue
            self.keys[key] = door["id"]

    # -- access --------------------------------------------------------------

    def visible_doors(self, user) -> list[dict]:
        out = []
        for d in self.catalog:
            did = d["id"]
            if did not in set(self.keys.values()):
                continue  # disabled by omission from keys file
            if not user.can_access(d.get("requires", [])):
                continue
            out.append(d)
        return out

    def door_by_id(self, door_id: str) -> dict | None:
        return next((d for d in self.catalog if d["id"] == door_id), None)

    # -- flow ------------------------------------------------------------------

    async def on_session_start(self, session) -> bool:
        while getattr(session, "is_active", True):
            doors = self.visible_doors(getattr(session, "user", None))
            lines = ["", " Doors", " ====="]
            key_for = {}
            for key, did in sorted(self.keys.items()):
                door = next((x for x in doors if x["id"] == did), None)
                if door:
                    lines.append(f" [{key}] {door['name']}")
                    key_for[key] = door
            lines.append(f" [{self._quit_key()}] Back to Main Menu")
            lines.append("")
            await self.bbs.send(session, "\r\n".join(lines) + "\r\n")
            pick = await self._ask(session, "Door: ")
            if not pick or pick.upper() == self._quit_key():
                return False
            pick_u = pick.upper()
            if pick_u in key_for:
                await self._launch(session, key_for[pick_u])
            else:
                await self.bbs.send(session, "\r\nInvalid selection.\r\n")
        return False

    async def _launch(self, session, door: dict):
        self.bbs.events.emit(
            "doors:launch", {"session": session, "door_id": door["id"]}
        )
        await self.bbs.send(
            session,
            f"\r\nLaunching {door['name']}...\r\n"
            "(door protocols not implemented yet)\r\n\r\n",
        )

    async def handle_command(self, session, command) -> bool:
        if (command or "").strip().upper() == self._quit_key():
            return False
        return True

    def _quit_key(self) -> str:
        qk = getattr(self, "_qkey", None)
        if qk:
            return qk
        kf = self.bbs.keys_for("doors", {"QUIT": "Q"}) if self.bbs else {"QUIT": "Q"}
        self._qkey = kf.get("QUIT", "Q")
        return self._qkey

    async def _ask(self, session, prompt: str) -> str:
        import asyncio

        await self.bbs.send(session, prompt)
        reader = getattr(session, "reader", None)
        if reader is None:
            return ""
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=300)
        except Exception:
            return ""
        return raw.decode("latin-1", errors="replace").strip()


__all__ = ["DoorsPlugin"]
