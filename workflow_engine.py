"""
workflow_engine.py
==================
Extends the L1-only POC into the full AML case lifecycle described in the
process map (Complete_TM.xlsx):

    L1 Review  ->  L3 QC of L1  ->  L2 Review  ->  L3 QC of L2  ->  MLRO / L3
    Investigation  ->  Compliance-MLRO SAR/STR decision

Design principles carried over from the existing POC:

  * AI (SARA.ai) drives each stage: it works the checklist, produces a
    recommended disposition and a narrative, and -- where permitted -- can
    move the case FORWARD to the next stage autonomously.

  * Human-in-the-loop (HITL) is ALWAYS present. Every stage records a
    `hitl` block with status Pending / Confirmed / Overridden. The AI may
    advance the case, but a human sign-off is always captured against the
    stage, and a human can override the AI's disposition. Two situations
    force the case to WAIT for a human before it can advance
    (`hitl.blocking = True`):
        (a) the AI's own evidence at that stage is contradictory, or
        (b) the stage is a regulatory decision point (MLRO SAR/STR filing).

  * Everything is deterministic per customer (seeded RNG), so the whole
    lifecycle is reproducible and demoable with no external dependency.

This module is pure logic: it consumes an existing investigation record
(the dict produced by generate_investigation_data.py) and returns a
`case_workflow` block that is threaded onto that record. The UI and audit
layers read from that block.
"""

import hashlib
import random
from datetime import datetime, timedelta

# ----------------------------------------------------------------- lifecycle
# Ordered stages of the case lifecycle. Each entry maps directly to a tab in
# the process map workbook.
STAGES = [
    "L1_REVIEW",        # L1 Process
    "L1_QC",            # L3 = QC for L1 Process
    "L2_REVIEW",        # L2 Process
    "L2_QC",            # L3 = QC for L2 Process
    "MLRO_L3",          # MLRO Process : L3 Investigation (Profile/Analysis/Intel/Decision)
    "MLRO_DECISION",    # MLRO Process : Compliance / MLRO SAR/STR decision
]

STAGE_LABELS = {
    "L1_REVIEW":     "L1 Analyst Review",
    "L1_QC":         "L3 Quality Control (L1)",
    "L2_REVIEW":     "L2 Investigation",
    "L2_QC":         "L3 Quality Control (L2)",
    "MLRO_L3":       "L3 Deep Investigation",
    "MLRO_DECISION": "Compliance / MLRO Decision",
}

# Human role that owns the sign-off at each stage.
STAGE_ROLE = {
    "L1_REVIEW":     "L1 Analyst",
    "L1_QC":         "L3 QC Reviewer",
    "L2_REVIEW":     "L2 Investigator",
    "L2_QC":         "L3 QC Reviewer",
    "MLRO_L3":       "L3 Senior Investigator",
    "MLRO_DECISION": "MLRO / Compliance Officer",
}

# The checklist each stage runs, taken from the process map. Kept short and
# human-readable; the UI renders them as a step tracker per stage.
STAGE_CHECKLISTS = {
    "L1_REVIEW": [
        "Alert management: assign, open issue, set In Review",
        "User info review: KYC/ID (retail) or UBO KYC/ID (institutional)",
        "Prior AML cases & alert history",
        "Account operations: freezes, device/IP, associated-account risk",
        "Transaction review: 90-day inflow/outflow/volume, counterparty KYC",
        "External data: PEP / OSINT (retail), UBO/company (institutional)",
        "Unusual Activity Report + summary conclusion",
        "Decision engine: dismiss / close / escalate",
    ],
    "L1_QC": [
        "Re-assign as QC of L1 output",
        "Re-verify KYC/ID and business documents",
        "Re-check prior cases, alert history, freezes/flags",
        "Re-validate transaction review and external data",
        "Confirm L1 narrative & categorisation are sound",
        "QC decision: pass L1 work / return to L1",
    ],
    "L2_REVIEW": [
        "Case management: assign AML case, open, set In Review",
        "User info review + business documents",
        "Account operations incl. banking-feature freeze on AML history",
        "Review period adjustment (contraction/expansion) beyond 90 days",
        "Transaction review + counterparty KYC + external search",
        "Unusual Activity Report + summary conclusion",
        "Decision engine: dismiss / close / request info / escalate to MLRO",
    ],
    "L2_QC": [
        "Re-assign as QC of L2 output",
        "Re-verify case documentation and justifications",
        "Re-validate expanded review period and findings",
        "Confirm L2 narrative supports the disposition",
        "QC decision: pass L2 work / return to L2",
    ],
    "MLRO_L3": [
        "Accept escalation from L2; review L2 investigation & QA notes",
        "Review customer profile, KYC/UBO, sanctions screening",
        "Analyse complete transaction history (velocity/structuring/layering)",
        "Device/IP/common-identifier & geographic risk analysis",
        "Review source of funds & source of wealth",
        "Assess fraud indicators; determine AML typology match",
        "Recalculate overall risk; prepare investigation summary & evidence",
    ],
    "MLRO_DECISION": [
        "Receive case & investigation package",
        "Review regulatory threshold & legal requirements",
        "Reasonable suspicion identified?",
        "File SAR/STR to regulator OR document justification & close",
    ],
}

# Per-stage disposition vocabulary (what the decision engine can output).
STAGE_ACTIONS = {
    "L1_REVIEW":     ["dismiss_no_new_risk", "close_l1", "escalate_to_l2"],
    "L1_QC":         ["pass_l1", "return_to_l1"],
    "L2_REVIEW":     ["dismiss_no_new_risk", "close_l2", "request_info", "escalate_to_mlro"],
    "L2_QC":         ["pass_l2", "return_to_l2"],
    "MLRO_L3":       ["close_no_suspicion", "refer_to_mlro_decision", "pushback_to_l2"],
    "MLRO_DECISION": ["file_sar_str", "close_no_sar"],
}

ACTION_LABELS = {
    "dismiss_no_new_risk":   "Dismiss - No New Risk",
    "close_l1":              "Close L1 Review",
    "escalate_to_l2":        "Escalate to L2 (create case)",
    "pass_l1":               "QC Passed - L1 work sound",
    "return_to_l1":          "Return to L1 for rework",
    "close_l2":              "Close L2 Review",
    "request_info":          "Request for Information",
    "escalate_to_mlro":      "Escalate to MLRO queue",
    "pass_l2":               "QC Passed - L2 work sound",
    "return_to_l2":          "Return to L2 for rework",
    "close_no_suspicion":    "Close - No Reasonable Suspicion",
    "refer_to_mlro_decision":"Refer to MLRO for SAR decision",
    "pushback_to_l2":        "Push back to L2 (info missing)",
    "file_sar_str":          "File SAR / STR to regulator",
    "close_no_sar":          "Close - No SAR required",
}

# Which action at each stage advances the case to the NEXT stage.
ADVANCING_ACTION = {
    "L1_REVIEW":     "escalate_to_l2",
    "L1_QC":         "pass_l1",
    "L2_REVIEW":     "escalate_to_mlro",
    "L2_QC":         "pass_l2",
    "MLRO_L3":       "refer_to_mlro_decision",
    "MLRO_DECISION": "file_sar_str",
}

# Regulatory decision stages: HITL is always blocking here regardless of AI
# confidence -- the AI may prepare and recommend, but a human MUST sign off
# before a SAR/STR is filed.
REGULATORY_STAGES = {"MLRO_DECISION"}

ANALYSTS = {
    "L1 Analyst":               ["N. Fraser", "T. Wickramasinghe", "B. Odutayo"],
    "L3 QC Reviewer":           ["C. Marsh", "L. Bouchard"],
    "L2 Investigator":          ["D. Alvarez", "R. Kimura", "S. Nwosu"],
    "L3 Senior Investigator":   ["H. Petrov", "M. Okonkwo"],
    "MLRO / Compliance Officer":["A. Rahman (MLRO)"],
}

AML_TYPOLOGIES = [
    "Layering via rapid pass-through", "Structuring / smurfing",
    "Trade-based money laundering", "Funnel account activity",
    "Crypto conversion & withdrawal to unhosted wallets",
    "Round-tripping between related parties",
]


def _rng(customer_id, salt=""):
    seed = int(hashlib.sha256(f"wf-{customer_id}-{salt}".encode()).hexdigest(), 16) % (2**32)
    return random.Random(seed)


def _hitl(stage, ai_action, contradictory, r, ts, role):
    """Build the human-in-the-loop sign-off block for a stage.

    HITL is ALWAYS present. `blocking` is True when the case cannot advance
    on AI confidence alone -- i.e. contradictory AI evidence, or a regulatory
    decision stage. When blocking is False the AI advanced the case and a
    human confirmation is recorded alongside (and in a minority of cases the
    human overrides).
    """
    blocking = contradictory or (stage in REGULATORY_STAGES)
    human = r.choice(ANALYSTS[role])

    if blocking:
        # Case waited for a human. Human then acts. For regulatory stages we
        # still show the human confirming the AI package the large majority of
        # the time, but the decision is unambiguously theirs.
        overrides = r.random() < (0.25 if stage in REGULATORY_STAGES else 0.4)
        status = "Overridden" if overrides else "Confirmed"
        return {
            "present": True,
            "blocking": True,
            "status": status,
            "human_role": role,
            "human_name": human,
            "signed_off_at": ts,
            "note": (
                "Regulatory decision point - AI prepared and recommended, but a human "
                "MUST authorise before filing. " if stage in REGULATORY_STAGES
                else "AI evidence was contradictory at this stage, so the case was held for a "
                     "human decision rather than advanced autonomously. "
            ) + ("Human overrode the AI recommendation." if overrides
                 else "Human reviewed and confirmed the disposition."),
        }
    else:
        # AI advanced autonomously; human sign-off still recorded (non-blocking
        # concurrent review). Small chance a human later overrides on review.
        overrides = r.random() < 0.1
        status = "Overridden" if overrides else "Confirmed"
        return {
            "present": True,
            "blocking": False,
            "status": status,
            "human_role": role,
            "human_name": human,
            "signed_off_at": ts,
            "note": (
                "AI advanced the case autonomously (no contradictory signals). A human "
                + ("subsequently overrode the disposition on review."
                   if overrides else "reviewed and confirmed the AI disposition.")
            ),
        }


def _stage_confidence(base_score, r, drift):
    """A stage-level AI confidence, derived from the L1 score with small drift."""
    val = base_score + r.randint(-drift, drift)
    return max(1, min(100, val))


def _contradictory(stage, conf, r):
    """Whether the AI's evidence at this stage is genuinely conflicting.

    Mirrors the L1 engine's philosophy: a borderline middle band, or a small
    random share of cases where signals diverge, forces human review. QC
    stages are steadier (a QC reviewer is re-checking existing work, not
    forming a fresh judgement), so they conflict less often.
    """
    if 48 <= conf <= 58:
        return True
    base = 0.06 if "QC" in stage else 0.12
    return r.random() < base


# ---------------------------------------------------------------- demo data
# For demo/showcase purposes only: these customer_ids are forced all the way
# through to a filed SAR at MLRO_DECISION, regardless of what the seeded RNG
# would otherwise produce. Everything else about their journey (timestamps,
# analysts, narratives, confidence scores) is still generated the normal way
# via the existing per-stage logic -- only the disposition at each stage is
# pinned to "advance", and the human sign-off is pinned to "Confirmed" so the
# override-flip logic never reverses that. This keeps the rest of the
# deterministic dataset (all other customers) completely unchanged.
DEMO_FORCE_SAR_FILED = {"CUST0006", "CUST0003", "CUST0063"}


def build_case_workflow(inv):
    """Given one investigation record, return its full-lifecycle workflow block.

    The L1 stage reuses the existing ai_l1_decision verbatim so nothing about
    the current L1 behaviour changes. Subsequent stages are only materialised
    if the case actually escalates into them.
    """
    cid = inv["customer_id"]
    r = _rng(cid)
    l1 = inv["ai_l1_decision"]
    base_score = l1.get("max_ai_confidence_score", inv["risk_snapshot"]["overall_risk_score"])
    start = datetime.strptime(inv["alert_date"], "%Y-%m-%d %H:%M")
    forced_sar = cid in DEMO_FORCE_SAR_FILED

    stages_out = []
    t = start + timedelta(minutes=12)

    # ---- Stage 1: L1_REVIEW (reuse existing L1 decision) --------------------
    l1_contra = bool(l1.get("requires_human_review"))
    if l1_contra:
        # Human chose. For the synthetic lifecycle we resolve the human's L1
        # choice deterministically: high score -> escalate, else close.
        l1_action = "escalate_to_l2" if base_score >= 50 else "close_l1"
    else:
        l1_action = l1.get("final_action") or ("escalate_to_l2" if base_score >= 50 else "close_l1")
        if l1_action == "close_false_positive":
            l1_action = "close_l1"

    t_l1 = t + timedelta(minutes=r.randint(3, 20))
    stages_out.append({
        "stage": "L1_REVIEW",
        "label": STAGE_LABELS["L1_REVIEW"],
        "role": STAGE_ROLE["L1_REVIEW"],
        "checklist": STAGE_CHECKLISTS["L1_REVIEW"],
        "ai_action": l1_action,
        "ai_action_label": ACTION_LABELS[l1_action],
        "ai_confidence": base_score,
        "ai_narrative": l1["decision_summary"],
        "contradictory": l1_contra,
        "review_reasons": l1.get("review_reasons", []),
        "hitl": _hitl("L1_REVIEW", l1_action, l1_contra, r, t_l1.strftime("%Y-%m-%d %H:%M"),
                      STAGE_ROLE["L1_REVIEW"]),
        "entered_at": t.strftime("%Y-%m-%d %H:%M"),
        "decided_at": t_l1.strftime("%Y-%m-%d %H:%M"),
    })

    # If L1 didn't escalate, the lifecycle ends here.
    advanced = (l1_action == "escalate_to_l2")
    if l1.get("requires_human_review") and stages_out[0]["hitl"]["status"] == "Overridden":
        # human override flips the advance decision
        advanced = not advanced
    if forced_sar:
        advanced = True

    risk_category = None
    if advanced:
        risk_category = r.choice([f["flag"] for f in inv["red_flags"] if f["triggered"] == "Y"] or
                                 ["Unusual Transaction Behaviour"])

    # ---- Remaining stages, only if the case keeps advancing -----------------
    remaining = ["L1_QC", "L2_REVIEW", "L2_QC", "MLRO_L3", "MLRO_DECISION"]
    prev_advanced = advanced
    for stage in remaining:
        if not prev_advanced:
            break
        t = t_l1 + timedelta(hours=r.randint(2, 40))
        conf = _stage_confidence(base_score, r, drift=6 if "QC" in stage else 10)
        if forced_sar:
            conf = max(conf, 75)  # keep confidence comfortably above every threshold below
        contra = _contradictory(stage, conf, r)
        if forced_sar:
            contra = False  # a forced demo case should read as a clean, consistent file

        # choose AI action for this stage
        adv_action = ADVANCING_ACTION[stage]
        if forced_sar:
            # Demo override: this stage always produces the disposition that
            # advances the case (see DEMO_FORCE_SAR_FILED above).
            ai_action = adv_action
        elif stage in ("L1_QC", "L2_QC"):
            # QC mostly passes; it only returns work when evidence is
            # contradictory AND a minority coin-flip lands (a QC reviewer
            # returning a case is the exception, not the norm).
            returns = contra and (r.random() < 0.35)
            if stage == "L1_QC":
                ai_action = "return_to_l1" if returns else "pass_l1"
            else:
                ai_action = "return_to_l2" if returns else "pass_l2"
        elif stage == "MLRO_L3":
            ai_action = "pushback_to_l2" if (contra and r.random() < 0.3) else \
                        ("refer_to_mlro_decision" if conf >= 50 else "close_no_suspicion")
        elif stage == "MLRO_DECISION":
            ai_action = "file_sar_str" if conf >= 50 else "close_no_sar"
        else:  # L2_REVIEW
            ai_action = "escalate_to_mlro" if conf >= 50 else \
                        ("request_info" if contra else "close_l2")

        t_dec = t + timedelta(minutes=r.randint(20, 240))
        hitl = _hitl(stage, ai_action, contra, r, t_dec.strftime("%Y-%m-%d %H:%M"), STAGE_ROLE[stage])
        if forced_sar and hitl["status"] == "Overridden":
            # Never let an override flip a forced case's disposition -- pin the
            # human sign-off to Confirmed so eff_action below stays ai_action.
            hitl["status"] = "Confirmed"
            hitl["note"] = ("Regulatory decision point - AI prepared and recommended; human "
                             "reviewed and authorised." if stage in REGULATORY_STAGES else
                             "AI advanced the case autonomously; human reviewed and confirmed "
                             "the disposition.")

        # human override at a stage can flip the disposition
        eff_action = ai_action
        if hitl["status"] == "Overridden":
            alts = [a for a in STAGE_ACTIONS[stage] if a != ai_action]
            eff_action = r.choice(alts) if alts else ai_action

        stage_block = {
            "stage": stage,
            "label": STAGE_LABELS[stage],
            "role": STAGE_ROLE[stage],
            "checklist": STAGE_CHECKLISTS[stage],
            "ai_action": ai_action,
            "ai_action_label": ACTION_LABELS[ai_action],
            "effective_action": eff_action,
            "effective_action_label": ACTION_LABELS[eff_action],
            "ai_confidence": conf,
            "ai_narrative": _stage_narrative(stage, conf, contra, eff_action, risk_category, inv, r),
            "contradictory": contra,
            "review_reasons": _stage_reasons(stage, conf, contra),
            "hitl": hitl,
            "entered_at": t.strftime("%Y-%m-%d %H:%M"),
            "decided_at": t_dec.strftime("%Y-%m-%d %H:%M"),
        }
        # MLRO_L3 carries the extra intelligence artefacts from the process map
        if stage == "MLRO_L3":
            stage_block["intelligence"] = _mlro_intelligence(inv, conf, risk_category, r)
        if stage == "MLRO_DECISION":
            stage_block["sar"] = _sar_package(inv, eff_action, risk_category, r, t_dec)

        stages_out.append(stage_block)
        prev_advanced = (eff_action == ADVANCING_ACTION[stage])
        t_l1 = t_dec

    # ---- lifecycle summary --------------------------------------------------
    terminal = stages_out[-1]
    current_stage = terminal["stage"]
    outcome = _lifecycle_outcome(stages_out)

    return {
        "risk_category": risk_category,
        "stages_completed": [s["stage"] for s in stages_out],
        "current_stage": current_stage,
        "current_stage_label": STAGE_LABELS[current_stage],
        "outcome": outcome,
        "sar_filed": outcome == "SAR/STR Filed",
        "stages": stages_out,
    }


def _stage_narrative(stage, conf, contra, action, risk_category, inv, r):
    who = "SARA.ai"
    if contra:
        return (f"{who} completed the {STAGE_LABELS[stage]} checklist but found conflicting "
                f"signals (stage confidence {conf}). Rather than advancing autonomously, the "
                f"case was held for {STAGE_ROLE[stage]} sign-off. Recommended action pending "
                f"human confirmation: {ACTION_LABELS[action]}.")
    return (f"{who} completed the {STAGE_LABELS[stage]} checklist with a stage confidence of "
            f"{conf}. Evidence is consistent, so {who} advanced the case with disposition "
            f"'{ACTION_LABELS[action]}'"
            + (f" under risk category '{risk_category}'" if risk_category else "")
            + f". A {STAGE_ROLE[stage]} sign-off is recorded on this stage.")


def _stage_reasons(stage, conf, contra):
    if not contra:
        return []
    reasons = []
    if 45 <= conf <= 62:
        reasons.append(f"Stage confidence {conf} is in the borderline band (neither clearly "
                       f"low nor clearly high), so the disposition is a close call.")
    else:
        reasons.append("Checklist findings diverge from the incoming disposition "
                       "(e.g. new adverse context vs. weak transaction evidence).")
    return reasons


def _mlro_intelligence(inv, conf, risk_category, r):
    """L3 investigation intelligence artefacts required by the MLRO process map."""
    geos = ["Low", "Medium", "High"]
    return {
        "source_of_funds": r.choice([
            "Business revenue - corroborated by invoices", "Salary & savings - corroborated",
            "Unclear - documentation requested", "Third-party transfers - unverified"]),
        "source_of_wealth": r.choice([
            "Established business ownership", "Employment income over time",
            "Inheritance - partially documented", "Unexplained - inconsistent with profile"]),
        "geographic_risk": r.choice(geos),
        "typology_match": r.choice(AML_TYPOLOGIES) if conf >= 50 else "No clear typology match",
        "fraud_indicators": r.choice(["None identified", "Account takeover indicators",
                                      "Mule-account indicators", "Identity mismatch indicators"]),
        "recalculated_risk_score": min(100, conf + r.randint(0, 10)),
        "additional_info_required": "Yes" if conf < 50 else "No",
    }


def _sar_package(inv, action, risk_category, r, ts):
    filed = (action == "file_sar_str")
    ref = "SAR-" + hashlib.sha256(f"{inv['customer_id']}-{ts}".encode()).hexdigest()[:8].upper()
    return {
        "sar_reference": ref if filed else None,
        "filed": filed,
        "regulator": "Financial Intelligence Unit (FIU)" if filed else None,
        "filed_at": ts.strftime("%Y-%m-%d %H:%M") if filed else None,
        "risk_category": risk_category,
        "status": "Reported" if filed else "Closed - No SAR",
        "narrative": (
            f"Investigation package reviewed against regulatory thresholds. Reasonable suspicion "
            f"{'was' if filed else 'was NOT'} identified for customer {inv['customer_id']}. "
            + ("A SAR/STR has been filed to the regulator and the case marked Reported."
               if filed else
               "Justification and findings documented; case closed with no SAR filed.")),
    }


def _lifecycle_outcome(stages):
    last = stages[-1]
    st = last["stage"]
    act = last.get("effective_action", last.get("ai_action"))
    if st == "MLRO_DECISION":
        return "SAR/STR Filed" if act == "file_sar_str" else "Closed - No SAR (MLRO)"
    if st == "MLRO_L3" and act == "close_no_suspicion":
        return "Closed - No Reasonable Suspicion (L3)"
    if st == "MLRO_L3" and act == "pushback_to_l2":
        return "Returned to L2 (info missing)"
    if st == "L2_REVIEW" and act in ("close_l2", "dismiss_no_new_risk"):
        return "Closed at L2"
    if st == "L2_REVIEW" and act == "request_info":
        return "Awaiting Requested Information (L2)"
    if st in ("L1_QC", "L2_QC") and act.startswith("return"):
        return f"Returned by QC ({STAGE_LABELS[st]})"
    if st == "L1_REVIEW" and act in ("close_l1", "dismiss_no_new_risk"):
        return "Closed at L1"
    return f"In progress - {STAGE_LABELS[st]}"


# ---------------------------------------------------------------- audit
def build_lifecycle_audit(inv, workflow):
    """Flat, chronological audit trail across ALL stages, extending the L1 one."""
    events = list(inv.get("audit_trail", []))
    for s in workflow["stages"]:
        hitl = s["hitl"]
        # AI action event
        events.append({
            "time": s["decided_at"], "user": "SARA.ai",
            "action": f"{s['label']}: AI recommends {s['ai_action_label']}",
            "comments": ("Contradictory signals - held for human sign-off."
                         if s["contradictory"] else "Advanced autonomously; HITL sign-off recorded."),
        })
        # Human sign-off event (always present)
        events.append({
            "time": hitl["signed_off_at"], "user": f"{hitl['human_name']} ({hitl['human_role']})",
            "action": f"{s['label']}: Human {hitl['status']}",
            "comments": hitl["note"],
        })
    return events


if __name__ == "__main__":
    import json, sys
    data = json.load(open("output/investigation_data.json"))
    out = {}
    counts = {}
    for cid, inv in data.items():
        wf = build_case_workflow(inv)
        out[cid] = wf
        counts[wf["outcome"]] = counts.get(wf["outcome"], 0) + 1
    json.dump(out, open("output/case_workflow.json", "w"), indent=2)
    print(f"Built output/case_workflow.json for {len(out)} customers.")
    print("Outcome distribution:")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {v:3d}  {k}")
