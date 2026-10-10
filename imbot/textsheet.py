"""Characters as plain text that players copy, edit and paste back. No Discord objects here.

One entry per line, columns separated by "|", lists under a heading::

    Name: Vex Harrow
    Description: A disgraced Administratum clerk.

    CHARACTERISTICS
    WS 30, BS 42, Str 28, Tgh 35, Ag 40, Int 48, Per 38, Wil 33, Fel 31

    SKILLS (Skill Total (Specialisation Total, ...) | Notes)
    Lore 58 (Adeptus Administratum 63) | Knows the forms.

    OTHER EQUIPMENT (Name | Quantity | Notes)
    Ration packs | 6

Reading is forgiving (any case, bullets, Markdown, the code fences of a copied Discord message)
and yields a patch for Store.save: whatever the text leaves out keeps its stored value, so a long
character can be imported one section at a time.
"""
from __future__ import annotations

import re

from . import model, render

TITLES = {**render.SECTION_TITLES, **render.EQUIPMENT_HEADINGS}  # characteristics + list key -> heading
HINTS = {"skills": "Skill Total (Specialisation Total, ...) | Notes",
         **{k: " | ".join(f.label for f in fields) for k, (_, fields) in model.LIST_SPECS.items() if k != "skills"}}

_HEADER = re.compile(r"^[#=*_\s-]*(characteristics|skills|talents|weapons|armou?r|(?:other\s+)?equipment)\b"
                     r"[*_\s]*(?:\(.*\))?[#=*_\s-]*(?::(.*))?$", re.IGNORECASE)
_ALIASES = {"armor": "armour", "other equipment": "equipment"}
_KEY = re.compile(r"^(name|description)\s*:(.*)$", re.IGNORECASE)
_BULLET = re.compile(r"^(?:[-–*•·]|\d+[.)])\s+")
_SKILL = re.compile(r"^(?P<name>.*?)[\s:=–—-]*(?P<rating>\d+)?\s*(?:\((?P<specs>[^()]*)\))?$")  # "Ranged: 52 (Pistols 57)"
_PAIR = re.compile(r"([A-Za-z][A-Za-z ]*?)\s*[:=]?\s*(\d+|[-–—?])")  # "WS 35", "Weapon Skill: 35", "WS -"
_CHARACTERISTIC = {k.lower(): abbr for abbr, full in model.CHARACTERISTICS for k in (abbr, full)}


# -- export ----------------------------------------------------------------------------

def format_text(c: dict | None) -> str:
    """``c`` as text that parse_text reads back unchanged, except that line breaks inside list
    entries become spaces. None gives a blank template."""
    c = c or model.empty_character()
    chars = c["characteristics"]
    out = [f"Name: {c['name']}", f"Description: {c['description']}", "", TITLES["characteristics"].upper(),
           ", ".join(f"{a} {'-' if chars.get(a) is None else chars[a]}" for a in model.CHARACTERISTIC_ABBRS)]
    for key in model.LIST_KEYS:
        out += ["", f"{TITLES[key].upper()} ({HINTS[key]})", *(_entry_line(key, e) for e in c[key])]
    return "\n".join(out)


def _entry_line(key: str, e: dict) -> str:
    if key == "skills":
        head = e["name"] if e.get("rating") is None else f"{e['name']} {e['rating']}"
        specs = model.format_specialisations(e.get("specialisations")).replace("\n", ", ")
        cells = [f"{head} ({specs})" if specs else head, e.get("notes") or ""]
    else:
        cells = [model.format_field(f, e.get(f.key)) for f in model.LIST_SPECS[key][1]]
    cells = [re.sub(r"\s*\n\s*", " ", c) for c in cells]
    cells = [c.replace("|", "/") for c in cells[:-1]] + cells[-1:]  # only the last column may hold a "|"
    while len(cells) > 1 and not cells[-1]:
        cells.pop()
    return " | ".join(cells)


# -- import ----------------------------------------------------------------------------

def parse_text(text: str) -> tuple[dict, list[str]]:
    """Read text in the export format into ``(patch, problems)``.

    Entries in ``patch`` are already validated; each line that could not be read is skipped and
    explained in ``problems``. A heading with no lines under it empties that list.
    """
    lines = text.splitlines()
    fenced = any(ln.strip().startswith("```") for ln in lines)  # a copied Discord message: read only its code block
    patch: dict = {}
    problems: list[str] = []
    section, inside = None, False  # section None: above every heading; "description": continuing it
    for n, line in enumerate(lines, 1):
        line = line.strip()
        if line.startswith("```"):
            inside = not inside
            continue
        if fenced and not inside:
            continue
        header, key = _HEADER.match(line), _KEY.match(line)
        if section == "description" and not header and not key:
            patch["description"] += "\n" + line
            continue
        if key:
            field = key[1].lower()
            patch[field] = key[2].strip()
            section = "description" if field == "description" else None
            continue
        if header:
            name = " ".join(header[1].lower().split())
            section = _ALIASES.get(name, name)
            patch.setdefault(section, {} if section == "characteristics" else [])
            line = (header[2] or "").strip()  # "Talents: Sharpshooter" carries an entry
        if not re.search(r"\w", line):
            continue
        if section is None:
            problems.append(_problem(n, line, "it is not under a heading such as SKILLS or TALENTS."))
        elif section == "characteristics":
            problems += _read_characteristics(n, line, patch["characteristics"])
        else:
            line = _BULLET.sub("", line)
            try:
                patch[section].append(_read_entry(section, line))
            except model.ValidationError as e:
                problems.append(_problem(n, line, str(e)))
    if "description" in patch:
        patch["description"] = patch["description"].strip()
    return patch, problems


def _problem(n: int, line: str, why: str) -> str:
    line = line.replace("`", "")
    return f"Line {n} `{line if len(line) <= 40 else line[:39] + '…'}`: {why}"


def _read_characteristics(n: int, line: str, out: dict) -> list[str]:
    pairs = _PAIR.findall(line)
    if not pairs:
        return [_problem(n, line, "write characteristics like WS 35, BS 40.")]
    problems = []
    for name, value in pairs:
        abbr = _CHARACTERISTIC.get(name.strip().lower())
        if abbr is None:
            problems.append(_problem(n, line, f"unknown characteristic; use {', '.join(model.CHARACTERISTIC_ABBRS)}."))
            continue
        try:
            out[abbr] = model.parse_field(model.Field(abbr, abbr, 3, "int"), value if value.isdigit() else None)
        except model.ValidationError as e:
            problems.append(_problem(n, line, str(e)))
    return problems


def _read_entry(key: str, line: str) -> dict:
    if key == "skills":
        main, _, notes = line.partition("|")
        m = _SKILL.match(main.strip())
        specs = [s.strip() for s in re.split(r"[,;]", m["specs"] or "") if s.strip()]
        entry = {"name": m["name"], "rating": m["rating"], "specialisations": specs, "notes": notes}
    else:
        keys = [f.key for f in model.LIST_SPECS[key][1]]
        entry = dict(zip(keys, (cell.strip() for cell in line.split("|", len(keys) - 1))))
    return model.validate_entry(key, entry)
