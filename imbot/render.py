"""Turn a character dict into plain-text pages. No Discord objects here.

A page is at most PAGE_CHARS characters and lists at most PAGE_ENTRIES entries so the
Discord layer can always fit it in one embed description and one 25-option select. A skills
page also has at most PAGE_ROLLS rated lines, so each can get its own roll button.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import model

PAGE_CHARS = 3600     # embed description limit is 4096; leave room for owner line, heading and a notice
PAGE_ENTRIES = 25     # select menu option limit
PAGE_ROLLS = 15       # roll buttons: the three rows of five a card leaves free

SECTIONS = ("characteristics", "skills", "talents", "equipment")
SECTION_TITLES = {
    "characteristics": "Characteristics",
    "skills": "Skills",
    "talents": "Talents",
    "equipment": "Equipment",
}
# Which stored lists feed each section (equipment merges three lists with headings).
SECTION_LISTS = {"skills": ["skills"], "talents": ["talents"], "equipment": ["weapons", "armour", "equipment"]}
EQUIPMENT_HEADINGS = {"weapons": "Weapons", "armour": "Armour", "equipment": "Other Equipment"}


@dataclass
class Page:
    text: str = ""
    entries: list[tuple[str, int]] = field(default_factory=list)  # (list_key, index) shown on this page
    rolls: int = 0  # rated skill and specialisation lines on this page


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def entry_label(list_key: str, entry: dict) -> str:
    """Short one-line label for select menus (≤100 chars)."""
    name = entry.get("name") or "(unnamed)"
    if list_key == "equipment" and entry.get("quantity") not in (None, 1):
        name = f"{name} ×{entry['quantity']}"
    return _clip(name, 100)


def skill_rolls(skill: dict) -> list[tuple[str, int]]:
    """(label, rating) of a skill and of its specialisations that have a rating, e.g. ("Lore (Academics)", 63)."""
    out = [(skill["name"], skill["rating"])] + [(f"{skill['name']} ({s['name']})", s["rating"]) for s in skill["specialisations"]]
    return [(label, rating) for label, rating in out if rating is not None]


def _stat(label: str, value) -> str:
    return "—" if value in (None, "") else str(value)


def _block(list_key: str, e: dict) -> str:
    name = f"**{e.get('name') or '(unnamed)'}**"
    notes = e.get("notes") or e.get("traits") or ""
    if list_key == "skills":
        lines = [f"{name} — {_stat('Rating', e.get('rating'))}"]
        for s in e.get("specialisations") or []:
            lines.append(f"  ↳ {s['name']} — {_stat('Rating', s.get('rating'))}")
    elif list_key == "talents":
        lines = [name]
    elif list_key == "weapons":
        lines = [f"{name} — Damage {_stat('', e.get('damage'))} · Range {_stat('', e.get('range'))} · Magazine {_stat('', e.get('magazine'))}"]
    elif list_key == "armour":
        lines = [f"{name} — Armour {_stat('', e.get('armour'))} · Locations {_stat('', e.get('locations'))} · Enc. {_stat('', e.get('encumbrance'))}"]
    else:  # equipment
        lines = [f"{name} ×{_stat('', e.get('quantity'))}"]
    if notes:
        lines.append(f"  _{notes}_")
    return "\n".join(lines)


def _characteristics_text(c: dict) -> str:
    vals = c.get("characteristics") or {}
    rows = [f"**{abbr}** {full}: {_stat('', vals.get(abbr))}" for abbr, full in model.CHARACTERISTICS]
    desc = c.get("description") or "_No description yet._"
    return f"{desc}\n\n" + "\n".join(rows)


def pages(c: dict, section: str) -> list[Page]:
    """Render ``section`` of character ``c`` into one or more pages. Never drops content."""
    if section == "characteristics":
        return [Page(_characteristics_text(c))]
    out: list[Page] = [Page()]
    for list_key in SECTION_LISTS[section]:
        entries = c.get(list_key) or []
        blocks: list[tuple[str, tuple[str, int] | None]] = []
        if section == "equipment":
            blocks.append((f"__**{EQUIPMENT_HEADINGS[list_key]}**__", None))
        if not entries:
            blocks.append((f"_No {EQUIPMENT_HEADINGS.get(list_key, section).lower()} recorded yet._", None))
        blocks += [(_block(list_key, e), (list_key, i)) for i, e in enumerate(entries)]
        for i, (text, ref) in enumerate(blocks):
            page = out[-1]
            # A heading must not be the last thing on a page.
            is_heading = ref is None and i + 1 < len(blocks)
            too_long = page.text and len(page.text) + len(text) + 2 > PAGE_CHARS
            rolls = len(skill_rolls(entries[ref[1]])) if ref is not None and list_key == "skills" else 0
            too_many = ref is not None and page.entries and (len(page.entries) >= PAGE_ENTRIES or page.rolls + rolls > PAGE_ROLLS)
            if too_long or too_many or (is_heading and len(page.text) + len(text) + len(blocks[i + 1][0]) + 4 > PAGE_CHARS):
                out.append(Page())
                page = out[-1]
            page.text = f"{page.text}\n\n{text}" if page.text else text
            if ref is not None:
                page.entries.append(ref)
                page.rolls += rolls
    return out
