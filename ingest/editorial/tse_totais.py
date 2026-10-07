"""Soma os votos do 1º turno de 2026 por candidato (deputado federal, senador, governador) nas UFs pedidas."""
from paths import RAW
import sys, subprocess, pandas as pd, os
os.chdir(os.path.join(RAW, "tse"))
out = []
for uf in sys.argv[1:]:
    fn = f"votacao_candidato_munzona_2026_{uf}.csv"
    if not os.path.exists(fn): subprocess.run(["unzip", "-o", "-q", "votos.zip", fn], check=True)
    parts = []
    for ch in pd.read_csv(fn, sep=";", encoding="latin1", dtype=str, chunksize=500000):
        ch = ch[ch.CD_CARGO.isin(["3", "5", "6"])]
        parts.append(ch[["SG_UF", "NR_TURNO", "CD_CARGO", "SQ_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "DS_SIT_TOT_TURNO", "QT_VOTOS_NOMINAIS"]])
    d = pd.concat(parts); d["QT"] = d.QT_VOTOS_NOMINAIS.astype(int)
    g = d.groupby(["SG_UF", "NR_TURNO", "CD_CARGO", "SQ_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "DS_SIT_TOT_TURNO"]).QT.sum().reset_index()
    out.append(g); print(uf, len(g)); os.remove(fn)
pd.concat(out).to_csv("../tse_totais.csv", index=False)
