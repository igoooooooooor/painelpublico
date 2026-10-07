"""Baixa dados e projetos de deputados adicionais e junta em raw/camara/deputados.json."""
from paths import RAW
import json, os, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
BASE = "https://dadosabertos.camara.leg.br/api/v2"
P = os.path.join(RAW, "camara", "deputados.json")
def get(url, params=None):
    if params: url += "?" + urllib.parse.urlencode(params)
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=60) as r: return json.load(r)
        except Exception as e:
            time.sleep(1.5 * (i + 1)); err = e
    print("FAIL", url, err, file=sys.stderr)
def paged(url, params):
    out = []
    while url:
        d = get(url, params); params = None
        if not d: break
        out += d["dados"]; nx = [l["href"] for l in d["links"] if l["rel"] == "next"]; url = nx[0] if nx else None
    return out
deps = json.load(open(P))
for did in sys.argv[1:]:
    if did in deps: continue
    info = get(f"{BASE}/deputados/{did}")["dados"]
    props = paged(f"{BASE}/proposicoes", {"idDeputadoAutor": did, "siglaTipo": "PL,PLP,PEC", "dataApresentacaoInicio": "2023-02-01", "itens": 100})
    def st(p):
        d = (get(f"{BASE}/proposicoes/{p['id']}") or {}).get("dados", {})
        s = d.get("statusProposicao") or {}
        return {"id": p["id"], "sigla": p["siglaTipo"], "numero": p["numero"], "ano": p["ano"], "ementa": p["ementa"], "situacao": s.get("descricaoSituacao")}
    with ThreadPoolExecutor(6) as ex: pl = list(ex.map(st, props))
    deps[did] = {"info": info, "projetos": pl}; print(info["ultimoStatus"]["nome"], len(pl))
json.dump(deps, open(P, "w"), ensure_ascii=False)
