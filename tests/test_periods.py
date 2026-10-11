import os
import unittest
from datetime import date
from unittest import mock

from ingest import periods


class PeriodTests(unittest.TestCase):
    def test_today_honours_painel_today(self):
        with mock.patch.dict(os.environ, {'PAINEL_TODAY': '2026-10-11'}):
            self.assertEqual(periods.today(), date(2026, 10, 11))
            self.assertEqual(periods.current_year(), 2026)
        with mock.patch.dict(os.environ, {'PAINEL_TODAY': 'ontem'}), self.assertRaises(ValueError):
            periods.today()

    def test_previous_month_crosses_the_year(self):
        self.assertEqual(periods.previous_month(date(2026, 10, 11)), (2026, 9))
        self.assertEqual(periods.previous_month(date(2027, 1, 5)), (2026, 12))

    def test_closed_months_follow_mandate_start_and_reference_date(self):
        today = date(2026, 10, 11)
        self.assertEqual(periods.closed_months(2026, today), tuple(range(1, 10)))
        self.assertEqual(periods.closed_months(2025, today), tuple(range(1, 13)))
        self.assertEqual(periods.closed_months(2023, today), tuple(range(2, 13)))
        self.assertEqual(periods.closed_months(2027, today), ())
        self.assertEqual(periods.closed_months(2022, today), ())
        self.assertEqual(periods.closed_months(2027, date(2027, 1, 15)), ())
        self.assertEqual(periods.history_years(today), (2023, 2024, 2025))
        self.assertEqual(periods.history_years(date(2023, 6, 1)), ())

    def test_quota_deadline_closes_a_month_ninety_days_after_its_end(self):
        self.assertEqual(periods.quota_closed_through(date(2026, 10, 11)), (2026, 6))
        self.assertEqual(periods.quota_closed_through(date(2026, 10, 29)), (2026, 7))
        self.assertEqual(periods.quota_closed_through(date(2026, 10, 28)), (2026, 6))
        self.assertEqual(periods.quota_closed_through(date(2027, 2, 1)), (2026, 10))

    def test_legislature_number_and_start(self):
        self.assertEqual(periods.legislature(date(2026, 10, 11)), 57)
        self.assertEqual(periods.legislature(date(2027, 1, 31)), 57)
        self.assertEqual(periods.legislature(date(2027, 2, 1)), 58)
        self.assertEqual(periods.legislature(date(2023, 1, 15)), 56)
        self.assertEqual(periods.legislature_start(57), date(2023, 2, 1))
        self.assertEqual(periods.legislature_start(55), date(2015, 2, 1))

    def test_month_lists_and_periods(self):
        self.assertEqual(periods.parse_months('1,2,9'), (1, 2, 9))
        self.assertEqual(periods.parse_months('1-3, 7..9'), (1, 2, 3, 7, 8, 9))
        self.assertEqual(periods.parse_months(None, (4, 5)), (4, 5))
        for bad in ('1,13', '9-2', 'x', ''):
            with self.assertRaises(ValueError):
                periods.parse_months(bad)
        self.assertEqual(periods.parse_period('2026-09'), (2026, 9))
        with self.assertRaises(ValueError):
            periods.parse_period('2026-13')


if __name__ == '__main__':
    unittest.main()
