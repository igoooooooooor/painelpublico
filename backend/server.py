"""Servidor: python3 -m backend.server --port 8000 (local) ou --prod (publicado atrás do Cloudflare Tunnel)."""
import argparse
import gzip
import json
import os
import re
import sqlite3
import sys
import threading
import time
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NamedTuple
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

from . import cities, citizen, database, photos, profiles, public_store as store, seo, votes
from .config import BUILD_PATH, ROOT

FAVICON_PATH = ROOT / 'frontend' / 'static' / 'favicon.svg'
OG_IMAGE_PATH = ROOT / 'frontend' / 'static' / 'og-image.png'
ASSETS_PATH = BUILD_PATH.parent / 'assets'
# Só os arquivos gerados pelo build (nome com hash do conteúdo) saem da pasta dist; nada de dados ou snapshots.
ASSET_NAME = re.compile(r'^app\.[0-9a-f]{12}\.(js|css)$')
ASSET_TYPES = {'js': 'text/javascript; charset=utf-8', 'css': 'text/css; charset=utf-8'}

QUERY_SECONDS = 8      # consulta que passar disso é abortada (protege o servidor público)
CACHE_ENTRIES = 3000   # respostas guardadas em memória no modo --prod
LISTEN_BACKLOG = 1024  # conexões que esperam na fila do sistema numa rajada (o padrão do Python, 5, recusa o excesso)
COMPUTE_SLOTS = max(2, min(8, os.cpu_count() or 2))  # respostas calculadas ao mesmo tempo; as outras esperam a vez
SNAPSHOT_CHECK_SECONDS = 1  # a pasta de snapshots é conferida no máximo uma vez por segundo
IDLE_SECONDS = 120     # conexão parada além disso é fechada (o túnel fecha as suas ociosas antes, em 90 s)
QUERY_ERRORS = (sqlite3.Error, ValueError, TypeError, ArithmeticError)
# Parâmetros que cada rota lê; os demais são descartados antes da consulta e da chave do cache. Assim um
# parâmetro inventado (?x=123) não fura o cache nem obriga a refazer uma resposta cara como /api/c/resumo.
API_PARAMS = {
    '/api/c/radar': ('tipo', 'cargo', 'id', 'ano', 'page', 'pageSize'),
    '/api/c/politicos': ('cargo', 'q', 'ordem', 'page', 'pageSize'),
    '/api/c/notas': ('id', 'mes'),
    '/api/c/gastos.csv': ('id',),
    '/api/c/cities': ('q',),
    '/api/c/votes': ('page', 'pageSize', 'kind', 'q', 'type', 'theme', 'result'),
}


def route_params(url):
    """Só os parâmetros conhecidos da rota (o último valor de cada um)."""
    allowed = API_PARAMS.get(url.path, ())
    return {key: values[-1] for key, values in parse_qs(url.query).items() if key in allowed}


def cache_path(url):
    """Endereço normalizado para a chave do cache: caminho e parâmetros conhecidos, em ordem fixa."""
    params = route_params(url)
    query = urlencode(sorted(params.items()))
    return url.path + ('?' + query if query else '')


def compressible(body, content_type):
    return len(body) > 1024 and not content_type.startswith('image/')  # JPEG e PNG já são comprimidos


class Response(NamedTuple):
    """Resposta pronta para enviar. `gz` é a versão comprimida, feita uma única vez quando compensa,
    para que uma página de 800 KB não seja comprimida de novo a cada visita."""
    status: int
    content_type: str
    body: bytes
    gz: bytes | None = None
    redirect: str | None = None

    @classmethod
    def build(cls, status, content_type, body, redirect=None):
        return cls(status, content_type, body, gzip.compress(body, 6) if compressible(body, content_type) else None, redirect)

    @classmethod
    def json(cls, data, status=200):
        return cls.build(status, 'application/json; charset=utf-8', json.dumps(data, ensure_ascii=False, allow_nan=False).encode())


def error_response(error):
    """Mensagem pública para um erro de consulta (QUERY_ERRORS); nunca expõe o erro interno do SQLite."""
    if isinstance(error, sqlite3.OperationalError):
        interrupted = 'interrupt' in str(error)
        return Response.json({'error': 'A consulta demorou demais. Tente um filtro menor.' if interrupted
                              else 'Não foi possível consultar a base local.'}, 503)
    if isinstance(error, sqlite3.Error):
        return Response.json({'error': 'Não foi possível consultar a base local.'}, 503)
    return Response.json({'error': str(error)}, 400)


BUSY_MESSAGE = 'O site está com muitos acessos neste momento. Tente de novo em instantes.'
BUSY_JSON = Response.json({'error': BUSY_MESSAGE}, 503)
BUSY_HTML = Response.build(503, 'text/html; charset=utf-8',
                           f'<!doctype html><meta charset="utf-8"><title>Painel Público</title><p>{BUSY_MESSAGE}'.encode('utf-8'))


def snapshot_signature():
    """Nome, data e tamanho de cada arquivo das pastas de snapshots: qualquer gravação ou remoção muda a assinatura,
    então uma resposta montada a partir de snapshots nunca sobrevive a uma atualização deles."""
    signature = []
    for folder in sorted({str(cities.SNAPSHOTS_PATH), str(profiles.SNAPSHOTS_PATH), str(votes.SNAPSHOTS_PATH)}):
        try:
            with os.scandir(folder) as entries:
                signature.append(tuple(sorted((entry.name, entry.stat().st_mtime_ns, entry.stat().st_size)
                                              for entry in entries)))
        except OSError:
            signature.append(None)
    return tuple(signature)


class _Pending:
    __slots__ = ('done', 'result')

    def __init__(self):
        self.done, self.result = threading.Event(), None


class ResponseCache:
    """Cache em memória das respostas. A chave começa pela família ('api', 'page', 'snapshot') e pela geração
    dos dados de que a família depende (data do arquivo SQLite, assinatura da pasta de snapshots): a base só muda
    numa reimportação, então trocar o arquivo invalida as respostas da família sem reiniciar o servidor.
    Pedidos simultâneos da mesma chave esperam o primeiro cálculo em vez de repetir a consulta, o que evita a
    avalanche de consultas iguais logo depois de o cache esvaziar."""

    def __init__(self, limit=CACHE_ENTRIES, slots=COMPUTE_SLOTS):
        self.limit, self.items, self.lock = limit, OrderedDict(), threading.Lock()
        self.generations, self.pending = {}, {}
        self.slots, self.slot_wait = threading.BoundedSemaphore(slots), QUERY_SECONDS
        self.snapshot_memo = (0.0, None)  # (válida até, assinatura)

    def snapshot_generation(self, check_seconds=SNAPSHOT_CHECK_SECONDS):
        """Assinatura da pasta de snapshots, relida no máximo a cada `check_seconds` (ler 40 arquivos a cada
        pedido custa pouco sozinho, mas sob mil conexões cada chamada ao sistema cede a vez a outra thread)."""
        now = time.monotonic()
        with self.lock:
            valid_until, value = self.snapshot_memo
            if value is not None and now < valid_until:
                return value
        value = snapshot_signature()
        with self.lock:
            self.snapshot_memo = (now + check_seconds, value)
        return value

    def get(self, key):
        with self.lock:
            hit = self.items.get(key)
            if hit is not None:
                self.items.move_to_end(key)  # as respostas mais pedidas ficam; as esquecidas saem primeiro
            return hit

    def put(self, key, value):
        family, generation = key[0], key[1]
        with self.lock:
            if self.generations.get(family) != generation:
                for old in [item for item in self.items if item[0] == family]:
                    del self.items[old]  # dados novos: descarta as respostas da versão anterior
                self.generations[family] = generation
            while len(self.items) >= self.limit:
                self.items.popitem(last=False)
            self.items[key] = value

    def fetch(self, key, compute, busy=BUSY_JSON):
        """Resposta em cache ou calculada por `compute` (que devolve (resposta, guardar?)) uma vez só:
        quem pede a mesma chave durante o cálculo recebe o mesmo resultado, inclusive um erro."""
        with self.lock:
            hit = self.items.get(key)
            if hit is not None:
                self.items.move_to_end(key)
                return hit
            pending = self.pending.get(key)
            leader = pending is None
            if leader:
                pending = self.pending[key] = _Pending()
        if not leader:
            pending.done.wait(self.slot_wait + QUERY_SECONDS + 2)
            if pending.result is not None:
                return pending.result
            return self._compute(key, compute, busy)  # o primeiro cálculo não terminou ou falhou: calcula por conta própria
        try:
            pending.result = self._compute(key, compute, busy)
            return pending.result
        finally:
            with self.lock:
                self.pending.pop(key, None)
            pending.done.set()

    def _compute(self, key, compute, busy):
        # Poucos cálculos de cada vez: numa rajada com o cache vazio, os pedidos esperam a vez em fila em vez de
        # disputar o processador todos juntos e estourar o limite de 8 s sem terminar nenhum. Quem espera demais
        # recebe 503 na hora, barato, e tenta de novo quando o cache já estiver cheio.
        if not self.slots.acquire(timeout=self.slot_wait):
            return busy
        try:
            response, cacheable = compute()
        finally:
            self.slots.release()
        if cacheable:
            self.put(key, response)
        return response


class Server(ThreadingHTTPServer):
    request_queue_size = LISTEN_BACKLOG
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Visitante que fechou a conexão no meio da resposta não é erro do servidor nem merece um traceback no log.
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    timeout = IDLE_SECONDS

    def log_request(self, code='-', size='-'):
        # Em produção só respostas de erro vão ao journal: o acesso normal fica nas métricas do Cloudflare,
        # e o journald não gasta CPU por requisição numa rajada de visitas.
        status = code.value if isinstance(code, HTTPStatus) else code
        if getattr(self.server, 'prod', False) and str(status).startswith(('2', '3')):
            return
        super().log_request(code, size)

    def common_headers(self, cache):
        self.send_header('Cache-Control', cache)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('X-Frame-Options', 'DENY')

    def send_body(self, content, content_type, status=200, cache='no-store', gz=None):
        accepts_gzip = 'gzip' in self.headers.get('Accept-Encoding', '')
        if accepts_gzip and gz is None and compressible(content, content_type):
            gz = gzip.compress(content, 6)
        compressed = accepts_gzip and gz is not None
        if compressed:
            content = gz
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        if compressed:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Vary', 'Accept-Encoding')
        self.common_headers(cache)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(content)

    def send_json(self, data, status=200, cache='no-store'):
        content = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_body(content, 'application/json; charset=utf-8', status, cache)

    def send_prepared(self, response, cache):
        """Envia uma resposta pronta, do cache ou recém-calculada, sem comprimir de novo."""
        if response.redirect:
            self.send_response(301)
            self.send_header('Location', response.redirect)
            self.send_header('Content-Length', '0')
            self.common_headers(cache)
            self.end_headers()
            return
        self.send_body(response.body, response.content_type, response.status, cache, response.gz)

    def database_generation(self):
        """Data do arquivo SQLite, ou None sem banco. Muda a cada publicação da base."""
        try:
            return self.server.db_path.stat().st_mtime_ns
        except OSError:
            return None

    def snapshot_generation(self, cache):
        """Geração das rotas de snapshot: assinatura da pasta (memorizada) e data do banco, que Minha cidade também lê."""
        check_seconds = getattr(self.server, 'snapshot_check_seconds', SNAPSHOT_CHECK_SECONDS)
        return (cache.snapshot_generation(check_seconds), self.database_generation())

    def send_page(self, path, prod):
        """Páginas do app com metadados e conteúdo inicial para pessoas sem JavaScript e buscadores; cacheadas como a API.
        A chave inclui o banco, o build e os snapshots: as seções leem Placar, presença e cidades dos arquivos locais."""
        if not BUILD_PATH.is_file():
            content = 'Aplicativo ainda não compilado. Execute python3 scripts/build.py.'.encode('utf-8')
            self.send_body(content, 'text/plain; charset=utf-8', 503)
            return
        origin = seo.site_origin(self.headers)
        database_ready = self.server.db_path.exists()
        cache = getattr(self.server, 'cache', None)

        def compute():
            page_html = BUILD_PATH.read_text(encoding='utf-8')
            db = store.connect(self.server.db_path) if database_ready else None
            try:
                if path == '/sitemap.xml':
                    if db is None:
                        return Response.build(503, 'text/plain; charset=utf-8', b'Base ainda nao importada.'), False
                    return Response.build(200, 'application/xml; charset=utf-8', seo.sitemap(db, origin).encode('utf-8')), True
                if db is not None:
                    db.execute('BEGIN')  # os números de uma página saem da mesma fotografia do banco
                status, content, redirect = seo.page(db, page_html, path, origin)
                # Só páginas e redirecionamentos ficam em cache: endereços inexistentes não ocupam as vagas da memória.
                return Response.build(status, 'text/html; charset=utf-8', (content or '').encode('utf-8'), redirect), database_ready and status in (200, 301)
            except QUERY_ERRORS as error:
                return error_response(error), False
            finally:
                if db is not None:
                    db.close()

        if cache is not None and database_ready:
            key = ('page', (self.database_generation(), BUILD_PATH.stat().st_mtime_ns, cache.snapshot_generation(
                getattr(self.server, 'snapshot_check_seconds', SNAPSHOT_CHECK_SECONDS))), path, origin)
            response = cache.fetch(key, compute, BUSY_HTML)
        else:
            response = compute()[0]
        if response.redirect:
            self.send_prepared(response, 'public, max-age=3600' if prod else 'no-store')
        elif response.status == 200:
            self.send_prepared(response, 'public, max-age=60' if prod else 'no-store')
        else:
            self.send_prepared(response, 'no-store')

    def send_asset(self, name, prod):
        """JavaScript e CSS do build, com nome que muda a cada conteúdo: cache longo e imutável."""
        path = ASSETS_PATH / name
        cache = getattr(self.server, 'cache', None)
        try:
            generation = path.stat().st_mtime_ns
        except OSError:
            self.send_json({'error': 'Recurso não encontrado.'}, 404)
            return

        def compute():
            return Response.build(200, ASSET_TYPES[name.rsplit('.', 1)[1]], path.read_bytes()), True

        response = cache.fetch(('asset', generation, name), compute) if cache is not None else compute()[0]
        self.send_prepared(response, 'public, max-age=31536000, immutable' if prod else 'no-store')

    def send_snapshot_route(self, compute, prod, url):
        """Rotas montadas a partir dos snapshots locais (Placar, cidades, perfis, Senado), sem o SQLite.
        Em produção a resposta fica em cache enquanto os arquivos não mudarem."""
        cache = getattr(self.server, 'cache', None)
        if cache is None:
            response = compute()[0]
        else:
            response = cache.fetch(('snapshot', self.snapshot_generation(cache), cache_path(url)), compute)
        self.send_prepared(response, 'public, max-age=300' if prod and cache is not None else 'no-store')

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlsplit(self.path)
        prod = getattr(self.server, 'prod', False)
        if url.path == '/healthz':
            ok = self.server.db_path.exists() and BUILD_PATH.is_file()
            self.send_json({'ok': ok}, 200 if ok else 503)
            return
        if url.path in ('/favicon.svg', '/favicon.ico'):
            # Um ícone só, em SVG; /favicon.ico (pedido automático de navegadores e robôs) recebe o mesmo arquivo.
            self.send_body(FAVICON_PATH.read_bytes(), 'image/svg+xml', cache='public, max-age=86400' if prod else 'no-store')
            return
        if url.path.startswith('/assets/'):
            name = url.path[len('/assets/'):]
            if ASSET_NAME.fullmatch(name):
                self.send_asset(name, prod)
            else:
                self.send_json({'error': 'Recurso não encontrado.'}, 404)
            return
        if url.path == '/og-image.png' and OG_IMAGE_PATH.is_file():
            self.send_body(OG_IMAGE_PATH.read_bytes(), 'image/png', cache='public, max-age=86400' if prod else 'no-store')
            return
        if url.path in ('/robots.txt', '/llms.txt'):
            text = seo.robots(seo.site_origin(self.headers)) if url.path == '/robots.txt' else seo.llms(seo.site_origin(self.headers))
            self.send_body(text.encode(), 'text/plain; charset=utf-8', cache='public, max-age=3600' if prod else 'no-store')
            return
        path = '/' if url.path == '/index.html' else url.path.rstrip('/') or '/'
        if not path.startswith('/api/'):
            # Páginas conhecidas recebem metadados e conteúdo; qualquer outro endereço, a página 404 do site.
            self.send_page(path, prod)
            return
        snapshot_route = self.snapshot_route(url)
        if snapshot_route is not None:
            self.send_snapshot_route(snapshot_route, prod, url)
            return
        if url.path.startswith('/api/c/foto/'):
            # Foto oficial pelo próprio domínio, para entrar na imagem de compartilhar (canvas sem CORS).
            data = photos.photo(unquote(url.path[len('/api/c/foto/'):]), known=self.known_politician)
            if data is None:
                self.send_json({'error': 'Foto não disponível.'}, 404, 'public, max-age=3600' if prod else 'no-store')
            else:
                self.send_body(data, 'image/jpeg', cache='public, max-age=604800' if prod else 'no-store')
            return
        params = route_params(url)
        if not self.server.db_path.exists():
            self.send_json({'error': 'Base ainda não importada. Execute python3 -m backend.public_store.'}, 503)
            return
        if url.path == '/api/c/gastos.csv':
            self.send_expenses_csv(params)
            return
        cache = getattr(self.server, 'cache', None)

        def compute():
            db = store.connect(self.server.db_path)
            deadline = time.monotonic() + QUERY_SECONDS
            db.set_progress_handler(lambda: time.monotonic() > deadline, 20000)
            try:
                # Counts and rows of one response come from the same imported snapshot.
                db.execute('BEGIN')
                routes = {'/api/c/radar': lambda: citizen.radar(db, params),
                          '/api/c/resumo': lambda: citizen.summary(db),
                          '/api/c/politicos': lambda: citizen.politicians(db, params),
                          '/api/c/partidos': lambda: citizen.parties(db),
                          '/api/c/notas': lambda: citizen.month_notes(db, params.get('id', ''), params.get('mes', ''))}
                if url.path in routes:
                    result = routes[url.path]()
                elif url.path.startswith('/api/c/politico/'):
                    result = citizen.politician(db, unquote(url.path[len('/api/c/politico/'):]))
                else:
                    result = None
                if result is None:
                    return Response.json({'error': 'Registro não encontrado.'}, 404), True
                return Response.json(result), True
            except QUERY_ERRORS as error:
                return error_response(error), False
            finally:
                db.close()

        if cache is None:
            response = compute()[0]
        else:
            response = cache.fetch(('api', self.database_generation(), cache_path(url)), compute)
        cacheable = cache is not None and response.status in (200, 404)
        try:
            self.send_prepared(response, 'public, max-age=300' if cacheable else 'no-store')
        except (BrokenPipeError, ConnectionResetError):
            pass

    def known_politician(self, identifier):
        """Deputado(a) ou senador(a) da base; sem banco, ninguém (a foto cai nas iniciais)."""
        if not self.server.db_path.exists():
            return False
        db = store.connect(self.server.db_path)
        try:
            return db.execute("SELECT 1 FROM authorities WHERE id=? AND role IN ('deputado','senador')",
                              (identifier,)).fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            db.close()

    def snapshot_route(self, url):
        """Função que monta a resposta de uma rota de snapshot, ou None se o caminho não for uma delas."""
        def found_or(found, message, status=404):
            return (Response.json(found) if found is not None else Response.json({'error': message}, status)), True

        if url.path == '/api/c/cities':
            query = route_params(url).get('q', '')
            return lambda: (Response.json(cities.search(query)), True)
        if url.path.startswith('/api/c/cities/'):
            identifier = unquote(url.path[len('/api/c/cities/'):])
            return lambda: found_or(cities.detail(identifier, self.server.db_path), 'Cidade não encontrada na base local.')
        if url.path.startswith('/api/c/perfil/'):
            # Não depende do banco: vem do snapshot de perfis, carregado sob demanda pela ficha.
            identifier = unquote(url.path[len('/api/c/perfil/'):])
            return lambda: found_or(profiles.profile(identifier), 'Perfil complementar não encontrado.')
        if url.path == '/api/c/votes':
            # O Placar vem de snapshots locais; não depende do SQLite.
            params = route_params(url)
            return lambda: (Response.json(votes.listing(params)), True)
        if url.path == '/api/c/votes/party-totals':
            # Totais por partido do catálogo do Placar, para comparar partidos na mesma base.
            return lambda: (Response.json(votes.party_totals()), True)
        if url.path.startswith('/api/c/votes/person/'):
            # Voto de um(a) deputado(a) em cada votação do Placar.
            identifier = unquote(url.path[len('/api/c/votes/person/'):])
            return lambda: found_or(votes.person_votes(identifier), 'Identificador inválido.')
        if url.path.startswith('/api/c/votes/'):
            identifier = unquote(url.path[len('/api/c/votes/'):])
            return lambda: found_or(votes.detail(identifier), 'Votação não encontrada na base local.')
        if url.path == '/api/c/senado/atividade':
            # O arquivo local é lido somente quando esta rota é chamada e pode mudar entre consultas.
            return lambda: found_or(profiles.senate_activity(), 'Atividade do Senado não encontrada.')
        return None

    def send_expenses_csv(self, params):
        """Download das notas de um(a) parlamentar; sem cache, em partes, até o fim da conexão."""
        db = store.connect(self.server.db_path)
        deadline = time.monotonic() + QUERY_SECONDS
        db.set_progress_handler(lambda: time.monotonic() > deadline, 20000)
        try:
            db.execute('BEGIN')
            export = citizen.expenses_csv(db, params.get('id', ''))
            if not export:
                self.send_json({'error': 'Registro não encontrado.'}, 404)
                return
            filename, chunks = export
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv; charset=utf-8')
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.common_headers('no-store')
            self.send_header('Connection', 'close')  # tamanho desconhecido: o fim da conexão marca o fim do arquivo
            self.close_connection = True
            self.end_headers()
            if self.command != 'HEAD':
                for chunk in chunks:
                    self.wfile.write(chunk.encode('utf-8'))
        except QUERY_ERRORS as error:
            self.send_prepared(error_response(error), 'no-store')
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='127.0.0.1', help='Use 0.0.0.0 para abrir no celular na mesma rede Wi-Fi')
    parser.add_argument('--db', type=store.Path, default=store.DB_PATH)
    parser.add_argument('--prod', action='store_true', help='Publicação: cache de respostas e cabeçalhos para o Cloudflare')
    args = parser.parse_args()
    try:
        database.ensure_schema(args.db)  # um banco antigo ganha as tabelas novas antes da primeira consulta
    except (sqlite3.Error, OSError, RuntimeError) as error:
        print(f'Aviso: não foi possível atualizar o esquema do banco: {error}', flush=True)
    server = Server((args.host, args.port), Handler)
    server.db_path = args.db
    server.prod = args.prod
    server.cache = ResponseCache() if args.prod else None
    print(f'Painel Público{" (produção)" if args.prod else ""}: http://{args.host}:{args.port}', flush=True)
    server.serve_forever()
