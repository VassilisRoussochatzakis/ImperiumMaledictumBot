# Imperium Maledictum character bot

A Discord bot for play-by-post **Warhammer 40,000 Roleplay: Imperium Maledictum** games.
Right-click a server member, pick **Apps → View Character**, and you get that member's character
card. The card is private: only you see it, and it is never posted to the channel or sent by DM.

Every card has four sections: **Characteristics**, **Skills**, **Talents** and **Equipment**
(Weapons, Armour and Other Equipment). Players create and edit their own character with slash
commands, buttons, menus and forms. A configurable GM role (and server administrators) can edit
everyone's characters.

Field names follow the official Cubicle 7 character sheet. The bot stores what you type and rolls
Tests against it (`/character roll`, the one thing it posts in the channel). It does not calculate
totals or track advancement.

---

## 1. Create the Discord application

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click
   **New Application**. Name it (for example *Imperium Maledictum*).
2. In the left menu open **Bot**. Click **Reset Token**, then **Copy** the token. You will paste it
   into `.env` in the next step. The token is only shown once; never share or commit it.
3. Still under **Bot → Privileged Gateway Intents**, leave **Presence**, **Server Members** and
   **Message Content** switched **off**. The bot does not need them.
4. Under **Installation**, make sure **Guild Install** is enabled (it is by default). The bot does
   not support user install.
5. Under **OAuth2 → OAuth2 URL Generator** tick the scopes **`bot`** and **`applications.commands`**.
   Leave every bot permission unticked: the bot only answers interactions (privately, apart from
   roll results), and answering an interaction needs no channel permissions. Copy the generated
   URL. It looks like:

   ```
   https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&scope=bot%20applications.commands&permissions=0
   ```

6. Open that URL, choose your server and authorise. You need **Manage Server** on that server.

## 2. Supply the token locally

```bash
cp .env.example .env
```

Edit `.env` and set `DISCORD_TOKEN` to the token you copied. The other values can stay as they are.
`.env`, the `data/` folder and `*.db` files are listed in `.gitignore` so they never reach version
control. Secrets are only ever read from the environment; nothing is logged.

Optional: while testing, set `DEV_GUILD_ID` to your server's ID (Server Settings → Widget, or
right-click the server with Developer Mode on → *Copy Server ID*). Commands then appear instantly
in that one server. Leave it empty for normal, global registration. If you later clear it, that
test server keeps its server-specific copies and shows each command twice; kick and re-invite the
bot there once to remove them.

## 3. Run it

### Option A: Docker (recommended for the one-host deployment)

```bash
docker compose up -d --build
```

This builds the image, starts one container, restarts it automatically after crashes or reboots,
and keeps the database in `./data/characters.db` on the host. Check it is alive:

```bash
docker compose logs -f
```

You should see `logged in as ...` and `synced N global commands`.

### Option B: plain Python (3.11 or newer)

```bash
python -m venv .venv
```

```bash
.venv/Scripts/pip install -r requirements.txt
```

(on macOS/Linux use `.venv/bin/pip`), then:

```bash
.venv/Scripts/python -m imbot
```

The database is created at `data/characters.db` (configurable with `DB_PATH`). Stop with Ctrl+C.

## 4. Check the commands registered

The bot registers its commands with Discord every time it starts (`synced N commands` in the log).
When `DEV_GUILD_ID` is empty the commands are global; the first global registration can take up to
an hour to show up in Discord clients, and may need a client restart (Ctrl+R in desktop Discord).

To verify: right-click any member (on mobile, tap their name and then the ⋯ menu) and look for
**Apps → View Character**. Type `/character` in a channel and the `view`, `edit`, `create`,
`delete`, `export`, `import` and `roll` subcommands should be offered. Administrators also see `/setup gm-role`.

## 5. Configure the GM role (administrators)

```
/setup gm-role role:@Game Master
```

Members of that role can create, edit and delete any character on this server. Server
administrators always can. `/setup gm-role` without arguments shows the current role;
`/setup gm-role clear:True` removes it. The role is stored by its Discord role ID, so renaming the
role is fine. Only members with the **Administrator** permission can use `/setup`.

## 6. Playing

### Create your character

```
/character create
```

A form asks for the character's name and a short description. Then the card opens in editing mode.
Each member has one character per server. A GM can create one for someone else with
`/character create member:@Player`.

### View a character

Right-click a member → **Apps → View Character**, or `/character view member:@Player`
(`/character view` alone shows your own). The card shows the character's name, its owner, and the
selected section, with buttons:

| Button | What it shows |
|---|---|
| **Characteristics** | Description and the nine characteristics (WS, BS, Str, Tgh, Ag, Int, Per, Wil, Fel) |
| **Skills** | Each skill with its total, specialisations and notes |
| **Talents** | Each talent with its effect |
| **Equipment** | **Weapons** (damage, range, magazine, traits), **Armour** (locations, armour value, encumbrance, traits) and **Other Equipment** (quantity, notes) |

Long sections are split into pages; use **◀ Previous** / **Next ▶**. Empty sections say so.
If the member has no character the card says so (and offers **Create character** if you may).

### Edit a character

Press **Edit** on a card (shown only when you are allowed to edit it), or run `/character edit`.
In editing mode the card gains:

- **Name & description**, **Edit WS–Ag**, **Edit Int–Fel** on the Characteristics section: forms
  for identity and the characteristics (Discord forms hold five fields, hence two).
- **Add skill / talent / weapon / armour / other equipment** buttons.
- **Edit an entry…**: pick an entry on the current page, change it in a form.
- **Remove an entry…**: pick an entry, then confirm with the red **Remove** button (or **Cancel**).
- **Done editing** returns to the plain view.

Skill specialisations are entered one per line as *name* then *total*, for example
`Adeptus Mechanicus 45`. Ratings are whole numbers from 0 to 100. If a form fails validation the
card explains why and nothing is changed.

### Copy a character as text, or import one

For writing a whole character at once instead of form by form:

1. `/character export` sends you your character as text (a blank template if you have none yet).
   Only you see it.
2. Copy the text, change what you like, then run `/character import` and paste it into the box.
3. The bot shows a **preview**: it lists what your text changes, what it leaves alone, and any lines
   it could not read. Nothing is saved until you press **Save**. **Cancel** throws it away.

The text looks like this. One entry per line; columns are separated by `|`; the heading of each
list shows its columns:

```
Name: Vex Harrow
Description: A disgraced Administratum clerk.

CHARACTERISTICS
WS 30, BS 42, Str 28, Tgh 35, Ag 40, Int 48, Per 38, Wil 33, Fel 31

SKILLS (Skill Total (Specialisation Total, ...) | Notes)
Lore 58 (Adeptus Administratum 63) | Knows the forms.
Awareness 43

TALENTS (Talent | Effect)
Bureaucratic Insight | Re-roll one Lore test per session.

WEAPONS (Name | Damage | Range | Mag. | Traits & notes)
Laspistol | 6 | Medium | 15 | Reliable

ARMOUR (Name | Locations | Armour | Enc. | Traits & notes)
Flak Coat | Body, Arms | 3 | 1

OTHER EQUIPMENT (Name | Quantity | Notes)
Ration packs | 6
```

- **Anything you leave out stays as it is.** A text with only a `TALENTS` heading and its lines
  replaces the talents and keeps everything else. A heading with no lines under it empties
  that list. `WS -` empties one characteristic.
- Upper or lower case, bullets (`-`, `•`, `1.`) and Markdown are fine. If you copy the whole bot
  message, only the part inside the grey box is read.
- **The paste box holds at most 4000 characters**, and Discord will not take more. If your text
  fills the box completely, the preview warns that the end may have been cut off. For longer text,
  either import one section at a time or save the text as a `.txt` file and attach it to
  `/character import` (the **file** option). `/character export` attaches a file itself when the
  character is too long for one message, and says so when it is over 4000 characters.
- GMs and administrators can import for someone else with `/character import member:@Player`.
  Anyone can export any character, because anyone can view it.
- Line breaks inside an entry's notes become spaces.

### Roll a Test

```
/character roll skill:Lore notes:Reading the forms test_adjustment:-10 advantage:1
```

Start typing in **skill** and pick one of your character's characteristics, skills or
specialisations from the list; each shows its rating. Everything else is optional:

| Option | What it does |
|---|---|
| **notes** | What the roll is for, shown above the result |
| **test_adjustment** | The difficulty: added to the rating before rolling, e.g. `20` or `-10` |
| **advantage** / **disadvantage** | 0 to 10 each; they cancel 1:1. Advantage reverses the dice if that is better, Disadvantage if that is worse, and each one after the first adds (or takes off) 10 |
| **sl_adjustment** | Added to the SL after rolling, e.g. `1` or `-2`; it can turn a failure into a success or back |

The bot rolls a d100 and posts the result **in the channel**, so the whole table sees it:

> **Test:** Reading the forms
>
> **Vex Harrow** rolled: **62**, reversed to **26**, with a target of **48** (skill: **58**, test adjustment: **-10**, Advantage)\
> **Success** (+2 SL) on **Lore**!

Doubles add **Critical!** or **Fumble!**. Only entries with a rating can be rolled, and only for
your own character. Typing a name without picking from the list works when it matches exactly one
entry (`bs` finds Ballistic Skill). Otherwise nothing is rolled and only you see why.

### Delete a character

```
/character delete
```

Asks for confirmation. GMs and administrators may add `member:@Player`.

### Who can do what

| Action | Owner | GM role | Administrator | Others |
|---|---|---|---|---|
| View or export any character on the server | ✓ | ✓ | ✓ | ✓ |
| Create / edit / import / delete own character | ✓ | ✓ | ✓ | ✓ |
| Create / edit / import / delete another member's character | – | ✓ | ✓ | – |
| Roll a Test (own character only; the result is public) | ✓ | ✓ | ✓ | ✓ |
| `/setup gm-role` | – | – | ✓ | – |

Permissions are checked on the server for every command, button, menu choice and form submission,
not just when the buttons are drawn. If a GM loses the role while a form or import preview is
open, the save is refused.

### Privacy and expiry

Everything the bot says is an *ephemeral* Discord response: visible only to the person who
clicked, never in the channel history, never a DM. The one exception is a roll result, which
`/character roll` posts in the channel on purpose. A card belongs to the member who opened it. It
stays interactive for 10 minutes after the last click; then its buttons are disabled and the card
says how to reopen it (Apps → View Character or `/character view`). After a bot restart or update,
buttons on older cards reply "This card has expired" instead; just open a new card. A form left
open for more than 30 minutes, or across a restart, cannot be submitted; reopen the card and redo
the change. The delete confirmation expires after two minutes. An import preview expires like a
card, 10 minutes after the last click, and nothing is saved.

If two people edit the same character at once, the second save is refused with a notice and the
card refreshes to the latest version, so nobody silently overwrites anybody. The same goes for an
import preview: if anyone saves the character before you press **Save**, the import is refused.

## 7. Operating the single host

- **Where is the data?** One SQLite file, `data/characters.db` (plus temporary `-wal`/`-shm`
  files while the bot runs). Characters are keyed by server ID and member ID, never by display
  name, and servers never see each other's data.
- **Update the bot:** `git pull`, then `docker compose up -d --build`. Data is untouched.
- **Logs:** `docker compose logs -f`. At the default `INFO` level logs record who opened or saved
  what by ID and never contain the token or sheet contents. `LOG_LEVEL=DEBUG` makes discord.py log
  every request body, including card contents, so use it only while debugging.
- **Restart:** `docker compose restart`. Open cards expire; nothing is lost.

### Backup (safe while the bot is running)

Never copy the `.db` file while the bot is running; SQLite may be mid-write. Use SQLite's online
backup instead, which produces a consistent snapshot:

```bash
docker compose exec bot python -c "import sqlite3; s=sqlite3.connect('/data/characters.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close(); print('ok')"
```

Then copy `data/backup.db` somewhere safe. Running the plain-Python option, use
`data/characters.db` and any destination path instead. Automate with cron or Task Scheduler.

### Restore

1. Stop the bot: `docker compose down` (or Ctrl+C).
2. Delete `data/characters.db`, `data/characters.db-wal` and `data/characters.db-shm` if present.
3. Copy your backup to `data/characters.db`.
4. Start the bot again: `docker compose up -d`.

## 8. Importing characters from code (for developers)

Players import text with `/character import` (see section 6). The text format lives in
`imbot/textsheet.py`: `format_text` writes it and `parse_text` turns it into a patch for the one
internal entry point that every editor and importer uses. Another importer (a spreadsheet, say)
would call that entry point too.

```python
from imbot.store import Store, Actor

store = Store("data/characters.db")
actor = Actor(guild_id=SERVER_ID, user_id=WHO_RUNS_THE_IMPORT, role_ids=frozenset(THEIR_ROLE_IDS), is_admin=False)
character, version = store.save(actor, owner_id=MEMBER_ID, patch=payload)
```

`Store.save` is exactly what the Discord forms call. It checks that the actor may edit that owner's
character on that server (owner, GM role, or administrator), validates the payload, merges it over
the stored character and writes it in one transaction. On any failure it raises
(`PermissionDenied`, `model.ValidationError`, `StaleEdit`) and writes nothing.

**Who is the actor?** Whoever is running the import, resolved from Discord by the caller.
Ownership or permission claims inside the payload are never trusted: a payload containing
`owner_id`, `guild_id` or any other unknown key is rejected.

**Payload shape** (every key optional, see `imbot/model.py` for limits):

```json
{
  "name": "Sister Ysolde Varn",
  "description": "Adepta Sororitas hospitaller, seconded to the Inquisition.",
  "characteristics": {"WS": 35, "BS": 30, "Str": 32, "Tgh": 38, "Ag": 36, "Int": 45, "Per": 40, "Wil": 50, "Fel": 42},
  "skills": [{"name": "Medicae", "rating": 60, "specialisations": [{"name": "Surgery", "rating": 65}], "notes": ""}],
  "talents": [{"name": "Field Medic", "notes": "Heal without a medikit at a penalty."}],
  "weapons": [{"name": "Chainsword", "damage": "9", "range": "Melee", "magazine": "—", "traits": "Rend (1), Loud"}],
  "armour": [{"name": "Carapace Armour", "locations": "Body, Arms, Legs", "armour": "5", "encumbrance": "2", "traits": "Bulky"}],
  "equipment": [{"name": "Medikit", "quantity": 1, "notes": "Full"}]
}
```

**Omitted versus cleared:**

- A key that is **omitted** keeps its stored value. `{"characteristics": {"BS": 33}}` changes BS
  only; the other eight characteristics and every list stay as they were.
- A key set to **`null`** (or `""` for text, `[]` for lists) is **cleared**. Lists are replaced
  wholesale, so to remove one talent send the full list without it.
- `name` is required when creating a character and can never be cleared.
- Pass `expected_version=` (the version you last read) to refuse the write if someone edited the
  character in between.

`tests/test_import_hook.py` saves the example above through this entry point and shows it on a card.

## 9. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| **Apps → View Character** is missing | Commands not registered yet. Check the log for `synced`; global commands can take up to an hour on first registration; restart your Discord client (Ctrl+R). Make sure the invite used the `applications.commands` scope; if not, re-invite with the URL from step 1. |
| Discord refuses the command in a channel, or it is missing from the picker there | Discord requires the *person using the command* to have **Send Messages** and **Use Application Commands** in that channel. Try another channel or adjust the channel permissions. |
| `/setup` is not shown | It is only visible to members with the Administrator permission. |
| "You don't have permission to edit this character" | You are not the owner, not in the configured GM role, and not an administrator. Ask an admin to run `/setup gm-role`. |
| "This card has expired" | The card was idle for 10 minutes or the bot restarted since it was opened. Open a new card with Apps → View Character. |
| Buttons do nothing or Discord says "This interaction failed" | The bot is not running or cannot reach Discord. Check `docker compose logs -f` and restart it. |
| Commands appear twice in one server | Leftover server-specific copies from `DEV_GUILD_ID` testing. Kick and re-invite the bot in that server. |
| Form says "changed by someone else" | Another editor saved first. The card shows the latest version; redo your change. |
| `DISCORD_TOKEN is not set` on start | `.env` is missing or empty. Copy `.env.example` and paste the token. |
| `Improper token has been passed` | Token mistyped or reset in the portal. Reset it again and update `.env`. |
| Commands show in one server only | `DEV_GUILD_ID` is set. Clear it to register globally (see step 2 about duplicates). |

## 10. Tests

The automated tests need no Discord token or network:

```bash
.venv/Scripts/pip install pytest==9.1.1
```

```bash
.venv/Scripts/python -m pytest
```

They cover: every message-producing path is ephemeral; section navigation and paging render the
right character; owners can edit themselves and ordinary players cannot edit others; GMs and
administrators can edit within their server but not in another server; cross-server access and
tampered buttons or menu values are rejected; lost permissions and stale forms cannot change data;
validation failures preserve saved data; data survives reopening the database; the import hook uses
the same validation and authorisation; exported text reads back unchanged, messy pasted text is
read forgivingly and unreadable lines are reported; an import saves nothing before **Save** and
respects permissions and staleness; a full paste box is flagged; `.txt` files are accepted and
other files refused; long sheets and empty sections stay within Discord's limits; rolls use the
stored rating and every modifier, are the only public message, and privately refuse names that are
unknown, ambiguous or unrated; Success Levels, Advantage and doubles follow the rulebook examples;
and the command and component payloads sent to Discord are within its limits.

### Live acceptance checklist

Needs one server, the bot installed, and three accounts: **Player A**, **Player B** and a **GM**
(an admin account can stand in for the GM to run `/setup`).

1. Admin: `/setup gm-role role:@GM`. Reply is visible only to the admin.
2. Player A: `/character create`, fill the form. The card appears and only Player A sees any
   message. Player B, watching the same channel, sees nothing.
3. Player A: add a skill with a specialisation, a talent, a weapon, an armour piece and an item.
   Switch between all four sections; Equipment shows Weapons, Armour and Other Equipment headings.
4. Player B: right-click Player A → **Apps → View Character**. The card shows A's character, the
   owner line names Player A, and there is **no Edit button**. Player A sees nothing new.
5. Player B: `/character view member:@PlayerA` works the same. `/character edit member:@PlayerA`
   opens a read-only card (no Edit controls). `/character delete member:@PlayerA` is refused.
6. GM: open Player A's card; **Edit** is present. Change a characteristic. Player A reopens their
   card and sees the change.
7. Stale edit: GM opens an edit form for A's talent but does not submit. Player A edits the same
   talent and saves. GM submits: refused with the "changed by someone else" notice, card refreshed.
8. Lost role: GM opens an edit form; admin removes the GM role from that account; GM submits:
   refused with "no longer have permission".
9. Player A: try the Remove menu, then **Cancel** (nothing removed), then remove for real.
10. Player A: enter `abc` as a rating: card says "Not saved", the old value remains.
11. Wait 10 minutes without touching a card: it shows the expiry text and disabled buttons.
12. Restart the bot (`docker compose restart`). Click a button on an old card: "This card has
    expired" (private). Open a fresh card: all data is still there.
13. Player A: `/character export`. Copy the text (on mobile: long-press the message → Copy Text),
    change one characteristic, add a talent line, then `/character import` and paste it. The
    preview lists the changes; switch sections; press **Save**: the card shows the change.
14. Player A: paste text that is exactly 4000 characters long (pad it with blank lines). The
    preview warns that the end may have been cut off. Also try pasting more than 4000 characters
    and note what your Discord client does with the extra text.
15. Player A: save a long export as a `.txt` file and run `/character import` with the **file**
    option: the preview appears after a short "thinking…" message. Attach a PDF: refused.
16. Player B: `/character import member:@PlayerA` is refused. The GM's is allowed.
17. Player A: `/character roll`, type `lore` in **skill**: the list offers Lore and its
    specialisations with their ratings. Pick one, add notes and send: Player B sees the result in
    the channel, with Player A's character name and that rating as the target. Roll again with
    `test_adjustment:-20 advantage:1 sl_adjustment:1`: the target is 20 below the rating and the
    result lists the test adjustment, Advantage and SL adjustment. Player B (no character):
    `/character roll` gets a private "no character" reply and nothing is posted.
18. Apart from the roll results in step 17, nobody ever sees a message in the channel or a DM from
    the bot during any of the above.

## 11. Assumptions and limits

- The rulebook spells it **Armour**; the bot does too.
- A skill's *rating* is the sheet's **Total** column. Specialisation ratings likewise. Enter whatever
  you want the table to see; the bot does not derive totals from characteristics and advances.
- Discord forms allow five fields, so a weapon form holds Name, Damage, Range, Mag. and a
  *Traits & notes* field for specialisation, test and encumbrance; armour holds Name, Locations,
  Armour, Enc. and *Traits & notes*.
- Text import reads the bot's own text format (section 6) from a paste or a `.txt` file. It does
  not read PDFs, Word files or images of character sheets.
- `imbot/rolls.py` is a copy of the stand-alone dice bot's `rolls.py`, and `/character roll` names
  its modifiers like that bot's `/im_test`. Copy the file again after changing the rules there.
- Not included on purpose: XP/advancement, wounds, corruption, fate, influence, psychic powers,
  more than one character per member per server.
