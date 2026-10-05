# Publishing this repo

Personal-data rules for this project (enforced by [.gitignore](.gitignore)):

- `contacts.json`, `*.vcf`, `*.sqlite`, `config.json` — never committed
- `deploy-*.sh` — private deployment helpers for one specific bot host; never committed
- anything matching `*.bak.*` — never committed

## Pre-flight check (run before every push)

```bash
cd <this folder>
git init -q 2>/dev/null; git add -A
git status --short                     # should show ONLY: README.md, docs/, LICENSE,
                                       # contact_lookup.py, housecontacts.py,
                                       # house-contacts.service/.timer, install.sh,
                                       # config.example.json, .gitignore
grep -rEi "branson|thrutubing|mccubbin|propetro|tail57aebf|192\.168\.|100\1" \
     --exclude-dir=.git . || echo "CLEAN"
```

If the grep prints anything, stop and sanitize before pushing.

## Publish with the GitHub CLI

```bash
git commit -m "house-contacts: initial public release"
gh repo create house-contacts --public --source=. --push
```

(Or without `gh`: create the repo on github.com, then
`git remote add origin git@github.com:<you>/house-contacts.git && git push -u origin main`.)

## Sanity-test the published copy

```bash
git clone --depth 1 https://github.com/<you>/house-contacts /tmp/hc-test
cd /tmp/hc-test
python3 housecontacts.py import-vcf <any>.vcf        # should build cleanly
python3 contact_lookup.py "remind me to call Jane Doe tomorrow"   # lookup smoke test
```
