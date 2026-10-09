# leadscraper

Type a search key → get genuine businesses with the **owner / decision-maker
email**, verified, scored, and tiered for cold outreach.

```
python -m leadscraper "restaurants 10001 new york ny usa"
```

Built to a specific brief: find real, active businesses and a reachable
**owner / founder / CEO / MD / GM** — not a `info@` / `support@` role inbox.
100% free tooling, no paid APIs or credit card.

---

## What it does

```
search key ──► discover businesses ──► crawl each website ──► find owner + emails
          ──► classify & filter emails ──► verify (DNS/MX) ──► score & tier ──► CSV/Excel
```

1. **Discover** businesses for the query.
   - `--source google` (default): scrapes Google Maps (rich: phone, address,
     rating, reviews, website). *See the legal note below.*
   - `--source osm`: OpenStreetMap / Overpass — fully free & ToS-clean, thinner
     coverage.
2. **Enrich**: crawls the business website (`home`, `contact`, `about`, `team`,
   …) for emails, the owner's name/title, and social profiles.
3. **Classify emails** against the brief:
   - ✅ keep: `owner@` / `founder@` / `firstname@` / `firstname.lastname@` on the
     company domain.
   - ❌ reject: `info@ contact@ sales@ support@ help@ admin@ office@ hello@
     booking@ noreply@` and any shared/role inbox.
   - free mailboxes (gmail/yahoo/…) are flagged and ranked lower unless the
     address is confirmed as the owner's.
4. **Verify** deliverability for free: syntax + MX/DNS, catch-all detection, and
   (opt-in) an SMTP probe.
5. **Score & tier** by how confident we are it's a genuine business with a
   reachable owner — then **dedupe** businesses and emails.
6. **Export** `…_qualified.csv`, (optionally) `…_all.csv`, and an `.xlsx`.

### Tiers

| Tier | Meaning |
|------|---------|
| **T1** | Verified **owner/founder** email on the company domain |
| **T2** | Decision-maker / personal email on the company domain |
| **T3** | Owner email on a **free** domain, only if confirmed as the owner's |
| DISCARD | generic/role-only, invalid, permanently closed, duplicate, or unmatched |

---

## Install

```powershell
# from the project root (D:\new_tool)
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium        # only needed for --source google
```

## Usage

```powershell
# Google Maps (default)
python -m leadscraper "dentist 90210 beverly hills ca usa" --limit 60

# OpenStreetMap (free & ToS-clean)
python -m leadscraper "cafes 400050 mumbai india" --source osm

# Deeper email verification (SMTP probe; port 25 must be open outbound)
python -m leadscraper "law firm 60601 chicago il usa" --verify-smtp

# Keep the full dump including DISCARD rows
python -m leadscraper "gyms 33139 miami fl usa" --include-discarded
```

### Key options

| Flag | Default | Notes |
|------|---------|-------|
| `--source {google,osm}` | `google` | business discovery backend |
| `--limit N` | `40` | max businesses |
| `--concurrency N` | `8` | parallel website workers |
| `--max-pages N` | `6` | pages crawled per website |
| `--timeout S` | `15` | per-request HTTP timeout |
| `--headless / --no-headless` | headless | show the browser (debugging) |
| `--respect-robots / --no-respect-robots` | on | honour `robots.txt` |
| `--verify-smtp` | off | SMTP deliverability probe + catch-all |
| `--include-discarded` | off | also write the full `_all.csv` + `All` sheet |

Output lands in `./output/` (override with `--out`).

---

## Getting more / better owner emails

Owner emails live on the **website**, so results depend on the niche:

- **Local service businesses** (dentists, law firms, agencies, contractors,
  clinics, salons, real-estate) list owners/principals far more often than
  chain restaurants — expect more T1/T2 there.
- Raise `--limit` and `--max-pages` to crawl more.
- Turn on `--verify-smtp` where port 25 is reachable to promote `mx_ok` → a
  confirmed `valid` (sets `email_verified`).
- Tune the rules in `leadscraper/config.py` (role-inbox blocklist, free-domain
  list, titles, and `ScoreWeights`).

## How scoring works

All weights are in `leadscraper/config.py → ScoreWeights`. The score (0–100)
rewards: owner identified, a non-generic email on the company domain mapped to
the owner, deliverability, a working website, a real Maps presence, owner
socials, data completeness, and location match. It penalises: permanently
closed, invalid/catch-all/free-unconfirmed emails, generic-only inboxes, and
location mismatch.

## Project layout

```
leadscraper/
  cli.py            # command line + Rich UI
  pipeline.py       # discover → enrich → verify → score → dedupe
  query.py          # parse "restaurants 10001 new york ny usa"
  config.py         # blocklists, free domains, titles, score weights
  models.py         # Lead / EmailCandidate
  sources/          # google_maps.py (Playwright) · osm.py (Overpass)
  enrich/           # website.py · emails.py · people.py · social.py
  verify/           # email_verify.py (syntax · MX · SMTP · catch-all)
  scoring/          # scorer.py (score + tier)
  output.py         # CSV + Excel
```

---

## ⚖️ Legal & ethical note

- **Google Maps** scraping violates Google's Terms of Service and the page has
  anti-bot measures; selectors can break without warning. Use `--source osm`
  for a free, ToS-clean alternative. You are responsible for how you use the
  `google` source.
- Respect each website's `robots.txt` (on by default) and rate limits.
- Scraped contacts are **personal data**. Comply with outreach / privacy law
  before contacting anyone — e.g. CAN-SPAM (US), CASL (Canada), GDPR / ePrivacy
  (EU/UK), and local rules. Honour opt-outs.
