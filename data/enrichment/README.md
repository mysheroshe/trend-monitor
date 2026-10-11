# Manual Semrush enrichment

`keywords.json` in this folder holds the manual SEO observations recorded with

```bash
python scripts/enrich.py
```

It is plain JSON, committed to git on purpose: human-editable, deterministic
and easy to merge with the daily reports.

## Join key

`cluster_id + normalized keyword` (lowercased, whitespace collapsed), e.g.

```
tattoo-generation|tattoo generator
```

## Record shape

```json
{
  "version": 1,
  "updated_at": "2026-10-11T09:15:00-07:00",
  "records": {
    "tattoo-generation|tattoo generator": {
      "cluster_id": "tattoo-generation",
      "keyword": "tattoo generator",
      "status": "CHECKED",
      "rejection_reason": "",
      "us_volume": 18100,
      "global_volume": 28900,
      "kd": 51,
      "weak_serp": true,
      "weak_serp_count": 2,
      "cpc": null,
      "intent": "",
      "notes": "",
      "checked_at": "2026-10-11T09:15:00-07:00",
      "history": []
    }
  }
}
```

Required for scoring: `us_volume`, `global_volume`, `kd`, `weak_serp`.
Optional (never block scoring): `weak_serp_count`, `cpc`, `intent`, `notes`.

`status` is one of `UNCHECKED`, `CHECKED`, `REJECTED`. Rejected keywords are
kept out of the daily Semrush Check List and out of SEO scoring.

`history` preserves every previous observation when a keyword is rechecked, so
movement such as `KD 12 -> 24 -> 41` stays recoverable. No trend scoring yet.
