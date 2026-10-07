"""Gera o data.json do app: panorama geral da Câmara + ficha de 10 deputados.
Toda conta que aparece no app é feita aqui, para poder ser auditada."""
import base64, json, os, re, statistics, urllib.request
from collections import defaultdict, Counter
import pandas as pd

from paths import SNAPSHOTS, RAW
H = str(SNAPSHOTS)
R = str(RAW); CAM = os.path.join(R, "camara")

# id Câmara -> SQ_CANDIDATO no TSE (conferido por nome, UF e partido)
DEPS = {"209787": "130002542026", "74161": "130002535317", "74646": "130002554332", "160632": "130002542724",
        "204534": "250002539435", "204536": "250002546642", "220645": "250002539612", "160541": "20002553272",
        "160674": "150002544205", "74858": "190002543101"}
ELEICAO = pd.Timestamp("2026-10-04")
VEDACAO_INICIO = ELEICAO - pd.Timedelta(days=120)  # Ato da Mesa 43/2009, art. 2º, XII
NOTAS = {"160674": "Preside a Câmara: pelo regimento, quem preside só vota para desempatar ou em votação secreta."}
CARGO = {"3": "Governador", "5": "Senador", "6": "Deputado federal"}

dep_all = json.load(open(os.path.join(R, "dep_all.json")))["dados"]
all_ids = [str(d["id"]) for d in dep_all]
uf_of = {str(d["id"]): d["siglaUf"] for d in dep_all}
camdeps = json.load(open(os.path.join(CAM, "deputados.json")))
PAG = json.load(open(os.path.join(R, "paginas", "paginas.json")))
PASS = json.load(open(os.path.join(R, "paginas", "passagens.json")))  # passagens aéreas (SIGEPA), fora do arquivo aberto
sessoes = sorted(json.load(open(os.path.join(CAM, "sessoes.json"))), key=lambda s: s["inicio"])
vots = json.load(open(os.path.join(CAM, "votacoes_nominais.json")))
todas = json.load(open(os.path.join(CAM, "votacoes_todas.json")))
ultima_votacao = max(v["data"] for v in todas)

# ---------- presença e alinhamento ----------
pres_rate = {i: sum(i in s["presentes"] for s in sessoes) / len(sessoes) for i in all_ids}
def alinhamento(did):
    tot = ok = 0
    for v in vots:
        g = next((o.get("orientacaoVoto") for o in v["orientacoes"] if o.get("siglaPartidoBloco") == "Governo"), None)
        voto = next((x["voto"] for x in v["votos"] if x["id"] == did), None)
        if g in ("Sim", "Não") and voto in ("Sim", "Não"):
            tot += 1; ok += voto == g
    return ok, tot
gov_rate = {i: (lambda a: a[0] / a[1] if a[1] else None)(alinhamento(i)) for i in all_ids}

# ---------- cota 2026 ----------
df = pd.read_csv(os.path.join(R, "Ano-2026.csv"), sep=";", encoding="utf-8-sig", dtype=str)
df = df[df.ideCadastro.notna()].copy()  # só deputados (tira lideranças)
df["v"] = df.vlrLiquido.astype(float)
# o arquivo registra o complemento de auxílio-moradia com sinal negativo; a página oficial soma o valor
comp = df.txtDescricao.str.startswith("COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA")
df.loc[comp, "v"] = df.loc[comp, "v"].abs()
df["data"] = pd.to_datetime(df.datEmissao, errors="coerce")
NOMES_CAT = {
    "MANUTENÇÃO DE ESCRITÓRIO DE APOIO À ATIVIDADE PARLAMENTAR": "Escritório",
    "LOCAÇÃO OU FRETAMENTO DE VEÍCULOS AUTOMOTORES": "Aluguel de carro",
    "COMBUSTÍVEIS E LUBRIFICANTES.": "Combustível",
    "DIVULGAÇÃO DA ATIVIDADE PARLAMENTAR.": "Divulgação",
    "HOSPEDAGEM ,EXCETO DO PARLAMENTAR NO DISTRITO FEDERAL.": "Hospedagem",
    "TELEFONIA": "Telefone", "SERVIÇO DE TÁXI, PEDÁGIO E ESTACIONAMENTO": "Táxi e pedágio",
    "FORNECIMENTO DE ALIMENTAÇÃO DO PARLAMENTAR": "Alimentação",
    "PASSAGENS TERRESTRES, MARÍTIMAS OU FLUVIAIS": "Ônibus e barco",
    "COMPLEMENTAÇÃO DO AUXÍLIO-MORADIA": "Complemento de moradia",
    "SERVIÇO DE SEGURANÇA PRESTADO POR EMPRESA ESPECIALIZADA.": "Segurança",
    "LOCAÇÃO OU FRETAMENTO DE AERONAVES": "Fretamento de avião",
    "ASSINATURA DE PUBLICAÇÕES": "Assinaturas", "SERVIÇOS POSTAIS": "Correios",
}
df["cat"] = df.txtDescricao.map(lambda c: NOMES_CAT.get(c, c.capitalize().rstrip(".")))
tot_dep = df.groupby("ideCadastro").v.sum().reindex(all_ids).fillna(0)
media_uf = {uf: float(tot_dep[[i for i in all_ids if uf_of[i] == uf]].mean()) for uf in set(uf_of.values())}

def foto(did):
    p = os.path.join(R, f"foto_{did}.jpg")
    if not os.path.exists(p):
        urllib.request.urlretrieve(f"https://www.camara.leg.br/internet/deputado/bandep/{did}.jpg", p)
    return "data:image/jpeg;base64," + base64.b64encode(open(p, "rb").read()).decode()

# ---------- panorama geral ----------
cats_all = df.groupby("cat").v.sum().sort_values(ascending=False)
top = tot_dep.sort_values(ascending=False).head(5)
info_all = {str(d["id"]): d for d in dep_all}
geral = {
    "cotaTotal": round(df.v.sum(), 2), "cotaNotas": int(len(df)), "cotaMediaDep": round(float(tot_dep.mean()), 2),
    "categorias": [{"nome": k, "valor": round(v, 2)} for k, v in cats_all.head(5).items()] +
                  [{"nome": "Outros", "valor": round(cats_all.iloc[5:].sum(), 2)}],
    "topGastos": [{"id": i, "nome": info_all[i]["nome"], "partido": info_all[i]["siglaPartido"], "uf": uf_of[i],
                   "valor": round(float(v), 2), "foto": foto(i)} for i, v in top.items()],
    "presencaMedia": round(statistics.mean(pres_rate.values()) * 100, 1),
    "govMedia": round(statistics.mean(x for x in gov_rate.values() if x is not None) * 100, 1),
    "sessoes": len(sessoes), "votacoesNominais": len(vots), "votacoesTotal": len(todas),
}

# ---------- TSE ----------
tse = pd.read_csv(os.path.join(R, "tse_totais.csv"), dtype=str); tse["QT"] = tse.QT.astype(int)
def eleicao(sq):
    r = tse[tse.SQ_CANDIDATO == sq].iloc[0]
    pool = tse[(tse.SG_UF == r.SG_UF) & (tse.CD_CARGO == r.CD_CARGO)].sort_values("QT", ascending=False).reset_index(drop=True)
    pos = int(pool.index[pool.SQ_CANDIDATO == sq][0]) + 1
    return {"cargo": CARGO[r.CD_CARGO], "situacao": r.DS_SIT_TOT_TURNO, "votos": int(r.QT), "posicao": pos, "uf": r.SG_UF}

def contato(did):
    """E-mail, telefone e endereço do gabinete e redes sociais, da API da Câmara (/deputados/{id})."""
    info = camdeps[did]["info"]; gab = info["ultimoStatus"]["gabinete"] or {}
    if (gab.get("predio") or "").isdigit():
        local = f"Anexo {gab['predio']}, {gab['andar']}º andar, gabinete {gab['sala']}"
    else:
        local = f"Gabinete {gab.get('sala')}"
    redes = []
    for u in info.get("redeSocial") or []:
        u = u.split("?")[0]
        nome = next((n for k, n in (("twitter", "X / Twitter"), ("x.com", "X / Twitter"), ("instagram", "Instagram"),
                                     ("facebook", "Facebook"), ("youtube", "YouTube"), ("tiktok", "TikTok")) if k in u), "Site")
        redes.append({"nome": nome, "url": u if u.startswith("http") else "https://" + u})
    return {"email": gab.get("email") or info["ultimoStatus"].get("email"), "telefone": f"(61) {gab.get('telefone')}" if gab.get("telefone") else None,
            "endereco": local, "cidade": "Câmara dos Deputados, Praça dos Três Poderes, Brasília (DF), CEP 70160-900", "redes": redes}

# ---------- 10 deputados ----------
out_deps = []
for did, sq in DEPS.items():
    ult = camdeps[did]["info"]["ultimoStatus"]; uf = ult["siglaUf"]
    pres = [did in s["presentes"] for s in sessoes]
    meses = defaultdict(list)
    for s, p in zip(sessoes, pres): meses[s["inicio"][:7]].append(p)
    d = df[df.ideCadastro == did]
    cats = d.groupby("cat").v.sum().sort_values(ascending=False)
    lanc = d.sort_values("data", ascending=False).head(6)
    alertas = []
    for c in ("Divulgação",):
        sub = d[d.cat == c]
        if sub.v.sum() >= 30000:
            f = sub.groupby("txtFornecedor").v.sum().sort_values(ascending=False)
            if f.iloc[0] / sub.v.sum() >= 0.5:
                alertas.append({"categoria": c, "fornecedor": f.index[0].strip(), "pct": round(f.iloc[0] / sub.v.sum() * 100)})
    # conta pelo mês de competência (julho em diante está inteiro dentro dos 120 dias);
    # notas emitidas em junho podem ser de serviço anterior ao prazo, então não entram
    ved = d[(d.cat == "Divulgação") & (d.numMes.astype(int) >= 7)]
    projs = camdeps[did]["projetos"]
    g = Counter("lei" if "Norma Jurídica" in (p.get("situacao") or "") else
                "encerrado" if any(k in (p.get("situacao") or "") for k in ("Arquivad", "Retirad", "Rejeitad", "Prejudicad")) else
                "tramitando" for p in projs)
    ok, tot = alinhamento(did)
    pg = PAG[did]
    sal = pg["salario"]
    cm = [pg["cota"]["meses"].get(str(m), 0) for m in range(1, 8)]      # jan-jul: meses já fechados
    gm = [pg["gabinete"]["meses"].get(str(m), 0) for m in range(1, 8)]
    aux = float(re.sub(r"[^\d,]", "", pg["auxilioMoradia"]).replace(",", ".") or 0) if "Recebeu" in pg["auxilioMoradia"] else 0.0
    csv_total = float(d.v.sum())
    aereo = PASS[did]["total"]
    sem_detalhe = pg["cota"]["gasto"] - csv_total - aereo
    cat_list = [{"nome": k, "valor": round(v, 2)} for k, v in cats.items()]
    if aereo > 0:
        cat_list.append({"nome": "Passagens aéreas", "valor": round(aereo, 2)})
    print("  conferência", did, "página", pg["cota"]["gasto"], "notas+passagens", round(csv_total + aereo, 2), "diferença", round(sem_detalhe, 2))
    if abs(sem_detalhe) > 1:
        cat_list.append({"nome": "Sem detalhe no arquivo aberto", "valor": round(sem_detalhe, 2)})
    cat_list.sort(key=lambda x: -x["valor"])
    out_deps.append({
        "id": did, "nome": ult["nomeEleitoral"], "partido": ult["siglaPartido"], "uf": uf, "foto": foto(did),
        "eleicao": eleicao(sq), "nota": NOTAS.get(did), "contato": contato(did),
        "presenca": {"presente": pg["presencas"], "justificadas": pg["justificadas"], "naoJustificadas": pg["naoJustificadas"],
                     "dias": pg["dias"], "viagensMissao": pg["viagens"]},
        "governo": {"ok": ok, "total": tot},
        "custo": {"salario": sal, "cotaMes": round(sum(cm) / 7, 2), "gabineteMes": round(sum(gm) / 7, 2),
                  "auxilioMoradia": aux, "mes": round(sal + sum(cm) / 7 + sum(gm) / 7, 2),
                  "ano": round(sal * 9 + pg["cota"]["gasto"] + pg["gabinete"]["gasto"] + aux, 2),
                  "pessoal": pg["pessoal"], "imovelFuncional": pg["imovelFuncional"], "auxilioTexto": pg["auxilioMoradia"],
                  "gabineteGasto": pg["gabinete"]["gasto"], "gabineteLimite": round(pg["gabinete"]["gasto"] + pg["gabinete"]["naoUsado"], 2),
                  "gabineteMeses": max(int(k) for k in pg["gabinete"]["meses"]) if pg["gabinete"]["meses"] else 0},
        "cota": {"total": pg["cota"]["gasto"], "limite": round(pg["cota"]["gasto"] + pg["cota"]["naoUsado"], 2),
                 "notas": int(len(d)), "porMes": {int(k): v for k, v in pg["cota"]["meses"].items()},
                 "categorias": cat_list,
                 "lancamentos": [{"data": str(r.data.date()), "fornecedor": r.txtFornecedor.strip(), "cat": r.cat,
                                  "valor": round(r.v, 2), "url": r.urlDocumento} for r in lanc.itertuples()],
                 "alertas": alertas, "divulgacaoVedada": int(len(ved))},
        "projetos": {"total": len(projs), "lei": g["lei"], "tramitando": g["tramitando"], "encerrado": g["encerrado"],
                     "lista": [{"t": f"{p['sigla']} {p['numero']}/{p['ano']}", "e": (p["ementa"] or "")[:220],
                                "s": p.get("situacao") or "", "id": p["id"]} for p in sorted(projs, key=lambda p: -int(p["id"]))]},
    })

# ---------- votações em destaque, com placar por partido ----------
destaques = json.load(open(os.path.join(H, "na_pratica.json")))
V = {v["id"]: v for v in vots}
out_vot = []
for dz in destaques:
    v = V[dz["id"]]
    m = re.search(r"Sim:\s*(\d+);\s*Não:\s*(\d+)", v["descricao"])
    secreta = not any(x.get("voto") for x in v["votos"])
    partidos = []
    if not secreta:
        c = defaultdict(Counter)
        for x in v["votos"]: c[x["partido"]][x["voto"]] += 1
        for p, cc in sorted(c.items(), key=lambda kv: -sum(kv[1].values())):
            partidos.append({"p": p, "sim": cc["Sim"], "nao": cc["Não"], "outros": sum(cc.values()) - cc["Sim"] - cc["Não"]})
    votos = {x["id"]: x["voto"] for x in v["votos"]}
    out_vot.append({**dz, "data": v["data"], "sim": int(m.group(1)), "nao": int(m.group(2)), "aprovada": v["aprovacao"] == 1,
                    "secreta": secreta, "partidos": partidos,
                    "votos": {did: (votos[did] if did in votos else "Ausente") for did in DEPS}})

out = {"geradoEm": "2026-10-06", "ultimaVotacao": ultima_votacao, "ultimoLancamento": str(df.data.max().date()),
       "vedacaoInicio": str(VEDACAO_INICIO.date()), "geral": geral, "deputados": out_deps, "votacoes": out_vot}
out = json.loads(json.dumps(out), parse_constant=lambda value: None)  # valores ausentes do pandas → null
json.dump(out, open(os.path.join(H, "editorial.json"), "w"), ensure_ascii=False, allow_nan=False)
print(json.dumps({k: v for k, v in geral.items() if k != "topGastos"}, ensure_ascii=False))
print([(t["nome"], t["uf"], t["valor"]) for t in geral["topGastos"]])
for dd in out_deps:
    print(dd["nome"], dd["uf"], dd["presenca"]["presente"], dd["governo"],
          dd["cota"]["total"], dd["custo"]["mes"], dd["custo"]["ano"], dd["cota"]["divulgacaoVedada"], dd["presenca"]["justificadas"])
for v in out_vot: print(v["id"], v["sim"], v["nao"], v["partidos"][:3])
print("bytes", os.path.getsize(os.path.join(H, "editorial.json")))
