# SEO Meta Automation

Automation that, for each keyword in a Google Sheet, analyses the Google SERP for
the given GEO, scrapes the top affiliate casino-review competitors, generates
optimized meta (`H1`, `Meta Title`, `Meta Description`) in the requested language
under strict rules, writes a structured Google Doc, shares it with **Commenter**
rights, and writes the doc link back into the sheet.

---

## Architecture

The code is split by responsibility

```
main.py            Orchestrator: per-row pipeline + per-row error isolation
config.py          Env/secrets loading + the content rules from the brief
models.py          Dataclasses passed between stages
sheets_client.py   Google Sheets read (pending rows) / write (Result column)
serp_client.py     Google SERP via serper.dev (geo-aware, no direct scraping)
affiliate_filter.py LLM classifies top-10 → first 3 affiliate review sites
scraper.py         Fault-tolerant H1/Title/Meta/structure scraping
ai_generator.py    Gemini prompt + programmatic rule validation + retry
docs_client.py     Builds the structured Google Doc + Commenter sharing
```

### Pipeline (per row)

1. **Read** rows from the sheet where `Result` is empty.
2. **SERP** — query `serper.dev` with `gl = GEO` to get the top-10 organic results.
   We use a SERP API instead of scraping `google.com` directly to avoid CAPTCHAs
   and IP blocks.
3. **Select competitors** — an LLM classifies each top-10 result as an
   *affiliate/review* site vs. operator brand / news / social, and we keep the
   first 3 **strictly within the top-10**, preserving SERP order. For brand
   keywords whose SERP is dominated by the operator's own pages, a fallback tops
   up with the remaining non-official, non-junk results (deduped by domain) so
   the report still contains competitors; if the SERP genuinely has no affiliate
   sites, we keep fewer and note why.
4. **Scrape** each selected site for `H1`, `Meta Title`, `Meta Description`, its
   SERP position and an H2/H3 structure outline. Every fetch is wrapped so a
   blocked/slow site is recorded as a failure with a reason rather than crashing.
5. **Generate meta** with Gemini in the row's `Language`.
6. **Create Google Doc** named `{Keyword}-{GEO}`, share as Commenter (anyone with
   the link), and write the URL into the sheet's `Result` column.

### Parsing logic

- SERP results come as JSON from serper.dev (`organic[*].link/title/snippet`).
- Per page we parse with BeautifulSoup: `<title>`, `<meta name="description">`,
the first `<h1>`, and up to 25 `<h2>/<h3>` headings as the "site structure".
- **Fault tolerance** (brief §2): HTTP errors, timeouts, parse errors and
"no meta found" (JS-rendered/blocked) are all captured as a `failure_reason`.
If fewer than 3 affiliate sites can be collected within the top-10, we stop at
what we found and record the reasons in the doc's **Notes** section.

### Generation logic

The rules are enforced **twice**:

1. The prompt states every rule explicitly (keyword-first, no emoji, banned stop
   words, anti-template/bonus-payout focus, length limits, capitalization, output
   language).
2. `ai_generator.validate()` re-checks the output mechanically — keyword-first,
   Title 40–60 chars, Description < 160 chars, no stop words, no emoji. If a rule
   is broken the violations are fed back to the model and it retries (up to 4×).

---

## Setup

### 1. Google Cloud / service account

1. Create a Google Cloud project and **enable**: Google Sheets API, Google Docs
   API, Google Drive API.
2. Create a **service account** and download its JSON key as
   `service_account.json` in the project root.
3. **Share the input spreadsheet** with the service account's email
   (`...@...iam.gserviceaccount.com`) as **Editor** so it can read rows and write
   the `Result` column.


### 2. The spreadsheet

Create a Google Sheet with a header row containing exactly these columns:

| Keyword | GEO | Language | Result |
|---------|-----|----------|--------|
| casino en ligne | FR | fr | |
| aviator | FR | fr | |
| 1win | IN | en | |


### 3. API keys

- **serper.dev**
- **Google Gemini**

### 4. Environment

```bash
python3 -m venv .venv 
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env

---

## Run

```bash
python main.py
```

---


## Self-contained / autonomy

A single command `python main.py` runs the full cycle for all pending rows with
no manual steps