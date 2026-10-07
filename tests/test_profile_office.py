import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ingest.profile_office import load_office, parse_office


class OfficeProfileTests(unittest.TestCase):
    def test_office_does_not_read_the_quota_or_salary_as_staff_spending(self):
        page = '''<div>Cota parlamentar ? Percentual Gasto 9.999,00 10%</div>
            <div>Verba de gabinete ? Percentual gasto Verba de gabinete Total (R$)
            Percentual Gasto 1.015,50 90% Não utilizado 100,00 10%
            Gasto mensal JAN 500,25 50% FEV 515,25 51% Veja mais</div>
            Pessoal de gabinete ? 17 pessoas neste ano, sendo 12 ativas atualmente
            Salário mensal bruto ? R$ 46.366,19
            Informações de gastos atualizadas em 07/10/2026 05:03'''
        data = parse_office(page, 'https://example.gov.br', '2026-10-07')
        self.assertEqual(data['amount'], 1015.5)
        self.assertEqual(data['months'], {'1': 500.25, '2': 515.25})
        self.assertEqual(data['staffActive'], 12)
        self.assertEqual(data['sourceUpdatedAt'], '07/10/2026')
        self.assertEqual(data['status'], 'imported')

    def test_missing_fields_remain_missing_but_published_zero_is_preserved(self):
        absent = parse_office('Cota parlamentar ? Percentual Gasto 9.999,00 10%', '', '')
        self.assertIsNone(absent['amount'])
        self.assertIsNone(absent['staffActive'])
        zero = parse_office('Verba de gabinete ? Percentual Gasto 0,00 0% Veja mais', '', '')
        self.assertEqual(zero['amount'], 0)
        self.assertEqual(zero['status'], 'partial')

    def test_refresh_failure_preserves_previous_observation_and_its_date(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = {'status': 'imported', 'amount': 25, 'fetchedAt': '2026-09-01'}
            cache = root / 'office-1-2026.json'
            cache.write_text(json.dumps(original))
            with patch('ingest.profile_office.urllib.request.urlopen', side_effect=OSError('offline')):
                updated = load_office('1', root, collect=True, refresh=True)
            self.assertEqual(updated['amount'], 25)
            self.assertEqual(updated['fetchedAt'], '2026-09-01')
            self.assertTrue(updated['stale'])
            self.assertEqual(json.loads(cache.read_text()), original)


if __name__ == '__main__':
    unittest.main()
