# CalDAV on Android — calendars, tasks & contacts

If your bot (or any tool) writes **VEVENTs** (calendar events) and **VTODOs** (tasks)
to a CalDAV server — Radicale, Nextcloud, iCloud, Fastmail, etc. — Android can sync all
of it natively. Three apps do the work:

| App | What it syncs | Where |
|---|---|---|
| **DAVx⁵** | Calendars (events) + CardDAV contacts — the sync engine | Play Store / F-Droid |
| **Tasks.org** (open-source "Tasks") | VTODO task lists, via DAVx⁵ | Play Store / F-Droid |
| **ICSx⁵** | Read-only .ics subscriptions (any calendar URL) | Play Store / F-Droid |

## Setup

1. **Install DAVx⁵** and open it.
2. **+** → *Enter URL or search* — give it your CalDAV base URL, username, and password
   (for Radicale that's typically `https://your-server/user/`; Nextcloud users can just
   paste the server root).
3. Grant DAVx⁵ calendar + contacts permissions when asked.
4. Pick which **calendars** (VEVENT collections) and **address books** (CardDAV) to sync.
   Tasks (VTODO collections) are handled by the task app, not DAVx⁵ alone.
5. **Install Tasks.org** → open → it will offer to connect to DAVx⁵ → enable your
   VTODO list(s). Tasks now appear in the Tasks app *and* most Android calendar widgets.
6. Optionally **ICSx⁵** for any read-only `.ics` URL (league schedules, holidays…).

## What you get

- Bot-created calendar events → native Android calendar (two-way edit)
- Bot-created tasks/reminders (VTODOs) → Tasks.org, with completion syncing **back**
  to the server (check one off on your phone, it's checked everywhere)
- Contacts (if your server exposes CardDAV) → native Android contacts app

## Notes

- **Work profile / battery**: disable battery optimization for DAVx⁵ or syncs can stall.
- **Self-signed certs**: DAVx⁵ can trust a custom CA, or use your Tailscale/Wireguard
  network so HTTPS comes from a real CA.
- **iOS?** Apple handles this differently — see [APPLE-IPHONE.md](APPLE-IPHONE.md).
