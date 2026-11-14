"""Loads the fixed organisation list from server/orgs.json.

In: the JSON file. Out: `{id: Org}`, with each phone exactly as the file has it.
It never invents, guesses or looks up a number; unverified entries stay `None`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from server.config import get_settings


@dataclass(frozen=True)
class Org:
    """One entry from orgs.json. `phone` is None until it is verified on the site."""

    id: str
    name: str
    phone: str | None
    aliases: tuple[str, ...]
    source_url: str | None = None
    verified_at: str | None = None

    @property
    def verified_phone(self) -> str | None:
        """The phone, but only when it was checked on the organisation's own site."""
        if self.phone and self.source_url and self.verified_at:
            return self.phone
        return None


def load_orgs(path: Path | None = None) -> dict[str, Org]:
    """Read orgs.json into `{id: Org}`. The file ships with phones unset on purpose."""
    target = Path(path or get_settings().orgs_path)
    raw = json.loads(target.read_text(encoding="utf-8"))
    orgs: dict[str, Org] = {}
    for entry in raw["orgs"]:
        org = Org(
            id=entry["id"],
            name=entry["name"],
            phone=entry.get("phone"),
            aliases=tuple(entry.get("aliases", ())),
            source_url=entry.get("source_url"),
            verified_at=entry.get("verified_at"),
        )
        orgs[org.id] = org
    return orgs
