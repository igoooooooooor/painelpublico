#!/usr/bin/env python3
"""Simulação reproduzível das regras de alerta sobre o mandato (fev/2023 em diante).

Usa o mesmo cálculo dos alertas publicados (backend/alert_rules.py), sobre uma fotografia fixa
do banco: notas detalhadas do ano corrente mais as notas de anos anteriores (visão quota_history).
Compara a base anual (regra em uso) com a de 12 meses (variante em estudo), por Casa, regra e ano,
mostrando também quantos meses e pessoas ficaram sem avaliação: menos alertas pode ser só menos cobertura.

Grava ``data/reviews/alert-simulation.json`` e, com ``--sample``, uma amostra sorteada com semente
fixa para revisão documental (alertados, casos perto dos limites e casos sem alerta).
Somente leitura do banco; não altera alertas publicados.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import alert_rules  # noqa: E402

OUTPUT_DIR = ROOT / 'data' / 'reviews'
MANDATE_START = (2023, 2)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load(db_path: Path):
    db = sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    records = [dict(r) for r in db.execute('''
        SELECT e.id,e.authorityId,e.sourceId,e.year,e.month,e.supplierKey,s.name supplierName,e.amountCents,e.airline
          FROM expenses e LEFT JOIN suppliers s ON s.key=e.supplierKey WHERE e.kind='reembolso'
        UNION ALL
        SELECT 'hist:'||h.authorityId||':'||h.year||':'||h.month||':'||h.seq,h.authorityId,h.sourceId,h.year,h.month,
               h.supplierKey,s.name,h.amountCents,h.airline
          FROM quota_history h LEFT JOIN suppliers s ON s.key=h.supplierKey WHERE h.kind='reembolso' ''')]
    records = [r for r in records if (int(r['year']), int(r['month'])) >= MANDATE_START]
    fetched = {r['id']: r['fetchedAt'] for r in db.execute('SELECT id,fetchedAt FROM sources')}
    roster = {r[0] for r in db.execute('SELECT authorityId FROM roster')}
    people = {r['id'] for r in db.execute("SELECT id FROM authorities WHERE role IN ('deputado','senador')")}
    snapshot = db.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone()
    db.close()
    return records, fetched, roster, people, snapshot[0] if snapshot else None


def summarize(result, population):
    signals = [s for s in result['signals'] if s['authorityId'] in population]
    counts = Counter((alert_rules.house_of(s['sourceId']), s['type'], int(s['period'][:4])) for s in signals)
    months = Counter()
    people_evaluated = Counter()
    for c in result['coverage']:
        if c['authorityId'] not in population:
            continue
        house, year, detail = alert_rules.house_of(c['sourceId']), c['year'], c['detail']
        if c['rule'] == 'pico':
            months[(house, year, 'avaliado')] += len(detail['evaluated'])
            months[(house, year, 'marcado')] += len(detail['flagged'])
            for reason, values in detail['notEvaluated'].items():
                months[(house, year, reason)] += len(values)
            people_evaluated[(house, year, 'pico', bool(detail['evaluated']))] += 1
        else:
            people_evaluated[(house, year, 'fornecedor', bool(detail['evaluated']))] += 1
    rows = []
    for house, year in sorted({(h, y) for (h, y, _) in months} | {(h, y) for (h, _, y) in counts}):
        rows.append({
            'casa': house, 'ano': year,
            # Alertas agrupam meses seguidos; a taxa compara meses marcados com meses avaliados.
            'alertas': {'pico': counts[(house, 'pico', year)], 'fornecedor': counts[(house, 'fornecedor', year)]},
            'taxaMesesMarcados': round(months[(house, year, 'marcado')] / months[(house, year, 'avaliado')], 4)
                                 if months[(house, year, 'avaliado')] else None,
            'mesesPessoa': {k[2]: v for k, v in months.items() if k[:2] == (house, year)},
            'pessoas': {'picoAvaliadas': people_evaluated[(house, year, 'pico', True)],
                        'picoSemAvaliacao': people_evaluated[(house, year, 'pico', False)],
                        'fornecedorAvaliadas': people_evaluated[(house, year, 'fornecedor', True)]},
        })
    return rows


def near_threshold(records, fetched, population, rng, limit):
    """Meses avaliados que quase passaram (1,5× a 1,75× da referência) e concentrações de 40% a 50%."""
    by_year = alert_rules.evaluate(records, fetched)
    flagged = {(s['authorityId'], s['period'][:4]) for s in by_year['signals']}
    series = {}
    for r in records:
        key = (r['authorityId'], r['sourceId'], int(r['year']))
        series.setdefault(key, {})[int(r['month'])] = series.get(key, {}).get(int(r['month']), 0) + r['amountCents']
    peaks, suppliers = [], []
    from statistics import median
    for c in by_year['coverage']:
        if c['authorityId'] not in population:
            continue
        months = series[(c['authorityId'], c['sourceId'], c['year'])]
        if c['rule'] == 'pico':
            for m in c['detail']['evaluated']:
                base = median([months[x] for x in range(1, m)])
                if base > 0 and 1.5 <= months[m] / base < alert_rules.PEAK_MULTIPLE:
                    peaks.append({'tipo': 'perto-pico', 'authorityId': c['authorityId'], 'sourceId': c['sourceId'],
                                  'ano': c['year'], 'mes': m, 'valorCents': months[m], 'referenciaCents': base})
    totals, per_supplier = {}, {}
    for r in records:
        key = (r['authorityId'], r['sourceId'], int(r['year']))
        totals[key] = totals.get(key, 0) + r['amountCents']
        if r.get('supplierKey'):
            per_supplier[(*key, r['supplierKey'], r.get('supplierName'))] = per_supplier.get((*key, r['supplierKey'], r.get('supplierName')), 0) + r['amountCents']
    for (a, s, y, k, name), cents in per_supplier.items():
        total = totals[(a, s, y)]
        if a in population and total > 0 and 0.4 <= cents / total < alert_rules.SUPPLIER_MIN_SHARE and cents >= alert_rules.SUPPLIER_MIN_CENTS:
            suppliers.append({'tipo': 'perto-fornecedor', 'authorityId': a, 'sourceId': s, 'ano': y, 'fornecedor': name,
                              'fornecedorKey': k, 'valorCents': cents, 'totalCents': total, 'parte': round(cents / total, 4)})
    no_alert = sorted({(c['authorityId'], c['sourceId'], c['year']) for c in by_year['coverage']
                       if c['authorityId'] in population and c['rule'] == 'pico' and c['detail']['evaluated']
                       and (c['authorityId'], str(c['year'])) not in flagged})
    pick = lambda items, n: rng.sample(items, min(n, len(items)))
    quiet = [{'tipo': 'sem-alerta', 'authorityId': a, 'sourceId': s, 'ano': y} for a, s, y in pick(no_alert, limit)]
    return pick(sorted(peaks, key=lambda x: (x['authorityId'], x['ano'], x['mes'])), limit) + \
        pick(sorted(suppliers, key=lambda x: (x['authorityId'], x['ano'], x['fornecedorKey'])), limit) + quiet


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'data' / 'na-lupa.sqlite3')
    parser.add_argument('--seed', type=int, default=20261008)
    parser.add_argument('--sample', type=int, default=0, help='alertas por estrato (Casa × tipo × ano) na amostra')
    parser.add_argument('--output', type=Path, default=OUTPUT_DIR / 'alert-simulation.json')
    args = parser.parse_args(argv)
    records, fetched, roster, people, snapshot = load(args.db)
    results = {baseline: alert_rules.evaluate(records, fetched, baseline) for baseline in alert_rules.BASELINES}
    report = {
        'geradoEm': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'fotografia': {'banco': str(args.db), 'sha256': sha256(args.db), 'snapshotAt': snapshot,
                       'coletas': {k: v for k, v in sorted(fetched.items()) if 'ceap' in k}, 'notas': len(records)},
        'parametros': {'regra': alert_rules.RULE_VERSION, 'multiplo': alert_rules.PEAK_MULTIPLE,
                       'diferencaMinimaCents': alert_rules.PEAK_MIN_DIFFERENCE_CENTS,
                       'mesesAnterioresMinimos': alert_rules.PEAK_MIN_PRIOR_MONTHS, 'parteFornecedor': alert_rules.SUPPLIER_MIN_SHARE,
                       'valorFornecedorCents': alert_rules.SUPPLIER_MIN_CENTS, 'diasCamara': alert_rules.CHAMBER_DAYS,
                       'senado': 'meses elegíveis só depois de 30/abr do ano seguinte', 'inicio': '2023-02'},
        'populacoes': {'listaAtual': len(roster), 'todosParlamentares': len(people)},
        'resultados': {baseline: {'listaAtual': summarize(result, roster), 'todosParlamentares': summarize(result, people)}
                       for baseline, result in results.items()},
    }
    if args.sample:
        rng = random.Random(args.seed)
        strata = {}
        for s in results['year']['signals']:
            if s['authorityId'] in roster:
                strata.setdefault((alert_rules.house_of(s['sourceId']), s['type'], s['period'][:4]), []).append(s)
        sample = []
        for key in sorted(strata):
            for s in rng.sample(sorted(strata[key], key=lambda x: x['id']), min(args.sample, len(strata[key]))):
                sample.append({'tipo': s['type'], 'id': s['id'], 'authorityId': s['authorityId'], 'sourceId': s['sourceId'],
                               'periodo': s['period'], 'valorCents': s['amountCents'], 'detalhe': s['detail']})
        sample += near_threshold(records, fetched, roster, rng, args.sample)
        # Casos que só aparecem nas bases móveis (sobretudo 2023 e base curta): a revisão precisa vê-los,
        # porque a amostra pela regra anual não diz nada sobre o que as variantes acrescentam.
        year_months = {(c['authorityId'], c['sourceId'], c['year'], m) for c in results['year']['coverage']
                       if c['rule'] == 'pico' for m in c['detail']['flagged']}
        for baseline in ('rolling12', 'rolling-short'):
            only = {}
            for s in results[baseline]['signals']:
                if s['type'] != 'pico' or s['authorityId'] not in roster:
                    continue
                marked = [m['month'] for m in s['detail']['months']]
                if all((s['authorityId'], s['sourceId'], s['detail']['year'], m) not in year_months for m in marked):
                    only.setdefault((alert_rules.house_of(s['sourceId']), s['period'][:4]), []).append(s)
            for key in sorted(only):
                for s in rng.sample(sorted(only[key], key=lambda x: x['id']), min(args.sample, len(only[key]))):
                    sample.append({'tipo': 'pico-so-' + baseline, 'id': s['id'], 'authorityId': s['authorityId'],
                                   'sourceId': s['sourceId'], 'periodo': s['period'], 'valorCents': s['amountCents'],
                                   'detalhe': s['detail']})
        report['amostra'] = {'semente': args.seed, 'porEstrato': args.sample, 'base': 'year', 'populacao': 'listaAtual',
                             'casos': sample}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    for baseline in alert_rules.BASELINES:
        print(f'== base {baseline} (lista atual)')
        for row in report['resultados'][baseline]['listaAtual']:
            m = row['mesesPessoa']
            rate = f"{row['taxaMesesMarcados'] * 100:5.2f}%" if row['taxaMesesMarcados'] is not None else '    —'
            print(f"{row['casa']:6} {row['ano']}  pico {row['alertas']['pico']:4}  fornecedor {row['alertas']['fornecedor']:3}  "
                  f"meses marcados/avaliados {m.get('marcado', 0):4}/{m.get('avaliado', 0):5} ({rate})  "
                  f"sem base {m.get('sem_base', 0):5}  prazo aberto {m.get('prazo_aberto', 0):5}  "
                  f"sem notas {m.get('sem_notas', 0):4}  pessoas sem avaliação de pico {row['pessoas']['picoSemAvaliacao']}")
    print(f'Gravado em {args.output}' + (f" com {len(report['amostra']['casos'])} casos na amostra" if args.sample else ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
