#!/usr/bin/env python3
"""Piloto de salário e gabinete do Senado pela lotação "Gabinete do(a) Senador(a) {nome}".

O CSV mensal de remuneração do Senado não traz nome nem identificador de pessoa, mas a coluna de
lotação nomeia o gabinete de cada senador(a). Para até 10 senadores(as), ligados(as) à lotação por uma
tabela conferida à mão (``senate_office_map.json``), este coletor calcula por mês:

- subsídio: a linha de vínculo PARLAMENTAR, folha normal, da lotação do próprio gabinete;
- gabinete: soma das linhas de vínculo COMISSIONADO da mesma lotação (o equivalente à verba de
  gabinete da Câmara, que paga secretários parlamentares);
- servidores efetivos lotados no gabinete: à parte, porque o salário deles não depende do gabinete.

Privacidade: cada arquivo é lido só em memória; nenhuma linha de servidor é gravada nem impressa.
Ficam só agregados por gabinete e mês. Grupo com menos de ``MIN_GROUP`` pessoas guarda só a contagem,
porque o total de uma ou duas pessoas equivale a uma linha individual. Mês sem a linha do(a) senador(a)
no próprio gabinete (por exemplo, lotado(a) numa liderança) ou com mais de uma linha fica sem subsídio,
com o motivo; ausência não vira zero.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ingest.senate_payroll_pilot import EXPECTED_FIELDS, USER_AGENT  # noqa: E402

MAP_PATH = Path(__file__).with_name('senate_office_map.json')
DEFAULT_OUTPUT = Path('data/snapshots/senate-office-pilot.json')
CSV_URL = 'https://www.senado.leg.br/transparencia/LAI/secrh/SF_ConsultaRemuneracaoServidoresParlamentares_{period}.csv'
COMPETENCES = [f'2026-{month:02d}' for month in range(1, 10)]
MAX_SENATORS = 10
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
    if len(entries) > MAX_SENATORS:
        raise PilotError(f'O piloto aceita no máximo {MAX_SENATORS} senadores(as)')
    for entry in entries:
        if not re.fullmatch(r'senado:\d+', entry['id']) or not entry.get('checkedAt'):
            raise PilotError('Correspondência sem ID do Senado ou sem data de conferência')
    return {entry['id']: entry['office'] for entry in entries}, entries


def fetch(period: str) -> bytes:
    url = CSV_URL.format(period=period.replace('-', ''))
    with urlopen(Request(url, headers={'User-Agent': USER_AGENT}), timeout=120) as response:
        return response.read()


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
            'linking': 'Tabela conferida à mão em ingest/senate_office_map.json; sem correspondência aproximada.',
        },
        'sources': sources, 'senators': senators,
    }


def write_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=1)
    os.replace(temp, path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = build()
    write_atomic(ROOT / args.output if not args.output.is_absolute() else args.output, payload)
    for s in payload['senators']:
        with_subsidy = sum(1 for m in s['months'] if m['subsidyGrossCents'] is not None)
        with_office = sum(1 for m in s['months'] if m['office']['grossCents'] is not None)
        print(f"{s['id']}: subsídio em {with_subsidy}/{len(s['months'])} meses, gabinete em {with_office}/{len(s['months'])}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
