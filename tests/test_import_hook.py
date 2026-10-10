"""The future-import hook is Store.save(actor, owner_id, payload). It shares validation,
permissions and persistence with interactive editing (see README, "Importing characters later")."""
import json

import pytest

from imbot import model
from imbot.store import PermissionDenied
from tests.conftest import GM, GM_ROLE, GUILD, OWNER, PLAYER, User, actor, click, open_card, run

EXAMPLE_PAYLOAD = {
    "name": "Sister Ysolde Varn",
    "description": "Adepta Sororitas hospitaller, seconded to the Inquisition.",
    "characteristics": {"WS": 35, "BS": 30, "Str": 32, "Tgh": 38, "Ag": 36, "Int": 45, "Per": 40, "Wil": 50, "Fel": 42},
    "skills": [
        {"name": "Medicae", "rating": 60, "specialisations": [{"name": "Surgery", "rating": 65}], "notes": ""},
        {"name": "Discipline", "rating": 55},
    ],
    "talents": [{"name": "Field Medic", "notes": "Heal without a medikit at a penalty."}],
    "weapons": [{"name": "Chainsword", "damage": "9", "range": "Melee", "magazine": "—", "traits": "Rend (1), Loud"}],
    "armour": [{"name": "Carapace Armour", "locations": "Body, Arms, Legs", "armour": "5", "encumbrance": "2", "traits": "Bulky"}],
    "equipment": [{"name": "Medikit", "quantity": 1, "notes": "Full"}, {"name": "Rosarius", "quantity": 1}],
}


def test_example_payload_is_saved_and_displayed(store):
    store.set_gm_role(GUILD, GM_ROLE)
    importer = actor(GM, roles=[GM_ROLE])  # the person running the import, resolved from Discord, not from the file
    char, version = store.save(importer, OWNER, json.loads(json.dumps(EXAMPLE_PAYLOAD)))
    assert version == 1 and char["name"] == "Sister Ysolde Varn"

    async def scenario():
        card, i = await open_card(User(PLAYER), owner_id=OWNER)
        assert i.embed.title == "Sister Ysolde Varn" and f"<@{OWNER}>" in i.embed.description
        assert "**Wil** Willpower: 50" in i.embed.description
        i2 = await click(card, "Equipment", User(PLAYER))
        d = i2.embed.description
        assert "Chainsword" in d and "Carapace Armour" in d and "Medikit" in d and "Rend (1), Loud" in d
        i3 = await click(card, "Skills", User(PLAYER))
        assert "**Medicae** — 60" in i3.embed.description and "↳ Surgery — 65" in i3.embed.description
    run(scenario())


def test_omitted_fields_preserved_explicit_clear_erases(store):
    store.save(actor(OWNER), OWNER, EXAMPLE_PAYLOAD)
    char, _ = store.save(actor(OWNER), OWNER, {"characteristics": {"BS": 33}})
    assert char["characteristics"]["WS"] == 35 and char["characteristics"]["BS"] == 33
    assert char["skills"] == model.apply_patch(None, EXAMPLE_PAYLOAD)["skills"]
    char, _ = store.save(actor(OWNER), OWNER, {"talents": None, "description": ""})
    assert char["talents"] == [] and char["description"] == "" and char["weapons"]


def test_payload_cannot_grant_itself_permission(store):
    with pytest.raises(PermissionDenied):
        store.save(actor(PLAYER), OWNER, {**EXAMPLE_PAYLOAD, "name": "Taken over"})
    with pytest.raises(model.ValidationError):
        store.save(actor(OWNER), OWNER, {**EXAMPLE_PAYLOAD, "owner_id": PLAYER})
    with pytest.raises(model.ValidationError):
        store.save(actor(OWNER), OWNER, {**EXAMPLE_PAYLOAD, "guild_id": 999})
    assert store.load(GUILD, OWNER) is None  # nothing persisted by the failed attempts


def test_invalid_payload_leaves_existing_character_untouched(store):
    store.save(actor(OWNER), OWNER, EXAMPLE_PAYLOAD)
    with pytest.raises(model.ValidationError):
        store.save(actor(OWNER), OWNER, {"skills": [{"name": "Lore", "rating": "high"}]})
    assert store.load(GUILD, OWNER)[0]["skills"][0]["name"] == "Medicae"
