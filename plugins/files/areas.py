"""File area storage for the files plugin."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class AreaStore:
    """File-area catalog + file listings.

    Catalog: data/files.json -- [{"id": "dos", "name": "DOS Files",
    "requires": []}, ...] (sysop-editable).

    Each file record lives at data/<area_id>/<file_id>.json:
      {"id": int, "name": "prog.zip", "size_bytes": 12345,
       "uploader": "dave", "description": "...", "timestamp": iso}
    Actual file bytes live beside it as data/<area_id>/store/<file_id>_<name>.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    # -- areas ---------------------------------------------------------------

    def load_areas(self) -> list[dict]:
        return load_areas(self.root)

    # -- records ----------------------------------------------------------------

    def _area_dir(self, area_id: str) -> Path:
        d = self.root / area_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_files(self, area_id: str) -> list[dict]:
        out = []
        for p in sorted(
            self._area_dir(area_id).glob("*.json"),
            key=lambda x: int(x.stem),
        ):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def add_file(self, area_id: str, name: str, size_bytes: int,
                 uploader: str, description: str) -> dict:
        existing = [int(p.stem) for p in self._area_dir(area_id).glob("*.json")]
        fid = (max(existing) + 1) if existing else 1
        rec = {
            "id": fid,
            "name": name,
            "size_bytes": size_bytes,
            "uploader": uploader,
            "description": description,
            "timestamp": datetime.now().astimezone().isoformat(),
        }
        p = self._area_dir(area_id) / f"{fid}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        tmp.replace(p)
        return rec

    def get_file(self, area_id: str, fid: int) -> dict | None:
        p = self._area_dir(area_id) / f"{fid}.json"
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def delete_file(self, area_id: str, fid: int) -> bool:
        p = self._area_dir(area_id) / f"{fid}.json"
        if p.is_file():
            p.unlink()
            return True
        return False

    def can_delete(self, user, rec: dict) -> bool:
        if rec.get("uploader") == user.username:
            return True
        return user.can_access(["moderator"])


def load_areas(root: Path) -> list[dict]:
    bj = root / "files.json"
    if bj.exists():
        try:
            return json.loads(bj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    areas = [{"id": "main", "name": "Main File Area", "requires": []}]
    bj.write_text(json.dumps(areas, indent=2), encoding="utf-8")
    return areas
