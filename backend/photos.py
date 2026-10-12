"""Fotos oficiais de deputados(as) e senadores(as) servidas pelo próprio domínio.

As imagens de compartilhar são desenhadas em canvas no navegador. Uma foto de outro domínio sem CORS (caso da
Câmara) "contamina" o canvas e impede exportar o PNG; servida daqui, a foto pode entrar na imagem.

Segurança: a URL de origem é montada a partir do identificador (``camara:204515``, ``senado:5672``); nenhuma URL
vinda de fora é aceita, então isto não vira um proxy aberto. A resposta precisa ser JPEG, pequena e vir de um
host oficial. Cada foto é baixada sob demanda e guardada em disco (``data/cache/fotos``, fora do Git) por 30 dias;
uma falha fica anotada por um dia para não repetir a consulta a cada pedido.
"""
from __future__ import annotations

import os
import re
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .config import DB_PATH

PHOTO_ID = re.compile(r'^(camara|senado):(\d{1,9})$')
SOURCES = {
    'camara': 'https://www.camara.leg.br/internet/deputado/bandep/{number}.jpg',
    'senado': 'https://www.senado.leg.br/senadores/img/fotos-oficiais/senador{number}.jpg',
}
ALLOWED_HOSTS = {'www.camara.leg.br', 'www.senado.leg.br', 'legis.senado.leg.br'}
MAX_BYTES = 1_500_000
TIMEOUT_SECONDS = 8
FRESH_SECONDS = 30 * 86400
MISS_SECONDS = 86400
_cache_setting = os.environ.get('PAINEL_PHOTOS')
CACHE_DIR = Path(_cache_setting).expanduser() if _cache_setting else DB_PATH.parent / 'cache' / 'fotos'


def _is_jpeg(data: bytes) -> bool:
    return len(data) > 64 and data[:3] == b'\xff\xd8\xff'


def download(url: str) -> bytes | None:
    """Baixa a foto oficial; devolve None se não vier um JPEG de um host oficial dentro do limite."""
    request = urllib.request.Request(url, headers={'User-Agent': 'PainelPublico/1.0 (+https://painelpublico.com)'})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if urlsplit(response.geturl()).hostname not in ALLOWED_HOSTS:
            return None
        if not response.headers.get('Content-Type', '').lower().startswith('image/jpeg'):
            return None
        data = response.read(MAX_BYTES + 1)
    return data if len(data) <= MAX_BYTES and _is_jpeg(data) else None


def _fresh(path: Path, seconds: int, now: float) -> bool:
    try:
        return now - path.stat().st_mtime < seconds
    except FileNotFoundError:
        return False


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(data)
    os.replace(handle.name, path)


def photo(identifier: str, fetch=download, now: float | None = None, cache_dir: Path | None = None) -> bytes | None:
    """JPEG da foto oficial, do cache quando recente. Sem foto disponível, None (a imagem usa as iniciais)."""
    match = PHOTO_ID.fullmatch(str(identifier or ''))
    if not match:
        return None
    house, number = match.groups()
    now = time.time() if now is None else now
    folder = cache_dir or CACHE_DIR
    path, miss = folder / f'{house}-{number}.jpg', folder / f'{house}-{number}.miss'
    if _fresh(path, FRESH_SECONDS, now):
        return path.read_bytes()
    stale = path.read_bytes() if path.exists() else None
    if _fresh(miss, MISS_SECONDS, now):
        return stale
    try:
        data = fetch(SOURCES[house].format(number=number))
    except Exception:  # fora do ar, tempo esgotado, 404: fica a cópia antiga ou as iniciais
        data = None
    try:
        if data and _is_jpeg(data):
            _write_atomic(path, data)
            miss.unlink(missing_ok=True)
            return data
        _write_atomic(miss, b'')
    except OSError:  # sem permissão de escrita: serve sem guardar
        return data if data and _is_jpeg(data) else stale
    return stale
