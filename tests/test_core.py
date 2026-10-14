import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from horizon.core import run_baseline, search_passages, split_passages, verify_citations


DOC = "Centripetal acceleration is directed toward the center of a circular path.\n\nPhotosynthesis uses sunlight to produce energy-rich molecules."


class HorizonTests(unittest.TestCase):
    def test_passages(self):
        self.assertEqual([p.id for p in split_passages(DOC)], ["P001", "P002"])

    def test_retrieval(self):
        self.assertEqual(search_passages("centripetal acceleration circular", split_passages(DOC))[0].id, "P001")

    def test_citations(self):
        self.assertTrue(verify_citations(["P002"], split_passages(DOC))["citation_ids_valid"])
        self.assertFalse(verify_citations(["P999"], split_passages(DOC))["citation_ids_valid"])

    def test_run_and_trace(self):
        with TemporaryDirectory() as path:
            result = run_baseline(DOC, "centripetal acceleration", Path(path), expected_passage="P001")
            self.assertTrue(result["citation_ids_valid"])
            self.assertTrue(result["expected_passage_found"])
            events = [json.loads(line) for line in Path(result["trace_file"]).read_text().splitlines()]
            self.assertEqual(events[-1]["kind"], "finish")
            self.assertTrue(any(e["kind"] == "tool_call" for e in events))

    def test_fault_and_recovery(self):
        with TemporaryDirectory() as path:
            result = run_baseline(DOC, "centripetal acceleration", Path(path), inject="wrong_citation")
            self.assertTrue(result["recovery_occurred"])
            self.assertEqual(result["citations"], ["P001"])
            self.assertTrue(result["citation_ids_valid"])
            events = [json.loads(line) for line in Path(result["trace_file"]).read_text().splitlines()]
            self.assertIn("recovery", [e["kind"] for e in events])

    def test_missing_evidence(self):
        with TemporaryDirectory() as path:
            result = run_baseline(DOC, "centripetal acceleration", Path(path), inject="drop_evidence")
            self.assertFalse(result["has_evidence"])
            self.assertFalse(result["citation_ids_valid"])
            self.assertIn("cannot answer", result["answer"])


if __name__ == "__main__":
    unittest.main()
