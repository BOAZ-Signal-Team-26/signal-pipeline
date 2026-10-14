"""KRX 재대조에서 복수 후보와 사람 확정의 우선순위를 검증한다."""

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RematchTest(unittest.TestCase):
    def test_duplicate_short_code_is_not_auto_matched_and_manual_match_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            scripts = work / "research" / "scripts"
            samples = work / "research" / "samples"
            scripts.mkdir(parents=True)
            samples.mkdir()
            (scripts / "verify_etf_rule.py").symlink_to(
                ROOT / "research" / "scripts" / "verify_etf_rule.py"
            )

            with (samples / "etf_rule_check.csv").open("w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["구분", "ISU_CD", "KRX종목명", "asoStdCd"])
                writer.writerow(["KRX매칭실패", "000001", "ACE TEST", ""])
                writer.writerow(["KRX매칭실패", "000002", "ACE ONE", ""])
                writer.writerow(["KRX매칭실패", "000004", "ACE TWO", ""])
                writer.writerow(["일치", "000005", "ACE TWO 다른 종목", "K55000000004"])

            cache = work / "funds.json"
            cache.write_text(json.dumps([
                {"fndNm": "ACE TEST증권상장지수투자신탁", "srtnCd": "ABCDE", "asoStdCd": "K55000000001"},
                {"fndNm": "ACE TEST채권상장지수투자신탁", "srtnCd": "ABCDE", "asoStdCd": "K55000000002"},
                {"fndNm": "ACE ONE증권상장지수투자신탁", "srtnCd": "FGHIJ", "asoStdCd": "K55000000003"},
                {"fndNm": "ACE TWO증권상장지수투자신탁", "srtnCd": "KLMNO", "asoStdCd": "K55000000004"},
            ], ensure_ascii=False), encoding="utf-8")
            output = work / "result.csv"
            with output.open("w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["결과", "ISU_CD", "KRX종목명", "후보수", "포털펀드명", "srtnCd", "asoStdCd", "유사도", "메모"])
                writer.writerow(["확정(사람 확인)", "000002", "ACE ONE", "1", "ACE ONE증권상장지수투자신탁", "FGHIJ", "K55000000003", "", "사람 확인"])

            subprocess.run(
                [sys.executable, str(ROOT / "research" / "scripts" / "rematch_krx_unmatched.py"), str(cache), str(output)],
                cwd=work, check=True, capture_output=True, text=True,
            )
            with output.open(encoding="utf-8") as file:
                rows = {row["ISU_CD"]: row for row in csv.DictReader(file)}
            self.assertEqual(rows["000001"]["결과"], "보류")
            self.assertEqual(rows["000001"]["후보수"], "2")
            self.assertEqual(rows["000002"]["결과"], "확정(사람 확인)")
            self.assertEqual(rows["000002"]["메모"], "사람 확인")
            self.assertEqual(rows["000004"]["결과"], "보류")
            self.assertEqual(rows["000004"]["asoStdCd"], "K55000000004")
            self.assertIn("000005", rows["000004"]["메모"])


if __name__ == "__main__":
    unittest.main()
