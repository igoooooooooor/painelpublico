"""Coleta complementar: votos nominais completos das votações do Placar e presença em Plenário 2026 de todos os deputados."""
import json, os, re, sys, time, html, urllib.request
from concurrent.futures import ThreadPoolExecutor
from paths import SNAPSHOTS, CACHE
H = str(SNAPSHOTS); C = str(CACHE); os.makedirs(C, exist_ok=True)
def get(url, fn, js=False):
    p = os.path.join(C, fn)
    if not os.path.exists(p):
        for i in range(3):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json' if js else 'text/html'})
                data = urllib.request.urlopen(req, timeout=40).read(); open(p, 'wb').write(data); break
            except Exception as e:
                if i == 2: print('FAIL', url, e, file=sys.stderr); return None
                time.sleep(2)
    t = open(p, encoding='utf-8', errors='ignore').read()
    return json.loads(t) if js else t
what = sys.argv[1]
if what == 'votos':
    d = json.load(open(os.path.join(H, 'editorial.json')))
    out = {}
    for v in d['votacoes']:
        r = get(f"https://dadosabertos.camara.leg.br/api/v2/votacoes/{v['id']}/votos", f"votos_{v['id']}.json", True)
        out[v['id']] = [[x['deputado_']['id'], x['deputado_']['nome'], x['deputado_']['siglaPartido'], x['deputado_']['siglaUf'], x['tipoVoto']] for x in r['dados']]
        print(v['id'], len(out[v['id']]))
    json.dump(out, open(os.path.join(H, 'votos.json'), 'w'), ensure_ascii=False)
elif what == 'deps':
    r = get('https://dadosabertos.camara.leg.br/api/v2/deputados?itens=600&ordem=ASC&ordenarPor=nome', 'deps.json', True)
    print(len(r['dados']))
elif what == 'pres':
    deps = json.load(open(os.path.join(C, 'deps.json')))['dados']
    lim = time.time() + float(sys.argv[2])
    def one(dep):
        if time.time() > lim: return None
        return get(f"https://www.camara.leg.br/deputados/{dep['id']}/presenca-plenario/2026", f"pres_{dep['id']}.html")
    with ThreadPoolExecutor(6) as ex: list(ex.map(one, deps))
    print('cached', len([f for f in os.listdir(C) if f.startswith('pres_')]), 'of', len(deps))
elif what == 'build':
    deps = json.load(open(os.path.join(C, 'deps.json')))['dados']; out = []
    for dep in deps:
        p = os.path.join(C, f"pres_{dep['id']}.html")
        if not os.path.exists(p): continue
        t = open(p, encoding='utf-8', errors='ignore').read()
        dias = re.findall(r'info-data__data-formatada">\s*(\d\d/\d\d/\d{4}).*?</td>\s*<td[^>]*>.*?</td>\s*<td class="info-presenca-dia">\s*(.*?)\s*</td>', t, flags=re.S)
        st = [html.unescape(re.sub(r'<[^>]+>', '', s)).strip() for _, s in dias]
        if not st: continue
        ok = sum(s == 'Presença' for s in st); falta = sum(s == 'Ausência' for s in st)
        mot = {}
        for s in st:
            if s not in ('Presença', 'Ausência'): mot[s] = mot.get(s, 0) + 1
        out.append({'id': dep['id'], 'nome': dep['nome'], 'partido': dep['siglaPartido'], 'uf': dep['siglaUf'], 'dias': len(st), 'presente': ok, 'falta': falta, 'justificadas': len(st) - ok - falta, 'motivos': sorted(mot.items(), key=lambda kv: -kv[1])[:3]})
    json.dump(out, open(os.path.join(H, 'presenca.json'), 'w'), ensure_ascii=False)
    print(len(out), sorted(out, key=lambda x: x['presente'] / x['dias'])[:3])
