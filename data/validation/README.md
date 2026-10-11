# Validation evidence + verdict history

`evidence.json` stores the manual validation evidence and the verdict-change
history recorded with

```bash
python scripts/validate.py add --cluster tattoo-generation \
    --type COMPETITOR --sentiment positive \
    --summary "Multiple standalone tattoo AI tools monetise via credits"
python scripts/validate.py list --cluster tattoo-generation
python scripts/validate.py history
```

Plain JSON, committed to git, no database needed.

## Evidence record

```json
{
  "evidence_id": "ev-1a2b3c4d5e",
  "cluster_id": "tattoo-generation",
  "evidence_type": "COMPETITOR",
  "sentiment": "positive",
  "source": "manual",
  "url": "",
  "note": "",
  "summary": "Multiple standalone tattoo AI tools monetise via credits",
  "checked_at": "2026-10-11T09:15:00-07:00"
}
```

Evidence types: `COMMUNITY_PAIN`, `COMPETITOR`, `PAYMENT_SIGNAL`,
`SEARCH_SIGNAL`, `TREND_SIGNAL`, `SUBSTITUTION`, `ACQUISITION`, `OTHER`.
Sentiment: `positive`, `neutral`, `negative`. URLs are optional — a note is
enough for manually observed evidence.

## Verdict history

`verdict_history` is append-only and records `previous_verdict`,
`new_verdict`, `date` and `reason` whenever a cluster changes verdict
(`WATCH -> TEST`, `TEST -> BUILD`, ...). `current_verdicts` keeps the last
known verdict so unchanged runs do not add history entries.
