"""Discord-layer behaviour with fake interactions: privacy, navigation, permissions, staleness."""
import re
from pathlib import Path

import discord

from imbot import bot, model, textsheet
from tests.conftest import (ADMIN, GM, GM_ROLE, GUILD, OTHER_GUILD, OWNER, PLAYER, Fake, User, actor, button, choose,
                            click, labels, open_card, run, submit)


# -- privacy ---------------------------------------------------------------------------

def test_all_sends_go_through_reply_and_are_ephemeral_except_the_roll_result():
    src = Path(bot.__file__).read_text(encoding="utf-8")
    body = src.split("async def reply(")[1].split("\n\n\n")[0]
    assert body.count("ephemeral=True") == 2  # both the first response and the follow-up branch
    roll = src.split("async def character_roll(")[1].split("\n\n\n")[0]
    assert roll.count("send_message(") == 1  # the one public message
    outside = src.replace(body, "").replace(roll, "")
    assert "send_message(" not in outside and "followup.send(" not in outside and ".send(" not in outside
    defers = re.findall(r"defer\((.*?)\)", src)
    assert defers and all("ephemeral=True" in d for d in defers)  # only private "thinking…" placeholders
    assert ".channel.send(" not in src and "dm_channel" not in src and "create_dm" not in src


def test_reply_follow_up_branch_is_ephemeral():
    async def scenario():
        i = Fake(User(PLAYER))
        i.response.done = True  # something already answered this interaction
        await bot.reply(i, "late")
        assert i.last == ("followup", "late", {"ephemeral": True})
        i2 = Fake(User(PLAYER))
        await bot.reply(i2, "first")
        assert i2.last == ("send_message", "first", {"ephemeral": True})
    run(scenario())


def test_context_menu_is_a_user_command_and_commands_are_guild_only():
    menu = bot.tree.get_command("View Character", type=discord.AppCommandType.user)
    assert menu is not None and menu.type is discord.AppCommandType.user and menu.guild_only
    assert bot.tree.get_command("character").guild_only and bot.tree.get_command("setup").guild_only
    assert bot.tree.get_command("setup").default_permissions.administrator
    assert {c.name for c in bot.tree.get_command("character").commands} == {"view", "edit", "create", "delete", "export", "import", "roll"}
    assert not bot.intents.members and not bot.intents.message_content


def test_view_character_reply_is_ephemeral_and_shows_name_owner_section(card_user_store):
    async def scenario():
        i = Fake(User(PLAYER))
        await bot.view_character.callback(i, User(OWNER))
        kind, _, kw = i.last
        assert kind == "send_message" and kw["ephemeral"] is True
        e = kw["embed"]
        assert e.title == "Vex Harrow" and f"<@{OWNER}>" in e.description and "Characteristics" in e.description
        assert e.footer.text.startswith("Characteristics")
        assert labels(kw["view"])[:4] == ["Characteristics", "Skills", "Talents", "Equipment"]
        assert "Edit" not in labels(kw["view"])  # PLAYER may not edit OWNER
    run(scenario())


def test_missing_character_is_explained(store):
    async def scenario():
        card, i = await open_card(User(PLAYER), owner_id=OWNER)
        assert i.embed.title == "No character" and f"<@{OWNER}> has no character" in i.embed.description
        assert "Create character" not in labels(card)
        card2, i2 = await open_card(User(OWNER), owner_id=OWNER)
        assert "Create character" in labels(card2)
    run(scenario())


# -- navigation ---------------------------------------------------------------------------

def test_sections_and_pages_render_the_right_character(card_user_store):
    card_user_store.save(actor(PLAYER), PLAYER, {"name": "Decoy", "skills": [{"name": "Stealth", "rating": 99}]})
    async def scenario():
        card, i = await open_card(User(PLAYER), owner_id=OWNER)
        for section, needle in [("Skills", "Adeptus Administratum — 63"), ("Talents", "Bureaucratic Insight"),
                                ("Equipment", "Laspistol"), ("Characteristics", "**BS** Ballistic Skill: 42")]:
            i2 = await click(card, section, User(PLAYER))
            assert i2.last[0] == "edit_message" and i2.embed.title == "Vex Harrow"
            assert needle in i2.embed.description and i2.embed.footer.text.startswith(section)
            assert "Decoy" not in i2.embed.description and "Stealth" not in i2.embed.description
        eq = (await click(card, "Equipment", User(PLAYER))).embed.description
        order = ["Weapons", "Laspistol", "Armour", "Flak Coat", "Other Equipment", "Ration packs** ×6"]
        assert [eq.index(x) for x in order] == sorted(eq.index(x) for x in order)
    run(scenario())


def test_pagination_buttons(card_user_store):
    card_user_store.save(actor(OWNER), OWNER, {"talents": [{"name": f"Talent {i:02d}", "notes": "x" * 900} for i in range(12)]})
    async def scenario():
        card, i = await open_card(User(PLAYER), owner_id=OWNER)
        i1 = await click(card, "Talents", User(PLAYER))
        n = len(card.pages)
        assert n >= 3 and i1.embed.footer.text == f"Talents · Page 1/{n}"
        assert button(card, "◀ Previous").disabled and not button(card, "Next ▶").disabled
        seen = set(re.findall(r"Talent \d\d", i1.embed.description))
        i2 = await click(card, "Next ▶", User(PLAYER))
        assert i2.embed.footer.text == f"Talents · Page 2/{n}" and "Talent 00" not in i2.embed.description
        for _ in range(n):
            seen |= set(re.findall(r"Talent \d\d", card.embed().description))
            if not button(card, "Next ▶").disabled:
                await click(card, "Next ▶", User(PLAYER))
        assert seen == {f"Talent {i:02d}" for i in range(12)}
        assert button(card, "Next ▶").disabled
        await click(card, "◀ Previous", User(PLAYER))
        assert card.page == n - 2
    run(scenario())


def test_card_is_bound_to_viewer_and_guild(card_user_store):
    async def scenario():
        card, _ = await open_card(User(PLAYER), owner_id=OWNER)
        other = Fake(User(GM), message=object())
        assert not await card.interaction_check(other)
        assert other.last[0] == "send_message" and other.last[2]["ephemeral"] is True
        wrong_guild = Fake(User(PLAYER), guild_id=OTHER_GUILD, message=object())
        assert not await card.interaction_check(wrong_guild)
        assert await card.interaction_check(Fake(User(PLAYER), message=object()))
    run(scenario())


def test_discord_limits_respected_with_huge_sheet(card_user_store):
    big = {k: [{"name": f"{k} {i}"} for i in range(model.MAX_ENTRIES)] for k in model.LIST_KEYS}
    card_user_store.save(actor(OWNER), OWNER, big)
    async def scenario():
        card, i = await open_card(User(OWNER), owner_id=OWNER, editing=True)
        for section in ("Skills", "Talents", "Equipment"):
            await click(card, section, User(OWNER))
            while True:
                e = card.embed()
                assert len(e) <= 6000 and len(e.description) <= 4096
                rows = {it.row for it in card.children}
                assert len(rows) <= 5 and len(card.children) <= 25
                for it in card.children:
                    if isinstance(it, discord.ui.Select):
                        assert 1 <= len(it.options) <= 25
                        assert all(len(o.label) <= 100 and len(o.value) <= 100 for o in it.options)
                    else:
                        assert len(it.label) <= 80
                    assert len(it.custom_id) <= 100
                if button(card, "Next ▶").disabled:
                    break
                await click(card, "Next ▶", User(OWNER))
    run(scenario())


# -- editing & permissions ----------------------------------------------------------------

def test_owner_edits_skill_via_form(card_user_store):
    async def scenario():
        card, _ = await open_card(User(OWNER), owner_id=OWNER)
        await click(card, "Skills", User(OWNER))
        i = await click(card, "Edit", User(OWNER))
        assert "Editing" in i.embed.footer.text and "Add skill" in labels(card)
        i2 = await click(card, "Add skill", User(OWNER))
        modal = i2.last[1]
        assert i2.last[0] == "send_modal" and isinstance(modal, bot.Form) and len(modal.children) <= 5
        i3 = await submit(modal, {"name": "Stealth", "rating": "41", "specialisations": "Urban 46", "notes": "Sneaky"}, User(OWNER))
        assert i3.last[0] == "edit_message" and "Saved" in i3.embed.description and "**Stealth** — 41" in i3.embed.description
        assert "↳ Urban — 46" in i3.embed.description
        char, version = card_user_store.load(GUILD, OWNER)
        assert version == 2 and char["skills"][-1]["name"] == "Stealth"
        # edit the entry we just added through the select menu
        i4 = await choose(card, "Edit an entry…", "skills:2", User(OWNER))
        modal2 = i4.last[1]
        assert modal2.inputs["name"].default == "Stealth" and modal2.inputs["specialisations"].default == "Urban 46"
        i5 = await submit(modal2, {"name": "Stealth", "rating": "45", "specialisations": "", "notes": ""}, User(OWNER))
        assert card_user_store.load(GUILD, OWNER)[0]["skills"][2] == {"name": "Stealth", "rating": 45, "specialisations": [], "notes": ""}
        assert "Saved" in i5.embed.description
    run(scenario())


def test_identity_and_characteristics_forms(card_user_store):
    async def scenario():
        card, _ = await open_card(User(OWNER), owner_id=OWNER, editing=True)
        i = await click(card, "Edit Int–Fel", User(OWNER))
        modal = i.last[1]
        assert [lbl.text for lbl in modal.children] == ["Intelligence (Int)", "Perception (Per)", "Willpower (Wil)", "Fellowship (Fel)"]
        assert modal.inputs["Int"].default == "48"
        i2 = await submit(modal, {"Int": "50", "Per": "", "Wil": "33", "Fel": "31"}, User(OWNER))
        c = card_user_store.load(GUILD, OWNER)[0]["characteristics"]
        assert c["Int"] == 50 and c["Per"] is None and c["WS"] == 30
        assert "**Int** Intelligence: 50" in i2.embed.description
        i3 = await click(card, "Name & description", User(OWNER))
        i4 = await submit(i3.last[1], {"name": "Vex Harrow II", "description": ""}, User(OWNER))
        assert i4.embed.title == "Vex Harrow II" and card_user_store.load(GUILD, OWNER)[0]["description"] == ""
    run(scenario())


def test_validation_failure_keeps_saved_data(card_user_store):
    async def scenario():
        card, _ = await open_card(User(OWNER), owner_id=OWNER, editing=True)
        await click(card, "Skills", User(OWNER))
        i = await choose(card, "Edit an entry…", "skills:0", User(OWNER))
        i2 = await submit(i.last[1], {"name": "Lore", "rating": "fifty", "specialisations": "", "notes": ""}, User(OWNER))
        assert "Not saved" in i2.embed.description and "whole number" in i2.embed.description
        char, version = card_user_store.load(GUILD, OWNER)
        assert version == 1 and char["skills"][0]["rating"] == 58 and char["skills"][0]["specialisations"]
        await click(card, "Characteristics", User(OWNER))
        i3 = await click(card, "Edit WS–Ag", User(OWNER))
        i4 = await submit(i3.last[1], {"WS": "30", "BS": "999", "Str": "28", "Tgh": "35", "Ag": "40"}, User(OWNER))
        assert "Not saved" in i4.embed.description and card_user_store.load(GUILD, OWNER)[1] == 1
    run(scenario())


def test_player_cannot_edit_others_even_when_calling_handlers_directly(card_user_store):
    async def scenario():
        card, _ = await open_card(User(PLAYER), owner_id=OWNER, editing=True)
        assert not card.editing and "Edit" not in labels(card) and "Add skill" not in labels(card)
        # Tampered client: invoke the edit handlers anyway.
        i = Fake(User(PLAYER), message=object())
        await card.open_entry("skills", None, i)
        assert i.last[0] == "edit_message" and "permission" in i.embed.description
        i2 = Fake(User(PLAYER), message=object())
        await card.save_patch(i2, {"name": "Pwned"}, card.version)
        assert "permission" in i2.embed.description and card_user_store.load(GUILD, OWNER)[0]["name"] == "Vex Harrow"
        i3 = Fake(User(PLAYER), message=object())
        await card.open_characteristics(0, i3)
        assert i3.last[0] != "send_modal"
    run(scenario())


def test_gm_and_admin_can_edit_within_their_server(card_user_store):
    async def scenario():
        card, i = await open_card(User(GM, roles=[GM_ROLE]), owner_id=OWNER)
        assert "Edit" in labels(card)
        await click(card, "Edit", User(GM, roles=[GM_ROLE]))
        i2 = await click(card, "Name & description", User(GM, roles=[GM_ROLE]))
        await submit(i2.last[1], {"name": "Vex (GM edit)", "description": "d"}, User(GM, roles=[GM_ROLE]))
        assert card_user_store.load(GUILD, OWNER)[0]["name"] == "Vex (GM edit)"
        card2, _ = await open_card(User(ADMIN), owner_id=OWNER, admin=True, editing=True)
        i3 = await click(card2, "Name & description", User(ADMIN), admin=True)
        await submit(i3.last[1], {"name": "Vex (admin edit)", "description": "d"}, User(ADMIN), admin=True)
        assert card_user_store.load(GUILD, OWNER)[0]["name"] == "Vex (admin edit)"
        # Same GM role id in another server grants nothing there.
        card_user_store.save(actor(OWNER, guild_id=OTHER_GUILD), OWNER, {"name": "Elsewhere"})
        card3, _ = await open_card(User(GM, roles=[GM_ROLE]), owner_id=OWNER, guild_id=OTHER_GUILD, editing=True)
        assert "Edit" not in labels(card3)
    run(scenario())


def test_lost_gm_role_while_form_open(card_user_store):
    async def scenario():
        gm = User(GM, roles=[GM_ROLE])
        card, _ = await open_card(gm, owner_id=OWNER, editing=True)
        i = await click(card, "Name & description", gm)
        modal = i.last[1]
        demoted = User(GM, roles=[])  # role removed while the form is open
        i2 = await submit(modal, {"name": "Sneaky", "description": ""}, demoted)
        assert "no longer have permission" in i2.embed.description
        assert card_user_store.load(GUILD, OWNER)[0]["name"] == "Vex Harrow"
        assert not card.editing and "Edit" not in labels(card) and "Name & description" not in labels(card)
    run(scenario())


def test_stale_form_cannot_overwrite_newer_edit(card_user_store):
    async def scenario():
        card, _ = await open_card(User(OWNER), owner_id=OWNER, editing=True)
        await click(card, "Talents", User(OWNER))
        i = await choose(card, "Edit an entry…", "talents:0", User(OWNER))
        modal = i.last[1]
        # Meanwhile the GM saves a newer version.
        card_user_store.save(actor(GM, roles=[GM_ROLE]), OWNER, {"talents": [{"name": "GM Talent"}]})
        i2 = await submit(modal, {"name": "Old Talent", "notes": "stale"}, User(OWNER))
        assert "changed by someone else" in i2.embed.description
        char, version = card_user_store.load(GUILD, OWNER)
        assert version == 2 and char["talents"] == [{"name": "GM Talent", "notes": ""}]
        assert "GM Talent" in i2.embed.description  # card refreshed to the latest version
    run(scenario())


def test_stale_identity_form_after_navigating_the_card(card_user_store):
    """The viewer opens a form, keeps clicking around the card (which refreshes it), someone else
    saves meanwhile: the old form must still be refused."""
    async def scenario():
        card, _ = await open_card(User(OWNER), owner_id=OWNER, editing=True)
        i = await click(card, "Name & description", User(OWNER))
        modal = i.last[1]
        card_user_store.save(actor(GM, roles=[GM_ROLE]), OWNER, {"name": "Renamed by GM"})
        await click(card, "Skills", User(OWNER))  # card refreshes to version 2
        assert card.version == 2
        i2 = await submit(modal, {"name": "Old name", "description": "old"}, User(OWNER))
        assert "changed by someone else" in i2.embed.description
        assert card_user_store.load(GUILD, OWNER)[0]["name"] == "Renamed by GM"
    run(scenario())


def test_remove_requires_confirmation(card_user_store):
    async def scenario():
        card, _ = await open_card(User(OWNER), owner_id=OWNER, editing=True)
        await click(card, "Equipment", User(OWNER))
        await choose(card, "Remove an entry…", "equipment:1", User(OWNER))
        assert labels(card) == ["Remove Ration packs ×6", "Cancel"]
        assert len(card_user_store.load(GUILD, OWNER)[0]["equipment"]) == 2
        await click(card, "Cancel", User(OWNER))
        assert len(card_user_store.load(GUILD, OWNER)[0]["equipment"]) == 2 and "Skills" in labels(card)
        await choose(card, "Remove an entry…", "equipment:1", User(OWNER))
        i2 = await click(card, "Remove Ration packs ×6", User(OWNER))
        assert "Removed" in i2.embed.description
        assert [e["name"] for e in card_user_store.load(GUILD, OWNER)[0]["equipment"]] == ["Data-slate"]
        assert "Laspistol" in i2.embed.description  # weapons untouched
    run(scenario())


def test_tampered_select_values_are_rejected(card_user_store):
    async def scenario():
        card, _ = await open_card(User(OWNER), owner_id=OWNER, editing=True)
        await click(card, "Skills", User(OWNER))
        for placeholder in ("Edit an entry…", "Remove an entry…"):
            for bad in ("skills:99", "nope:0", "weapons:x", ""):
                i = await choose(card, placeholder, bad, User(OWNER))
                assert i.last[0] == "edit_message" and "no longer exists" in i.embed.description
                assert card.pending_remove is None
        assert card_user_store.load(GUILD, OWNER)[1] == 1
    run(scenario())


def test_custom_ids_are_stable_per_action(card_user_store):
    """A click from an older render must never land on a different action (e.g. the red Remove)."""
    async def scenario():
        card, _ = await open_card(User(OWNER), owner_id=OWNER, editing=True)
        ids_before = {item.label: item.custom_id for item in card.children if isinstance(item, discord.ui.Button)}
        await click(card, "Equipment", User(OWNER))
        await choose(card, "Remove an entry…", "equipment:0", User(OWNER))
        confirm_ids = {item.custom_id for item in card.children}
        await click(card, "Cancel", User(OWNER))
        ids_after = {item.label: item.custom_id for item in card.children if isinstance(item, discord.ui.Button)}
        for label in ("Characteristics", "Skills", "Talents", "Equipment", "◀ Previous", "Next ▶", "Done editing"):
            assert ids_before[label] == ids_after[label]
        assert confirm_ids.isdisjoint(ids_after.values())
        assert len({item.custom_id for item in card.children}) == len(card.children)
    run(scenario())


# -- slash commands ------------------------------------------------------------------------

def test_create_command_flow(store):
    async def scenario():
        i = Fake(User(OWNER))
        await bot.character_create.callback(i, None)
        assert i.last[0] == "send_modal"
        i2 = await submit(i.last[1], {"name": "Fresh", "description": "new"}, User(OWNER), from_message=False)
        assert i2.last[0] == "send_message" and i2.last[2]["ephemeral"] is True and i2.embed.title == "Fresh"
        assert store.load(GUILD, OWNER)[0]["name"] == "Fresh"
        i3 = Fake(User(OWNER))
        await bot.character_create.callback(i3, None)
        assert i3.last[0] == "send_message" and "already has a character" in i3.embed.description
        i4 = Fake(User(PLAYER))
        await bot.character_create.callback(i4, User(OWNER))
        assert i4.last[0] == "send_message" and "⛔" in i4.last[1] and i4.last[2]["ephemeral"] is True
    run(scenario())


def test_delete_command_flow(card_user_store):
    async def scenario():
        i = Fake(User(PLAYER))
        await bot.character_delete.callback(i, User(OWNER))
        assert "permission" in i.last[1] and i.last[2]["ephemeral"] is True
        i2 = Fake(User(OWNER))
        await bot.character_delete.callback(i2, None)
        view = i2.view
        assert i2.last[2]["ephemeral"] is True and labels(view) == ["Delete character", "Cancel"]
        assert not await view.interaction_check(Fake(User(PLAYER), message=object()))
        i3 = Fake(User(OWNER), message=object())
        await button(view, "Delete character").callback(i3)
        assert i3.last[0] == "edit_message" and "Deleted" in i3.last[1]
        assert card_user_store.load(GUILD, OWNER) is None
        assert view.token not in bot.LIVE_CARDS
    run(scenario())


def test_delete_confirmation_rechecks_permission_and_can_cancel(card_user_store):
    async def scenario():
        gm = User(GM, roles=[GM_ROLE])
        i = Fake(gm)
        await bot.character_delete.callback(i, User(OWNER))
        view = i.view
        demoted = Fake(User(GM, roles=[]), message=object())  # lost the GM role before confirming
        await button(view, "Delete character").callback(demoted)
        assert "permission" in demoted.last[1] and card_user_store.load(GUILD, OWNER) is not None
        i2 = Fake(gm)
        await bot.character_delete.callback(i2, User(OWNER))
        cancel = Fake(gm, message=object())
        await button(i2.view, "Cancel").callback(cancel)
        assert "Cancelled" in cancel.last[1] and card_user_store.load(GUILD, OWNER) is not None
        i3 = Fake(gm)
        await bot.character_delete.callback(i3, User(OWNER))
        await i3.view.on_timeout()
        assert all(item.disabled for item in i3.view.children) and "expired" in i3.last[1]
        assert i3.view.token not in bot.LIVE_CARDS
    run(scenario())


def test_setup_gm_role(store):
    async def scenario():
        role = type("Role", (), {"id": GM_ROLE})()
        i = Fake(User(PLAYER))
        await bot.setup_gm_role.callback(i, role, False)
        assert "administrators" in i.last[1] and store.gm_role(GUILD) is None
        i2 = Fake(User(ADMIN), admin=True)
        await bot.setup_gm_role.callback(i2, role, False)
        assert store.gm_role(GUILD) == GM_ROLE and i2.last[2]["ephemeral"] is True
        i3 = Fake(User(ADMIN), admin=True)
        await bot.setup_gm_role.callback(i3, None, False)
        assert str(GM_ROLE) in i3.last[1]
        i4 = Fake(User(ADMIN), admin=True)
        await bot.setup_gm_role.callback(i4, None, True)
        assert store.gm_role(GUILD) is None
    run(scenario())


# -- text export & import --------------------------------------------------------------------

class Attachment:
    """A duck-typed discord.Attachment."""

    def __init__(self, data: bytes, filename="vex.txt", content_type="text/plain; charset=utf-8"):
        self.data, self.filename, self.content_type, self.size = data, filename, content_type, len(data)

    async def read(self):
        return self.data


async def paste(text, user=None, owner=None):
    """Run /character import, fill the form with ``text`` and submit it; returns the submit interaction."""
    user = user or User(OWNER)
    i = Fake(user)
    await bot.character_import.callback(i, owner, None)
    assert i.last[0] == "send_modal"
    return await submit(i.last[1], {"text": text}, user, from_message=False)


def test_export_command(card_user_store):
    async def scenario():
        i = Fake(User(PLAYER))  # anyone may export a character they can view
        await bot.character_export.callback(i, User(OWNER))
        kind, content, kw = i.last
        assert kind == "send_message" and kw["ephemeral"] is True and "file" not in kw
        assert "```\nName: Vex Harrow\n" in content and "Laspistol | 6 | Medium | 15 | Reliable" in content
        assert f"with **member** set to <@{OWNER}>" in content  # so nobody imports it over their own character
        i2 = Fake(User(PLAYER))
        await bot.character_export.callback(i2, None)  # PLAYER has no character: blank template
        assert "has no character yet" in i2.last[1] and "Name: \n" in i2.last[1]
        for talents, over_box in ((6, False), (15, True)):  # too long for a message, then too long for the paste box
            card_user_store.save(actor(OWNER), OWNER, {"talents": [{"name": f"Talent {n}", "notes": "x" * 300} for n in range(talents)]})
            i3 = Fake(User(OWNER))
            await bot.character_export.callback(i3, None)
            content, kw = i3.last[1], i3.last[2]
            assert kw["file"].filename == "Vex_Harrow.txt" and "as a file" in content
            assert ("over the 4000 characters" in content) is over_box
            text = kw["file"].fp.read().decode("utf-8")
            assert len(textsheet.parse_text(text)[0]["talents"]) == talents
    run(scenario())


def test_import_by_pasting_previews_then_saves(card_user_store):
    async def scenario():
        i = Fake(User(OWNER))
        await bot.character_import.callback(i, None, None)
        modal = i.last[1]
        assert modal.inputs["text"].max_length == bot.PASTE_MAX and "Up to 4000 characters" in modal.children[0].description
        text = textsheet.format_text(card_user_store.load(GUILD, OWNER)[0]).replace("BS 42", "BS 45")
        text = text.replace("(Talent | Effect)\n", "(Talent | Effect)\nSharpshooter | Ignore range penalties.\n")
        i2 = await submit(modal, {"text": text}, User(OWNER), from_message=False)
        kind, header, kw = i2.last
        preview = kw["view"]
        assert kind == "send_message" and kw["ephemeral"] is True and isinstance(preview, bot.Preview)
        assert "nothing is saved yet" in header and "talents (2, was 1)" in header and "Skipped" not in header
        assert "**BS** Ballistic Skill: 45" in kw["embed"].description and "Edit" not in labels(preview)
        assert card_user_store.load(GUILD, OWNER)[1] == 1  # nothing stored yet
        i3 = await click(preview, "Talents", User(OWNER))
        assert i3.last[1] == header and "Sharpshooter" in i3.embed.description  # the summary stays while browsing
        assert all(len(row["components"]) <= 5 for row in preview.to_components())
        i4 = await click(preview, "Save", User(OWNER))
        char, version = card_user_store.load(GUILD, OWNER)
        assert version == 2 and char["characteristics"]["BS"] == 45 and char["talents"][0]["name"] == "Sharpshooter"
        assert i4.last[0] == "edit_message" and i4.last[1] is None and "Imported" in i4.embed.description
        assert type(i4.view) is bot.Card and "Edit" in labels(i4.view)  # now the real, live card
        assert preview.token not in bot.LIVE_CARDS and i4.view.token in bot.LIVE_CARDS
    run(scenario())


def test_import_summarises_skips_bad_lines_and_can_be_cancelled(card_user_store):
    async def scenario():
        i = await paste("SKILLS\nStealth 40\nRanged 152\nTALENTS")
        header, preview = i.last[1], i.view
        assert "Skipped 1 line(s)" in header and "• Line 3 `Ranged 152`: Total must be between 0 and 100." in header
        assert "From your text: skills (1, was 2), talents (0, was 1)." in header
        assert "kept as they are: name, description, characteristics, weapons, armour, other equipment." in header
        i2 = await click(preview, "Cancel", User(OWNER))
        assert i2.last[0] == "edit_message" and "Nothing was changed" in i2.last[1] and i2.last[2]["view"] is None
        assert card_user_store.load(GUILD, OWNER)[1] == 1 and preview.token not in bot.LIVE_CARDS
        i3 = await paste("TALENTS\n" + "\n".join(f"{n} | " + "x" * 2000 for n in range(50)))  # 50 unreadable lines
        assert len(i3.last[1]) <= 2000 and "…and 42 more." in i3.last[1]
        await i3.view.on_timeout()
        assert i3.last[0] == "edit_original" and "nothing was imported" in i3.last[1]
        assert all(item.disabled for item in i3.view.children)
    run(scenario())


def test_import_permissions_and_stale_preview(card_user_store):
    async def scenario():
        i = Fake(User(PLAYER))
        await bot.character_import.callback(i, User(OWNER), None)
        assert i.last[0] == "send_message" and "⛔" in i.last[1]  # no form for someone who may not edit
        i2 = Fake(User(PLAYER))
        await bot.character_import.callback(i2, User(OWNER), Attachment(b"Name: Taken"))
        assert "⛔" in i2.last[1] and i2.log[0][0] == "send_message"  # refused before downloading anything
        gm = User(GM, roles=[GM_ROLE])
        i3 = await paste("Name: Renamed by import", gm, User(OWNER))
        card_user_store.save(actor(OWNER), OWNER, {"description": "edited meanwhile"})
        i4 = await click(i3.view, "Save", gm)
        assert "changed by someone else" in i4.last[1] and card_user_store.load(GUILD, OWNER)[0]["name"] == "Vex Harrow"
        i5 = await paste("Name: Renamed by import", gm, User(OWNER))
        i6 = await click(i5.view, "Save", User(GM, roles=[]))  # lost the GM role before pressing Save
        assert "no longer have permission" in i6.last[1] and card_user_store.load(GUILD, OWNER)[0]["name"] == "Vex Harrow"
    run(scenario())


def test_import_from_a_txt_file(store):
    async def scenario():
        text = "Name: Ysolde\r\nTALENTS\r\nField Medic | Heal without a medikit — at a penalty."
        i = Fake(User(OWNER))
        await bot.character_import.callback(i, None, Attachment(text.encode("utf-8-sig")))
        assert i.log[0][0] == "defer" and i.last[0] == "followup" and isinstance(i.view, bot.Preview)
        assert "cut off" not in i.last[1]
        await click(i.view, "Save", User(OWNER))
        assert store.load(GUILD, OWNER)[0]["talents"][0]["notes"] == "Heal without a medikit — at a penalty."
        i2 = Fake(User(OWNER))
        await bot.character_import.callback(i2, None, Attachment("Name: Zoë".encode("cp1252")))  # old Notepad files
        assert i2.view.char["name"] == "Zoë"
        i3 = Fake(User(OWNER))
        await bot.character_import.callback(i3, None, Attachment(b"%PDF-1.7", "sheet.pdf", "application/pdf"))
        assert i3.log[0][0] == "send_message" and ".txt" in i3.last[1]
        i4 = Fake(User(OWNER))
        await bot.character_import.callback(i4, None, Attachment(b"x" * (bot.IMPORT_MAX_BYTES + 1)))
        assert i4.log[0][0] == "send_message" and "too big" in i4.last[1]
    run(scenario())


def test_a_full_paste_box_is_flagged(card_user_store):
    async def scenario():
        start = "TALENTS\nSharpshooter | Ignore range penalties 🙂"  # Discord counts the emoji as two characters
        for size, flagged in ((bot.PASTE_MAX, True), (bot.PASTE_MAX - 1, False)):
            i = await paste(start + "\n" * (size - bot.discord_len(start)))
            assert ("may be cut off" in i.last[1]) is flagged and isinstance(i.view, bot.Preview)
    run(scenario())


def test_import_explains_text_it_cannot_use(store):
    async def scenario():
        for text, expected in (("hello there", "no `Name:` line"), ("TALENTS\nSharpshooter", "needs a name"),
                               ("Name: " + "x" * 81, "too long")):
            i = await paste(text)
            assert i.last[0] == "send_message" and expected in i.last[1] and i.view is None
        assert store.load(GUILD, OWNER) is None
    run(scenario())


# -- rolls ----------------------------------------------------------------------------------

async def roll(skill, notes=None, user=OWNER):
    """Run /character roll as ``user``; returns the interaction."""
    i = Fake(User(user))
    i.response.public_ok = True
    await bot.character_roll.callback(i, skill, notes)
    return i


def test_roll_offers_and_uses_the_stored_ratings(card_user_store, monkeypatch):
    monkeypatch.setattr(bot.rolls.random, "randint", lambda a, b: 42)
    async def scenario():
        choices = await bot.roll_choices(Fake(User(OWNER)), " LORE")
        assert [(c.name, c.value) for c in choices] == [
            ("Lore — 58", "Lore"), ("Lore (Adeptus Administratum) — 63", "Lore (Adeptus Administratum)")]
        assert len(await bot.roll_choices(Fake(User(OWNER)), "")) == 12  # 9 characteristics, 2 skills, 1 specialisation
        assert await bot.roll_choices(Fake(User(PLAYER)), "") == []  # no character, nothing to offer
        for typed, target, outcome in (("Lore", 58, "**Success** (+1 SL) on **Lore**!"),
                                       ("lore (adeptus administratum)", 63, "**Success** (+2 SL) on **Lore (Adeptus Administratum)**!"),
                                       ("bs", 42, "**Marginal Success** (+0 SL) on **Ballistic Skill (BS)**!")):
            i = await roll(typed, "Reading the forms")
            kind, content, kw = i.last
            assert kind == "send_message" and "ephemeral" not in kw  # posted in the channel for the table
            assert content == f"**Test:** Reading the forms\n\n**Vex Harrow** rolled: **42** with a target of **{target}**\n{outcome}"
        assert "Test:" not in (await roll("Awareness")).last[1]  # notes are optional
    run(scenario())


def test_roll_refuses_privately_what_it_cannot_roll(card_user_store):
    card_user_store.save(actor(OWNER), OWNER, {"characteristics": {"Per": None}})
    async def scenario():
        for typed in ("Stealth", "l", "Perception (Per)", "  "):  # unknown, ambiguous, unrated, blank
            i = await roll(typed)
            assert i.last[0] == "send_message" and i.last[2].get("ephemeral") is True and "Nothing was rolled" in i.last[1]
        i2 = await roll("Lore", user=PLAYER)
        assert i2.last[2].get("ephemeral") is True and "no character" in i2.last[1]
    run(scenario())


# -- expiry ---------------------------------------------------------------------------------

def test_timeout_disables_controls_and_explains(card_user_store):
    async def scenario():
        card, i = await open_card(User(PLAYER), owner_id=OWNER)
        assert card.timeout == bot.CARD_TIMEOUT and 0 < bot.CARD_TIMEOUT < 15 * 60
        await card.on_timeout()
        assert all(item.disabled for item in card.children)
        assert i.last[0] == "edit_original" and "expired" in i.last[1] and "View Character" in i.last[1]
        assert card.token not in bot.LIVE_CARDS
        # a form submitted after the card expired still saves, but the redrawn card has no live buttons
        card.stop()
        i2 = Fake(User(OWNER), message=object())
        await card.show(i2)
        assert all(item.disabled for item in card.children) and card.token not in bot.LIVE_CARDS
    run(scenario())


def test_dead_card_buttons_get_a_private_explanation(card_user_store):
    async def scenario():
        card, _ = await open_card(User(PLAYER), owner_id=OWNER)
        live = Fake(User(PLAYER), message=object(), custom_id=card.children[0].custom_id)
        await bot.on_interaction(live)
        assert live.log == []  # the live view handles it
        dead = Fake(User(PLAYER), message=object(), custom_id="imc:deadbeef:1")
        await bot.on_interaction(dead)
        assert dead.last[0] == "send_message" and "expired" in dead.last[1] and dead.last[2]["ephemeral"] is True
        dead_save = Fake(User(PLAYER), message=object(), custom_id="imc:deadbeef:save")  # an import preview from before a restart
        await bot.on_interaction(dead_save)
        assert "nothing was imported" in dead_save.last[1]
        unrelated = Fake(User(PLAYER), message=object(), custom_id="someone-elses-button")
        await bot.on_interaction(unrelated)
        assert unrelated.log == []
    run(scenario())


def test_error_handlers_reply_privately(card_user_store):
    async def scenario():
        i = Fake(User(PLAYER))
        await bot.on_app_command_error(i, discord.app_commands.CheckFailure())
        assert i.last[0] == "send_message" and i.last[2]["ephemeral"] is True
        i2 = Fake(User(PLAYER))
        await bot.on_app_command_error(i2, discord.app_commands.CommandInvokeError(bot.view_character, RuntimeError("boom")))
        assert i2.last[1] == bot.GENERIC_ERROR and i2.last[2]["ephemeral"] is True
        card, _ = await open_card(User(PLAYER), owner_id=OWNER)
        i3 = Fake(User(PLAYER), message=object())
        await card.on_error(i3, RuntimeError("boom"), card.children[0])
        assert i3.last[2]["ephemeral"] is True
    run(scenario())

