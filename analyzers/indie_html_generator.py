"""Indie opportunity HTML report generator — dark theme matching docs/index.html"""

import re

from analyzers.indie_analyzer import deep_analyze_product, rank_products
from analyzers.clustering import analyze_clusters
from analyzers.keyword_candidates import attach_keyword_candidates, build_semrush_checklist
from analyzers.seo_score import attach_seo
from analyzers.source_quality import source_health
from analyzers.verdict import attach_verdict
from config import scoring_weights as SW
from config import verdict_weights as VW
from config import timeutil
from storage import enrichment_store
from storage import validation_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _e(text):
    """HTML-escape a value."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _parse_deep_dive(md):
    """
    Parse the markdown produced by deep_analyze_product() into a structured dict.

    Returns:
        {
          "name": str,
          "source": str,
          "url": str,
          "description": str,
          "qa": [(question, answer), ...],   # 8 items
          "first_step": str,
        }
    """
    result = {"name": "", "source": "", "url": "", "description": "", "qa": [], "first_step": ""}

    # Name from first heading: ## #1 — Name
    m = re.search(r"^## #\d+ — (.+)$", md, re.MULTILINE)
    if m:
        result["name"] = m.group(1).strip()

    # Source
    m = re.search(r"Source: `([^`]+)`", md)
    if m:
        result["source"] = m.group(1).strip()

    # URL
    m = re.search(r"\[([^\]]+)\]\(([^)]+)\)", md)
    if m and m.group(2).startswith("http"):
        result["url"] = m.group(2)

    # Description
    m = re.search(r"\*\*Description:\*\* (.+)", md)
    if m:
        result["description"] = m.group(1).strip()

    # Q&A sections: ### N. Question\nanswer
    qa_pattern = re.findall(
        r"### \d+\. (.+?)\n([\s\S]+?)(?=### \d+\.|---|\Z)",
        md,
    )
    for question, answer in qa_pattern:
        # Clean up the answer: strip leading/trailing whitespace, collapse blank lines
        answer = answer.strip()
        # Remove blockquote markers (> ) for inline display
        answer = re.sub(r"^\s*>\s?", "", answer, flags=re.MULTILINE)
        result["qa"].append((question.strip(), answer.strip()))

    # First step
    m = re.search(r"💡 \*\*First Step:\*\* (.+)", md)
    if m:
        result["first_step"] = m.group(1).strip()

    return result


def _score_bar(value, max_val=5):
    """Render a small score bar as inline HTML."""
    pct = int(value / max_val * 100)
    return (
        f'<div class="score-bar-wrap" title="{value}/{max_val}">'
        f'<div class="score-bar" style="width:{pct}%"></div>'
        f'<span class="score-num">{value}</span>'
        f"</div>"
    )


def _product_url(product):
    """Return the best URL for a product, constructing GitHub URLs from repo name."""
    source = product.get("_source", "")
    if source == "github":
        name = product.get("name", "")
        return f"https://github.com/{name}" if name else ""
    return (
        product.get("link")
        or product.get("url")
        or product.get("website")
        or ""
    )


def _dim_points(score, key):
    """Weighted points earned on one dimension of a Solo Builder Score."""
    return score["dimensions"][key]["points"]


def _link_label(source):
    """Return appropriate button label for a given source."""
    if source == "github":
        return "View on GitHub →"
    if source == "hackernews":
        return "View on HN →"
    return "Visit Product →"


def _score_color(total):
    """Return a CSS class name for a 0-100 Solo Builder Score."""
    if total >= SW.SCORE_BANDS["high"]:
        return "score-high"
    if total >= SW.SCORE_BANDS["mid"]:
        return "score-mid"
    return "score-low"


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #0f1117;
        color: #e2e8f0;
        line-height: 1.6;
    }

    /* ── Header ── */
    .header {
        background: linear-gradient(135deg, #1a1f2e 0%, #16213e 100%);
        border-bottom: 1px solid #2d3748;
        padding: 32px 24px;
        text-align: center;
    }
    .header h1 { font-size: 3rem; font-weight: 700; color: #fff; letter-spacing: -0.5px; }
    .header h1 span { color: #60a5fa; }
    .header .date { margin-top: 8px; font-size: 14px; color: #718096; }

    .nav-links {
        display: flex;
        justify-content: center;
        gap: 16px;
        margin-top: 16px;
        flex-wrap: wrap;
    }
    .nav-link {
        display: inline-block;
        padding: 6px 18px;
        background: #1e3a5f;
        color: #60a5fa;
        text-decoration: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 500;
        transition: background 0.2s;
    }
    .nav-link:hover { background: #2d5a8e; }

    /* ── Stats bar ── */
    .stats-bar {
        display: flex;
        justify-content: center;
        gap: 32px;
        flex-wrap: wrap;
        padding: 20px 16px;
        background: #13171f;
        border-bottom: 1px solid #2d3748;
    }
    .stat { text-align: center; }
    .stat-num { font-size: 28px; font-weight: 700; color: #60a5fa; }
    .stat-label { font-size: 12px; color: #718096; margin-top: 2px; }

    /* ── Container ── */
    .container { max-width: 1100px; margin: 0 auto; padding: 32px 16px 64px; }

    /* ── Section headers ── */
    .section { margin-bottom: 48px; }
    .section-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 20px;
        padding-bottom: 12px;
        border-bottom: 1px solid #2d3748;
    }
    .section-icon {
        width: 32px; height: 32px; border-radius: 8px;
        display: flex; align-items: center; justify-content: center;
        font-size: 16px; flex-shrink: 0;
    }
    .section-title { font-size: 18px; font-weight: 600; color: #f7fafc; }
    .section-count {
        margin-left: auto;
        font-size: 12px; color: #718096;
        background: #2d3748;
        padding: 2px 10px; border-radius: 999px;
    }

    /* ── Collapsible (filtered) ── */
    details summary {
        cursor: pointer;
        padding: 10px 14px;
        background: #1a1f2e;
        border: 1px solid #2d3748;
        border-radius: 8px;
        font-size: 14px;
        color: #a0aec0;
        list-style: none;
        user-select: none;
    }
    details summary::-webkit-details-marker { display: none; }
    details summary::before { content: "▶  "; font-size: 10px; }
    details[open] summary::before { content: "▼  "; }
    details[open] summary { border-radius: 8px 8px 0 0; border-bottom-color: transparent; }
    .details-body {
        border: 1px solid #2d3748;
        border-top: none;
        border-radius: 0 0 8px 8px;
        overflow: hidden;
    }

    /* ── Tables ── */
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th {
        background: #1e2535;
        color: #a0aec0;
        font-weight: 600;
        text-align: left;
        padding: 10px 14px;
        white-space: nowrap;
    }
    th.sortable { cursor: pointer; user-select: none; }
    th.sortable:hover { color: #60a5fa; }
    th.sort-asc::after  { content: " ↑"; color: #60a5fa; }
    th.sort-desc::after { content: " ↓"; color: #60a5fa; }
    td { padding: 10px 14px; border-top: 1px solid #1e2535; color: #e2e8f0; }
    tr:hover td { background: #1a1f2e; }
    .source-tag {
        display: inline-block;
        font-size: 11px; padding: 2px 8px;
        border-radius: 999px;
        background: #2d3748; color: #a0aec0;
    }

    /* ── Wide score table ── */
    .table-scroll { overflow-x: auto; }
    .why { font-size: 12px; color: #a0aec0; min-width: 260px; max-width: 420px; }
    .why ul { margin: 0; padding-left: 16px; }
    .why li { margin: 2px 0; }

    /* ── Cluster cards + keyword chips ── */
    .cluster-card { margin-bottom: 12px; }
    .cluster-card summary { font-weight: 600; }
    .kw-list {
        list-style: none; padding-left: 0;
        display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 0;
    }
    .kw-list li {
        background: #13171f; border: 1px solid #2d3748;
        border-radius: 6px; padding: 4px 8px; font-size: 12px; color: #cbd5e0;
    }

    /* ── Score bars ── */
    .score-bar-wrap {
        display: flex; align-items: center; gap: 6px; min-width: 80px;
    }
    .score-bar {
        height: 6px; border-radius: 3px;
        background: #60a5fa; flex-shrink: 0;
    }
    .score-num { font-size: 12px; color: #a0aec0; }
    .score-high { color: #86efac; font-weight: 700; }
    .score-mid  { color: #60a5fa; font-weight: 700; }
    .score-low  { color: #718096; }

    /* ── Top 5 cards ── */
    .top-cards { display: flex; flex-direction: column; gap: 20px; }

    .top-card {
        background: #1a1f2e;
        border: 1px solid #2d3748;
        border-radius: 12px;
        overflow: hidden;
    }

    .top-card-header {
        display: flex;
        align-items: flex-start;
        gap: 16px;
        padding: 20px;
    }

    .rank-badge {
        flex-shrink: 0;
        width: 40px; height: 40px;
        border-radius: 10px;
        background: #1e3a5f;
        color: #60a5fa;
        font-size: 16px; font-weight: 700;
        display: flex; align-items: center; justify-content: center;
    }

    .top-card-info { flex: 1; min-width: 0; }
    .top-card-name { font-size: 17px; font-weight: 700; color: #f7fafc; }
    .product-name-link { color: #f7fafc; text-decoration: none; }
    .product-name-link:hover { color: #60a5fa; text-decoration: underline; }
    .top-card-desc { font-size: 13px; color: #a0aec0; margin-top: 4px; }
    .top-card-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }

    .badge {
        font-size: 11px; padding: 3px 8px;
        border-radius: 6px; font-weight: 500;
    }
    .badge-blue   { background: #1e3a5f; color: #93c5fd; }
    .badge-green  { background: #14532d; color: #86efac; }
    .badge-orange { background: #431407; color: #fb923c; }
    .badge-gray   { background: #2d3748; color: #a0aec0; }

    .top-card-score {
        flex-shrink: 0;
        text-align: center;
        padding: 4px 12px;
        border-radius: 8px;
        background: #0f1117;
    }
    .top-card-score .big { font-size: 22px; font-weight: 700; }
    .top-card-score .label { font-size: 10px; color: #718096; }

    /* ── Expandable Q&A ── */
    .qa-toggle {
        width: 100%;
        background: #13171f;
        border: none; border-top: 1px solid #2d3748;
        padding: 10px 20px;
        color: #718096;
        font-size: 13px;
        text-align: left;
        cursor: pointer;
        display: flex; align-items: center; gap: 6px;
        transition: background 0.2s, color 0.2s;
    }
    .qa-toggle:hover { background: #1a1f2e; color: #a0aec0; }
    .qa-toggle .arrow { font-size: 10px; transition: transform 0.2s; }
    .qa-toggle.open .arrow { transform: rotate(90deg); }
    .qa-toggle.open { color: #60a5fa; }

    .qa-body {
        display: none;
        padding: 0 20px 20px;
        border-top: 1px solid #2d3748;
    }
    .qa-body.open { display: block; }

    .qa-item { margin-top: 18px; }
    .qa-q {
        font-size: 12px; font-weight: 700;
        color: #60a5fa;
        text-transform: uppercase; letter-spacing: 0.5px;
        margin-bottom: 4px;
    }
    .qa-a {
        font-size: 13px; color: #cbd5e0;
        white-space: pre-wrap;
    }
    .qa-quote {
        margin-top: 6px;
        padding: 8px 12px;
        border-left: 3px solid #2d5a8e;
        background: #13171f;
        border-radius: 0 6px 6px 0;
        font-size: 12px; color: #a0aec0; font-style: italic;
    }
    .first-step {
        margin-top: 18px;
        padding: 12px 16px;
        background: #162032;
        border: 1px solid #1e3a5f;
        border-radius: 8px;
        font-size: 13px; color: #93c5fd;
    }
    .first-step strong { color: #60a5fa; }

    .card-link {
        display: inline-block;
        padding: 6px 16px;
        background: #1e3a5f; color: #60a5fa;
        text-decoration: none; border-radius: 8px;
        font-size: 13px; font-weight: 500;
        transition: background 0.2s;
    }
    .card-link:hover { background: #2d5a8e; color: #93c5fd; }

    @media (max-width: 600px) {
        .header h1 { font-size: 22px; }
        .top-card-header { flex-wrap: wrap; }
        th, td { padding: 8px 10px; }
    }
"""

# ---------------------------------------------------------------------------
# JS for sortable table + Q&A toggles
# ---------------------------------------------------------------------------

_JS = """
    // Sortable table
    document.querySelectorAll('th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const table = th.closest('table');
            const idx = [...th.parentNode.children].indexOf(th);
            const asc = th.classList.contains('sort-asc');
            table.querySelectorAll('th').forEach(t => t.classList.remove('sort-asc','sort-desc'));
            th.classList.add(asc ? 'sort-desc' : 'sort-asc');
            const tbody = table.querySelector('tbody');
            const rows = [...tbody.querySelectorAll('tr')];
            rows.sort((a, b) => {
                const av = a.children[idx].dataset.val ?? a.children[idx].textContent.trim();
                const bv = b.children[idx].dataset.val ?? b.children[idx].textContent.trim();
                const an = parseFloat(av), bn = parseFloat(bv);
                if (!isNaN(an) && !isNaN(bn)) return asc ? bn - an : an - bn;
                return asc ? bv.localeCompare(av) : av.localeCompare(bv);
            });
            rows.forEach(r => tbody.appendChild(r));
        });
    });

    // Q&A toggles
    document.querySelectorAll('.qa-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const body = btn.nextElementSibling;
            const open = body.classList.toggle('open');
            btn.classList.toggle('open', open);
            btn.querySelector('.qa-label').textContent = open ? 'Hide analysis' : 'Show 8-question analysis';
        });
    });
"""


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_indie_html(indie_report_markdown, product_data, enrichment_path=None,
                        validation_path=None, source_errors=None):
    """
    Generate a dark-theme HTML page for the indie opportunity report.

    Args:
        indie_report_markdown: str — the markdown from generate_indie_report()
                                     (used only for reference; HTML is built from data)
        product_data: dict with keys matching generate_indie_report() parameters:
            product_hunt, toolify, ai_tools, chrome_extensions, github, hackernews
        enrichment_path: optional override for the manual Semrush store location
        validation_path: optional override for the validation evidence store
        source_errors: optional {source: last error} map for the Source Health section

    Returns:
        str: Complete HTML document
    """
    date_str = timeutil.display_str()

    # ── Analyze (shared pipeline with generate_indie_report) ──────────────
    toolify_raw = product_data.get("toolify", [])
    if isinstance(toolify_raw, dict):
        toolify_list = toolify_raw.get("new", []) + toolify_raw.get("trending", [])
    else:
        toolify_list = toolify_raw or []

    all_products = {
        "product_hunt":     product_data.get("product_hunt", []),
        "toolify":          toolify_list,
        "ai_tools":         product_data.get("ai_tools", []),
        "chrome_extensions": product_data.get("chrome_extensions", []),
        "github":           product_data.get("github", []),
        "hackernews":       product_data.get("hackernews", []),
    }

    suitable, filtered_out = rank_products(all_products)
    top5 = suitable[:5]

    total_input = sum(len(v) for v in all_products.values())
    health_rows = source_health(all_products, suitable, filtered_out, errors=source_errors or {})
    store = enrichment_store.load_store(enrichment_path)
    clusters = attach_keyword_candidates(analyze_clusters(suitable))
    attach_seo(clusters, store)
    validation = validation_store.load_store(validation_path)
    attach_verdict(clusters, validation, record_history=False)
    checklist = build_semrush_checklist(clusters, enrichment=store)

    # ── Top Opportunities Today ───────────────────────────────────────────
    ranked_today = sorted(
        clusters,
        key=lambda c: (
            VW.VERDICT_ORDER.get(c.get("verdict"), 9),
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(c.get("discovery_quality"), 1),
            -c.get("opportunity_score", 0),
            c["cluster_id"],
        ),
    )
    top_rows = "".join(
        '<tr>'
        f'<td data-val="{index}">{index}</td>'
        f'<td><strong>{_e(c.get("verdict", "-"))}</strong></td>'
        f'<td>{_e(c["cluster_label"])}</td>'
        f'<td>{_e(c.get("discovery_quality", "MEDIUM"))}</td>'
        f'<td data-val="{c.get("opportunity_score", 0)}">'
        f'<span class="{_score_color(c.get("opportunity_score", 0))}">'
        f'{c.get("opportunity_score", 0)}</span></td>'
        f'<td data-val="{c["max_solo_builder_score"]}">{c["max_solo_builder_score"]}</td>'
        f'<td>{_e(c.get("market_demand_gate", "UNKNOWN"))}</td>'
        f'<td>{_e(c.get("primary_acquisition_channel", "UNKNOWN"))}</td>'
        f'<td>{_e(c.get("substitution_risk", "MEDIUM"))}</td>'
        '</tr>'
        for index, c in enumerate(ranked_today[:5], 1)
    )
    verdict_counts = {}
    for cluster in clusters:
        verdict = cluster.get("verdict", VW.VERDICT_SKIP)
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    counts_line = (
        f"{verdict_counts.get('BUILD', 0)} BUILD · {verdict_counts.get('TEST', 0)} TEST · "
        f"{verdict_counts.get('WATCH', 0)} WATCH · {verdict_counts.get('SKIP', 0)} SKIP"
    )
    no_build_note = ""
    if not verdict_counts.get("BUILD", 0):
        no_build_note = (
            '<p class="why">No opportunity met the BUILD bar today — that is the '
            'expected default. BUILD requires validated demand, monetization evidence, '
            'low substitution risk and low operating cost.</p>'
        )
    top_html = (
        f"<p class=\"why\">{_e(counts_line)} across {len(clusters)} clusters.</p>"
        + '<div class="table-scroll">\n<table>\n'
        + '    <thead><tr><th>#</th><th>Verdict</th><th>Cluster</th>'
          '<th>Discovery</th><th>Opportunity</th><th>Solo Builder</th><th>Market Gate</th>'
          '<th>Acquire</th><th>Substitution</th></tr></thead>\n'
        + '    <tbody>' + top_rows + '</tbody>\n'
        + '</table>\n</div>' + no_build_note
    )

    # ── Section A: Top Opportunity Clusters ───────────────────────────────
    cluster_rows = "".join(
        '<tr>'
        f'<td data-val="{c["cluster_rank"]}">{c["cluster_rank"]}</td>'
        f'<td>{_e(c["cluster_label"])}</td>'
        f'<td data-val="{c["max_solo_builder_score"]}">{c["max_solo_builder_score"]}/100</td>'
        f'<td data-val="{c["cluster_score"]}">'
        f'<span class="{_score_color(c["cluster_score"])}">{c["cluster_score"]}</span></td>'
        f'<td data-val="{c.get("seo_score", 0)}">'
        f'<span class="{_score_color(c.get("seo_score", 0))}">'
        f'{"-" if c.get("seo_score_status") == "NOT_CHECKED" else c.get("seo_score", 0)}</span></td>'
        f'<td data-val="{c.get("opportunity_score", 0)}">'
        f'<span class="{_score_color(c.get("opportunity_score", 0))}">'
        f'{c.get("opportunity_score", 0)}</span></td>'
        f'<td data-val="{_e(c.get("market_demand_gate", "UNKNOWN"))}">'
        f'{_e(c.get("market_demand_gate", "UNKNOWN"))}</td>'
        f'<td data-val="{_e(c.get("verdict", "-"))}">'
        f'<strong>{_e(c.get("verdict", "-"))}</strong></td>'
        f'<td data-val="{c["member_count"]}">{c["member_count"]}</td>'
        f'<td data-val="{c["source_diversity"]}">{c["source_diversity"]}</td>'
        f'<td data-val="{c["tool_orchard_potential"]}">{c["tool_orchard_potential"]}/10</td>'
        '</tr>'
        for c in clusters
    )
    cluster_table = (
        '<div class="table-scroll">\n<table>\n'
        '    <thead><tr>\n'
        '        <th class="sortable">#</th>\n'
        '        <th class="sortable">Cluster</th>\n'
        '        <th class="sortable">Solo Builder</th>\n'
        '        <th class="sortable sort-desc">Cluster Evidence \u2193</th>\n'
        '        <th class="sortable">SEO</th>\n'
        '        <th class="sortable">Opportunity</th>\n'
        '        <th class="sortable">Market Gate</th>\n'
        '        <th class="sortable">Verdict</th>\n'
        '        <th class="sortable">Products</th>\n'
        '        <th class="sortable">Sources</th>\n'
        '        <th class="sortable">Orchard</th>\n'
        '    </tr></thead>\n'
        '    <tbody>' + cluster_rows + '</tbody>\n'
        '</table>\n</div>'
    )

    cluster_cards = []
    for c in clusters[:10]:
        kw_items = "".join(
            f'<li><strong>{_e(k["keyword"])}</strong> '
            f'<span class="source-tag">{_e(k["priority"])}</span> '
            f'<span class="source-tag">{_e(k["type"])}</span></li>'
            for k in c.get("keyword_candidates", [])
        )
        reasons = "".join(f'<li>{_e(r)}</li>' for r in c.get("cluster_score_reasons", []))
        members = "".join(f'<li>{_e(m)}</li>' for m in c.get("member_names", []))
        seo_reasons = "".join(f'<li>{_e(r)}</li>' for r in c.get("seo_reasons", []))
        checked_rows = ""
        for keyword in c.get("checked_keywords") or []:
            weak = "yes" if keyword.get("weak_serp") else "no"
            if keyword.get("weak_serp_count") is not None:
                weak = f"yes ({keyword['weak_serp_count']} weak sites)"
            checked_rows += (
                f'<tr><td>{_e(keyword["keyword"])}</td>'
                f'<td>{keyword["us_volume"]:,}</td>'
                f'<td>{keyword["global_volume"]:,}</td>'
                f'<td>{keyword["kd"]}</td>'
                f'<td>{_e(weak)}</td>'
                f'<td>{keyword["keyword_score"]}/85</td></tr>'
            )
        seo_summary = (
            f'<p class="why"><strong>Solo Builder Score:</strong> '
            f'{c["max_solo_builder_score"]}/100 · '
            f'<strong>Cluster Evidence Score:</strong> {c["cluster_score"]}/100 · '
            f'<strong>SEO Opportunity Score:</strong> {c.get("seo_score", 0)}/100 '
            f'({_e(c.get("seo_score_status", "NOT_CHECKED"))}) · '
            f'<strong>Market Demand Gate:</strong> '
            f'{_e(c.get("market_demand_gate", "UNKNOWN"))}</p>'
        )
        verdict_summary = (
            f'<p class="why"><strong>Verdict:</strong> {_e(c.get("verdict", "-"))} · '
            f'<strong>Opportunity Score:</strong> {c.get("opportunity_score", 0)}/100 · '
            f'<strong>Substitution:</strong> {_e(c.get("substitution_risk", "MEDIUM"))} · '
            f'<strong>Primary acquisition:</strong> '
            f'{_e(c.get("primary_acquisition_channel", "UNKNOWN"))} '
            f'({_e(c.get("acquisition_fit", "WEAK"))}) · '
            f'<strong>Monetization:</strong> {_e(c.get("monetization_model", "unknown"))} '
            f'({_e(c.get("monetization_confidence", "UNKNOWN"))}) · '
            f'<strong>Cost risk:</strong> {_e(c.get("operating_cost_risk", "MEDIUM"))}</p>'
        )
        blocking_items = "".join(f'<li>{_e(r)}</li>' for r in c.get("blocking_reasons", []))
        gap_items = "".join(f'<li>{_e(g)}</li>' for g in c.get("validation_gaps", []))
        verdict_detail = [verdict_summary]
        if blocking_items:
            verdict_detail.append(
                f'<p class="why"><strong>Not BUILD because:</strong></p>'
                f'<ul class="why">{blocking_items}</ul>'
            )
        if gap_items:
            verdict_detail.append(
                f'<p class="why"><strong>Next actions:</strong></p>'
                f'<ul class="why">{gap_items}</ul>'
            )
        parts = [
            '<details class="cluster-card">',
            f'<summary>#{c["cluster_rank"]} {_e(c["cluster_label"])} — {c["cluster_score"]}/100</summary>',
            '<div class="details-body">',
            f'<p class="why">{_e(c.get("evidence_summary", ""))}</p>',
            f'<p class="why"><strong>Why grouped:</strong> {_e(c.get("cluster_reason", ""))}</p>',
            f'<p class="why"><strong>Cluster score:</strong></p><ul class="why">{reasons}</ul>',
            seo_summary,
            f'<p class="why"><strong>SEO basis:</strong></p><ul class="why">{seo_reasons}</ul>',
            f'<p class="why"><strong>Members:</strong></p><ul class="why">{members}</ul>',
        ] + verdict_detail
        if checked_rows:
            parts.append('<p class="why"><strong>Checked keywords:</strong></p>')
            parts.append(
                '<div class="table-scroll"><table><thead><tr>'
                '<th>Keyword</th><th>US volume</th><th>Global volume</th>'
                '<th>KD</th><th>Weak SERP</th><th>Score</th>'
                '</tr></thead><tbody>' + checked_rows + '</tbody></table></div>'
            )
        elif c.get("seo_score_status") == "NOT_CHECKED":
            parts.append(
                '<p class="why">No keywords enriched yet — run '
                '<code>python scripts/enrich.py</code>.</p>'
            )
        if kw_items:
            parts.append('<p class="why"><strong>Keyword candidates:</strong></p>')
            parts.append(f'<ul class="kw-list">{kw_items}</ul>')
        parts.append('</div></details>')
        cluster_cards.append("".join(parts))

    cluster_html = cluster_table + "".join(cluster_cards)
    if not clusters:
        cluster_html = '<p style="color:#718096;font-size:13px">No clusters were produced.</p>'

    # ── Section B: Semrush Check List ─────────────────────────────────────
    if checklist:
        checklist_rows = "".join(
            f'<tr><td><strong>{_e(e["keyword"])}</strong></td>'
            f'<td>{_e(e["cluster_label"])}</td>'
            f'<td><span class="source-tag">{_e(e.get("maturity", "-"))}</span></td>'
            f'<td><span class="source-tag">{_e(e["priority"])}</span></td>'
            f'<td>{_e(e["type"])}</td>'
            f'<td class="why">{_e(e["why"])}</td></tr>'
            for e in checklist
        )
        checklist_html = (
            '<p class="why">Pre-Semrush candidates only — no volume, KD or SERP data. '
            'Manual fields to enter later (Phase 3): US Volume, Global Volume, KD, weak SERP (yes/no).</p>'
            '<div class="table-scroll">\n<table>\n'
            '    <thead><tr><th>Keyword</th><th>Cluster</th><th>Maturity</th>'
            '<th>Priority</th><th>Type</th><th>Why it is worth checking</th></tr></thead>\n'
            '    <tbody>' + checklist_rows + '</tbody>\n'
            '</table>\n</div>'
        )
    else:
        checklist_html = '<p style="color:#718096;font-size:13px">No candidates were generated.</p>'

    # ── Source Health ─────────────────────────────────────────────────────
    health_rows_html = "".join(
        f'<tr><td>{_e(row["label"])}</td>'
        f'<td>{row["fetched"]}</td><td>{row["accepted"]}</td><td>{row["filtered"]}</td>'
        f'<td><span class="source-tag">{_e(row["status"])}</span></td>'
        f'<td class="why">{_e(row.get("note") or "")}'
        f'{" — " + _e(row["error"]) if row.get("error") else ""}</td></tr>'
        for row in health_rows
    )
    health_html = (
        '<p class="why">0 fetched means the collector returned nothing (a source problem); '
        'items fetched but 0 accepted simply means nothing product-like was found today.</p>'
        '<div class="table-scroll"><table><thead><tr><th>Source</th><th>Fetched</th>'
        '<th>Accepted</th><th>Filtered</th><th>Status</th><th>Note</th></tr></thead>'
        '<tbody>' + health_rows_html + '</tbody></table></div>'
    )

    # ── Section 1: Filtered Out (collapsible) ──────────────────────────────
    if filtered_out:
        rows = "".join(
            f"""<tr>
                <td>{_e(p.get("name") or p.get("title") or "Unknown")}</td>
                <td><span class="source-tag">{_e(p.get("_source","?"))}</span></td>
                <td style="color:#718096;font-size:12px">{_e(p.get("filter_reason",""))}</td>
            </tr>"""
            for p in filtered_out
        )
        filtered_html = f"""
        <details>
            <summary>{len(filtered_out)} products removed from consideration</summary>
            <div class="details-body">
                <table>
                    <thead><tr>
                        <th>Product</th><th>Source</th><th>Reason</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </details>"""
    else:
        filtered_html = '<p style="color:#718096;font-size:13px">No products were filtered out.</p>'

    # ── Section 2: Solo Builder Score table (sortable) ─────────────────────
    def _dim_cell(product, key):
        dim = product["_scores"]["dimensions"][key]
        return (f'<td data-val="{dim["points"]}">'
                f'{_score_bar(dim["points"], dim["max"])}</td>')

    score_rows = ""
    for i, p in enumerate(suitable, 1):
        s = p["_scores"]
        name = p.get("name") or p.get("title") or "Unknown"
        url = _product_url(p)
        if url:
            name_html = (f'<a href="{_e(url)}" target="_blank" rel="noopener" '
                         f'style="color:#60a5fa;text-decoration:none">{_e(name)}</a>')
        else:
            name_html = _e(name)

        adjustment = s["source_adjustment"]
        sign = f"+{adjustment}" if adjustment >= 0 else str(adjustment)
        confidence_html = f'<span class="source-tag">{_e(s["source_confidence"])} {sign}</span>'
        reasons_html = "".join(f"<li>{_e(r)}</li>" for r in s["reasons"])
        source = _e(p.get("_source", "?"))

        score_rows += (
            '<tr>'
            f'<td data-val="{i}">{i}</td>'
            f'<td>{name_html}</td>'
            f'<td><span class="source-tag">{source}</span></td>'
            f'<td data-val="{s["source_confidence_value"]:.2f}">{confidence_html}</td>'
            f'<td data-val="{s["ranking_score"]}">'
            f'<span class="{_score_color(s["ranking_score"])}">{s["ranking_score"]}</span></td>'
            f'{_dim_cell(p, "build_ease")}'
            f'{_dim_cell(p, "self_service_acquisition")}'
            f'{_dim_cell(p, "monetization")}'
            f'{_dim_cell(p, "low_communication")}'
            f'{_dim_cell(p, "operating_cost")}'
            f'{_dim_cell(p, "solo_builder_fit")}'
            f'{_dim_cell(p, "tool_orchard")}'
            f'<td class="why"><ul>{reasons_html}</ul></td>'
            '</tr>'
        )

    score_html = (
        '<div class="table-scroll">\n'
        '<table>\n'
        '    <thead><tr>\n'
        '        <th class="sortable">#</th>\n'
        '        <th class="sortable">Product</th>\n'
        '        <th class="sortable">Source</th>\n'
        '        <th class="sortable">Confidence</th>\n'
        '        <th class="sortable sort-desc">Score /100 \u2193</th>\n'
        '        <th class="sortable">Build Ease (20)</th>\n'
        '        <th class="sortable">Self-Serve (15)</th>\n'
        '        <th class="sortable">Monetize (15)</th>\n'
        '        <th class="sortable">Comms (15)</th>\n'
        '        <th class="sortable">Op Cost (10)</th>\n'
        '        <th class="sortable">Solo Fit (15)</th>\n'
        '        <th class="sortable">Orchard (10)</th>\n'
        '        <th>Why this score</th>\n'
        '    </tr></thead>\n'
        '    <tbody>' + score_rows + '</tbody>\n'
        '</table>\n'
        '</div>'
    )

    # ── Section 3: Top 5 deep-dive cards ──────────────────────────────────
    card_htmls = []
    for rank, product in enumerate(top5, 1):
        md = deep_analyze_product(product, rank)
        parsed = _parse_deep_dive(md)
        s = product["_scores"]
        total = s["ranking_score"]
        score_cls = _score_color(total)

        name = parsed["name"] or product.get("name") or product.get("title") or "Unknown"
        desc = parsed["description"] or product.get("description") or product.get("tagline") or ""
        source = parsed["source"] or product.get("_source", "")
        url = _product_url(product) or parsed["url"]

        if url:
            link_html = (
                f'<a class="card-link" href="{_e(url)}" target="_blank" rel="noopener">'
                f'{_link_label(source)}'
                f'</a>'
            )
        else:
            link_html = '<span style="font-size:12px;color:#4a5568">URL not available</span>'

        # Score badges for header (weighted points per dimension, /100 total)
        badges_html = (
            f'<span class="badge badge-blue">Build ease {_dim_points(s, "build_ease")}/20</span>'
            f'<span class="badge badge-green">Acquisition '
            f'{_dim_points(s, "self_service_acquisition")}/15</span>'
            f'<span class="badge badge-orange">Monetization '
            f'{_dim_points(s, "monetization")}/15</span>'
            f'<span class="badge badge-gray">Op cost {s["operating_cost_level"]}</span>'
        )

        # Q&A items
        qa_items_html = ""
        for q, a in parsed["qa"]:
            # Split out any blockquote line
            lines = a.split("\n")
            main_lines, quote_lines = [], []
            for ln in lines:
                if ln.startswith('"') or ln.startswith("'") or "What the product says" in ln:
                    quote_lines.append(ln.strip('"').strip("'").strip())
                else:
                    main_lines.append(ln)
            main_text = _e("\n".join(main_lines).strip())
            quote_html = ""
            if quote_lines:
                quote_text = " ".join(quote_lines).strip('"').strip()
                quote_html = f'<div class="qa-quote">{_e(quote_text)}</div>'
            qa_items_html += f"""
            <div class="qa-item">
                <div class="qa-q">{_e(q)}</div>
                <div class="qa-a">{main_text}</div>
                {quote_html}
            </div>"""

        first_step_html = ""
        if parsed["first_step"]:
            first_step_html = (
                f'<div class="first-step">'
                f'<strong>💡 First Step:</strong> {_e(parsed["first_step"])}'
                f"</div>"
            )

        card_htmls.append(f"""
        <div class="top-card">
            <div class="top-card-header">
                <div class="rank-badge">#{rank}</div>
                <div class="top-card-info">
                    <div class="top-card-name">{
                        f'<a href="{_e(url)}" target="_blank" rel="noopener" class="product-name-link">{_e(name)}</a>'
                        if url else _e(name)
                    }</div>
                    <div class="top-card-desc">{_e(desc)}</div>
                    <div class="top-card-meta">
                        <span class="source-tag">{_e(source)}</span>
                        {badges_html}
                        {link_html}
                    </div>
                </div>
                <div class="top-card-score">
                    <div class="big {score_cls}">{total}</div>
                    <div class="label">/ 100</div>
                </div>
            </div>
            <button class="qa-toggle">
                <span class="arrow">▶</span>
                <span class="qa-label">Show 8-question analysis</span>
            </button>
            <div class="qa-body">
                {qa_items_html}
                {first_step_html}
            </div>
        </div>""")

    top5_html = f'<div class="top-cards">{"".join(card_htmls)}</div>'

    # ── Assemble page ──────────────────────────────────────────────────────
    def _section(icon, bg, title, content, count_label):
        return f"""
    <div class="section">
        <div class="section-header">
            <div class="section-icon" style="background:{bg}">{icon}</div>
            <span class="section-title">{title}</span>
            <span class="section-count">{count_label}</span>
        </div>
        {content}
    </div>"""

    sections_html = (
        _section("🏁", "#16213e", "Top Opportunities Today", top_html,
                 f"top {min(5, len(clusters))}")
        + _section("🧭", "#0a1e35", "Top Opportunity Clusters", cluster_html,
                 f"{len(clusters)} clusters")
        + _section("🔎", "#1a1a0a", "Semrush Check List", checklist_html,
                   f"{len(checklist)} keywords")
        + _section("🩺", "#16213e", "Source Health", health_html,
                   f"{len(health_rows)} sources")
        + '<div class="section"><div class="section-header">'
        + '<span class="section-title">Individual Product Evidence</span></div></div>'
        + _section("🚫", "#2d1515", "Filtered Out", filtered_html,
                   f"{len(filtered_out)} removed")
        + _section("⭐", "#1a1a0a", "Solo Builder Score — All Suitable Products", score_html,
                   f"{len(suitable)} products")
        + _section("🎯", "#0a1e35", "Top 5 Deep Dive", top5_html, "top 5")
    )

    stats_html = f"""
    <div class="stats-bar">
        <div class="stat">
            <div class="stat-num">{total_input}</div>
            <div class="stat-label">Products Analysed</div>
        </div>
        <div class="stat">
            <div class="stat-num">{len(filtered_out)}</div>
            <div class="stat-label">Filtered Out</div>
        </div>
        <div class="stat">
            <div class="stat-num">{len(suitable)}</div>
            <div class="stat-label">Scored</div>
        </div>
        <div class="stat">
            <div class="stat-num">{len(clusters)}</div>
            <div class="stat-label">Clusters</div>
        </div>
        <div class="stat">
            <div class="stat-num">{len(checklist)}</div>
            <div class="stat-label">Semrush Keys</div>
        </div>
        <div class="stat">
            <div class="stat-num">{len(top5)}</div>
            <div class="stat-label">Deep Dives</div>
        </div>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Indie Opportunities — {timeutil.today_str()}</title>
    <style>{_CSS}</style>
</head>
<body>
    <div class="header">
        <h1>Indie <span>Opportunities</span></h1>
        <div class="date">{date_str}</div>
        <div class="nav-links">
            <a class="nav-link" href="index.html">← View All Products</a>
        </div>
    </div>
    {stats_html}
    <div class="container">
        {sections_html}
    </div>
    <script>{_JS}</script>
</body>
</html>"""
