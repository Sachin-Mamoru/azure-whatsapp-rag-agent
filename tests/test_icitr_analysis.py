"""Checks the image-evaluation metric arithmetic on synthetic records with known answers.
Synthetic data here tests code only; it is never reported as an evaluation result."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evaluation", "icitr_reporting"))
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-used")

import analyze_image_eval as A  # noqa: E402


def record(item_id, hazard_type, vision):
    meta = {"model_snapshot": "fake", "token_usage": {"prompt_tokens": 10, "completion_tokens": 2}, "latency_s": 1.0}
    return {"item_id": item_id, "failures": [],
            "attempts": [{"stage": "extraction", "meta": meta}, {"stage": "vision", "meta": meta}],
            "extraction": {"report_domain": "hazard" if hazard_type != "unknown" else "unknown",
                           "hazard_type": hazard_type, "location_text": "Kandy", "location_specific": True,
                           "description": "synthetic description for testing", "people_at_risk": False,
                           "ongoing": True, "hazard_scale": "unknown", "infrastructure_damage": False,
                           "_extraction_meta": {"status": "ok"}},
            "vision": vision}


def item(item_id, cls, cond, claim, supports):
    return {"item_id": item_id, "split": "test", "source_kind": "real_commons", "event_group": f"G-{item_id}",
            "contributor_group": "u", "provisional_image_class": cls, "caption_condition": cond,
            "caption_language": "en", "text_claim_class": claim, "expected_image_supports_report": supports,
            "duplicate_of": None, "transformation": None, "image_sha256": item_id}


def vision(category, consistency, score, detected=True):
    return {"status": "ok", "hazard_detected": detected, "hazard_category": category,
            "possible_condition": "", "severity_from_image": "moderate",
            "report_image_consistency": consistency, "evidence_score": score}


class TestAnalysisArithmetic(unittest.TestCase):
    def test_known_counts(self):
        manifest = {
            "M1": item("M1", "flood", "matching", "flood", True),
            "S1": item("S1", "landslide", "sparse", "none", True),
            "C1": item("C1", "flood", "contradiction", "landslide", False),
            "N1": item("N1", "none", "hazard_claim", "flood", False),
            "N2": item("N2", "none", "sparse", "none", False),
        }
        records = [
            record("M1", "flood", vision("localised_flooding", "high", 0.20)),
            record("S1", "unknown", vision("slope_instability", "moderate", 0.15)),      # correct backfill
            record("C1", "landslide", vision("localised_flooding", "contradiction", 0.10)),
            record("N1", "flood", vision("localised_flooding", "low", 0.05)),            # model wrongly sees flood
            record("N2", "unknown", vision("none", "low", 0.00, detected=False)),
        ]
        rows = A.score_items(records, manifest)
        m = A.analyze(rows, {"source_commit": "x", "split": "test"})
        fs = m["false_support"]["all_non_supporting"]
        # legacy supports C1, N1 (score > 0); visual-v2 supports only N1 (low consistency still counts)
        self.assertEqual((fs["legacy_L"]["k"], fs["visual_v2_C"]["k"], fs["legacy_L"]["n"]), (2, 1, 3))
        self.assertEqual((fs["discordant_L_only"], fs["discordant_C_only"]), (1, 0))
        bf = m["backfill_hazard_type"]["C"]
        self.assertEqual((bf["eligible_text_unknown"], bf["coverage"]["k"], bf["correct_vs_provisional"]["k"]), (2, 1, 1))
        self.assertEqual(m["visual_category"]["coarse_accuracy"]["k"], 4)  # N1 wrong
        self.assertEqual(m["text_extraction"]["hazard_type_agreement"]["k"], 5)
        self.assertEqual(m["ablation"]["sparse_caption_hazard_type_vs_provisional"]["C_with_backfill"]["k"], 1)
        self.assertEqual(m["ablation"]["sparse_caption_hazard_type_vs_provisional"]["A_text_only"]["k"], 0)


if __name__ == "__main__":
    unittest.main()
