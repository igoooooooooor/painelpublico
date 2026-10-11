import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest import pipeline  # noqa: E402

YEAR = 2026


def document(deputies=5, senators=3, expenses_per_person=4, chamber_status='partial', senate_status='partial',
             roster_status='imported', period=f'{YEAR} (parcial, ano em andamento)'):
    """Documento no formato de ingest/legislative.py: listas oficiais e notas da cota."""
    sources = [
        {'id': 'camara_deputies_current', 'label': 'Câmara: lista', 'url': 'https://dadosabertos.camara.leg.br',
         'scope': 'lista', 'period': 'atual', 'status': roster_status, 'detail': '', 'fetchedAt': '2026-10-11T08:00:00+00:00'},
        {'id': 'camara_ceap', 'label': 'Câmara: CEAP', 'url': 'https://www.camara.leg.br/cotas', 'scope': 'cota',
         'period': period, 'status': chamber_status, 'detail': '', 'fetchedAt': '2026-10-11T08:00:00+00:00'},
        {'id': 'senado_senators_current', 'label': 'Senado: lista', 'url': 'https://legis.senado.leg.br',
         'scope': 'lista', 'period': 'atual', 'status': roster_status, 'detail': '', 'fetchedAt': '2026-10-11T08:00:00+00:00'},
        {'id': 'senado_ceaps', 'label': 'Senado: CEAPS', 'url': 'https://adm.senado.gov.br', 'scope': 'cota',
         'period': period, 'status': senate_status, 'detail': '', 'fetchedAt': '2026-10-11T08:00:00+00:00'},
    ]
    authorities, expenses = [], []
    for house, count, role, source in (('camara', deputies, 'deputado', 'camara_deputies_current'),
                                       ('senado', senators, 'senador', 'senado_senators_current')):
        for i in range(count):
            authorities.append({'id': f'{house}:{i}', 'name': f'Pessoa {house} {i}', 'role': role, 'sphere': 'federal',
                                'branch': 'legislativo', 'institution': house, 'uf': 'SP', 'sourceId': source})
            for month in range(1, expenses_per_person + 1):
                expenses.append({'id': f'{house}:{i}:{month}', 'authorityId': f'{house}:{i}',
                                 'sourceId': 'camara_ceap' if house == 'camara' else 'senado_ceaps',
                                 'year': YEAR, 'month': month, 'date': f'{YEAR}-{month:02d}-10', 'category': 'Escritório',
                                 'kind': 'reembolso', 'amount': 100 + i,
                                 'supplier': {'key': 'x', 'name': 'Empresa', 'cnpj': '12345678000199'}})
    return {'sources': sources, 'authorities': authorities, 'expenses': expenses}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mail_environ = {'PAINEL_MAIL_TO': 'a@x.br', 'PAINEL_SMTP_HOST': 'smtp.x.br'}
        self.config = pipeline.PipelineConfig(data_dir=self.root / 'data', db_path=self.root / 'data' / 'live.sqlite3',
                                              year=YEAR, environ=dict(self.mail_environ))
        self.sent = []
        self.collector_exit = 0
        self.next_document = document()
        self.snapshot_calls = []
        self.snapshot_results = {'ingest/profiles.py': (0, 'arquivos anuais: completo=True projetos=4\nsnapshot perfis=8')}

    def tearDown(self):
        self.temp.cleanup()

    # O coletor real faz rede; aqui ele grava o documento preparado e devolve o código combinado.
    def fake_collector(self, config):
        config.document_path.parent.mkdir(parents=True, exist_ok=True)
        config.document_path.write_text(json.dumps(self.next_document), encoding='utf-8')
        return subprocess.CompletedProcess(['legislative'], self.collector_exit, stdout='{}', stderr='')

    def fake_mail(self, mail, subject, body):
        self.sent.append((mail, subject, body))

    # Os coletores de snapshot (perfis e situação) também são subprocessos; aqui respondem conforme combinado.
    def fake_snapshot_collector(self, config, arguments, timeout=None):
        self.snapshot_calls.append(arguments)
        key = arguments[1] if arguments[0] == '-m' else arguments[0]
        code, stdout = self.snapshot_results.get(key, (0, ''))
        return subprocess.CompletedProcess(list(arguments), code, stdout=stdout, stderr='')

    def run_daily(self, config=None):
        with mock.patch.object(pipeline, 'run_collector', self.fake_collector), \
                mock.patch.object(pipeline, 'run_snapshot_collector', self.fake_snapshot_collector), \
                redirect_stdout(StringIO()):
            return pipeline.run_daily(config or self.config, mail_sender=self.fake_mail)

    def counts(self):
        with closing(sqlite3.connect(self.config.db_path)) as db:
            roster = db.execute('SELECT COUNT(*) FROM roster').fetchone()[0]
            expenses = db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0]
        return roster, expenses

    def test_first_run_creates_database_status_and_no_mail_on_success(self):
        status = self.run_daily()
        self.assertEqual(status['result'], 'ok', status)
        self.assertEqual(self.counts(), (8, 32))
        self.assertEqual([s['name'] for s in status['steps']],
                         ['collect', 'validate', 'backup', 'stage', 'import', 'verify', 'publish',
                          'profiles', 'project-status', 'senate-projects', 'senate-activity', 'notify'])
        self.assertEqual([call[0] for call in self.snapshot_calls],
                         ['ingest/profiles.py', 'ingest/project_status.py', 'ingest/senate_projects.py', 'ingest/senate_activity.py'])
        self.assertIn('--max-age-hours', self.snapshot_calls[1])
        self.assertEqual(status['summary']['roster'], {'camara_deputies_current': 5, 'senado_senators_current': 3})
        self.assertEqual(json.loads(self.config.status_path.read_text())['result'], 'ok')
        self.assertEqual(len(self.config.history_path.read_text().splitlines()), 1)
        self.assertEqual(self.sent, [])
        self.assertFalse(self.config.work_db.exists())
        self.assertEqual(list(self.config.backups_dir.glob('*.sqlite3')) if self.config.backups_dir.exists() else [], [])

    def test_second_run_backs_up_prunes_and_updates_in_place(self):
        self.run_daily()
        self.next_document = document(expenses_per_person=5)
        config = pipeline.PipelineConfig(**{**self.config.__dict__, 'keep_backups': 1})
        self.run_daily(config)
        self.assertEqual(self.counts(), (8, 40))
        backups = list(self.config.backups_dir.glob('na-lupa-daily-*.sqlite3'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0], 32)
        self.run_daily(config)
        self.assertEqual(len(list(self.config.backups_dir.glob('na-lupa-daily-*.sqlite3'))), 1)

    def test_roster_drop_is_refused_and_live_database_is_kept(self):
        self.run_daily()
        self.next_document = document(deputies=2)
        status = self.run_daily()
        self.assertEqual(status['result'], 'failed')
        self.assertIn('camara_deputies_current caiu de 5 para 2', status['error'])
        self.assertEqual(self.counts(), (8, 32))
        self.assertEqual(len(self.sent), 1)
        self.assertIn('FALHOU', self.sent[0][1])
        self.assertIn('Regressão detectada', self.sent[0][2])
        self.assertFalse(self.config.work_db.exists())

    def test_expense_drop_is_refused_but_unavailable_source_keeps_previous_rows(self):
        self.run_daily()
        self.next_document = document(expenses_per_person=2)
        self.assertEqual(self.run_daily()['result'], 'failed')
        self.assertEqual(self.counts(), (8, 32))
        self.sent.clear()
        # Fonte indisponível: a importação preserva as notas anteriores e a execução fica parcial, com aviso.
        unavailable = document(expenses_per_person=4, senate_status='unavailable')
        unavailable['expenses'] = [e for e in unavailable['expenses'] if e['sourceId'] != 'senado_ceaps']
        self.next_document, self.collector_exit = unavailable, 1
        status = self.run_daily()
        self.assertEqual(status['result'], 'partial')
        self.assertEqual(self.counts(), (8, 32))
        self.assertEqual(len(self.sent), 1)
        self.assertIn('parcial', self.sent[0][1])
        self.assertIn('senado_ceaps', self.sent[0][2])

    def test_document_of_another_year_is_not_imported(self):
        self.run_daily()
        self.next_document = document(period='2025')
        status = self.run_daily()
        self.assertEqual(status['result'], 'failed')
        self.assertIn('2025', status['error'])
        self.assertEqual([s['name'] for s in status['steps'] if s['status'] == 'failed'], ['validate'])
        self.assertEqual(self.counts(), (8, 32))

    def test_collector_crash_and_missing_document_fail_before_import(self):
        self.collector_exit = 2
        status = self.run_daily()
        self.assertEqual(status['result'], 'failed')
        self.assertIn('código 2', status['error'])
        self.assertFalse(self.config.db_path.exists())

    def test_dry_run_leaves_published_database_untouched(self):
        self.run_daily()
        self.next_document = document(expenses_per_person=5)
        status = self.run_daily(pipeline.PipelineConfig(**{**self.config.__dict__, 'dry_run': True}))
        self.assertEqual(status['result'], 'ok')
        self.assertEqual(self.counts(), (8, 32))
        self.assertIn('dry-run', next(s for s in status['steps'] if s['name'] == 'publish')['skipped'])

    def test_pending_journal_blocks_publication(self):
        self.run_daily()
        journal = Path(str(self.config.db_path) + '-journal')
        journal.write_bytes(b'')
        status = self.run_daily()
        self.assertEqual(status['result'], 'failed')
        self.assertIn('journal', status['error'])

    def test_concurrent_run_is_refused(self):
        with pipeline.Lock(self.config.lock_path):
            status = self.run_daily(pipeline.PipelineConfig(**{**self.config.__dict__, 'lock_wait_seconds': 0}))
        self.assertEqual(status['result'], 'failed')
        self.assertIn('em andamento', status['error'])
        self.assertEqual(status['steps'], [{**status['steps'][0]}])  # só o registro de aviso

    def test_snapshot_collectors_run_after_publish_and_failures_are_partial(self):
        self.snapshot_results['ingest/project_status.py'] = (1, 'Nenhuma situação consultada disponível')
        status = self.run_daily()
        self.assertEqual(status['result'], 'partial')
        self.assertEqual(self.counts(), (8, 32))
        statuses = {s['name']: s['status'] for s in status['steps']}
        self.assertEqual((statuses['publish'], statuses['profiles'], statuses['project-status']), ('ok', 'ok', 'partial'))
        self.assertIn('código 1', self.sent[0][2])
        # Arquivos anuais incompletos: perfis avisam no stdout e a execução fica parcial.
        self.sent.clear()
        self.snapshot_results = {'ingest/profiles.py': (0, 'arquivos anuais: completo=False projetos=4')}
        status = self.run_daily()
        self.assertEqual(status['result'], 'partial')
        self.assertIn('Arquivos anuais incompletos', self.sent[0][2])
        # Falha do banco pula os snapshots; --db-only também.
        self.snapshot_calls.clear()
        self.next_document = document(period='2025')
        self.run_daily()
        self.assertEqual(self.snapshot_calls, [])
        self.next_document = document()
        self.run_daily(pipeline.PipelineConfig(**{**self.config.__dict__, 'db_only': True}))
        self.assertEqual(self.snapshot_calls, [])

    def test_lock_waits_for_the_other_job(self):
        import threading
        held = pipeline.Lock(self.config.lock_path)
        held.__enter__()
        threading.Timer(0.3, held.__exit__, args=(None, None, None)).start()
        with mock.patch.object(pipeline, 'LOCK_WAIT_SECONDS', 5):
            with pipeline.Lock(self.config.lock_path, wait_seconds=5, poll_seconds=0.05):
                pass

    def test_monthly_runs_the_chain_in_order_and_imports_history_through_a_work_copy(self):
        self.run_daily()
        self.snapshot_calls.clear()
        with mock.patch.dict('os.environ', {'PAINEL_TODAY': '2026-10-11'}):
            with mock.patch.object(pipeline, 'run_collector', self.fake_collector), \
                    mock.patch.object(pipeline, 'run_snapshot_collector', self.fake_snapshot_collector), \
                    redirect_stdout(StringIO()):
                status = pipeline.run_monthly(self.config, mail_sender=self.fake_mail)
        self.assertEqual(status['result'], 'ok', status)
        self.assertEqual(status['period'], '2026-09')
        names = [s['name'] for s in status['steps']]
        self.assertEqual(names[:4], ['legislative-2023', 'legislative-2024', 'legislative-2025', 'quota-history'])
        self.assertEqual(names[4:9], ['backup', 'stage', 'import-history', 'verify', 'publish'])
        self.assertEqual(names[9:12], ['payroll-2023', 'housing-2023', 'service-2023'])
        self.assertEqual(names[-11:], ['chamber-mandate-history', 'mandate-cost', 'senate-office-pilot', 'senate-cost',
                                       'senate-attendance', 'senate-activity', 'senate-participation', 'tenure',
                                       'state-tax-revenue', 'build', 'notify'])
        history_call = next(call for call in self.snapshot_calls if call[:2] == ('-m', 'backend.quota_history'))
        self.assertEqual(history_call[2:], ('--db', str(self.config.work_db)))
        payroll_2023 = next(call for call in self.snapshot_calls if call[0] == 'ingest/chamber_payroll.py')
        self.assertIn('data/snapshots/chamber-payroll-2023.json', payroll_2023)
        payroll_2026 = [call for call in self.snapshot_calls if call[0] == 'ingest/chamber_payroll.py'][-1]
        self.assertEqual(payroll_2026, ('ingest/chamber_payroll.py', '--collect', '--year', '2026'))
        self.assertEqual(self.counts(), (8, 32))
        self.assertTrue((self.config.status_dir / 'monthly.json').exists())
        self.assertEqual(self.sent, [])

    def test_monthly_failures_are_partial_and_history_import_failure_keeps_the_database(self):
        self.run_daily()
        self.sent.clear()
        self.snapshot_results['backend.quota_history'] = (1, '')
        self.snapshot_results['ingest/senate_attendance.py'] = (2, 'pdfplumber ausente')
        with mock.patch.object(pipeline, 'run_collector', self.fake_collector), \
                mock.patch.object(pipeline, 'run_snapshot_collector', self.fake_snapshot_collector), \
                redirect_stdout(StringIO()):
            status = pipeline.run_monthly(pipeline.PipelineConfig(**{**self.config.__dict__, 'period': (2026, 8)}),
                                          mail_sender=self.fake_mail)
        self.assertEqual(status['result'], 'failed')
        self.assertIn('histórico da cota', status['error'])
        statuses = {s['name']: s['status'] for s in status['steps']}
        self.assertEqual((statuses['import-history'], statuses['senate-attendance'], statuses['build']), ('failed', 'partial', 'ok'))
        self.assertEqual(self.counts(), (8, 32))
        self.assertFalse(self.config.work_db.exists())
        self.assertIn('Atualização mensal FALHOU', self.sent[0][1])
        self.assertIn('2026-08', self.sent[0][2])
        # --only/--skip limitam a cadeia.
        self.snapshot_calls.clear()
        with mock.patch.object(pipeline, 'run_collector', self.fake_collector), \
                mock.patch.object(pipeline, 'run_snapshot_collector', self.fake_snapshot_collector), \
                redirect_stdout(StringIO()):
            status = pipeline.run_monthly(pipeline.PipelineConfig(**{**self.config.__dict__, 'only': ('senate-cost', 'build')}),
                                          mail_sender=self.fake_mail)
        self.assertEqual([call[0] for call in self.snapshot_calls], ['ingest/senate_cost.py', 'scripts/build.py'])

    def test_weekly_runs_inventory_and_mails_when_the_queue_has_news(self):
        self.snapshot_results['ingest.editorial_queue'] = (0, 'resumo: {"placar": "ok", "candidatos": 12, "semRevisao": 2, '
                                                            '"pendentes": 1, "novos": ["7-1"], "arquivosManuais": ["arrecadacao.json"], "atencao": true}\nfila: x')
        with mock.patch.dict('os.environ', {'PAINEL_TODAY': '2026-10-11'}), \
                mock.patch.object(pipeline, 'run_snapshot_collector', self.fake_snapshot_collector), redirect_stdout(StringIO()):
            status = pipeline.run_weekly(self.config, mail_sender=self.fake_mail)
        self.assertEqual(status['result'], 'ok')
        self.assertEqual([s['name'] for s in status['steps']], ['vote-inventory', 'editorial-queue', 'notify'])
        self.assertEqual(self.snapshot_calls[0], ('-m', 'ingest.chamber_vote_inventory', '--collect', '--year', '2026', '--through', '2026-10-11'))
        self.assertEqual(status['summary']['editorial']['novos'], ['7-1'])
        self.assertEqual(len(self.sent), 1)
        self.assertIn('Atualização semanal concluída', self.sent[0][1])
        self.assertIn('Novos sem revisão desde a fila anterior: 7-1', self.sent[0][2])
        self.assertIn('arrecadacao.json', self.sent[0][2])
        self.assertTrue((self.config.status_dir / 'weekly.json').exists())
        # Sem novidade e sem avisos: nada de e-mail.
        self.sent.clear()
        self.snapshot_results['ingest.editorial_queue'] = (0, 'resumo: {"placar": "ok", "candidatos": 12, "semRevisao": 0, '
                                                            '"pendentes": 0, "novos": [], "arquivosManuais": [], "atencao": false}')
        with mock.patch.object(pipeline, 'run_snapshot_collector', self.fake_snapshot_collector), redirect_stdout(StringIO()):
            status = pipeline.run_weekly(self.config, mail_sender=self.fake_mail)
        self.assertEqual((status['result'], self.sent), ('ok', []))
        # Inventário indisponível: parcial com e-mail; fila que não gera é falha.
        self.snapshot_results['ingest.chamber_vote_inventory'] = (1, 'erro de rede')
        self.snapshot_results['ingest.editorial_queue'] = (2, '')
        with mock.patch.object(pipeline, 'run_snapshot_collector', self.fake_snapshot_collector), redirect_stdout(StringIO()):
            status = pipeline.run_weekly(self.config, mail_sender=self.fake_mail)
        self.assertEqual(status['result'], 'failed')
        self.assertIn('Fila editorial não gerada', status['error'])

    def test_weekly_runs_due_events_and_reports_them(self):
        self.snapshot_results['ingest.editorial_queue'] = (0, 'resumo: {"placar": "ok", "candidatos": 1, "semRevisao": 0, '
                                                            '"pendentes": 0, "novos": [], "arquivosManuais": [], "atencao": false}')
        due = {'id': 'second-round-2026', 'date': '2026-10-25', 'label': 'Segundo turno', 'status': 'due', 'detail': 'pendente',
               'actions': [{'name': 'event-elections', 'arguments': ['ingest/elections_2026.py', '--collect']}]}
        done = {**due, 'status': 'done', 'detail': 'feito'}
        done.pop('actions')
        quiet = {'id': 'legislature-58', 'date': '2027-02-01', 'label': 'Troca', 'status': 'not_due', 'detail': 'posse'}
        answers = iter([[due, quiet], [done, quiet]])
        with mock.patch.object(pipeline.calendar_events, 'pending_events', side_effect=lambda *a, **k: next(answers)), \
                mock.patch.object(pipeline, 'run_snapshot_collector', self.fake_snapshot_collector), redirect_stdout(StringIO()):
            status = pipeline.run_weekly(self.config, mail_sender=self.fake_mail)
        self.assertEqual(status['result'], 'ok')
        self.assertEqual([s['name'] for s in status['steps']], ['vote-inventory', 'editorial-queue', 'event-elections', 'notify'])
        self.assertEqual(self.snapshot_calls[-1], ('ingest/elections_2026.py', '--collect'))
        self.assertEqual(status['summary']['events']['events'][0]['status'], 'done')
        self.assertEqual(self.sent, [])  # sem pendência restante, sem aviso
        # Evento que continua pendente (fonte ainda não regenerada) avisa.
        self.sent.clear()
        answers = iter([[due, quiet], [due, quiet]])
        with mock.patch.object(pipeline.calendar_events, 'pending_events', side_effect=lambda *a, **k: next(answers)), \
                mock.patch.object(pipeline, 'run_snapshot_collector', self.fake_snapshot_collector), redirect_stdout(StringIO()):
            pipeline.run_weekly(self.config, mail_sender=self.fake_mail)
        self.assertEqual(len(self.sent), 1)
        self.assertIn('second-round-2026: due', self.sent[0][2])

    def test_roster_guard_relaxes_in_the_first_weeks_of_a_legislature(self):
        self.run_daily()
        self.next_document = document(deputies=3, expenses_per_person=7)  # lista 40% menor: recusada em dia comum
        self.assertEqual(self.run_daily()['result'], 'failed')
        with mock.patch.dict('os.environ', {'PAINEL_TODAY': '2027-02-10'}):
            status = self.run_daily()
        self.assertEqual(status['result'], 'ok', status['error'])
        self.assertIn('legislatura', status['summary']['turnover'])
        self.assertEqual(self.counts()[0], 6)
        # Lista vazia continua sem substituir a anterior (regra da importação), mesmo na janela.
        self.next_document = document(deputies=0, chamber_status='unavailable', expenses_per_person=7)
        with mock.patch.dict('os.environ', {'PAINEL_TODAY': '2027-02-10'}):
            status = self.run_daily()
        self.assertEqual(status['result'], 'partial')
        self.assertEqual(self.counts()[0], 6)

    def test_mail_config_and_report(self):
        self.assertIsNone(pipeline.MailConfig.from_environ({}))
        mail = pipeline.MailConfig.from_environ({'PAINEL_MAIL_TO': 'a@x.br, b@x.br', 'PAINEL_SMTP_HOST': 'smtp.x.br',
                                                 'PAINEL_SMTP_PORT': '465', 'PAINEL_SMTP_SECURITY': 'SSL',
                                                 'PAINEL_SMTP_USER': 'u', 'PAINEL_SMTP_PASSWORD': 'p',
                                                 'PAINEL_MAIL_ON_SUCCESS': '1'})
        self.assertEqual((mail.to, mail.sender, mail.port, mail.security, mail.on_success),
                         (['a@x.br', 'b@x.br'], 'u', 465, 'ssl', True))
        self.config.environ['PAINEL_MAIL_ON_SUCCESS'] = 'sim'
        status = self.run_daily()
        self.assertEqual(status['result'], 'ok')
        self.assertEqual(len(self.sent), 1)
        subject, body = self.sent[0][1], self.sent[0][2]
        self.assertTrue(subject.startswith('[Painel Público] Atualização diária concluída em '), subject)
        self.assertIn('lista camara_deputies_current: 5', body)
        self.assertIn('notas senado_ceaps: 12', body)
        self.assertIn('publish: ok', body)

    def test_mail_failure_is_recorded_without_hiding_the_result(self):
        def broken(mail, subject, body):
            raise OSError('smtp down')
        self.next_document = document(deputies=0, roster_status='unavailable')
        with mock.patch.object(pipeline, 'run_collector', self.fake_collector), redirect_stdout(StringIO()):
            status = pipeline.run_daily(self.config, mail_sender=broken)
        notify = status['steps'][-1]
        self.assertEqual(notify['name'], 'notify')
        self.assertEqual(notify['status'], 'failed')
        self.assertIn('smtp down', notify['mail'])

    def test_notify_failure_uses_last_status(self):
        self.next_document = document(period='2025')
        self.run_daily()
        code = pipeline.notify_failure(self.config, 'painel-ingest.service', mail_sender=self.fake_mail)
        self.assertEqual(code, 0)
        self.assertIn('painel-ingest.service falhou', self.sent[-1][1])
        self.assertIn('2025', self.sent[-1][2])

    def test_cli_exit_code_is_zero_for_partial_and_one_for_failed(self):
        self.collector_exit = 1
        unavailable = document(senate_status='unavailable')
        unavailable['expenses'] = [e for e in unavailable['expenses'] if e['sourceId'] != 'senado_ceaps']
        self.next_document = unavailable
        with mock.patch.object(pipeline, 'run_collector', self.fake_collector), \
                mock.patch.object(pipeline, 'run_snapshot_collector', self.fake_snapshot_collector), \
                mock.patch.object(pipeline, 'send_mail', self.fake_mail), redirect_stdout(StringIO()):
            code = pipeline.main(['--db', str(self.config.db_path), '--data-dir', str(self.config.data_dir), 'daily', '--year', str(YEAR)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.config.status_path.read_text())['result'], 'partial')
        self.next_document = document(period='2025')
        with mock.patch.object(pipeline, 'run_collector', self.fake_collector), \
                mock.patch.object(pipeline, 'send_mail', self.fake_mail), redirect_stdout(StringIO()):
            code = pipeline.main(['--db', str(self.config.db_path), '--data-dir', str(self.config.data_dir), 'daily', '--year', str(YEAR)])
        self.assertEqual(code, 1)

    def test_cli_status_reports_last_run(self):
        self.run_daily()
        out = StringIO()
        with redirect_stdout(out):
            code = pipeline.main(['--db', str(self.config.db_path), '--data-dir', str(self.config.data_dir), 'status'])
        self.assertEqual(code, 1)  # o mensal nunca rodou
        self.assertEqual(json.loads(out.getvalue())['daily']['result'], 'ok')
        self.assertEqual(json.loads(out.getvalue())['monthly']['status'], 'nunca executado')
        self.assertEqual(json.loads(out.getvalue())['weekly']['status'], 'nunca executado')


class MonthlyReleaseStepTests(unittest.TestCase):
    def steps(self, environ, dry_run=False):
        config = pipeline.PipelineConfig(environ=environ, dry_run=dry_run)
        return {name: arguments for name, arguments, _timeout in pipeline.monthly_steps(config)}

    def test_publish_data_runs_last_only_when_enabled(self):
        self.assertNotIn('publish-data', self.steps({}))
        self.assertNotIn('publish-data', self.steps({'PAINEL_DATA_RELEASE': '0'}))
        config = pipeline.PipelineConfig(environ={'PAINEL_DATA_RELEASE': '1'})
        names = [name for name, _arguments, _timeout in pipeline.monthly_steps(config)]
        self.assertEqual(names[-2:], ['build', 'publish-data'])
        self.assertEqual(self.steps({'PAINEL_DATA_RELEASE': 'sim'})['publish-data'], ('scripts/publish_data.py',))
        self.assertEqual(self.steps({'PAINEL_DATA_RELEASE': '1'}, dry_run=True)['publish-data'],
                         ('scripts/publish_data.py', '--dry-run'))


if __name__ == '__main__':
    unittest.main()
