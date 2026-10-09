import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import votes

_MISSING = object()


def vote(identifier, date_value, title, proposition, vote_type='PLP', themes=None):
    return {
        'id': identifier, 'date': date_value, 'proposition': proposition, 'type': vote_type,
        'title': title, 'summary': f'Resumo de {title}.', 'decisionLabel': 'Substitutivo',
        'yesMeaning': 'Aprovar o texto submetido.', 'noMeaning': 'Rejeitar o texto submetido.',
        'outcome': 'approved', 'tally': {'yes': 10, 'no': 2, 'abstention': None, 'total': 12},
        'themes': themes or [{'id': 'tributos', 'label': 'Tributos'}],
        'sources': {'vote': 'https://camara.leg.br/voto', 'rollCall': 'https://camara.leg.br/lista',
                    'text': 'https://camara.leg.br/texto', 'proposition': 'https://camara.leg.br/proposicao'},
        'reviewedAt': '2026-09-04T12:00:00Z',
        # These detail-only fields must never be returned by the summary API.
        'participants': [{'id': 'camara:1'}], 'partyTotals': [{'party': 'ABC'}],
    }


def snapshot(items=None, published_count=None, details_version=_MISSING):
    items = items or []
    result = {'schemaVersion': 1, 'generatedAt': '2026-10-09T12:00:00Z',
              'period': {'start': '2023-02-01', 'end': '2026-10-09'},
              'coverage': {'inventoryCount': 1500, 'candidateCount': 160, 'reviewedCount': 20,
                           'publishedCount': len(items) if published_count is None else published_count,
                           'pendingCount': 140, 'detail': 'Cobertura revisada da Câmara.'},
              'items': items}
    if details_version is not _MISSING:
        result['detailsVersion'] = details_version
    return result


class VoteSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.index = self.root / votes.INDEX_NAME
        self.items = [
            vote('2611313-31', '2026-09-03', 'Regras para benefícios tributários', 'PLP 74/2026'),
            vote('2600001-02', '2026-09-03', 'Proteção da infância', 'PL 20/2026', 'PL',
                 [{'id': 'protecao-social', 'label': 'Proteção social'}]),
            vote('2599999-01', '2026-08-12', 'Tributos sobre combustíveis', 'PLP 114/2026'),
        ]
        self.write(self.index, snapshot(self.items))

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def test_listing_filters_accent_insensitive_and_paginates_after_filtering(self):
        result = votes.listing({'q': 'BENEFICIOS tributarios', 'type': 'plp', 'page': '1', 'pageSize': '1'}, self.index)
        self.assertTrue(result['available'])
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['page'], 1)
        self.assertEqual(result['pageSize'], 1)
        self.assertEqual(result['pageCount'], 1)
        self.assertEqual(result['items'][0]['id'], '2611313-31')
        self.assertEqual(result['coverage']['publishedCount'], 3)

        page = votes.listing({'type': 'PLP', 'page': '2', 'pageSize': '1'}, self.index)
        self.assertEqual(page['total'], 2)
        self.assertEqual(page['items'][0]['id'], '2599999-01')
        self.assertEqual(page['pageCount'], 2)

    def test_listing_returns_available_filters_and_stable_date_order(self):
        result = votes.listing({}, self.index)
        self.assertEqual([item['id'] for item in result['items']], ['2600001-02', '2611313-31', '2599999-01'])
        self.assertEqual(result['filters']['types'], ['PL', 'PLP', 'PEC'])
        self.assertEqual(result['filters']['themes'], [
            {'id': 'protecao-social', 'label': 'Proteção social'}, {'id': 'tributos', 'label': 'Tributos'}])
        self.assertEqual(votes.listing({'theme': 'protecao-social'}, self.index)['total'], 1)

    def test_summary_projection_never_includes_participants_or_party_totals(self):
        result = votes.listing({}, self.index)
        serialized = json.dumps(result)
        self.assertNotIn('participants', serialized)
        self.assertNotIn('partyTotals', serialized)

    def test_optional_exclusion_count_preserves_old_snapshots_and_validates_new_coverage(self):
        self.assertNotIn('excludedCount', votes.listing({}, self.index)['coverage'])
        data = snapshot(self.items)
        data['coverage'].update(candidateCount=160, reviewedCount=150,
                                excludedCount=147, pendingCount=10)
        self.write(self.index, data)
        result = votes.listing({}, self.index)
        self.assertTrue(result['available'])
        self.assertEqual(result['coverage']['excludedCount'], 147)

        for value in (None, -1, True, '147', 146, 148):
            with self.subTest(excludedCount=value):
                data['coverage']['excludedCount'] = value
                self.write(self.index, data)
                self.assertFalse(votes.listing({}, self.index)['available'])

        data['coverage'].update(excludedCount=147, reviewedCount=149)
        self.write(self.index, data)
        self.assertFalse(votes.listing({}, self.index)['available'])

    def test_optional_missing_coverage_counts_preserve_old_snapshots_and_validate_new_coverage(self):
        keys = ('missingTextCount', 'missingAbstentionCount', 'missingThemeCount')
        coverage = votes.listing({}, self.index)['coverage']
        for key in keys:
            self.assertNotIn(key, coverage)

        data = snapshot(self.items)
        data['coverage'].update(missingTextCount=3, missingAbstentionCount=2, missingThemeCount=1)
        self.write(self.index, data)
        result = votes.listing({}, self.index)
        self.assertTrue(result['available'])
        for key, value in zip(keys, (3, 2, 1)):
            with self.subTest(key=key):
                self.assertEqual(result['coverage'][key], value)

        for key in keys:
            for value in (None, -1, True, '1', 4):
                with self.subTest(key=key, value=value):
                    data['coverage'][key] = value
                    self.write(self.index, data)
                    self.assertFalse(votes.listing({}, self.index)['available'])
            data['coverage'][key] = 0

    def test_text_source_may_be_null_and_optional_decision_source_is_preserved(self):
        item = dict(self.items[0])
        item['sources'] = {**item['sources'], 'text': None,
                           'decision': 'https://camara.leg.br/ordem-do-dia'}
        self.write(self.index, snapshot([item]))
        listed = votes.listing({}, self.index)
        self.assertTrue(listed['available'])
        self.assertIsNone(listed['items'][0]['sources']['text'])
        self.assertEqual(listed['items'][0]['sources']['decision'], 'https://camara.leg.br/ordem-do-dia')

        del item['sources']['decision']
        self.write(self.index, snapshot([item]))
        listed_without_decision = votes.listing({}, self.index)
        self.assertTrue(listed_without_decision['available'])
        self.assertNotIn('decision', listed_without_decision['items'][0]['sources'])

    def test_text_source_key_is_required_even_when_its_value_can_be_null(self):
        item = dict(self.items[0])
        item['sources'] = dict(item['sources'])
        del item['sources']['text']
        self.write(self.index, snapshot([item]))
        self.assertFalse(votes.listing({}, self.index)['available'])

    def test_optional_source_notes_are_preserved_and_invalid_notes_reject_the_snapshot(self):
        item = {**self.items[0], 'dataNotes': ['Votos conferidos no relatório nominal oficial.']}
        self.write(self.index, snapshot([item]))
        self.assertEqual(votes.listing({}, self.index)['items'][0]['dataNotes'], item['dataNotes'])
        for notes in (None, 'note', [''], [42], ['x' * 501], ['note'] * 5):
            with self.subTest(notes=notes):
                self.write(self.index, snapshot([{**item, 'dataNotes': notes}]))
                self.assertFalse(votes.listing({}, self.index)['available'])

    def test_detail_reads_per_vote_file_only_when_requested_and_handles_unavailable_details(self):
        details_path = self.root / votes.DETAILS_DIRECTORY / '2611313-31.json'
        self.write(details_path, {'id': '2611313-31', 'participants': [
            {'id': 'camara:1', 'name': 'Ana Deputada', 'party': 'ABC', 'uf': 'SP', 'vote': 'Sim'}],
            'partyTotals': [{'party': 'ABC', 'yes': 1, 'no': 0, 'other': 0}]})
        original_loader = votes._load_json
        loaded_paths = []

        def recording_loader(path):
            loaded_paths.append(Path(path).name)
            return original_loader(path)

        with patch.object(votes, '_load_json', side_effect=recording_loader):
            listing = votes.listing({}, self.index)
            self.assertEqual(loaded_paths, [votes.INDEX_NAME])
            self.assertNotIn('participants', json.dumps(listing))
            detail = votes.detail('2611313-31', self.index)
        self.assertIn('2611313-31.json', loaded_paths)
        self.assertTrue(detail['participantsAvailable'])
        self.assertEqual(detail['participants'][0]['vote'], 'Sim')
        self.assertEqual(detail['partyTotals'][0]['yes'], 1)

        details_path.write_text('{invalid', encoding='utf-8')
        unavailable = votes.detail('2611313-31', self.index)
        self.assertTrue(unavailable['available'])
        self.assertFalse(unavailable['participantsAvailable'])
        self.assertEqual(unavailable['vote']['id'], '2611313-31')
        self.assertEqual(unavailable['participants'], [])

    def test_detail_uses_selected_generation_and_tracks_index_switch_without_leaking_version(self):
        first_version, second_version = 'a' * 64, 'b' * 64
        first_details = {'participants': [
            {'id': 'camara:1', 'name': 'Primeira versão', 'party': 'ABC', 'uf': 'SP', 'vote': 'Sim'}],
            'partyTotals': []}
        first_path = self.root / votes.DETAILS_DIRECTORY / first_version / '2611313-31.json'
        self.write(first_path, {'id': '2611313-31', **first_details})
        self.write(self.index, snapshot([self.items[0]], details_version=first_version))
        self.assertEqual(votes._index(self.index)['detailsVersion'], first_version)
        first = votes.detail('2611313-31', self.index)
        self.assertTrue(first['participantsAvailable'])
        self.assertEqual(first['participants'][0]['name'], 'Primeira versão')
        self.assertNotIn('detailsVersion', first)
        self.assertNotIn('detailsVersion', first['vote'])

        second_path = self.root / votes.DETAILS_DIRECTORY / second_version / '2611313-31.json'
        second_details = {'participants': [
            {'id': 'camara:2', 'name': 'Segunda versão', 'party': 'DEF', 'uf': 'RJ', 'vote': 'Não'}],
            'partyTotals': []}
        self.write(second_path, {'id': '2611313-31', **second_details})
        self.write(self.index, snapshot([self.items[0]], details_version=second_version))
        second = votes.detail('2611313-31', self.index)
        self.assertTrue(second['participantsAvailable'])
        self.assertEqual(second['participants'][0]['name'], 'Segunda versão')
        self.assertNotIn('detailsVersion', json.dumps(votes.listing({}, self.index)))
        self.assertNotIn('detailsVersion', json.dumps(second))

    def test_invalid_details_version_makes_index_unavailable(self):
        for version in ('A' * 64, 'a' * 63, 'g' * 64, None, 123):
            with self.subTest(version=version):
                self.write(self.index, snapshot([self.items[0]], details_version=version))
                self.assertFalse(votes.listing({}, self.index)['available'])

    def test_generation_symlink_escape_keeps_summary_and_marks_details_unavailable(self):
        version = 'c' * 64
        outside = self.root / 'outside'
        outside.mkdir()
        self.write(outside / '2611313-31.json', {
            'id': '2611313-31', 'participants': [], 'partyTotals': []})
        generation_link = self.root / votes.DETAILS_DIRECTORY / version
        generation_link.parent.mkdir(parents=True, exist_ok=True)
        try:
            generation_link.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'symlinks unavailable: {error}')
        self.write(self.index, snapshot([self.items[0]], details_version=version))
        result = votes.detail('2611313-31', self.index)
        self.assertTrue(result['available'])
        self.assertFalse(result['participantsAvailable'])
        self.assertEqual(result['vote']['id'], '2611313-31')

    def test_unknown_and_traversal_ids_are_rejected_without_reading_detail_files(self):
        self.assertIsNone(votes.detail('../2611313-31', self.index))
        self.assertIsNone(votes.detail('2611313-31/../../secret', self.index))
        self.assertIsNone(votes.detail('2611313-30', self.index))

    def test_snapshot_cache_tracks_path_updates_removal_and_empty_vs_missing(self):
        first_path = self.root / 'first.json'
        second_path = self.root / 'second.json'
        self.write(first_path, snapshot([self.items[0]]))
        original_stat = first_path.stat()
        self.write(second_path, snapshot([self.items[1]]))
        self.assertEqual(votes.listing({}, first_path)['items'][0]['id'], '2611313-31')
        self.assertEqual(votes.listing({}, second_path)['items'][0]['id'], '2600001-02')

        replacement = snapshot([self.items[2]])
        self.write(first_path, replacement)
        stat = first_path.stat()
        os.utime(first_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1_000_000_000))
        self.assertEqual(votes.listing({}, first_path)['items'][0]['id'], '2599999-01')
        first_path.unlink()
        self.assertFalse(votes.listing({}, first_path)['available'])

        empty_path = self.root / 'empty.json'
        self.write(empty_path, snapshot([]))
        empty = votes.listing({}, empty_path)
        self.assertTrue(empty['available'])
        self.assertEqual(empty['items'], [])
        self.assertFalse(votes.listing({}, self.root / 'absent.json')['available'])

    def test_malformed_published_summary_makes_the_index_unavailable(self):
        self.write(self.index, snapshot([self.items[0]], published_count=2))
        self.assertFalse(votes.listing({}, self.index)['available'])


if __name__ == '__main__':
    unittest.main()
