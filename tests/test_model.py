import pytest

from imbot import model, render


def test_new_character_requires_name():
    with pytest.raises(model.ValidationError):
        model.apply_patch(None, {})
    c = model.apply_patch(None, {"name": "Vex"})
    assert c["name"] == "Vex" and c["skills"] == [] and set(c["characteristics"]) == set(model.CHARACTERISTIC_ABBRS)


def test_unknown_keys_and_smuggled_ownership_are_rejected():
    for bad in ({"name": "V", "owner_id": 1}, {"name": "V", "guild_id": 1}, {"name": "V", "is_gm": True},
                {"name": "V", "skills": [{"name": "Lore", "owner": 1}]}):
        with pytest.raises(model.ValidationError):
            model.apply_patch(None, bad)


def test_omitted_keeps_and_explicit_none_clears():
    c = model.apply_patch(None, {"name": "Vex", "description": "clerk", "characteristics": {"WS": 30, "BS": 40},
                                 "talents": [{"name": "T1"}]})
    c2 = model.apply_patch(c, {"characteristics": {"BS": 45}})
    assert c2["characteristics"]["WS"] == 30 and c2["characteristics"]["BS"] == 45
    assert c2["description"] == "clerk" and c2["talents"] == c["talents"]
    c3 = model.apply_patch(c2, {"description": None, "talents": None, "characteristics": {"WS": None}})
    assert c3["description"] == "" and c3["talents"] == [] and c3["characteristics"]["WS"] is None
    assert c3["characteristics"]["BS"] == 45


def test_ratings_validated():
    with pytest.raises(model.ValidationError):
        model.apply_patch(None, {"name": "V", "characteristics": {"WS": "abc"}})
    with pytest.raises(model.ValidationError):
        model.apply_patch(None, {"name": "V", "characteristics": {"WS": 101}})
    with pytest.raises(model.ValidationError):
        model.apply_patch(None, {"name": "V", "characteristics": {"STR": 30}})  # wrong abbreviation
    with pytest.raises(model.ValidationError):
        model.apply_patch(None, {"name": "V", "skills": [{"name": "Lore", "rating": -1}]})


def test_specialisations_text_and_list_forms():
    specs = model.parse_specialisations("Adeptus Mechanicus 45\nImperial Creed\n  \nVoid Born: 50")
    assert specs == [{"name": "Adeptus Mechanicus", "rating": 45}, {"name": "Imperial Creed", "rating": None},
                     {"name": "Void Born", "rating": 50}]
    assert model.parse_specialisations(specs) == specs
    assert model.format_specialisations(specs).splitlines() == ["Adeptus Mechanicus 45", "Imperial Creed", "Void Born 50"]
    with pytest.raises(model.ValidationError):
        model.parse_specialisations([{"rating": 5}])
    with pytest.raises(model.ValidationError):  # must stay editable in the 400-character form field
        model.parse_specialisations([{"name": "x" * 60, "rating": 10}] * 8)


def test_entry_defaults_and_limits():
    c = model.apply_patch(None, {"name": "V", "equipment": [{"name": "Rope"}], "weapons": [{"name": "Knife"}]})
    assert c["equipment"][0] == {"name": "Rope", "quantity": 1, "notes": ""}
    assert c["weapons"][0] == {"name": "Knife", "damage": "", "range": "", "magazine": "", "traits": ""}
    with pytest.raises(model.ValidationError):
        model.apply_patch(None, {"name": "V", "talents": [{"name": "x"}] * (model.MAX_ENTRIES + 1)})
    with pytest.raises(model.ValidationError):
        model.apply_patch(None, {"name": "V", "talents": [{"name": "x", "notes": "y" * 1001}]})
    with pytest.raises(model.ValidationError):
        model.apply_patch(None, {"name": "x" * 81})


def test_every_edit_form_fits_a_discord_modal():
    for key, (_, fields) in model.LIST_SPECS.items():
        assert 1 <= len(fields) <= 5, key
        for f in fields:
            assert len(f.label) <= 45 and len(f.hint) <= 100 and 1 <= f.max_length <= 4000
    assert len(model.IDENTITY) <= 5
    assert len(model.CHARACTERISTICS) == 9 and [a for a, _ in model.CHARACTERISTICS] == ["WS", "BS", "Str", "Tgh", "Ag", "Int", "Per", "Wil", "Fel"]
    assert len(model.SKILLS) == 20


def test_render_empty_sections_are_explicit():
    c = model.apply_patch(None, {"name": "V"})
    for section in render.SECTIONS:
        pages = render.pages(c, section)
        assert len(pages) == 1 and pages[0].entries == []
    eq = render.pages(c, "equipment")[0].text
    assert "Weapons" in eq and "Armour" in eq and "Other Equipment" in eq and "No weapons" in eq and "No armour" in eq


def test_render_paginates_without_losing_content():
    talents = [{"name": f"Talent {i:03d}", "notes": "Lorem ipsum " * 60} for i in range(60)]
    c = model.apply_patch(None, {"name": "V", "talents": talents})
    pages = render.pages(c, "talents")
    assert len(pages) > 1
    shown = [ref for p in pages for ref in p.entries]
    assert shown == [("talents", i) for i in range(60)]  # every entry exactly once, in order
    for p in pages:
        assert len(p.text) <= render.PAGE_CHARS and len(p.entries) <= render.PAGE_ENTRIES
        for _, i in p.entries:
            assert f"Talent {i:03d}" in p.text


def test_render_select_limit_with_many_tiny_entries():
    c = model.apply_patch(None, {"name": "V", "equipment": [{"name": f"i{i}"} for i in range(100)]})
    pages = render.pages(c, "equipment")
    assert all(len(p.entries) <= 25 for p in pages)
    assert sum(len(p.entries) for p in pages) == 100
    # a heading is never stranded at the bottom of a page
    for p in pages:
        assert not p.text.rstrip().endswith("__")


def test_render_equipment_subsections_in_order():
    c = model.apply_patch(None, {"name": "V", "weapons": [{"name": "Lasgun"}], "armour": [{"name": "Flak"}],
                                 "equipment": [{"name": "Rope", "quantity": 2}]})
    text = render.pages(c, "equipment")[0].text
    assert text.index("Weapons") < text.index("Lasgun") < text.index("Armour") < text.index("Flak") < text.index("Other Equipment") < text.index("Rope** ×2")
    assert render.entry_label("equipment", c["equipment"][0]) == "Rope ×2"
