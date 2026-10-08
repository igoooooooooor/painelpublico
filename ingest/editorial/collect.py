"""Coletas complementares manuais de presença e votos da Câmara."""
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from paths import CACHE, ROOT, SNAPSHOTS

CHAMBER_API = "https://dadosabertos.camara.leg.br/api/v2"
DEPUTIES_URL = CHAMBER_API + "/deputados?" + urllib.parse.urlencode({
    "itens": 100, "pagina": 1, "ordem": "ASC", "ordenarPor": "nome",
})
DEPUTIES_CACHE = CACHE / "deps-completo.json"
LEGACY_DEPUTIES_CACHE = CACHE / "deps.json"
VOTE_METADATA = ROOT / "frontend" / "data" / "votes.json"


def get(url, filename, js=False):
    """Read a saved official response or fetch it during an explicit collection command."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / filename
    if not path.exists():
        for attempt in range(3):
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json" if js else "text/html",
                }
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=40) as response:
                    path.write_bytes(response.read())
                break
            except Exception as error:  # pragma: no cover - network behavior
                if attempt == 2:
                    print("FAIL", url, error, file=sys.stderr)
                    return None
                time.sleep(2)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    return json.loads(text) if js else text


def paged(url, cache_prefix, fetch=get):
    """Follow every official next link; the API may cap the requested page size."""
    current_url = url
    seen_urls = set()
    rows = []
    page = 0
    while current_url:
        if current_url in seen_urls:
            raise ValueError(f"A paginação repetiu uma página: {current_url}")
        seen_urls.add(current_url)
        page += 1
        response = fetch(current_url, f"{cache_prefix}-page-{page}.json", js=True)
        if not isinstance(response, dict) or not isinstance(response.get("dados"), list):
            raise ValueError(f"Resposta sem lista de dados na página {page}")
        rows.extend(row for row in response["dados"] if isinstance(row, dict))
        links = response.get("links")
        next_link = next((link.get("href") for link in links
                          if isinstance(link, dict) and link.get("rel") == "next"), None) \
            if isinstance(links, list) else None
        if not next_link:
            current_url = ""
            continue
        current_url = urljoin(current_url, next_link)
        parts = urlsplit(current_url)
        if parts.scheme != "https" or parts.hostname != "dadosabertos.camara.leg.br":
            raise ValueError("Link de paginação fora do domínio oficial da Câmara")
    if not rows:
        raise ValueError("A Câmara não retornou registros para a lista de deputados")
    return {"dados": rows, "links": []}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def vote_metadata(path=VOTE_METADATA):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or any(not isinstance(item, dict) or not item.get("id") for item in data):
        raise ValueError("frontend/data/votes.json deve listar os IDs das votações selecionadas")
    return data


def collect_votes(fetch=get, output=SNAPSHOTS / "votos.json", metadata_path=VOTE_METADATA):
    """Save full participant rows for the versioned vote cards, using local response caches."""
    out = {}
    for vote in vote_metadata(metadata_path):
        vote_id = str(vote["id"])
        response = fetch(f"{CHAMBER_API}/votacoes/{vote_id}/votos", f"votos_{vote_id}.json", js=True)
        if not isinstance(response, dict) or not isinstance(response.get("dados"), list):
            raise ValueError(f"Resposta de votos incompleta para {vote_id}")
        participants = []
        for row in response["dados"]:
            person = row.get("deputado_") if isinstance(row, dict) else None
            if not isinstance(person, dict) or person.get("id") is None or not str(person["id"]).strip():
                continue
            participants.append([
                person.get("id"), person.get("nome"), person.get("siglaPartido"),
                person.get("siglaUf"), row.get("tipoVoto"),
            ])
        out[vote_id] = participants
        print(vote_id, len(out[vote_id]))
    write_json(output, out)
    return out


def collect_deputies(fetch=get, output=DEPUTIES_CACHE):
    result = paged(DEPUTIES_URL, "deps", fetch=fetch)
    write_json(output, result)
    print(len(result["dados"]))
    return result


def load_deputies(path=DEPUTIES_CACHE):
    """Require the new paginated cache; the old single-response cache may be truncated."""
    path = Path(path)
    if not path.is_file():
        legacy = " O cache anterior foi preservado; rode a coleta paginada `deps` para criar um novo." \
            if LEGACY_DEPUTIES_CACHE.is_file() else ""
        raise FileNotFoundError(f"Falta {path.name}.{legacy}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("dados"), list) or not data["dados"]:
        raise ValueError(f"{path.name} não contém a lista paginada de deputados")
    return data["dados"]


def collect_presence(seconds, fetch=get):
    deputies = load_deputies()
    deadline = time.time() + float(seconds)

    def one(deputy):
        if time.time() > deadline:
            return None
        identifier = deputy.get("id")
        if identifier is None:
            return None
        return fetch(f"https://www.camara.leg.br/deputados/{identifier}/presenca-plenario/2026",
                     f"pres_{identifier}.html")

    with ThreadPoolExecutor(6) as executor:
        list(executor.map(one, deputies))
    cached = sum((CACHE / f"pres_{deputy.get('id')}.html").is_file() for deputy in deputies)
    print(f"cache de presença: {cached}/{len(deputies)} deputados")


# A presença do mandato (presenca.json) vem de ingest/chamber_mandate_history.py; esta versão só de 2026
# grava em arquivo separado para não sobrescrevê-la.
def build_presence(output=SNAPSHOTS / "presenca-2026.json"):
    deputies = load_deputies()
    out = []
    for deputy in deputies:
        identifier = deputy.get("id")
        if identifier is None:
            continue
        path = CACHE / f"pres_{identifier}.html"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        days = re.findall(
            r'info-data__data-formatada">\s*(\d\d/\d\d/\d{4}).*?</td>\s*<td[^>]*>.*?</td>\s*'
            r'<td class="info-presenca-dia">\s*(.*?)\s*</td>', text, flags=re.S,
        )
        statuses = [html.unescape(re.sub(r"<[^>]+>", "", status)).strip() for _, status in days]
        if not statuses:
            continue
        present = sum(status == "Presença" for status in statuses)
        absent = sum(status == "Ausência" for status in statuses)
        reasons = {}
        for status in statuses:
            if status not in ("Presença", "Ausência"):
                reasons[status] = reasons.get(status, 0) + 1
        out.append({
            "id": identifier, "nome": deputy.get("nome"), "partido": deputy.get("siglaPartido"),
            "uf": deputy.get("siglaUf"), "dias": len(statuses), "presente": present,
            "falta": absent, "justificadas": len(statuses) - present - absent,
            "motivos": sorted(reasons.items(), key=lambda item: -item[1])[:3],
        })
    write_json(output, out)
    print(f"presença processada: {len(out)}/{len(deputies)} deputados com cache válido")
    return out


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("Uso: collect.py votes | deputies | presence SEGUNDOS | build")
    command = {"votos": "votes", "deps": "deputies", "pres": "presence"}.get(args[0], args[0])
    if command == "votes":
        collect_votes()
    elif command == "deputies":
        collect_deputies()
    elif command == "presence":
        if len(args) < 2:
            raise SystemExit("Uso: collect.py presence SEGUNDOS")
        collect_presence(args[1])
    elif command == "build":
        build_presence()
    else:
        raise SystemExit("Uso: collect.py votes | deputies | presence SEGUNDOS | build")


if __name__ == "__main__":
    main()
