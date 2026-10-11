"""Projetos (PL, PLP e PEC) de cada deputado a partir dos arquivos anuais da Câmara.

Substitui a consulta paginada por deputado (513 consultas, com coautorias repetidas em
cada uma) por dois arquivos por ano, lidos uma vez e guardados em cache:

- ``arquivos/proposicoes/json/proposicoes-{ano}.json``: uma linha por proposição, com tipo,
  número, ementa e data de apresentação (o mesmo arquivo que a situação dos projetos usa);
- ``arquivos/proposicoesAutores/json/proposicoesAutores-{ano}.json``: uma linha por
  assinatura, ligando a proposição ao ``idDeputadoAutor``.

O recorte é o mesmo de antes: PL, PLP e PEC apresentados desde 1/2/2023, incluindo
coautorias. Anos fechados ficam em cache; só o arquivo do ano corrente é baixado de
novo, por GET condicional, quando o cache passa da validade. Um ano indisponível torna a
seção de cada deputado parcial, sem total, e a observação anterior é preservada por
``ingest/profiles.py``. Nada aqui consulta o detalhe de uma proposição.

Uso direto (diagnóstico; a integração nas fichas é ``ingest/profiles.py --collect``):
    python3 -m ingest.chamber_projects --collect [--refresh] [--max-age-hours 20]
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest import project_status  # noqa: E402

CHAMBER = 'https://dadosabertos.camara.leg.br'
PROPOSITIONS_URL = CHAMBER + '/arquivos/proposicoes/json/proposicoes-{year}.json'
AUTHORS_URL = CHAMBER + '/arquivos/proposicoesAutores/json/proposicoesAutores-{year}.json'
ARCHIVE_PAGE = 'https://dadosabertos.camara.leg.br/swagger/api.html#staticfile'
PROJECT_TYPES = ('PL', 'PLP', 'PEC')
PERIOD_START = date(2023, 2, 1)
PERIOD_LABEL = 'PL, PLP e PEC apresentados desde 2023-02-01'
DEFAULT_MAX_AGE_HOURS = 20.0


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text(value: Any, limit: int = 12000) -> str | None:
    if not isinstance(value, str):
        return None
    value = ' '.join(value.split())
    return value[:limit] or None


def archive_years(today: date | None = None) -> list[int]:
    today = today or date.today()
    return list(range(PERIOD_START.year, max(PERIOD_START.year, today.year) + 1))


def _presented_on(value: Any) -> date | None:
    text = _text(value, 40)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def project_row(row: Any) -> tuple[str, dict[str, Any]] | None:
    """Projeta uma linha do arquivo de proposições para o item da ficha, ou None fora do recorte."""
    if not isinstance(row, dict):
        return None
    identifier = _text(str(row.get('id') or ''), 60)
    kind = _text(str(row.get('siglaTipo') or ''), 40)
    if not identifier or not identifier.isdigit() or kind not in PROJECT_TYPES:
        return None
    presented = _presented_on(row.get('dataApresentacao'))
    if presented is None or presented < PERIOD_START:
        return None
    number = _text(str(row.get('numero') or ''), 40)
    year = _text(str(row.get('ano') or ''), 40)
    return identifier, {
        'id': identifier,
        'titulo': f'{kind} {number}/{year}' if number and year else None,
        'ementa': _text(row.get('ementa')),
        'situacao': None,
        'url': f'https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={identifier}',
        'apresentadaEm': presented.isoformat(),
    }


def author_row(row: Any) -> tuple[str, str, bool] | None:
    """(id da proposição, id do deputado, proponente) para assinaturas de deputados; None para outros autores."""
    if not isinstance(row, dict):
        return None
    proposition = _text(str(row.get('idProposicao') or ''), 60)
    deputy = row.get('idDeputadoAutor')
    if deputy is None or isinstance(deputy, bool):
        return None
    deputy = _text(str(deputy), 60)
    if not proposition or not proposition.isdigit() or not deputy or not deputy.isdigit():
        return None
    proponent = row.get('proponente')
    return proposition, deputy, proponent in (1, '1', True, 'true', 'True')


def _validate_archive(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get('dados'), list)


def load_archives(
    root: Path = ROOT, *, collect: bool = False, refresh: bool = False, request=project_status.request_bytes,
    fetch=None, max_age_hours: float | None = DEFAULT_MAX_AGE_HOURS, today: date | None = None,
) -> dict[str, Any]:
    """Lê (ou coleta) os arquivos anuais e devolve projetos distintos e assinaturas por deputado.

    ``projects``: id → item; ``signatures``: id do deputado → {id do projeto: proponente};
    ``years``: por ano, URLs, datas de consulta e erros; ``complete``: todos os anos lidos.
    """
    raw = root / 'data' / 'raw' / 'projetos-situacao' / 'camara'
    options = {'collect': collect, 'refresh': refresh, 'request': request, 'fetch': fetch}
    current_year = (today or date.today()).year
    projects: dict[str, dict[str, Any]] = {}
    signatures: dict[str, dict[str, bool]] = {}
    years: dict[str, dict[str, Any]] = {}
    complete = True
    consulted: list[str] = []
    for year in archive_years(today):
        max_age = max_age_hours if year == current_year else None
        record: dict[str, Any] = {}
        propositions_url = PROPOSITIONS_URL.format(year=year)
        payload, meta, error = project_status.cached_json(
            propositions_url, raw / f'proposicoes-{year}.json', validate=_validate_archive, max_age_hours=max_age, **options)
        record['proposicoes'] = {'sourceUrl': propositions_url, 'consultadoEm': meta.get('consultadoEm') if meta else None,
                                 'lastModified': meta.get('lastModified') if meta else None, 'detail': error}
        year_projects: set[str] = set()
        if payload is None:
            complete = False
        else:
            consulted.append(record['proposicoes']['consultadoEm'] or '')
            for row in payload['dados']:
                projected = project_row(row)
                if projected:
                    projects[projected[0]] = projected[1]
                    year_projects.add(projected[0])
            del payload
        authors_url = AUTHORS_URL.format(year=year)
        payload, meta, error = project_status.cached_json(
            authors_url, raw / f'proposicoesAutores-{year}.json', validate=_validate_archive, max_age_hours=max_age, **options)
        record['autores'] = {'sourceUrl': authors_url, 'consultadoEm': meta.get('consultadoEm') if meta else None,
                             'lastModified': meta.get('lastModified') if meta else None, 'detail': error}
        if payload is None:
            complete = False
        else:
            consulted.append(record['autores']['consultadoEm'] or '')
            for row in payload['dados']:
                signature = author_row(row)
                if signature and signature[0] in year_projects:
                    signatures.setdefault(signature[1], {})
                    signatures[signature[1]][signature[0]] = signatures[signature[1]].get(signature[0], False) or signature[2]
            del payload
        record['projetos'] = len(year_projects)
        years[str(year)] = record
        print(f'Câmara: arquivos de {year}: {len(year_projects)} projetos no recorte'
              + ('' if record['autores']['consultadoEm'] else ' (autores indisponíveis)'), flush=True)
    return {
        'projects': projects, 'signatures': signatures, 'years': years, 'complete': complete,
        'fetchedAt': max(consulted) if any(consulted) else None,
    }


def projects_section(deputy_identifier: str, archive: dict[str, Any]) -> dict[str, Any]:
    """Seção ``projetos`` da ficha, no mesmo contrato da consulta por deputado."""
    signed = archive['signatures'].get(str(deputy_identifier), {})
    items = []
    for project_id in sorted(signed, key=lambda value: -int(value)):
        item = archive['projects'].get(project_id)
        if item is None:
            continue
        items.append({**item, 'proponente': signed[project_id]})
    missing = [year for year, record in archive['years'].items()
               if not record['proposicoes']['consultadoEm'] or not record['autores']['consultadoEm']]
    section = {
        'status': 'imported' if archive['complete'] else ('partial' if items else 'unavailable'),
        'period': PERIOD_LABEL,
        'sourceUrl': ARCHIVE_PAGE,
        'fetchedAt': archive.get('fetchedAt'),
        'total': len(items) if archive['complete'] else None,
        'items': items,
        'method': 'arquivos-anuais',
    }
    if missing:
        section['detail'] = ('Arquivos anuais indisponíveis para ' + ', '.join(sorted(missing))
                             + '; total não confirmado.')
    return section


def sections_by_deputy(deputy_identifiers, archive: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {identifier: projects_section(identifier, archive) for identifier in deputy_identifiers}


def summary(archive: dict[str, Any]) -> dict[str, Any]:
    associations = sum(len(signed) for signed in archive['signatures'].values())
    return {
        'method': 'arquivos-anuais',
        'complete': archive['complete'],
        'fetchedAt': archive.get('fetchedAt'),
        'projetosDistintos': len(archive['projects']),
        'associacoes': associations,
        'deputadosComAssinatura': len(archive['signatures']),
        'anos': archive['years'],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--collect', action='store_true', help='baixa os arquivos anuais que faltam ou venceram')
    parser.add_argument('--refresh', action='store_true', help='baixa todos os arquivos de novo')
    parser.add_argument('--max-age-hours', type=float, default=DEFAULT_MAX_AGE_HOURS,
                        help='validade do cache do ano corrente (padrão: 20 horas)')
    args = parser.parse_args(argv)
    if args.refresh and not args.collect:
        parser.error('--refresh exige --collect')
    archive = load_archives(collect=args.collect, refresh=args.refresh, max_age_hours=args.max_age_hours,
                            fetch=project_status.request_archive if args.collect else None)
    print(json.dumps(summary(archive), ensure_ascii=False, indent=2))
    return 0 if archive['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
