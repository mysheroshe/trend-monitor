#!/usr/bin/env python3
"""Manual Semrush enrichment workflow (Phase 3, Step 2).

Smallest practical workflow: read the latest stored day, show the clusters and
their keyword candidates, and record US volume / global volume / KD / weak SERP
into ``data/enrichment/keywords.json`` (human-editable JSON, committed to git).

Examples
--------
    python scripts/enrich.py
    python scripts/enrich.py list
    python scripts/enrich.py list-unchecked --limit 20
    python scripts/enrich.py list-checked
    python scripts/enrich.py set --cluster tattoo-generation \\
        --keyword "tattoo generator" --us 18100 --global 28900 --kd 51 --weak-serp yes
    python scripts/enrich.py reject --cluster tattoo-generation \\
        --keyword "tattoo generator" --reason "too broad"
    python scripts/enrich.py show --cluster tattoo-generation

No web UI, no database, no API calls.
"""

import argparse
import json
import sys
from pathlib import Path

# Allow `python scripts/enrich.py` to import the project packages.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analyzers.indie_analyzer import clusters_for_day  # noqa: E402
from storage import enrichment_store  # noqa: E402

DEFAULT_DATA_DIR = REPO_ROOT / "data" / "daily"


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def available_days(data_dir=None):
    base = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    if not base.exists():
        return []
    return sorted(path.stem for path in base.glob("*.json"))


def load_day(data_dir=None, date=None):
    """Return (day_data, date_str) for the requested or latest stored day."""
    base = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    if date:
        path = base / f"{date}.json"
        if not path.exists():
            raise SystemExit(f"no stored data for {date} in {base}")
    else:
        days = available_days(base)
        if not days:
            raise SystemExit(f"no stored daily data in {base}; run the daily job first")
        date = days[-1]
        path = base / f"{date}.json"
    return json.loads(path.read_text(encoding="utf-8")), date


def load_clusters(args):
    day_data, date = load_day(args.data_dir, args.date)
    return clusters_for_day(day_data, enrichment_path=args.store, today=date), date


def resolve_cluster(clusters, token):
    """Find a cluster by exact id, or by a unique case-insensitive substring."""
    if not token:
        return None
    for cluster in clusters:
        if cluster["cluster_id"] == token:
            return cluster
    lowered = token.lower()
    matches = [c for c in clusters
               if lowered in c["cluster_id"].lower() or lowered in c["cluster_label"].lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"no cluster matches {token!r}")
    names = ", ".join(c["cluster_id"] for c in matches[:6])
    raise SystemExit(f"{token!r} matches several clusters: {names}")


def store_location(args):
    return args.store if args.store else enrichment_store.default_path()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(args):
    clusters, date = load_clusters(args)
    store = enrichment_store.load_store(args.store)
    print(f"Stored day: {date} | clusters: {len(clusters)} | store: {store_location(args)}")
    print()
    print(f"{'#':>3}  {'cluster id':<32} {'label':<38} {'n':>2} {'SEO':>11} {'gate':<8}")
    for cluster in clusters:
        print(f"{cluster['cluster_rank']:>3}  {cluster['cluster_id']:<32} "
              f"{cluster['cluster_label'][:38]:<38} {cluster['member_count']:>2} "
              f"{cluster['seo_score_status']:>11} {cluster['market_demand_gate']:<8}")
    unchecked = 0
    for cluster in clusters:
        for candidate in cluster.get("keyword_candidates", []):
            status = enrichment_store.status_for(store, cluster["cluster_id"], candidate["keyword"])
            if status == enrichment_store.STATUS_UNCHECKED:
                unchecked += 1
    print()
    print(f"Unchecked candidates: {unchecked}")
    return 0


def cmd_list_unchecked(args):
    clusters, _ = load_clusters(args)
    store = enrichment_store.load_store(args.store)
    target = resolve_cluster(clusters, args.cluster) if args.cluster else None
    shown = 0
    for cluster in clusters:
        if target is not None and cluster["cluster_id"] != target["cluster_id"]:
            continue
        for candidate in cluster.get("keyword_candidates", []):
            status = enrichment_store.status_for(store, cluster["cluster_id"], candidate["keyword"])
            if status != enrichment_store.STATUS_UNCHECKED:
                continue
            shown += 1
            print(f"{cluster['cluster_id']:<30} {candidate['keyword']:<44} "
                  f"{candidate['priority']:<6} {candidate['type']}")
            if args.limit and shown >= args.limit:
                return 0
    if not shown:
        print("nothing unchecked")
    return 0


def _print_records(records, args):
    if args.cluster:
        needle = args.cluster.lower()
        records = [r for r in records if needle in r.get("cluster_id", "").lower()]
    if not records:
        print("no records")
        return 0
    for record in records:
        metrics = (f"US {record.get('us_volume')} | Global {record.get('global_volume')} "
                   f"| KD {record.get('kd')} | weak {record.get('weak_serp')}")
        reason = record.get("rejection_reason")
        extra = f" | reason: {reason}" if reason else ""
        history = len(record.get("history") or [])
        history_note = f" | history: {history}" if history else ""
        print(f"[{str(record.get('status')):<8}] {record.get('cluster_id'):<30} "
              f"{record.get('keyword'):<44} {metrics}{extra}{history_note}")
    return 0


def cmd_list_checked(args):
    store = enrichment_store.load_store(args.store)
    return _print_records(enrichment_store.records_for(store, status="CHECKED"), args)


def cmd_list_rejected(args):
    store = enrichment_store.load_store(args.store)
    return _print_records(enrichment_store.records_for(store, status="REJECTED"), args)


def cmd_show(args):
    clusters, _ = load_clusters(args)
    store = enrichment_store.load_store(args.store)
    target = resolve_cluster(clusters, args.cluster) if args.cluster else None
    for cluster in clusters:
        if target is not None and cluster["cluster_id"] != target["cluster_id"]:
            continue
        print(f"{cluster['cluster_label']} ({cluster['cluster_id']})")
        print(f"  Solo Builder {cluster['max_solo_builder_score']}/100 | "
              f"Cluster Evidence {cluster['cluster_score']}/100 | "
              f"SEO {cluster['seo_score']}/100 {cluster['seo_score_status']} | "
              f"Gate {cluster['market_demand_gate']}")
        for record in enrichment_store.records_for(store, cluster_id=cluster["cluster_id"]):
            print(f"    [{record.get('status')}] {record.get('keyword')} "
                  f"US {record.get('us_volume')} KD {record.get('kd')} "
                  f"weak {record.get('weak_serp')}")
        print()
    return 0


def cmd_set(args):
    store = enrichment_store.load_store(args.store)
    metrics = {
        "us_volume": args.us,
        "global_volume": args.global_volume,
        "kd": args.kd,
        "weak_serp": args.weak_serp,
        "weak_serp_count": args.weak_count,
        "cpc": args.cpc,
        "intent": args.intent,
        "notes": args.notes,
    }
    record = enrichment_store.upsert_metrics(
        store, args.cluster, args.keyword, metrics, path=args.store
    )
    print(f"saved {record['cluster_id']} | {record['keyword']} | "
          f"US {record.get('us_volume')} KD {record.get('kd')} weak {record.get('weak_serp')}")
    return 0


def cmd_reject(args):
    store = enrichment_store.load_store(args.store)
    record = enrichment_store.reject_keyword(
        store, args.cluster, args.keyword, reason=args.reason or "", path=args.store
    )
    print(f"rejected {record['cluster_id']} | {record['keyword']} | "
          f"{record.get('rejection_reason')}")
    return 0


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

def _prompt(text, input_fn=input):
    try:
        return input_fn(text).strip()
    except EOFError:
        return ""


def interactive(args, input_fn=input, output=print):
    clusters, date = load_clusters(args)
    store = enrichment_store.load_store(args.store)
    if not clusters:
        output("no clusters for the latest stored day")
        return 1

    output(f"Stored day: {date}")
    output("")
    output("Select cluster:")
    for index, cluster in enumerate(clusters, 1):
        output(f"{index}. {cluster['cluster_label']}  [{cluster['cluster_id']}] "
               f"SEO {cluster['seo_score_status']}")

    choice = _prompt("> ", input_fn)
    if not choice.isdigit() or not 1 <= int(choice) <= len(clusters):
        output("invalid cluster selection")
        return 1
    cluster = clusters[int(choice) - 1]

    candidates = cluster.get("keyword_candidates", [])
    if not candidates:
        output(f"cluster '{cluster['cluster_label']}' has no keyword candidates")
        return 1

    output("")
    output("Select keyword (number, or type a keyword):")
    for index, candidate in enumerate(candidates, 1):
        status = enrichment_store.status_for(store, cluster["cluster_id"], candidate["keyword"])
        output(f"{index}. {candidate['keyword']} [{status}]")

    keyword_choice = _prompt("> ", input_fn)
    if keyword_choice.isdigit() and 1 <= int(keyword_choice) <= len(candidates):
        keyword = candidates[int(keyword_choice) - 1]["keyword"]
    else:
        keyword = enrichment_store.normalize_keyword(keyword_choice)
    if not keyword:
        output("no keyword selected")
        return 1

    output("")
    us = _prompt("US Volume: ", input_fn)
    global_volume = _prompt("Global Volume: ", input_fn)
    kd = _prompt("KD: ", input_fn)
    weak = _prompt("Weak SERP (yes/no): ", input_fn)
    reject = _prompt("Reject this keyword instead? (y/N): ", input_fn)

    if reject.lower() in ("y", "yes"):
        reason = _prompt("Rejection reason: ", input_fn)
        enrichment_store.reject_keyword(
            store, cluster["cluster_id"], keyword, reason=reason, path=args.store
        )
        output(f"rejected {keyword}")
        return 0

    enrichment_store.upsert_metrics(
        store, cluster["cluster_id"], keyword,
        {"us_volume": us, "global_volume": global_volume, "kd": kd, "weak_serp": weak},
        path=args.store,
    )
    output(f"saved {keyword}")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(description="Manual Semrush enrichment workflow")
    parser.add_argument("--data-dir", default=None, help="directory of stored daily JSON files")
    parser.add_argument("--store", default=None, help="path to the enrichment store JSON")
    parser.add_argument("--date", default=None, help="stored day to use (default: latest)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="list clusters and their SEO status")

    unchecked = sub.add_parser("list-unchecked", help="list keywords not checked yet")
    unchecked.add_argument("--cluster", default=None)
    unchecked.add_argument("--limit", type=int, default=None)

    checked = sub.add_parser("list-checked", help="list previously checked keywords")
    checked.add_argument("--cluster", default=None)

    rejected = sub.add_parser("list-rejected", help="list rejected keywords")
    rejected.add_argument("--cluster", default=None)

    show = sub.add_parser("show", help="show clusters with their enriched keywords")
    show.add_argument("--cluster", default=None)

    set_cmd = sub.add_parser("set", help="record metrics for a keyword")
    set_cmd.add_argument("--cluster", required=True)
    set_cmd.add_argument("--keyword", required=True)
    set_cmd.add_argument("--us", dest="us", default=None)
    set_cmd.add_argument("--global", dest="global_volume", default=None)
    set_cmd.add_argument("--kd", default=None)
    set_cmd.add_argument("--weak-serp", dest="weak_serp", default=None)
    set_cmd.add_argument("--weak-count", dest="weak_count", default=None)
    set_cmd.add_argument("--cpc", default=None)
    set_cmd.add_argument("--intent", default=None)
    set_cmd.add_argument("--notes", default=None)

    reject_cmd = sub.add_parser("reject", help="reject a keyword permanently")
    reject_cmd.add_argument("--cluster", required=True)
    reject_cmd.add_argument("--keyword", required=True)
    reject_cmd.add_argument("--reason", default="")
    return parser


COMMANDS = {
    "list": cmd_list,
    "list-unchecked": cmd_list_unchecked,
    "list-checked": cmd_list_checked,
    "list-rejected": cmd_list_rejected,
    "show": cmd_show,
    "set": cmd_set,
    "reject": cmd_reject,
}


def main(argv=None, input_fn=input, output=print):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        return interactive(args, input_fn=input_fn, output=output)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
