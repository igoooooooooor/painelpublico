"""Baixa da API de Dados Abertos da Câmara o que o POC precisa:
from paths import RAW
sessões deliberativas do Plenário em 2026 (com presença), votações nominais
de 2026 (com votos e orientações) e projetos dos deputados escolhidos."""
import json, os, re, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

BASE = "https://dadosabertos.camara.leg.br/api/v2"
OUT = os.path.join(RAW, "camara")
os.makedirs(OUT, exist_ok=True)
DEPS = {"209787": "Nikolas Ferreira", "74161": "Reginaldo Lopes", "74646": "Aécio Neves", "160632": "Zé Silva"}


def get(path, params=None, tries=4):
    url = path if path.startswith("http") else BASE + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa
            if i == tries - 1:
                print("FAIL", url, e, file=sys.stderr)
                return None
            time.sleep(1.5 * (i + 1))


def paged(path, params):
    out, url, p = [], path, dict(params)
    while url:
        d = get(url, p)
        if not d:
            break
        out += d["dados"]
        nxt = [l["href"] for l in d.get("links", []) if l["rel"] == "next"]
        url, p = (nxt[0], None) if nxt else (None, None)
    return out


def save(name, obj):
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, ensure_ascii=False)


# 1) Sessões deliberativas do Plenário em 2026 e presença em cada uma
eventos = []
for (a, b) in [("2026-02-01", "2026-04-30"), ("2026-05-01", "2026-07-31"), ("2026-08-01", "2026-10-06")]:
    eventos += paged("/eventos", {"idOrgao": 180, "dataInicio": a, "dataFim": b, "itens": 100, "ordem": "ASC", "ordenarPor": "dataHoraInicio"})
sess = [e for e in eventos if e["descricaoTipo"].startswith("Sessão Deliberativa") and e["situacao"] == "Encerrada"]
print("eventos", len(eventos), "sessões deliberativas encerradas", len(sess))


def presenca(e):
    d = get(f"/eventos/{e['id']}/deputados")
    return {"id": e["id"], "inicio": e["dataHoraInicio"], "tipo": e["descricaoTipo"],
            "presentes": [str(x["id"]) for x in (d or {}).get("dados", [])], "ok": d is not None}

with ThreadPoolExecutor(6) as ex:
    sessoes = list(ex.map(presenca, sess))
save("sessoes.json", sessoes)
print("sessões salvas; sem lista de presença:", sum(1 for s in sessoes if not s["presentes"]))

# 2) Votações do Plenário em 2026; nominais = as que têm placar na descrição
vots = []
for (a, b) in [("2026-02-01", "2026-03-31"), ("2026-04-01", "2026-05-31"), ("2026-06-01", "2026-07-31"), ("2026-08-01", "2026-10-06")]:
    vots += paged("/votacoes", {"idOrgao": 180, "dataInicio": a, "dataFim": b, "itens": 200, "ordem": "ASC", "ordenarPor": "dataHoraRegistro"})
nom = [v for v in vots if re.search(r"Sim:\s*\d+", v.get("descricao") or "")]
print("votações", len(vots), "nominais", len(nom))


def detalhe(v):
    votos = get(f"/votacoes/{v['id']}/votos")
    ori = get(f"/votacoes/{v['id']}/orientacoes")
    det = get(f"/votacoes/{v['id']}")
    return {"id": v["id"], "data": v["dataHoraRegistro"], "descricao": v["descricao"], "aprovacao": v.get("aprovacao"),
            "detalhe": (det or {}).get("dados"),
            "votos": [{"id": str(x["deputado_"]["id"]), "voto": x["tipoVoto"], "partido": x["deputado_"]["siglaPartido"]} for x in (votos or {}).get("dados", [])],
            "orientacoes": (ori or {}).get("dados", [])}

with ThreadPoolExecutor(6) as ex:
    nominais = list(ex.map(detalhe, nom))
save("votacoes_nominais.json", nominais)
save("votacoes_todas.json", vots)

# 3) Dados e projetos de cada deputado escolhido (mandato atual, 2023 em diante)
deps = {}
for did in DEPS:
    info = get(f"/deputados/{did}")["dados"]
    props = paged("/proposicoes", {"idDeputadoAutor": did, "siglaTipo": "PL,PLP,PEC", "dataApresentacaoInicio": "2023-02-01", "itens": 100, "ordem": "DESC", "ordenarPor": "id"})

    def st(p):
        d = get(f"/proposicoes/{p['id']}")
        s = (d or {}).get("dados", {}).get("statusProposicao", {}) or {}
        return {"id": p["id"], "sigla": p["siglaTipo"], "numero": p["numero"], "ano": p["ano"], "ementa": p["ementa"],
                "situacao": s.get("descricaoSituacao"), "tramitacao": s.get("descricaoTramitacao"), "data": s.get("dataHora"),
                "apresentacao": (d or {}).get("dados", {}).get("dataApresentacao")}

    with ThreadPoolExecutor(6) as ex:
        plist = list(ex.map(st, props))
    deps[did] = {"info": info, "projetos": plist}
    print(DEPS[did], "projetos", len(plist))
save("deputados.json", deps)
print("ok")
