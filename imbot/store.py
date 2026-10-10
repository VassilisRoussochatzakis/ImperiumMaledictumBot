"""SQLite persistence, permissions and the single save entry point.

Nothing in this module knows about Discord UI objects. Interactive editing
(bot.py) and any future importer both go through :meth:`Store.save`.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import model

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id   INTEGER PRIMARY KEY,
    gm_role_id INTEGER
);
CREATE TABLE IF NOT EXISTS characters (
    guild_id   INTEGER NOT NULL,
    owner_id   INTEGER NOT NULL,
    version    INTEGER NOT NULL,
    data       TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    updated_by INTEGER NOT NULL,
    PRIMARY KEY (guild_id, owner_id)
);
"""


@dataclass(frozen=True)
class Actor:
    """Who is acting, resolved by the caller from Discord *at the moment of the action*.

    Never build this from data inside a payload: ownership and permission claims
    in imported data are not trusted.
    """

    guild_id: int
    user_id: int
    role_ids: frozenset[int] = frozenset()
    is_admin: bool = False


class PermissionDenied(Exception):
    """The actor may not edit this character."""


class StaleEdit(Exception):
    """The character changed since the form was opened; nothing was written."""


class Store:
    """One SQLite file. Safe to call from a single asyncio thread (the bot)."""

    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path, isolation_level=None)  # autocommit; we open explicit transactions
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # -- guild settings -----------------------------------------------------
    def gm_role(self, guild_id: int) -> int | None:
        row = self.db.execute("SELECT gm_role_id FROM guild_settings WHERE guild_id=?", (guild_id,)).fetchone()
        return row[0] if row else None

    def set_gm_role(self, guild_id: int, role_id: int | None) -> None:
        self.db.execute(
            "INSERT INTO guild_settings (guild_id, gm_role_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET gm_role_id=excluded.gm_role_id",
            (guild_id, role_id),
        )

    # -- permissions --------------------------------------------------------
    def can_edit(self, actor: Actor, owner_id: int) -> bool:
        """Owner, server administrator, or member of the configured GM role."""
        if actor.user_id == owner_id or actor.is_admin:
            return True
        gm = self.gm_role(actor.guild_id)
        return gm is not None and gm in actor.role_ids

    # -- characters ---------------------------------------------------------
    def load(self, guild_id: int, owner_id: int) -> tuple[dict, int] | None:
        """Return (character, version) or None. Guild isolation is the primary key."""
        row = self.db.execute(
            "SELECT data, version FROM characters WHERE guild_id=? AND owner_id=?", (guild_id, owner_id)
        ).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def save(self, actor: Actor, owner_id: int, patch: dict, expected_version: int | None = None) -> tuple[dict, int]:
        """Validate ``patch``, merge it over the stored character and write atomically.

        This is the import hook as well as the interactive save path.

        * ``patch`` follows the shape documented in :mod:`imbot.model` (see README "Data shape").
          Omitted keys keep their stored value; explicit ``None`` (or ``[]``/``""``) clears.
        * ``expected_version`` enables optimistic locking: pass the version you displayed
          and the write is refused with :class:`StaleEdit` if someone saved in between.
        * Raises :class:`PermissionDenied` or :class:`model.ValidationError`; nothing is
          written in either case.
        Returns the stored (character, new_version).
        """
        if not self.can_edit(actor, owner_id):
            raise PermissionDenied
        self.db.execute("BEGIN IMMEDIATE")
        try:
            current = self.load(actor.guild_id, owner_id)
            cur_data, cur_version = current if current else (None, 0)
            if expected_version is not None and expected_version != cur_version:
                raise StaleEdit
            merged = model.apply_patch(cur_data, patch)  # ValidationError propagates, nothing written
            new_version = cur_version + 1
            self.db.execute(
                "INSERT INTO characters (guild_id, owner_id, version, data, updated_at, updated_by) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id, owner_id) DO UPDATE SET version=excluded.version, data=excluded.data, "
                "updated_at=excluded.updated_at, updated_by=excluded.updated_by WHERE version=?",
                (actor.guild_id, owner_id, new_version, json.dumps(merged, ensure_ascii=False),
                 datetime.now(timezone.utc).isoformat(timespec="seconds"), actor.user_id, cur_version),
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return merged, new_version

    def delete(self, actor: Actor, owner_id: int) -> bool:
        if not self.can_edit(actor, owner_id):
            raise PermissionDenied
        cur = self.db.execute("DELETE FROM characters WHERE guild_id=? AND owner_id=?", (actor.guild_id, owner_id))
        return cur.rowcount > 0
