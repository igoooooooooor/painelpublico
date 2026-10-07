/* Comparar partidos: bancada e cota (API /api/c/partidos), presença e votos (snapshots editoriais).
   Ausência não vira zero: partido sem nota importada ou sem deputado(a) na presença aparece como "Sem dados". */
const par = { sel: [], data: null, erro: null, loading: false };
const PAR_PATH = '/api/c/partidos';

function parLoad() {
  // Com erro, espera o "Tentar de novo": recarregar sozinho a cada render prendia a tela no loading.
  if (par.data || par.loading || par.erro) return;
  par.loading = true; par.erro = null;
  cidGet(PAR_PATH).then(d => {
    par.data = d; par.loading = false;
    if (par.sel.length < 2) par.sel = d.itens.slice(0, 2).map(p => p.sigla);
    if (state.view === 'partidos') rerender();
  }).catch(e => { par.loading = false; par.erro = cidErroMsg(e); if (state.view === 'partidos') rerender(); });
}

/* Votos do partido em cada votação aberta: sim, não, outros e para onde foi a maioria. */
function parVotos(sigla) {
  return DATA.votacoes.filter(v => !v.secreta).map(v => {
    const linhas = (typeof extVotos === 'function' ? extVotos(v) : null) || [];
    const meus = linhas.filter(x => x[2] === sigla && x[4] !== 'Não votou');
    const sim = meus.filter(x => x[4] === 'Sim').length, nao = meus.filter(x => x[4] === 'Não').length;
    const maioria = !sim && !nao ? null : sim > nao ? 'Sim' : nao > sim ? 'Não' : 'Dividido';
    return { v, sim, nao, outros: meus.length - sim - nao, maioria };
  });
}
function parUnidade(votos) {
  const base = votos.reduce((s, r) => s + r.sim + r.nao, 0);
  return base ? votos.reduce((s, r) => s + Math.max(r.sim, r.nao), 0) / base : null;
}
function parPresenca(sigla) {
  const membros = (DATA.presencaTodos || []).filter(p => p.partido === sigla && p.dias);
  return membros.length ? { media: membros.reduce((s, p) => s + p.presente / p.dias, 0) / membros.length, n: membros.length } : null;
}

const parSemDados = '<span class="muted">Sem dados</span>';
function parLinha(rotulo, va, vb, fmt, melhor) {
  // melhor: 'menor', 'maior' ou null (só informa). Sem dado de um lado, ninguém ganha destaque.
  const ok = v => v !== null && v !== undefined && Number.isFinite(v);
  const ganha = !melhor || !ok(va) || !ok(vb) || va === vb ? '' : (va < vb) === (melhor === 'menor') ? 'a' : 'b';
  return `<div class="cmp-row"><span class="cmp-l">${rotulo}</span><div class="cmp-v ${ganha === 'a' ? 'best' : ''}">${ok(va) ? fmt(va) : parSemDados}</div><div class="cmp-v ${ganha === 'b' ? 'best' : ''}">${ok(vb) ? fmt(vb) : parSemDados}</div></div>`;
}
const parPct = v => `<b>${Math.round(v * 100)}%</b>`;
function parVotoChip(r) {
  if (!r.maioria) return parSemDados;
  const cls = r.maioria === 'Sim' ? 'sim' : r.maioria === 'Não' ? 'nao' : '';
  return `<span class="vchip ${cls}">${esc(r.maioria.toLowerCase())}</span><small class="par-placar mono">${r.sim}–${r.nao}</small>`;
}

function parTabela(a, b) {
  const va = parVotos(a.sigla), vb = parVotos(b.sigla);
  const pa = parPresenca(a.sigla), pb = parPresenca(b.sigla);
  const porDez = p => { const tot = (p.deputado?.alertas || 0) + (p.senador?.alertas || 0); const n = (p.deputado?.comDados || 0) + (p.senador?.comDados || 0); return n ? tot / n * 10 : null; };
  const comparaveis = va.map((r, i) => [r, vb[i]]).filter(([x, y]) => x.maioria && y.maioria);
  const iguais = comparaveis.filter(([x, y]) => x.maioria === y.maioria).length;
  const bancada = p => `<b>${p.membros}</b><small>${[p.deputado ? `${p.deputado.membros} dep.` : '', p.senador ? `${p.senador.membros} sen.` : ''].filter(Boolean).join(' · ')}</small>`;
  return `<section class="card cmp wide par-cmp">
    <div class="cmp-head"><span></span>${[a, b].map(p => `<div class="par-who"><span class="par-sigla" style="--fit:${Math.min(30, Math.round(170 / Math.max(5, p.sigla.length)))}px">${esc(p.sigla)}</span><small>${p.membros} parlamentares em exercício</small></div>`).join('')}</div>
    <div class="cmp-row"><span class="cmp-l">Bancada no Congresso</span><div class="cmp-v par-stack">${bancada(a)}</div><div class="cmp-v par-stack">${bancada(b)}</div></div>
    ${parLinha('Gasto médio de cota por deputado(a) em 2026', a.deputado?.media, b.deputado?.media, v => `<b class="mono">${cidMil(v)}</b>`, 'menor')}
    ${parLinha('Gasto médio de cota por senador(a) em 2026', a.senador?.media, b.senador?.media, v => `<b class="mono">${cidMil(v)}</b>`, 'menor')}
    ${parLinha('Alertas a cada 10 parlamentares', porDez(a), porDez(b), v => `<b>${v.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}</b>`, 'menor')}
    ${parLinha('Presença média dos(as) deputados(as) no Plenário', pa?.media, pb?.media, parPct, 'maior')}
    ${parLinha('Unidade nas votações (votaram com a maioria do partido)', parUnidade(va), parUnidade(vb), parPct, null)}
  </section>
  ${comparaveis.length ? `<section class="card wide"><span class="k">Como votaram</span>
    <h2 class="h" style="font-size:21px">${esc(a.sigla)} e ${esc(b.sigla)} ficaram do mesmo lado em ${iguais} de ${comparaveis.length} ${comparaveis.length === 1 ? 'votação' : 'votações'}.</h2>
    ${va.map((r, i) => `<button type="button" class="cmp-vote par-vote" data-vote="${esc(r.v.id)}"><span>${esc(r.v.titulo)}</span><span class="par-v">${parVotoChip(r)}</span><span class="par-v">${parVotoChip(vb[i])}</span><em>${r.maioria && vb[i].maioria ? (r.maioria === vb[i].maioria ? 'mesmo lado' : 'lados opostos') : 'sem votos registrados de um dos partidos'}</em></button>`).join('')}
    <span class="muted">Placar dentro de cada partido: votos sim–não dos(as) deputados(as) da legenda. Votações secretas ficam de fora.</span>
  </section>` : ''}
  <section class="card wide"><span class="k">Quem mais gastou a cota em cada partido</span>
    <div class="par-tops">${[a, b].map(p => `<div><b class="par-sigla sm">${esc(p.sigla)}</b>${p.top.length ? p.top.map(x => `<button type="button" class="cid-row" data-pol="${esc(x.id)}">${cidAvatar(x, 40)}<span class="cid-rowtxt"><b>${esc(cidNome(x.name))}</b><small>${esc(CARGO[x.role] || '')}</small></span><span class="cid-rowval"><b class="mono">${x.gasto === null || x.gasto === undefined ? 'Sem dados' : cidMil(x.gasto)}</b></span></button>`).join('') : '<p class="muted">Sem notas importadas.</p>'}</div>`).join('')}</div>
  </section>`;
}

function vPartidos() {
  parLoad();
  const head = `<button type="button" class="back" data-back>‹ Voltar</button>
  ${pageHead('Câmara e Senado', 'Comparar partidos', 'Bancada, gastos com a cota, presença e votos de dois partidos lado a lado.')}`;
  if (par.erro) return `${head}<section class="card wide"><p>Não deu para carregar os partidos agora.</p><p class="muted">${esc(par.erro)}</p><button type="button" class="more" data-par-retry>Tentar de novo</button></section>`;
  if (!par.data) return `${head}<section class="card wide par-pick sk-card">${skL('140px', 10)}${skel('chips', 12)}</section>${skel('cmp')}`;
  const porSigla = Object.fromEntries(par.data.itens.map(p => [p.sigla, p]));
  const [a, b] = par.sel.map(s => porSigla[s]).filter(Boolean);
  return `${head}
  <section class="card wide par-pick"><span class="k">Escolha dois partidos</span>
    <div class="chips" role="group" aria-label="Partidos">${par.data.itens.map(p => `<button type="button" class="fchip" data-par="${esc(p.sigla)}" aria-pressed="${par.sel.includes(p.sigla)}">${esc(p.sigla)} <b>${p.membros}</b></button>`).join('')}</div>
    <span class="muted">O número ao lado é a bancada (deputados(as) + senadores(as)). Toque para trocar; o mais antigo da comparação sai.</span>
  </section>
  ${a && b ? parTabela(a, b) : '<p class="note">Escolha dois partidos para comparar.</p>'}
  <span class="src">Destaque em roxo: menor gasto médio, menos alertas ou mais presença. Partidos maiores tendem a ter mais variação interna; compare a média, não o total. Gastos pelas notas da cota (sem passagens aéreas da Câmara); presença e votos só da Câmara.</span>`;
}

document.addEventListener('click', e => {
  if (e.target.closest('[data-par-retry]')) { par.erro = null; cid.cache.delete(PAR_PATH); rerender(); return; }
  const t = e.target.closest('[data-par]');
  if (!t) return;
  const s = t.dataset.par;
  par.sel = par.sel.includes(s) ? par.sel.filter(x => x !== s) : [...par.sel, s].slice(-2);
  rerender();
});
