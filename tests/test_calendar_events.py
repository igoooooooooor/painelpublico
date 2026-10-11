import json
from datetime import date
from pathlib import Path
import tempfile
import unittest

from ingest import calendar_events


class CalendarEventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'data' / 'snapshots').mkdir(parents=True)
        (self.root / 'data' / 'raw' / 'tse').mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, payload):
        (self.root / relative).write_text(json.dumps(payload), encoding='utf-8')

    def test_second_round_becomes_due_then_done_when_sources_postdate_the_round(self):
        self.write('data/snapshots/eleicoes-2026.json', {'segundoTurno': '2026-10-25', 'fonte': {'geradoNoTse': '07/10/2026 16:30:39'}})
        self.write('data/raw/tse/candidacies_2026_v2.meta.json', {'lastModified': 'Wed, 07 Oct 2026 19:30:00 GMT'})
        before = calendar_events.second_round_event(self.root, date(2026, 10, 20))
        self.assertEqual(before['status'], 'not_due')
        due = calendar_events.second_round_event(self.root, date(2026, 10, 27))
        self.assertEqual(due['status'], 'due')
        self.assertEqual(due['stale'], ['candidacies_2026', 'eleicoes-2026.json', 'votes_2026'])
        self.assertEqual([a['name'] for a in due['actions']], ['event-elections', 'event-cities'])
        self.assertEqual(calendar_events.second_round_event(self.root, date(2027, 2, 1))['status'], 'overdue')
        self.write('data/snapshots/eleicoes-2026.json', {'segundoTurno': '2026-10-25', 'fonte': {'geradoNoTse': '27/10/2026 08:00:00'}})
        self.write('data/raw/tse/candidacies_2026_v2.meta.json', {'lastModified': 'Tue, 27 Oct 2026 10:00:00 GMT'})
        self.write('data/raw/tse/votacao_candidato_munzona_2026.meta.json', {'lastModified': 'Wed, 28 Oct 2026 10:00:00 GMT'})
        done = calendar_events.second_round_event(self.root, date(2026, 10, 30))
        self.assertEqual(done['status'], 'done')
        self.assertNotIn('actions', done)

    def test_missing_election_snapshot_uses_the_constitutional_date(self):
        event = calendar_events.second_round_event(self.root, date(2026, 11, 1))
        self.assertEqual((event['date'], event['status']), ('2026-10-25', 'due'))

    def test_legislature_notice_window_and_quiet_periods(self):
        self.assertEqual(calendar_events.legislature_event(date(2026, 10, 11))['status'], 'not_due')
        notice = calendar_events.legislature_event(date(2027, 1, 10))
        self.assertEqual((notice['status'], notice['date']), ('notice', '2027-02-01'))
        window = calendar_events.legislature_event(date(2027, 2, 15))
        self.assertEqual((window['status'], window['id']), ('window', 'legislature-59'))
        self.assertIn('relaxada', window['detail'])
        self.assertEqual(calendar_events.legislature_event(date(2027, 4, 1))['status'], 'not_due')
        summary = calendar_events.summary(calendar_events.pending_events(self.root, date(2027, 1, 10)))
        self.assertEqual(summary['attention'], ['second-round-2026', 'legislature-58'])

    def test_parse_date_formats(self):
        self.assertEqual(calendar_events.parse_date('Sat, 10 Oct 2026 03:00:00 GMT'), date(2026, 10, 10))
        self.assertEqual(calendar_events.parse_date('07/10/2026 16:30:39'), date(2026, 10, 7))
        self.assertEqual(calendar_events.parse_date('2026-10-07T10:00:00+00:00'), date(2026, 10, 7))
        self.assertIsNone(calendar_events.parse_date('ontem'))


if __name__ == '__main__':
    unittest.main()
