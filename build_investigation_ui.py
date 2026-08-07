"""
build_investigation_ui.py
--------------------------
Injects output/alerts_for_ui.json, the rule catalog, and the new
output/investigation_data.json into investigation_template.html to produce
the final output/case_review_ui.html -- a standalone file, no server needed.
"""

import json

from rules_engine import RULE_DESCRIPTIONS, RULE_NAMES, RULE_WEIGHTS

with open("output/alerts_for_ui.json") as f:
    alerts = json.load(f)

with open("output/investigation_data.json") as f:
    investigation_data = json.load(f)

rule_catalog = [{"rule_id": rid, "name": name, "weight": RULE_WEIGHTS[rid],
                  "description": RULE_DESCRIPTIONS[rid]}
                 for rid, name in RULE_NAMES.items()]

with open("investigation_template.html") as f:
    template = f.read()

html = template.replace("__ALERTS_JSON__", json.dumps(alerts))
html = html.replace("__RULE_CATALOG_JSON__", json.dumps(rule_catalog))
html = html.replace("__INVESTIGATION_JSON__", json.dumps(investigation_data))

with open("output/case_review_ui.html", "w") as f:
    f.write(html)

print(f"Built output/case_review_ui.html with {len(alerts)} alerts, "
      f"{len(rule_catalog)} rules, and investigation workspaces for "
      f"{len(investigation_data)} customers.")
