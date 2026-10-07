"""Build estático sem dependências: python3 scripts/build.py."""
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SNAPSHOTS = Path(os.environ.get("PAINEL_SNAPSHOTS") or ROOT / "data" / "snapshots")
STYLES = ("tokens.css", "base.css", "public-data.css", "cidadao.css")
# Ordem explícita: helpers/views antes do bootstrap e router.
SCRIPTS = ("profile-data.js", "public-data-view.js", "cidadao-view.js",
           "extras-view.js", "partidos-view.js", "home-view.js", "app.script.js")
VOTE_METADATA = FRONTEND / "data" / "votacoes.json"


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


def build(output=None):
    metadata = _read_json(VOTE_METADATA, [])
    if not isinstance(metadata, list):
        raise ValueError("frontend/data/votacoes.json deve conter uma lista")

    # O arquivo versionado guarda só os resumos das quatro votações selecionadas.
    # A participação completa vem dos snapshots locais e fica separada dos metadados.
    votes_source = _read_json(SNAPSHOTS / "votos.json", {})
    if not isinstance(votes_source, dict):
        votes_source = {}
    selected_ids = [str(record["id"]) for record in metadata if isinstance(record, dict) and "id" in record]
    votes = {vote_id: votes_source[vote_id] for vote_id in selected_ids
             if isinstance(votes_source.get(vote_id), list)}
    votacoes = []
    for record in metadata:
        if not isinstance(record, dict):
            continue
        vote = dict(record)
        vote["partidos"] = _party_totals(vote, votes.get(str(vote.get("id")), []))
        votacoes.append(vote)

    presence = _read_json(SNAPSHOTS / "presenca.json", [])
    if not isinstance(presence, list):
        presence = []
    arrecadacao = _read_json(SNAPSHOTS / "arrecadacao.json", None)
    if not isinstance(arrecadacao, dict):
        arrecadacao = None

    dates = [vote.get("data") for vote in votacoes if isinstance(vote.get("data"), str)]
    data = {
        "geradoEm": None,
        "ultimaVotacao": max(dates) if dates else None,
        "votacoes": votacoes,
        "presencaTodos": presence,
        "votosCompletos": votes,
        "arrecadacao": arrecadacao,
        "perfis": {"profiles": {}, "sobDemanda": any(
            (SNAPSHOTS / name).exists() for name in ("perfis.json", "senado-projetos.json")
        )},
        "senado": {"sobDemanda": (SNAPSHOTS / "senado-atividade.json").exists()},
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
    html = html.replace("{{STYLES}}", styles).replace("{{SCRIPTS}}", script)
    output = Path(output) if output else ROOT / "dist" / "index.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".html.tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(output)
    return output


if __name__ == "__main__":
    print(f"Gerado: {build().relative_to(ROOT)}")
