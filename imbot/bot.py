"""Discord layer: the "View Character" user command, /character and /setup commands, cards, forms.

Every message leaves through :func:`reply` (always ephemeral) or edits an existing
ephemeral card, so nothing is ever sent as a DM and the only channel post is the
result of ``/character roll``, which the table needs to see.
"""
from __future__ import annotations

import io
import logging
import os
import re
import secrets
import sys
from functools import partial
from pathlib import Path

import discord
from discord import app_commands

from . import model, render, rolls, textsheet
from .store import Actor, PermissionDenied, StaleEdit, Store

log = logging.getLogger("imbot")

CARD_TIMEOUT = 10 * 60  # seconds of inactivity; Discord interaction tokens last 15 minutes
FORM_TIMEOUT = 30 * 60  # an abandoned form is forgotten after this; a later submit gets the generic Discord failure
REOPEN_HINT = "Reopen it with **Apps → View Character** on a member, or `/character view`."
GENERIC_ERROR = "Something went wrong on our side. Nothing was changed. Please try again."
NOT_IN_GUILD = "This bot only works inside a server."
PASTE_MAX = 4000              # Discord's limit for one text box in a form
MESSAGE_MAX = 2000            # Discord's limit for a message's text
IMPORT_MAX_BYTES = 200_000    # a real character is a few KB; keeps a huge upload out of memory
IMPORT_FIELD = model.Field("text", "Character text", PASTE_MAX, "long", required=True,
                           hint=f"Up to {PASTE_MAX} characters. Longer? Run /character import and attach a .txt file.")

LIVE_CARDS: set[str] = set()   # tokens of cards whose buttons still work (see on_interaction)
CLAIMED: set[int] = set()      # ids of clicks a live card answers, so on_interaction never answers them too
STORE: Store = None  # type: ignore[assignment]  # set by main() or by tests

intents = discord.Intents(guilds=True)  # role cache only; no privileged intents
client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())  # never ping anyone
tree = app_commands.CommandTree(client)


# -- helpers -----------------------------------------------------------------------

async def reply(interaction: discord.Interaction, content: str | None = None, **kwargs) -> None:
    """The single place that creates messages, apart from roll results. Always ephemeral, never a channel post or DM."""
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True, **kwargs)
    else:
        await interaction.response.send_message(content, ephemeral=True, **kwargs)


def discord_len(text: str) -> int:
    """Length as Discord clients count it (UTF-16 code units: an emoji counts twice)."""
    return len(text.encode("utf-16-le")) // 2


def actor_from(interaction: discord.Interaction) -> Actor:
    """Resolve who is acting *right now* from the interaction (never from stored or submitted data)."""
    user = interaction.user  # Member.roles needs the guild role cache (guilds intent); before it is filled this fails closed
    return Actor(
        guild_id=interaction.guild_id,
        user_id=user.id,
        role_ids=frozenset(r.id for r in getattr(user, "roles", [])),
        is_admin=interaction.permissions.administrator,
    )


class Btn(discord.ui.Button):
    def __init__(self, handler, **kwargs):
        super().__init__(**kwargs)
        self.handler = handler

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.handler(interaction)


class Sel(discord.ui.Select):
    def __init__(self, handler, **kwargs):
        super().__init__(**kwargs)
        self.handler = handler

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.handler(interaction, self.values[0])


class Form(discord.ui.Modal):
    """A modal built from model.Field specs. Returns raw strings to ``on_done``; validation
    happens in the card so errors become a notice on the card."""

    def __init__(self, title: str, fields: list[model.Field], values: dict, on_done):
        super().__init__(title=title[:45], timeout=FORM_TIMEOUT)
        self.fields, self.on_done, self.inputs = fields, on_done, {}
        for f in fields:
            ti = discord.ui.TextInput(
                style=discord.TextStyle.paragraph if f.kind in ("long", "specs") else discord.TextStyle.short,
                default=model.format_field(f, values.get(f.key)) or None,
                required=f.required,
                max_length=f.max_length,
            )
            self.inputs[f.key] = ti
            self.add_item(discord.ui.Label(text=f.label[:45], description=f.hint[:100] or None, component=ti))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.on_done(interaction, {k: ti.value for k, ti in self.inputs.items()})

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("form error", exc_info=error)
        await reply(interaction, GENERIC_ERROR)


# -- the character card ------------------------------------------------------------------

class Card(discord.ui.View):
    """One private, interactive character card bound to the member who opened it."""

    expired = f"⌛ This card expired after {CARD_TIMEOUT // 60} minutes without activity. {REOPEN_HINT}"

    def __init__(self, viewer_id: int, guild_id: int, owner_id: int, section: str = "characteristics", editing: bool = False):
        super().__init__(timeout=CARD_TIMEOUT)
        self.token = secrets.token_hex(4)
        self.viewer_id, self.guild_id, self.owner_id = viewer_id, guild_id, owner_id
        self.section, self.page, self.editing = section, 0, editing
        self.notice = ""
        self.header: str | None = None  # message text above the card, kept while navigating (import previews)
        self.pending_remove: tuple[str, int, str] | None = None
        self.last_interaction: discord.Interaction | None = None
        self.char: dict | None = None
        self.version = 0
        self.pages: list[render.Page] = []
        self.editable = False

    # -- lifecycle ------------------------------------------------------------------------
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        CLAIMED.add(interaction.id)  # answered below either way
        if interaction.user.id == self.viewer_id and interaction.guild_id == self.guild_id:
            return True
        await reply(interaction, f"This card was opened by someone else. {REOPEN_HINT}")
        return False

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        log.exception("card error guild=%s viewer=%s", self.guild_id, self.viewer_id, exc_info=error)
        try:
            await reply(interaction, GENERIC_ERROR)
        except discord.HTTPException:
            pass

    def stop(self) -> None:
        LIVE_CARDS.discard(self.token)
        super().stop()

    async def on_timeout(self) -> None:
        LIVE_CARDS.discard(self.token)
        for item in self.children:
            item.disabled = True
        if self.last_interaction is not None and not self.last_interaction.is_expired():
            try:
                await self.last_interaction.edit_original_response(content=self.expired, view=self)
            except discord.HTTPException:
                pass  # token already gone; clicks then get the on_interaction "expired" reply

    # -- rendering ------------------------------------------------------------------------
    def refresh(self, actor: Actor) -> None:
        row = STORE.load(self.guild_id, self.owner_id)
        self.char, self.version = row if row else (None, 0)
        self.editable = STORE.can_edit(actor, self.owner_id)
        if not self.editable:
            self.editing = False
            self.pending_remove = None
        self.pages = render.pages(self.char, self.section) if self.char else []
        self.page = min(self.page, max(len(self.pages) - 1, 0))

    def embed(self) -> discord.Embed:
        owner = f"**Owner:** <@{self.owner_id}>"
        notice = f"{self.notice}\n\n" if self.notice else ""
        if self.char is None:
            text = f"<@{self.owner_id}> has no character on this server yet."
            if self.editable:
                text += " Press **Create character** to make one."
            return discord.Embed(title="No character", description=f"{notice}{owner}\n\n{text}", colour=discord.Colour.dark_grey())
        page = self.pages[self.page]
        title = render.SECTION_TITLES[self.section]
        e = discord.Embed(title=self.char["name"], description=f"{notice}{owner}\n\n## {title}\n{page.text}",
                          colour=discord.Colour.dark_gold())
        footer = f"{title} · Page {self.page + 1}/{len(self.pages)}"
        e.set_footer(text=footer + (" · Editing" if self.editing else ""))
        return e

    def build(self) -> None:
        self.clear_items()

        def add(key: str, item):
            # Stable per-action ids: a click sent from an older render of this card can only
            # reach the action it was drawn for, never a different one that took its slot.
            item.custom_id = f"imc:{self.token}:{key}"
            item.disabled = item.disabled or self.is_finished()
            self.add_item(item)

        if self.pending_remove is not None:
            _, _, label = self.pending_remove
            add("remove", Btn(self.do_remove, label=f"Remove {label}"[:80], style=discord.ButtonStyle.danger, row=0))
            add("cancel", Btn(self.cancel_remove, label="Cancel", row=0))
            return
        for s in render.SECTIONS:
            style = discord.ButtonStyle.primary if s == self.section else discord.ButtonStyle.secondary
            add(f"sec:{s}", Btn(partial(self.go_section, s), label=render.SECTION_TITLES[s], style=style, row=0))
        if self.char is None:
            if self.editable:
                add("create", Btn(self.open_identity, label="Create character", style=discord.ButtonStyle.success, row=1))
            return
        last = len(self.pages) - 1
        add("prev", Btn(partial(self.go_page, -1), label="◀ Previous", row=1, disabled=self.page == 0))
        add("next", Btn(partial(self.go_page, +1), label="Next ▶", row=1, disabled=self.page >= last))
        if self.editable:
            label, style = ("Done editing", discord.ButtonStyle.secondary) if self.editing else ("Edit", discord.ButtonStyle.success)
            add("edit", Btn(self.toggle_edit, label=label, style=style, row=1))
        if not self.editing:
            return
        if self.section == "characteristics":
            add("identity", Btn(self.open_identity, label="Name & description", row=2))
            add("chars:0", Btn(partial(self.open_characteristics, 0), label="Edit WS–Ag", row=2))
            add("chars:1", Btn(partial(self.open_characteristics, 1), label="Edit Int–Fel", row=2))
            return
        for key in render.SECTION_LISTS[self.section]:
            add(f"add:{key}", Btn(partial(self.open_entry, key, None), label=f"Add {model.LIST_SPECS[key][0].lower()}", row=2))
        entries = self.pages[self.page].entries
        if entries:
            options = [discord.SelectOption(label=render.entry_label(k, self.char[k][i]), value=f"{k}:{i}") for k, i in entries]
            add("sel:edit", Sel(self.edit_selected, placeholder="Edit an entry…", options=options, row=3))
            add("sel:remove", Sel(self.remove_selected, placeholder="Remove an entry…", options=list(options), row=4))

    async def show(self, interaction: discord.Interaction) -> None:
        """Re-read the character and permissions, rebuild the card, and send or edit it. Always private."""
        self.refresh(actor_from(interaction))
        self.build()
        self.last_interaction = interaction
        if not self.is_finished():
            LIVE_CARDS.add(self.token)
        embed = self.embed()
        self.notice = ""
        if interaction.message is not None:  # button, select or form launched from this card
            await interaction.response.edit_message(content=self.header, embed=embed, view=self)
        else:  # slash command or context menu: a fresh private card
            await reply(interaction, self.header, embed=embed, view=self)

    # -- navigation ------------------------------------------------------------------------
    async def go_section(self, section: str, interaction: discord.Interaction) -> None:
        self.section, self.page = section, 0
        await self.show(interaction)

    async def go_page(self, delta: int, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page + delta)
        await self.show(interaction)

    async def toggle_edit(self, interaction: discord.Interaction) -> None:
        self.editing = not self.editing
        await self.show(interaction)

    # -- editing ---------------------------------------------------------------------------
    async def save_patch(self, interaction: discord.Interaction, patch: dict, version: int, success: str = "✅ Saved.") -> None:
        """Apply a patch via the store with full permission + staleness checks, then redraw.

        ``version`` is the character version the form was built from; the store refuses the
        write if anyone saved since, so a stale form can never overwrite a newer edit."""
        actor = actor_from(interaction)
        try:
            STORE.save(actor, self.owner_id, patch, expected_version=version)
            self.notice = success
            log.info("saved character guild=%s owner=%s by=%s keys=%s", self.guild_id, self.owner_id, actor.user_id, sorted(patch))
        except PermissionDenied:
            self.notice = "⛔ You no longer have permission to edit this character. Nothing was saved."
        except StaleEdit:
            self.notice = ("⚠️ This character was changed by someone else while your form was open. "
                           "Nothing was saved; the card now shows the latest version. Please redo your change.")
        except model.ValidationError as e:
            self.notice = f"⚠️ Not saved: {e}"
        self.pending_remove = None
        await self.show(interaction)

    async def _guard_edit(self, interaction: discord.Interaction) -> bool:
        """Re-check permission right before opening a form; the button may be stale."""
        if STORE.can_edit(actor_from(interaction), self.owner_id):
            return True
        self.notice = "⛔ You don't have permission to edit this character."
        await self.show(interaction)
        return False

    async def open_identity(self, interaction: discord.Interaction) -> None:
        if not await self._guard_edit(interaction):
            return
        values, version, creating = self.char or {}, self.version, self.char is None

        async def done(i: discord.Interaction, raw: dict) -> None:
            await self.save_patch(i, {f.key: raw[f.key] for f in model.IDENTITY}, version,
                                  "✅ Character created." if creating else "✅ Saved.")

        title = "Create character" if self.char is None else f"{values['name']} – identity"
        await interaction.response.send_modal(Form(title, model.IDENTITY, values, done))

    async def open_characteristics(self, half: int, interaction: discord.Interaction) -> None:
        if not await self._guard_edit(interaction):
            return
        chars = model.CHARACTERISTICS[:5] if half == 0 else model.CHARACTERISTICS[5:]
        fields = [model.Field(abbr, f"{full} ({abbr})", 3, "int") for abbr, full in chars]
        values, version = self.char["characteristics"], self.version

        async def done(i: discord.Interaction, raw: dict) -> None:
            await self.save_patch(i, {"characteristics": raw}, version)

        await interaction.response.send_modal(Form(f"{self.char['name']} – characteristics", fields, values, done))

    async def open_entry(self, key: str, index: int | None, interaction: discord.Interaction) -> None:
        if not await self._guard_edit(interaction):
            return
        singular, fields = model.LIST_SPECS[key]
        current = self.char[key]
        values = current[index] if index is not None and index < len(current) else {}
        version = self.version

        async def done(i: discord.Interaction, raw: dict) -> None:
            try:
                entry = {f.key: model.parse_field(f, raw.get(f.key)) for f in fields}
            except model.ValidationError as e:
                self.notice = f"⚠️ Not saved: {e}"
                await self.show(i)
                return
            items = list(current)
            if index is None:
                items.append(entry)
            else:
                items[index] = entry
            await self.save_patch(i, {key: items}, version)

        title = f"{'Add' if index is None else 'Edit'} {singular.lower()}"
        await interaction.response.send_modal(Form(title, fields, values, done))

    def _parse_ref(self, value: str) -> tuple[str, int] | None:
        key, _, idx = value.partition(":")
        if key in model.LIST_KEYS and idx.isdigit() and int(idx) < len(self.char[key]):
            return key, int(idx)
        return None

    async def edit_selected(self, interaction: discord.Interaction, value: str) -> None:
        ref = self._parse_ref(value)
        if ref is None:
            self.notice = "That entry no longer exists."
            await self.show(interaction)
            return
        await self.open_entry(ref[0], ref[1], interaction)

    async def remove_selected(self, interaction: discord.Interaction, value: str) -> None:
        ref = self._parse_ref(value)
        if ref is None:
            self.notice = "That entry no longer exists."
            await self.show(interaction)
        elif await self._guard_edit(interaction):
            key, idx = ref
            self.pending_remove = (key, idx, render.entry_label(key, self.char[key][idx]))
            await self.show(interaction)

    async def do_remove(self, interaction: discord.Interaction) -> None:
        key, idx, label = self.pending_remove
        items = list(self.char[key])
        if idx < len(items) and render.entry_label(key, items[idx]) == label:
            del items[idx]
            await self.save_patch(interaction, {key: items}, self.version, f"🗑️ Removed {label}.")
        else:
            self.notice = "That entry has already changed; nothing was removed."
            self.pending_remove = None
            await self.show(interaction)

    async def cancel_remove(self, interaction: discord.Interaction) -> None:
        self.pending_remove = None
        await self.show(interaction)


class Preview(Card):
    """A read-only card of imported text. Nothing is stored until the viewer presses Save."""

    expired = "⌛ This preview expired, so nothing was imported. Run `/character import` again."

    def __init__(self, viewer_id: int, guild_id: int, owner_id: int, char: dict, patch: dict, version: int, header: str):
        super().__init__(viewer_id, guild_id, owner_id)
        self.char, self.patch, self.version, self.header = char, patch, version, header

    def refresh(self, actor: Actor) -> None:  # always the draft, never editable
        self.pages = render.pages(self.char, self.section)
        self.page = min(self.page, len(self.pages) - 1)

    def build(self) -> None:
        super().build()
        for key, label, style, handler in (("save", "Save", discord.ButtonStyle.success, self.save),
                                           ("cancel", "Cancel", discord.ButtonStyle.secondary, self.cancel)):
            self.add_item(Btn(handler, label=label, style=style, row=2, custom_id=f"imc:{self.token}:{key}",
                              disabled=self.is_finished()))

    async def save(self, interaction: discord.Interaction) -> None:
        """Same permission and staleness checks as every form: refused if anyone saved since the preview."""
        self.stop()
        actor = actor_from(interaction)
        try:
            STORE.save(actor, self.owner_id, self.patch, expected_version=self.version)
        except PermissionDenied:
            text = "⛔ You no longer have permission to edit this character. Nothing was imported."
        except StaleEdit:
            text = "⚠️ This character was changed by someone else after you started. Nothing was imported; run `/character import` again."
        except model.ValidationError as e:
            text = f"⚠️ Nothing was imported: {e}"
        else:
            log.info("imported character guild=%s owner=%s by=%s keys=%s", self.guild_id, self.owner_id, actor.user_id, sorted(self.patch))
            card = Card(self.viewer_id, self.guild_id, self.owner_id)
            card.notice = "✅ Imported."
            await card.show(interaction)
            return
        await interaction.response.edit_message(content=text, embed=None, view=None)

    async def cancel(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.edit_message(content="Import cancelled. Nothing was changed.", embed=None, view=None)


class ConfirmDelete(discord.ui.View):
    """Two-button confirmation, bound to the viewer, expiring quickly."""

    def __init__(self, interaction: discord.Interaction, owner_id: int):
        super().__init__(timeout=120)
        self.token = secrets.token_hex(4)
        LIVE_CARDS.add(self.token)
        self.interaction, self.owner_id = interaction, owner_id
        self.viewer_id, self.guild_id = interaction.user.id, interaction.guild_id
        self.add_item(Btn(self.confirm, label="Delete character", style=discord.ButtonStyle.danger, custom_id=f"imc:{self.token}:delete"))
        self.add_item(Btn(self.cancel, label="Cancel", custom_id=f"imc:{self.token}:cancel"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        ok = interaction.user.id == self.viewer_id and interaction.guild_id == self.guild_id
        if ok:
            CLAIMED.add(interaction.id)
        return ok

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        log.exception("delete confirm error guild=%s viewer=%s", self.guild_id, self.viewer_id, exc_info=error)
        try:
            await reply(interaction, GENERIC_ERROR)
        except discord.HTTPException:
            pass

    def stop(self) -> None:
        LIVE_CARDS.discard(self.token)
        super().stop()

    async def on_timeout(self) -> None:
        LIVE_CARDS.discard(self.token)
        for item in self.children:
            item.disabled = True
        if not self.interaction.is_expired():
            try:
                await self.interaction.edit_original_response(
                    content="⌛ Delete request expired; nothing was deleted. Run `/character delete` again if you still want to.", view=self)
            except discord.HTTPException:
                pass

    async def confirm(self, interaction: discord.Interaction) -> None:
        for item in self.children:
            item.disabled = True
        try:
            deleted = STORE.delete(actor_from(interaction), self.owner_id)
            text = f"🗑️ Deleted the character of <@{self.owner_id}>." if deleted else "There was no character to delete."
            log.info("deleted character guild=%s owner=%s by=%s", self.guild_id, self.owner_id, interaction.user.id)
        except PermissionDenied:
            text = "⛔ You don't have permission to delete this character."
        await interaction.response.edit_message(content=text, view=self)
        self.stop()

    async def cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="Cancelled. Nothing was deleted.", view=None)
        self.stop()


# -- commands -----------------------------------------------------------------------------

async def open_card(interaction: discord.Interaction, member: discord.abc.User, editing: bool = False) -> None:
    if interaction.guild_id is None:
        await reply(interaction, NOT_IN_GUILD)
        return
    card = Card(interaction.user.id, interaction.guild_id, member.id, editing=editing)
    log.info("open card guild=%s viewer=%s owner=%s editing=%s", interaction.guild_id, interaction.user.id, member.id, editing)
    await card.show(interaction)


@tree.context_menu(name="View Character")
@app_commands.guild_only()
@app_commands.guild_install()
async def view_character(interaction: discord.Interaction, member: discord.Member) -> None:
    await open_card(interaction, member)


GUILD_ONLY = dict(guild_only=True, allowed_contexts=app_commands.AppCommandContext(guild=True),
                  allowed_installs=app_commands.AppInstallationType(guild=True))
character = app_commands.Group(name="character", description="Imperium Maledictum character profiles", **GUILD_ONLY)


@character.command(name="view", description="Show a character card. Only you will see it.")
@app_commands.describe(member="Whose character (default: yours)")
async def character_view(interaction: discord.Interaction, member: discord.Member | discord.User | None = None) -> None:
    await open_card(interaction, member or interaction.user)


@character.command(name="edit", description="Open a character card in editing mode.")
@app_commands.describe(member="Whose character (default: yours; GMs and admins may edit others)")
async def character_edit(interaction: discord.Interaction, member: discord.Member | discord.User | None = None) -> None:
    await open_card(interaction, member or interaction.user, editing=True)


@character.command(name="create", description="Create a character (one per member per server).")
@app_commands.describe(member="Create for another member (GMs and admins only)")
async def character_create(interaction: discord.Interaction, member: discord.Member | discord.User | None = None) -> None:
    if interaction.guild_id is None:
        await reply(interaction, NOT_IN_GUILD)
        return
    owner = member or interaction.user
    card = Card(interaction.user.id, interaction.guild_id, owner.id, editing=True)
    card.refresh(actor_from(interaction))
    if not card.editable:
        await reply(interaction, "⛔ Only the member, server administrators or the GM role can create this character.")
    elif card.char is not None:
        card.notice = "This member already has a character. Use **Edit** to change it."
        await card.show(interaction)
    else:
        await card.open_identity(interaction)


@character.command(name="delete", description="Delete a character after confirmation.")
@app_commands.describe(member="Whose character (default: yours; GMs and admins may delete others)")
async def character_delete(interaction: discord.Interaction, member: discord.Member | discord.User | None = None) -> None:
    if interaction.guild_id is None:
        await reply(interaction, NOT_IN_GUILD)
        return
    owner = member or interaction.user
    if not STORE.can_edit(actor_from(interaction), owner.id):
        await reply(interaction, "⛔ You don't have permission to delete this character.")
        return
    if STORE.load(interaction.guild_id, owner.id) is None:
        await reply(interaction, f"<@{owner.id}> has no character on this server.")
        return
    await reply(interaction, f"Delete the character of <@{owner.id}>? This cannot be undone.",
                view=ConfirmDelete(interaction, owner.id))


@character.command(name="export", description="Get a character as text to copy, edit and import again. Only you will see it.")
@app_commands.describe(member="Whose character (default: yours)")
async def character_export(interaction: discord.Interaction, member: discord.Member | discord.User | None = None) -> None:
    if interaction.guild_id is None:
        await reply(interaction, NOT_IN_GUILD)
        return
    owner = member or interaction.user
    row = STORE.load(interaction.guild_id, owner.id)
    char = row[0] if row else None
    text = textsheet.format_text(char)
    target = "`/character import`" if owner.id == interaction.user.id else f"`/character import` with **member** set to <@{owner.id}>"
    if char is None:
        intro = (f"<@{owner.id}> has no character yet, so here is a blank template. Fill it in and paste it into "
                 f"{target}: one entry per line, columns separated by `|`, for example "
                 "`Ranged 45 (Pistols 50)` or `Laspistol | 4 | Medium | 15 | Reliable`.")
    else:
        intro = (f"**{char['name']}** as text. Copy it, change what you like and paste it into {target}. "
                 "Sections you leave out stay as they are.")
    message = f"{intro}\n```\n{text}\n```"
    if discord_len(message) <= MESSAGE_MAX and "```" not in text:
        await reply(interaction, message)
        return
    intro += " It is too long for one message, so here it is as a file."
    if discord_len(text) > PASTE_MAX:
        intro += (f"\n⚠️ It is over the {PASTE_MAX} characters the paste box takes. To import it, attach the edited "
                  "file to `/character import`, or paste one section at a time.")
    filename = re.sub(r"[^\w-]+", "_", char["name"] if char else "").strip("_") or "character"
    await reply(interaction, intro, file=discord.File(io.BytesIO(text.encode("utf-8")), filename=f"{filename}.txt"))


@character.command(name="import", description="Create or update a character from text: paste it, or attach a .txt file.")
@app_commands.describe(member="Whose character (default: yours; GMs and admins may import for others)",
                       file=f"A .txt file instead of pasting, for text over {PASTE_MAX} characters")
async def character_import(interaction: discord.Interaction, member: discord.Member | discord.User | None = None,
                           file: discord.Attachment | None = None) -> None:
    if interaction.guild_id is None:
        await reply(interaction, NOT_IN_GUILD)
        return
    owner = member or interaction.user
    if not STORE.can_edit(actor_from(interaction), owner.id):
        await reply(interaction, "⛔ Only the member, server administrators or the GM role can import this character.")
        return
    if file is None:
        async def done(i: discord.Interaction, raw: dict) -> None:
            await preview_import(i, owner.id, raw["text"], pasted=True)

        await interaction.response.send_modal(Form("Import character", [IMPORT_FIELD], {}, done))
        return
    if not (file.filename.lower().endswith(".txt") or (file.content_type or "").startswith("text/")):
        await reply(interaction, "⚠️ Please attach a plain text (.txt) file, or run `/character import` without a file and paste the text.")
        return
    if file.size > IMPORT_MAX_BYTES:
        await reply(interaction, f"⚠️ That file is too big ({file.size // 1000} KB). A character's text is only a few KB.")
        return
    await interaction.response.defer(ephemeral=True, thinking=True)  # the download may outlast Discord's 3-second reply window
    data = await file.read()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")  # older Windows Notepad default
    await preview_import(interaction, owner.id, text)


NOTHING_TO_IMPORT = ("⚠️ Nothing was imported: the text has no `Name:` line and no headings such as SKILLS or TALENTS. "
                     "Run `/character export` to get a template to fill in.")


async def preview_import(interaction: discord.Interaction, owner_id: int, text: str, pasted: bool = False) -> None:
    """Read ``text`` and show the result as a preview card. Nothing is stored until Save."""
    row = STORE.load(interaction.guild_id, owner_id)
    current, version = row if row else (None, 0)
    patch, problems = textsheet.parse_text(text)
    if not patch:
        await reply(interaction, NOTHING_TO_IMPORT)
        return
    if current is None and not patch.get("name"):
        await reply(interaction, "⚠️ Nothing was imported: a new character needs a name. Add a line like `Name: Vex Harrow`.")
        return
    try:
        char = model.apply_patch(current, patch)
    except model.ValidationError as e:
        await reply(interaction, f"⚠️ Nothing was imported: {e}")
        return
    cut_off = pasted and discord_len(text) >= PASTE_MAX  # the box was full, so the client may have dropped the rest
    log.info("import preview guild=%s owner=%s by=%s problems=%d", interaction.guild_id, owner_id, interaction.user.id, len(problems))
    header = import_header(owner_id, current, char, patch, problems, cut_off)
    await Preview(interaction.user.id, interaction.guild_id, owner_id, char, patch, version, header).show(interaction)


def import_header(owner_id: int, old: dict | None, new: dict, patch: dict, problems: list[str], cut_off: bool) -> str:
    """The text above an import preview: whose character, what the text changes, what it keeps, what could not be read."""
    lines = [(f"📝 **Preview of the character of <@{owner_id}>: nothing is saved yet.** "
              "Look through the sections, then press **Save** or **Cancel**.")]
    if cut_off:
        lines.append(f"⚠️ **Your text filled the whole {PASTE_MAX}-character box, so its end may be cut off.** Check the "
                     "last section. For longer text, attach a .txt file to `/character import` instead.")
    if old is not None:
        parts = {"name": "name", "description": "description",
                 **{k: textsheet.TITLES[k].lower() for k in ("characteristics", *model.LIST_KEYS)}}
        for k in model.LIST_KEYS:
            if k in patch:
                parts[k] += f" ({len(new[k])}" + (f", was {len(old[k])})" if len(old[k]) != len(new[k]) else ")")
        lines.append("From your text: " + ", ".join(v for k, v in parts.items() if k in patch) + ".")
        kept = [v for k, v in parts.items() if k not in patch]
        if kept:
            lines.append("Not in your text, so kept as they are: " + ", ".join(kept) + ".")
    if problems:
        lines.append(f"⚠️ Skipped {len(problems)} line(s) that could not be read:")
        lines += [f"• {p}" for p in problems[:8]]
        if len(problems) > 8:
            lines.append(f"…and {len(problems) - 8} more.")
    return "\n".join(lines)[:MESSAGE_MAX]


ROLL_NOTES_MAX = 500  # keeps a result with the longest name, skill and modifiers under MESSAGE_MAX
MAX_ADVANTAGE = 10


def roll_targets(char: dict) -> list[tuple[str, int]]:
    """(label, rating) of every rated characteristic, skill and specialisation, in sheet order."""
    out = [(f"{full} ({abbr})", char["characteristics"][abbr]) for abbr, full in model.CHARACTERISTICS]
    for s in char["skills"]:
        out += [(s["name"], s["rating"])] + [(f"{s['name']} ({sp['name']})", sp["rating"]) for sp in s["specialisations"]]
    return [(label, rating) for label, rating in out if rating is not None]


def find_target(targets: list[tuple[str, int]], text: str) -> tuple[str, int] | None:
    """The exact label, else the only label containing ``text``. Never a guess: the result is public."""
    t = text.strip().lower()
    exact = [x for x in targets if x[0].lower() == t]
    partial = [x for x in targets if t and t in x[0].lower()]
    return exact[0] if exact else partial[0] if len(partial) == 1 else None


@character.command(name="roll", description="Roll a Test against your character's characteristic, skill or specialisation.")
@app_commands.describe(skill="Characteristic, skill or specialisation: start typing, then pick one",
                       notes="What the roll is for, e.g. Sneaking past the guards",
                       test_adjustment="Difficulty: added to your skill before rolling, e.g. 20 or -10",
                       advantage="Reverse the dice if better; each Advantage after the first adds 10 to your skill",
                       disadvantage="Reverse the dice if worse; each Disadvantage after the first takes 10 off your skill",
                       sl_adjustment="Added to your SL after rolling, e.g. 1 or -2")
async def character_roll(interaction: discord.Interaction, skill: str,
                         notes: app_commands.Range[str, 1, ROLL_NOTES_MAX] | None = None, test_adjustment: int = 0,
                         advantage: app_commands.Range[int, 0, MAX_ADVANTAGE] = 0,
                         disadvantage: app_commands.Range[int, 0, MAX_ADVANTAGE] = 0, sl_adjustment: int = 0) -> None:
    row = STORE.load(interaction.guild_id, interaction.user.id)
    if row is None:
        await reply(interaction, "You have no character on this server yet. Create one with `/character create`.")
        return
    target = find_target(roll_targets(row[0]), skill)
    if target is None:
        await reply(interaction, "⚠️ Nothing was rolled: that is not one of your character's rated characteristics, skills or "
                                 "specialisations. Start typing in the **skill** box and pick one from the list.")
        return
    label, rating = target
    you = rolls.Participant(row[0]["name"], rating, test_adjustment=test_adjustment, sl_adjustment=sl_adjustment,
                            advantage=advantage, disadvantage=disadvantage, skill_name=label)
    result = rolls.build_test_result(you, notes)
    await interaction.response.send_message(result)  # public on purpose; the client never pings anyone


@character_roll.autocomplete("skill")
async def roll_choices(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    row = STORE.load(interaction.guild_id, interaction.user.id)
    targets = roll_targets(row[0]) if row else []
    typed = current.strip().lower()
    return [app_commands.Choice(name=f"{label[:90]} — {rating}", value=label[:100])
            for label, rating in targets if typed in label.lower()][:25]


tree.add_command(character)

setup = app_commands.Group(name="setup", description="Bot setup (server administrators only)",
                           default_permissions=discord.Permissions(administrator=True), **GUILD_ONLY)


@setup.command(name="gm-role", description="Show, set or clear the GM role that may edit everyone's characters.")
@app_commands.describe(role="Role whose members act as GMs", clear="Remove the configured GM role")
async def setup_gm_role(interaction: discord.Interaction, role: discord.Role | None = None, clear: bool = False) -> None:
    if interaction.guild_id is None:
        await reply(interaction, NOT_IN_GUILD)
        return
    if not interaction.permissions.administrator:
        await reply(interaction, "⛔ Only server administrators can change bot setup.")
        return
    if clear:
        STORE.set_gm_role(interaction.guild_id, None)
        log.info("gm role cleared guild=%s by=%s", interaction.guild_id, interaction.user.id)
        await reply(interaction, "GM role cleared. Only owners and administrators can edit characters now.")
    elif role is not None:
        STORE.set_gm_role(interaction.guild_id, role.id)
        log.info("gm role set guild=%s role=%s by=%s", interaction.guild_id, role.id, interaction.user.id)
        await reply(interaction, f"GM role set to <@&{role.id}> (ID {role.id}). Its members can now create and edit any character on this server.")
    else:
        current = STORE.gm_role(interaction.guild_id)
        await reply(interaction, f"Current GM role: <@&{current}> (ID {current})." if current else "No GM role configured.")


tree.add_command(setup)


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.CheckFailure):
        text = "⛔ You can't use this command here."
    else:
        log.exception("command error guild=%s user=%s", interaction.guild_id, interaction.user.id, exc_info=error)
        text = GENERIC_ERROR
    try:
        await reply(interaction, text)
    except discord.HTTPException:
        pass


@client.event
async def on_interaction(interaction: discord.Interaction) -> None:
    """Buttons of cards that died (bot restart, expiry) would otherwise fail silently."""
    if interaction.type is not discord.InteractionType.component:
        return
    # The card's handler may already have run and stopped the card (Save, Cancel, Delete), which drops
    # its token from LIVE_CARDS; CLAIMED tells that apart from a click on a genuinely dead card.
    if interaction.id in CLAIMED:
        CLAIMED.discard(interaction.id)
        return
    custom_id = (interaction.data or {}).get("custom_id", "")
    if custom_id.startswith("imc:") and custom_id.split(":")[1] not in LIVE_CARDS:
        await reply(interaction, Preview.expired if custom_id.endswith(":save") else f"⌛ This card has expired. {REOPEN_HINT}")


@client.event
async def setup_hook() -> None:
    dev_guild = os.environ.get("DEV_GUILD_ID")
    if dev_guild:
        guild = discord.Object(id=int(dev_guild))
        tree.copy_global_to(guild=guild)
        synced = await tree.sync(guild=guild)
        log.info("synced %d commands to guild %s", len(synced), dev_guild)
    else:
        synced = await tree.sync()
        log.info("synced %d global commands", len(synced))


@client.event
async def on_ready() -> None:
    log.info("logged in as %s (id %s) in %d guild(s)", client.user, client.user.id, len(client.guilds))


def load_env_file(path: str = ".env") -> None:
    """Tiny .env loader (KEY=VALUE lines) so local runs need no extra dependency."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    global STORE
    load_env_file()
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        sys.exit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill in your bot token.")
    db_path = os.environ.get("DB_PATH", "data/characters.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    STORE = Store(db_path)
    log.info("database: %s", db_path)
    try:
        client.run(token, log_level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO), root_logger=True)
    except discord.LoginFailure:
        sys.exit("Discord rejected the bot token. Reset it in the Developer Portal (Bot → Reset Token) and update .env.")
