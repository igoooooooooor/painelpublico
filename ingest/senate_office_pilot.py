#!/usr/bin/env python3
"""Salário e gabinete do Senado pela lotação "Gabinete do(a) Senador(a) {nome}", no mandato.

O CSV mensal de remuneração do Senado não traz nome nem identificador de pessoa, mas a coluna de
lotação nomeia o gabinete de cada senador(a). Para os(as) senadores(as) da tabela conferida
(``senate_office_map.json``), de fev/2023 ao último mês publicado, este coletor calcula por mês:

- subsídio: a linha de vínculo PARLAMENTAR, folha normal, da lotação do próprio gabinete;
- gabinete: soma das linhas de vínculo COMISSIONADO da mesma lotação (o equivalente à verba de
  gabinete da Câmara, que paga secretários parlamentares);
- servidores efetivos lotados no gabinete: à parte, porque o salário deles não depende do gabinete.

Privacidade: cada arquivo é lido só em memória; nenhuma linha de servidor é gravada nem impressa.
Ficam só agregados por gabinete e mês. Grupo com menos de ``MIN_GROUP`` pessoas guarda só a contagem,
porque o total de uma ou duas pessoas equivale a uma linha individual. Mês sem a linha do(a) senador(a)
no próprio gabinete (por exemplo, lotado(a) numa liderança) ou com mais de uma linha fica sem subsídio,
com o motivo; ausência não vira zero. Suplente em exercício e titular licenciado(a) para ministério
podem ter linhas PARLAMENTAR na mesma lotação: sem identificador, o subsídio daquele mês fica sem dono.

``--suggest`` lista lotações do período ainda fora da tabela, com o nome igual no cadastro quando houver,
para conferência à mão antes de entrar na tabela. A tabela nunca é preenchida por aproximação.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unicodedata
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ingest.senate_payroll_pilot import EXPECTED_FIELDS, USER_AGENT  # noqa: E402

MAP_PATH = Path(__file__).with_name('senate_office_map.json')
DEFAULT_OUTPUT = Path('data/snapshots/senate-office-pilot.json')
CSV_URL = 'https://www.senado.leg.br/transparencia/LAI/secrh/SF_ConsultaRemuneracaoServidoresParlamentares_{period}.csv'
MANDATE_START = (2023, 2)
LAST_PUBLISHED = (2026, 9)


def competences(until=LAST_PUBLISHED):
    return [f'{y}-{m:02d}' for y in range(MANDATE_START[0], until[0] + 1) for m in range(1, 13)
            if MANDATE_START <= (y, m) <= until]


COMPETENCES = competences()
MIN_GROUP = 3
OFFICE = re.compile(r'^gabinete d[oa] senador[a]? (.+)$', re.IGNORECASE)
# Remuneração bruta: parcelas de pagamento; o abate-teto (REVERSAO_TETO_CONST) vem negativo e entra na soma.
GROSS_FIELDS = ('REMUN_BASICA', 'VANT_PESSOAIS', 'FUNC_COMISSIONADA', 'GRAT_NATALINA', 'HORAS_EXTRAS',
                'OUTRAS_EVENTUAIS', 'ABONO_PERMANENCIA', 'REVERSAO_TETO_CONST')
# Fora do bruto, à parte: auxílios e indenizações (não são salário) e diárias.
OTHER_FIELDS = ('AUXÍLIOS', 'VANT_INDENIZATORIAS', 'DIÁRIAS')


class PilotError(RuntimeError):
    """O arquivo não tem o formato esperado; nada é gravado."""


def fold(value: str) -> str:
    value = unicodedata.normalize('NFD', str(value or '').casefold())
    return ' '.join(''.join(c for c in value if unicodedata.category(c) != 'Mn').split())


def cents(value: str) -> int:
    """'12.345,67' ou '12345,67' em centavos; vazio vale zero dentro de uma linha publicada."""
    text = str(value or '').strip().replace('.', '').replace(',', '.')
    if not text:
        return 0
    try:
        return round(float(text) * 100)
    except ValueError as error:
        raise PilotError('Valor numérico fora do formato esperado') from error


def parse_csv(raw: bytes) -> tuple[str | None, list[dict[str, str]]]:
    """Valida metadados e cabeçalho e devolve as linhas em memória (nunca gravadas)."""
    text = raw.decode('cp1252').lstrip('﻿')
    lines = text.splitlines()
    if len(lines) < 2:
        raise PilotError('Arquivo sem cabeçalho')
    meta = next(csv.reader([lines[0]], delimiter=';'))
    header = next(csv.reader([lines[1]], delimiter=';'))
    if header != EXPECTED_FIELDS:
        raise PilotError('Cabeçalho diferente do esquema conferido')
    updated = None
    if len(meta) >= 2 and 'ultima atualizacao' in fold(meta[0]):
        try:
            updated = datetime.strptime(meta[1].strip(), '%d/%m/%Y %H:%M').isoformat(timespec='minutes')
        except ValueError:
            updated = None
    return updated, list(csv.DictReader(io.StringIO('\n'.join(lines[1:])), delimiter=';'))


def _group(rows):
    """Agregado de um grupo de linhas; abaixo de MIN_GROUP pessoas, só a contagem.

    Pessoas = linhas da folha normal (cada servidor tem uma por mês). A folha suplementar (13º, férias,
    acertos) repete as mesmas pessoas e fica num total à parte, para não dobrar a contagem nem o mês.
    """
    normal = [r for r in rows if r['TIPO FOLHA'] == 'Normal']
    extra = [r for r in rows if r['TIPO FOLHA'] != 'Normal']
    if len(normal) < MIN_GROUP:
        return {'people': len(normal), 'grossCents': None, 'otherCents': None, 'supplementaryGrossCents': None,
                'supplementaryRows': len(extra), 'suppressed': bool(rows)}
    total = lambda group, fields: sum(cents(r[f]) for r in group for f in fields)
    return {'people': len(normal), 'grossCents': total(normal, GROSS_FIELDS), 'otherCents': total(normal, OTHER_FIELDS),
            'supplementaryGrossCents': total(extra, GROSS_FIELDS), 'supplementaryRows': len(extra), 'suppressed': False}


def aggregate_month(rows, offices):
    """Agregados por senador(a) num mês. ``offices``: {id: nome da lotação conferido}."""
    by_office = {}
    for row in rows:
        match = OFFICE.match((row.get('LOTAÇÃO EXERCÍCIO') or '').strip())
        if match:
            by_office.setdefault(fold(match.group(1)), []).append(row)
    out = {}
    for identifier, office_name in offices.items():
        office_rows = by_office.get(fold(office_name), [])
        senator = [r for r in office_rows if r['VÍNCULO'] == 'PARLAMENTAR' and r['TIPO FOLHA'] == 'Normal']
        senator_extra = [r for r in office_rows if r['VÍNCULO'] == 'PARLAMENTAR' and r['TIPO FOLHA'] != 'Normal']
        staff = [r for r in office_rows if r['VÍNCULO'] == 'COMISSIONADO']
        career = [r for r in office_rows if r['VÍNCULO'] == 'EFETIVO']
        if not office_rows:
            subsidy, reason = None, 'lotacao_ausente'
        elif len(senator) == 1:
            subsidy, reason = sum(cents(senator[0][f]) for f in GROSS_FIELDS), None
        else:
            subsidy, reason = None, 'sem_linha_no_gabinete' if not senator else 'mais_de_uma_linha'
        out[identifier] = {
            'subsidyGrossCents': subsidy, 'subsidyReason': reason,
            'subsidyOtherCents': sum(cents(senator[0][f]) for f in OTHER_FIELDS) if len(senator) == 1 else None,
            'senatorSupplementaryRows': len(senator_extra),
            'office': _group(staff), 'careerStaff': _group(career),
        }
    return out


def load_map(path: Path = MAP_PATH):
    entries = json.loads(path.read_text(encoding='utf-8'))['offices']
    if len({e['id'] for e in entries}) != len(entries) or len({fold(e['office']) for e in entries}) != len(entries):
        raise PilotError('Tabela com ID ou lotação repetidos')
    for entry in entries:
        if not re.fullmatch(r'senado:\d+', entry['id']) or not entry.get('checkedAt'):
            raise PilotError('Correspondência sem ID do Senado ou sem data de conferência')
    return {entry['id']: entry['office'] for entry in entries}, entries


def fetch(period: str, attempts: int = 3) -> bytes:
    """Baixa o CSV do mês para a memória; leitura incompleta é repetida, nunca aceita pela metade."""
    url = CSV_URL.format(period=period.replace('-', ''))
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(Request(url, headers={'User-Agent': USER_AGENT}), timeout=120) as response:
                return response.read()
        except (http.client.IncompleteRead, OSError):
            if attempt == attempts:
                raise
            time.sleep(2 * attempt)


def build(fetcher=fetch, map_path: Path = MAP_PATH, competences=COMPETENCES):
    offices, entries = load_map(map_path)
    months, sources = {}, []
    for period in competences:
        raw = fetcher(period)
        updated, rows = parse_csv(raw)
        sources.append({'competence': period, 'url': CSV_URL.format(period=period.replace('-', '')),
                        'sha256': hashlib.sha256(raw).hexdigest(), 'sourceUpdatedAt': updated, 'rows': len(rows)})
        months[period] = aggregate_month(rows, offices)
        del rows, raw  # nada das linhas sai desta função
    senators = []
    for entry in entries:
        identifier = entry['id']
        series = [{'competence': period, **months[period][identifier]} for period in competences]
        senators.append({'id': identifier, 'name': entry['name'], 'office': entry['office'], 'months': series})
    return {
        'schemaVersion': 1,
        'generatedAt': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'rules': {
            'subsidy': 'Linha PARLAMENTAR, folha normal, na lotação do próprio gabinete; bruto = parcelas de pagamento menos abate-teto.',
            'office': 'Soma das linhas COMISSIONADO da lotação do gabinete (bruto, folha normal), equivalente à verba de gabinete da Câmara; folha suplementar (13º, férias, acertos) em total à parte.',
            'careerStaff': 'Servidores efetivos lotados no gabinete, à parte: o salário não depende do gabinete.',
            'other': 'Auxílios, vantagens indenizatórias e diárias ficam fora do bruto, em campo próprio.',
            'privacy': f'Só agregados por gabinete e mês; grupos com menos de {MIN_GROUP} pessoas guardam só a contagem.',
            'linking': 'Tabela conferida em ingest/senate_office_map.json; sem correspondência aproximada.',
            'sharedOffice': 'Suplente em exercício e titular licenciado(a) com linhas na mesma lotação: subsídio do mês sem dono (mais_de_uma_linha).',
        },
        'sources': sources, 'senators': senators,
    }


def write_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=1)
    os.replace(temp, path)


def suggest(people, fetcher=fetch, map_path: Path = MAP_PATH, periods=COMPETENCES):
    """Lotações de gabinete com linha PARLAMENTAR fora da tabela; ``people``: {id: nome do cadastro}."""
    known = {fold(office) for office in load_map(map_path)[0].values()}
    by_name = {}
    for identifier, name in people.items():
        by_name.setdefault(fold(name), []).append(identifier)
    found = {}
    for period in periods:
        _, rows = parse_csv(fetcher(period))
        for row in rows:
            match = OFFICE.match((row.get('LOTAÇÃO EXERCÍCIO') or '').strip())
            if match and row['VÍNCULO'] == 'PARLAMENTAR' and fold(match.group(1)) not in known:
                found.setdefault(match.group(1).strip(), set()).add(period)
    return [{'office': name, 'months': sorted(months), 'exactMatches': by_name.get(fold(name), [])}
            for name, months in sorted(found.items())]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--suggest', action='store_true', help='lista lotações fora da tabela, para conferência à mão')
    args = parser.parse_args(argv)
    if args.suggest:
        import sqlite3
        db = sqlite3.connect(f'file:{ROOT / "data" / "na-lupa.sqlite3"}?mode=ro', uri=True)
        people = dict(db.execute("SELECT id,name FROM authorities WHERE id LIKE 'senado:%' AND role='senador'"))
        for item in suggest(people):
            print(f"{item['office']}: {item['months'][0]}–{item['months'][-1]} ({len(item['months'])} meses); "
                  f"cadastro com nome igual: {', '.join(item['exactMatches']) or 'nenhum'}")
        return 0
    payload = build()
    write_atomic(ROOT / args.output if not args.output.is_absolute() else args.output, payload)
    for s in payload['senators']:
        with_subsidy = sum(1 for m in s['months'] if m['subsidyGrossCents'] is not None)
        with_office = sum(1 for m in s['months'] if m['office']['grossCents'] is not None)
        print(f"{s['id']}: subsídio em {with_subsidy}/{len(s['months'])} meses, gabinete em {with_office}/{len(s['months'])}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
