const DATA = /*DATA*/null;
const VOT = Object.fromEntries(DATA.votacoes.map(v => [v.id, v]));
const $app = document.getElementById('app');
const MES = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const brl = (v, d = 0) => 'R$ ' + v.toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const mi = v => (v / 1e6).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const mil = v => (v / 1e3).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
const pct = (a, b) => b > 0 ? Math.round(a / b * 100) : 0;
const dmy = s => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}/.test(s) ? `${+s.slice(8, 10)}/${MES[+s.slice(5, 7)]}` : 'data não informada';
const first = n => n.split(' ')[0];
const CATS = ['--cat1', '--cat2', '--cat3', '--cat4', '--cat5', '--cat6'];
const CATS_H = ['--cat1', '--hero-fg', '--cat3', '--cat4', '--cat5', '--cat6']; // em fundo escuro, o tom escuro some
const store = { get(k, f) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : f; } catch (e) { return f; } },
                set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
let state = { view: 'inicio', dep: null, vote: null, quiz: null };

function cardVoto(v) {
  return `<article class="card">
    <span class="k">${esc(v.proposicao)} · ${dmy(v.data)}</span>
    <h3 class="h" style="font-size:20px">${esc(v.titulo)}</h3>
    <div class="score"><span class="big">${v.sim}×${v.nao}</span><span class="tag ${v.aprovada ? '' : 'soft'}">${v.aprovada ? 'APROVADO' : 'REJEITADO'}</span></div>
    <div class="vbar" role="img" aria-label="${v.sim} sim, ${v.nao} não"><i style="width:${v.sim / Math.max(1, v.sim + v.nao) * 100}%"></i><i style="width:${v.nao / Math.max(1, v.sim + v.nao) * 100}%"></i></div>
    <p style="margin:0;font-size:14px;color:var(--ink-2)">${esc(v.curto)}</p>
    ${v.secreta ? `<div class="secret"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>Voto secreto: só o total é público.</div>` :
      `<div style="display:flex;flex-direction:column;gap:6px">${v.partidos.slice(0, 4).map(partyRow).join('')}</div>`}
    <button type="button" class="more" data-vote="${v.id}">Entender essa votação</button>
  </article>`;
}
function partyRow(p) { const t = p.sim + p.nao + p.outros; return `<div class="party"><b>${esc(p.p)}</b><div class="bar"><i style="width:${p.sim / t * 100}%"></i><i style="width:${p.nao / t * 100}%"></i></div><span>${p.sim}–${p.nao}</span></div>`; }

/* ---------- VOTAÇÃO (detalhe) ---------- */
function vVotacao() {
  const v = VOT[state.vote];
  if (!v) return '<p class="note">Votação não disponível neste recorte.</p>';
  return `<button type="button" class="back" data-back>‹ Voltar</button>
  <span class="k">${esc(v.proposicao)} · votado em ${dmy(v.data)}</span>
  <h1 class="h" style="font-size:30px">${esc(v.titulo)}</h1>
  <section class="card hero">
    <div class="score"><span class="huge" style="font-size:clamp(44px,14vw,60px)">${v.sim}×${v.nao}</span></div>
    <div class="stack grow-x" role="img" aria-label="${v.sim} sim e ${v.nao} não"><i style="width:${v.sim / Math.max(1, v.sim + v.nao) * 100}%;background:var(--accent-2)"></i><i style="width:${v.nao / Math.max(1, v.sim + v.nao) * 100}%;background:var(--hero-muted)"></i></div>
    <div class="legend" style="color:var(--hero-muted)"><span><i style="background:var(--accent-2)"></i>Sim ${v.sim}</span><span><i style="background:var(--hero-muted)"></i>Não ${v.nao}</span></div>
    <span class="muted">${v.sim} deputados(as) votaram sim e ${v.nao} votaram não. ${v.aprovada ? 'Aprovado.' : 'Rejeitado.'} Hoje: ${esc(v.situacao.toLowerCase())}.</span>
  </section>
  <section class="card">
    <span class="k">O que muda na prática</span>
    <p style="margin:0;font-size:16px;line-height:1.5">${esc(v.naPratica)}</p>
    <div style="display:flex;gap:14px;flex-wrap:wrap"><a href="${esc(v.texto)}" target="_blank" rel="noopener">Texto aprovado</a><a href="${esc(v.ficha)}" target="_blank" rel="noopener">Andamento na Câmara</a></div>
  </section>
  ${extQuemVotou(v)}
  ${v.secreta ? `<section class="card">
    <span class="k">Por que o voto foi secreto?</span>
    <p style="margin:0">Quando a Câmara escolhe uma autoridade, como um ministro do Tribunal de Contas da União, o regimento manda o voto ser secreto. O painel mostra só o total, então não existe registro de como cada deputado(a) votou.</p>
  </section>` : `<section class="card wide">
    <span class="k">Como cada partido votou</span>
    ${v.partidos.length ? `<div class="party-grid">${v.partidos.map(partyRow).join('')}</div>
    <div class="legend"><span><i style="background:var(--accent)"></i>Sim</span><span><i style="background:var(--no)"></i>Não</span></div>
    <button type="button" class="more" data-go="partidos">Comparar dois partidos →</button>` : '<p class="muted">Sem dados de votos por partido neste recorte.</p>'}
  </section>`}
  <span class="src">Fonte: Câmara dos Deputados. O resumo foi escrito a partir do texto aprovado.</span>`;
}

/* ---------- PLACAR ---------- */
function vVotacoes() {
  const V = DATA.votacoes, apr = V.filter(v => v.aprovada).length;
  if (!V.length) return pageHead('Câmara · Plenário', 'Placar', 'Nenhuma votação disponível neste recorte.');
  const ab = V.filter(v => !v.secreta).map(v => ({ v, gap: Math.abs(v.sim - v.nao) / Math.max(1, v.sim + v.nao) })).sort((a, b) => a.gap - b.gap)[0];
  const tot = V.reduce((s, v) => s + v.sim + v.nao, 0), sim = V.reduce((s, v) => s + v.sim, 0);
  return `${pageHead('Câmara · Plenário', 'Placar', 'Como os(as) deputados(as) votaram nas propostas selecionadas. Toque numa votação para entender o que muda.')}
  <section class="card hero">
    <span class="k">${V.length} votações selecionadas</span>
    <div class="huge">${apr}<small style="margin-left:6px">de ${V.length}</small></div>
    <span class="muted">foram aprovadas. A mais recente deste recorte foi em ${dmy(DATA.ultimaVotacao)}.</span>
    <div class="hero-split">
      <div><b class="mono">${pct(sim, tot)}%</b><span>dos votos foram “sim”</span></div>
      ${ab ? `<div><b class="mono">${ab.v.sim}×${ab.v.nao}</b><span>a mais apertada: ${esc(ab.v.titulo)}</span></div>` : ''}
    </div>
    <div class="stack grow-x" role="img" aria-label="Todos os votos: ${pct(sim, tot)}% sim"><i style="width:${pct(sim, tot)}%;background:var(--accent-2)"></i><i style="width:${pct(tot - sim, tot)}%;background:var(--hero-muted)"></i></div>
    <div class="legend" style="color:var(--hero-muted)"><span><i style="background:var(--accent-2)"></i>Sim · ${sim.toLocaleString('pt-BR')} votos</span><span><i style="background:var(--hero-muted)"></i>Não · ${(tot - sim).toLocaleString('pt-BR')}</span></div>
  </section>
  <div class="cid-actions"><button type="button" class="fchip" data-go="partidos">Comparar partidos →</button></div>
  ${V.map(cardVoto).join('')}
  <span class="src">Fonte: Câmara dos Deputados (dados abertos de votações do Plenário).</span>`;
}

/* Compatibilidade para entradas antigas que ainda chamem a rota ficha. */
function vFicha() {
  if (state.dep) state.pol = String(state.dep).includes(':') ? String(state.dep) : 'camara:' + state.dep;
  return vPolitico();
}

function render() {
  const v = state.view;
  const html = { inicio: vHoje, base: vBasePublica, autoridades: vAutoridades, despesas: vDespesas, fornecedores: vFornecedores,
    fornecedor: vFornecedor, autoridade: vAutoridade, radar: vRadarPublico, cobertura: vCobertura, investigacoes: vInvestigacoes,
    hoje: vHoje, votacoes: vVotacoes, deputados: vPoliticos, ficha: vFicha, votacao: vVotacao, gastos: vLupa, gasto: vFicha,
    lupa: vLupa, politicos: vPoliticos, politico: vPolitico, presenca: vPresenca, comparar: vComparar, partidos: vPartidos }[v]();
  $app.innerHTML = `<div class="view">${html}</div>`;
  document.body.dataset.view = v;
  const tab = ['autoridade', 'autoridades', 'ficha', 'deputados', 'politicos', 'politico', 'presenca', 'comparar', 'partidos'].includes(v) ? 'politicos' :
    v === 'votacao' ? 'votacoes' : ['gasto', 'gastos', 'radar', 'despesas', 'fornecedor', 'fornecedores', 'lupa'].includes(v) ? 'lupa' :
    ['hoje', 'base', 'cobertura', 'investigacoes'].includes(v) ? 'inicio' : v;
  document.querySelectorAll('nav.tabs button').forEach(b => b.dataset.go === tab ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current'));
  if (!['inicio', 'hoje', 'lupa', 'politicos', 'politico', 'ficha', 'votacao', 'votacoes', 'deputados', 'gastos', 'gasto', 'presenca', 'comparar', 'partidos'].includes(v)) loadPublicView(v);
  state.publicContext = Object.fromEntries(['publicAuthority', 'publicSupplier', 'authority', 'expense', 'supplier', 'signal'].map(k => [k, JSON.parse(JSON.stringify(publicState[k]))]));
}
const hist = [];
function go(view, keep) {
  if (view === 'deputados') view = 'politicos';
  if (view === 'gastos') view = 'lupa';
  if (view === 'ficha' || view === 'gasto') {
    if (state.dep) state.pol = String(state.dep).includes(':') ? state.dep : 'camara:' + state.dep;
    view = 'politico';
  }
  if (!keep) hist.push({ view: state.view, dep: state.dep, vote: state.vote, pol: state.pol, y: window.scrollY, publicContext: state.publicContext });
  state.view = view; render(); window.scrollTo(0, 0);
}
function back() { const h = hist.pop() || { view: 'inicio', y: 0 }; Object.assign(state, { view: h.view, dep: h.dep, vote: h.vote, pol: h.pol }); if (h.publicContext) Object.assign(publicState, h.publicContext); render(); window.scrollTo(0, h.y || 0); }
const rerender = () => { const y = window.scrollY; render(); window.scrollTo(0, y); };

document.addEventListener('click', e => {
  const t = e.target.closest('[data-copy],[data-go],[data-dep],[data-quiz],[data-vote],[data-back],[data-summary-retry]');
  if (!t) return;
  if (t.dataset.copy) {
    const done = () => { t.textContent = 'Copiado'; setTimeout(() => { t.textContent = 'Copiar'; }, 1500); };
    const pick = () => { const r = document.createRange(); r.selectNodeContents(t.previousElementSibling); const s = getSelection(); s.removeAllRanges(); s.addRange(r); t.textContent = 'Selecionado'; };
    try { navigator.clipboard.writeText(t.dataset.copy).then(done, pick); } catch (err) { pick(); }
    return;
  }
  if (t.hasAttribute('data-summary-retry')) { homeReset(); return rerender(); }
  if (t.hasAttribute('data-back')) return back();
  if (t.dataset.quiz) { state.quiz = t.dataset.quiz; return rerender(); }
  if (t.dataset.vote) { state.vote = t.dataset.vote; return go('votacao'); }
  if (t.dataset.dep) return cidOpenPol(t.dataset.dep);
  if (t.dataset.go) { hist.length = 0; go(t.dataset.go, true); }
});
initPublicData();
render();

/* Downloads da busca avançada: dados do filtro atual. */
function salvarArquivo(blob, nome) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = nome;
  document.body.appendChild(link);
  try { link.click(); } finally {
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
}
