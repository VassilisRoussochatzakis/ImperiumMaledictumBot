"""Fakes that stand in for Discord interactions. No token, no network."""
from __future__ import annotations

import asyncio

import discord
import pytest

from imbot import bot
from imbot.store import Actor, Store

GUILD, OTHER_GUILD = 100, 200
OWNER, PLAYER, GM, ADMIN = 1, 2, 3, 4
GM_ROLE = 50

run = asyncio.run


class Role:
    def __init__(self, id):
        self.id = id


class User:
    def __init__(self, id, roles=()):
        self.id = id
        self.roles = [Role(r) for r in roles]
        self.mention = f"<@{id}>"
        self.bot = False


class Perms:
    def __init__(self, admin):
        self.administrator = admin


def _must_be_ephemeral(kind, kw):
    """Every message-creating call in every test must be ephemeral; fail at the call, not later."""
    assert kw.get("ephemeral") is True, f"{kind} without ephemeral=True: {kw}"


class Response:
    def __init__(self, log):
        self.log, self.done = log, False

    def is_done(self):
        return self.done

    async def send_message(self, content=None, **kw):
        _must_be_ephemeral("send_message", kw)
        self.done = True
        self.log.append(("send_message", content, kw))

    async def edit_message(self, **kw):
        self.done = True
        self.log.append(("edit_message", kw.get("content"), kw))

    async def send_modal(self, modal):
        self.done = True
        self.log.append(("send_modal", modal, {}))

    async def defer(self, **kw):
        _must_be_ephemeral("defer", kw)
        self.done = True
        self.log.append(("defer", None, kw))


class Followup:
    def __init__(self, log):
        self.log = log

    async def send(self, content=None, **kw):
        _must_be_ephemeral("followup", kw)
        self.log.append(("followup", content, kw))


class Fake:
    """A duck-typed discord.Interaction."""

    def __init__(self, user, guild_id=GUILD, admin=False, message=None, custom_id=None, kind=None):
        self.user, self.guild_id, self.message = user, guild_id, message
        self.permissions = Perms(admin)
        self.log: list[tuple] = []
        self.response, self.followup = Response(self.log), Followup(self.log)
        self.type = kind or (discord.InteractionType.component if message else discord.InteractionType.application_command)
        self.data = {"custom_id": custom_id} if custom_id else {}

    def is_expired(self):
        return False

    async def edit_original_response(self, **kw):
        self.log.append(("edit_original", kw.get("content"), kw))

    @property
    def last(self):
        return self.log[-1]

    @property
    def embed(self) -> discord.Embed:
        return self.last[2]["embed"]

    @property
    def view(self):
        return self.last[2].get("view")


def actor(user_id, guild_id=GUILD, roles=(), admin=False):
    return Actor(guild_id, user_id, frozenset(roles), admin)


@pytest.fixture
def store():
    bot.STORE = Store(":memory:")
    yield bot.STORE
    bot.STORE.close()


@pytest.fixture
def card_user_store(store):
    """A stored character for OWNER plus a GM role, returns the store."""
    store.set_gm_role(GUILD, GM_ROLE)
    store.save(actor(OWNER), OWNER, {
        "name": "Vex Harrow", "description": "A disgraced Administratum clerk.",
        "characteristics": {"WS": 30, "BS": 42, "Str": 28, "Tgh": 35, "Ag": 40, "Int": 48, "Per": 38, "Wil": 33, "Fel": 31},
        "skills": [{"name": "Lore", "rating": 58, "specialisations": [{"name": "Adeptus Administratum", "rating": 63}], "notes": "Knows the forms."},
                   {"name": "Awareness", "rating": 43}],
        "talents": [{"name": "Bureaucratic Insight", "notes": "Re-roll one Lore test per session."}],
        "weapons": [{"name": "Laspistol", "damage": "6", "range": "Medium", "magazine": "15", "traits": "Reliable"}],
        "armour": [{"name": "Flak Coat", "locations": "Body, Arms", "armour": "3", "encumbrance": "1", "traits": "—"}],
        "equipment": [{"name": "Data-slate", "quantity": 1, "notes": "Encrypted."}, {"name": "Ration packs", "quantity": 6}],
    })
    return store


def button(view, label):
    for item in view.children:
        if getattr(item, "label", None) == label:
            return item
    raise AssertionError(f"no button {label!r}; have {[getattr(i, 'label', getattr(i, 'placeholder', None)) for i in view.children]}")


def select(view, placeholder):
    for item in view.children:
        if getattr(item, "placeholder", None) == placeholder:
            return item
    raise AssertionError(f"no select {placeholder!r}")


def labels(view):
    return [getattr(i, "label", None) or getattr(i, "placeholder", None) for i in view.children]


async def open_card(user, owner_id=OWNER, guild_id=GUILD, admin=False, editing=False):
    """Open a card the way the context menu / slash command does, return (card, interaction)."""
    i = Fake(user, guild_id=guild_id, admin=admin)
    await bot.open_card(i, User(owner_id), editing=editing)
    return i.view, i


async def click(card, label, user, guild_id=GUILD, admin=False):
    i = Fake(user, guild_id=guild_id, admin=admin, message=object())
    assert await card.interaction_check(i), "interaction_check refused the viewer"
    await button(card, label).callback(i)
    return i


async def choose(card, placeholder, value, user, admin=False):
    i = Fake(user, admin=admin, message=object())
    sel = select(card, placeholder)
    sel._values = [value]  # what discord.py sets from the interaction payload
    await sel.callback(i)
    return i


async def submit(modal, values: dict, user, admin=False, from_message=True):
    """Fill a Form's inputs and submit it as ``user``."""
    for key, text in values.items():
        modal.inputs[key]._value = text
    i = Fake(user, admin=admin, message=object() if from_message else None, kind=discord.InteractionType.modal_submit)
    await modal.on_submit(i)
    return i
