"""Busca no site da Câmara as passagens aéreas (PASSAGEM AÉREA - SIGEPA, código 998) de 2026,
que não aparecem no arquivo aberto Ano-2026.csv. Salva o total e o mês a mês por deputado."""
import html, json, os, re, sys, time, urllib.request
import pandas as pd
from paths import SNAPSHOTS, RAW
H = str(SNAPSHOTS); OUT = os.path.join(RAW, "paginas")
MESES = "Janeiro Fevereiro Março Abril Maio Junho Julho Agosto Setembro Outubro Novembro Dezembro".split()
ids = pd.read_csv(os.path.join(RAW, "Ano-2026.csv"), sep=";", encoding="utf-8-sig", dtype=str, usecols=["ideCadastro", "nuDeputadoId"]).dropna().drop_duplicates()
cota_id = dict(zip(ids.ideCadastro, ids.nuDeputadoId))
res = {}
for did in sys.argv[1:]:
    url = f"https://www.camara.leg.br/cota-parlamentar/index.jsp?deputadosSelecionados={cota_id[did]}&dataInicio=01/2026&dataFim=12/2026&despesa=998&pesquisar=sim&cnpjFornecedor="
    t = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode("utf-8", "ignore")
    s = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", t, flags=re.S))))
    num = lambda x: float(x.replace(".", "").replace(",", "."))
    meses = {MESES.index(m) + 1: num(v) for m, v in re.findall(r"(" + "|".join(MESES) + r")/2026 R\$ ([\d.,]+)", s)}
    tot = re.search(r"Total R\$ ([\d.,]+)", s)
    res[did] = {"total": num(tot.group(1)) if tot else 0.0, "meses": meses}
    print(did, res[did]["total"]); time.sleep(0.8)
json.dump(res, open(os.path.join(OUT, "passagens.json"), "w"))
