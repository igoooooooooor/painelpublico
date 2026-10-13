"""Build estático sem dependências: python3 scripts/build.py.

Gera dist/index.html (o documento, pequeno) e dist/assets/app.<hash>.js e app.<hash>.css, com o hash do
conteúdo no nome: o HTML de cada página pode ficar pouco tempo em cache enquanto o código e o estilo, iguais
para todas as páginas, ficam em cache por um ano no navegador e na borda. Um build novo gera nomes novos e o
HTML passa a apontar para eles; os arquivos anteriores ficam alguns dias para páginas ainda em cache.
"""
import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SNAPSHOTS = Path(os.environ.get("PAINEL_SNAPSHOTS") or ROOT / "data" / "snapshots")
STYLES = ("tokens.css", "base.css", "citizen.css")
# Ordem explícita: helpers/views antes do bootstrap e router.
SCRIPTS = ("dates.js", "profile-data.js", "profile-cost.js", "profile-senate-cost.js", "share-card.js", "citizen-view.js",
           "extras-view.js", "parties-view.js", "home-view.js", "city-view.js", "scoreboard-view.js",
           "methodology-view.js", "app.script.js")
VOTE_METADATA = FRONTEND / "data" / "votes.json"
SITE_PAGES = FRONTEND / "data" / "site-pages.json"
ASSETS_DIRECTORY = "assets"
ASSET_PREFIX = "app."
STALE_ASSET_SECONDS = 7 * 86400


def _read_json(path, default):
    if not path.is_file():
        return default
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _party_totals(vote, rows):
    """Calcula o placar por partido a partir de todas as linhas da fonte."""
    if vote.get("secreta") or not isinstance(rows, list):
        return []
    grouped = defaultdict(Counter)
    for row in rows:
        if not isinstance(row, list) or len(row) < 5 or not isinstance(row[2], str):
            continue
        party, choice = row[2], row[4]
        if not (isinstance(choice, str) or choice is None):
            continue
        grouped[party][choice] += 1
    return [
        {"p": party, "sim": counts["Sim"], "nao": counts["Não"],
         "outros": sum(counts.values()) - counts["Sim"] - counts["Não"]}
        for party, counts in sorted(grouped.items(), key=lambda item: (-sum(item[1].values()), item[0]))
    ]


def site_pages():
    """Textos e metadados compartilhados entre o app e o servidor (frontend/data/site-pages.json)."""
    pages = _read_json(SITE_PAGES, None)
    if not isinstance(pages, dict) or not isinstance(pages.get("sections"), list):
        raise ValueError("frontend/data/site-pages.json deve conter 'sections', 'methodology' e 'about'")
    return {key: pages[key] for key in ("repository", "sections", "methodology", "about")}


def _content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _write_atomic(path, text):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _prune_assets(directory, keep, now=None):
    """Remove arquivos de builds antigos, deixando os recentes para páginas ainda em cache na borda."""
    now = time.time() if now is None else now
    for entry in directory.iterdir():
        if entry.name in keep or not entry.name.startswith(ASSET_PREFIX) or entry.suffix not in (".js", ".css"):
            continue
        try:
            if now - entry.stat().st_mtime > STALE_ASSET_SECONDS:
                entry.unlink()
        except OSError:
            pass


def build(output=None):
    metadata = _read_json(VOTE_METADATA, [])
    if not isinstance(metadata, list):
        raise ValueError("frontend/data/votes.json deve conter uma lista")

    # O arquivo versionado guarda só os resumos das quatro votações selecionadas.
    # A participação completa vem dos snapshots locais e fica separada dos metadados.
    votes_source = _read_json(SNAPSHOTS / "votos.json", {})
    if not isinstance(votes_source, dict):
        votes_source = {}
    selected_ids = [str(record["id"]) for record in metadata if isinstance(record, dict) and "id" in record]
    votes = {vote_id: votes_source[vote_id] for vote_id in selected_ids
             if isinstance(votes_source.get(vote_id), list)}
    vote_summaries = []
    for record in metadata:
        if not isinstance(record, dict):
            continue
        vote = dict(record)
        vote["partidos"] = _party_totals(vote, votes.get(str(vote.get("id")), []))
        vote_summaries.append(vote)

    presence = _read_json(SNAPSHOTS / "presenca.json", [])
    if not isinstance(presence, list):
        presence = []
    revenue = _read_json(SNAPSHOTS / "arrecadacao.json", None)
    if not isinstance(revenue, dict):
        revenue = None
    state_revenue = _read_json(SNAPSHOTS / "state-tax-revenue.json", None)
    if not isinstance(state_revenue, dict) or state_revenue.get("estadosComDado") != state_revenue.get("estadosEsperados"):
        state_revenue = None

    dates = [vote.get("data") for vote in vote_summaries if isinstance(vote.get("data"), str)]
    data = {
        "geradoEm": None,
        "ultimaVotacao": max(dates) if dates else None,
        "votacoes": vote_summaries,
        "presencaTodos": presence,
        "votosCompletos": votes,
        "arrecadacao": revenue,
        "arrecadacaoEstadual": state_revenue,
        "perfis": {"profiles": {}, "sobDemanda": any(
            (SNAPSHOTS / name).exists() for name in ("perfis.json", "senado-projetos.json", "eleicoes-2026.json", "mandate-cost.json", "senate-cost.json", "tenure.json")
        )},
        "senado": {"sobDemanda": (SNAPSHOTS / "senado-atividade.json").exists()},
        "sitePages": site_pages(),
    }

    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    script = "\n".join((FRONTEND / "scripts" / name).read_text(encoding="utf-8") for name in SCRIPTS)
    if script.count("/*DATA*/null") != 1:
        raise ValueError("Marcador de dados ausente ou duplicado")
    script = script.replace("/*DATA*/null", payload)
    styles = "\n".join((FRONTEND / "styles" / name).read_text(encoding="utf-8") for name in STYLES)
    html = (FRONTEND / "index.template.html").read_text(encoding="utf-8")
    for marker in ("{{STYLES}}", "{{SCRIPTS}}"):
        if html.count(marker) != 1:
            raise ValueError(f"Marcador {marker} ausente ou duplicado")

    output = Path(output) if output else ROOT / "dist" / "index.html"
    assets = output.parent / ASSETS_DIRECTORY
    assets.mkdir(parents=True, exist_ok=True)
    script_name = f"{ASSET_PREFIX}{_content_hash(script)}.js"
    style_name = f"{ASSET_PREFIX}{_content_hash(styles)}.css"
    _write_atomic(assets / script_name, script)
    _write_atomic(assets / style_name, styles)
    _prune_assets(assets, {script_name, style_name})
    html = (html.replace("{{STYLES}}", f'<link rel="stylesheet" href="/{ASSETS_DIRECTORY}/{style_name}">')
            .replace("{{SCRIPTS}}", f'<script src="/{ASSETS_DIRECTORY}/{script_name}" defer></script>'))
    _write_atomic(output, html)
    return output


if __name__ == "__main__":
    print(f"Gerado: {build().relative_to(ROOT)}")
