"""Offline golden calculations and retrieval checks; never calls a model."""
import json
import math
from pathlib import Path
from .study_math import calculate
from .study_library import retrieve

def evaluate():
    fixture=json.loads((Path(__file__).resolve().parents[1]/"education/evaluation-v1.json").read_text(encoding="utf-8"))
    results=[]
    for case in fixture["cases"]:
        passed=None
        if case["category"]=="numerical":
            passed=math.isclose(calculate(case["calculation"])["value"],case["expected_value"],rel_tol=1e-12,abs_tol=1e-12)
        elif case["category"]=="retrieval":
            passed=any(r["locator"]==case["expected_locator"] for r in retrieve(case["prompt"],{}))
        results.append({"id":case["id"],"local_check":passed,"live_teaching":"not_evaluated"})
    checked=[r for r in results if r["local_check"] is not None]
    return {"version":fixture["version"],"scenarios":len(results),"local_checks":len(checked),
            "passed":sum(r["local_check"] for r in checked),"failed":sum(not r["local_check"] for r in checked),
            "manual_rubrics_pending":len(results)-len(checked),"live_invocations":0,
            "notice":"Software checks do not establish live explanation quality. Human review and authorized live evaluation remain pending.",
            "results":results}

if __name__=="__main__":
    report=evaluate()
    print(json.dumps(report,indent=2))
    raise SystemExit(bool(report["failed"]))
