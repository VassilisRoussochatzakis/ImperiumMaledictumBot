"""The plain-text character format: what export writes, and how forgivingly import reads it."""
from imbot import model, textsheet
from tests.test_import_hook import EXAMPLE_PAYLOAD


def test_export_reads_back_unchanged():
    char = model.apply_patch(None, {
        **EXAMPLE_PAYLOAD,
        "description": "Hospitaller.\n\nSeconded to the Inquisition.",
        "characteristics": {**EXAMPLE_PAYLOAD["characteristics"], "Fel": None},
        "weapons": [*EXAMPLE_PAYLOAD["weapons"], {"name": "Knife", "range": "Melee"}],
    })
    text = textsheet.format_text(char)
    assert "Medicae 60 (Surgery 65)" in text and "Knife |  | Melee" in text and "Fel -" in text
    patch, problems = textsheet.parse_text(text)
    assert problems == [] and model.apply_patch(None, patch) == char
    patch, problems = textsheet.parse_text(textsheet.format_text(None))  # the blank template
    assert problems == [] and patch == model.empty_character()


def test_line_breaks_and_pipes_inside_entries_survive_as_text():
    char = model.apply_patch(None, {"name": "X", "talents": [{"name": "A|B", "notes": "one\ntwo | three"}]})
    patch, _ = textsheet.parse_text(textsheet.format_text(char))
    assert patch["talents"] == [{"name": "A/B", "notes": "one two | three"}]


def test_forgiving_reading_of_a_copied_message():
    messy = """Here is **Vex** as text. Copy it...
```text
NAME: Vex Harrow
description: Clerk.
Still the description.

## Characteristics: Weapon Skill 30 BS 42
Str: 28 / Tgh 35

**Skills**
- Lore 58 (Adeptus Administratum 63; Xenos) | Knows the forms.
• Awareness 43
-----
Armor: Flak Coat | Body, Arms | 3
other   equipment
1. Rope | 2
```
Anything after the code block is ignored.""".replace("\n", "\r\n")
    patch, problems = textsheet.parse_text(messy)
    assert problems == []
    assert patch == {
        "name": "Vex Harrow",
        "description": "Clerk.\nStill the description.",
        "characteristics": {"WS": 30, "BS": 42, "Str": 28, "Tgh": 35},
        "skills": [
            {"name": "Lore", "rating": 58, "notes": "Knows the forms.",
             "specialisations": [{"name": "Adeptus Administratum", "rating": 63}, {"name": "Xenos", "rating": None}]},
            {"name": "Awareness", "rating": 43, "specialisations": [], "notes": ""},
        ],
        "armour": [{"name": "Flak Coat", "locations": "Body, Arms", "armour": "3", "encumbrance": "", "traits": ""}],
        "equipment": [{"name": "Rope", "quantity": 2, "notes": ""}],
    }


def test_unreadable_lines_are_skipped_and_explained():
    patch, problems = textsheet.parse_text("Name: Vex\nSome stray line\nCHARACTERISTICS\nWS 30, Luck 5, BS 150\nwhatever\n"
                                           "SKILLS\nRanged 152\nStealth 40\nTALENTS\n| no name")
    assert patch == {"name": "Vex", "characteristics": {"WS": 30},
                     "skills": [{"name": "Stealth", "rating": 40, "specialisations": [], "notes": ""}], "talents": []}
    assert problems == [
        "Line 2 `Some stray line`: it is not under a heading such as SKILLS or TALENTS.",
        "Line 4 `WS 30, Luck 5, BS 150`: unknown characteristic; use WS, BS, Str, Tgh, Ag, Int, Per, Wil, Fel.",
        "Line 4 `WS 30, Luck 5, BS 150`: BS must be between 0 and 100.",
        "Line 5 `whatever`: write characteristics like WS 35, BS 40.",
        "Line 7 `Ranged 152`: Total must be between 0 and 100.",
        "Line 10 `| no name`: Talent is required.",
    ]


def test_text_that_leaves_sections_out_keeps_them():
    assert textsheet.parse_text("TALENTS\nSharpshooter | Ignore range penalties.") == (
        {"talents": [{"name": "Sharpshooter", "notes": "Ignore range penalties."}]}, [])
    assert textsheet.parse_text("Characteristics\nBS 45")[0] == {"characteristics": {"BS": 45}}


def test_skill_separators_people_type():
    patch, problems = textsheet.parse_text("SKILLS\nRanged: 50\nAwareness — 43 | sharp\nPsychic Mastery - 31 (Divination 36)\nStealth -")
    assert problems == [] and [(s["name"], s["rating"]) for s in patch["skills"]] == [
        ("Ranged", 50), ("Awareness", 43), ("Psychic Mastery", 31), ("Stealth", None)]
    assert patch["skills"][2]["specialisations"] == [{"name": "Divination", "rating": 36}]
