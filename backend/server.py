"""Servidor: python3 -m backend.server --port 8000 (local) ou --prod (publicado atrás do Cloudflare Tunnel)."""
import argparse
import gzip
import json
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from . import cidadao, perfis, public_store as store
from .config import BUILD_PATH

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

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlsplit(self.path)
        prod = getattr(self.server, 'prod', False)
        if url.path == '/healthz':
            ok = self.server.db_path.exists() and BUILD_PATH.is_file()
            self.send_json({'ok': ok}, 200 if ok else 503)
            return
        if url.path in ('/', '/index.html'):
            if not BUILD_PATH.is_file():
                message = 'Aplicativo ainda não compilado. Execute python3 scripts/build.py.'
                content = message.encode('utf-8')
                self.send_response(503)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(content)
                return
            self.send_body(BUILD_PATH.read_bytes(), 'text/html; charset=utf-8',
                           cache='public, max-age=60' if prod else 'no-store')
            return
        if url.path.startswith('/api/c/perfil/'):
            # Não depende do banco: vem do snapshot de perfis, carregado sob demanda pela ficha.
            found = perfis.perfil(unquote(url.path[len('/api/c/perfil/'):]))
            self.send_json(found if found is not None else {'error': 'Perfil complementar não encontrado.'},
                           200 if found is not None else 404, 'public, max-age=300' if prod else 'no-store')
            return
        if url.path == '/api/c/senado/atividade':
            # O arquivo local é lido somente quando esta rota é chamada e pode mudar entre consultas.
            found = perfis.atividade_senado()
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
        if cache is not None and url.path != '/api/expenses.csv':
            key = (self.server.db_path.stat().st_mtime_ns, self.path)
            hit = cache.get(key)
            if hit:
                self.send_body(hit[1], 'application/json; charset=utf-8', hit[0], 'public, max-age=300')
                return
        db = store.connect(self.server.db_path)
        deadline = time.monotonic() + QUERY_SECONDS
        db.set_progress_handler(lambda: time.monotonic() > deadline, 20000)
        try:
            # Keep counts, rows and the follow cursor on the same imported snapshot.
            db.execute('BEGIN')
            routes = {'/api/coverage': lambda: store.coverage(db),
                      '/api/authorities': lambda: store.authorities(db, params),
                      '/api/expenses': lambda: store.expenses(db, params),
                      '/api/signals': lambda: store.signals(db, params),
                      '/api/suppliers': lambda: store.suppliers(db, params),
                      '/api/c/radar': lambda: cidadao.radar(db, params),
                      '/api/c/resumo': lambda: cidadao.resumo(db),
                      '/api/c/politicos': lambda: cidadao.politicos(db, params),
                      '/api/c/partidos': lambda: cidadao.partidos(db)}
            if url.path in routes:
                result = routes[url.path]()
            elif url.path.startswith('/api/c/politico/'):
                result = cidadao.politico(db, unquote(url.path[len('/api/c/politico/'):]))
            elif url.path.startswith('/api/authorities/'):
                result = store.authority_detail(db, unquote(url.path[len('/api/authorities/'):]))
            elif url.path.startswith('/api/suppliers/'):
                result = store.supplier_detail(db, unquote(url.path[len('/api/suppliers/'):]))
            elif url.path == '/api/expenses.csv':
                store.expense_query(params)  # Validate filters before sending response headers.
                self.send_response(200)
                self.send_header('Content-Type', 'text/csv; charset=utf-8')
                self.send_header('Content-Disposition', 'attachment; filename="painel-publico-despesas.csv"')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')  # tamanho desconhecido: o fim da conexão marca o fim do arquivo
                self.close_connection = True
                self.end_headers()
                for chunk in store.csv_chunks(db, params):
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
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.db_path = args.db
    server.prod = args.prod
    server.cache = ResponseCache() if args.prod else None
    print(f'Painel Público{" (produção)" if args.prod else ""}: http://{args.host}:{args.port}', flush=True)
    server.serve_forever()
