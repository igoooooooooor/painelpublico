"""Lista de URLs com pesos para teste de carga, a partir da base e dos snapshots locais.

Imprime uma URL por linha; a repetição é o peso (a home aparece mais vezes que uma busca de cidade).
Uso com o oha (https://github.com/hatoo/oha):

    python3 scripts/load_test_urls.py https://painelpublico.com > /tmp/urls.txt
    oha -z 20s -c 500 -H 'Accept-Encoding: gzip' --urls-from-file /tmp/urls.txt

Sem argumento, usa http://127.0.0.1:8000. Método, resultados e limites em docs/performance.md.
"""
import json
import random
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import DB_PATH, SNAPSHOTS_PATH  # noqa: E402


def fold(text):
    return unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode().lower()


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', fold(name)).strip('-')


def load(name, key):
    try:
        data = json.loads((SNAPSHOTS_PATH / name).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return data.get(key) or []


def main(base):
    random.seed(7)
    weighted = []

    def add(path, weight):
        weighted.extend([path] * weight)

    add('/', 220)
    for section, weight in (('/politicos', 40), ('/placar', 40), ('/picos-e-concentracoes', 20), ('/comparar', 15), ('/minha-cidade', 15)):
        add(section, weight)
    add('/api/c/resumo', 40), add('/api/c/radar', 20), add('/api/c/partidos', 15), add('/api/c/politicos', 60)
    for page in range(2, 8):
        add(f'/api/c/politicos?page={page}', 5)
    for uf in ('SP', 'RJ', 'MG', 'BA', 'RS'):
        add(f'/api/c/politicos?uf={uf}', 6)

    people = []
    if DB_PATH.is_file():
        db = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
        people = db.execute("""SELECT DISTINCT a.id, a.name, a.role FROM authorities a JOIN roster r ON r.authorityId=a.id
                               WHERE r.sourceId IN ('camara_deputies_current', 'senado_senators_current')""").fetchall()
        random.shuffle(people)
    deputies = [row for row in people if row[2] == 'deputado'][:80]
    for identifier, name, role in people[:40]:
        add(f'/{role}/{identifier.split(":")[1]}-{slug(name)}', 2)
    for identifier, _, _ in people[:80]:
        add(f'/api/c/politico/{quote(identifier)}', 2)
        add(f'/api/c/perfil/{quote(identifier)}', 1)
    for identifier, _, _ in deputies[:60]:
        add(f'/api/c/votes/person/{quote(identifier)}', 1)
    for identifier, _, _ in deputies:
        add(f'/api/c/foto/{quote(identifier)}', 3)

    add('/api/c/votes', 60), add('/api/c/votes?page=2', 15), add('/api/c/votes?kind=segment', 10), add('/api/c/votes/party-totals', 10)
    for vote in load('chamber-votes.json', 'items')[:30]:
        add(f'/api/c/votes/{vote["id"]}', 2)

    cities = [city for city in load('cities.json', 'municipalities') if city.get('population')]
    cities.sort(key=lambda city: -city['population'])
    queries = sorted({fold(city['name'][:size]).strip() for city in cities[:60] for size in (3, 4, 5)})
    for query in queries[:120]:
        add(f'/api/c/cities?q={quote(query)}', 1)
    for city in cities[:40]:
        add(f'/api/c/cities/{city["id"]}', 1)
    add('/api/c/senado/atividade', 10)

    random.shuffle(weighted)
    print('\n'.join(base.rstrip('/') + path for path in weighted))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000')
