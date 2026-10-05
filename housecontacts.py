#!/usr/bin/env python3
"""housecontacts — build contacts.json for a chat/voice bot from any contact source.

Sources:
  * vCard (.vcf) files — what Google Contacts (Takeout), iCloud, Outlook,
    Nextcloud, and any CardDAV server can export
  * an auto-detected local Thunderbird profile (CardDAV-cached books included)

Usage:
  housecontacts import-vcf FILE [FILE ...]   # register .vcf file(s) as a source + build
  housecontacts export-thunderbird           # register local Thunderbird books + build
  housecontacts build                        # rebuild contacts.json from all sources
  housecontacts sources                      # list registered sources

Output is privacy-minimal: name, nickname, org, title, phones, emails. Nothing else.

Configuration (optional): ~/.config/house-contacts/config.json
  {
    "out_path": "~/Documents/house/contacts.json",
    "sources": [
      {"type": "thunderbird"},
      {"type": "vcf", "path": "~/.local/share/house-contacts/sources/google.vcf"}
    ]
  }

Stdlib only.
"""

import argparse
import glob
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time

CONFIG_PATH = os.environ.get(
    "HOUSE_CONTACTS_CONFIG", os.path.expanduser("~/.config/house-contacts/config.json")
)
SOURCES_DIR = os.path.expanduser("~/.local/share/house-contacts/sources")

DEFAULT_CONFIG = {
    "out_path": "~/house-contacts/contacts.json",
    "sources": [{"type": "thunderbird"}],
}

_SKIP_PROPS = {"PHOTO", "LOGO", "SOUND", "KEY", "BDAY", "ANNIVERSARY", "URL", "ADR", "NOTE"}


# --------------------------------------------------------------------------- vCard

def _unfold(block: str) -> str:
    """RFC6350 unfolding: newline + space/tab continues the previous line."""
    return re.sub(r"\r?\n[ \t]", "", block)


def _decode_qp(value: str) -> str:
    """Quoted-printable (vCard 2.1, Outlook-style) values, UTF-8 aware."""
    if "=" not in value:
        return value
    try:
        raw = re.sub(r"=\r?\n", "", value)  # soft line breaks
        out = bytearray()
        i = 0
        while i < len(raw):
            if raw[i] == "=" and i + 2 < len(raw) + 1:
                try:
                    out.append(int(raw[i + 1 : i + 3], 16))
                    i += 3
                    continue
                except ValueError:
                    pass
            out.extend(raw[i].encode("utf-8"))
            i += 1
        return out.decode("utf-8", errors="replace")
    except Exception:
        return value


def _param_types(params):
    """Extract TYPE-ish tokens from v2.1 bare params and v3/v4 TYPE= lists."""
    types = []
    for p in params:
        k, _, v = p.partition("=")
        ku = k.upper()
        if not v:
            if ku in ("ENCODING", "CHARSET", "VALUE"):
                continue
            types.append(ku.lower())
        elif ku == "TYPE":
            types.extend(t.strip('"').lower() for t in v.split(","))
        # other keyed params (ENCODING=, CHARSET=, PREF=1, MEDIATYPE=...) ignored
    out = []
    for t in types:
        if t and t not in out and t != "pref" or t == "pref":
            if t not in out:
                out.append(t)
    return out


def parse_vcard(card: str):
    """One unfolded BEGIN..END VCARD block -> record dict (or None)."""
    props, tels, emails, n_name = {}, [], [], None
    for line in _unfold(card).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        head, _, value = line.partition(":")
        parts = head.split(";")
        name = re.sub(r"^item\d+\.", "", parts[0], flags=re.I).upper()
        params = parts[1:]
        value = value.strip()
        upper_head = head.upper()
        if "QUOTED-PRINTABLE" in upper_head:
            value = _decode_qp(value)
        if "BASE64" in upper_head or name in _SKIP_PROPS:
            continue
        value = re.sub(r"\\([,;\\nN])", lambda m: "\n" if m.group(1).lower() == "n" else m.group(1), value)
        if name == "TEL" and value:
            value = re.sub(r"^tel:", "", value, flags=re.I)
            tels.append({"type": ",".join(_param_types(params)) or "other", "number": value})
        elif name == "EMAIL" and value:
            value = re.sub(r"^mailto:", "", value, flags=re.I)
            if value not in emails:
                emails.append(value)
        elif name in ("FN", "NICKNAME", "ORG", "TITLE") and value:
            props.setdefault(name, value)
        elif name == "N" and value and n_name is None:
            # N:Last;First;Middle;Prefix;Suffix  ->  "First Last"
            bits = [b.strip() for b in value.split(";")]
            n_name = " ".join(b for b in [bits[1] if len(bits) > 1 else "", bits[0]] if b) or None
    name = props.get("FN") or n_name or ""
    if not name:
        return None
    return {
        "name": name,
        "nickname": props.get("NICKNAME", ""),
        "org": props.get("ORG", "").rstrip(","),
        "title": props.get("TITLE", ""),
        "phones": tels,
        "emails": emails,
    }


def load_vcf(path: str):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    records = []
    for block in re.findall(r"BEGIN:VCARD.*?END:VCARD", text, re.S | re.I):
        rec = parse_vcard(block)
        if rec:
            records.append(rec)
    return records


# ------------------------------------------------------------------- Thunderbird

def _thunderbird_globs():
    """Profile locations per OS (Linux / macOS / Windows)."""
    home = os.path.expanduser("~")
    bases = [
        os.path.join(home, ".thunderbird"),                       # Linux
        os.path.join(home, "Library", "Thunderbird"),             # macOS
        os.path.join(home, "AppData", "Roaming", "Thunderbird"),  # Windows
    ]
    if os.environ.get("APPDATA"):                                 # Windows w/ APPDATA set
        bases.insert(0, os.path.join(os.environ["APPDATA"], "Thunderbird"))
    return [os.path.join(b, "*", "abook*.sqlite") for b in bases]


def load_thunderbird():
    dbs = []
    for pattern in _thunderbird_globs():
        dbs.extend(sorted(glob.glob(pattern)))
    dbs = sorted(set(os.path.normpath(d) for d in dbs))  # dedupe across OS paths
    records = []
    for db in dbs:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                snap = os.path.join(tmp, "abook.sqlite")
                shutil.copy2(db, snap)
                con = sqlite3.connect(snap)
                try:
                    rows = con.execute(
                        "SELECT card, value FROM properties WHERE name='_vCard'"
                    ).fetchall()
                finally:
                    con.close()
            for _card, vc in rows:
                rec = parse_vcard(vc)
                if rec:
                    records.append(rec)
        except sqlite3.Error as e:
            print(f"WARN: skipping {db}: {e}", file=sys.stderr)
    return records


# ------------------------------------------------------------------------ merging

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _merge_key(c):
    phone = _digits(c["phones"][0]["number"])[-10:] if c["phones"] else ""
    email = c["emails"][0].lower() if c["emails"] else ""
    return (c["name"].lower().strip(), phone, email)


_EMAIL_NAME_RE = re.compile(r"^[\w.+-]+@[\w.-]+\.[a-z]{2,}$", re.I)


def consolidate(contacts):
    """Google-style email-only cards (name == the email address itself) get merged
    into the named card holding that same address, then dropped. Keeps lookups of
    'Dana Reyes' from missing the email that Google stored as its own card."""
    email_index = {}
    for c in contacts:
        if _EMAIL_NAME_RE.match(c["name"]):
            continue
        for e in c["emails"]:
            email_index.setdefault(e.lower(), c)
    drop = set()
    for c in contacts:
        if not _EMAIL_NAME_RE.match(c["name"]):
            continue
        target = None
        for email in c["emails"]:
            t = email_index.get(email.lower())
            if t is not None and t is not c:
                target = t
                break
        if target is None:
            continue  # keep genuinely address-only entries
        for e in c["emails"]:
            if e.lower() not in {x.lower() for x in target["emails"]}:
                target["emails"].append(e)
        for p in c["phones"]:
            if _digits(p["number"]) not in {_digits(q["number"]) for q in target["phones"]}:
                target["phones"].append(p)
        for field in ("nickname", "org", "title"):
            if not target[field] and c[field]:
                target[field] = c[field]
        drop.add(id(c))

    # Second chance: email-only cards whose local part matches a named contact
    # with no email yet — "dreyes@x.com" ~ "Dana Reyes" (initial+last),
    # "dana.reyes@x.com" ~ "Dana Reyes" (first+last). Unique match only.
    by_key = {}
    for c in contacts:
        if id(c) in drop or _EMAIL_NAME_RE.match(c["name"]):
            continue
        tokens = [t for t in re.split(r"[^a-z]+", c["name"].lower()) if t]
        if len(tokens) >= 2:
            first, last = tokens[0], tokens[-1]
            by_key.setdefault(first[0] + last, []).append(c)
            by_key.setdefault(first + last, []).append(c)
    for c in contacts:
        if id(c) in drop or not _EMAIL_NAME_RE.match(c["name"]):
            continue
        local = re.sub(r"[._\-\d]", "", c["name"].split("@")[0]).lower()
        candidates = by_key.get(local, [])
        if len(candidates) != 1:
            continue
        target = candidates[0]
        for e in c["emails"]:
            if e.lower() not in {x.lower() for x in target["emails"]}:
                target["emails"].append(e)
        for p in c["phones"]:
            if _digits(p["number"]) not in {_digits(q["number"]) for q in target["phones"]}:
                target["phones"].append(p)
        drop.add(id(c))
    return [c for c in contacts if id(c) not in drop]


def merge(records):
    """Union duplicate cards across sources; keep the richest field set."""
    merged = {}
    for c in records:
        key = _merge_key(c)
        if key not in merged:
            merged[key] = c
            continue
        m = merged[key]
        for field in ("nickname", "org", "title"):
            if not m[field] and c[field]:
                m[field] = c[field]
        for p in c["phones"]:
            if _digits(p["number"]) not in {_digits(q["number"]) for q in m["phones"]}:
                m["phones"].append(p)
        for e in c["emails"]:
            if e.lower() not in {x.lower() for x in m["emails"]}:
                m["emails"].append(e)
    return sorted(merged.values(), key=lambda c: c["name"].lower())


# ------------------------------------------------------------------- config / IO

def load_config():
    path = CONFIG_PATH
    if os.path.exists(path):
        with open(path) as f:
            cfg = json.load(f)
    else:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(cfg, f, indent=2)
    cfg.setdefault("sources", list(DEFAULT_CONFIG["sources"]))
    cfg.setdefault("out_path", DEFAULT_CONFIG["out_path"])
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def build(cfg, quiet=False):
    records = []
    for src in cfg["sources"]:
        stype = src.get("type")
        try:
            if stype == "thunderbird":
                recs = load_thunderbird()
            elif stype == "vcf":
                path = os.path.expanduser(src["path"])
                recs = load_vcf(path) if os.path.exists(path) else []
                if not os.path.exists(path):
                    print(f"WARN: vcf source missing: {path}", file=sys.stderr)
            else:
                print(f"WARN: unknown source type {stype!r}", file=sys.stderr)
                recs = []
        except Exception as e:
            print(f"WARN: source {src} failed: {e}", file=sys.stderr)
            recs = []
        records.extend(recs)
        if not quiet:
            print(f"  {stype}: {len(recs)} cards")
    contacts = consolidate(merge(records))
    out = os.path.expanduser(cfg["out_path"])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    payload = {
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "count": len(contacts),
        "contacts": contacts,
    }
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=1)
    os.replace(tmp, out)  # atomic — readers never see a half file
    print(f"built {len(contacts)} contacts ({len(records)} raw) -> {out}")
    return out


# --------------------------------------------------------------------------- CLI

def cmd_import_vcf(args):
    cfg = load_config()
    os.makedirs(SOURCES_DIR, exist_ok=True)
    for f in args.files:
        src_path = os.path.abspath(os.path.expanduser(f))
        if not os.path.exists(src_path):
            sys.exit(f"not found: {src_path}")
        dest = os.path.join(SOURCES_DIR, os.path.basename(src_path))
        shutil.copy2(src_path, dest)
        entry = {"type": "vcf", "path": dest}
        if entry not in cfg["sources"]:
            cfg["sources"].append(entry)
        print(f"registered {dest}")
    save_config(cfg)
    build(cfg)


def cmd_export_thunderbird(args):
    cfg = load_config()
    if not any(s.get("type") == "thunderbird" for s in cfg["sources"]):
        cfg["sources"].insert(0, {"type": "thunderbird"})
        save_config(cfg)
    build(cfg)


def cmd_build(args):
    build(load_config())


def cmd_sources(args):
    cfg = load_config()
    print(f"config : {CONFIG_PATH}")
    print(f"output : {cfg['out_path']}")
    for s in cfg["sources"]:
        print(f"source : {s}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import-vcf", help="register .vcf file(s) as a contact source and build")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_import_vcf)
    p = sub.add_parser("export-thunderbird", help="use the local Thunderbird profile as a source and build")
    p.set_defaults(func=cmd_export_thunderbird)
    p = sub.add_parser("build", help="rebuild contacts.json from all configured sources")
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("sources", help="show config and registered sources")
    p.set_defaults(func=cmd_sources)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
