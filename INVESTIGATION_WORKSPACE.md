# L1 Investigation Workspace — Enhancement Notes

This extends the existing `case_review_ui.html` alert-details page into a
full L1 AML investigation cockpit, without redesigning the rest of the app
(header, alert queue, filters, and the original AI-copilot/disposition
flow are unchanged).

## What's new

- **`generate_investigation_data.py`** — builds `output/investigation_data.json`,
  a deterministic, per-customer bundle of KYC/CDD, risk snapshot, 12-month
  transaction analysis, expected-vs-actual behaviour, AML history, PEP
  screening, sanctions screening, OSINT/adverse media, UBO structure (for
  corporate customers), red-flag analysis, a rule-based recommendation, an
  audit trail, and an SLA tracker — generated **from the existing**
  `data/customers.csv`, `data/accounts.csv`, and `data/transactions.csv`, so
  customer IDs, account numbers, and transactions line up with the rest of
  the app. Re-running it produces identical output (seeded by customer ID).
- **`investigation_template.html`** — a copy of `ui_template.html` with:
  - Bootstrap 5 (CSS + JS bundle) and Chart.js added via CDN.
  - A new CSS block (reusing the existing colour/type tokens) for the
    workflow tracker, KPI cards, definition grids, red-flag traffic lights,
    OSINT cards, UBO tree, timeline, and SLA bar.
  - An expanded `renderMain()` plus ~20 new section-builder functions that
    render a **6-step analyst workflow tracker**, an enhanced **Alert
    Summary**, and a 15-section Bootstrap accordion: Customer Risk
    Snapshot, KYC/CDD, AI Copilot Assessment (the original feature, kept
    as-is), Transaction Analysis (with 4 Chart.js charts + a 50-row
    history table), Historical Behaviour, AML History, PEP Screening,
    Sanctions Screening, OSINT/Adverse Media, UBO Details, Risk Indicators
    (red-flag analysis), Recommended Decision (recommendation engine +
    the original Close/Escalate/Request-info disposition flow, now with a
    mandatory rationale to close a false positive), Investigation Notes
    (editable, in-memory per alert), Case Audit Trail, and SLA Tracker.
- **`build_investigation_ui.py`** — combines `alerts_for_ui.json`, the rule
  catalog, and `investigation_data.json` into `output/case_review_ui.html`.

## Rebuilding

```bash
python3 generate_investigation_data.py   # -> output/investigation_data.json
python3 build_investigation_ui.py        # -> output/case_review_ui.html
```

Open `output/case_review_ui.html` directly in a browser — everything
(data + logic) is still embedded in one standalone file. An internet
connection is needed for the Bootstrap/Chart.js CDNs; if they're
unreachable, the tables/KPI cards still render (only the four charts and
accordion collapse animation are affected).
