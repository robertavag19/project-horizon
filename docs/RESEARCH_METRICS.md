# Measurement design — Project Horizon

We must distinguish the accuracy of the agent from the precision of the *detector*.

**Dataset A — Location and evolution**: run ID; observation index; known seeded fault location; suspected first observed deviation; severity estimate; state changes; recovery detection; relevant evidence; time/cost per check.

**Dataset B — Outcome and impact**: independently checked final answer or external state; error persistence; recovery success; consequential error flag; intervention count; false alarms; cost of checks; uncertainty and reference quality.

Proposed future evaluation metrics with well-defined labels:
- **Agent final task success rate**: fraction of tasks satisfying pre-specified acceptance conditions.
- **Detector precision**: TP/(TP+FP) among flagged *consequential* errors; define one counted event per task or per step before experiments.
- **Detector recall**: TP/(TP+FN), with seeded fault labels and manual audit.
- **Recovery rate**: fraction of seeded initial defects with evidence of actual correction by end of run. Condition this on fault type and severity.
- **Selective-verification efficiency**: difference in verification/model/tool cost at comparable quality and error-detection performance.
- **Counterfactual impact**: matched replay comparison (with and without a fault), not just temporal coincidence.

Beware: injected faults aren't identical to naturally arising model errors; a 1-10 score requires expert grading calibration; an LLM judge alone is not objective ground truth. The baseline only checks citation IDs and a known reference passage; it does not implement these research metrics yet.
