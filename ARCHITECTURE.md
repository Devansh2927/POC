# Architecture Flow (stakeholder walkthrough)

**One line:** synthetic bank/crypto data flows through a deterministic rules
engine, gets a bounded AI-assisted read, is merged with a full investigation
case file, and lands in a single standalone HTML page where **the AI makes
the full L1 disposition itself** (Escalate to L2 or Close as False Positive
— there is no "request more info" tier at L1) and explains why. A human is
only pulled into the loop when the AI's own signals are contradictory
(conflicting evidence, a sharp AI score adjustment, or a genuinely
borderline confidence score); in that case the human chooses between the
same two outcomes. Every decision — whether made autonomously by the AI or
by a human — is written to an audit trail, but to **two separate files** so
it's always clear from the file itself who made the call: autonomous AI
decisions go to `AI_Autonomous_Decisions_Log.csv`, human decisions (including
overrides of an AI decision) go to `L1_Audit_tracker.csv`.


```
 STAGE 1                 STAGE 2                  STAGE 3
 Data Ingestion    ──▶    Detection Engine   ──▶   AI Copilot
 generate_data.py         rules_engine.py          ai_copilot.py
 (stands in for core-     12 deterministic,        Claude (or a
 banking + crypto-        auditable rules           deterministic mock)
 custodian feeds)         (R01–R12)                 reads the rule hits and:
                                                     • nudges the score ±10 pts
 → data/customers.csv     → output/alerts.json        with a stated reason
   accounts.csv             (alert, rules fired,     • explains each rule in
   transactions.csv         evidence, base score)      plain language
   customer_profile_                                 • writes a short summary
   updates.csv                                        • suggests an action
                                                     → output/alerts_with_ai.json
                                                              │
        ┌─────────────────────────────────────────────────────┘
        ▼
 STAGE 4                                    STAGE 5
 Case File Assembly                   ──▶   UI Build
 enrich_ui_data.py                          build_investigation_ui.py
 (attaches the most evidentially            merges the alert queue +
 interesting supporting transactions        rule catalog + full
 to each alert)                             investigation case file into
 → output/alerts_for_ui.json                one standalone page
                                             → output/case_review_ui.html
 generate_investigation_data.py                      │
 (builds the full L1 case file per                   │
 customer: KYC/CDD, User/Entity                      │
 jurisdiction, risk snapshot,                        │
 12-month transaction analysis,                      │
 expected-vs-actual behaviour, past                  │
 AML history + SAR-raised flag,                      │
 Account Operations (device/login                    │
 activity), PEP/sanctions screening,                 │
 OSINT, UBO structure, red-flag                       │
 analysis, an autonomous AI L1                       │
 decision, audit trail, SLA tracker)                 │
 → output/investigation_data.json                    │
 (also reads data/device_sessions.csv)                │
                                                       ▼
                                        STAGE 6
                                        AI L1 Review (autonomous by default)
                                        output/case_review_ui.html — opened
                                        directly in a browser, no server
                                        • the AI reviews KYC/CDD, User/Entity
                                          jurisdiction, transactions, Account
                                          Operations, screening, and past AML/
                                          SAR history, and decides Escalate to
                                          L2 or Close as False Positive itself
                                        • a human analyst is only pulled in
                                          when the AI's own signals are
                                          contradictory (conflicting evidence,
                                          a sharp AI score adjustment, or a
                                          borderline confidence score) — the
                                          human then picks the same two
                                          outcomes; there is no "request more
                                          info" tier at L1
                                        • an analyst can still explicitly
                                          override an autonomous AI decision
                                                       │
                                                       ▼
                                        STAGE 7
                                        Audit Trail (two separate files)
                                        Autonomous AI decisions are written to
                                        AI_Autonomous_Decisions_Log.csv; human
                                        decisions (contradiction cases and any
                                        manual overrides) are written to
                                        L1_Audit_tracker.csv — alert ID, rules
                                        fired, AI base/adjusted score, action,
                                        rationale/summary, override flag,
                                        timestamp. No manual export step.
```

| Stage | Script / artifact | Input | Output | Who owns this in production |
|---|---|---|---|---|
| 1. Data ingestion | `generate_data.py` | — (synthetic generator) | `data/*.csv` (incl. `device_sessions.csv`) | Core-banking / crypto-custodian data feeds (batch or streaming) |
| 2. Detection engine | `rules_engine.py` | `data/*.csv` | `output/alerts.json` | AML detection / compliance engineering (deterministic, explainable rules) |
| 3. AI copilot | `ai_copilot.py` | `output/alerts.json` | `output/alerts_with_ai.json` | AI/ML platform team — bounded, auditable score adjustment only |
| 4. Case file assembly | `enrich_ui_data.py`, `generate_investigation_data.py` | `output/alerts_with_ai.json`, `data/*.csv` | `output/alerts_for_ui.json`, `output/investigation_data.json` | Case-management / backend team |
| 5. UI build | `build_investigation_ui.py` | outputs of stage 4 + rule catalog | `output/case_review_ui.html` | Front-end/UX — currently a static build step, would become a live web app |
| 6. L1 analyst review | `output/case_review_ui.html` | itself (standalone) | staged disposition | L1 AML analyst (human-in-the-loop, final decision-maker) |
| 7. Audit trail | written client-side by the UI | analyst's submitted decision | `L1_Audit_tracker.csv` | Compliance/audit — system-of-record for every decision made |

## Why this shape matters for stakeholders

- The AI now makes the L1 disposition itself (Escalate to L2 or Close as
  False Positive) in most cases, using a deterministic rule-based score it
  can only adjust within a fixed ±10 band, plus red-flag weight, screening
  results, and past AML/SAR history. A human is pulled in only when the
  AI's own signals are contradictory, and can always step in to override an
  autonomous decision.
- Every stage's output is a plain JSON/CSV file, so each step can be
  inspected, replayed, or swapped out independently (e.g. point stage 1 at a
  real core-banking extract without touching stages 2–7).
- The whole thing runs with **zero infrastructure** — no database, no
  server, no deployment — which is exactly why it's fast to demo end-to-end,
  and also exactly what changes first when moving toward production (see
  below).

## Current vs. legacy build path

`README.md` documents `build_ui.py` / `ui_template.html` as the original,
simpler pipeline (alert queue + AI copilot + disposition only). The
canonical build used to produce today's `output/case_review_ui.html` is
`build_investigation_ui.py` / `investigation_template.html`, which layers
the full L1 investigation workspace (KYC/CDD, 12-month transaction analysis,
screening, red flags, system recommendation, audit trail, SLA tracker) on
top of that same original flow. See `INVESTIGATION_WORKSPACE.md` for how
the two relate.

```bash
python3 generate_data.py               # -> data/customers.csv, accounts.csv, transactions.csv, customer_profile_updates.csv
python3 rules_engine.py                # -> output/alerts.json
python3 ai_copilot.py                  # -> output/alerts_with_ai.json
python3 enrich_ui_data.py              # -> output/alerts_for_ui.json
python3 generate_investigation_data.py # -> output/investigation_data.json
python3 build_investigation_ui.py      # -> output/case_review_ui.html
```

Then open `output/case_review_ui.html` in a browser. No build step at
runtime, no server — everything (data + logic) is embedded in the single
HTML file. (An internet connection is needed once, when the page loads, for
the Bootstrap/Chart.js CDNs; if unreachable, tables and KPI cards still
render — only the charts and accordion animation are affected.)

## Extending this into something closer to production

- Swap `generate_data.py`'s output for a real (masked/synthetic)
  core-banking + crypto-custodian extract with the same schema.
- Persist alerts, profile-update events, and analyst decisions to a real
  database instead of JSON/CSV files, and expose the case-review UI through
  a backend (FastAPI is a natural fit given `ai_copilot.py` is already
  plain Python). A backend would also remove the current reliance on each
  analyst's local browser (File System Access API) for the audit file.
- Wire R04/R07/R10 to real exchange/custody APIs for wallet attribution
  (exchange-hosted vs. unhosted) rather than the synthetic `wallet_type`
  flag used here.
- Add a feedback loop job that periodically reviews analyst overrides to
  suggest rule threshold tuning.
- Layer in SAR (Suspicious Activity Report) drafting assistance once a case
  is escalated, using the same summary the copilot already generates.
- Add role-based access control and a full audit log store (who viewed
  what, when, and what the AI showed them at the time) — expected by bank
  compliance/audit functions even for a pilot.
