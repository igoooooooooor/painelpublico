"""Fila editorial: o que depende de uma pessoa antes de entrar no site.

Duas coisas são conferidas, sem rede:

1. **Placar.** O inventário mais recente do ano corrente (``data/reviews/chamber-vote-inventory-<data>.json``)
   é cruzado com todas as revisões (``reviews/chamber-vote-reviews-*.json``, versionadas, e as antigas em
   ``data/reviews/``). Candidato sem revisão é
   trabalho pendente; revisão ``pending`` continua listada com o motivo. O alerta de tipos do inventário
   (``typeGuard``) é repetido aqui, porque um turno de PEC classificado como emenda some da fila em silêncio.
2. **Arquivos mantidos à mão.** ``arrecadacao.json`` (arrecadação federal, com ``ate``), a tabela de
   gabinetes do Senado (``ingest/senate_office_map.json``) contra a lista atual de senadores, o exercício
   das contas municipais e a fotografia das eleições de 2026 depois do segundo turno.

Para cada candidato sem revisão, um rascunho entra em ``chamber-vote-reviews-draft-<data>.json``
com os campos objetivos preenchidos (ID, data, proposição, placar, links); os campos de texto e a
evidência ficam vazios e o ``status`` é ``draft``, que o catálogo recusa: só uma pessoa o muda para
``confirmed``, ``excluded`` ou ``pending``. Rascunhos já editados não são sobrescritos.

Nada aqui publica: a saída é ``data/reviews/editorial-queue.json`` e ``.md`` e uma linha ``resumo:`` no
terminal, que a atualização semanal usa para avisar por e-mail quando há novidade.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.periods import today as reference_today  # noqa: E402
from ingest.review_paths import review_files  # noqa: E402

REVIEWS_DIR = ROOT / 'data' / 'reviews'
QUEUE_NAME = 'editorial-queue'
INVENTORY_PATTERN = re.compile(r'chamber-vote-inventory-(\d{4}-\d{2}-\d{2})\.json$')
REVIEW_PATTERN = re.compile(r'chamber-vote-reviews-(\d{4}-\d{2}-\d{2})\.json$')
REVENUE_MAX_AGE_DAYS = 60
ROSTER_SENATE_SOURCE = 'senado_senators_current'


def utc_now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def latest_inventory(reviews_dir: Path, year: int) -> tuple[Path, dict] | None:
    """Inventário com a data final mais recente dentro do ano."""
    candidates = []
    for path in reviews_dir.glob('chamber-vote-inventory-*.json'):
        match = INVENTORY_PATTERN.search(path.name)
        if match and match.group(1).startswith(str(year)):
            candidates.append((match.group(1), path))
    if not candidates:
        return None
    _, path = max(candidates)
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get('entries'), list):
        return None
    return path, payload


def load_reviews(reviews_dir: Path, root: Path | None = None) -> dict[str, dict]:
    """Todas as revisões, por ID de votação: as versionadas em ``reviews/`` e as locais em ``data/reviews/``
    (ingest/review_paths.py); entre arquivos, a data mais recente prevalece."""
    reviews: dict[str, dict] = {}
    files = review_files(root) if root is not None else {p.name: p for p in reviews_dir.glob('chamber-vote-reviews-*.json')}
    for stamp, path in sorted((REVIEW_PATTERN.search(name).group(1), path)
                              for name, path in files.items() if REVIEW_PATTERN.search(name)):
        payload = _read_json(path, [])
        if not isinstance(payload, list):
            continue
        for review in payload:
            if isinstance(review, dict) and isinstance(review.get('id'), str):
                reviews[review['id']] = {**review, 'file': path.name}
    return reviews


def _entry_summary(entry: dict) -> dict:
    description = ' '.join(str(entry.get('description') or '').split())
    return {
        'id': entry.get('id'), 'date': entry.get('date'), 'category': entry.get('category'),
        'method': entry.get('method'), 'targetPropositions': entry.get('targetPropositions'),
        'recordedTally': entry.get('recordedTally'), 'description': description[:300],
        'reviewIssues': entry.get('reviewIssues', []), 'sourceUrl': entry.get('sourceUrl'),
    }


def scoreboard_queue(reviews_dir: Path, year: int, root: Path | None = None) -> dict:
    found = latest_inventory(reviews_dir, year)
    if found is None:
        return {'status': 'unavailable', 'detail': f'Nenhum inventário de {year} em {reviews_dir}.',
                'unreviewed': [], 'pending': [], 'counts': {}}
    path, inventory = found
    reviews = load_reviews(reviews_dir, root)
    unreviewed, pending, counts = [], [], {'candidates': 0, 'confirmed': 0, 'excluded': 0, 'pending': 0, 'unreviewed': 0}
    for entry in inventory['entries']:
        if not isinstance(entry, dict) or not entry.get('candidate'):
            continue
        counts['candidates'] += 1
        review = reviews.get(str(entry.get('id')))
        if review is None:
            counts['unreviewed'] += 1
            unreviewed.append(_entry_summary(entry))
        elif review.get('status') == 'pending':
            counts['pending'] += 1
            pending.append({**_entry_summary(entry), 'reason': review.get('reason'), 'file': review.get('file')})
        elif review.get('status') == 'excluded':
            counts['excluded'] += 1
        else:
            counts['confirmed'] += 1
    guard = inventory.get('typeGuard') if isinstance(inventory.get('typeGuard'), dict) else None
    guard_alerts = []
    if guard:
        for key in ('pecTurnsOutsideCandidates', 'wholeTextOutsideCandidates', 'alerts', 'warnings'):
            value = guard.get(key)
            if isinstance(value, list) and value:
                guard_alerts.append({key: value[:20]})
    period = inventory.get('period') or {}
    entries_by_id = {str(entry.get('id')): entry for entry in inventory['entries'] if isinstance(entry, dict)}
    drafts = write_drafts(reviews_dir, str(period.get('end') or path.stem[-10:]), unreviewed, entries_by_id)
    return {
        'status': 'ok', 'inventory': {'file': path.name, 'period': period,
                                      'generatedAt': inventory.get('generatedAt'), 'listComplete': inventory.get('listComplete')},
        'counts': counts, 'unreviewed': unreviewed, 'pending': pending, 'typeGuardAlerts': guard_alerts,
        'reviewFiles': sorted({review['file'] for review in reviews.values()}), 'drafts': drafts,
    }


FICHA_URL = 'https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={}'
DRAFT_STATUS = 'draft'


def review_draft(entry: dict) -> dict:
    """Rascunho de revisão com o que o inventário já sabe; o julgamento fica em branco."""
    targets = entry.get('targetPropositions') or []
    target = targets[0] if len(targets) == 1 and isinstance(targets[0], dict) else None
    label = (f"{target.get('siglaTipo')} {target.get('numero')}/{target.get('ano')}" if target else None)
    return {
        'id': entry.get('id'), 'status': DRAFT_STATUS, 'reviewedAt': None,
        'title': None, 'summary': None, 'decisionLabel': None, 'yesMeaning': None, 'noMeaning': None,
        'sources': {
            'rollCall': None, 'text': None, 'decision': None,
            'proposition': FICHA_URL.format(target['id']) if target and target.get('id') else None,
        },
        'evidence': {'method': None, 'object': None, 'text': None},
        'inventory': {
            'date': entry.get('date'), 'category': entry.get('category'), 'method': entry.get('method'),
            'proposition': label, 'recordedTally': entry.get('recordedTally'),
            'description': ' '.join(str(entry.get('description') or '').split())[:600],
            'reviewIssues': entry.get('reviewIssues', []), 'sourceUrl': entry.get('sourceUrl'),
        },
        'howTo': ('Confira o relatório nominal e cole o link em sources.rollCall; escreva title, summary, decisionLabel, '
                  'yesMeaning e noMeaning em linguagem simples; registre evidence.method/object/text; mude status para '
                  'confirmed, excluded (com reason, reviewedAt, sources e evidence) ou pending (com reason). '
                  'Depois copie para reviews/chamber-vote-reviews-<data>.json, rode make collect-votes THROUGH=<data> e commite.'),
    }


def write_drafts(reviews_dir: Path, inventory_end: str, unreviewed: list[dict], entries_by_id: dict[str, dict]) -> dict:
    """Mantém um arquivo de rascunhos por inventário: acrescenta os novos, preserva os editados e retira os revisados."""
    path = reviews_dir / f'chamber-vote-reviews-draft-{inventory_end}.json'
    existing = _read_json(path, [])
    existing = [item for item in existing if isinstance(item, dict) and isinstance(item.get('id'), str)] if isinstance(existing, list) else []
    wanted = {item['id'] for item in unreviewed}
    kept = [item for item in existing if item['id'] in wanted]
    known = {item['id'] for item in kept}
    added = [review_draft(entries_by_id[item['id']]) for item in unreviewed if item['id'] not in known and item['id'] in entries_by_id]
    drafts = sorted([*kept, *added], key=lambda item: (item.get('inventory', {}).get('date') or '', item['id']), reverse=True)
    if drafts or path.exists():
        temp = path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(drafts, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        temp.replace(path)
    return {'file': path.name, 'total': len(drafts), 'added': [item['id'] for item in added],
            'removed': [item['id'] for item in existing if item['id'] not in wanted]}


def _parse_any_date(value: Any) -> date | None:
    text = str(value or '').strip()
    for pattern, order in ((r'(\d{4})-(\d{2})-(\d{2})', (0, 1, 2)), (r'(\d{2})/(\d{2})/(\d{4})', (2, 1, 0))):
        match = re.search(pattern, text)
        if match:
            parts = [int(match.group(i + 1)) for i in order]
            try:
                return date(*parts)
            except ValueError:
                return None
    return None


def manual_file_warnings(root: Path, reference: date) -> list[dict]:
    """Avisos sobre arquivos que só uma pessoa atualiza; cada um diz o que fazer."""
    warnings: list[dict] = []
    snapshots = root / 'data' / 'snapshots'

    revenue = _read_json(snapshots / 'arrecadacao.json')
    if not isinstance(revenue, dict):
        warnings.append({'file': 'arrecadacao.json', 'issue': 'ausente ou ilegível',
                         'action': 'Atualize a arrecadação federal (receitas administradas pela RFB) com fonte, inicio e ate.'})
    else:
        until = _parse_any_date(revenue.get('ate'))
        if until is None:
            warnings.append({'file': 'arrecadacao.json', 'issue': 'sem data final (ate) legível', 'action': 'Informe a última data publicada.'})
        elif (reference - until).days > REVENUE_MAX_AGE_DAYS:
            warnings.append({'file': 'arrecadacao.json', 'issue': f'última data publicada {until.isoformat()}, há {(reference - until).days} dias',
                             'action': 'Atualize com o relatório mais recente da Receita Federal.'})

    roster = _read_json(root / 'data' / 'imports' / 'legislative.json', {})
    office_map = _read_json(root / 'ingest' / 'senate_office_map.json', {})
    auto_map = _read_json(snapshots / 'senate-office-map-auto.json', {}) or {}
    mapped = {entry.get('id') for table in (office_map, auto_map) if isinstance(table, dict)
              for entry in table.get('offices', []) if isinstance(entry, dict)}
    if isinstance(roster, dict) and mapped:
        missing = sorted(
            f"{row.get('id')} ({row.get('name')})" for row in roster.get('authorities', [])
            if isinstance(row, dict) and row.get('sourceId') == ROSTER_SENATE_SOURCE and row.get('id') not in mapped)
        if missing:
            warnings.append({'file': 'ingest/senate_office_map.json', 'issue': f'{len(missing)} senador(es) da lista atual sem gabinete na tabela',
                             'action': 'Nome diferente do cadastro (os iguais entram sozinhos no job mensal). Rode python3 ingest/senate_office_pilot.py --suggest e confira a lotação à mão: ' + ', '.join(missing[:10])})

    accounts = _read_json(snapshots / 'accounts.json')
    expected_year = reference.year - 1
    if isinstance(accounts, dict) and isinstance(accounts.get('year'), int) and accounts['year'] < expected_year and reference.month >= 7:
        warnings.append({'file': 'accounts.json', 'issue': f"exercício {accounts['year']}; o de {expected_year} já deve estar no SICONFI",
                         'action': f'Rode make collect-accounts YEAR={expected_year} e, se houver CSVs do FINBRA, python3 -m ingest.finbra --year {expected_year}.'})

    elections = _read_json(snapshots / 'eleicoes-2026.json')
    if isinstance(elections, dict):
        second_round = _parse_any_date(elections.get('segundoTurno'))
        generated = _parse_any_date((elections.get('fonte') or {}).get('geradoNoTse'))
        if second_round and reference > second_round and (generated is None or generated <= second_round):
            warnings.append({'file': 'eleicoes-2026.json', 'issue': 'fotografia anterior ao segundo turno',
                             'action': 'Rode make collect-elections e make collect-cities --collect --refresh para o resultado final.'})
    return warnings


def render_markdown(queue: dict) -> str:
    board = queue['scoreboard']
    lines = [f"# Fila editorial · {queue['generatedAt'][:10]}", '']
    if board['status'] != 'ok':
        lines += [f"Placar: {board['detail']}", '']
    else:
        counts = board['counts']
        inventory = board['inventory']
        lines += [f"Placar: inventário `{inventory['file']}` ({inventory['period']['start']} a {inventory['period']['end']}); "
                  f"{counts['candidates']} candidatos: {counts['confirmed']} publicados, {counts['excluded']} excluídos, "
                  f"{counts['pending']} pendentes com motivo, **{counts['unreviewed']} sem revisão**.", '']
        if queue.get('newSinceLastRun'):
            lines += [f"Novos desde a fila anterior: {', '.join(queue['newSinceLastRun'])}", '']
        if board.get('drafts', {}).get('total'):
            lines += [f"Rascunhos de revisão com os campos objetivos preenchidos: `{board['drafts']['file']}` "
                      f"({board['drafts']['total']}); falta o julgamento e o status.", '']
        if board['unreviewed']:
            lines += ['| Data | ID | Categoria | Método | Proposição | Descrição |', '| --- | --- | --- | --- | --- | --- |']
            for item in board['unreviewed']:
                targets = ', '.join(str(t) for t in (item.get('targetPropositions') or [])) or '—'
                lines.append(f"| {item['date']} | {item['id']} | {item['category']} | {item['method']} | {targets} | "
                             f"{(item['description'] or '').replace('|', '/')[:160]} |")
            lines.append('')
        if board['pending']:
            lines += ['Pendentes com motivo:'] + [f"- {item['date']} · {item['id']}: {item['reason']} ({item['file']})" for item in board['pending']] + ['']
        if board.get('typeGuardAlerts'):
            lines += ['Alertas de tipo do inventário (confira antes de fechar o período):',
                      *[f'- {json.dumps(alert, ensure_ascii=False)}' for alert in board['typeGuardAlerts']], '']
    lines.append('Arquivos mantidos à mão:' if queue['manualFiles'] else 'Arquivos mantidos à mão: nenhum aviso.')
    for warning in queue['manualFiles']:
        lines.append(f"- `{warning['file']}`: {warning['issue']}. {warning['action']}")
    lines += ['', 'Nada desta fila é publicado automaticamente; o catálogo do Placar segue a revisão em docs/voting-scoreboard.md.']
    return '\n'.join(lines) + '\n'


def build_queue(root: Path = ROOT, reference: date | None = None, output_dir: Path | None = None) -> dict:
    reference = reference or reference_today()
    reviews_dir = output_dir or (root / 'data' / 'reviews')
    previous = _read_json(reviews_dir / f'{QUEUE_NAME}.json', {})
    board = scoreboard_queue(reviews_dir, reference.year, root)
    previous_ids = {item.get('id') for item in (previous.get('scoreboard') or {}).get('unreviewed', [])} if isinstance(previous, dict) else set()
    new_ids = sorted(item['id'] for item in board['unreviewed'] if item['id'] not in previous_ids)
    queue = {
        'generatedAt': utc_now(), 'reference': reference.isoformat(), 'scoreboard': board,
        'newSinceLastRun': new_ids, 'manualFiles': manual_file_warnings(root, reference),
    }
    queue['attention'] = bool(new_ids or queue['manualFiles'] or board['status'] != 'ok')
    reviews_dir.mkdir(parents=True, exist_ok=True)
    for name, text in ((f'{QUEUE_NAME}.json', json.dumps(queue, ensure_ascii=False, indent=1) + '\n'),
                       (f'{QUEUE_NAME}.md', render_markdown(queue))):
        temp = reviews_dir / (name + '.tmp')
        temp.write_text(text, encoding='utf-8')
        temp.replace(reviews_dir / name)
    return queue


def summary_line(queue: dict) -> str:
    board = queue['scoreboard']
    counts = board.get('counts') or {}
    return 'resumo: ' + json.dumps({
        'placar': board['status'], 'candidatos': counts.get('candidates'), 'semRevisao': counts.get('unreviewed'),
        'pendentes': counts.get('pending'), 'novos': queue['newSinceLastRun'],
        'rascunhos': (board.get('drafts') or {}).get('file'),
        'arquivosManuais': [w['file'] for w in queue['manualFiles']], 'atencao': queue['attention'],
    }, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    queue = build_queue(args.root)
    print(summary_line(queue))
    print(f"fila: {args.root / 'data' / 'reviews' / (QUEUE_NAME + '.md')}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
