"""Raspa as páginas oficiais dos deputados na Câmara (www.camara.leg.br/deputados/ID):
presença dia a dia com justificativa, cota (total, limite, mês a mês), verba de gabinete,
pessoal, salário, imóvel funcional e auxílio-moradia. Salva em raw/paginas/paginas.json."""
import html, json, os, re, sys, time, urllib.request

from paths import SNAPSHOTS, RAW
H = str(SNAPSHOTS)
OUT = os.path.join(RAW, "paginas"); os.makedirs(OUT, exist_ok=True)
IDS = sys.argv[1:]
MES = {m: i + 1 for i, m in enumerate("JAN FEV MAR ABR MAI JUN JUL AGO SET OUT NOV DEZ".split())}


def fetch(url, fn):
    p = os.path.join(OUT, fn)
    if not os.path.exists(p):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        open(p, "wb").write(urllib.request.urlopen(req, timeout=60).read()); time.sleep(0.8)
    return open(p, encoding="utf-8", errors="ignore").read()


def text(t):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s)))


num = lambda s: float(s.replace(".", "").replace(",", "."))


def bloco(s, titulo):
    """Lê 'Total (R$) Percentual Gasto X% Não utilizado Y%' e a tabela mês a mês de um bloco."""
    i = s.find(titulo + " ?")
    b = s[i:i + 1500]
    for fim in ("Detalhamento", "Veja mais"):
        if fim in b: b = b[:b.find(fim)]
    m = re.search(r"Percentual Gasto ([\d.,]+) [\d.,]+% Não utilizado ([\d.,]+)", b)
    meses = {MES[k]: num(v) for k, v in re.findall(r"\b(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ) ([\d.,]+)", b)}
    return {"gasto": num(m.group(1)), "naoUsado": num(m.group(2)), "meses": meses}


res = {}
for did in IDS:
    s = text(fetch(f"https://www.camara.leg.br/deputados/{did}?ano=2026", f"{did}.html"))
    pres = re.search(r"Presenças na Câmara (\d+) dias Ausências justificadas (\d+) dias Ausências não justificadas (\d+) dias", s)
    r = {"presencas": int(pres.group(1)), "justificadas": int(pres.group(2)), "naoJustificadas": int(pres.group(3)),
         "cota": bloco(s, "Cota parlamentar"), "gabinete": bloco(s, "Verba de gabinete")}
    m = re.search(r"Pessoal de gabinete \? (\d+) pessoas neste ano, sendo (\d+) ativas", s)
    r["pessoal"] = {"ano": int(m.group(1)), "ativos": int(m.group(2))} if m else None
    r["salario"] = num(re.search(r"Salário mensal bruto \? R\$ ([\d.,]+)", s).group(1))
    r["imovelFuncional"] = re.search(r"Imóvel funcional \? (.+?) Auxílio-moradia", s).group(1).strip()
    r["auxilioMoradia"] = re.search(r"Auxílio-moradia \? (.+?) Viagens", s).group(1).strip()
    m = re.search(r"Viagens em missão oficial \? (\d+)", s); r["viagens"] = int(m.group(1)) if m else 0
    m = re.search(r"Informações de gastos atualizadas em ([\d/]+)", s); r["atualizado"] = m.group(1) if m else None
    # presença dia a dia
    t = fetch(f"https://www.camara.leg.br/deputados/{did}/presenca-plenario/2026", f"pres_{did}.html")
    dias = re.findall(r'info-data__data-formatada">\s*(\d\d/\d\d/\d{4}).*?</td>\s*<td[^>]*>.*?</td>\s*<td class="info-presenca-dia">\s*(.*?)\s*</td>', t, flags=re.S)
    r["dias"] = [{"d": f"{d[6:10]}-{d[3:5]}-{d[0:2]}", "s": html.unescape(re.sub(r"<[^>]+>", "", st)).strip()} for d, st in dias]
    res[did] = r
    print(did, r["presencas"], r["justificadas"], r["naoJustificadas"], len(r["dias"]), r["cota"]["gasto"], r["gabinete"]["gasto"], r["pessoal"], r["auxilioMoradia"], r["imovelFuncional"])
json.dump(res, open(os.path.join(OUT, "paginas.json"), "w"), ensure_ascii=False)
