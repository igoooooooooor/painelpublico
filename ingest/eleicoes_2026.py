"""Eleições de 2026 nas fichas: liga cada parlamentar da lista atual à sua candidatura no TSE.

Coleta manual (rede):     python3 ingest/eleicoes_2026.py --collect
Reconstrução (sem rede):  python3 ingest/eleicoes_2026.py

A ligação compara o nome civil e a data de nascimento publicados pelas APIs da Câmara e do Senado
com o arquivo de candidaturas do TSE, em regras graduais (ver `match`). CPF não é lido nem guardado. Nome civil e nascimento ficam só
no cache local (data/raw/tse/), nunca no snapshot servido ao app. Sem uma correspondência única,
a ficha não afirma nada sobre candidatura.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database import fold  # noqa: E402
from ingest.profiles import _atomic_json, _current_roster, _json_from_path, _request_json, utc_now  # noqa: E402

YEAR = 2026
CANDIDATES_URL = f"https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{YEAR}.zip"
DATASET_URL = f"https://dadosabertos.tse.jus.br/dataset/candidatos-{YEAR}"
CAMARA_DETAIL = "https://dadosabertos.camara.leg.br/api/v2/deputados/{}"
SENADO_DETAIL = "https://legis.senado.leg.br/dadosabertos/senador/{}.json"
# Calendário constitucional: 1º turno no primeiro domingo e 2º turno no último domingo de outubro.
SECOND_ROUND = "2026-10-25"
USER_AGENT = "QuantoCusta/1.0 (public-data importer)"
MAX_WORKERS = 4
RESULT_FIELDS = ("DS_CARGO", "SG_UF", "NM_UE", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO",
                 "NR_TURNO", "DT_ELEICAO", "DS_SIT_TOT_TURNO")


def paths(root: Path = ROOT) -> dict[str, Path]:
    raw = root / "data" / "raw" / "tse"
    return {
        "zip": raw / f"consulta_cand_{YEAR}.zip",
        "meta": raw / f"consulta_cand_{YEAR}.meta.json",
        "identities": raw / f"identidades-{YEAR}.json",
        "imports": root / "data" / "imports" / "legislative.json",
        "output": root / "data" / "snapshots" / f"eleicoes-{YEAR}.json",
    }


def name_key(value: Any) -> str:
    """Nome comparável: sem acentos, caixa, pontuação nem espaços repetidos."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", fold(value or "")).split())


def birth_key(value: Any) -> str | None:
    """Aceita AAAA-MM-DD (Câmara e Senado) ou DD/MM/AAAA (TSE) e devolve AAAA-MM-DD."""
    text = str(value or "").strip()[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    found = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", text)
    return f"{found[3]}-{found[2]}-{found[1]}" if found else None


def date_br_to_iso(value: Any) -> str | None:
    return birth_key(value)


def fetch_identity(authority_id: str, request_json: Callable[[str], dict] = _request_json) -> dict[str, Any] | None:
    """Nome civil e nascimento na API oficial da Casa; None se faltar algum dos dois."""
    chamber, code = authority_id.split(":", 1)
    if chamber == "camara":
        data = request_json(CAMARA_DETAIL.format(code)).get("dados") or {}
        found = {"nomeCivil": data.get("nomeCivil"), "nascimento": data.get("dataNascimento")}
    elif chamber == "senado":
        parlamentar = (request_json(SENADO_DETAIL.format(code)).get("DetalheParlamentar") or {}).get("Parlamentar") or {}
        found = {"nomeCivil": (parlamentar.get("IdentificacaoParlamentar") or {}).get("NomeCompletoParlamentar"),
                 "nascimento": (parlamentar.get("DadosBasicosParlamentar") or {}).get("DataNascimento")}
    else:
        return None
    if not name_key(found["nomeCivil"]) or not birth_key(found["nascimento"]):
        return None
    return {"nomeCivil": str(found["nomeCivil"]).strip(), "nascimento": birth_key(found["nascimento"]), "fetchedAt": utc_now()}


def collect_identities(roster: list[dict[str, Any]], cache: dict[str, Any], refresh: bool = False,
                       fetch: Callable[[str], dict[str, Any] | None] = fetch_identity) -> int:
    """Completa o cache de identidades. Falhas mantêm o valor anterior, sem apagar nada."""
    targets = [row["id"] for row in roster if refresh or not cache.get(row["id"])]

    def one(identifier: str):
        try:
            return identifier, fetch(identifier)
        except Exception:  # Uma consulta que falha não derruba a coleta das outras.
            return identifier, None
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for identifier, found in pool.map(one, targets):
            if found:
                cache[identifier] = found
    return len(targets)


def download_candidates(zip_path: Path, meta_path: Path) -> None:
    request = Request(CANDIDATES_URL, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=180) as response:
        content = response.read()
        modified = response.headers.get("Last-Modified")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:  # Valida antes de substituir o cache.
        if archive.testzip() is not None or not _brasil_csv(archive):
            raise ValueError("Arquivo do TSE sem a tabela nacional de candidaturas")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = zip_path.with_suffix(".zip.tmp")
    temporary.write_bytes(content)
    temporary.replace(zip_path)
    _atomic_json(meta_path, {"url": CANDIDATES_URL, "lastModified": modified, "fetchedAt": utc_now()})


def _brasil_csv(archive: zipfile.ZipFile) -> str | None:
    return next((name for name in archive.namelist() if name.upper().endswith(f"_{YEAR}_BRASIL.CSV")), None)


def read_candidates(zip_path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(zip_path) as archive:
        name = _brasil_csv(archive)
        if not name:
            raise ValueError("Arquivo do TSE sem a tabela nacional de candidaturas")
        text = archive.read(name).decode("latin-1")
    keep = RESULT_FIELDS + ("SQ_CANDIDATO", "NM_CANDIDATO", "DT_NASCIMENTO", "DT_GERACAO", "HH_GERACAO")
    return [{key: (row.get(key) or "").strip() for key in keep} for row in csv.DictReader(io.StringIO(text), delimiter=";")]


def _turn(row: dict[str, str]) -> int:
    return int(row["NR_TURNO"]) if row.get("NR_TURNO", "").isdigit() else 0


STOPWORDS = {"de", "da", "do", "das", "dos", "e"}
RULES = {
    "nome": "mesmo nome civil e mesma data de nascimento",
    "nome-parecido": "nome civil com as mesmas palavras (inclusive iniciais abreviadas) e mesma data de nascimento",
    "nome-de-urna": "nome de urna igual ao nome parlamentar, mesma UF e mesma data de nascimento",
    "ano-divergente": "mesmo nome civil e mesma UF; dia e mês de nascimento iguais e ano diferente em um ano",
}


def _words(value: Any) -> list[str]:
    return [word for word in name_key(value).split() if word not in STOPWORDS]


def _contained(short: list[str], long: list[str]) -> bool:
    """Palavras de `short` aparecem em `long`, na mesma ordem; uma inicial casa com palavra da mesma letra."""
    if len(short) < 2:
        return False
    rest = iter(long)
    return all(any(word == other or (len(word) == 1 and other.startswith(word)) for other in rest) for word in short)


def similar_names(civil: Any, candidate: Any) -> bool:
    a, b = _words(civil), _words(candidate)
    if not a or not b or a[0] != b[0]:
        return False
    return "".join(a) == "".join(b) or _contained(a, b) or _contained(b, a)


def _one_year_apart(first: str | None, second: str | None) -> bool:
    return bool(first and second and first[5:] == second[5:] and abs(int(first[:4]) - int(second[:4])) == 1)


def match(roster: list[dict[str, Any]], identities: dict[str, Any], candidates: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    """Uma candidatura por pessoa, pela primeira regra que der uma resposta única:

    1. mesma data de nascimento e mesmo nome civil (sem acentos, pontuação nem espaços);
    2. mesma data de nascimento e nomes com as mesmas palavras, em ordem (sobrenome a mais ou inicial abreviada);
    3. mesma data de nascimento, mesma UF e nome de urna igual ao nome parlamentar (nome social, grafia);
    4. mesmo nome civil e mesma UF, com dia e mês de nascimento iguais e ano diferente em um (erro de uma das fontes).
    Sem resposta única, nada é afirmado.
    """
    latest: dict[str, dict[str, str]] = {}
    for row in candidates:
        previous = latest.get(row["SQ_CANDIDATO"])
        if previous is None or _turn(row) >= _turn(previous):  # o turno mais recente traz o resultado final
            latest[row["SQ_CANDIDATO"]] = row
    by_birth: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_name_uf: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in latest.values():
        by_birth[birth_key(row["DT_NASCIMENTO"]) or ""].append(row)
        by_name_uf[(name_key(row["NM_CANDIDATO"]), row["SG_UF"])].append(row)
    out = {}
    for authority in roster:
        identity = identities.get(authority["id"])
        if not identity:
            out[authority["id"]] = {"status": "indisponivel"}
            continue
        civil, birth, uf = identity.get("nomeCivil"), birth_key(identity.get("nascimento")), authority.get("uf") or ""
        pool = by_birth.get(birth or "", [])
        compact = name_key(civil).replace(" ", "")
        attempts = (
            ("nome", [r for r in pool if name_key(r["NM_CANDIDATO"]).replace(" ", "") == compact]),
            ("nome-parecido", [r for r in pool if similar_names(civil, r["NM_CANDIDATO"])]),
            ("nome-de-urna", [r for r in pool if r["SG_UF"] == uf and name_key(r["NM_URNA_CANDIDATO"]) == name_key(authority.get("name"))]),
            ("ano-divergente", [r for r in by_name_uf.get((name_key(civil), uf), []) if _one_year_apart(birth, birth_key(r["DT_NASCIMENTO"]))]),
        )
        rule, rows = next(((rule, rows) for rule, rows in attempts if rows), (None, []))
        if not rows:
            out[authority["id"]] = {"status": "sem-correspondencia"}
        elif len(rows) > 1:
            out[authority["id"]] = {"status": "ambiguo"}
        else:
            row = rows[0]
            out[authority["id"]] = {
                "status": "encontrada", "criterio": rule, "cargo": row["DS_CARGO"], "uf": row["SG_UF"], "ue": row["NM_UE"],
                "numero": row["NR_CANDIDATO"], "nomeUrna": row["NM_URNA_CANDIDATO"], "partido": row["SG_PARTIDO"],
                "turno": _turn(row), "dataEleicao": date_br_to_iso(row["DT_ELEICAO"]), "situacao": row["DS_SIT_TOT_TURNO"],
            }
    return out

def build_snapshot(root: Path = ROOT, collect: bool = False, refresh: bool = False) -> dict[str, Any]:
    where = paths(root)
    roster = _current_roster(_json_from_path(where["imports"]))
    identities = _json_from_path(where["identities"]) if where["identities"].exists() else {}
    if collect:
        download_candidates(where["zip"], where["meta"])
        consulted = collect_identities(roster, identities, refresh)
        _atomic_json(where["identities"], identities)  # cache local; não vai para o snapshot
        print(f"identidades consultadas: {consulted}")
    if not where["zip"].exists():
        raise SystemExit("Arquivo do TSE ausente; rode com --collect.")
    candidates = read_candidates(where["zip"])
    meta = _json_from_path(where["meta"]) if where["meta"].exists() else {}
    profiles = match(roster, identities, candidates)
    first = candidates[0] if candidates else {}
    counts: dict[str, int] = {}
    for item in profiles.values():
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    snapshot = {
        "generatedAt": utc_now(),
        "ano": YEAR,
        "segundoTurno": SECOND_ROUND,
        "fonte": {
            "label": f"TSE — candidaturas {YEAR} (dados abertos)",
            "sourceUrl": DATASET_URL,
            "arquivo": CANDIDATES_URL,
            "geradoNoTse": " ".join(part for part in (first.get("DT_GERACAO"), first.get("HH_GERACAO")) if part) or None,
            "lastModified": meta.get("lastModified"),
            "fetchedAt": meta.get("fetchedAt"),
        },
        "metodo": "Nome civil e data de nascimento das APIs da Câmara e do Senado comparados com o arquivo de "
                  "candidaturas do TSE, sem CPF. Sem correspondência única, nada é afirmado.",
        "criterios": RULES,
        "cobertura": {"lista": len(roster), **counts},
        "profiles": profiles,
    }
    _atomic_json(where["output"], snapshot)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Liga a lista atual de parlamentares às candidaturas de 2026 no TSE")
    parser.add_argument("--collect", action="store_true", help="baixa o arquivo do TSE e completa nomes civis e nascimentos")
    parser.add_argument("--refresh", action="store_true", help="consulta de novo identidades que já estão no cache")
    args = parser.parse_args(argv)
    if args.refresh and not args.collect:
        parser.error("--refresh exige --collect")
    snapshot = build_snapshot(collect=args.collect, refresh=args.refresh)
    print("snapshot eleicoes", json.dumps(snapshot["cobertura"], ensure_ascii=False), f"gerado no TSE: {snapshot['fonte']['geradoNoTse']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
