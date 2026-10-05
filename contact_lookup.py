#!/usr/bin/env python3
"""Contact lookup for a chat/voice bot.

Reads contacts.json (built by housecontacts.py on any machine that has your
contacts, then transported however you like — Syncthing, rsync, a shared folder)
and attaches a person's contact info to call/text/email tasks, reminders, and events.

Usage inside your bot:

    from contact_lookup import attach_contact_info, format_contact

    enriched, contact, ambiguous = attach_contact_info(arg)
    # enriched  = original text with a contact block appended (or unchanged)
    # contact  = the matched contact dict, or None
    # ambiguous = list of candidate contacts when the name matched more than
    #             one person (bot can ask which one)

Stdlib only. Caches the JSON by mtime so per-message lookups are ~free.
"""

import json
import os
import re
import unicodedata

_DEFAULT_CANDIDATES = [
    os.environ.get("HOUSE_CONTACTS_JSON"),
    "/tank/data/house/contacts.json",
    os.path.expanduser("~/Documents/house/contacts.json"),
    os.path.expanduser("~/.local/share/house-contacts/contacts.json"),
]

def _default_contacts_path():
    for p in _DEFAULT_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return os.path.expanduser("~/.local/share/house-contacts/contacts.json")

CONTACTS_PATH = os.environ.get("HOUSE_CONTACTS_JSON") or _default_contacts_path()

_cache = {"mtime": None, "contacts": []}

# Words that end a person's name in phrases like "call Dana Reyes tomorrow at 5"
_FILLER = re.compile(
    r"\s+\b(about|tomorrow|today|tonight|later|asap|now|soon|when|while|because|"
    r"and|then|at|on|in|after|before|next|this|if|so|to)\b.*$",
    re.IGNORECASE,
)

# "call|text|email|message <name>" — up to 4 name tokens after the verb
_TARGET_RE = re.compile(
    r"(?i)\b(call|text|txt|e-?mail|message|msg|ring|phone)\b\s+(?:to\s+|up\s+)?"
    r"([A-Za-z][\w'’.\-]+(?:\s+[A-Za-z][\w'’.\-]+){0,3})"
)


def load_contacts(path: str = None):
    path = path or CONTACTS_PATH
    try:
        mtime = os.path.getmtime(path)
        if _cache["mtime"] != mtime:
            with open(path) as f:
                data = json.load(f)
            contacts = data["contacts"] if isinstance(data, dict) else data
            _cache["mtime"], _cache["contacts"] = mtime, contacts
        return _cache["contacts"]
    except (OSError, ValueError, KeyError):
        return _cache["contacts"]  # stale on read error; better than nothing


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


_NOUN_VERBS = {"number", "address", "info", "details", "me", "up", "back"}

def extract_call_target(text: str):
    """Pull the person's name out of 'remind me to call Dana Reyes tomorrow'.
    Rejects noun-uses like 'what is Dana's phone number' ("phone" matches as a
    verb but "number" is not a person)."""
    m = _TARGET_RE.search(text or "")
    if not m:
        return None
    verb = m.group(1).lower()
    name = m.group(2)
    name = _FILLER.sub("", name).strip()
    # drop dangling single-letter/garbage tokens
    name = re.sub(r"\s+\b[a-z]\b$", "", name, flags=re.IGNORECASE).strip()
    if not name or name.lower() in _NOUN_VERBS:
        return None
    if verb == "phone" and re.match(r"(?:number|address|info)", name, re.I):
        return None
    return name or None


def find_contact(query: str, contacts=None):
    """Tiered matcher. Returns (contact|None, kind|None, ambiguous_candidates)."""
    if not query:
        return None, None, []
    contacts = contacts if contacts is not None else load_contacts()
    q = _norm(query)
    ql = " ".join(q)

    # 1. exact full name
    exact = [c for c in contacts if " ".join(_norm(c["name"])) == ql]
    if len(exact) == 1:
        return exact[0], "exact", []
    # 2. nickname
    nick = [c for c in contacts if c.get("nickname") and " ".join(_norm(c["nickname"])) == ql]
    if len(nick) == 1:
        return nick[0], "nickname", []
    # 3. swapped first/last ("reyes dana")
    swapped = [c for c in contacts if " ".join(_norm(c["name"])[::-1]) == ql]
    if len(swapped) == 1:
        return swapped[0], "swapped", []
    # 4. unique last name
    last = [c for c in contacts if len(_norm(c["name"])) > 1 and _norm(c["name"])[-1] == ql]
    if len(last) == 1:
        return last[0], "last-name", []
    # 5. unique first name
    first = [c for c in contacts if len(_norm(c["name"])) > 1 and _norm(c["name"])[0] == ql]
    if len(first) == 1:
        return first[0], "first-name", []
    # 6. substring / contained-in (handles "Dover Logistics - Dana Reyes" queried as "dana reyes")
    # Both sides need >=3 chars, or one-letter/short card names ("S", "CC") hijack
    # every query via the reversed direction ("s" is inside everything).
    contains = []
    if len(ql) >= 3:
        for c in contacts:
            nn = " ".join(_norm(c["name"]))
            if len(nn) >= 3 and (ql in nn or nn in ql):
                contains.append(c)
    if len(contains) == 1:
        return contains[0], "substring", []
    # ambiguous or no match
    candidates = (exact + nick + swapped + last + first + contains)[:5]
    return None, None, candidates


def format_contact(c: dict) -> str:
    bits = []
    if c.get("org"):
        role = c["org"]
        if c.get("title"):
            role += f", {c['title']}"
        bits.append(role)
    for p in c.get("phones", [])[:3]:
        label = p.get("type", "other").replace(",pref", "").replace("pref", "phone") or "phone"
        bits.append(f"{label}: {p['number']}")
    for e in c.get("emails", [])[:2]:
        bits.append(f"email: {e}")
    return f"{c['name']}" + (" — " + " · ".join(bits) if bits else " (no contact info on file)")


def attach_contact_info(text: str, contacts=None):
    """Main entry: enrich call/text/email phrasing with the person's info.

    Returns (enriched_text, contact_or_None, ambiguous_or_None).
    """
    name = extract_call_target(text)
    if not name:
        return text, None, None
    contact, kind, candidates = find_contact(name, contacts)
    if contact:
        block = format_contact(contact)
        # avoid repeating the name when it's already in the phrase
        if contact["name"].lower() in text.lower() and " — " in block:
            block = block.split(" — ", 1)[1]
        note = f" [contact:{kind}]" if os.environ.get("HOUSE_CONTACTS_DEBUG") else ""
        # single line — this text can end up in an ICS SUMMARY field
        return f"{text} 📇 {block}{note}", contact, None
    if candidates:
        return text, None, candidates
    return text, None, None


if __name__ == "__main__":
    # CLI sanity check:  python3 contact_lookup.py "remind me to call Dana Reyes tomorrow"
    import sys

    t = " ".join(sys.argv[1:]) or "remind me to call Dana Reyes tomorrow at 5"
    enriched, c, amb = attach_contact_info(t)
    print("target :", extract_call_target(t))
    if c:
        print("match  :", c["name"])
    elif amb:
        print("ambiguous:", [x["name"] for x in amb])
    print("result :", enriched)
