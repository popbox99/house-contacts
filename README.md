# house-contacts

Give a chat/voice bot access to your real contacts — feed it a `contacts.json` built from
**whichever contacts storage you already use**, and it can attach phone numbers and emails
to tasks, reminders, and events like *"remind me to call Dana Reyes tomorrow at 3pm"* —
and answer *"what is Dana's phone number?"* and *"what is her email?"* follow-ups.

```text
call dana reyes 📇 cell: +1 555-0137 · email: d.reyes@example.com
```

Two halves:

| Piece | Runs on | What it does |
|---|---|---|
| [`housecontacts.py`](housecontacts.py) | any machine with your contacts | builds `contacts.json` from vCard exports and/or a local Thunderbird profile |
| [`contact_lookup.py`](contact_lookup.py) | your bot's host | fuzzy name matching, text enrichment, direct contact Q&A |

The two machines talk to each other however you like — Syncthing, rsync over SSH/Tailscale,
a shared folder. One file, plain JSON.

## Quickstart

### A. Import a vCard file (any contacts provider)

All of these export `.vcf`:

- **Google Contacts** — contacts.google.com → Export → vCard, or a
  [Takeout](https://takeout.google.com) export (`Contacts/*.vcf`)
- **iCloud** — icloud.com → Contacts → select all → Export vCard
- **Outlook** — People → Manage → Export contacts (choose vCard if offered)
- **Nextcloud / any CardDAV server** — download the address book as `.vcf`

Then:

```bash
python3 housecontacts.py import-vcf ~/Downloads/contacts.vcf
# -> registered + built (see output for the output path)
```

Re-run `import-vcf` any time you re-export; `build` merges everything and dedupes.

### B. Thunderbird auto-export (no manual exports, stays fresh)

```bash
python3 housecontacts.py export-thunderbird
```

Reads every `abook*.sqlite` in your Thunderbird profile — on Linux, macOS, or Windows —
including CardDAV-cached address books (Google, Nextcloud…), so the export stays current
as long as Thunderbird runs.

### Keep it fresh (scheduling)

- **Linux**: `bash install.sh` installs a systemd user timer (every 2 hours)
- **macOS**: a launchd job or cron running `housecontacts.py build` periodically
- **Windows**: a Task Scheduler job running `python housecontacts.py build`

## Bot integration

Copy `contact_lookup.py` next to your bot's code. Then:

```python
from contact_lookup import attach_contact_info, contact_find, contact_format, extract_call_target

# 1) Enrich call/text/email tasks, reminders, events before persisting:
text, contact, ambiguous = attach_contact_info(arg)
if ambiguous:
    return "Which one? " + " · ".join(c["name"] for c in ambiguous)

# 2) Answer "what is dana's phone number" / follow-ups like "what is her email":
name = extract_call_target(text)          # or your own name extraction
contact, kind, candidates = contact_find(name)
reply = contact_format(contact)
```

Behavior: `attach_contact_info` fires only on call/text/email phrasing — everything else
passes through untouched. Match tiers: exact name → nickname → swapped first/last →
unique last name → unique first name → substring. Ambiguous short names ask instead of
guessing. If `contact_lookup.py` or the JSON is missing, features silently disable
themselves — your bot never crashes over contacts.

Set `HOUSE_CONTACTS_JSON=/path/to/contacts.json` if your bot reads the file from somewhere
other than the default locations. The lookup caches by mtime, so rebuilds need no restart.

## Seeing tasks & calendars on your phone

The bot-generated VTODOs/VEVENTs live on any CalDAV server (Radicale, Nextcloud, iCloud…):

- **Android** → [docs/CALDAV-ANDROID.md](docs/CALDAV-ANDROID.md) — DAVx⁵ + Tasks.org setup
- **iPhone** → [docs/APPLE-IPHONE.md](docs/APPLE-IPHONE.md) — native CalDAV events,
  the VTODO limitation, and workarounds

## Configuration

`~/.config/house-contacts/config.json` (see [`config.example.json`](config.example.json)):

```json
{
  "out_path": "~/.local/share/house-contacts/contacts.json",
  "sources": [
    {"type": "thunderbird"},
    {"type": "vcf", "path": "~/.local/share/house-contacts/sources/google-contacts.vcf"}
  ]
}
```

Any number of sources; output is merged and deduped (same name + phone/email across
accounts collapses into one card with unioned fields).

**Google email-only cards** get consolidated too: Google Contacts often stores an email
entered without a full contact as a separate card whose *name is the address itself*
(`d.reyes@example.com`). Those merge into the named contact holding the same address,
or — when the named contact has no email yet — by unique local-part match
(`dreyes` ≈ Dana Reyes, `dana.reyes` ≈ Dana Reyes). Ambiguous matches are left alone.

## Privacy

- The JSON contains **only**: name, nickname, org, title, phones, emails.
- `contacts.json` and `.vcf` files are personal data — keep them out of any repo
  (see [.gitignore](.gitignore)) and share them only over transports you trust.

## Platform support

| Piece | Linux | macOS | Windows |
|---|---|---|---|
| `import-vcf` / `build` (the core) | ✓ | ✓ | ✓ |
| Thunderbird auto-export | ✓ | ✓ | ✓ (detects `%APPDATA%\Thunderbird`) |
| `contact_lookup.py` in your bot | ✓ | ✓ | ✓ |
| Scheduling | systemd timer (included) | launchd / cron | Task Scheduler |
| `install.sh` | ✓ | ✓ | run Python directly |

Everything is Python stdlib — no dependencies on any platform.

## CLI reference

```
housecontacts.py import-vcf FILE...      register .vcf file(s) as a source + build
housecontacts.py export-thunderbird      register local Thunderbird books + build
housecontacts.py build                   rebuild from all configured sources
housecontacts.py sources                 show config and registered sources
contact_lookup.py "remind me to call Dana Reyes tomorrow at 5"   # test enrichment
```
