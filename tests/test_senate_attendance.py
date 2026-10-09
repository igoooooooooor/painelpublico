import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ingest import senate_attendance as attendance


def roster(*rows):
    return {"authorities": [
        {
            "id": identifier,
            "name": name,
            "role": "senador",
            "sourceId": attendance.SOURCE_ID,
            "party": party,
            "uf": state,
        }
        for identifier, name, party, state in rows
    ]}


def agenda_event(code="700", session_date="2026-01-15", kind="SESSÃO DELIBERATIVA ORDINÁRIA", *, status="Sim"):
    return f"""<Sessao><Data>{session_date}</Data><TipoSessao>{kind}</TipoSessao>
    <CodigoSessao>{code}</CodigoSessao><Casa>SF</Casa><SituacaoSessao>Encerrada</SituacaoSessao>
    <Realizada><Status>{status}</Status></Realizada></Sessao>"""


def diary_page(text, marks, *, kind="Ordinária", ordinal=4, table_title="REGISTRO DE COMPARECIMENTO E VOTO"):
    return {
        "text": f"""Senado Federal
{table_title}
Partido UF Nome Senador
{ordinal}ª Sessão Deliberativa {kind}, às 14 horas
Presenças no período: 15/01/2026 07:00:00 até 15/01/2026 20:00:59
Votos no período: 15/01/2026 07:00:00 até 15/01/2026 20:00:59
{text}""",
        "presenceMarks": marks,
    }


class SenateAttendanceTests(unittest.TestCase):
    def test_agenda_filters_to_realized_deliberative_senate_sessions(self):
        xml = """<AgendaPlenario><Sessoes>""" + "".join([
            agenda_event(),
            agenda_event("701", "2026-01-16", "SESSÃO NÃO DELIBERATIVA", status="Sim"),
            agenda_event("702", "2026-01-17", status="Não"),
            agenda_event("703", "2026-01-18", "SESSÃO DELIBERATIVA EXTRAORDINÁRIA"),
            "<Sessao><Casa>CN</Casa><Data>2026-01-19</Data><TipoSessao>SESSÃO DELIBERATIVA ORDINÁRIA</TipoSessao><CodigoSessao>704</CodigoSessao><Realizada><Status>Sim</Status></Realizada></Sessao>",
        ]) + """</Sessoes></AgendaPlenario>"""
        events, malformed = attendance.parse_agenda_xml(xml, 2026, 1, date(2026, 1, 31))
        self.assertEqual(malformed, 0)
        self.assertEqual([event["id"] for event in events], ["senado:700", "senado:703"])

    def test_calendar_maps_only_official_diary_links_to_session_dates(self):
        html = '''<table class="sf-calendario"><td><a href="/diarios/ver/123">15</a></td>
          <td><a href="/diarios/ver/124">31</a></td></table>'''
        self.assertEqual(attendance.parse_calendar_html(html, 2026, 1), [
            {"diarioId": "123", "date": "2026-01-15"},
            {"diarioId": "124", "date": "2026-01-31"},
        ])

    def test_presence_column_is_required_and_explicit_footer_must_match(self):
        text = """Republicanos AC Alan Rick XX
UNIÃO AP Davi Alcolumbre X
Compareceram 2 senadores."""
        table = attendance.parse_attendance_pages([diary_page(text, 2)], "2026-01-15")
        self.assertEqual(table[0]["total"], 2)
        self.assertEqual(table[0]["type"], "SESSÃO DELIBERATIVA ORDINÁRIA")
        self.assertEqual(table[0]["ordinal"], 4)
        self.assertEqual([row["nome"] for row in table[0]["rows"]], ["Alan Rick", "Davi Alcolumbre"])
        self.assertTrue(all(row["presente"] for row in table[0]["rows"]))

        # Plain-text XX can contain a vote mark but does not establish that
        # the X occupied the PDF's Presença column.
        with self.assertRaisesRegex(attendance.SourceError, "X na coluna Presença"):
            attendance.parse_attendance_pages(
                [diary_page("Republicanos AC Alan Rick XX\nCompareceram 1 senador.", 0)],
                "2026-01-15",
            )

    def test_attendance_summary_accepts_comparecimento_without_voto(self):
        summary = [{"text": """ÍNDICE
1.5 – REGISTRO DE COMPARECIMENTO ........................................ 77
Nota: registro de comparecimento do senador em outra sessão, p. 88
2.5 — REGISTRO DE COMPARECIMENTO E VOTO .............................. 108"""}]
        self.assertEqual(attendance.attendance_page_numbers(summary), [77, 108])
        parsed = attendance.parse_attendance_pages(
            [diary_page(
                "Republicanos AC Alan Rick X\nCompareceram 1 senador.", 1,
                ordinal=1, table_title="REGISTRO DE COMPARECIMENTO",
            )],
            "2026-01-15",
        )
        self.assertEqual(parsed[0]["type"], "SESSÃO DELIBERATIVA ORDINÁRIA")
        self.assertEqual(parsed[0]["ordinal"], 1)
        self.assertEqual(parsed[0]["total"], 1)

    def test_explicit_non_deliberative_table_is_skipped(self):
        text = """Senado Federal
REGISTRO DE COMPARECIMENTO
Partido UF Nome Senador
1ª Sessão Não Deliberativa, às 14 horas
Presenças no período: 15/01/2026 07:00:00 até 15/01/2026 20:00:59
Republicanos AC Alan Rick X
Compareceram 1 senador."""
        self.assertEqual(
            attendance.parse_attendance_pages([{"text": text, "presenceMarks": 1}], "2026-01-15"),
            [],
        )

    def test_table_columns_and_ocr_ordinal_validate_spaced_title(self):
        text = """R E G IS T R O D E C O M P A R E C IM E N T O
Senado Federal
114“ Sessão Deliberativa Extraordinária, às 10 horas
Presenças no período: 13/08/2026 07:00:00 até 13/08/2026 18:00:59
Partido UF Nome Senador Presença
Republicanos AC Alan Rick X
Compareceram 1 senador."""
        parsed = attendance.parse_attendance_pages(
            [{"text": text, "presenceMarks": 1}], "2026-08-13"
        )
        self.assertEqual(parsed[0]["type"], "SESSÃO DELIBERATIVA EXTRAORDINÁRIA")
        self.assertEqual(parsed[0]["ordinal"], 114)
        self.assertEqual(parsed[0]["total"], 1)

    def test_recorded_attendance_timestamp_counts_without_using_vote_x(self):
        text = """REGISTRO DE COMPARECIMENTO E VOTO
44ª Sessão Deliberativa Ordinária, às 14 horas
Presenças no período: 29/04/2026 07:00:00 até 29/04/2026 20:00:59
Partido UF Nome Senador Horário Voto
Republicanos AC Alan Rick 29/04/2026 10:22:27 X
MDB SE Alessandro Vieira 29/04/2026 08:29:57 X
Compareceram 2 senadores."""
        parsed = attendance.parse_attendance_pages([{
            "text": text,
            "presenceMarks": 0,
            "timestampMarks": 2,
        }], "2026-04-29")
        self.assertEqual(parsed[0]["method"], "attendance_timestamp")
        self.assertEqual(parsed[0]["total"], 2)
        self.assertEqual(
            [row["nome"] for row in parsed[0]["rows"]],
            ["Alan Rick", "Alessandro Vieira"],
        )

        # A vote X without a matching recorded arrival time is not evidence
        # of presence and cannot make the printed attendance total validate.
        with self.assertRaisesRegex(attendance.SourceError, "não reconhecidas|evidências explícitas"):
            attendance.parse_attendance_pages([{
                "text": text.replace(
                    "MDB SE Alessandro Vieira 29/04/2026 08:29:57 X",
                    "MDB SE Alessandro Vieira X",
                ).replace("Compareceram 2 senadores.", "Compareceram 1 senador."),
                "presenceMarks": 0,
                "timestampMarks": 1,
            }], "2026-04-29")

        with self.assertRaisesRegex(attendance.SourceError, "não coincidem"):
            attendance.parse_attendance_pages(
                [diary_page("Republicanos AC Alan Rick XX\nCompareceram 2 senadores.", 1)],
                "2026-01-15",
            )

    def test_absent_roster_person_is_not_emitted_as_zero_or_falta(self):
        payload = roster(
            ("senado:1", "Ana Exemplo", "P1", "AC"),
            ("senado:2", "Beto Sem Linha", "P2", "AP"),
        )
        index, ambiguous = attendance.build_roster_index(payload)
        ids, unmatched, ambiguous_count = attendance.map_presence_rows(
            [{"nome": "Ana Exemplo", "presente": True}], index, ambiguous
        )
        self.assertEqual(ids, ["senado:1"])
        self.assertEqual((unmatched, ambiguous_count), (0, 0))
        self.assertEqual(
            attendance.map_presence_rows([{"nome": "Beto Sem Linha", "presente": False}], index, ambiguous),
            ([], 0, 0),
        )

        month = 1
        month_payload = {
            "year": 2026,
            "month": month,
            "agendaUrl": attendance.agenda_url(2026, month),
            "agendaFetchedAt": "2026-01-16T12:00:00+00:00",
            "agendaXml": "<AgendaPlenario><Sessoes>" + agenda_event() + "</Sessoes></AgendaPlenario>",
            "calendarUrl": attendance.calendar_url(2026, month),
            "calendarFetchedAt": "2026-01-16T12:00:00+00:00",
            "calendarHtml": '<table class="calendario"><a href="/diarios/ver/123">15</a></table>',
        }
        diary = {
            "diarioId": "123",
            "calendarDate": "2026-01-15",
            "sourceUrl": attendance.diary_url("123"),
            "fetchedAt": "2026-01-16T12:00:00+00:00",
            "scanned": True,
            "tables": [{
                "type": "SESSÃO DELIBERATIVA ORDINÁRIA",
                "ordinal": 4,
                "total": 1,
                "rows": [{"nome": "Ana Exemplo", "partido": "P1", "uf": "AC", "presente": True}],
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "data" / "raw" / "senado-presenca"
            attendance._atomic_json(attendance._month_cache_path(cache_root, 2026, 1), month_payload)
            attendance._atomic_json(attendance._diary_cache_path(cache_root, "123"), diary)
            snapshot, stats = attendance.build_snapshot(
                root=root, today=date(2026, 1, 31), roster=payload
            )

        section = snapshot["presenca"]
        self.assertEqual(section["status"], "partial")
        self.assertEqual(section["sessionCount"], 1)
        self.assertEqual(section["items"], [{
            "id": "senado:1", "nome": "Ana Exemplo", "partido": "P1", "uf": "AC",
            "presente": 1, "dias": None, "falta": None, "justificadas": None,
            "sessoesEmExercicio": None,  # sem histórico de exercício nesta base de teste
        }])
        self.assertEqual(section["sessions"][0]["presentIds"], ["senado:1"])
        self.assertNotIn("senado:2", [item["id"] for item in section["items"]])
        self.assertEqual(stats["sessions"], 1)

    def test_default_period_is_the_mandate_across_years(self):
        start, end = attendance._period_dates(None, date(2026, 10, 9))
        self.assertEqual((start, end), (date(2023, 2, 1), date(2026, 10, 9)))
        months = attendance._months(start, end)
        self.assertEqual((months[0], months[-1], len(months)), ((2023, 2), (2026, 10), 45))
        self.assertEqual(attendance._period_dates(2023, date(2026, 10, 9)), (date(2023, 2, 1), date(2023, 12, 31)))
        with self.assertRaises(ValueError):
            attendance._period_dates(2022, date(2026, 10, 9))

    def test_checked_diary_spelling_maps_to_the_registered_senator(self):
        index, _ = attendance.build_roster_index(roster(("senado:6362", "MAURO CARVALHO JUNIOR", "P1", "MT")))
        ids, unmatched, _ = attendance.map_presence_rows([{"nome": "Mauro Carvalho Jr.", "presente": True}], index, set())
        self.assertEqual((ids, unmatched), (["senado:6362"], 0))
        other, _ = attendance.build_roster_index(roster(("senado:1", "Ana Exemplo", "P1", "AC")))
        self.assertNotIn(attendance._normalize_name("Mauro Carvalho Jr."), other)  # sem o ID no cadastro, não liga

    def test_duplicate_normalized_roster_name_remains_unassigned(self):
        payload = roster(
            ("senado:1", "José Exemplo", "P1", "AC"),
            ("senado:2", "Jose Exemplo", "P2", "AP"),
        )
        index, ambiguous = attendance.build_roster_index(payload)
        self.assertIn("jose exemplo", ambiguous)
        ids, unmatched, ambiguous_count = attendance.map_presence_rows(
            [{"nome": "José Exemplo", "presente": True}], index, ambiguous
        )
        self.assertEqual(ids, [])
        self.assertEqual((unmatched, ambiguous_count), (1, 1))

    def test_offline_without_valid_calendar_cache_does_not_write_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out = root / "data" / "snapshots" / "senado-presenca.json"
            with self.assertRaises(attendance.SourceError):
                attendance.build_snapshot(root=root, output=out, today=date(2026, 1, 31), roster=roster(
                    ("senado:1", "Ana Exemplo", "P1", "AC"),
                ))
            self.assertFalse(out.exists())

    def test_refresh_failure_uses_previous_cache_and_marks_partial(self):
        payload = roster(("senado:1", "Ana Exemplo", "P1", "AC"))
        month_payload = {
            "year": 2026,
            "month": 1,
            "agendaUrl": attendance.agenda_url(2026, 1),
            "agendaFetchedAt": "2026-01-16T12:00:00+00:00",
            "agendaXml": "<AgendaPlenario><Sessoes>" + agenda_event() + "</Sessoes></AgendaPlenario>",
            "calendarUrl": attendance.calendar_url(2026, 1),
            "calendarFetchedAt": "2026-01-16T12:00:00+00:00",
            "calendarHtml": '<table class="calendario"><a href="/diarios/ver/123">15</a></table>',
        }
        diary = {
            "diarioId": "123", "calendarDate": "2026-01-15",
            "sourceUrl": attendance.diary_url("123"),
            "fetchedAt": "2026-01-16T12:00:00+00:00", "scanned": True,
            "tables": [{"type": "SESSÃO DELIBERATIVA ORDINÁRIA", "total": 1,
                        "rows": [{"nome": "Ana Exemplo", "partido": "P1", "uf": "AC", "presente": True}]}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / "data" / "raw" / "senado-presenca"
            attendance._atomic_json(attendance._month_cache_path(cache_root, 2026, 1), month_payload)
            attendance._atomic_json(attendance._diary_cache_path(cache_root, "123"), diary)

            def fail(_url):
                raise OSError("offline")

            result, error = attendance._collect_diary(
                {"diarioId": "123", "date": "2026-01-15"}, cache_root, fail, True,
            )
            saved = json.loads(attendance._diary_cache_path(cache_root, "123").read_text(encoding="utf-8"))

        self.assertTrue(result["stale"])
        self.assertIn("refresh falhou", error)
        self.assertNotIn("stale", saved)

    def test_refresh_without_previously_observed_table_preserves_previous_table_cache(self):
        previous = {
            "diarioId": "123",
            "calendarDate": "2026-01-15",
            "sourceUrl": attendance.diary_url("123"),
            "fetchedAt": "2026-01-16T12:00:00+00:00",
            "scanned": True,
            "tables": [{
                "type": "SESSÃO DELIBERATIVA ORDINÁRIA",
                "total": 1,
                "rows": [{"nome": "Ana Exemplo", "partido": "P1", "uf": "AC", "presente": True}],
            }],
        }
        diary_html = b'''<script>var diario = {"caderno":{"codigo":123,
        "dataSessao":"2026-01-15T00:00:00","paginaSumarioInicio":3,
        "paginaSumarioFim":4,"paginaFinal":12,"extraordinaria":false},
        "veiculoDSF":true,"veiculoDCN":false,"tituloLongo":"DSF"};</script>'''

        def request(url):
            if url == attendance.diary_url("123"):
                return diary_html, "2026-02-01T12:00:00+00:00"
            return b"%PDF-fake", "2026-02-01T12:00:01+00:00"

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir)
            cache_path = attendance._diary_cache_path(cache_root, "123")
            attendance._atomic_json(cache_path, previous)
            with patch.object(attendance, "_load_pdf_pages", return_value=[{
                "text": "Sumário sem Registro de Comparecimento e Voto", "presenceMarks": 0,
            }]):
                result, error = attendance._collect_diary(
                    {"diarioId": "123", "date": "2026-01-15"}, cache_root, request, True,
                )
            saved = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertTrue(result["stale"])
        self.assertIn("refresh falhou", error)
        self.assertEqual(result["tables"], previous["tables"])
        self.assertEqual(saved, previous)

    def test_diary_cache_rejects_rows_without_explicit_presence_true(self):
        cache = {
            "diarioId": "123",
            "calendarDate": "2026-01-15",
            "sourceUrl": attendance.diary_url("123"),
            "fetchedAt": "2026-01-16T12:00:00+00:00",
            "scanned": True,
            "tables": [{
                "type": "SESSÃO DELIBERATIVA ORDINÁRIA",
                "total": 1,
                "rows": [{"nome": "Ana Exemplo", "partido": "P1", "uf": "AC", "presente": False}],
            }],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = attendance._diary_cache_path(root, "123")
            attendance._atomic_json(path, cache)
            self.assertIsNone(attendance._read_diary_cache(path, "123", "2026-01-15"))

    def test_legacy_empty_cache_with_attendance_summary_is_refetched(self):
        cache = {
            "diarioId": "123",
            "calendarDate": "2026-01-15",
            "sourceUrl": attendance.diary_url("123"),
            "fetchedAt": "2026-01-16T12:00:00+00:00",
            "scanned": True,
            "sumarioText": "1.5 – REGISTRO DE COMPARECIMENTO ........ 77",
            "tables": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = attendance._diary_cache_path(Path(temp_dir), "123")
            attendance._atomic_json(path, cache)
            self.assertIsNone(attendance._read_diary_cache(path, "123", "2026-01-15"))

    def test_repeated_table_copies_are_counted_once_by_session_identity(self):
        payload = roster(("senado:1", "Ana Exemplo", "P1", "AC"))
        month = {
            "month": 1,
            "agendaXml": "<AgendaPlenario><Sessoes>" + agenda_event() + "</Sessoes></AgendaPlenario>",
            "calendarHtml": '<table class="calendario"><a href="/diarios/ver/123">15</a></table>',
            "agendaFetchedAt": "2026-01-16T12:00:00+00:00",
            "calendarFetchedAt": "2026-01-16T12:00:00+00:00",
        }

        def copy(diary_id):
            return (
                {"diarioId": diary_id, "date": "2026-01-15"},
                {
                    "scanned": True,
                    "sourceUrl": attendance.diary_url(diary_id),
                    "fetchedAt": "2026-01-16T12:00:00+00:00",
                    "tables": [{
                        "type": "SESSÃO DELIBERATIVA ORDINÁRIA",
                        "ordinal": 4,
                        "total": 1,
                        "rows": [{"nome": "Ana Exemplo", "presente": True}],
                    }],
                },
            )

        errors = []
        section, stats = attendance._build_attendance_section(
            2026, date(2026, 1, 1), date(2026, 1, 31),
            [month], [copy("123"), copy("124")], payload, errors,
        )
        self.assertEqual(section["sessionCount"], 1)
        self.assertEqual(section["items"][0]["presente"], 1)
        self.assertEqual(section["sessions"][0]["sourceUrl"], attendance.diary_url("124"))
        self.assertEqual(stats["sessions"], 1)
        self.assertTrue(any("cópia repetida" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
