import tempfile
import unittest
from pathlib import Path

from ingest.chamber_vote_report_locator import REPORT_URL, locate
from test_chamber_vote_urgencies import urgency_report

DAY = "2026-10-09"
RECORD = {"descricao": "Aprovado o Requerimento de Urgência (Art. 155 do RICD). Sim: 3; Não: 1; Total: 4.",
          "dataHoraRegistro": f"{DAY}T10:31:00"}


class ReportLocatorTests(unittest.TestCase):
    def locate(self, reports, pairs=((DAY, 100),)):
        def request(url):
            number = int(url.rsplit("=", 1)[1])
            if number not in reports:
                raise OSError("sem relatório")
            return reports[number]
        with tempfile.TemporaryDirectory() as directory:
            return locate({"date": DAY}, RECORD, list(pairs), cache=Path(directory), collect=True,
                          request=request, width=5)

    def test_finds_the_single_report_with_the_same_day_and_tally(self):
        found = self.locate({98: urgency_report(yes=3, no=1), 99: urgency_report(yes=2, no=2)})
        self.assertEqual((found["number"], found["url"]), (98, REPORT_URL.format(98)))

    def test_no_match_or_several_matches_fail_closed(self):
        self.assertIn("0 relatórios", self.locate({99: urgency_report(yes=2, no=2)})["error"])
        twins = {98: urgency_report(yes=3, no=1), 101: urgency_report(yes=3, no=1)}
        self.assertIn("2 relatórios", self.locate(twins)["error"])

    def test_without_known_reports_around_the_day_there_is_no_search(self):
        self.assertIn("delimitar", self.locate({}, pairs=())["error"])


if __name__ == "__main__":
    unittest.main()
