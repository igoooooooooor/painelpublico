"""Baixa o release de dados mais recente do GitHub e instala banco, snapshots e revisões em data/.

Uso: python3 scripts/fetch_data.py [--tag data-AAAA-MM-DD] [--force]

Só a biblioteca padrão: lista os releases públicos do repositório, escolhe o último com tag `data-`,
baixa os arquivos, confere o SHA-256 pelo manifest.json e instala em data/na-lupa.sqlite3,
data/snapshots/ e data/reviews/. Um banco existente só é substituído com --force (guardado antes
em data/backups/). Depois: make db-init, make build, make dev (o alvo make fetch-data encadeia tudo).
"""
import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.publish_data import API_URL, GITHUB_REPO, TAG_PREFIX, TOKEN_VARIABLES, sha256_of  # noqa: E402

DEFAULT_DATA_DIR = ROOT / 'data'
DB_NAME = 'na-lupa.sqlite3'
ASSET_KINDS = {'na-lupa-': 'database', 'snapshots-': 'snapshots', 'reviews-': 'reviews'}


class FetchError(Exception):
    pass


def _headers(token=None):
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
               'User-Agent': 'painelpublico-fetch-data'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _optional_token(environ=None):
    environ = os.environ if environ is None else environ
    for name in TOKEN_VARIABLES:
        if environ.get(name):
            return environ[name].strip()
    return None


def get_json(url, token=None):
    request = urllib.request.Request(url, headers=_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        raise FetchError(f'GitHub respondeu {error.code} em {url}') from error
    except urllib.error.URLError as error:
        raise FetchError(f'Sem acesso a {url}: {error.reason}') from error


def download(url, destination, token=None, log=print):
    destination = Path(destination)
    request = urllib.request.Request(url, headers={**_headers(token), 'Accept': 'application/octet-stream'})
    try:
        with urllib.request.urlopen(request, timeout=600) as response, open(destination, 'wb') as handle:
            shutil.copyfileobj(response, handle, 1024 * 1024)
    except urllib.error.HTTPError as error:
        destination.unlink(missing_ok=True)
        raise FetchError(f'GitHub respondeu {error.code} ao baixar {url}') from error
    except urllib.error.URLError as error:
        destination.unlink(missing_ok=True)
        raise FetchError(f'Sem acesso a {url}: {error.reason}') from error
    log(f'  {destination.name}: {destination.stat().st_size / (1024 * 1024):.1f} MB')
    return destination


def select_release(releases, tag=None):
    """O release pedido ou o mais recente com tag de dados, ignorando rascunhos e pré-lançamentos."""
    candidates = [release for release in releases
                  if not release.get('draft') and not release.get('prerelease')
                  and str(release.get('tag_name', '')).startswith(TAG_PREFIX)]
    if tag:
        for release in candidates:
            if release.get('tag_name') == tag:
                return release
        raise FetchError(f'Release {tag} não encontrado entre os releases de dados.')
    if not candidates:
        raise FetchError(f'Nenhum release de dados (tag {TAG_PREFIX}*) publicado em {GITHUB_REPO}.')
    return max(candidates, key=lambda release: (release.get('created_at') or '', release.get('tag_name') or ''))


def list_releases(repo=GITHUB_REPO, token=None, fetch_json=get_json):
    return fetch_json(f'{API_URL}/repos/{repo}/releases?per_page=50', token)


def asset_kind(name):
    for prefix, kind in ASSET_KINDS.items():
        if name.startswith(prefix):
            return kind
    return None


def verify_manifest(download_dir, manifest):
    """Confere SHA-256 e tamanho de cada arquivo listado; devolve os caminhos por tipo."""
    download_dir = Path(download_dir)
    found = {}
    for entry in manifest.get('files', []):
        path = download_dir / entry['name']
        if not path.is_file():
            raise FetchError(f'Arquivo do manifesto não baixado: {entry["name"]}')
        if path.stat().st_size != entry['bytes']:
            raise FetchError(f'Tamanho diferente do manifesto: {entry["name"]}')
        if sha256_of(path) != entry['sha256']:
            raise FetchError(f'SHA-256 diferente do manifesto: {entry["name"]}')
        kind = asset_kind(path.name)
        if kind:
            found[kind] = path
    if 'database' not in found:
        raise FetchError('O release não traz o banco SQLite.')
    return found


def _safe_extract(archive_path, destination):
    """Extrai o tar sem deixar membros escaparem da pasta de destino."""
    destination = Path(destination)
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if not member.isfile() and not member.isdir():
                raise FetchError(f'Membro inesperado no pacote: {member.name}')
            if destination.resolve() not in target.parents and target != destination.resolve():
                raise FetchError(f'Caminho fora da pasta de destino no pacote: {member.name}')
        if hasattr(tarfile, 'data_filter'):
            archive.extractall(destination, filter='data')
        else:
            archive.extractall(destination)


def _merge_tree(source, destination):
    """Copia os arquivos de source para destination, substituindo os de mesmo nome e mantendo os demais."""
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted(source.rglob('*')):
        if path.is_file():
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            copied += 1
    return copied


def install_package(found, data_dir, force=False, log=print, now=None):
    """Instala banco (gunzip), snapshots e revisões em data_dir. Banco existente exige force."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / DB_NAME
    if db_path.exists():
        if not force:
            raise FetchError(f'{db_path} já existe. Use --force (FORCE=1 no make) para substituí-lo; '
                             'uma cópia do atual fica em data/backups/.')
        stamp = (now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%SZ')
        backups = data_dir / 'backups'
        backups.mkdir(parents=True, exist_ok=True)
        kept = backups / f'na-lupa-before-fetch-{stamp}.sqlite3'
        shutil.move(str(db_path), str(kept))
        for suffix in ('-wal', '-shm'):
            Path(f'{db_path}{suffix}').unlink(missing_ok=True)
        log(f'banco anterior guardado em {kept}')

    temporary = data_dir / f'.{DB_NAME}.download'
    with gzip.open(found['database'], 'rb') as packed, open(temporary, 'wb') as handle:
        shutil.copyfileobj(packed, handle, 1024 * 1024)
    os.replace(temporary, db_path)
    log(f'banco instalado em {db_path}')

    summary = {'database': db_path, 'snapshots': 0, 'reviews': 0}
    for kind in ('snapshots', 'reviews'):
        archive = found.get(kind)
        if archive is None:
            continue
        with tempfile.TemporaryDirectory(prefix=f'.{kind}-', dir=data_dir) as staging:
            _safe_extract(archive, staging)
            extracted = Path(staging) / kind
            if not extracted.is_dir():
                raise FetchError(f'O pacote {archive.name} não contém a pasta {kind}/.')
            summary[kind] = _merge_tree(extracted, data_dir / kind)
        log(f'{kind}: {summary[kind]} arquivos em {data_dir / kind}')
    return summary


def fetch(tag=None, data_dir=DEFAULT_DATA_DIR, force=False, repo=GITHUB_REPO, token=None,
          fetch_json=get_json, downloader=download, keep_downloads=False, log=print):
    release = select_release(list_releases(repo, token, fetch_json), tag)
    tag = release['tag_name']
    assets = {asset['name']: asset for asset in release.get('assets', [])}
    if 'manifest.json' not in assets:
        raise FetchError(f'O release {tag} não traz manifest.json.')
    log(f'release {tag} ({release.get("html_url", "")})')
    download_dir = Path(data_dir) / 'releases' / tag
    download_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = downloader(assets['manifest.json']['browser_download_url'], download_dir / 'manifest.json', token, log)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for entry in manifest.get('files', []):
        asset = assets.get(entry['name'])
        if asset is None:
            raise FetchError(f'O release {tag} não traz {entry["name"]}, listado no manifesto.')
        target = download_dir / entry['name']
        if target.is_file() and target.stat().st_size == entry['bytes'] and sha256_of(target) == entry['sha256']:
            log(f'  {entry["name"]}: já baixado e conferido')
            continue
        downloader(asset['browser_download_url'], target, token, log)
    found = verify_manifest(download_dir, manifest)
    summary = install_package(found, data_dir, force=force, log=log)
    if not keep_downloads:
        shutil.rmtree(download_dir, ignore_errors=True)
        try:
            download_dir.parent.rmdir()  # só se ficou vazia
        except OSError:
            pass
    summary['tag'] = tag
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description='Baixa o release de dados do GitHub e instala em data/')
    parser.add_argument('--tag', default=None, help='tag do release (padrão: o mais recente com tag data-)')
    parser.add_argument('--data-dir', default=DEFAULT_DATA_DIR, help='pasta de dados (padrão: data/)')
    parser.add_argument('--force', action='store_true', help='substitui um banco existente, guardando cópia em data/backups/')
    parser.add_argument('--keep-downloads', action='store_true', help='mantém os arquivos baixados em data/releases/<tag>/')
    args = parser.parse_args(argv)
    try:
        summary = fetch(args.tag, Path(args.data_dir), force=args.force, token=_optional_token(),
                        keep_downloads=args.keep_downloads)
    except FetchError as error:
        print(f'erro: {error}', file=sys.stderr)
        return 1
    print(f'Dados do release {summary["tag"]} instalados. Agora: make db-init && make build && make dev')
    return 0


if __name__ == '__main__':
    sys.exit(main())
