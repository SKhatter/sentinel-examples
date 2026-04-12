"""
Sentinel.AI — stress test runner
Fires 15 pipeline runs with a mix of valid and invalid inputs.
View results at: https://www.agentsentinelai.com/dashboard
"""

import sys, os, time
import pipeline

API_KEY = os.environ.get("SENTINEL_API_KEY") or (sys.argv[1] if len(sys.argv) > 1 else None)
if not API_KEY:
    print("Usage:  python stress_test.py <sentinel-api-key>")
    print("   or:  SENTINEL_API_KEY=sk_live_... python stress_test.py")
    sys.exit(1)

pipeline.init(API_KEY)
from sentinel import ContractViolationError

# ── 15 test runs ──────────────────────────────────────────────────────────────
RUNS = [
    # 8 clean runs
    ("Trip to Tokyo for 5 days",          "none"),
    ("Plan a Paris vacation",              "none"),
    ("Weekend in New York City",           "none"),
    ("London for 6 days, $2800 budget",   "none"),
    ("10 days in Bali",                    "none"),
    ("Tokyo again — week-long trip",      "none"),
    ("Paris long weekend",                 "none"),
    ("Budget trip to NYC",                 "none"),
    # plan→research violations (budget type)
    ("Trip to Tokyo",                      "budget_string"),
    ("Paris vacation planning",            "budget_string"),
    # plan→research violations (missing field)
    ("Bali escape",                        "missing_days"),
    ("London trip",                        "missing_days"),
    # plan→research violation (value out of range)
    ("Cheap Tokyo trip",                   "negative_budget"),
    # research→write violations (missing hotels)
    ("Tokyo trip — research fail",         "missing_hotels"),
    ("Paris — research fail",              "missing_hotels"),
]

# ── Run ───────────────────────────────────────────────────────────────────────
print(f"\n{'='*62}")
print(f"  Sentinel.AI stress test — {len(RUNS)} runs")
print(f"  Dashboard: https://www.agentsentinelai.com/dashboard")
print(f"{'='*62}\n")

counts = {"success": 0, "blocked": 0, "error": 0}

for i, (query, mode) in enumerate(RUNS, 1):
    tag   = f"[{i:02d}/{len(RUNS)}]"
    label = f"{query[:46]:<46}"
    try:
        pipeline.run_pipeline(query, failure_mode=mode)
        counts["success"] += 1
        print(f"{tag} {label}  ✓ success")
    except ContractViolationError as e:
        counts["blocked"] += 1
        print(f"{tag} {label}  ✗ BLOCKED   {str(e)[:55]}")
    except Exception as e:
        counts["error"] += 1
        print(f"{tag} {label}  ! ERROR     {str(e)[:55]}")

    time.sleep(0.4)

print(f"\n{'='*62}")
print(f"  success={counts['success']}  blocked={counts['blocked']}  errors={counts['error']}")
print(f"\n  → https://www.agentsentinelai.com/dashboard")
print(f"{'='*62}\n")
