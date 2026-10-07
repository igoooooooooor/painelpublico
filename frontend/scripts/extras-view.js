/* Contador de impostos, presença de todos(as), quem votou o quê e comparação de perfis.
   A leitura de presença e votos passa pelos helpers compartilhados de perfil. */
const ext = { voto: {}, votoLim: 40, votoQ: '', presOrd: 'menos', presQ: '', presLim: 40, cmp: [], cmpQ: '', cmpRes: null, cmpErro: null, cmpLoading: false };
const extCam = id => 'camara:' + id;
const extPct = (a, b) => b ? Math.round(a / b * 100) : 0;

/* ---------- Contador de impostos (estimativa a partir do dado oficial) ---------- */
function extImposto(now = Date.now()) {
  const a = DATA.arrecadacao;
  if (!a) return null;
  const ini = Date.parse(a.inicio + 'T00:00:00-03:00'), fim = Date.parse(a.ate + 'T00:00:00-03:00') + 864e5;
  const porMs = a.acumulado / (fim - ini);
  return { valor: a.acumulado + porMs * Math.max(0, now - fim), porSeg: porMs * 1000, a };
}
const extReais = v => 'R$ ' + Math.floor(v).toLocaleString('pt-BR');
function extImpostoCard() {
  const t = extImposto();
  if (!t) return '';
  const cota = G.cotaTotal || 0, min = cota / t.porSeg / 60;
  return `<section class="card imposto">
    <div class="imposto-top"><span class="k">Contador de impostos · 2026</span><span class="live"><i></i>ao vivo</span></div>
    <div class="imposto-n mono" data-imposto aria-live="off">${extReais(t.valor)}</div>
    <span class="muted">em impostos federais pagos pelos brasileiros desde 1º de janeiro. Estimativa: o valor oficial até ${dmy(t.a.ate)} mais a média diária do ano.</span>
    <div class="imposto-grid">
      <div><b class="mono" data-imposto-seg>${extReais(t.porSeg)}</b><span>por segundo</span></div>
      <div><b class="mono" data-imposto-pessoa>${extReais(t.valor / t.a.populacao)}</b><span>por pessoa no ano</span></div>
    </div>
    ${cota ? `<p class="imposto-rel">Tudo o que a Câmara gastou da cota em 2026 (${cidMil(cota)}) é o que o país paga de impostos federais em <b>${min < 1 ? Math.round(min * 60) + ' segundos' : Math.round(min) + ' minutos'}</b>.</p>` : ''}
    <a class="src" href="${esc(t.a.url)}" target="_blank" rel="noopener">Fonte: Receita Federal (arrecadação até ${dmy(t.a.ate)}). Não inclui impostos estaduais e municipais ↗</a>
  </section>`;
}
(function tick() {
  const el = document.querySelector('[data-imposto]');
  if (el) { // troca só o texto (characterData), sem disparar o reencaixe da grade
    const t = extImposto(), set = (n, v) => { if (n && n.firstChild) n.firstChild.data = v; };
    set(el, extReais(t.valor)); set(document.querySelector('[data-imposto-pessoa]'), extReais(t.valor / t.a.populacao));
  }
  setTimeout(tick, 120);
})();

/* ---------- Presença de todos(as) ---------- */
function extPresRows() {
  const rows = typeof profilePresenceRows === 'function' ? profilePresenceRows() : (DATA.presencaTodos || []);
  return rows.filter(p => p && Number.isFinite(p.dias) && p.dias > 0
    && [p.presente, p.falta, p.justificadas].every(n => Number.isFinite(n) && n >= 0)
    && p.presente + p.falta + p.justificadas === p.dias);
}
function extPres(id) {
  const p = typeof profilePresence === 'function'
    ? profilePresence(String(id).includes(':') ? String(id) : extCam(id))
    : extPresRows().find(x => String(x.id) === String(id));
  return p && Number.isFinite(p.dias) && p.dias > 0 ? p : null;
}
function extPresBar(p) {
  if (!p || !Number.isFinite(p.dias) || p.dias <= 0) return '';
  return `<span class="pbar" role="img" aria-label="${p.presente} presenças, ${p.justificadas} faltas justificadas, ${p.falta} faltas em ${p.dias} dias"><i style="width:${p.presente / p.dias * 100}%"></i><i class="j" style="width:${p.justificadas / p.dias * 100}%"></i><i class="f" style="width:${p.falta / p.dias * 100}%"></i></span>`;
}
function vPresenca() {
  const all = extPresRows();
  const q = cidFold(ext.presQ);
  const lista = all.filter(p => !q || cidFold(`${p.nome} ${p.partido} ${p.uf}`).includes(q))
    .sort((a, b) => ext.presOrd === 'menos' ? a.presente / a.dias - b.presente / b.dias || a.nome.localeCompare(b.nome) : b.presente / b.dias - a.presente / a.dias || a.nome.localeCompare(b.nome));
  const media = all.reduce((s, p) => s + p.presente / p.dias, 0) / (all.length || 1);
  const cheio = all.filter(p => p.presente === p.dias).length, metade = all.filter(p => p.presente / p.dias < 0.5).length;
  const dias = all.length ? Math.max(...all.map(p => p.dias)) : 0;
  return `<button type="button" class="back" data-back>‹ Voltar</button>
  ${pageHead('Câmara · 2026', 'Presença', `Quantos dias cada deputado(a) foi às ${dias} sessões de votação do Plenário em 2026.`)}
  <section class="card hero">
    <span class="k">Média dos dados disponíveis</span>
    <div class="huge">${Math.round(media * 100)}<small style="margin-left:4px">%</small></div>
    <span class="muted">dos dias com sessão, em média, entre os(as) ${all.length} deputados(as) com dados de presença disponíveis.</span>
    <div class="hero-split"><div><b class="mono">${cheio}</b><span>não faltaram nenhum dia</span></div><div><b class="mono">${metade}</b><span>foram a menos da metade</span></div></div>
    <div class="legend" style="color:var(--hero-muted)"><span><i style="background:var(--accent-2)"></i>Presente</span><span><i style="background:var(--hero-muted)"></i>Falta justificada</span><span><i style="background:var(--warn)"></i>Falta</span></div>
  </section>
  <label class="search" for="ext-pres-q"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="ext-pres-q" type="search" placeholder="Nome, partido ou estado" value="${esc(ext.presQ)}" autocomplete="off"></label>
  <div class="chips" role="group" aria-label="Ordenar">${[['menos', 'Menos presentes'], ['mais', 'Mais presentes']].map(([k, n]) => `<button type="button" class="fchip" data-pres-ord="${k}" aria-pressed="${ext.presOrd === k}">${n}</button>`).join('')}</div>
  <div id="ext-pres-list" class="cid-stack">${extPresList(lista)}</div>
  <span class="src">Fonte: página de presença em Plenário de cada deputado(a) na Câmara, ${dias} dias com sessão deliberativa em 2026. Falta justificada inclui missão autorizada, licença e atestado. Quem assumiu no meio do ano tem menos dias na conta.</span>`;
}
function extPresList(lista) {
  if (!lista.length) return '<section class="card"><p>Ninguém encontrado.</p></section>';
  return `<span class="muted" role="status">${lista.length} deputados(as)</span><section class="card cid-list">${lista.slice(0, ext.presLim).map((p, i) => `<button type="button" class="cid-row" data-pol="${extCam(p.id)}">${cidAvatar({ id: extCam(p.id), name: p.nome }, 48)}<span class="cid-rowtxt"><b>${esc(p.nome)}</b><small>${esc(p.partido)} · ${esc(p.uf)}${p.motivos?.length && p.justificadas ? ` · ${esc(p.motivos[0][0].toLowerCase())} (${p.motivos[0][1]})` : ''}</small>${extPresBar(p)}</span>
    <span class="cid-rowval"><b class="mono ${p.presente / p.dias < 0.5 ? 'warn' : ''}">${p.presente}/${p.dias}</b><small>${extPct(p.presente, p.dias)}% presente</small></span></button>`).join('')}</section>
  ${lista.length > ext.presLim ? `<button type="button" class="opt cid-more" data-pres-more>Mostrar mais (${lista.length - ext.presLim})</button>` : ''}`;
}
const cidFold = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

/* ---------- Quem votou o quê ---------- */
const EXT_VOTO = { 'Sim': 'Sim', 'Não': 'Não', 'Abstenção': 'Abstenção', 'Obstrução': 'Obstrução', 'Artigo 17': 'Presidiu' };
function extVotos(v) {
  const lista = typeof profileVoteRows === 'function' ? profileVoteRows(v) : DATA.votosCompletos?.[v.id];
  if (!Array.isArray(lista)) return null;
  return lista.map(x => [x[0], x[1], x[2], x[3], v.secreta ? 'Presente' : (x[4] ? (EXT_VOTO[x[4]] || x[4]) : 'Presente')]);
}
function extQuemVotou(v) {
  const todos = extVotos(v);
  if (!todos?.length) return `<section class="card wide" id="quem-votou"><span class="k">Quem votou o quê</span><p class="muted">Sem registros individuais importados para esta votação.</p></section>`;
  const grupos = {};
  todos.forEach(x => (grupos[x[4]] = grupos[x[4]] || []).push(x));
  const ordem = ['Sim', 'Não', 'Abstenção', 'Obstrução', 'Presidiu', 'Presente', 'Não votou'].filter(g => grupos[g]);
  if (!ext.voto[v.id]) ext.voto[v.id] = v.secreta ? 'Presente' : (grupos['Não']?.length || 0) <= (grupos['Sim']?.length || 0) && grupos['Não'] ? 'Não' : 'Sim';
  const sel = ext.voto[v.id], q = cidFold(ext.votoQ);
  const lista = (grupos[sel] || []).filter(x => !q || cidFold(`${x[1]} ${x[2]} ${x[3]}`).includes(q)).sort((a, b) => a[1].localeCompare(b[1]));
  const partidos = {};
  (grupos[sel] || []).forEach(x => partidos[x[2]] = (partidos[x[2]] || 0) + 1);
  const topP = Object.entries(partidos).sort((a, b) => b[1] - a[1]).slice(0, 4);
  return `<section class="card wide" id="quem-votou">
    <span class="k">Quem votou o quê</span>
    ${v.secreta ? '<p class="note">Voto secreto: a Câmara só publica quem marcou presença na votação, não o voto de cada um(a).</p>' : ''}
    <div class="chips" role="group" aria-label="Filtrar por voto">${ordem.map(g => `<button type="button" class="fchip" data-voto-grupo="${esc(g)}" data-voto-id="${esc(v.id)}" aria-pressed="${sel === g}">${g === 'Presente' ? 'Marcaram presença' : g} <b>${grupos[g].length}</b></button>`).join('')}</div>
    ${(grupos[sel] || []).length > 8 ? `<label class="search" for="ext-voto-q"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="ext-voto-q" type="search" placeholder="Procurar nome, partido ou estado" value="${esc(ext.votoQ)}" autocomplete="off"></label>` : ''}
    ${topP.length > 1 && sel !== 'Não votou' ? `<span class="muted">Partidos com mais votos “${esc(sel.toLowerCase())}”: ${topP.map(([p, n]) => `${esc(p)} ${n}`).join(' · ')}</span>` : ''}
    <div class="cid-list ext-vlist">${lista.slice(0, ext.votoLim).map(x => `<button type="button" class="cid-row" data-pol="${extCam(x[0])}">${cidAvatar({ id: extCam(x[0]), name: x[1] }, 44)}<span class="cid-rowtxt"><b>${esc(x[1])}</b><small>${esc(x[2])} · ${esc(x[3])}</small></span><span class="cid-rowval"><span class="vchip ${sel === 'Sim' ? 'sim' : sel === 'Não' ? 'nao' : ''}">${esc(sel === 'Presente' ? 'presente' : sel.toLowerCase())}</span></span></button>`).join('') || '<p class="muted">Ninguém com esse nome neste grupo.</p>'}</div>
    ${lista.length > ext.votoLim ? `<button type="button" class="opt cid-more" data-voto-more>Mostrar mais (${lista.length - ext.votoLim})</button>` : ''}
    <span class="muted">Toque num nome para ver a ficha: quanto gastou, presença e como votou.</span>
  </section>`;
}

/* ---------- Ficha leve: presença e votos de quem é deputado(a) ---------- */
function extVotosDe(num) {
  const id = String(num).includes(':') ? String(num) : extCam(num);
  const rows = typeof profileVotes === 'function' ? profileVotes(id) : (DATA.votacoes || []).map(v => {
    const t = extVotos(v) || [];
    const x = t.find(r => String(r[0]) === String(num).replace(/^camara:/, ''));
    return { v, voto: x?.[4] ?? null };
  });
  return (rows || []).filter(r => r?.v && String(r.v.data || '').startsWith('2026'))
    .sort((a, b) => String(b.v.data).localeCompare(String(a.v.data)));
}
function extFichaExtra(id) {
  const [casa, num] = String(id).split(':');
  if (casa === 'senado') {
    const official = typeof cidFonte === 'function' ? cidFonte({ id })
      : /^\d+$/.test(num || '') ? `https://www25.senado.leg.br/web/senadores/senador/-/perfil/${encodeURIComponent(num)}` : null;
    return `<section class="card"><span class="k">Presença no Senado</span>
      <p class="muted">Sem dados de presença do Senado importados neste painel.</p>
      <span class="k">Votações individuais no Senado</span>
      <p class="muted">Sem registros individuais de votação do Senado importados neste painel.</p>
      ${official ? `<a class="fchip" href="${esc(official)}" target="_blank" rel="noopener">Conferir no Senado ↗</a>` : ''}
    </section>`;
  }
  if (casa !== 'camara') return '';
  const p = extPres(num), votos = extVotosDe(id), presRows = extPresRows();
  const media = presRows.length ? presRows.reduce((s, x) => s + x.presente / x.dias, 0) / presRows.length : null;
  const votacoes = votos.length;
  const presenceUrl = /^\d+$/.test(num || '') ? `https://www.camara.leg.br/deputados/${encodeURIComponent(num)}/presenca-plenario/2026` : null;
  return `${p ? `<section class="card ${p.presente / p.dias < 0.5 ? 'alarm' : ''}">
    <span class="k">Presença nas sessões de votação · 2026</span>
    <div><span class="big">${p.presente}/${p.dias}</span> <span class="muted">dias${media === null ? '' : ` · média dos registros válidos ${Math.round(media * 100)}%`}</span></div>
    ${extPresBar(p)}
    <div class="legend"><span><i style="background:var(--accent)"></i>Presente ${p.presente}</span><span><i style="background:var(--muted);opacity:.55"></i>Justificada ${p.justificadas}</span><span><i style="background:var(--warn)"></i>Falta ${p.falta}</span></div>
    ${p.motivos?.length ? `<p class="note">Justificativas: ${p.motivos.map(([k, n]) => `${esc(k.toLowerCase())} (${n})`).join(', ')}.</p>` : ''}
    <button type="button" class="more" data-go="presenca">Ver a presença de todos(as)</button>
  </section>` : `<section class="card"><span class="k">Presença nas sessões de votação · 2026</span><p class="muted">Sem registro importado para este perfil. Ausência de dado não significa zero presença.</p></section>`}
  <section class="card"><span class="k">Votações selecionadas do Placar · ${votacoes}</span>
    ${votacoes ? `<div class="votes">${votos.map(({ v, voto }) => {
      const label = voto == null ? 'Sem registro importado' : v.secreta ? 'Presença registrada · voto secreto' : String(voto).toLowerCase();
      return `<button type="button" class="vt" data-vote="${esc(v.id)}"><b>${esc(label)}</b><span>${esc(v.titulo)}</span></button>`;
    }).join('')}</div>` : '<p class="muted">Nenhuma votação selecionada do Placar em 2026.</p>'}
    <span class="muted">A lista cobre apenas as votações selecionadas no Placar; falta de registro não identifica motivo nem situação do mandato.</span>
  </section>
  <span class="src">Fonte: Câmara dos Deputados. ${presenceUrl ? `<a href="${esc(presenceUrl)}" target="_blank" rel="noopener">Presença no Plenário ↗</a>` : ''} Os botões de votação abrem o resumo e as fontes oficiais de cada votação.</span>`;
}

/* ---------- Comparar perfis ---------- */
function extCmpAdd(id) {
  if (!ext.cmp.includes(id)) ext.cmp = [...ext.cmp, id].slice(-2);
  ext.cmpQ = ''; ext.cmpRes = null;
  ext.cmp.forEach(x => cidGet('/api/c/politico/' + encodeURIComponent(x)).then(() => state.view === 'comparar' && rerender()).catch(e => { ext.cmpErro = cidErroMsg(e); if (state.view === 'comparar') rerender(); }));
}
function extCmpBusca(q) {
  ext.cmpQ = q;
  if (!q.trim()) { ext.cmpRes = null; extCmpRenderPicker(); return; }
  ext.cmpLoading = true; extCmpRenderPicker();
  cidGet(`/api/c/politicos?pageSize=8&page=1&ordem=nome&q=${encodeURIComponent(q.trim())}`).then(d => { if (ext.cmpQ !== q) return; ext.cmpRes = d.itens; ext.cmpLoading = false; extCmpRenderPicker(); })
    .catch(e => { ext.cmpLoading = false; ext.cmpRes = []; ext.cmpErro = cidErroMsg(e); extCmpRenderPicker(); });
}
function extCmpPickerList() {
  if (ext.cmpLoading) return skel('linhas', 3);
  if (ext.cmpRes === null) return `<div class="chips">${D.slice(0, 6).map(d => `<button type="button" class="fchip" data-cmp-add="${extCam(d.id)}">${esc(first(d.nome))}</button>`).join('')}</div>`;
  if (!ext.cmpRes.length) return `<p class="muted">${ext.cmpErro ? esc(ext.cmpErro) : 'Ninguém encontrado.'}</p>`;
  return ext.cmpRes.filter(x => !ext.cmp.includes(x.id)).map(x => `<button type="button" class="cid-row" data-cmp-add="${esc(x.id)}">${cidAvatar(x, 40)}<span class="cid-rowtxt"><b>${esc(cidNome(x.name))}</b><small>${cidQuem(x)}</small></span><span class="cid-rowval"><span class="fchip">Escolher</span></span></button>`).join('');
}
function extCmpRenderPicker() { const el = document.getElementById('ext-cmp-res'); if (el) el.innerHTML = extCmpPickerList(); }
function vComparar() {
  const fichas = ext.cmp.map(id => ({ id, f: cid.cache.get('/api/c/politico/' + encodeURIComponent(id)) }));
  const prontas = fichas.filter(x => x.f).map(x => x.f);
  const picker = ext.cmp.length < 2 ? `<section class="card wide"><span class="k">${ext.cmp.length ? 'Com quem comparar?' : 'Escolha dois(duas) políticos(as)'}</span>
      <label class="search" for="ext-cmp-q"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="ext-cmp-q" type="search" placeholder="Nome, partido ou estado" value="${esc(ext.cmpQ)}" autocomplete="off"></label>
      <div id="ext-cmp-res" class="cid-list">${extCmpPickerList()}</div></section>` : '';
  let corpo = '';
  if (ext.cmp.length === 2 && prontas.length === 2) corpo = extCmpTabela(prontas);
  else if (ext.cmp.length === 2) corpo = ext.cmpErro ? `<section class="card wide"><p>Não deu para abrir as fichas.</p><p class="muted">${esc(ext.cmpErro)}</p></section>` : skel('cmp');
  return `<button type="button" class="back" data-back>‹ Voltar</button>
  ${pageHead('Lado a lado', 'Comparar', 'Gastos, alertas, presença e votos de dois(duas) políticos(as) na mesma tela.')}
  ${ext.cmp.length ? `<div class="cmp-slots">${ext.cmp.map(id => { const f = cid.cache.get('/api/c/politico/' + encodeURIComponent(id)); const p = f?.pessoa || { id, name: '…' }; return `<div class="cmp-slot">${cidAvatar(p, 40)}<span><b>${esc(cidNome(p.name))}</b><small>${esc([p.party, p.uf].filter(Boolean).join(' · '))}</small></span><button type="button" class="cmp-x" data-cmp-del="${esc(id)}" aria-label="Tirar ${esc(cidNome(p.name))} da comparação">×</button></div>`; }).join('')}</div>` : ''}
  ${picker}${corpo}`;
}
function extCmpPerfil(f) {
  return typeof profileData === 'function' ? profileData(f.pessoa || f.pessoa?.id) || {} : {};
}
function extCmpParticipacao(profile) {
  const mandato = profile.mandato || {}, pessoa = profile.pessoa || {};
  const values = [mandato.participacao || pessoa.position, mandato.exercicio || pessoa.employmentStatus].filter(Boolean);
  if (!values.length && pessoa.foraDaLista) values.push('Fora da lista atual');
  return values.length ? values.map(esc).join('<br>') : 'Sem informação importada';
}
function extCmpContato(profile) {
  const c = profile.contato;
  if (!c) return 'Sem dados importados';
  const available = [c.email, c.endereco, ...(Array.isArray(c.telefones) ? c.telefones : []), ...(Array.isArray(c.redes) ? c.redes.map(r => r.url) : [])].some(Boolean);
  if (!available) return 'Sem contato informado neste recorte';
  return c.status === 'partial' ? 'Disponível em recorte parcial' : 'Dados disponíveis';
}
function extCmpProjetos(profile) {
  const projects = profile.projetos;
  if (!projects) return 'Sem dados importados';
  if (projects.status === 'partial') return 'Disponíveis em recorte parcial';
  if (projects.status === 'imported' || Number.isInteger(projects.total)) return 'Dados disponíveis';
  return projects.items?.length ? 'Disponíveis neste recorte' : 'Sem dados importados';
}
function extCmpRemuneracao(profile) {
  const salary = profile.remuneracao;
  if (!salary || !Number.isFinite(salary.amount)) return 'Sem referência importada';
  return `${salary.amount.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })} por mês · referência do cargo, não pagamento individual`;
}
function extCmpGabinete(profile) {
  const office = profile.gabinete;
  if (!office) return 'Sem dados importados';
  const value = Number.isFinite(office.amount)
    ? office.amount.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
    : 'valor não informado';
  const period = office.period || (Number.isFinite(office.months) ? `${office.months} meses` : 'período não informado');
  const monthNames = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  const months = Object.keys(office.months || {}).map(Number).filter(n => n >= 1 && n <= 12).sort((a, b) => a - b);
  const observed = months.length ? ` · meses: ${months.map(m => monthNames[m]).join(', ')}` : '';
  const staff = Number.isFinite(office.staffActive) ? `${office.staffActive} pessoas ativas` : 'equipe não informada';
  const fetched = office.fetchedAt ? `fotografia ${String(office.fetchedAt).slice(0, 10)}` : 'fotografia sem data';
  return `${value} · ${esc(period)}${observed} · ${staff} · ${esc(fetched)}`;
}
function extCmpInfoRow(label, a, b) {
  return `<div class="cmp-row"><span class="cmp-l">${esc(label)}</span><div class="cmp-v">${a}</div><div class="cmp-v">${b}</div></div>`;
}
function extCmpTabela([a, b]) {
  const pa = a.pessoa, pb = b.pessoa, maxT = Math.max(a.total, b.total, 1);
  const perfilA = extCmpPerfil(a), perfilB = extCmpPerfil(b);
  const nome = p => esc(cidNome(p.name).split(' ')[0]);
  const lado = (va, vb, fmt, maiorPior = true) => {
    const ganha = va == null || vb == null || va === vb || va < 0 || vb < 0 ? '' : (va > vb) === maiorPior ? 'b' : 'a';
    return `<div class="cmp-v ${ganha === 'a' ? 'best' : ''}">${va == null ? 'Sem dados' : fmt(va)}</div><div class="cmp-v ${ganha === 'b' ? 'best' : ''}">${vb == null ? 'Sem dados' : fmt(vb)}</div>`;
  };
  const vsMedia = f => f.total != null && f.media ? Math.round((f.total / f.media - 1) * 100) : null;
  const pres = f => { const [casa, num] = String(f.pessoa.id).split(':'); return casa === 'camara' ? extPres(num) : null; };
  const pA = pres(a), pB = pres(b);
  const topCat = f => f.categorias[0] ? `${esc(f.categorias[0].nome)} <small>${extPct(f.categorias[0].valor, f.total)}%</small>` : '—';
  const topForn = f => f.fornecedores[0] ? `${esc(cidNome(f.fornecedores[0].name))} <small>${extPct(f.fornecedores[0].valor, f.total)}%</small>` : '—';
  const numA = String(pa.id).split(':')[1], numB = String(pb.id).split(':')[1];
  const ambosDep = String(pa.id).startsWith('camara:') && String(pb.id).startsWith('camara:');
  const votos = ambosDep ? DATA.votacoes.filter(v => !v.secreta).map(v => { const t = extVotos(v) || []; const x = t.find(r => String(r[0]) === numA), y = t.find(r => String(r[0]) === numB); return { v, va: x?.[4] ?? null, vb: y?.[4] ?? null }; }) : [];
  const comparaveis = votos.filter(r => r.va !== null && r.vb !== null);
  const iguais = comparaveis.filter(r => r.va === r.vb).length;
  return `<section class="card cmp wide">
    <div class="cmp-head"><span></span>${[a, b].map(f => `<button type="button" class="cmp-who" data-pol="${esc(f.pessoa.id)}">${cidAvatar(f.pessoa, 56)}<b>${esc(cidNome(f.pessoa.name))}</b><small>${esc([CARGO[f.pessoa.role], f.pessoa.party, f.pessoa.uf].filter(Boolean).join(' · '))}</small></button>`).join('')}</div>
    <div class="cmp-row"><span class="cmp-l">Cota gasta em 2026</span>${lado(a.total, b.total, v => `<b class="mono">${cidMil(v)}</b>`)}</div>
    <div class="cmp-row cmp-bars"><span class="cmp-l"></span><div><i style="width:${a.total == null ? 0 : a.total / maxT * 100}%"></i></div><div><i style="width:${b.total == null ? 0 : b.total / maxT * 100}%"></i></div></div>
    <div class="cmp-row"><span class="cmp-l">Comparado à média do cargo</span>${lado(vsMedia(a), vsMedia(b), v => `<b>${v > 0 ? '+' : ''}${v}%</b>`)}</div>
    <div class="cmp-row"><span class="cmp-l">Alertas</span>${lado(a.total == null ? null : a.alertas.length, b.total == null ? null : b.alertas.length, v => `<b>${v}</b>`)}</div>
    <div class="cmp-row"><span class="cmp-l">Presença no Plenário · Câmara</span>${lado(pA ? pA.presente / pA.dias : null, pB ? pB.presente / pB.dias : null, v => `<b>${Math.round(v * 100)}%</b>`, false)}</div>
    ${extCmpInfoRow('Participação e exercício', extCmpParticipacao(perfilA), extCmpParticipacao(perfilB))}
    ${extCmpInfoRow('Contato institucional', esc(extCmpContato(perfilA)), esc(extCmpContato(perfilB)))}
    ${extCmpInfoRow('Projetos', esc(extCmpProjetos(perfilA)), esc(extCmpProjetos(perfilB)))}
    ${extCmpInfoRow('Equipe e verba de gabinete', extCmpGabinete(perfilA), extCmpGabinete(perfilB))}
    ${extCmpInfoRow('Remuneração de referência', esc(extCmpRemuneracao(perfilA)), esc(extCmpRemuneracao(perfilB)))}
    <div class="cmp-row"><span class="cmp-l">Onde mais gastou</span><div class="cmp-v">${topCat(a)}</div><div class="cmp-v">${topCat(b)}</div></div>
    <div class="cmp-row"><span class="cmp-l">Empresa que mais recebeu</span><div class="cmp-v">${topForn(a)}</div><div class="cmp-v">${topForn(b)}</div></div>
  </section>
  ${votos.length ? `<section class="card wide"><span class="k">Como votaram</span>
    <h2 class="h" style="font-size:21px">${nome(pa)} e ${nome(pb)} registraram o mesmo voto em ${iguais} de ${comparaveis.length} votações comparáveis.</h2>
    ${votos.map(r => `<button type="button" class="cmp-vote" data-vote="${esc(r.v.id)}"><span>${esc(r.v.titulo)}</span><span class="vchip ${r.va === 'Sim' ? 'sim' : r.va === 'Não' ? 'nao' : ''}">${esc(r.va === null ? 'Sem registro importado' : r.va.toLowerCase())}</span><span class="vchip ${r.vb === 'Sim' ? 'sim' : r.vb === 'Não' ? 'nao' : ''}">${esc(r.vb === null ? 'Sem registro importado' : r.vb.toLowerCase())}</span><em>${r.va === null || r.vb === null ? 'sem registro comparável' : r.va === r.vb ? 'igual' : 'diferente'}</em></button>`).join('')}
    <span class="muted">A comparação considera apenas votos registrados por ambos; ausência de registro não significa que a pessoa não votou.</span>
  </section>` : ''}
  <span class="src">Destaque em roxo: quem gastou menos, teve menos alertas ou foi mais às sessões. Gastos pelas notas da cota publicadas pela Câmara e pelo Senado (sem as passagens aéreas da Câmara).</span>`;
}

/* ---------- Eventos ---------- */
document.addEventListener('click', e => {
  const t = e.target.closest('[data-pres-ord],[data-pres-more],[data-voto-grupo],[data-voto-more],[data-cmp-add],[data-cmp-del],[data-cmp-start]');
  if (!t) return;
  if (t.dataset.presOrd) { ext.presOrd = t.dataset.presOrd; ext.presLim = 40; return rerender(); }
  if (t.hasAttribute('data-pres-more')) { ext.presLim += 60; return rerender(); }
  if (t.dataset.votoGrupo) { ext.voto[t.dataset.votoId] = t.dataset.votoGrupo; ext.votoLim = 40; ext.votoQ = ''; return rerender(); }
  if (t.hasAttribute('data-voto-more')) { ext.votoLim += 80; return rerender(); }
  if (t.dataset.cmpAdd) { e.stopPropagation(); extCmpAdd(t.dataset.cmpAdd); return state.view === 'comparar' ? rerender() : go('comparar'); }
  if (t.dataset.cmpDel) { ext.cmp = ext.cmp.filter(x => x !== t.dataset.cmpDel); return rerender(); }
  if (t.hasAttribute('data-cmp-start')) { if (t.dataset.cmpStart) { ext.cmp = []; extCmpAdd(t.dataset.cmpStart); } go('comparar'); }
}, true);
let extTimer = null;
document.addEventListener('input', e => {
  const id = e.target.id;
  if (id === 'ext-pres-q') { ext.presQ = e.target.value; ext.presLim = 40; const q = cidFold(ext.presQ); const el = document.getElementById('ext-pres-list'); if (el) { const all = extPresRows(); el.innerHTML = extPresList(all.filter(p => !q || cidFold(`${p.nome} ${p.partido} ${p.uf}`).includes(q)).sort((a, b) => ext.presOrd === 'menos' ? a.presente / a.dias - b.presente / b.dias : b.presente / b.dias - a.presente / a.dias)); } }
  if (id === 'ext-voto-q') { ext.votoQ = e.target.value; const pos = e.target.selectionStart; rerender(); const i = document.getElementById('ext-voto-q'); if (i) { i.focus(); i.setSelectionRange(pos, pos); } }
  if (id === 'ext-cmp-q') { clearTimeout(extTimer); const v = e.target.value; extTimer = setTimeout(() => extCmpBusca(v), 250); }
});

/* ---------- Encaixe bento no computador ----------
   Os cards ficam em fileiras de 12 colunas. Se uma fileira não fecha (card sozinho ou dois de três),
   os cards dela se alargam para ocupar o espaço: nada de buraco na grade. */
function bentoFix() {
  const desk = matchMedia('(min-width: 900px)').matches;
  document.querySelectorAll('#app .view, #app .public-view, #app .public-results, #app .public-signal-section').forEach(box => {
    const kids = [...box.children];
    kids.forEach(k => { if (k.dataset.bento) { k.style.gridColumn = ''; delete k.dataset.bento; } });
    if (!desk) return;
    let run = [];
    const flush = () => {
      const rows = []; let row = [], used = 0;
      run.forEach(x => { if (used + x.span > 12) { rows.push(row); row = []; used = 0; } row.push(x); used += x.span; });
      if (row.length) rows.push(row);
      rows.forEach(r => {
        if (r.reduce((s, x) => s + x.span, 0) >= 12) return;
        const each = Math.floor(12 / r.length);
        r.forEach((x, i) => { x.el.style.gridColumn = `span ${i === r.length - 1 ? 12 - each * (r.length - 1) : each}`; x.el.dataset.bento = '1'; });
      });
      run = [];
    };
    kids.forEach(k => {
      const cs = getComputedStyle(k);
      if (cs.display === 'none' || cs.position === 'absolute') return;
      const m = /^span (\d+)$/.exec(cs.gridColumnStart);
      if (m && cs.gridColumnEnd === 'auto' && +m[1] < 12) run.push({ el: k, span: +m[1] }); else flush();
    });
    flush();
  });
}
let bentoQueued = false;
const bentoSoon = () => { if (bentoQueued) return; bentoQueued = true; requestAnimationFrame(() => { bentoQueued = false; bentoFix(); }); };
new MutationObserver(bentoSoon).observe(document.getElementById('app'), { childList: true, subtree: true });
addEventListener('resize', bentoSoon);
