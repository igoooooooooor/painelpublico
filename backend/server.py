"""Servidor: python3 -m backend.server --port 8000 (local) ou --prod (publicado atrás do Cloudflare Tunnel)."""
import argparse
import gzip
import json
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from . import cities, citizen, database, profiles, public_store as store, seo, votes
from .config import BUILD_PATH, ROOT

FAVICON_PATH = ROOT / 'frontend' / 'static' / 'favicon.svg'
VOTE_DETAIL_PATH = re.compile(r'^/placar/\d+-\d+$')

QUERY_SECONDS = 8      # consulta que passar disso é abortada (protege o servidor público)
CACHE_ENTRIES = 3000   # respostas JSON guardadas em memória no modo --prod


class ResponseCache:
    """Cache em memória das respostas da API. A base só muda numa reimportação, então a chave inclui
    o mtime do arquivo SQLite: trocar o banco invalida tudo sem reiniciar o servidor."""

    def __init__(self, limit=CACHE_ENTRIES):
        self.limit, self.items, self.lock = limit, {}, threading.Lock()

    def get(self, key):
        with self.lock:
            return self.items.get(key)

    def put(self, key, value):
        with self.lock:
            if key[0] != next(iter(self.items), (key[0],))[0]:
                self.items.clear()  # banco novo: descarta respostas da versão anterior
            if len(self.items) >= self.limit:
                self.items.pop(next(iter(self.items)))
            self.items[key] = value


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def common_headers(self, cache):
        self.send_header('Cache-Control', cache)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('X-Frame-Options', 'DENY')

    def send_body(self, content, content_type, status=200, cache='no-store'):
        gz = 'gzip' in self.headers.get('Accept-Encoding', '') and len(content) > 1024
        if gz:
            content = gzip.compress(content, 6)
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        if gz:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Vary', 'Accept-Encoding')
        self.common_headers(cache)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(content)

    def send_json(self, data, status=200, cache='no-store'):
        content = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_body(content, 'application/json; charset=utf-8', status, cache)

    def send_page(self, path, prod):
        """Páginas do app com metadados e resumo para buscadores; cacheadas como a API."""
        if not BUILD_PATH.is_file():
            content = 'Aplicativo ainda não compilado. Execute python3 scripts/build.py.'.encode('utf-8')
            self.send_body(content, 'text/plain; charset=utf-8', 503)
            return
        origin = seo.site_origin(self.headers)
        database_ready = self.server.db_path.exists()
        cache = getattr(self.server, 'cache', None)
        key = None
        if cache is not None and database_ready:
            key = (self.server.db_path.stat().st_mtime_ns, 'page', path, origin, BUILD_PATH.stat().st_mtime_ns)
            hit = cache.get(key)
            if hit:
                self.send_page_result(*hit, prod)
                return
        page_html = BUILD_PATH.read_text(encoding='utf-8')
        if path in seo.SECTIONS:
            result = (200, seo.section_page(page_html, path, origin), 'text/html; charset=utf-8', None)
        elif not database_ready:
            # Sem banco, a ficha ainda abre pelo app; só não há resumo nem sitemap.
            result = (200 if path != '/sitemap.xml' else 503, page_html if path != '/sitemap.xml' else '', 'text/html; charset=utf-8', None)
        else:
            db = store.connect(self.server.db_path)
            try:
                if path == '/sitemap.xml':
                    result = (200, seo.sitemap(db, origin), 'application/xml; charset=utf-8', None)
                else:
                    status, content, redirect = seo.profile_page(db, page_html, path, origin)
                    result = (status, content or '', 'text/html; charset=utf-8', redirect)
            finally:
                db.close()
        if key is not None:
            cache.put(key, result)
        self.send_page_result(*result, prod)

    def send_page_result(self, status, content, content_type, redirect, prod):
        if redirect:
            self.send_response(301)
            self.send_header('Location', redirect)
            self.send_header('Content-Length', '0')
            self.common_headers('public, max-age=3600' if prod else 'no-store')
            self.end_headers()
            return
        self.send_body(content.encode('utf-8'), content_type, status, 'public, max-age=60' if prod else 'no-store')

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
        if url.path in ('/robots.txt', '/llms.txt'):
            text = seo.robots(seo.site_origin(self.headers)) if url.path == '/robots.txt' else seo.llms(seo.site_origin(self.headers))
            self.send_body(text.encode(), 'text/plain; charset=utf-8', cache='public, max-age=3600' if prod else 'no-store')
            return
        path = '/' if url.path == '/index.html' else url.path.rstrip('/') or '/'
        if VOTE_DETAIL_PATH.fullmatch(path):
            # Endereços compartilháveis usam a mesma página e metadados gerais do Placar.
            self.send_page('/placar', prod)
            return
        if path in seo.SECTIONS or path == '/sitemap.xml' or seo.PROFILE_PATH.match(path):
            self.send_page(path, prod)
            return
        if url.path == '/api/c/cities':
            query = parse_qs(url.query).get('q', [''])[-1]
            self.send_json(cities.search(query))
            return
        if url.path.startswith('/api/c/cities/'):
            found = cities.detail(unquote(url.path[len('/api/c/cities/'):]), self.server.db_path)
            self.send_json(found if found is not None else {'error': 'Cidade não encontrada na base local.'},
                           200 if found is not None else 404)
            return
        if url.path.startswith('/api/c/perfil/'):
            # Não depende do banco: vem do snapshot de perfis, carregado sob demanda pela ficha.
            found = profiles.profile(unquote(url.path[len('/api/c/perfil/'):]))
            self.send_json(found if found is not None else {'error': 'Perfil complementar não encontrado.'},
                           200 if found is not None else 404, 'public, max-age=300' if prod else 'no-store')
            return
        if url.path == '/api/c/votes':
            # O Placar vem de snapshots locais; não depende do SQLite nem do cache de respostas da API.
            params = {key: values[-1] for key, values in parse_qs(url.query).items()}
            self.send_json(votes.listing(params))
            return
        if url.path.startswith('/api/c/votes/'):
            identifier = unquote(url.path[len('/api/c/votes/'):])
            found = votes.detail(identifier)
            self.send_json(found if found is not None else {'error': 'Votação não encontrada na base local.'},
                           200 if found is not None else 404)
            return
        if url.path == '/api/c/senado/atividade':
            # O arquivo local é lido somente quando esta rota é chamada e pode mudar entre consultas.
            found = profiles.senate_activity()
            self.send_json(found if found is not None else {'error': 'Atividade do Senado não encontrada.'},
                           200 if found is not None else 404)
            return
        if not url.path.startswith('/api/'):
            self.send_json({'error': 'Recurso não encontrado.'}, 404)
            return
        params = {key: values[-1] for key, values in parse_qs(url.query).items()}
        if not self.server.db_path.exists():
            self.send_json({'error': 'Base ainda não importada. Execute python3 -m backend.public_store.'}, 503)
            return
        cache = getattr(self.server, 'cache', None)
        key = None
        if cache is not None and url.path != '/api/c/gastos.csv':
            key = (self.server.db_path.stat().st_mtime_ns, self.path)
            hit = cache.get(key)
            if hit:
                self.send_body(hit[1], 'application/json; charset=utf-8', hit[0], 'public, max-age=300')
                return
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
            elif url.path == '/api/c/gastos.csv' and (export := citizen.expenses_csv(db, params.get('id', ''))):
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
                return
            else:
                result = None
            status = 200 if result is not None else 404
            body = result if result is not None else {'error': 'Registro não encontrado.'}
            if key is not None:
                content = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
                cache.put(key, (status, content))
                self.send_body(content, 'application/json; charset=utf-8', status, 'public, max-age=300')
            else:
                self.send_json(body, status)
        except sqlite3.OperationalError as error:
            interrupted = 'interrupt' in str(error)
            self.send_json({'error': 'A consulta demorou demais. Tente um filtro menor.' if interrupted
                            else 'Não foi possível consultar a base local.'}, 503)
        except (ValueError, TypeError, ArithmeticError) as error:
            self.send_json({'error': str(error)}, 400)
        except sqlite3.Error:
            self.send_json({'error': 'Não foi possível consultar a base local.'}, 503)
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
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.db_path = args.db
    server.prod = args.prod
    server.cache = ResponseCache() if args.prod else None
    print(f'Painel Público{" (produção)" if args.prod else ""}: http://{args.host}:{args.port}', flush=True)
    server.serve_forever()
