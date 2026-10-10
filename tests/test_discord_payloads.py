"""Serialise what we would send to Discord, so limit and signature mistakes fail here, not live."""
import discord

from imbot import bot, model
from tests.conftest import OWNER, User, click, open_card, run


def test_command_tree_serialises():
    payloads = [cmd.to_dict(bot.tree) for cmd in bot.tree.get_commands()]
    by_name = {p["name"]: p for p in payloads}
    menu = by_name["View Character"]
    assert menu["type"] == discord.AppCommandType.user.value
    assert menu.get("description", "") == ""
    for p in payloads:  # guild-only, guild-installed: never usable in DMs or via user install
        assert p["contexts"] == [0] and p["integration_types"] == [0] and p["dm_permission"] is False, p["name"]
    assert by_name["setup"]["default_member_permissions"] == discord.Permissions(administrator=True).value
    for sub in by_name["character"]["options"]:
        assert sub["type"] == 1 and 1 <= len(sub["description"]) <= 100
        for opt in sub.get("options", []):
            assert 1 <= len(opt["description"]) <= 100
            if sub["name"] != "roll":
                assert opt["type"] in (6, 8, 5, 11) and not opt.get("required", False)  # user, role, boolean, attachment
    roll = {o["name"]: o for s in by_name["character"]["options"] if s["name"] == "roll" for o in s["options"]}
    assert roll["skill"]["type"] == 3 and roll["skill"]["required"] and roll["skill"]["autocomplete"]
    assert roll["notes"]["type"] == 3 and not roll["notes"].get("required") and roll["notes"]["max_length"] == bot.ROLL_NOTES_MAX


def test_longest_roll_result_fits_one_message():
    wide = "𝔛"  # outside the BMP, so Discord counts it twice
    label = f"{wide * 60} ({wide * 60})"  # longest skill and specialisation names
    worst = bot.rolls.build_test_result(bot.rolls.Participant(wide * 80, 0, roll=100, skill_name=label), wide * bot.ROLL_NOTES_MAX)
    assert "Astounding Failure** (-10 SL)" in worst and bot.discord_len(worst) <= bot.MESSAGE_MAX


def test_card_components_and_embeds_serialise(card_user_store):
    async def scenario():
        card, i = await open_card(User(OWNER), owner_id=OWNER, editing=True)
        for section in ("Characteristics", "Skills", "Talents", "Equipment"):
            await click(card, section, User(OWNER))
            rows = card.to_components()
            assert 1 <= len(rows) <= 5
            for row in rows:
                assert row["type"] == 1 and 1 <= len(row["components"]) <= 5
            assert len(card.embed()) <= 6000 and card.embed().to_dict()
    run(scenario())


def test_forms_serialise_within_modal_limits():
    async def noop(i, raw):
        pass
    values = {"name": "x", "quantity": 3, "specialisations": [{"name": "a", "rating": 1}]}
    forms = [bot.Form("Identity", model.IDENTITY, values, noop)]
    forms += [bot.Form(f"Edit {k}", fields, values, noop) for k, (_, fields) in model.LIST_SPECS.items()]
    forms.append(bot.Form("Import character", [bot.IMPORT_FIELD], {}, noop))
    forms.append(bot.Form("Characteristics " * 5, [model.Field(a, f"{f} ({a})", 3, "int") for a, f in model.CHARACTERISTICS[:5]], {}, noop))
    for form in forms:
        d = form.to_dict()
        assert 1 <= len(d["title"]) <= 45 and 1 <= len(d["components"]) <= 5
        for comp in d["components"]:
            assert comp["type"] == 18 and len(comp["label"]) <= 45  # Label wrapping a text input
            ti = comp["component"]
            assert ti["type"] == 4 and 1 <= ti["max_length"] <= 4000
            if comp.get("description"):
                assert len(comp["description"]) <= 100
