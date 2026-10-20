import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from ingest import editorial_queue


def entry(identifier, day, candidate=True, category='main_text', method='nominal'):
    return {'id': identifier, 'date': day, 'description': f'Aprovado o projeto {identifier}', 'candidate': candidate,
            'category': category, 'method': method, 'targetPropositions': ['PL 1/2026'], 'recordedTally': {'sim': 300},
            'reviewIssues': [], 'sourceUrl': f'https://dadosabertos.camara.leg.br/api/v2/votacoes/{identifier}'}


class EditorialQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reviews = self.root / 'data' / 'reviews'
        self.snapshots = self.root / 'data' / 'snapshots'
        self.reviews.mkdir(parents=True)
        self.snapshots.mkdir(parents=True)
        (self.root / 'data' / 'imports').mkdir()
        (self.root / 'ingest').mkdir()
        self.today = date(2026, 10, 11)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, payload):
        path.write_text(json.dumps(payload), encoding='utf-8')

    def inventory(self, through, entries):
        self.write(self.reviews / f'chamber-vote-inventory-{through}.json', {
            'period': {'start': through[:4] + '-01-01', 'end': through}, 'generatedAt': through + 'T06:00:00',
            'listComplete': True, 'typeGuard': {'pecTurnsOutsideCandidates': [{'id': '9-1', 'description': 'PEC turno'}]},
            'entries': entries})

    def test_unreviewed_candidates_and_new_since_last_run(self):
        self.write(self.snapshots / 'accounts.json', {'year': 2024})  # exercício atrasado: aviso de arquivo manual
        self.inventory('2026-10-04', [entry('1-1', '2026-09-30'), entry('2-1', '2026-10-01'), entry('3-1', '2026-10-02', candidate=False)])
        self.inventory('2026-10-11', [entry('1-1', '2026-09-30'), entry('2-1', '2026-10-01'), entry('4-1', '2026-10-09'),
                                      entry('5-1', '2026-10-09')])
        self.inventory('2025-12-31', [entry('8-1', '2025-05-05')])  # outro ano: ignorado
        self.write(self.reviews / 'chamber-vote-reviews-2026-10-09.json', [
            {'id': '1-1', 'status': 'confirmed', 'reviewedAt': '2026-10-09'},
            {'id': '2-1', 'status': 'pending', 'reason': 'sem relatório nominal'},
            {'id': '4-1', 'status': 'excluded', 'reason': 'procedimento'},
        ])
        first = editorial_queue.build_queue(self.root, self.today)
        board = first['scoreboard']
        self.assertEqual(board['inventory']['file'], 'chamber-vote-inventory-2026-10-11.json')
        self.assertEqual(board['counts'], {'candidates': 4, 'confirmed': 1, 'excluded': 1, 'pending': 1, 'unreviewed': 1})
        self.assertEqual([item['id'] for item in board['unreviewed']], ['5-1'])
        self.assertEqual(board['pending'][0]['reason'], 'sem relatório nominal')
        self.assertEqual(first['newSinceLastRun'], ['5-1'])
        self.assertTrue(first['attention'])
        self.assertEqual(board['typeGuardAlerts'][0]['pecTurnsOutsideCandidates'][0]['id'], '9-1')
        markdown = (self.reviews / 'editorial-queue.md').read_text(encoding='utf-8')
        self.assertIn('**1 sem revisão**', markdown)
        self.assertIn('| 2026-10-09 | 5-1 |', markdown)
        self.assertIn('accounts.json', markdown)
        # Segunda execução sem novidade: nada novo, mas os avisos de arquivo manual continuam.
        second = editorial_queue.build_queue(self.root, self.today)
        self.assertEqual(second['newSinceLastRun'], [])
        self.assertTrue(second['attention'])
        self.assertIn('"novos": []', editorial_queue.summary_line(second))

    def test_drafts_are_prefilled_kept_when_edited_and_dropped_when_reviewed(self):
        candidate = {**entry('5-1', '2026-10-09'), 'targetPropositions': [{'id': 77, 'siglaTipo': 'PLP', 'numero': 9, 'ano': 2026}]}
        self.inventory('2026-10-11', [entry('1-1', '2026-09-30'), candidate])
        self.write(self.reviews / 'chamber-vote-reviews-2026-10-09.json', [{'id': '1-1', 'status': 'confirmed', 'reviewedAt': '2026-10-09'}])
        queue = editorial_queue.build_queue(self.root, self.today)
        draft_path = self.reviews / 'chamber-vote-reviews-draft-2026-10-11.json'
        drafts = json.loads(draft_path.read_text(encoding='utf-8'))
        self.assertEqual(queue['scoreboard']['drafts'], {'file': draft_path.name, 'total': 1, 'added': ['5-1'], 'removed': []})
        self.assertEqual(drafts[0]['status'], 'draft')
        self.assertEqual(drafts[0]['sources']['proposition'], 'https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=77')
        self.assertEqual(drafts[0]['inventory']['proposition'], 'PLP 9/2026')
        self.assertIsNone(drafts[0]['title'])
        self.assertIn('rascunhos', editorial_queue.summary_line(queue))
        # A pessoa começa a editar: o rascunho não é sobrescrito na execução seguinte.
        drafts[0]['title'] = 'Em edição'
        draft_path.write_text(json.dumps(drafts), encoding='utf-8')
        editorial_queue.build_queue(self.root, self.today)
        self.assertEqual(json.loads(draft_path.read_text())[0]['title'], 'Em edição')
        # Revisão registrada: o rascunho sai do arquivo.
        self.write(self.reviews / 'chamber-vote-reviews-2026-10-11.json', [{'id': '5-1', 'status': 'pending', 'reason': 'conferir'}])
        queue = editorial_queue.build_queue(self.root, self.today)
        self.assertEqual(json.loads(draft_path.read_text()), [])
        self.assertEqual(queue['scoreboard']['drafts']['removed'], ['5-1'])

    def test_versioned_reviews_folder_is_read_and_wins_over_the_local_copy(self):
        from ingest.review_paths import find_review, review_files
        self.inventory('2026-10-11', [entry('1-1', '2026-09-30'), entry('2-1', '2026-10-01')])
        repo = self.root / 'reviews'
        repo.mkdir()
        self.write(repo / 'chamber-vote-reviews-2026-10-09.json', [{'id': '1-1', 'status': 'confirmed', 'reviewedAt': '2026-10-09'}])
        self.write(self.reviews / 'chamber-vote-reviews-2026-10-09.json', [{'id': '1-1', 'status': 'pending', 'reason': 'cópia antiga'}])
        self.write(self.reviews / 'chamber-vote-reviews-2026-10-10.json', [{'id': '2-1', 'status': 'excluded', 'reason': 'antiga'}])
        queue = editorial_queue.build_queue(self.root, self.today)
        counts = queue['scoreboard']['counts']
        self.assertEqual((counts['confirmed'], counts['excluded'], counts['unreviewed']), (1, 1, 0))
        self.assertEqual(find_review(self.root, 'chamber-vote-reviews-2026-10-09.json'), repo / 'chamber-vote-reviews-2026-10-09.json')
        self.assertEqual(find_review(self.root, 'chamber-vote-reviews-2026-10-10.json'), self.reviews / 'chamber-vote-reviews-2026-10-10.json')
        self.assertEqual(sorted(review_files(self.root)), ['chamber-vote-reviews-2026-10-09.json', 'chamber-vote-reviews-2026-10-10.json'])

    def test_missing_inventory_is_reported_not_zero(self):
        queue = editorial_queue.build_queue(self.root, self.today)
        self.assertEqual(queue['scoreboard']['status'], 'unavailable')
        self.assertTrue(queue['attention'])
        out = StringIO()
        with redirect_stdout(out):
            editorial_queue.main(['--root', str(self.root)])
        self.assertIn('"placar": "unavailable"', out.getvalue())

    def test_manual_file_warnings(self):
        self.write(self.root / 'data' / 'imports' / 'legislative.json', {'authorities': [
            {'id': 'senado:1', 'name': 'Senadora Nova', 'sourceId': 'senado_senators_current'},
            {'id': 'senado:2', 'name': 'Senador Antigo', 'sourceId': 'senado_senators_current'},
            {'id': 'camara:3', 'name': 'Deputado', 'sourceId': 'camara_deputies_current'}]})
        self.write(self.root / 'ingest' / 'senate_office_map.json', {'offices': [{'id': 'senado:2', 'office': 'Senador Antigo'}]})
        self.write(self.snapshots / 'accounts.json', {'year': 2024})
        self.write(self.snapshots / 'eleicoes-2026.json', {'segundoTurno': '2026-10-25', 'fonte': {'geradoNoTse': '07/10/2026 16:30:39'}})
        warnings = {w['file']: w for w in editorial_queue.manual_file_warnings(self.root, self.today)}
        self.assertIn('senado:1 (Senadora Nova)', warnings['ingest/senate_office_map.json']['action'])
        self.assertIn('2025', warnings['accounts.json']['issue'])
        self.assertNotIn('eleicoes-2026.json', warnings)  # antes do segundo turno
        after = {w['file'] for w in editorial_queue.manual_file_warnings(self.root, date(2026, 10, 26))}
        self.assertIn('eleicoes-2026.json', after)
        self.write(self.snapshots / 'eleicoes-2026.json', {'segundoTurno': '2026-10-25', 'fonte': {'geradoNoTse': '27/10/2026 10:00:00'}})
        self.write(self.snapshots / 'accounts.json', {'year': 2025})
        remaining = {w['file'] for w in editorial_queue.manual_file_warnings(self.root, date(2026, 10, 26))}
        self.assertEqual(remaining, {'ingest/senate_office_map.json'})


if __name__ == '__main__':
    unittest.main()
