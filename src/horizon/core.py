"""Dependency-free, deterministic baseline. No language model is included yet."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import time
import uuid


@dataclass(frozen=True)
class Passage:
    id: str
    text: str


def split_passages(document: str) -> list[Passage]:
    chunks = [p.strip() for p in re.split(r"\n\s*\n", document) if p.strip()]
    return [Passage(id=f"P{i:03d}", text=p) for i, p in enumerate(chunks, start=1)]


def keywords(text: str) -> set[str]:
    ignored = {"what", "where", "when", "which", "does", "with", "from", "this", "that", "their", "there", "about", "explain", "how", "the", "and", "for", "are", "can", "why", "you", "into"}
    return {t for t in re.findall(r"[a-zA-Z]+", text.lower()) if len(t) > 2 and t not in ignored}


def search_passages(question: str, passages: list[Passage], top_k: int = 2) -> list[Passage]:
    q = keywords(question)
    scored = [(len(q & keywords(p.text)), p) for p in passages]
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return [p for score, p in scored if score > 0][:top_k]


class Trace:
    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id
        self.step = 0
        path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, kind: str, **data: object) -> None:
        self.step += 1
        event = {"run_id": self.run_id, "step": self.step, "time_utc": datetime.now(timezone.utc).isoformat(), "kind": kind, "data": data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def verify_citations(citations: list[str], passages: list[Passage]) -> dict:
    ids = {p.id for p in passages}
    missing = [c for c in citations if c not in ids]
    return {"citation_ids_valid": not missing and bool(citations), "invalid_ids": missing}


def run_baseline(document: str, question: str, log_dir: Path, *, inject: str = "none", expected_passage: str | None = None) -> dict:
    """A repeatable control workflow; intentionally *not* a model-driven AI agent.

    Injected faults are recorded and evaluated. No private or personal source content
    is written to the trace, only passage IDs and a few metadata fields.
    """
    run_id = str(uuid.uuid4())
    trace = Trace(log_dir / f"{run_id}.jsonl", run_id)
    start = time.perf_counter()
    passages = split_passages(document)
    trace.record("ingest", passage_count=len(passages))
    selected = search_passages(question, passages)
    trace.record("tool_call", name="search_passages", question_length=len(question))
    trace.record("tool_result", name="search_passages", selected_ids=[p.id for p in selected])
    original = selected[0] if selected else None
    if inject == "drop_evidence":
        selected = []
        trace.record("fault_injected", fault="drop_evidence", after="search_passages")
    elif inject == "wrong_citation" and selected:
        trace.record("fault_injected", fault="wrong_citation", after="search_passages")
    trace.record("tool_call", name="read_passage", selected_ids=[p.id for p in selected])
    trace.record("tool_result", name="read_passage", found=bool(selected), count=len(selected))

    if selected:
        # This is an evidence excerpt, not a generated or proven-correct answer.
        quote = selected[0].text[:500]
        answer = f"Relevant source excerpt: {quote}"
        citations = ["P999"] if inject == "wrong_citation" else [selected[0].id]
    else:
        answer = "No relevant source excerpt was found. I cannot answer from this document."
        citations = []
    trace.record("draft", citation_ids=citations, answer_length=len(answer))
    verification = verify_citations(citations, passages)
    trace.record("verify", **verification)

    if not verification["citation_ids_valid"] and selected:
        # Correct a demonstrably invalid citation; don't claim to fix factual errors.
        citations = [selected[0].id]
        trace.record("recovery", reason="invalid_citation_id", corrected_ids=citations)
        verification = verify_citations(citations, passages)
        trace.record("reverify", **verification)

    reference_found = bool(expected_passage and original and original.id == expected_passage)
    outcome = {
        "run_id": run_id,
        "answer": answer,
        "citations": citations,
        "has_evidence": bool(selected),
        "citation_ids_valid": verification["citation_ids_valid"],
        "expected_passage_found": reference_found if expected_passage else None,
        "recovery_occurred": inject == "wrong_citation" and bool(selected),
        "fault_injected": inject,
        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
        "trace_file": str(trace.path),
        "limitations": "Citation IDs are checked; semantic correctness is NOT evaluated. No LLM is used.",
    }
    trace.record("finish", has_evidence=outcome["has_evidence"], citation_ids_valid=outcome["citation_ids_valid"], recovered=outcome["recovery_occurred"])
    return outcome
