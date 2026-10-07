"""Verba e equipe de gabinete nas páginas oficiais da Câmara, sem estimativas."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

MONTHS = {name: i + 1 for i, name in enumerate('JAN FEV MAR ABR MAI JUN JUL AGO SET OUT NOV DEZ'.split())}


def number(value):
    return float(Decimal(value.replace('.', '').replace(',', '.')))


def parse_office(content, source_url, fetched_at, year=2026):
    cleaned = re.sub(r'<script\b.*?</script>|<style\b.*?</style>', ' ', content, flags=re.S | re.I)
    text = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', cleaned)))
    start = re.search(r'Verba de gabinete\s*\?', text)
    block = text[start.end():] if start else ''
    block = re.split(r'Veja mais|Detalhamento|Pessoal de gabinete', block, maxsplit=1)[0]
    amount = re.search(r'Percentual\s+Gasto\s+([\d.,]+)\s+[\d.,]+%', block)
    months = {str(MONTHS[name]): number(value) for name, value in
              re.findall(r'\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s+([\d.,]+)', block)}
    staff = re.search(r'Pessoal de gabinete\s*\?\s*(\d+) pessoas neste ano, sendo (\d+) ativas', text)
    updated = re.search(r'Informações de gastos atualizadas em (\d{2}/\d{2}/\d{4})', text)
    amount_value = number(amount.group(1)) if amount else None
    status = 'imported' if amount and staff else 'partial' if amount or staff else 'unavailable'
    return {
        'status': status, 'amount': amount_value, 'months': months,
        'staffActive': int(staff.group(2)) if staff else None,
        'staffYear': int(staff.group(1)) if staff else None,
        'sourceUpdatedAt': updated.group(1) if updated else None,
        'sourceUrl': source_url, 'fetchedAt': fetched_at, 'period': str(year),
        'detail': ('Total de verba de gabinete publicado na página oficial. Os meses são os que a fonte informa; '
                   'valor da equipe separado da cota e do subsídio.') if amount else
                  'Total de verba de gabinete não identificado na página consultada; ausência não significa zero.',
    }


def load_office(deputy_id, raw_dir: Path, collect=False, refresh=False, year=2026):
    deputy_id = str(deputy_id).removeprefix('camara:')
    if not deputy_id.isdigit():
        raise ValueError('Código de deputado inválido')
    source_url = f'https://www.camara.leg.br/deputados/{deputy_id}?ano={year}'
    cache = Path(raw_dir) / f'office-{deputy_id}-{year}.json'
    previous = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else None
    if previous and not (collect and refresh):
        return previous
    missing = {'status': 'unavailable', 'amount': None, 'months': {}, 'staffActive': None,
               'staffYear': None, 'sourceUpdatedAt': None, 'sourceUrl': source_url,
               'fetchedAt': None, 'period': str(year), 'detail': 'Verba e equipe de gabinete ainda não coletadas.'}
    if not collect:
        return previous or missing
    try:
        request = urllib.request.Request(source_url, headers={'User-Agent': 'Mozilla/5.0 (PainelPublico)'})
        with urllib.request.urlopen(request, timeout=20) as response:
            content = response.read().decode('utf-8')
        stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
        result = parse_office(content, source_url, stamp, year)
        if result['status'] == 'unavailable':
            raise ValueError('Campos de verba e equipe não encontrados na página')
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        temporary.replace(cache)
        return result
    except (OSError, ValueError) as error:
        # Preserve the date of the successful observation if refreshing fails.
        result = dict(previous or missing)
        result['stale'] = bool(previous)
        result['detail'] = result.get('detail', '') + f' Falha na atualização: {type(error).__name__}.'
        return result
