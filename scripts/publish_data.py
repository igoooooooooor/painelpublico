"""Empacota banco, snapshots e revisões do Placar e publica num release de dados no GitHub.

Uso: python3 scripts/publish_data.py [--tag data-AAAA-MM-DD] [--dry-run]

O pacote reproduz o que `make deploy-data` envia ao servidor: cópia consistente do SQLite (compactada
após VACUUM), os snapshots complementares que o site lê (sem os insumos de deploy/snapshots-local-only.txt)
e as revisões humanas do Placar. `--dry-run` monta o pacote em data/releases/<tag>/ sem publicar.

A publicação usa a API REST do GitHub, só com a biblioteca padrão. O token vem de PAINEL_GITHUB_TOKEN,
GH_TOKEN ou GITHUB_TOKEN (permissão de conteúdo no repositório) ou, no computador de quem mantém o
projeto, de `gh auth token`. O job mensal do servidor roda este script quando PAINEL_DATA_RELEASE=1.
"""
import argparse
import fnmatch
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.database import backup_database  # noqa: E402
from backend.supplier_keys import LEGACY_PREFIX  # noqa: E402

DEFAULT_DB = ROOT / 'data' / 'na-lupa.sqlite3'
DEFAULT_SNAPSHOTS = ROOT / 'data' / 'snapshots'
# Revisões versionadas em reviews/ desde 11/10/2026 (ingest/review_paths.py); data/reviews/ guarda só os gerados.
DEFAULT_REVIEWS = ROOT / 'reviews'
DEFAULT_OUTPUT = ROOT / 'data' / 'releases'
LOCAL_ONLY_PATTERNS = ROOT / 'deploy' / 'snapshots-local-only.txt'
REVIEW_PATTERNS = ('chamber-vote-reviews-*.json', 'chamber-vote-segment-reviews-*.json', 'chamber-vote-urgency-reviews-*.json')
VOTES_INDEX = 'chamber-votes.json'
VOTE_DETAILS_DIRECTORY = 'chamber-vote-details'
DRAFT_SUFFIX = '.draft.json'
GITHUB_REPO = 'igoooooooooor/painelpublico'
DEFAULT_BRANCH = 'main'
API_URL = 'https://api.github.com'
UPLOADS_URL = 'https://uploads.github.com'
TAG_PREFIX = 'data-'
TOKEN_VARIABLES = ('PAINEL_GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN')
DATA_LICENSE = 'CC BY 4.0'
DATA_LICENSE_URL = 'https://creativecommons.org/licenses/by/4.0/deed.pt-br'


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


def legacy_supplier_keys(connection):
    """Quantas chaves de fornecedor ainda estão no formato cpf-sha256 (só nas tabelas que existem)."""
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return sum(connection.execute(f'SELECT COUNT(*) FROM {table} WHERE {column} LIKE ?', (LEGACY_PREFIX + '%',)).fetchone()[0]
               for table, column in (('suppliers', 'key'), ('expenses', 'supplierKey'), ('quota_history_notes', 'supplierKey'))
               if table in tables and column in {row[1] for row in connection.execute(f'PRAGMA table_info({table})')})


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
            # A chave cpf-sha256 se desfaz em minutos e revela o CPF; o banco precisa estar migrado (make db-init).
            if legacy_supplier_keys(connection):
                raise RuntimeError('O banco ainda tem chaves de fornecedor cpf-sha256; rode make db-init antes de publicar.')
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
    """Revisões humanas do Placar na raiz da pasta (sem rascunhos nem auditorias). Devolve (None, []) quando não há nenhuma."""
    reviews_dir = Path(reviews_dir)
    packed = Path(out_dir) / f'reviews-{tag}.tar.gz'
    packed.unlink(missing_ok=True)
    if not reviews_dir.is_dir():
        return None, []
    with tarfile.open(packed, 'w:gz', compresslevel=9) as archive:
        # Só a raiz de data/reviews/: as subpastas guardam auditorias e cópias intermediárias.
        added = _add_tree(archive, reviews_dir, 'reviews', lambda relative: len(relative.parts) == 1 and is_review_file(relative.name))
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
        'como está.',
        '',
        f'**Licença:** esta compilação (banco, snapshots e revisões) está sob [{DATA_LICENSE}]({DATA_LICENSE_URL}): use, copie, '
        'modifique e redistribua para qualquer fim, inclusive comercial, citando "Painel Público" e o link do release. '
        'As informações em si são públicas e pertencem às respectivas fontes; o código do projeto está sob licença MIT. '
        'Veja o `LEGAL-NOTICE.md` do repositório.',
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


def github_token(environ=None):
    """Token do GitHub: variáveis de ambiente ou, como alternativa local, `gh auth token`."""
    environ = os.environ if environ is None else environ
    for name in TOKEN_VARIABLES:
        if environ.get(name):
            return environ[name].strip()
    if shutil.which('gh'):
        try:
            result = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, check=False)
        except OSError:
            result = None
        if result is not None and result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def _request(url, token, method='GET', data=None, content_type=None, content_length=None):
    headers = {'Accept': 'application/vnd.github+json', 'Authorization': f'Bearer {token}',
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'painelpublico-publish-data'}
    if content_type:
        headers['Content-Type'] = content_type
    if content_length is not None:
        headers['Content-Length'] = str(content_length)
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=600) as response:
        body = response.read()
    return json.loads(body.decode('utf-8')) if body else {}


def check_token(token):
    if not token:
        raise SystemExit('Sem token do GitHub: defina PAINEL_GITHUB_TOKEN (ou GH_TOKEN/GITHUB_TOKEN) ou rode `gh auth login`.')


def release_exists(tag, token, repo=GITHUB_REPO, request=_request):
    try:
        request(f'{API_URL}/repos/{repo}/releases/tags/{tag}', token)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise SystemExit(f'GitHub respondeu {error.code} ao consultar o release {tag}: {error.read().decode("utf-8", "replace")[:300]}')
    return True


def _content_type(path):
    name = Path(path).name
    if name.endswith('.json'):
        return 'application/json'
    if name.endswith('.gz'):
        return 'application/gzip'
    return 'application/octet-stream'


def publish_release(tag, files, notes_path, title=None, token=None, repo=GITHUB_REPO, branch=DEFAULT_BRANCH,
                    request=_request, log=print):
    """Cria o release (e a tag, no último commit do branch) e anexa os arquivos pela API REST."""
    check_token(token)
    if release_exists(tag, token, repo, request):
        raise SystemExit(f'O release {tag} já existe no GitHub. Escolha outra tag (TAG=...) ou apague o release antes.')
    payload = json.dumps({'tag_name': tag, 'target_commitish': branch, 'name': title or f'Dados {tag}',
                          'body': Path(notes_path).read_text(encoding='utf-8'), 'draft': False, 'prerelease': False}).encode('utf-8')
    try:
        release = request(f'{API_URL}/repos/{repo}/releases', token, method='POST', data=payload,
                          content_type='application/json')
    except urllib.error.HTTPError as error:
        raise SystemExit(f'GitHub respondeu {error.code} ao criar o release {tag}: {error.read().decode("utf-8", "replace")[:300]}')
    upload_url = release['upload_url'].split('{', 1)[0]
    for path in files:
        path = Path(path)
        log(f'enviando {path.name}')
        with open(path, 'rb') as handle:
            try:
                request(f'{upload_url}?name={path.name}', token, method='POST', data=handle,
                        content_type=_content_type(path), content_length=path.stat().st_size)
            except urllib.error.HTTPError as error:
                raise SystemExit(f'GitHub respondeu {error.code} ao enviar {path.name}: '
                                 f'{error.read().decode("utf-8", "replace")[:300]}. O release {tag} ficou incompleto; '
                                 'apague-o no GitHub e rode de novo.')
    return release.get('html_url') or f'https://github.com/{repo}/releases/tag/{tag}'


def default_tag(today=None):
    return f'data-{(today or date.today()).isoformat()}'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Publica banco, snapshots e revisões do Placar como release de dados no GitHub')
    parser.add_argument('--tag', default=None, help='tag do release (padrão: data-AAAA-MM-DD de hoje)')
    parser.add_argument('--title', default=None, help='título do release (padrão: "Dados <tag>")')
    parser.add_argument('--db', default=DEFAULT_DB, help='banco SQLite (padrão: data/na-lupa.sqlite3)')
    parser.add_argument('--snapshots', default=DEFAULT_SNAPSHOTS, help='pasta de snapshots (padrão: data/snapshots)')
    parser.add_argument('--reviews', default=DEFAULT_REVIEWS, help='pasta de revisões (padrão: reviews/, versionada)')
    parser.add_argument('--output', default=DEFAULT_OUTPUT, help='onde montar o pacote (padrão: data/releases)')
    parser.add_argument('--dry-run', action='store_true', help='só monta o pacote, sem publicar')
    args = parser.parse_args(argv)

    tag = args.tag or default_tag()
    if not tag.startswith(TAG_PREFIX):
        raise SystemExit(f'A tag de dados precisa começar com {TAG_PREFIX!r} (ex.: {default_tag()}).')
    token = None
    if not args.dry_run:
        token = github_token()
        check_token(token)
        if release_exists(tag, token):
            raise SystemExit(f'O release {tag} já existe no GitHub. Escolha outra tag (TAG=...) ou apague o release antes.')

    out_dir, files, notes_path = build_package(tag, args.db, args.snapshots, args.reviews, args.output, commit=git_commit())
    if args.dry_run:
        print(f'Pacote montado em {out_dir} (dry-run, nada publicado). Notas em {notes_path}.')
        return 0

    url = publish_release(tag, files, notes_path, args.title, token=token)
    print(f'Release {tag} publicado: {url}. Pacote local em {out_dir}.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
