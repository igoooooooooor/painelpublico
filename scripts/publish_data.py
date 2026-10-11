"""Empacota banco, snapshots e revisões do Placar e publica num release de dados no GitHub.

Uso: python3 scripts/publish_data.py [--tag data-AAAA-MM-DD] [--dry-run]

O pacote reproduz o que `make deploy-data` envia ao servidor: cópia consistente do SQLite (compactada
após VACUUM), os snapshots complementares que o site lê (sem os insumos de deploy/snapshots-local-only.txt)
e as revisões humanas do Placar. `--dry-run` monta o pacote em data/releases/<tag>/ sem publicar.
"""
import argparse
import fnmatch
import gzip
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database import backup_database  # noqa: E402

DEFAULT_DB = ROOT / 'data' / 'na-lupa.sqlite3'
DEFAULT_SNAPSHOTS = ROOT / 'data' / 'snapshots'
DEFAULT_REVIEWS = ROOT / 'data' / 'reviews'
DEFAULT_OUTPUT = ROOT / 'data' / 'releases'
LOCAL_ONLY_PATTERNS = ROOT / 'deploy' / 'snapshots-local-only.txt'
REVIEW_PATTERNS = ('chamber-vote-reviews-*.json', 'chamber-vote-segment-reviews-*.json')
VOTES_INDEX = 'chamber-votes.json'
VOTE_DETAILS_DIRECTORY = 'chamber-vote-details'
DRAFT_SUFFIX = '.draft.json'
SITE_URL = 'https://github.com/igoooooooooor/painelpublico'


def read_patterns(path):
    """Lê padrões de nome de arquivo, um por linha, ignorando comentários e linhas vazias."""
    path = Path(path)
    if not path.is_file():
        return []
    patterns = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            patterns.append(line)
    return patterns


def matches_any(name, patterns):
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def is_review_file(name):
    return name.endswith('.json') and not name.endswith(DRAFT_SUFFIX) and matches_any(name, REVIEW_PATTERNS)


def current_details_version(snapshots_dir):
    """Geração de detalhes do Placar apontada pelo índice; None quando não há índice ou versão."""
    index = Path(snapshots_dir) / VOTES_INDEX
    if not index.is_file():
        return None
    try:
        version = json.loads(index.read_text(encoding='utf-8')).get('detailsVersion')
    except (ValueError, AttributeError):
        return None
    return version if isinstance(version, str) and version else None


def is_stale_details_generation(relative, current_version):
    """Arquivos de gerações antigas de chamber-vote-details/, que o site não lê mais."""
    parts = Path(relative).parts
    return (len(parts) >= 3 and parts[0] == VOTE_DETAILS_DIRECTORY and current_version is not None
            and parts[1] != current_version)


def _gzip_file(source, destination):
    with open(source, 'rb') as raw, gzip.open(destination, 'wb', compresslevel=9) as packed:
        shutil.copyfileobj(raw, packed, 1024 * 1024)


def database_summary(db_path):
    """Versão do esquema e contagem por tabela, para o manifesto e as notas do release."""
    connection = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
    finally:
        connection.close()
    return {'schemaVersion': version, 'tables': counts}


def package_database(db_path, out_dir, tag):
    """Cópia consistente do banco, VACUUM na cópia e gzip. Devolve (arquivo, resumo)."""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f'Banco não encontrado: {db_path}')
    out_dir = Path(out_dir)
    working = out_dir / f'na-lupa-{tag}.sqlite3'
    packed = out_dir / f'na-lupa-{tag}.sqlite3.gz'
    working.unlink(missing_ok=True)
    packed.unlink(missing_ok=True)
    backup_database(db_path, working)
    try:
        connection = sqlite3.connect(working)
        try:
            connection.execute('PRAGMA journal_mode = DELETE')
            connection.execute('VACUUM')
        finally:
            connection.close()
        summary = database_summary(working)
        _gzip_file(working, packed)
    finally:
        working.unlink(missing_ok=True)
        for suffix in ('-wal', '-shm', '-journal'):
            Path(f'{working}{suffix}').unlink(missing_ok=True)
    return packed, summary


def _add_tree(archive, root, arc_root, keep):
    """Adiciona ao tar os arquivos de root aceitos por keep(caminho relativo), em ordem estável."""
    added = []
    for path in sorted(Path(root).rglob('*')):
        if not path.is_file() or path.name == '.DS_Store':
            continue
        relative = path.relative_to(root)
        if not keep(relative):
            continue
        archive.add(path, arcname=str(Path(arc_root) / relative), recursive=False)
        added.append(str(relative))
    return added


def package_snapshots(snapshots_dir, out_dir, tag, local_only_patterns=()):
    """Snapshots que o site lê: sem os insumos locais (deploy/snapshots-local-only.txt) nem gerações antigas do Placar."""
    snapshots_dir = Path(snapshots_dir)
    if not snapshots_dir.is_dir():
        raise FileNotFoundError(f'Pasta de snapshots não encontrada: {snapshots_dir}')
    packed = Path(out_dir) / f'snapshots-{tag}.tar.gz'
    packed.unlink(missing_ok=True)
    current_version = current_details_version(snapshots_dir)

    def keep(relative):
        return (not matches_any(relative.name, local_only_patterns)
                and not is_stale_details_generation(relative, current_version))

    with tarfile.open(packed, 'w:gz', compresslevel=9) as archive:
        added = _add_tree(archive, snapshots_dir, 'snapshots', keep)
    return packed, added


def package_reviews(reviews_dir, out_dir, tag):
    """Revisões humanas do Placar (sem rascunhos). Devolve (None, []) quando não há nenhuma."""
    reviews_dir = Path(reviews_dir)
    packed = Path(out_dir) / f'reviews-{tag}.tar.gz'
    packed.unlink(missing_ok=True)
    if not reviews_dir.is_dir():
        return None, []
    with tarfile.open(packed, 'w:gz', compresslevel=9) as archive:
        added = _add_tree(archive, reviews_dir, 'reviews', lambda relative: is_review_file(relative.name))
    if not added:
        packed.unlink(missing_ok=True)
        return None, []
    return packed, added


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit():
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def write_manifest(out_dir, tag, files, db_summary, snapshot_names, review_names, commit=None, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    manifest = {
        'tag': tag,
        'generatedAt': generated_at,
        'commit': commit,
        'files': [{'name': Path(path).name, 'bytes': Path(path).stat().st_size, 'sha256': sha256_of(path)}
                  for path in files],
        'database': db_summary,
        'snapshots': snapshot_names,
        'reviews': review_names,
    }
    path = Path(out_dir) / 'manifest.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path, manifest


def _count(value):
    return f'{value:,}'.replace(',', '.')


def _human_size(size):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.0f} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024
    return f'{size:.1f} GB'


def write_notes(out_dir, tag, manifest, has_reviews):
    """Notas do release em pt-BR: conteúdo, como usar, fontes e limites."""
    tables = manifest['database']['tables']
    sizes = {entry['name']: entry['bytes'] for entry in manifest['files']}
    db_name = f'na-lupa-{tag}.sqlite3.gz'
    snapshots_name = f'snapshots-{tag}.tar.gz'
    reviews_name = f'reviews-{tag}.tar.gz'
    lines = [
        f'# Dados do Painel Público — {tag}',
        '',
        f'Fotografia de {manifest["generatedAt"][:10]} da base que o site usa, gerada pelo `make publish-data`'
        + (f' no commit `{manifest["commit"][:12]}`.' if manifest.get('commit') else '.'),
        'Os arquivos são os mesmos que `make deploy-data` envia ao servidor; `manifest.json` traz o SHA-256 e o tamanho de cada um.',
        '',
        '## Conteúdo',
        '',
        f'- `{db_name}` ({_human_size(sizes.get(db_name, 0))}): banco SQLite, esquema versão {manifest["database"]["schemaVersion"]}, '
        f'com {_count(tables.get("authorities", 0))} cadastros, {_count(tables.get("expenses", 0))} notas da cota e {_count(tables.get("signals", 0))} sinais. '
        'Valores em centavos (`amountCents`); o esquema está em `backend/schema.sql`.',
        f'- `{snapshots_name}` ({_human_size(sizes.get(snapshots_name, 0))}): {_count(len(manifest["snapshots"]))} arquivos de snapshots '
        'complementares lidos pela página (perfis, presença, custo do mandato, Senado, Placar com os detalhes nominais da '
        'geração atual, Minha cidade e eleições).',
    ]
    if has_reviews:
        lines.append(f'- `{reviews_name}` ({_human_size(sizes.get(reviews_name, 0))}): {len(manifest["reviews"])} arquivos de revisão '
                     'humana do Placar, com ID, status, fonte e motivo de cada votação incluída ou excluída. '
                     'Rascunhos não entram.')
    lines += [
        '- `manifest.json`: lista dos arquivos, SHA-256, tamanhos e contagem por tabela.',
        '',
        '## Como usar',
        '',
        '```sh',
        f'gunzip {db_name}',
        f'tar -xzf {snapshots_name}',
        f'PAINEL_DB=na-lupa-{tag}.sqlite3 PAINEL_SNAPSHOTS=snapshots make dev',
        '```',
        '',
        'Qualquer cliente SQLite abre o banco diretamente. A pasta `snapshots/` é lida por `scripts/build.py`; '
        'o site funciona sem ela, com menos seções nas fichas. Os arquivos brutos das fontes não fazem parte do pacote.',
        '',
        '## Fontes, limitações e uso',
        '',
        'Todas as informações vêm de fontes públicas: Câmara dos Deputados, Senado Federal, TSE, IBGE, Portal da Transparência e '
        'SICONFI. As fontes, a cobertura de cada uma e as limitações conhecidas estão em `docs/data.md`; as regras dos alertas, '
        'em `docs/alerts.md`; a metodologia do Placar, em `docs/voting-scoreboard.md`. Dado ausente não vira zero, e os alertas '
        'são critérios de triagem, não conclusões sobre conduta.',
        '',
        'Recoletar uma fonte pode produzir outro retrato: use a tag para citar esta fotografia. O pacote é distribuído sem garantia, '
        'como está. O código do projeto está sob licença MIT; os dados pertencem às respectivas fontes públicas e seguem as '
        'condições de uso de cada órgão. Veja o `LEGAL-NOTICE.md` do repositório.',
        '',
    ]
    path = Path(out_dir) / 'NOTES.md'
    path.write_text('\n'.join(lines), encoding='utf-8')
    return path


def build_package(tag, db_path=DEFAULT_DB, snapshots_dir=DEFAULT_SNAPSHOTS, reviews_dir=DEFAULT_REVIEWS,
                  output_dir=DEFAULT_OUTPUT, local_only_patterns=None, commit=None, log=None):
    """Monta o pacote em output_dir/tag e devolve (pasta, arquivos para anexar, notas)."""
    log = log or print
    if local_only_patterns is None:
        local_only_patterns = read_patterns(LOCAL_ONLY_PATTERNS)
    out_dir = Path(output_dir) / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    log(f'banco: copiando e compactando {db_path}')
    db_file, db_summary = package_database(db_path, out_dir, tag)
    log(f'snapshots: empacotando {snapshots_dir}')
    snapshots_file, snapshot_names = package_snapshots(snapshots_dir, out_dir, tag, local_only_patterns)
    log(f'revisões: empacotando {reviews_dir}')
    reviews_file, review_names = package_reviews(reviews_dir, out_dir, tag)
    if reviews_file is None:
        log('revisões: nenhuma revisão do Placar encontrada; o pacote sai sem esse arquivo')

    files = [path for path in (db_file, snapshots_file, reviews_file) if path is not None]
    manifest_path, manifest = write_manifest(out_dir, tag, files, db_summary, snapshot_names, review_names, commit=commit)
    notes_path = write_notes(out_dir, tag, manifest, has_reviews=reviews_file is not None)
    for entry in manifest['files']:
        log(f'  {entry["name"]}: {_human_size(entry["bytes"])}')
    return out_dir, files + [manifest_path], notes_path


def _run_gh(args, **kwargs):
    return subprocess.run(['gh', *args], cwd=ROOT, text=True, **kwargs)


def check_gh():
    if shutil.which('gh') is None:
        raise SystemExit('O comando gh (GitHub CLI) não está instalado: https://cli.github.com/')
    status = _run_gh(['auth', 'status'], capture_output=True)
    if status.returncode != 0:
        raise SystemExit('gh não está autenticado; rode `gh auth login`.\n' + (status.stderr or status.stdout))


def release_exists(tag):
    return _run_gh(['release', 'view', tag], capture_output=True).returncode == 0


def publish_release(tag, files, notes_path, title=None):
    if release_exists(tag):
        raise SystemExit(f'O release {tag} já existe no GitHub. Escolha outra tag (TAG=...) ou apague o release antes.')
    command = ['release', 'create', tag, *[str(path) for path in files],
               '--title', title or f'Dados {tag}', '--notes-file', str(notes_path)]
    result = _run_gh(command)
    if result.returncode != 0:
        raise SystemExit(f'gh release create falhou (código {result.returncode}).')


def default_tag(today=None):
    return f'data-{(today or date.today()).isoformat()}'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Publica banco, snapshots e revisões do Placar como release de dados no GitHub')
    parser.add_argument('--tag', default=None, help='tag do release (padrão: data-AAAA-MM-DD de hoje)')
    parser.add_argument('--title', default=None, help='título do release (padrão: "Dados <tag>")')
    parser.add_argument('--db', default=DEFAULT_DB, help='banco SQLite (padrão: data/na-lupa.sqlite3)')
    parser.add_argument('--snapshots', default=DEFAULT_SNAPSHOTS, help='pasta de snapshots (padrão: data/snapshots)')
    parser.add_argument('--reviews', default=DEFAULT_REVIEWS, help='pasta de revisões (padrão: data/reviews)')
    parser.add_argument('--output', default=DEFAULT_OUTPUT, help='onde montar o pacote (padrão: data/releases)')
    parser.add_argument('--dry-run', action='store_true', help='só monta o pacote, sem publicar')
    args = parser.parse_args(argv)

    tag = args.tag or default_tag()
    if not args.dry_run:
        check_gh()
        if release_exists(tag):
            raise SystemExit(f'O release {tag} já existe no GitHub. Escolha outra tag (TAG=...) ou apague o release antes.')

    out_dir, files, notes_path = build_package(tag, args.db, args.snapshots, args.reviews, args.output, commit=git_commit())
    if args.dry_run:
        print(f'Pacote montado em {out_dir} (dry-run, nada publicado). Notas em {notes_path}.')
        return 0

    publish_release(tag, files, notes_path, args.title)
    print(f'Release {tag} publicado. Pacote local em {out_dir}.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
