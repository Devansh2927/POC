# SARA.ai — Full Case Lifecycle Extension (L1 → L2 → L3 → MLRO)

This note documents how the POC was extended to follow the end-to-end process
flow in `Complete_TM.xlsx`, while keeping the existing L1 behaviour unchanged.

## What was added

A new module, **`workflow_engine.py`**, models the complete case lifecycle as a
state machine. It consumes each existing investigation record (produced by
`generate_investigation_data.py`) and attaches a `case_workflow` block plus a
`lifecycle_audit` trail. The UI (`investigation_template.html`) renders this as
a new **"Case Lifecycle (L1 → L2 → L3 → MLRO)"** section in every case, on top
of the untouched L1 workspace.

Nothing in the L1 detection, scoring, AI copilot, or existing L1 disposition
logic changed. The L1 stage of the lifecycle **reuses `ai_l1_decision`
verbatim**; the later stages only materialise when a case actually escalates.

## Mapping: process map → lifecycle stages

| Process-map tab | Lifecycle stage (code) | Owner role | Advancing action |
|---|---|---|---|
| L1 Process | `L1_REVIEW` | L1 Analyst | Escalate to L2 (create case) |
| L3 = QC for L1 Process | `L1_QC` | L3 QC Reviewer | QC pass |
| L2 Process | `L2_REVIEW` | L2 Investigator | Escalate to MLRO queue |
| L3 = QC for L2 Process | `L2_QC` | L3 QC Reviewer | QC pass |
| MLRO Process (L3 Investigation) | `MLRO_L3` | L3 Senior Investigator | Refer to MLRO decision |
| MLRO Process (Compliance / MLRO) | `MLRO_DECISION` | MLRO / Compliance | File SAR/STR |

Each stage carries the **checklist steps** taken directly from the map
(User Info Review, Account Operations, Transaction Review, Summary/Decision
for L1/L2; Profile → Analysis → Intelligence → Decision for the MLRO L3 stage;
regulatory-threshold review and SAR filing for the MLRO decision stage).

The L3 stage also generates the **intelligence artefacts** the MLRO map calls
for — source of funds, source of wealth, geographic risk, AML typology match,
fraud indicators, and a recalculated risk score — and the decision stage
generates the **SAR/STR package** (reference, regulator, status = Reported).

## AI progression + mandatory human-in-the-loop (HITL)

This is the core behaviour you asked for: **the AI can move an alert from L1 to
L2 and onward, but HITL is present in every case.**

At each stage SARA.ai works the checklist, produces a recommended disposition
and a narrative, and then one of two things happens:

- **AI advances autonomously** (`hitl.blocking = false`) — when the stage
  evidence is consistent, the AI moves the case to the next stage on its own.
  A human sign-off is **still recorded** against the stage (non-blocking
  concurrent review), and a human can still override on review.

- **Held for human sign-off** (`hitl.blocking = true`) — the case cannot
  advance on AI confidence alone. This happens when:
  1. the AI's own evidence at that stage is **contradictory** (borderline
     confidence band, or diverging signals — the same philosophy as the
     existing L1 engine), or
  2. the stage is a **regulatory decision point** (`MLRO_DECISION`): a SAR/STR
     is **never** filed without a human authorising it, regardless of AI
     confidence.

Every stage therefore has a `hitl` block with:
`present` (always true), `blocking`, `status` (Confirmed / Overridden),
`human_role`, `human_name`, `signed_off_at`, and a `note`. When a human
overrides, the `effective_action` reflects the human's decision, not the AI's.

## Guided demo — one case from L1 alert to SAR filing

For presentations, the login screen has a **"Guided demo — one case, L1 → SAR
filing"** button. It walks a single, representative case
(`ALT-CUST0005` — Sam Kim, high-risk, AI score 90, rules R03/R05/R07, crypto
cash-out with adverse media) through **all six stages** in order:

`L1 Analyst Review → L3 QC of L1 → L2 Investigation → L3 QC of L2 →
L3 Deep Investigation → Compliance/MLRO Decision → SAR/STR filed`

Each step shows the stage's AI recommendation, whether the AI advanced
autonomously or the case was **held for a human sign-off**, the named
human-in-the-loop reviewer and their confirm/override, the checklist from the
process map, the L3 intelligence artefacts, and finally the **filed SAR
reference**. A "Next stage" button advances the case; the rail shows which
login (L1 / L2 / L3 / MLRO) would work each stage in the real per-role
workspaces. "Open the full case file" signs the viewer in as that stage's role
and drops them into the complete investigation workspace for the case.

This gives you a clean, one-click narrative for showing the whole lifecycle end
to end without hunting through the queues.

## Role-based sign-in, per-tier workspaces & Case Management

The workspace now opens on a **role sign-in gate**. Demo credentials are
username = password:

| Username / Password | Role | Sees in their queue |
|---|---|---|
| `L1` / `L1` | L1 Analyst | Cases currently at `L1_REVIEW` |
| `L2` / `L2` | L2 Investigator | Cases currently at `L2_REVIEW` |
| `L3` / `L3` | L3 (QC + Senior) | Cases at `L1_QC`, `L2_QC`, or `MLRO_L3` (deep investigation) |
| `MLRO` / `MLRO` | MLRO / Compliance | Cases at `MLRO_DECISION` (SAR/STR filing) |
| `CM` / `CM` | Case Management | Case Management tab only |

Each role only sees the cases that currently **rest at a stage it owns** (its
queue header shows "N case(s) currently at this stage"). A case therefore
"moves" from the L1 queue into the L2 queue, then the L3 queue, then the MLRO
queue as it is escalated — the credential is effectively carried forward with
the case until a SAR is filed by the MLRO user, exactly as requested.

**Case Management** is a separate tab (also its own `CM` login). Type an
Alert ID, Customer ID, or name and it shows, for each matching case:

- a **status pill** (e.g. *SAR/STR Filed*, *Closed at L1*, *Returned by QC*),
- a **"Currently at"** line — the current stage, the owning role, and the risk
  category,
- a **lifecycle rail** (L1 -> QC-L1 -> L2 -> QC-L2 -> L3 -> MLRO) with the
  current stage highlighted and prior stages marked passed, and
- an **"Open full case file"** button that jumps into the full investigation
  workspace for that case.

> Note on auth: this is **demo-grade, client-side** access control (username
> equals password, checked in the browser). It demonstrates the role-routing
> and per-tier workspace model, not a real authentication system. Production
> would replace it with the Identity Provider / SSO and server-enforced RBAC
> described in the enterprise architecture document.

## Data / files

- **`workflow_engine.py`** — the new lifecycle state machine (pure logic).
- **`generate_investigation_data.py`** — now calls the engine and attaches
  `case_workflow` + `lifecycle_audit` to each record (one small block added at
  the end; everything above it is unchanged).
- **`investigation_template.html`** — new `buildCaseLifecycle()` renderer,
  supporting CSS, and one new accordion section. All existing sections
  unchanged.
- **`output/case_workflow.json`** — the lifecycle for all customers, also
  written standalone (run `python workflow_engine.py`) for inspection.

No new external dependencies. Everything remains deterministic per customer
(seeded RNG), so the whole L1→MLRO lifecycle is reproducible and demoable with
no server and no API key.

## How to run

```
python generate_data.py                 # (unchanged) synthetic source data
python rules_engine.py                  # (unchanged) R01–R12 detection
python ai_copilot.py                    # (unchanged) bounded AI scoring
python enrich_ui_data.py                # (unchanged) evidence enrichment
python generate_investigation_data.py   # now also attaches the case lifecycle
python build_investigation_ui.py        # renders the workspace incl. lifecycle
# open output/case_review_ui.html
```

To inspect the lifecycle outcomes on their own:

```
python workflow_engine.py
# -> output/case_workflow.json + an outcome distribution summary
```

## Example outcome distribution (current synthetic data)

Of 39 alerts, a realistic funnel results: the majority close at L1, a subset
pass L1 QC into L2, fewer reach the MLRO L3 investigation, and a handful result
in a filed SAR/STR — with human sign-off recorded at every stage and a blocking
human authorisation on every SAR decision.
