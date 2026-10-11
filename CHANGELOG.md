# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.9.0] - Phase 5: Discovery quality + keyword shortlist tightening

### Added
- `analyzers/brand_filter.py` — structural brand detection. Camel case, acronyms,
  digit-mixed tokens, single-word names and colon-separated leading names are
  treated as brand tokens, plus a small stoplist of common platform brands.
  Brand tokens are stripped from keyword subjects, so `monica all one
  summarizer` and `shippedit me analyzer` can no longer be generated while
  `video summarizer`, `ai detector` and `prompt generator` stay.
- Keyword **maturity**: `NICHE` / `BROAD` / `BRAND` / `AWKWARD`. BRAND and
  AWKWARD are never generated, never scored and never listed.
- Search-intent anchors: a candidate must carry a category anchor **and** a
  functional anchor; when a cluster has no specific domain, a broad category is
  inferred from the product text (`ai detector`, `video summarizer`).
- `analyzers/source_quality.py`:
  - `hn_content_type`: PRODUCT / DEMAND_SIGNAL / NEWS_DISCUSSION / UNKNOWN.
    Only PRODUCT enters the opportunity pipeline (fixes the "Cloudflare bot
    traffic" news item that used to pass because of the word "bot").
  - `github_product_likeness`: HIGH / MEDIUM / LOW; libraries, SDKs, frameworks,
    research and dev-tooling repos no longer enter the ranking.
  - `novelty_signal`: HIGH / MEDIUM / LOW / UNKNOWN from Toolify new-vs-trending,
    traffic/growth, install base and launch feeds. Mature high-traffic products
    are no longer treated as new opportunities.
  - `discovery_quality`: HIGH / MEDIUM / LOW, used only for shortlist ordering
    and for dropping noise (LOW is filtered out).
  - `source_health()`: per-collector fetched / accepted / filtered / status.
- **Source Health** section in the Markdown report and HTML dashboard, so
  "no opportunity today" can be told apart from "a collector is broken"
  (e.g. `TAAFT 0/0 — request failed: 403`).
- Collectors remember `LAST_ERROR`, exposed through `collectors.source_status()`.
- Cluster-level `novelty_signal` / `discovery_quality` with a capped ±3
  novelty adjustment (cannot override the Solo Builder Score or a verdict).
- 31 new tests including a regression fixture taken from the first real run
  (`tests/fixtures/first_run_2026-10-11.json`) — 186 tests total.

### Changed
- Semrush Check List: NICHE first, then a capped number of BROAD benchmark
  terms, never brand/awkward, 1–3 per cluster, no padding to a minimum, and
  every row now carries a "why it survived" explanation.
- Top Opportunities Today orders by verdict, then discovery quality, then
  Opportunity Score.

### Notes
- No scoring thresholds, verdict logic, data sources, APIs, LLMs or databases
  were added.

## [1.8.0] - Phase 4: Deep Opportunity Validation + Final Decision Layer

### Added
- `analyzers/verdict.py` — the final decision layer. Distinct inputs: Solo
  Builder Score, Cluster Evidence Score, SEO Opportunity Score, Market Demand
  Gate, validation evidence, substitution risk, acquisition fit, monetization
  confidence and operating-cost risk. The three scores are **not** averaged.
- **Verdicts**: `BUILD`, `TEST`, `WATCH`, `SKIP`. BUILD is deliberately hard:
  every requirement must be met (Solo Builder >= 75, market gate PASS or strong
  non-SEO demand, SEO validated when SEO is the main channel, substitution risk
  LOW/MEDIUM, acquisition fit STRONG/MEDIUM, monetization HIGH/MEDIUM,
  operating-cost risk LOW/MEDIUM, no hard blocker, plus either HIGH
  monetization confidence or a positive COMPETITOR/PAYMENT_SIGNAL note, source
  corroboration and persistence).
- **Hard gates** that a high score cannot override: market gate FAIL with no
  non-SEO demand, severe substitution (commodity capability), enterprise/sales
  or service-delivery dependency, regulatory burden, severe operating cost,
  Solo Builder Score < 50, predominantly negative evidence.
- `substitution_risk` LOW/MEDIUM/HIGH/SEVERE with reasons (generic writers,
  summarizers, translators and wrappers are SEVERE; prompt and media generation
  are HIGH; deterministic domain utilities are LOW).
- `primary_acquisition_channel` (SEO / SOCIAL / COMMUNITY /
  PLATFORM_MARKETPLACE / DIRECT_SALES / PAID_ADS / MIXED / UNKNOWN) plus
  `acquisition_fit` (STRONG/MEDIUM/WEAK). SEO is not assumed for every tool.
- `monetization_model` (one-time payment, credits, subscription, ads,
  affiliate, freemium, lead generation, marketplace, enterprise sales) plus
  `monetization_confidence` (HIGH/MEDIUM/LOW/UNKNOWN). No revenue estimates.
- **Opportunity Score /100** as a supporting metric only: Solo Builder Fit 20,
  Market/SEO Demand 20, Opportunity Evidence 15, Competition Accessibility 10,
  Monetization Confidence 10, Acquisition Fit 10, Operating Cost 5,
  Tool-Orchard 5, Substitution Risk 5. Hard gates are applied separately.
- `storage/validation_store.py` + `data/validation/` — manual validation
  evidence (`COMMUNITY_PAIN`, `COMPETITOR`, `PAYMENT_SIGNAL`, `SEARCH_SIGNAL`,
  `TREND_SIGNAL`, `SUBSTITUTION`, `ACQUISITION`, `OTHER`; positive/neutral/
  negative; URL optional) and append-only verdict history
  (previous -> new, date, reason).
- `scripts/validate.py` — `add`, `list`, `history`, `verdicts`,
  `research-status`.
- `analyzers/deep_research.py` — optional research interface, **off by
  default**, no provider registered, no API key, and every provider result is
  normalized into an evidence record (nothing is invented).
- **Validation gaps**: every TEST/WATCH cluster lists concrete next actions
  (check more Semrush keywords, inspect the SERP, check competitor pricing,
  look for payment signals, search Reddit, check API cost, test whether
  ChatGPT already handles it).
- New report sections: **Top Opportunities Today** (top 5 by verdict then
  Opportunity Score, no forced BUILD - a day with no BUILD says so) and
  verdict/substitution/acquisition/monetization/next-actions blocks per cluster
  in both the Markdown report and the HTML dashboard.
- 42 new tests including the five brief example cases — 143 tests total.

### Changed
- `main.py` records verdict history (`record_verdicts=True`); report generation
  itself stays side-effect free, and the HTML dashboard never writes.
- Daily workflow now commits `data/validation` alongside `data/daily` and
  `analysis/daily`.

### Notes
- No Semrush/Ahrefs API, no paid datasets, no embeddings, no vector database,
  no database and no mandatory LLM. The deterministic pipeline runs fully
  offline.

## [1.7.0] - Phase 3: Manual Semrush Enrichment + SEO Opportunity Score

### Added
- `storage/enrichment_store.py` — human-editable JSON store joining on
  **cluster_id + normalized keyword**. Records hold `us_volume`,
  `global_volume`, `kd`, `weak_serp` (required for scoring) plus optional
  `weak_serp_count`, `cpc`, `intent`, `notes`, and a `history` list that keeps
  every previous observation (`KD 12 -> 24 -> 41` stays recoverable). Atomic
  writes; no database.
- `data/enrichment/` — committed store location plus a README documenting the
  format. Wired into `.gitignore` with explicit re-include rules.
- `scripts/enrich.py` — the manual workflow: interactive entry, plus
  `list`, `list-unchecked`, `list-checked`, `list-rejected`, `show`, `set`
  and `reject`. Supports editing a single field, skipping unknown fields, and
  optional rejection reasons (too broad, brand-only, irrelevant intent,
  duplicate intent, no meaningful volume, mature/high-competition category).
- Keyword status per candidate: **UNCHECKED / CHECKED / REJECTED**; rejected
  keywords never return to the daily checklist and never score.
- `analyzers/seo_score.py` — **SEO Opportunity Score 0–100**: Search Demand 35,
  Keyword Difficulty 30, Weak-SERP evidence 20, Long-Tail depth 15. Uses only
  stored enrichment data; missing values are never invented.
  - `seo_score_status`: NOT_CHECKED / PARTIAL / VALIDATED
  - `market_demand_gate`: PASS / WEAK / FAIL / UNKNOWN (SEO demand only)
- `analyzers/keyword_quality.py` — keyword-quality gate. Generic category
  phrases (`checker tool`, `free checker`, `code editor`, `free code editor`,
  `ai tool`, `productivity tool`, `business tool`) are no longer generated;
  per-product keywords require a domain anchor, so `wa workflow enhancer`
  style product names cannot appear. Useful head terms such as
  `tattoo generator` and `prompt generator` are preserved.
- `config/seo_weights.py` — all Phase 3 constants (demand/KD bands, weak-SERP
  points, bonus caps, status and gate thresholds).
- 39 new tests (`test_enrichment_store.py`, `test_keyword_quality.py`,
  `test_seo_score.py`, `test_phase3_demo.py` and report/checklist coverage in
  `test_pipeline.py`) — 101 tests total.

### Changed
- Report Sections A/B now show the three scores **separately**: Solo Builder
  Score, Cluster Evidence Score and SEO Opportunity Score, plus SEO status,
  Market Demand Gate and a checked-keyword table (US / global / KD / weak SERP
  / keyword score). No combined score is produced.
- Semrush Check List: unvalidated clusters first, UNCHECKED keywords only by
  default, HIGH priority first, one keyword per search intent per cluster,
  2–4 keywords per cluster, 10–20 per day, and clusters without usable
  candidates are skipped instead of emitting filler.

### Notes
- Demo Semrush values live only in `tests/fixtures/semrush_demo_enrichment.json`
  and are asserted never to reach production output.
- No Semrush/Ahrefs API, no LLM, no embeddings, no database, no new
  dependency, and no BUILD/TEST/WATCH/SKIP verdict yet.

## [1.6.0] - Phase 2: Opportunity Clustering + SEO Keyword Candidates

### Added
- `analyzers/clustering.py` — deterministic opportunity clustering. Products
  are grouped by **domain + functional head term** (e.g. `tattoo:generation` →
  "Tattoo Generator Tools"); creation-style domains (tattoo, logo, qr, prompt,
  …) fall back to a `domain:generation` cluster; products that cannot be
  confidently grouped stay as their own cluster (keyed by a hash, never by a
  product name).
- Stable `cluster_id` (slug of the cluster key) plus `cluster_key`,
  `cluster_label`, `cluster_theme` and `cluster_reason`.
- Cluster aggregation: member count/names/sources, source diversity, strongest
  source confidence, average/max Solo Builder Score, Tool-Orchard potential,
  evidence summary, representative product, and `first_seen` / `days_seen` /
  `latest_seen` / `repeat_appearances` from the stored JSON history.
- Deterministic `cluster_score` (0–100) with a published breakdown: quality
  (best member score) + capped member bonus (+9) + capped source-diversity
  bonus (+12) + source-confidence adjustment (±5) + persistence bonus (+7 cap)
  − Hacker-News-only penalty (−20) − singleton penalty (−12), with bonuses
  halved below the 60-point quality floor.
- `analyzers/keyword_candidates.py` — 5–15 deterministic SEO candidates per
  cluster (member-derived cores, then compatibility-checked modifier variants,
  a problem query and at most one comparison keyword), each with a
  pre-Semrush priority (HIGH/MEDIUM/LOW) and type (CORE_TOOL, LONG_TAIL_TOOL,
  PROBLEM_QUERY, AUDIENCE_SPECIFIC, COMPARISON).
- Daily **Semrush Check List** (10–20 keywords) built from the highest-ranked
  clusters, corroborated clusters first; each row shows the keyword, cluster,
  priority, type and why it is worth checking. No volume/KD data.
- `config/cluster_weights.py` — all Phase 2 constants in one place.
- Report sections: **A. Top Opportunity Clusters**, **B. Semrush Check List**,
  **C. Individual Product Evidence** (the previous product-level content is
  preserved unchanged) in both `analysis/daily/*-indie.md` and `docs/indie.html`.
- 24 new tests (`test_clustering.py`, `test_keywords.py`,
  `test_cluster_history.py` and cluster/checklist coverage in
  `test_pipeline.py`) — 62 tests total.

### Changed
- `analyzers/text_utils.py` now holds the shared word-boundary matcher,
  name/URL normalization and tokenizer used by scoring, clustering and
  keyword generation (the Phase 1 module re-exports them, so its public
  surface is unchanged).

### Notes
- History signals are limited to what `data/daily` holds (28-day retention).
  When a cluster has no history the report says so instead of inventing
  metrics. No database, no LLM, no embeddings, no Semrush/Ahrefs integration.

## [1.5.0] - Phase 1: Solo Builder Opportunity Radar

### Fixed
- **Daily data history was never committed.** `.gitignore` ignored the whole
  `data/` directory while `daily-report.yml` ran `git add data/daily/*.json || true`.
  Git refuses to add ignored paths, so the command aborted (hidden by `|| true`)
  and `data/daily/` was frozen at 2026-03-20 — starving the weekly report of
  current data. The ignore rule is now explicit (`/data/*`, `!/data/daily/`,
  `/data/daily/*`, `!/data/daily/*.json`) and the workflow stages with
  `git add -A -- data/daily analysis/daily` (no silent failure).
- **Mixed timezones.** Report timestamps used `ZoneInfo("America/Los_Angeles")`
  while file names and storage cutoffs used system-local time. Everything now
  goes through `config/timeutil.py` (`now`, `today_str`, `timestamp_str`,
  `display_str`).
- **Scoring polarity.** `tech_difficulty` (lower = easier) was summed with three
  higher-is-better dimensions, so harder products ranked higher. Replaced by
  `build_ease` (5 = very easy) with the polarity asserted by tests.
- **Domain detection substring bug.** `"reel"` matched inside `"freelancers"`
  and `"ai"` inside `"email"`. Keyword matching is now word-boundary aware.
- GitHub Actions: added a `concurrency` group and `timeout-minutes` so daily
  runs cannot race each other on `git push`.

### Added
- `config/scoring_weights.py` — centralized weights, source confidence and
  reporting bands.
- `config/timeutil.py` — single explicit timezone strategy (Pacific).
- Weighted **Solo Builder Score (0–100)**: Build Ease 20, Self-Service
  Acquisition 15, Monetization 15, Low Communication 15, Operating Cost 10,
  Solo-Builder Fit 15, Tool-Orchard 10.
- Source-confidence ranking adjustment (max ±5): Toolify High, Product Hunt /
  TAAAT Medium–High, Chrome Web Store Medium, GitHub Low–Medium, Hacker News Low.
- Normalization + same-day de-duplication, including the Toolify
  `new`/`trending` overlap.
- Hacker News product-likeness filter (`Show HN` / `Launch HN` kept; news and
  opinion posts excluded from the ranking).
- Operating-cost and communication-burden categories (LOW / MEDIUM / HIGH).
- `tool_orchard_potential` heuristic (converter/calculator/checker/generator
  families expand; novelty and service businesses do not).
- Report/dashboard rows now show the Solo Builder Score /100, source
  confidence, all seven dimensions, the operating-cost category and 2–5 short
  reasons per product.
- `tests/` — first test suite (38 tests, pytest) plus `pytest.ini` and
  `requirements-dev.txt`.

### Notes
- No LLM calls, embeddings, databases, Semrush/Ahrefs integrations or paid APIs
  were added. Clustering, keyword generation, Semrush enrichment and the
  BUILD / TEST / WATCH / SKIP verdict remain future work.

## [1.4.0] - 2026-03-18

### Added
- **Indie hacker opportunity analysis** — new daily report generated alongside the main digest
- `analyzers/indie_analyzer.py` with three core functions:
  - `filter_unsuitable_products()` — removes B2B, complex, institutional, and GitHub library products using keyword + compound-phrase detection
  - `score_product()` — scores each product 1–5 on tech difficulty, user acquisition, revenue potential, and indie-friendliness (max 20)
  - `generate_indie_report()` — produces a full markdown report with three sections: filtered-out table, quick-score table, and top-5 deep-dive
- **8-question deep-dive framework** per top product: Who are the users? Why do they need it? Distribution? Revenue model? Key learnings? One-sentence pitch? Can I build it? How do I find users? Plus a "💡 First Step" action recommendation
- Domain detection table (14 domains) that reads actual product name + description to drive product-specific answers (e.g. fortune-telling → r/astrology outreach, not generic advice)
- `analysis/daily/{date}-indie.md` output file created on every run
- GitHub Actions daily workflow now auto-commits `analysis/daily/*.md`

### Added (continued)
- `analyzers/indie_html_generator.py` — dark-theme HTML version of indie report
  - Collapsible filtered-out table (`<details>`)
  - Sortable quick-score table (vanilla JS, click any column header)
  - Top-5 expandable cards with full 8-question Q&A per product
  - Source-aware link buttons: "View on GitHub →", "View on HN →", "Visit Product →"
  - Clickable product names (white → light-blue on hover, open in new tab)
  - Stats bar: products analysed / filtered / scored / deep-dives
- `docs/indie.html` — indie opportunity dashboard published to GitHub Pages
- Navigation between dashboards: `index.html ↔ indie.html`

### Changed
- `main.py` generates indie HTML report (`docs/indie.html`) after markdown, before email
- `reporters/html_generator.py`: added "View Indie Opportunities →" nav link
- Daily workflow auto-commits `docs/indie.html` alongside `docs/index.html`
- `.gitignore`: added `test*.md`, `test*.html`, `main_output.log`, `.claude/`
- Untracked `.claude/settings.local.json` from git history

## [1.3.1] - 2026-03-17

### Added
- HTML report generation (`reporters/html_generator.py`) — dark-theme, responsive, card-based layout
- `docs/index.html` published to GitHub Pages on every daily run
- GitHub Actions auto-commit step: pushes `docs/index.html` + daily JSON to repo after each run
- `contents: write` permission added to daily workflow for git push support

### Changed
- `main.py` now generates both `report.md` and `docs/index.html` on every run
- HTML UI colors: replaced all purple/violet accents with light blue (`#60a5fa`)
- HTML title font size increased to `3rem` for prominence
- "View →" buttons styled with blue-on-dark-blue look (`#1e3a5f` bg, `#60a5fa` text)

### Technical
- `reporters/html_generator.py`: inline CSS, no external dependencies, HTML-escaped output
- Card badges per source: Toolify (monthly visits + growth rate), Chrome (installs + rating), GitHub (stars), HN (score + comments)
- `collectors/__init__.py`: added `fetch_toolify_tools` export for `from collectors import *`
- Workflow commit message uses `[skip ci]` to prevent infinite trigger loops

## [1.3.0] - 2026-03-17

### Added
- Toolify.ai data source with two sections: latest tools (`/new`) and trending tools (`/Best-trending-AI-Tools`)
- Trending tools include monthly visit count and growth rate (e.g. `1054%`)
- Toolify section in daily report (Latest + Trending subsections)
- Toolify integrated into weekly report: overview, repeated items, new discoveries, statistics
- Playwright-based scraper to bypass Cloudflare protection on Toolify.ai

### Changed
- Data source count increased from 5 to 6
- Daily data JSON now includes `toolify` field (combined new + trending, 10 items)
- Report section order: Product Hunt → Toolify → TAAFT → Chrome Extensions → GitHub → Hacker News
- Weekly report overview and statistics updated to include Toolify Trending

### Technical
- Added `collectors/toolify.py` with `fetch_new_tools()`, `fetch_trending_tools()`, `fetch_toolify_tools()`
- Added `playwright>=1.40.0` to `requirements.txt`
- Both GitHub Actions workflows now install Chromium via `playwright install chromium --with-deps`
- Toolify returns `{'new': [...], 'trending': [...]}` dict; stored as merged flat list for weekly analysis

## [1.2.2] - 2026-02-04

### Fixed
- Chrome Extension rating display issue (fixed rating extraction logic)
- There's An AI For That data source changed to `/new/` page (latest tools instead of stale trending)
- Filter out B2B tools, focus on personal-use tools
- Daily report send time adjusted from 7:30 AM to 7:00 AM PST

## [1.2.1] - 2026-02-02

### Fixed
- Chrome Extension 评分获取失败（选择器从 `ratingValue` 改为 `aria-label`）
- There's An AI For That 改为抓取 `/popular/` 页面而非首页，提升数据质量

## [1.2.0] - 2026-01-31

### Added
- Weekly report automation - comprehensive trend analysis every Sunday
- Daily data storage to JSON files for historical tracking
- Weekly analyzer with frequency analysis and keyword extraction
- Repeated items detection (products appearing multiple times)
- Top keywords analysis across all data sources
- GitHub Actions weekly workflow (every Sunday 22:00 PST)

### Technical
- Added `storage/` module for daily data persistence
- Added `analyzers/` module for weekly data analysis
- Added `reporters/weekly_report_generator.py` for weekly report generation
- Added `weekly_report.py` entry script for weekly automation
- Added `.github/workflows/weekly-report.yml`
- Weekly reports saved to `reports/weekly/weekly-YYYY-MM-DD.md`
- Data retention: 4 weeks (28 days)

## [1.1.0] - 2026-01-31

### Added
- There's An AI For That data source for AI tool discovery
- Chrome Extensions dynamic scraper with random keyword search
- Focus shift: from developer tools to business opportunity discovery

### Changed
- Data source priority: Product Hunt moved to #1 position
- Report structure: Product Hunt → AI Tools → Chrome Extensions → GitHub → Hacker News
- Chrome Extensions: dynamic search instead of hardcoded list

### Technical
- Added `collectors/theresanaiforthat.py`
- Added `collectors/chrome_extensions.py` (refactored from hardcoded IDs to dynamic scraping)
- Updated report generator to support 5 data sources

## [1.0.0] - 2026-01-30

### Added
- GitHub Trending monitoring (top repositories by daily stars)
- Product Hunt monitoring (daily hot products via RSS)
- Hacker News monitoring (top stories via official API)
- Markdown report generation with structured sections
- Email delivery via SMTP (Gmail compatible)
- GitHub Actions automation (daily at 7:30 AM PST)
- PST timezone support for report timestamps
- Complete English documentation (README.md)
- Environment-based configuration (.env support)
