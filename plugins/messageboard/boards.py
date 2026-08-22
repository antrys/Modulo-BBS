"""Message storage helpers for the messageboard plugin."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class BoardStore:
    """JSON-per-message storage under data/<board_id>/."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def messages_dir(self, board_id: str) -> Path:
        d = self.root / board_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_messages(self, board_id: str) -> list[dict]:
        out = []
        for p in sorted(
            self.messages_dir(board_id).glob("*.json"),
            key=lambda x: int(x.stem),
        ):
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
                out.append(m)
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def get_message(self, board_id: str, msg_id: int) -> dict | None:
        p = self.messages_dir(board_id) / f"{msg_id}.json"
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def add_message(self, board_id: str, author: str, subject: str, body: str) -> dict:
        existing = [int(p.stem) for p in self.messages_dir(board_id).glob("*.json")]
        msg_id = (max(existing) + 1) if existing else 1
        msg = {
            "id": msg_id,
            "author": author,
            "subject": subject,
            "body": body,
            "timestamp": datetime.now().astimezone().isoformat(),
        }
        p = self.messages_dir(board_id) / f"{msg_id}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(msg, indent=2), encoding="utf-8")
        tmp.replace(p)
        return msg

    def delete_message(self, board_id: str, msg_id: int) -> bool:
        p = self.messages_dir(board_id) / f"{msg_id}.json"
        if p.is_file():
            p.unlink()
            return True
        return False

    def count(self, board_id: str) -> int:
        return len(list(self.messages_dir(board_id).glob("*.json")))


def load_boards(root: Path) -> list[dict]:
    """Load boards.json from root, creating a default on first run."""
    bj = root / "boards.json"
    if bj.exists():
        try:
            return json.loads(bj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    boards = [{"id": "general", "name": "General Discussion", "requires": []}]
    bj.write_text(json.dumps(boards, indent=2), encoding="utf-8")
    return boards


def can_delete(user, msg: dict) -> bool:
    """Own messages always; any message if user passes the moderator gate."""
    if msg.get("author") == user.username:
        return True
    return user.can_access(["moderator"])
