"""SKN36 V3 self-tests (Python standard library; synthetic PDF test needs PyMuPDF)."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import SKN36_auto_splitting as m

ROOT = Path(__file__).resolve().parent


class SplittingTests(unittest.TestCase):
    def test_table_years_repeated(self):
        text = ("2026 개정사항\n\n| 열 1 | 열 2 | 열 3 |\n| --- | --- | --- |\n"
                "| 구분 | 2025년(현행) | 2026년(개정안) |\n"
                "| 선정기준액 | 2,280,000원 | 2,470,000원 |\n")
        units=m.split_pdf_semantically(text,section_heading="기초연금")
        rows=[x for x in units if x["content_kind"]=="markdown_table_row"]
        self.assertEqual(len(rows),1)
        self.assertIn("2025년(현행): 2,280,000원",rows[0]["body"])
        self.assertIn("2026년(개정안): 2,470,000원",rows[0]["body"])
        self.assertTrue(all(len(x["body"])<=700 for x in units))

    def test_long_table_repeats_cell_label(self):
        text="| 항목 | 2025년(현행) | 2026년(개정안) |\n| --- | --- | --- |\n"
        text+="| 금액 | " + "2025년 금액 123원 \\n"*80 + " | " + "2026년 금액 234원 \\n"*80 + " |"
        units=m.split_pdf_semantically(text,section_heading="기초연금")
        t=[x for x in units if x["content_kind"]=="markdown_table_row"]
        self.assertGreater(len(t),2)
        self.assertTrue(all(len(x["body"])<=700 for x in t))
        self.assertTrue(all("행: 금액" in x["body"] for x in t))
        self.assertTrue(all("2025년" in x["body"] or "2026년" in x["body"] for x in t))

    def test_prose_offset_exact(self):
        text=("단락 시작\n\n"+"정책 지원 조건 및 혜택 설명. "*100)
        for unit in m.split_pdf_semantically(text,section_heading="정책"):
            if unit["content_kind"]=="prose":
                self.assertEqual(m.clean_text(text)[unit["start"]:unit["end"]],unit["body"])

    def test_real_csv_and_jsonl_counts(self):
        report_path=ROOT/"splitting_output_v3/split_quality_report.json"
        if not report_path.exists():
            self.skipTest("실제 데이터 결과 없이 코드만 받았으면 생략")
        report=json.loads(report_path.read_text(encoding="utf8"))
        self.assertEqual(report["source_counts"]["total_policies"],1946)
        self.assertEqual(report["source_counts"]["local_detail_missing"],485)
        self.assertGreater(report["pdf_table_chunk_count"],500)
        self.assertFalse(report["limitations"]["tokenizer_verified"])
        self.assertFalse(report["limitations"]["pdf_page_specific_citations_approved"])

    def test_optional_fifth_pdf_extraction(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF optional")
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"test.pdf"
            doc=fitz.open()
            for i in range(2):
                page=doc.new_page()
                page.insert_text((60,80),f"TEST PAGE {i+1} - local synthetic example")
            doc.save(p)
            doc.close()
            rows=m.extract_elderly_pdf_pages(p)
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]["page_start"],1)
            self.assertIn("TEST PAGE 1",rows[0]["content"])
            self.assertEqual(rows[1]["review_status"],"pending")


if __name__ == "__main__":
    unittest.main(verbosity=2)
