# Imperium Maledictum character bot

A Discord bot for play-by-post **Warhammer 40,000 Roleplay: Imperium Maledictum** games.
Right-click a server member, pick **Apps → View Character**, and you get that member's character
card. The card is private: only you see it, and it is never posted to the channel or sent by DM.

Every card has four sections: **Characteristics**, **Skills**, **Talents** and **Equipment**
(Weapons, Armour and Other Equipment). Players create and edit their own character with slash
commands, buttons, menus and forms. A configurable GM role (and server administrators) can edit
everyone's characters.

Field names follow the official Cubicle 7 character sheet. The bot stores what you type; it does
not calculate, roll dice or track advancement.

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
   Leave every bot permission unticked: the bot only answers interactions privately, so it needs no
   channel permissions. Copy the generated URL. It looks like:

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
**Apps → View Character**. Type `/character` in a channel and the `view`, `edit`, `create` and
`delete` subcommands should be offered. Administrators also see `/setup gm-role`.

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

### Delete a character

```
/character delete
```

Asks for confirmation. GMs and administrators may add `member:@Player`.

### Who can do what

| Action | Owner | GM role | Administrator | Others |
|---|---|---|---|---|
| View any character on the server | ✓ | ✓ | ✓ | ✓ |
| Create / edit / delete own character | ✓ | ✓ | ✓ | ✓ |
| Create / edit / delete another member's character | – | ✓ | ✓ | – |
| `/setup gm-role` | – | – | ✓ | – |

Permissions are checked on the server for every command, button, menu choice and form submission,
not just when the buttons are drawn. If a GM loses the role while a form is open, the submission
is refused.

### Privacy and expiry

Everything the bot says is an *ephemeral* Discord response: visible only to the person who
clicked, never in the channel history, never a DM. A card belongs to the member who opened it. It
stays interactive for 10 minutes after the last click; then its buttons are disabled and the card
says how to reopen it (Apps → View Character or `/character view`). After a bot restart or update,
buttons on older cards reply "This card has expired" instead; just open a new card. A form left
open for more than 30 minutes, or across a restart, cannot be submitted; reopen the card and redo
the change. The delete confirmation expires after two minutes.

If two people edit the same character at once, the second save is refused with a notice and the
card refreshes to the latest version, so nobody silently overwrites anybody.

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

## 8. Importing characters later (for developers)

The future import source is undecided (spreadsheet, PDF, paper transcription…). The bot therefore
exposes one internal entry point and nothing else: no parsers, uploads or endpoints.

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
the same validation and authorisation; long sheets and empty sections stay within Discord's
limits; and the command and component payloads sent to Discord are within its limits.

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
13. Nobody ever sees a message in the channel or a DM from the bot during any of the above.

## 11. Assumptions and limits

- The rulebook spells it **Armour**; the bot does too.
- A skill's *rating* is the sheet's **Total** column. Specialisation ratings likewise. Enter whatever
  you want the table to see; the bot does not derive totals from characteristics and advances.
- Discord forms allow five fields, so a weapon form holds Name, Damage, Range, Mag. and a
  *Traits & notes* field for specialisation, test and encumbrance; armour holds Name, Locations,
  Armour, Enc. and *Traits & notes*.
- Not included on purpose: dice rolling, XP/advancement, wounds, corruption, fate, influence,
  psychic powers, file imports, more than one character per member per server.
