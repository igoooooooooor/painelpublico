/* Comparar partidos: registros e cota (API /api/c/partidos), presença e votos (helpers compartilhados).
   Ausência não vira zero: presença depende dos registros válidos de cada casa e voto só usa linha da fonte. */
const par = { sel: [], data: null, erro: null, loading: false, camVoteLim: 20, senateVoteLim: 20 };
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

/* Votos do partido em cada votação aberta. Só Sim/Não formam a maioria e a unidade do voto. */
function parVotos(sigla, chamber = 'camara') {
  if (chamber === 'senado' && typeof profileSenateEnsure === 'function') profileSenateEnsure();
  const votes = typeof profileVoteList === 'function' ? profileVoteList(chamber) : chamber === 'camara' ? DATA.votacoes || [] : [];
  return votes.filter(v => !v.secreta).map(v => {
    const linhas = (typeof extVotos === 'function' ? extVotos(v) : null) || [];
    // extVotos contém somente linhas registradas na fonte; não completar ausentes pela lista atual.
    const meus = linhas.filter(x => x[2] === sigla);
    const sim = meus.filter(x => x[4] === 'Sim').length, nao = meus.filter(x => x[4] === 'Não').length;
    const maioria = !sim && !nao ? null : sim > nao ? 'Sim' : nao > sim ? 'Não' : 'Dividido';
    return { v, sim, nao, outros: meus.length - sim - nao, maioria };
  });
}
function parUnidade(votos) {
  const base = votos.reduce((s, r) => s + r.sim + r.nao, 0);
  return base ? votos.reduce((s, r) => s + Math.max(r.sim, r.nao), 0) / base : null;
}
function parPresenca(sigla, chamber = 'camara') {
  if (chamber === 'senado' && typeof profileSenateEnsure === 'function') profileSenateEnsure();
  if (chamber === 'senado') {
    const rows = typeof profileRegisteredPresenceRows === 'function' ? profileRegisteredPresenceRows() : [];
    const members = rows.filter(p => p && p.partido === sigla && Number.isFinite(p.presente) && p.presente > 0);
    return members.length ? { media: members.reduce((sum, p) => sum + p.presente, 0) / members.length, n: members.length } : null;
  }
  const rows = typeof profilePresenceRows === 'function' ? profilePresenceRows(chamber) : (chamber === 'camara' ? DATA.presencaTodos || [] : []);
  const membros = rows.filter(p => p && p.partido === sigla && Number.isFinite(p.dias) && p.dias > 0
    && [p.presente, p.falta, p.justificadas].every(n => Number.isFinite(n) && n >= 0)
    && p.presente + p.falta + p.justificadas === p.dias);
  return membros.length ? { media: membros.reduce((s, p) => s + p.presente / p.dias, 0) / membros.length, n: membros.length } : null;
}

const parSemDados = '<span class="muted">Sem dados</span>';
function parPresencaRegistradaLinha(a, b, pending, source) {
  const show = p => pending ? '<i class="sk" style="display:inline-block;width:48px;height:12px"></i>' : p
    ? `<b>${p.media.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}</b><small> sessões em média · ${p.n} ${p.n === 1 ? 'senador(a)' : 'senadores(as)'} com registro</small>` : parSemDados;
  const sourceHtml = !source ? '' : typeof profileSource === 'function' ? profileSource(source, 'Fonte e período') : source.period ? `<span class="src">${esc(source.period)}</span>` : '';
  const sessionCount = Number.isFinite(source?.sessionCount) ? source.sessionCount : null;
  const detail = 'Média somente de parlamentares com presença registrada, pela legenda do cadastro atual. Faltas e justificativas não apuradas; ausência de linha não equivale a zero.';
  return `<div class="cmp-row"><span class="cmp-l">Presenças registradas por senador(a) · Senado</span><div class="cmp-v">${show(a)}</div><div class="cmp-v">${show(b)}</div></div>
    <div class="cmp-row"><div class="cmp-v muted cmp-source" style="grid-column:1 / -1">${sessionCount === null ? '' : `${sessionCount} listas de sessões consultadas. `}${esc(detail)}${sourceHtml}</div></div>`;
}
function parLinha(rotulo, va, vb, fmt, melhor, pending = false) {
  // melhor: 'menor', 'maior' ou null (só informa). Sem dado de um lado, ninguém ganha destaque.
  const ok = v => v !== null && v !== undefined && Number.isFinite(v);
  const ganha = !melhor || !ok(va) || !ok(vb) || va === vb ? '' : (va < vb) === (melhor === 'menor') ? 'a' : 'b';
  const show = value => pending ? '<i class="sk" style="display:inline-block;width:48px;height:12px"></i>' : ok(value) ? fmt(value) : parSemDados;
  return `<div class="cmp-row"><span class="cmp-l">${rotulo}</span><div class="cmp-v ${!pending && ganha === 'a' ? 'best' : ''}">${show(va)}</div><div class="cmp-v ${!pending && ganha === 'b' ? 'best' : ''}">${show(vb)}</div></div>`;
}
const parPct = v => `<b>${Math.round(v * 100)}%</b>`;
function parVotoChip(r) {
  if (!r.maioria) return parSemDados;
  const cls = r.maioria === 'Sim' ? 'sim' : r.maioria === 'Não' ? 'nao' : '';
  return `<span class="vchip ${cls}">${esc(r.maioria.toLowerCase())}</span><small class="par-placar mono">${r.sim}–${r.nao}</small>`;
}

function parTabela(a, b) {
  if (typeof profileSenateEnsure === 'function') profileSenateEnsure();
  const va = parVotos(a.sigla), vb = parVotos(b.sigla), sa = parVotos(a.sigla, 'senado'), sb = parVotos(b.sigla, 'senado');
  const pa = parPresenca(a.sigla), pb = parPresenca(b.sigla);
  const psa = parPresenca(a.sigla, 'senado'), psb = parPresenca(b.sigla, 'senado');
  const senateLoading = typeof profileSenateLoading === 'function' && profileSenateLoading();
  const senatePresenceSource = typeof profileSenateSource === 'function' ? profileSenateSource('presenca') : null;
  const senateVoteSource = typeof profileSenateSource === 'function' ? profileSenateSource('votacoes') : null;
  const porDez = p => { const tot = (p.deputado?.alertas || 0) + (p.senador?.alertas || 0); const n = (p.deputado?.comDados || 0) + (p.senador?.comDados || 0); return n ? tot / n * 10 : null; };
  const comparaveis = va.map((r, i) => [r, vb[i]]).filter(([x, y]) => x.maioria && y.maioria);
  const iguais = comparaveis.filter(([x, y]) => x.maioria === y.maioria).length;
  const senateComparaveis = sa.map((r, i) => [r, sb[i]]).filter(([x, y]) => x?.maioria && y?.maioria);
  const senateIguais = senateComparaveis.filter(([x, y]) => x.maioria === y.maioria).length;
  const sourceMeta = section => {
    if (!section) return '';
    if (typeof profileSource === 'function') return profileSource(section, 'Fonte e período');
    const url = /^https?:\/\//i.test(section.sourceUrl || '') ? section.sourceUrl : '';
    return `<span class="src">${section.period ? `${esc(section.period)}. ` : ''}${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">Fonte e período ↗</a>` : ''}</span>`;
  };
  const senateVoteRows = sa.slice(0, par.senateVoteLim).map((r, i) => {
    const pair = sb[i];
    if (!pair) return '';
    const content = `<span>${esc(r.v.titulo || r.v.proposicao || 'Votação nominal')}</span><span class="par-v">${parVotoChip(r)}</span><span class="par-v">${parVotoChip(pair)}</span><em>${r.maioria && pair.maioria ? (r.maioria === pair.maioria ? 'mesmo lado' : 'lados opostos') : 'sem votos registrados de um dos partidos'}</em>`;
    return typeof profileVoteButton === 'function' ? profileVoteButton(r.v, content, 'cmp-vote par-vote') : `<button type="button" class="cmp-vote par-vote" data-vote="${esc(r.v.id)}">${content}</button>`;
  }).join('');
  const chamberVoteRows = va.slice(0, par.camVoteLim).map((r, i) => `<button type="button" class="cmp-vote par-vote" data-vote="${esc(r.v.id)}"><span>${esc(r.v.titulo)}</span><span class="par-v">${parVotoChip(r)}</span><span class="par-v">${parVotoChip(vb[i])}</span><em>${r.maioria && vb[i]?.maioria ? (r.maioria === vb[i].maioria ? 'mesmo lado' : 'lados opostos') : 'sem votos registrados de um dos partidos'}</em></button>`).join('');
  const totalRegistros = p => `<b>${p.membros}</b><small>${[p.deputado ? `${p.deputado.membros} dep.` : '', p.senador ? `${p.senador.membros} sen.` : ''].filter(Boolean).join(' · ')}</small>`;
  return `<section class="card cmp wide par-cmp">
    <div class="cmp-head"><span></span>${[a, b].map(p => `<div class="par-who"><span class="par-sigla" style="--fit:${Math.min(30, Math.round(170 / Math.max(5, p.sigla.length)))}px">${esc(p.sigla)}</span><small>${p.membros} registros da lista</small></div>`).join('')}</div>
    <div class="cmp-row"><span class="cmp-l">Registros na lista disponível</span><div class="cmp-v par-stack">${totalRegistros(a)}</div><div class="cmp-v par-stack">${totalRegistros(b)}</div></div>
    ${parLinha('Gasto médio de cota por deputado(a) em 2026', a.deputado?.media, b.deputado?.media, v => `<b class="mono">${cidMil(v)}</b>`, 'menor')}
    ${parLinha('Gasto médio de cota por senador(a) em 2026', a.senador?.media, b.senador?.media, v => `<b class="mono">${cidMil(v)}</b>`, 'menor')}
    ${parLinha('Alertas a cada 10 parlamentares', porDez(a), porDez(b), v => `<b>${v.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}</b>`, 'menor')}
    ${parLinha('Presença média dos(as) deputados(as) no Plenário · Câmara', pa?.media, pb?.media, parPct, 'maior')}
    ${parPresencaRegistradaLinha(psa, psb, senateLoading, senatePresenceSource)}
    ${parLinha('Unidade nas votações · Câmara', parUnidade(va), parUnidade(vb), parPct, null)}
    ${parLinha('Unidade nas votações nominais · Senado', parUnidade(sa), parUnidade(sb), parPct, null, senateLoading)}
  </section>
  ${comparaveis.length ? `<section class="card wide"><span class="k">Como votaram · Câmara</span>
    <h2 class="h" style="font-size:21px">${esc(a.sigla)} e ${esc(b.sigla)} ficaram do mesmo lado em ${iguais} de ${comparaveis.length} ${comparaveis.length === 1 ? 'votação' : 'votações'}.</h2>
    ${chamberVoteRows}${va.length > par.camVoteLim ? `<button type="button" class="opt cid-more" data-par-cam-votes-more>Mostrar mais (${va.length - par.camVoteLim})</button>` : ''}
    <span class="muted">Placar dentro de cada partido: votos sim–não dos(as) deputados(as) da legenda. Votações secretas ficam de fora.</span>
  </section>` : ''}
  <section class="card wide"><span class="k">Como votaram · Senado</span>
    ${senateLoading ? (typeof skel === 'function' ? skel('linhas', 3) : '<i class="sk" style="display:block;width:100%;height:14px"></i>') : senateVoteSource ? `<h2 class="h" style="font-size:21px">${senateComparaveis.length ? `${esc(a.sigla)} e ${esc(b.sigla)} ficaram do mesmo lado em ${senateIguais} de ${senateComparaveis.length} votações nominais comparáveis.` : 'Sem votações com escolhas nominais registradas para ambos os partidos.'}</h2>
      ${sa.length ? senateVoteRows : '<p class="muted">Sem votações nominais do Senado com registro neste recorte.</p>'}
      ${sa.length > par.senateVoteLim ? `<button type="button" class="opt cid-more" data-par-senate-votes-more>Mostrar mais (${sa.length - par.senateVoteLim})</button>` : ''}
      ${senateVoteSource.detail ? `<p class="muted">${esc(senateVoteSource.detail)}</p>` : ''}${sourceMeta(senateVoteSource)}`
      : `<p class="muted">Votações nominais do Senado ainda não importadas.</p>${sourceMeta(senateVoteSource)}`}
  </section>
  <section class="card wide"><span class="k">Quem mais gastou a cota em cada partido</span>
    <div class="par-tops">${[a, b].map(p => `<div><b class="par-sigla sm">${esc(p.sigla)}</b>${p.top.length ? p.top.map(x => `<button type="button" class="cid-row" data-pol="${esc(x.id)}">${cidAvatar(x, 40)}<span class="cid-rowtxt"><b>${esc(cidNome(x.name))}</b><small>${esc(CARGO[x.role] || '')}</small></span><span class="cid-rowval"><b class="mono">${x.gasto === null || x.gasto === undefined ? 'Sem dados' : cidMil(x.gasto)}</b></span></button>`).join('') : '<p class="muted">Sem notas importadas.</p>'}</div>`).join('')}</div>
  </section>`;
}

function vPartidos() {
  if (typeof profileSenateEnsure === 'function') profileSenateEnsure();
  parLoad();
  const head = `<button type="button" class="back" data-back>‹ Voltar</button>
  ${pageHead('Câmara e Senado', 'Comparar partidos', 'Registros da lista, gastos com a cota, presença e votos de dois partidos lado a lado.')}`;
  if (par.erro) return `${head}<section class="card wide"><p>Não deu para carregar os partidos agora.</p><p class="muted">${esc(par.erro)}</p><button type="button" class="more" data-par-retry>Tentar de novo</button></section>`;
  if (!par.data) return `${head}<section class="card wide par-pick sk-card">${skL('140px', 10)}${skel('chips', 12)}</section>${skel('cmp')}`;
  const porSigla = Object.fromEntries(par.data.itens.map(p => [p.sigla, p]));
  const [a, b] = par.sel.map(s => porSigla[s]).filter(Boolean);
  return `${head}
  <section class="card wide par-pick"><span class="k">Escolha dois partidos</span>
    <div class="chips" role="group" aria-label="Partidos">${par.data.itens.map(p => `<button type="button" class="fchip" data-par="${esc(p.sigla)}" aria-pressed="${par.sel.includes(p.sigla)}">${esc(p.sigla)} <b>${p.membros}</b></button>`).join('')}</div>
    <span class="muted">O número ao lado conta registros incluídos na lista (deputados(as) + senadores(as)); o Senado tem 81 cadeiras e a lista pode incluir suplentes em transição. Toque para trocar; o mais antigo da comparação sai.</span>
  </section>
  ${a && b ? parTabela(a, b) : '<p class="note">Escolha dois partidos para comparar.</p>'}
  <span class="src">Destaque em roxo: menor gasto médio, menos alertas ou mais presença na Câmara. Registros de presença do Senado são contagens informativas, sem ranking, e não contam sessões sem linha publicada. Partidos maiores tendem a ter mais variação interna; compare a média, não o total. Gastos pelas notas da cota (sem passagens aéreas da Câmara); presença e votos são mostrados separadamente por casa e pelos recortes das respectivas fontes.</span>`;
}

document.addEventListener('click', e => {
  if (e.target.closest('[data-par-cam-votes-more]')) { par.camVoteLim += 20; return rerender(); }
  if (e.target.closest('[data-par-senate-votes-more]')) { par.senateVoteLim += 20; return rerender(); }
  if (e.target.closest('[data-par-retry]')) { par.erro = null; cid.cache.delete(PAR_PATH); rerender(); return; }
  const t = e.target.closest('[data-par]');
  if (!t) return;
  const s = t.dataset.par;
  par.sel = par.sel.includes(s) ? par.sel.filter(x => x !== s) : [...par.sel, s].slice(-2);
  rerender();
});
