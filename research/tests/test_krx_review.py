import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_krx_review_table import build_rows
from propose_krx_duplicate_links import candidates


def fund(code, name):
    return {"asoStdCd": code, "fndNm": name}


def audit_row(code, portal, name, reason="", result="일치"):
    return {"ISU_CD": code, "KRX종목명": name, "asoStdCd": portal,
            "포털펀드명": name, "review_reasons": reason, "result": result}


class ReviewTest(unittest.TestCase):
    def test_broad_name_does_not_select_a_different_strategy(self):
        examples = [
            ("KODEX 200", "KODEX 200증권상장지수투자신탁", "KODEX 200커버드콜액티브증권상장지수투자신탁"),
            ("KIWOOM 200선물인버스", "KIWOOM 200선물인버스증권상장지수투자신탁", "KIWOOM 200선물인버스2X증권상장지수투자신탁"),
            ("PLUS 코스닥150", "PLUS 코스닥150증권상장지수투자신탁", "PLUS 코스닥150선물인버스증권상장지수투자신탁"),
            ("ACE 미국10년국채액티브", "ACE 미국10년국채액티브증권상장지수투자신탁(채권)", "ACE 미국10년국채액티브증권상장지수투자신탁(채권)(H)"),
        ]
        for name, correct, incorrect in examples:
            with self.subTest(name=name):
                self.assertEqual([x["asoStdCd"] for x in candidates({"KRX종목명": name},
                                 [fund("wrong", incorrect), fund("right", correct)])], ["right"])

    def test_structural_pass_is_not_published_as_confirmed_identity(self):
        rows = build_rows([audit_row("111111", "A", "ETF A")], [], [], [], [fund("A", "ETF A")])
        self.assertEqual(rows[0]["review_status"], "STRUCTURAL_PASS_ONLY")
        self.assertEqual(rows[0]["candidate_asoStdCd"], "A")
        self.assertEqual(rows[0]["resolved_asoStdCd"], "")

    def test_an_old_manual_decision_with_a_new_conflict_is_held(self):
        rows = build_rows([audit_row("111111", "A", "ETF A", "MULTIPLE_NAME_CANDIDATES", "확정(사람 확인)")],
                          [], [], [], [fund("A", "ETF A")])
        self.assertEqual(rows[0]["review_status"], "PENDING")
        self.assertEqual(rows[0]["resolved_asoStdCd"], "")

    def test_issuer_decision_cannot_reference_an_absent_product(self):
        decision = {"ISU_CD": "111111", "asoStdCd": "B", "포털펀드명": "ETF B",
                    "source_url": "https://issuer.example/product", "evidence_type": "ISSUER_NAME_MATCH", "note": "review"}
        with self.assertRaisesRegex(ValueError, "missing portal product"):
            build_rows([audit_row("111111", "A", "ETF A")], [], [], [decision], [fund("A", "ETF A")])

    def test_a_revised_candidate_table_must_not_reintroduce_collisions(self):
        with self.assertRaisesRegex(ValueError, "collision"):
            build_rows([audit_row("111111", "A", "ETF A"), audit_row("222222", "A", "ETF A")],
                       [], [], [], [fund("A", "ETF A")])


if __name__ == "__main__":
    unittest.main()
