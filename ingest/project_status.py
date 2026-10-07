"""Situação oficial dos projetos já listados nas fichas; execução offline por padrão.

Arquivos anuais da Câmara e lotes de até 100 processos do Senado evitam consultar
cada associação de autoria. O snapshot separado é mesclado pela API de perfis.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest import project_status_chamber, project_status_senate

CHAMBER = 'https://dadosabertos.camara.leg.br'
SENATE = 'https://legis.senado.leg.br/dadosabertos'
GROUPS = ('lei', 'emenda', 'tramitando', 'arquivado')
_last_request = 0.0


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _atomic_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=path.parent, delete=False) as stream:
            name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode()


def request_bytes(url):
    global _last_request
    for attempt in range(2):
        try:
            time.sleep(max(0, 0.2 - (time.monotonic() - _last_request)))
            _last_request = time.monotonic()
            request = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'QuantoCusta/1.0 (project-status collector)'})
            with urlopen(request, timeout=90) as response:
                return response.read()
        except (OSError, TimeoutError):
            if attempt:
                raise
            time.sleep(0.5)


def _valid_date(value):
    try:
        return isinstance(value, str) and datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None
    except ValueError:
        return False


def _read_cache(path, url, validate):
    try:
        meta = json.loads(path.with_suffix('.meta.json').read_text(encoding='utf-8'))
        if meta.get('sourceUrl') != url or not _valid_date(meta.get('consultadoEm')):
            return None
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != meta.get('sha256'):
            return None
        payload = json.loads(content)
        if not validate(payload):
            return None
        return payload, meta
    except (OSError, ValueError, AttributeError):
        return None


def cached_json(url, path, *, collect=False, refresh=False, request=request_bytes, validate=lambda value: isinstance(value, (dict, list))):
    previous = _read_cache(path, url, validate)
    if previous and not refresh:
        return (*previous, None)
    if not collect:
        return (*previous, None) if previous else (None, None, 'Consulta ainda não coletada ou cache inválido.')
    try:
        content = request(url)
        payload = json.loads(content)
        if not validate(payload):
            raise ValueError('Resposta oficial fora do contrato esperado')
        meta = {'sourceUrl': url, 'consultadoEm': utc_now(), 'sha256': hashlib.sha256(content).hexdigest()}
        _atomic_bytes(path, content)
        _atomic_bytes(path.with_suffix('.meta.json'), _json_bytes(meta))
        return payload, meta, None
    except (OSError, TimeoutError, ValueError) as error:
        message = f'Falha na consulta ({type(error).__name__}); a observação anterior, se disponível, foi preservada.'
        return (*previous, message) if previous else (None, None, message)


def project_targets(snapshot_dir):
    targets = {'camara': {}, 'senado': {}}
    for name, chamber in (('perfis.json', 'camara'), ('senado-projetos.json', 'senado')):
        path = snapshot_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding='utf-8'))
        profiles = payload.get('profiles')
        if not isinstance(profiles, dict):
            raise ValueError(f'{name}: lista de perfis inválida')
        for person, profile in profiles.items():
            if not person.startswith(chamber + ':') or not isinstance(profile, dict):
                continue
            projects = profile.get('projetos')
            items = projects.get('items') if isinstance(projects, dict) else None
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                identifier = str(item.get('id', ''))
                if identifier.isdigit():
                    targets[chamber][identifier] = item
    if not any(targets.values()):
        raise ValueError('Nenhum projeto listado nos snapshots locais; nenhuma saída foi alterada.')
    return targets


def unavailable(url, detail):
    return {'grupo': None, 'descricao': None, 'consultadoEm': None, 'sourceUrl': url,
            'atualizadoEm': None, 'status': 'unavailable', 'normas': [], 'detail': detail}


def _annotate(record, meta, error):
    record['consultaUrl'] = meta['sourceUrl'] if meta else record.get('sourceUrl')
    if error:
        record = {**record, 'status': 'partial', 'detail': ' '.join(filter(None, (record.get('detail'), error)))}
    return record


def _chamber_statuses(targets, raw, options):
    years = sorted({int(match.group(1)) for item in targets.values()
                    if (match := re.search(r'/(\d{4})\b', str(item.get('titulo', ''))))})
    records, matched, sources = {}, {}, []
    for year in years:
        if year < 1900 or year > datetime.now().year:
            continue
        url = f'{CHAMBER}/arquivos/proposicoes/json/proposicoes-{year}.json'
        payload, meta, error = cached_json(url, raw / 'camara' / f'proposicoes-{year}.json',
            validate=lambda p: isinstance(p, dict) and isinstance(p.get('dados'), list), **options)
        sources.append({'sourceUrl': url, 'consultadoEm': meta.get('consultadoEm') if meta else None, 'detail': error})
        if payload is None:
            continue
        for row in payload['dados']:
            if not isinstance(row, dict):
                continue
            identifier = str(row.get('id', ''))
            if identifier not in targets:
                continue
            previous = matched.get(identifier)
            stamp = str((row.get('ultimoStatus') or {}).get('data') or '')
            if previous and stamp < previous[0]:
                continue
            matched[identifier] = (stamp, row, meta, error)
        print(f'Câmara: arquivo {year} consultado; {len(matched)}/{len(targets)} IDs encontrados.', flush=True)
    for identifier in targets:
        source_url = f'{CHAMBER}/api/v2/proposicoes/{identifier}'
        observation = matched.get(identifier)
        if observation:
            _, row, meta, error = observation
            record = project_status_chamber.normalize_status(row, meta['consultadoEm'], source_url)
            record = _annotate(record, meta, error)
        else:
            record = unavailable(source_url, 'Projeto não encontrado nos arquivos anuais disponíveis.')
        # Detalhes só para IDs ausentes e para a referência normativa direta.
        if not observation or project_status_chamber.needs_detail(row) or record.get('grupo') in ('lei', 'emenda'):
            payload, meta, error = cached_json(source_url, raw / 'camara' / f'projeto-{identifier}.json',
                validate=lambda p: isinstance(p, dict) and isinstance(p.get('dados'), dict)
                    and str(p['dados'].get('id')) == identifier, **options)
            if payload is not None and not error:
                record = _annotate(project_status_chamber.normalize_status(payload['dados'], meta['consultadoEm'], source_url), meta, error)
            elif observation:
                failure = error or 'Detalhe individual da proposição indisponível.'
                record = {**record, 'status': 'partial', 'detail': ' '.join(filter(None, (
                    record.get('detail'), failure, 'A situação e a data do arquivo anual foram preservadas.',
                )))}
            elif payload is not None:
                record = _annotate(project_status_chamber.normalize_status(payload['dados'], meta['consultadoEm'], source_url), meta, error)
            else:
                record['detail'] = error or record['detail']
        records[f'camara:{identifier}'] = record
    return records, sources


def _senate_statuses(targets, raw, options):
    identifiers = sorted(targets, key=int)
    records, sources = {}, []
    for start in range(0, len(identifiers), 100):
        batch = identifiers[start:start + 100]
        url = SENATE + '/processo?' + urlencode([('idProcesso', identifier) for identifier in batch])
        key = hashlib.sha256(','.join(batch).encode()).hexdigest()[:20]
        payload, meta, error = cached_json(url, raw / 'senado' / f'lote-{key}.json', validate=lambda p: isinstance(p, list), **options)
        sources.append({'sourceUrl': url, 'consultadoEm': meta.get('consultadoEm') if meta else None, 'detail': error})
        by_id = {}
        duplicates = set()
        for row in payload or []:
            if isinstance(row, dict) and str(row.get('id')) in batch:
                identifier = str(row['id'])
                if identifier in by_id:
                    duplicates.add(identifier)
                by_id[identifier] = row
        for identifier in batch:
            source_url = f'{SENATE}/processo/{identifier}'
            row = by_id.get(identifier)
            if not row or identifier in duplicates:
                records[f'senado:{identifier}'] = unavailable(source_url, error or 'ID ausente ou repetido na consulta oficial; situação não confirmada.')
                continue
            detail = None
            detail_error = None
            if project_status_senate.needs_detail(row):
                detail, detail_meta, detail_error = cached_json(source_url, raw / 'senado' / f'processo-{identifier}.json',
                    validate=lambda p: isinstance(p, dict) and str(p.get('id')) == identifier, **options)
                # A lista fornece a situação principal; a data do detalhe fica explícita.
            record = project_status_senate.normalize_status(row, meta['consultadoEm'], source_url, detail=detail)
            if detail is not None:
                record['detalheConsultadoEm'] = detail_meta['consultadoEm']
            record = _annotate(record, meta, error or detail_error)
            records[f'senado:{identifier}'] = record
        print(f'Senado: {min(start + 100, len(identifiers))}/{len(identifiers)} processos consultados.', flush=True)
    return records, sources


def build_snapshot(*, root=ROOT, collect=False, refresh=False, request=request_bytes):
    if refresh and not collect:
        raise ValueError('--refresh exige --collect')
    snapshot_dir = root / 'data' / 'snapshots'
    targets = project_targets(snapshot_dir)
    raw = root / 'data' / 'raw' / 'projetos-situacao'
    options = {'collect': collect, 'refresh': refresh, 'request': request}
    records, sources = {}, []
    for chamber, builder in (('camara', _chamber_statuses), ('senado', _senate_statuses)):
        if targets[chamber]:
            house_records, house_sources = builder(targets[chamber], raw, options)
            records.update(house_records)
            sources.extend(house_sources)
    output = snapshot_dir / 'projetos-situacao.json'
    # Falhas sem cache não apagam evidências datadas de uma fotografia anterior.
    try:
        previous = json.loads(output.read_text(encoding='utf-8')).get('projects', {})
    except (OSError, ValueError, AttributeError):
        previous = {}
    for key, record in records.items():
        old = previous.get(key) if isinstance(previous, dict) else None
        if record.get('consultadoEm') is None and isinstance(old, dict) and _valid_date(old.get('consultadoEm')):
            records[key] = {**old, 'status': 'partial', 'detail': ' '.join(filter(None, (old.get('detail'), record.get('detail'), 'Consulta anterior preservada com sua data.')))}
    summary = {}
    for chamber in targets:
        items = [record for key, record in records.items() if key.startswith(chamber + ':')]
        groups = Counter(record.get('grupo') for record in items if record.get('status') == 'imported')
        summary[chamber] = {'total': len(items), 'consultados': sum(_valid_date(record.get('consultadoEm')) for record in items),
                            **{group: groups[group] for group in GROUPS},
                            'semConfirmacao': sum(record.get('status') != 'imported' or record.get('grupo') not in GROUPS for record in items)}
    if not any(record.get('consultadoEm') for record in records.values()):
        raise ValueError('Nenhuma situação consultada disponível; snapshot anterior preservado.')
    snapshot = {'generatedAt': utc_now(), 'sources': sources, 'summary': summary, 'projects': records}
    _atomic_bytes(output, _json_bytes(snapshot))
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect', action='store_true', help='consultar fontes oficiais quando falta cache')
    parser.add_argument('--refresh', action='store_true', help='atualizar todas as consultas e preservar observação anterior em falhas')
    args = parser.parse_args()
    try:
        result = build_snapshot(collect=args.collect, refresh=args.refresh)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result['summary'], ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
