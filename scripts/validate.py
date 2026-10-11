#!/usr/bin/env python3
"""Manual validation-evidence workflow (Phase 4, Step 8).

Examples
--------
    python scripts/validate.py add --cluster tattoo-generation \\
        --type COMPETITOR --sentiment positive \\
        --summary "Multiple standalone tattoo AI tools monetise via credits"
    python scripts/validate.py list --cluster tattoo-generation
    python scripts/validate.py history
    python scripts/validate.py verdicts
    python scripts/validate.py research-status

Stored in data/validation/evidence.json (JSON in git, no database).
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analyzers import deep_research  # noqa: E402
from analyzers.indie_analyzer import clusters_for_day  # noqa: E402
from scripts.enrich import load_day, resolve_cluster  # noqa: E402
from storage import validation_store  # noqa: E402


def _resolve_cluster_id(args, token):
    """Resolve a cluster label/id against the latest stored day when possible."""
    if not token:
        raise SystemExit("--cluster is required")
    try:
        day_data, date = load_day(args.data_dir, args.date)
        clusters = clusters_for_day(day_data, enrichment_path=args.store, today=date)
        cluster = resolve_cluster(clusters, token)
        if cluster:
            return cluster["cluster_id"]
    except (SystemExit, Exception):
        pass
    return token                       # accept a raw cluster_id for older data


def cmd_add(args):
    store = validation_store.load_store(args.validation)
    cluster_id = _resolve_cluster_id(args, args.cluster)
    record = validation_store.add_evidence(
        store, cluster_id, args.type, args.sentiment, args.summary,
        source=args.source or "manual", url=args.url or "", note=args.note or "",
        path=args.validation,
    )
    print(f"added [{record['evidence_type']}/{record['sentiment']}] "
          f"{cluster_id} | {record['summary']}")
    return 0


def cmd_list(args):
    store = validation_store.load_store(args.validation)
    cluster_id = _resolve_cluster_id(args, args.cluster) if args.cluster else None
    records = validation_store.evidence_for(store, cluster_id) if cluster_id else [
        record for records_ in (store.get("records") or {}).values() for record in records_
    ]
    if not records:
        print("no evidence recorded")
        return 0
    for record in sorted(records, key=lambda r: (r.get("cluster_id", ""), r.get("checked_at", ""))):
        line = (f"[{record.get('sentiment'):<8}] {record.get('evidence_type'):<15} "
                f"{record.get('cluster_id'):<30} {record.get('summary')}")
        if record.get("url"):
            line += f"  ({record['url']})"
        print(line)
    return 0


def cmd_history(args):
    store = validation_store.load_store(args.validation)
    history = store.get("verdict_history") or []
    if args.cluster:
        cluster_id = _resolve_cluster_id(args, args.cluster)
        history = [h for h in history if h.get("cluster_id") == cluster_id]
    if not history:
        print("no verdict changes recorded")
        return 0
    for entry in history:
        previous = entry.get("previous_verdict") or "NEW"
        print(f"{entry.get('date')}  {entry.get('cluster_id'):<30} "
              f"{previous} -> {entry.get('new_verdict')}"
              + (f"  ({entry['reason']})" if entry.get("reason") else ""))
    return 0


def cmd_verdicts(args):
    store = validation_store.load_store(args.validation)
    current = store.get("current_verdicts") or {}
    if not current:
        print("no verdicts recorded yet (run the daily pipeline)")
        return 0
    for cluster_id, verdict in sorted(current.items(), key=lambda item: item[1]):
        print(f"{verdict:<6} {cluster_id}")
    return 0


def cmd_research_status(args):
    enabled = deep_research.deep_research_enabled()
    print(f"deep research enabled: {enabled}")
    if not enabled:
        print(f"  {deep_research.DISABLED_REASON}")
    print(f"registered providers: {deep_research.available_providers() or 'none'}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Manual validation evidence workflow")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--store", default=None, help="enrichment store path")
    parser.add_argument("--validation", default=None, help="validation store path")
    parser.add_argument("--date", default=None)
    sub = parser.add_subparsers(dest="command")

    add = sub.add_parser("add", help="add an evidence record")
    add.add_argument("--cluster", required=True)
    add.add_argument("--type", default="OTHER",
                     help="COMMUNITY_PAIN | COMPETITOR | PAYMENT_SIGNAL | SEARCH_SIGNAL | "
                          "TREND_SIGNAL | SUBSTITUTION | ACQUISITION | OTHER")
    add.add_argument("--sentiment", default="neutral")
    add.add_argument("--summary", required=True)
    add.add_argument("--source", default="manual")
    add.add_argument("--url", default="")
    add.add_argument("--note", default="")

    listing = sub.add_parser("list", help="list evidence")
    listing.add_argument("--cluster", default=None)

    history = sub.add_parser("history", help="show verdict changes")
    history.add_argument("--cluster", default=None)

    sub.add_parser("verdicts", help="show the current verdict per cluster")
    sub.add_parser("research-status", help="show the optional deep-research state")
    return parser


COMMANDS = {
    "add": cmd_add,
    "list": cmd_list,
    "history": cmd_history,
    "verdicts": cmd_verdicts,
    "research-status": cmd_research_status,
}


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
