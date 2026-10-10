"""The character data model: field specs, validation and patch merging.

Pure Python, no Discord objects. A character is a plain dict with exactly these keys::

    {
      "name": str,                           # required, 1-80 chars
      "description": str,                    # may be ""
      "characteristics": {abbr: int|None},   # one key per CHARACTERISTICS abbreviation, 0-100 or None
      "skills":    [ {name, rating, specialisations: [{name, rating}], notes} ],
      "talents":   [ {name, notes} ],
      "weapons":   [ {name, damage, range, magazine, traits} ],
      "armour":    [ {name, locations, armour, encumbrance, traits} ],
      "equipment": [ {name, quantity, notes} ],
    }

Patch semantics (used by Store.save and therefore by every editor and importer):
omitted key -> keep stored value; explicit None (or "" / []) -> clear; lists replace wholesale.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Field names follow the official Cubicle 7 character sheet (2023 printer-friendly edition).
# Characteristics in sheet order (abbreviation, full name). We store the sheet's "Current" row.
CHARACTERISTICS: list[tuple[str, str]] = [
    ("WS", "Weapon Skill"),
    ("BS", "Ballistic Skill"),
    ("Str", "Strength"),
    ("Tgh", "Toughness"),
    ("Ag", "Agility"),
    ("Int", "Intelligence"),
    ("Per", "Perception"),
    ("Wil", "Willpower"),
    ("Fel", "Fellowship"),
]
CHARACTERISTIC_ABBRS = [a for a, _ in CHARACTERISTICS]

# The 20 skills on the sheet with their linked characteristic, offered as a hint when adding
# a skill. Free text is accepted so homebrew skills are not blocked.
SKILLS: dict[str, str] = {
    "Athletics": "Str", "Awareness": "Per", "Dexterity": "Ag", "Discipline": "Wil", "Fortitude": "Tgh",
    "Intuition": "Per", "Linguistics": "Int", "Logic": "Int", "Lore": "Int", "Medicae": "Int",
    "Melee": "WS", "Navigation": "Int", "Presence": "Wil", "Piloting": "Ag", "Psychic Mastery": "Wil",
    "Ranged": "BS", "Rapport": "Fel", "Reflexes": "Ag", "Stealth": "Ag", "Tech": "Int",
}
HIT_LOCATIONS = ["Head", "Left Arm", "Right Arm", "Left Leg", "Right Leg", "Body"]

MAX_ENTRIES = 100   # per list; keeps pagination and select menus sane
SPECS_MAX_CHARS = 400  # specialisations text in the edit form
RATING_MAX = 100    # characteristics and skill ratings are percentile-style values


class ValidationError(Exception):
    """Human-readable; safe to show to the player."""


@dataclass(frozen=True)
class Field:
    key: str
    label: str                 # modal label, <=45 chars
    max_length: int = 100
    kind: str = "text"         # text | long | int | specs
    required: bool = False
    hint: str = ""             # modal description, <=100 chars


NAME = Field("name", "Name", 80, required=True)
NOTES = Field("notes", "Notes", 400, "long")

IDENTITY: list[Field] = [
    Field("name", "Character name", 80, required=True),
    Field("description", "Short description", 400, "long", hint="Origin, faction, role, a line of flavour..."),
]

# list key -> (singular label, fields). Order of fields = order in the edit form (max 5).
LIST_SPECS: dict[str, tuple[str, list[Field]]] = {
    "skills": ("Skill", [
        Field("name", "Skill", 60, required=True, hint="e.g. " + ", ".join(list(SKILLS)[:6]) + "..."),
        Field("rating", "Total", 3, "int", hint="The Total column on your sheet (0-100)"),
        Field("specialisations", "Specialisations", SPECS_MAX_CHARS, "specs",
              hint="One per line, name then total, e.g. Adeptus Mechanicus 45"),
        NOTES,
    ]),
    "talents": ("Talent", [
        Field("name", "Talent", 80, required=True),
        Field("notes", "Effect", 1000, "long", hint="Your own summary of what it does"),
    ]),
    "weapons": ("Weapon", [
        NAME,
        Field("damage", "Damage", 40),
        Field("range", "Range", 40),
        Field("magazine", "Mag.", 40, hint="Magazine"),
        Field("traits", "Traits & notes", 400, "long", hint="Traits, plus specialisation, test and encumbrance"),
    ]),
    "armour": ("Armour", [
        NAME,
        Field("locations", "Locations", 80, hint="e.g. " + ", ".join(HIT_LOCATIONS[:3]) + "..."),
        Field("armour", "Armour", 40, hint="Protection value"),
        Field("encumbrance", "Enc.", 40, hint="Encumbrance"),
        Field("traits", "Traits & notes", 400, "long"),
    ]),
    "equipment": ("Other equipment", [
        NAME,
        Field("quantity", "Quantity", 4, "int"),
        NOTES,
    ]),
}
LIST_KEYS = list(LIST_SPECS)

_SPEC_LINE = re.compile(r"^(?P<name>.*?)[\s,:-]*(?P<rating>\d+)?\s*$")


def empty_character() -> dict:
    return {
        "name": "",
        "description": "",
        "characteristics": {a: None for a in CHARACTERISTIC_ABBRS},
        **{k: [] for k in LIST_KEYS},
    }


# -- single values ---------------------------------------------------------------

def _int(label: str, value, maximum: int = RATING_MAX):
    if value in (None, ""):
        return None
    try:
        n = int(str(value).strip())
    except ValueError:
        raise ValidationError(f"{label} must be a whole number.") from None
    if not 0 <= n <= maximum:
        raise ValidationError(f"{label} must be between 0 and {maximum}.")
    return n


def _text(f: Field, value) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(f"{f.label} must be text.")
    value = value.strip()
    if f.required and not value:
        raise ValidationError(f"{f.label} is required.")
    if len(value) > f.max_length:
        raise ValidationError(f"{f.label} is too long (max {f.max_length} characters).")
    return value


def parse_specialisations(value) -> list[dict]:
    """Accept the stored list form or the form text ('Name 45' per line)."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [ln for ln in value.splitlines() if ln.strip()]
    if not isinstance(value, list):
        raise ValidationError("Specialisations must be a list.")
    out = []
    for item in value:
        if isinstance(item, str):
            m = _SPEC_LINE.match(item.strip())
            item = {"name": m["name"].strip(), "rating": m["rating"]}
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            raise ValidationError("Each specialisation needs a name, e.g. Adeptus Mechanicus 45.")
        out.append({"name": _text(Field("name", "Specialisation name", 60, required=True), item["name"]),
                    "rating": _int("Specialisation rating", item.get("rating"))})
    if len(out) > 20:
        raise ValidationError("At most 20 specialisations per skill.")
    if len(format_specialisations(out)) > SPECS_MAX_CHARS:  # same bound as the edit form, so imports stay editable
        raise ValidationError(f"Specialisations are too long (max {SPECS_MAX_CHARS} characters in total).")
    return out


def format_specialisations(specs: list[dict]) -> str:
    return "\n".join(f"{s['name']} {s['rating']}" if s.get("rating") is not None else s["name"] for s in specs or [])


def parse_field(f: Field, value):
    """Validate one field value (from a form string or an import payload)."""
    if f.kind == "int":
        return _int(f.label, value, 9999 if f.key == "quantity" else RATING_MAX)
    if f.kind == "specs":
        return parse_specialisations(value)
    return _text(f, value)


def format_field(f: Field, value) -> str:
    """Inverse of parse_field, for pre-filling forms."""
    if value is None:
        return ""
    if f.kind == "specs":
        return format_specialisations(value)
    return str(value)


# -- whole character ---------------------------------------------------------------

def validate_entry(list_key: str, entry) -> dict:
    singular, fields = LIST_SPECS[list_key]
    if not isinstance(entry, dict):
        raise ValidationError(f"Each {singular.lower()} must be an object.")
    unknown = set(entry) - {f.key for f in fields}
    if unknown:
        raise ValidationError(f"Unknown {singular.lower()} field(s): {', '.join(sorted(unknown))}.")
    out = {f.key: parse_field(f, entry.get(f.key)) for f in fields}
    if list_key == "equipment" and out["quantity"] is None:
        out["quantity"] = 1
    return out


def apply_patch(current: dict | None, patch: dict) -> dict:
    """Merge ``patch`` over ``current`` (None = new character) and return a fully validated character.

    Raises ValidationError without side effects. Unknown keys are rejected so that typos
    (and ownership/permission claims smuggled into a payload) can never be stored.
    """
    if not isinstance(patch, dict):
        raise ValidationError("Character data must be an object.")
    base = empty_character()
    if current:
        base.update({k: v for k, v in current.items() if k in base})
        base["characteristics"] = {**empty_character()["characteristics"], **current.get("characteristics", {})}
    unknown = set(patch) - set(base)
    if unknown:
        raise ValidationError(f"Unknown field(s): {', '.join(sorted(unknown))}.")
    out = dict(base)
    for f in IDENTITY:
        if f.key in patch:
            out[f.key] = _text(f, patch[f.key])
    if "characteristics" in patch:
        chars = patch["characteristics"]
        if chars is None:
            chars = {a: None for a in CHARACTERISTIC_ABBRS}
        if not isinstance(chars, dict):
            raise ValidationError("Characteristics must be an object of abbreviation -> rating.")
        bad = set(chars) - set(CHARACTERISTIC_ABBRS)
        if bad:
            raise ValidationError(f"Unknown characteristic(s): {', '.join(sorted(bad))}. Use {', '.join(CHARACTERISTIC_ABBRS)}.")
        out["characteristics"] = {**base["characteristics"], **{a: _int(a, v) for a, v in chars.items()}}
    for key in LIST_KEYS:
        if key in patch:
            items = patch[key] or []
            if not isinstance(items, list):
                raise ValidationError(f"{key} must be a list.")
            if len(items) > MAX_ENTRIES:
                raise ValidationError(f"At most {MAX_ENTRIES} {key} entries.")
            out[key] = [validate_entry(key, e) for e in items]
    if not out["name"]:
        raise ValidationError("Character name is required.")
    return out
