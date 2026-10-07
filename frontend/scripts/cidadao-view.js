/* Telas do cidadão: "Fora do normal" (Home), "Alertas", "Políticos" (busca) e a ficha leve.
   Tudo em linguagem simples. A busca avançada continua acessível por um link discreto. */
const cid = {
  cache: new Map(), pending: new Set(),
  lupa: { tipo: 'pico,fornecedor', cargo: '', page: 1, itens: [], total: null, loading: false, erro: null, key: '' },
  pol: { q: '', cargo: '', ordem: 'nome', page: 1, itens: [], total: null, loading: false, erro: null, key: '', medias: null, cobertura: null },
  ficha: null, fichaId: null,
};
/* Peças de identidade usadas em todas as abas */
function brandMark() {
  return `<span class="brand"><svg class="brand-ic" width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><rect width="26" height="26" rx="8" fill="var(--accent)"/><rect x="6" y="13" width="3.2" height="7" rx="1.2" fill="#fff"/><rect x="11.4" y="9" width="3.2" height="11" rx="1.2" fill="#fff"/><rect x="16.8" y="5.5" width="3.2" height="14.5" rx="1.2" fill="#fff" opacity=".7"/></svg>Painel Público</span>`;
}
/* Skeleton: a forma do conteúdo em cinza, com brilho suave, enquanto os dados chegam.
   Toda espera do app usa uma destas formas; o texto fica só para leitores de tela. */
const skL = (w = '100%', h = 12, extra = '') => `<i class="sk ${extra}" style="width:${w};height:${h}px"></i>`;
const skO = (s = 44) => `<i class="sk sk-o" style="width:${s}px;height:${s}px"></i>`;
const SK_MSG = '<span class="sr-only" role="status">Carregando…</span>';
function skel(tipo = 'cards', n = 3) {
  const rep = (k, f) => Array.from({ length: k }, (_, i) => f(i)).join('');
  const linhas = k => rep(k, i => `<div class="sk-row">${skO(44)}<span class="sk-col">${skL(i % 2 ? '58%' : '70%', 13)}${skL('42%', 10)}${skL('80%', 5)}</span>${skL('64px', 14)}</div>`);
  if (tipo === 'alerta') return SK_MSG + rep(n, () => `<div class="card sk-card cid-alert" aria-hidden="true"><div class="sk-between">${skL('118px', 22, 'sk-pill')}${skL('56px', 12)}</div>
    <div class="sk-row sk-flat">${skO(40)}<span class="sk-col">${skL('52%', 13)}${skL('70%', 10)}</span></div>${skL('86%', 22)}${skL('60%', 22)}
    <div class="sk-bars">${rep(9, i => `<i class="sk" style="height:${[22, 30, 18, 40, 86, 26, 20, 34, 16][i]}%"></i>`)}</div>${skL('96%')}${skL('72%')}
    <div class="sk-between sk-start">${skL('92px', 36, 'sk-pill')}${skL('132px', 36, 'sk-pill')}</div></div>`);
  if (tipo === 'lista') return `${SK_MSG}<section class="card cid-list sk-card" aria-hidden="true">${linhas(n)}</section>`;
  if (tipo === 'linhas') return `${SK_MSG}<div aria-hidden="true">${linhas(n)}</div>`;
  if (tipo === 'chips') return `<div class="chips" aria-hidden="true">${rep(n, i => skL(`${[64, 56, 72, 60, 84, 58][i % 6]}px`, 40, 'sk-pill'))}</div>`;
  if (tipo === 'numeros') return `${SK_MSG}<div class="row2 sk-tiles" aria-hidden="true">${rep(3, () => `<div class="tile">${skL('60%', 10)}${skL('80%', 22)}</div>`)}</div>`;
  if (tipo === 'ficha') return `${SK_MSG}<div class="profile" aria-hidden="true">${skO(64)}<span class="sk-col" style="flex:1">${skL('55%', 24)}${skL('40%', 12)}</span></div>
    <section class="card hero sk-card" aria-hidden="true">${skL('40%', 10)}${skL('62%', 56)}${skL('90%')}${skL('100%', 10)}${skL('100%', 10)}</section>
    ${rep(2, () => `<section class="card sk-card" aria-hidden="true">${skL('35%', 10)}${skL('50%', 30)}${skL('100%', 8)}${skL('88%')}${skL('70%')}</section>`)}`;
  if (tipo === 'ficha-respostas') return `${SK_MSG}<div class="profile" aria-hidden="true">${skO(64)}<span class="sk-col" style="flex:1">${skL('55%', 24)}${skL('40%', 12)}</span></div>
    <span class="k">Em 3 respostas</span><div class="cid-answers" aria-hidden="true">${rep(3, i => `<section class="card ${i === 0 ? 'hero' : ''} sk-card">${skL('50%', 24)}${skL('65%', 56)}${skL('90%')}${skL('100%', 10)}${skL('100%', 10)}</section>`)}</div>
    ${skL('110px', 24)}${rep(4, () => `<div class="card sk-card" aria-hidden="true">${skL('70%', 24)}</div>`)}`;
  if (tipo === 'cmp') return `${SK_MSG}<section class="card wide sk-card cmp" aria-hidden="true"><div class="cmp-head"><span></span>${rep(2, () => `<div class="sk-colc">${skO(56)}${skL('70%', 13)}${skL('50%', 10)}</div>`)}</div>
    ${rep(5, () => `<div class="cmp-row">${skL('80%', 11)}${skL('70%', 16)}${skL('70%', 16)}</div>`)}</section>`;
  return SK_MSG + rep(n, () => `<section class="card sk-card" aria-hidden="true">${skL('35%', 10)}${skL('70%', 20)}${skL('100%')}${skL('92%')}${skL('64%')}</section>`);
}
function pageHead(kicker, title, lead) {
  return `<header class="ph"><span class="k">${kicker}</span><h1 class="h ph-t">${title}</h1>${lead ? `<p class="ph-lead">${lead}</p>` : ''}</header>`;
}
const advLink = (attrs, label = 'Busca avançada') => `<button type="button" class="cid-adv" ${attrs}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>${label} →</button>`;
const cidPublicAuthorityAttrs = (p, mandate) => `data-public-authority="${esc(p.id || '')}" data-public-authority-name="${esc(cidNome(p.name))}" data-public-authority-role="${esc(p.role || '')}" data-public-authority-position="${esc(p.position || mandate?.position || mandate?.participacao || '')}" data-public-authority-status="${esc(p.employmentStatus || mandate?.employmentStatus || mandate?.exercicio || '')}" data-public-authority-institution="${esc(p.institution || '')}" data-public-authority-sphere="${esc(p.sphere || '')}" data-public-authority-uf="${esc(p.uf || '')}" data-public-authority-source="${esc(p.sourceUrl || mandate?.sourceUrl || '')}"`;
const CARGO = { deputado: 'Deputado(a) federal', senador: 'Senador(a)' };
const CARGO_PL = { deputado: 'deputados(as)', senador: 'senadores(as)' };
const MES_LONGO = ['', 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];

function cidErroMsg(e) {
  if (e && e.status === 404) return 'O servidor que está rodando é de uma versão anterior. Feche-o (Ctrl+C no terminal) e rode de novo: python3 -m backend.server --port 8000';
  if (location.protocol === 'file:') return 'Abra o app pelo servidor (python3 -m backend.server --port 8000), não pelo arquivo direto.';
  if (e && e.name === 'AbortError') return 'O servidor demorou demais para responder.';
  return (e && e.message) || 'Não deu para carregar agora.';
}
async function cidGet(path) {
  if (cid.cache.has(path)) return cid.cache.get(path);
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 15000);
  let r;
  try { r = await fetch(path, { headers: { Accept: 'application/json' }, signal: ctl.signal }); }
  finally { clearTimeout(timer); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const err = new Error(data.error || 'Não deu para carregar agora.'); err.status = r.status; throw err; }
  cid.cache.set(path, data);
  return data;
}
const cidLocalId = id => String(id || '').startsWith('camara:') ? String(id).slice(7) : null;
const cidTemFicha = id => /^(?:camara|senado):\d+$/.test(String(id || ''));
function cidIniciais(nome) { return String(nome || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]).join('').toUpperCase(); }
/* Foto oficial (Câmara/Senado); se não carregar, ficam as iniciais por baixo */
function cidFoto(id) {
  const [casa, num] = String(id || '').split(':');
  if (!/^\d+$/.test(num || '')) return null;
  return casa === 'camara' ? `https://www.camara.leg.br/internet/deputado/bandep/${num}.jpg` : casa === 'senado' ? `https://www.senado.leg.br/senadores/img/fotos-oficiais/senador${num}.jpg` : null;
}
function cidAvatar(p, size = 44) {
  const dim = `width:${size}px;height:${size}px`;
  const ini = `<span class="cid-av cid-ini" style="${dim};font-size:${Math.round(size / 2.8)}px" aria-hidden="true">${esc(cidIniciais(cidNome(p.name)))}</span>`;
  const rawPhoto = p.photo || p.foto;
  const url = (typeof profileSafeUrl === 'function' && profileSafeUrl(rawPhoto)) || cidFoto(p.id);
  return url ? `<span class="cid-avs" style="${dim}">${ini}<img class="cid-av" src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()" style="${dim}"></span>` : ini;
}
const cidNome = n => { const s = String(n || ''); return s === s.toUpperCase() ? s.toLowerCase().replace(/(^|\s)\S/g, c => c.toUpperCase()) : s; };
function cidQuem(p) {
  return [CARGO[p.role] || 'Parlamentar', p.party, p.uf].filter(Boolean).map(esc).join(' · ') + (p.foraDaLista ? ' · fora da lista atual' : '');
}
function cidSenadoFotografia(p) {
  if (p?.role !== 'senador') return '';
  const position = String(p.position || '').trim();
  const employmentStatus = String(p.employmentStatus || '').trim();
  if (!position && !employmentStatus) return '';
  return `<section class="card"><span class="k">Na fotografia da fonte</span>
    ${position ? `<p><b>Participação no mandato:</b> ${esc(position)}</p>` : ''}
    ${employmentStatus ? `<p>${esc(employmentStatus)}</p>` : ''}
    ${p.sourceUrl ? `<a class="fchip" href="${esc(p.sourceUrl)}" target="_blank" rel="noopener">Fonte do Senado ↗</a>` : ''}
  </section>`;
}
const cidMil = v => v >= 1e6 ? 'R$ ' + (v / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' mi' : 'R$ ' + Math.round(v / 1e3).toLocaleString('pt-BR') + ' mil';
const cidFonte = p => {
  const [casa, num] = String(p.id || '').split(':');
  return casa === 'camara' ? `https://www.camara.leg.br/deputados/${num}?ano=2026` : casa === 'senado' ? `https://www25.senado.leg.br/web/senadores/senador/-/perfil/${num}` : null;
};

/* ---------- Cartão de alerta: o coração da fiscalização simples ---------- */
function cidNivel(a) {
  return a.nivel === 'alto' ? ['alto', 'Muito fora do normal'] : a.nivel === 'medio' ? ['medio', 'Fora do normal'] : ['info', 'Para conferir'];
}
function cidVisual(a) {
  if (a.tipo === 'pico' && a.serie?.length) {
    const max = Math.max(...a.serie.map(s => s.valor || 0), 1), refH = a.referencia / max * 64;
    return `<div class="cid-spark" role="img" aria-label="Gasto por mês. Em ${MES_LONGO[a.mes]} foi ${brl(a.valor)}; o normal era ${brl(a.referencia)}.">
      <div class="cid-ref" style="bottom:${refH + 16}px"><span>normal: ${cidMil(a.referencia)}</span></div>
      ${a.serie.map(s => `<div class="cid-col ${s.mes === a.mes ? 'hot' : s.mes > a.mes ? 'after' : ''}"><i style="height:${Math.max(2, (s.valor || 0) / max * 64)}px"></i><span>${MES[s.mes]}</span></div>`).join('')}
    </div>`;
  }
  if (a.tipo === 'fornecedor' && a.parte) {
    return `<div class="cid-share" role="img" aria-label="${Math.round(a.parte * 100)}% para ${esc(a.fornecedor)}">
      <div class="cid-sharebar"><i style="width:${a.parte * 100}%"></i></div>
      <div class="cid-sharelbl"><span><b>${Math.round(a.parte * 100)}%</b> ${esc(cidNome(a.fornecedor))}</span><span>${100 - Math.round(a.parte * 100)}% outros</span></div>
    </div>`;
  }
  return '';
}
function cidPorQue(a) {
  if (a.tipo === 'pico') return `Aparece quando o gasto de um mês passa de 1,75 vez o valor normal dos meses anteriores e a diferença é de pelo menos R$ 10 mil. "Normal" é o valor do meio dos meses anteriores (a mediana).`;
  if (a.tipo === 'fornecedor') return `Aparece quando metade ou mais do dinheiro da cota no ano foi para uma mesma empresa, somando pelo menos R$ 30 mil. Pode ser um contrato fixo de divulgação ou escritório; vale conferir as notas.`;
  return `Aparece para toda nota de R$ 10 mil ou mais. É só um corte de valor.`;
}
function cidCard(a, opts = {}) {
  const [cls, label] = cidNivel(a), p = a.pessoa || {};
  return `<article class="card cid-alert" data-n="${cls}">
    <div class="cid-top"><span class="cid-chip ${cls}"><i></i>${label}</span><span class="muted">${a.tipo === 'pico' ? MES[a.mes] + '/' + String(a.periodo).slice(0, 4) : 'em ' + String(a.periodo).slice(0, 4)}</span></div>
    ${opts.semPessoa ? '' : `<button type="button" class="cid-who" data-pol="${esc(p.id)}">${cidAvatar(p, 40)}<span><b>${esc(cidNome(p.name))}</b><small>${cidQuem(p)}</small></span></button>`}
    <h3 class="cid-title">${esc(a.titulo)}</h3>
    ${cidVisual(a)}
    <p class="cid-frase">${esc(a.frase)}</p>
    <details class="cid-why"><summary>Por que apareceu aqui?</summary><p>${cidPorQue(a)}</p><p class="muted">Fora do normal não quer dizer irregular. É um convite para conferir as notas.</p></details>
    <div class="cid-actions">${opts.semPessoa ? '' : `<button type="button" class="fchip" data-pol="${esc(p.id)}">Ver a ficha</button>`}${cidFonte(p) ? `<a class="fchip" href="${esc(cidFonte(p))}" target="_blank" rel="noopener">Conferir na fonte ↗</a>` : ''}</div>
  </article>`;
}

/* ---------- Home: "Fora do normal" ---------- */
function cidHomeCard() {
  const path = '/api/c/radar?pageSize=8&tipo=pico,fornecedor';
  const data = cid.cache.get(path);
  if (!data) {
    if (!cid.pending.has(path)) { cid.pending.add(path); cidGet(path).then(() => { cid.pending.delete(path); if (state.view === 'inicio' || state.view === 'hoje') rerender(); }).catch(() => { cid.pending.delete(path); cid.cache.set(path, { erro: true }); if (state.view === 'inicio' || state.view === 'hoje') rerender(); }); }
    return `<section class="cid-home"><div class="cid-head"><h2 class="h">Fora do normal</h2></div><div class="carousel cid-carousel">${skel('alerta', 3)}</div></section>`;
  }
  if (data.erro) return `<section class="cid-home"><div class="cid-head"><div><h2 class="h">Fora do normal</h2><span class="muted">Os alertas da Câmara e do Senado não carregaram.</span></div></div><section class="card"><p>Não deu para carregar os alertas agora.</p><button type="button" class="more" data-home-retry>Tentar de novo</button></section></section>`;
  const itens = [...data.itens].sort((a, b) => (b.nivel === 'alto') - (a.nivel === 'alto'));
  return `<section class="cid-home">
    <div class="cid-head"><div><h2 class="h">Fora do normal</h2><span class="muted">Gastos de deputados(as) e senadores(as) em 2026 que merecem uma conferida</span></div></div>
    <div class="carousel cid-carousel">${itens.map(a => cidCard(a)).join('')}</div>
    <button type="button" class="opt cid-cta" data-go="lupa">Ver os ${data.total} alertas</button>
  </section>`;
}

/* ---------- Aba "Alertas" ---------- */
function cidLupaKey() { const l = cid.lupa; return `tipo=${l.tipo}&cargo=${l.cargo}`; }
function cidLoadLupa(more) {
  const l = cid.lupa, key = cidLupaKey();
  if (!more && l.key === key) return;
  if (!more) { l.key = key; l.page = 1; l.itens = []; l.total = null; }
  l.loading = true; l.erro = null;
  const qs = `/api/c/radar?pageSize=12&page=${l.page}&tipo=${l.tipo}${l.cargo ? '&cargo=' + l.cargo : ''}`;
  cidGet(qs).then(d => { if (l.key !== key) return; l.itens = l.itens.concat(d.itens); l.total = d.total; l.contagem = d.contagem; l.loading = false; if (state.view === 'lupa') rerender(); })
    .catch(e => { if (l.key !== key) return; l.loading = false; l.erro = cidErroMsg(e); if (state.view === 'lupa') rerender(); });
}
const CID_TOP = '/api/c/politicos?pageSize=5&page=1&ordem=alertas';
function cidLoadTop() {
  if (cid.cache.has(CID_TOP) || cid.pending.has(CID_TOP)) return;
  cid.pending.add(CID_TOP);
  cidGet(CID_TOP).then(() => { if (state.view === 'lupa') rerender(); }).catch(() => cid.cache.set(CID_TOP, { itens: [] }));
}
function cidLupaHero() {
  const l = cid.lupa, c = l.contagem, top = (cid.cache.get(CID_TOP)?.itens || []).filter(x => x.alertas);
  const pico = c?.pico || 0, forn = c?.fornecedor || 0, tot = pico + forn;
  return `<section class="card hero">
    <span class="k">Alertas em 2026</span>
    <div class="huge">${c ? tot.toLocaleString('pt-BR') : '—'}</div>
    <span class="muted">gastos fora do normal para conferir. Fora do normal não quer dizer irregular.</span>
    ${tot ? `<div class="stack" role="img" aria-label="${pico} picos num mês e ${forn} concentrações numa empresa"><i style="width:${pico / tot * 100}%;background:var(--accent-2)"></i><i style="width:${forn / tot * 100}%;background:var(--hero-fg)"></i></div>
    <div class="legend" style="color:var(--hero-muted)"><span><i style="background:var(--accent-2)"></i>Gastou muito num mês · ${pico}</span><span><i style="background:var(--hero-fg)"></i>Uma empresa só · ${forn}</span></div>` : ''}
    ${top.length ? `<span class="k" style="margin-top:6px">Quem mais aparece</span>
    <div class="faces cid-top5">${top.map(x => `<button type="button" class="face" data-pol="${esc(x.id)}">${cidAvatar(x, 54)}<span>${esc(cidNome(x.name).split(' ')[0])}</span><em>${x.alertas} ${x.alertas === 1 ? 'ALERTA' : 'ALERTAS'}</em></button>`).join('')}</div>` : ''}
  </section>`;
}
function vLupa() {
  const l = cid.lupa; cidLoadLupa(false); cidLoadTop();
  const tipos = [['pico,fornecedor', 'Tudo'], ['pico', 'Gastou muito num mês'], ['fornecedor', 'Uma empresa só']];
  const cargos = [['', 'Todos'], ['deputado', 'Deputados(as)'], ['senador', 'Senadores(as)']];
  return `${pageHead('Fiscalize em 1 minuto', 'Alertas', 'Cada cartão é um gasto fora do normal na cota de um(a) deputado(a) ou senador(a). Toque para ver de quem é e conferir.')}
    ${cidLupaHero()}
    <div class="cid-filters">
      <div class="chips" role="group" aria-label="Tipo de alerta">${tipos.map(([k, n]) => `<button type="button" class="fchip" data-lupa-tipo="${k}" aria-pressed="${l.tipo === k}">${n}</button>`).join('')}</div>
      <div class="chips" role="group" aria-label="Cargo">${cargos.map(([k, n]) => `<button type="button" class="fchip" data-lupa-cargo="${k}" aria-pressed="${l.cargo === k}">${n}</button>`).join('')}</div>
    </div>
    ${l.erro ? `<section class="card"><p>Não deu para carregar os alertas agora.</p><p class="muted">${esc(l.erro)}</p><button type="button" class="more" data-lupa-retry>Tentar de novo</button></section>` : ''}
    ${l.total !== null ? `<span class="muted" role="status">${l.total} ${l.total === 1 ? 'alerta' : 'alertas'} neste filtro</span>` : ''}
    ${l.itens.map(a => cidCard(a)).join('')}
    ${l.loading && !l.erro ? skel('alerta', l.itens.length ? 1 : 3) : l.total !== null && l.itens.length < l.total ? `<button type="button" class="opt cid-more" data-lupa-more>Mostrar mais</button>` : ''}
    <section class="card cid-how"><span class="k">Como funciona</span>
      <p><b>Gastou muito num mês:</b> o gasto do mês passou de 1,75 vez o normal dos meses anteriores.</p>
      <p><b>Uma empresa só:</b> metade ou mais do dinheiro do ano foi para a mesma empresa.</p>
      <p class="muted">Pode ter explicação, como um evento no estado ou um contrato fixo. Os dados vêm das notas que a Câmara e o Senado publicam; as passagens aéreas da Câmara não entram nessa conta.</p>
    </section>
    ${advLink('data-public-go="radar"')}`;
}

/* ---------- Aba "Políticos" ---------- */
function cidLoadPol(more) {
  const p = cid.pol, key = `q=${p.q}&cargo=${p.cargo}&ordem=${p.ordem}`;
  if (!more && p.key === key) return;
  if (!more) { p.key = key; p.page = 1; p.itens = []; p.total = null; }
  p.loading = true; p.erro = null;
  const qs = `/api/c/politicos?pageSize=25&page=${p.page}&ordem=${p.ordem}${p.cargo ? '&cargo=' + p.cargo : ''}${p.q ? '&q=' + encodeURIComponent(p.q) : ''}`;
  cidGet(qs).then(d => { if (p.key !== key) return; p.itens = p.itens.concat(d.itens); p.total = d.total; p.medias = d.medias; p.cobertura = d.cobertura; p.loading = false; if (['politicos', 'deputados'].includes(state.view)) cidRenderPolList(); })
    .catch(e => { if (p.key !== key) return; p.loading = false; p.erro = cidErroMsg(e); if (['politicos', 'deputados'].includes(state.view)) cidRenderPolList(); });
}
function cidPolRow(x, max) {
  const hasExpenseData = x.hasExpenseData === undefined ? x.gasto != null : Boolean(x.hasExpenseData);
  const media = cid.pol.medias?.[x.role]?.media, acima = hasExpenseData && media && x.gasto > media * 1.25;
  const cargo = x.role === 'senador' ? 'Senador(a)' : 'Deputado(a)';
  const barWidth = hasExpenseData && x.gasto > 0 ? Math.max(2, x.gasto / max * 100) : 0;
  const gasto = hasExpenseData ? (x.gasto === 0 ? 'R$ 0' : cidMil(x.gasto)) : 'Sem dados';
  return `<button type="button" class="cid-row" data-pol="${esc(x.id)}">${cidAvatar(x, 48)}<span class="cid-rowtxt"><b>${esc(cidNome(x.name))}</b><small>${[cargo, x.party, x.uf].filter(Boolean).map(esc).join(' · ')}</small>
      <span class="cid-rowbar"><i style="width:${barWidth}%" class="${acima ? 'hi' : ''}"></i></span></span>
    <span class="cid-rowval"><b class="mono">${gasto}</b>${x.alertas ? `<span class="cid-chip alto cid-mini"><i></i>${x.alertas} ${x.alertas === 1 ? 'alerta' : 'alertas'}</span>` : `<small>${hasExpenseData ? acima ? 'acima da média' : 'na cota' : 'sem despesa observada'}</small>`}</span></button>`;
}
function cidPolCoverageHTML(cobertura) {
  if (!cobertura) return skL('260px', 14);
  const deputados = cobertura.deputado, senadores = cobertura.senador;
  if (![deputados?.count, deputados?.withExpenses, senadores?.count, senadores?.withExpenses].every(Number.isFinite)) return 'Cobertura da lista indisponível.';
  return `<b>${deputados.count} deputados(as)</b> · <b>${senadores.count} registros do Senado</b>`;
}
function cidPolCoverageNotesHTML(cobertura) {
  if (!cobertura) return '';
  const deputados = cobertura.deputado, senadores = cobertura.senador;
  if (![deputados?.count, deputados?.withExpenses, senadores?.count, senadores?.withExpenses].every(Number.isFinite)) return '';
  const senado = senadores.count > 81
    ? '<p class="muted">O Senado tem 81 cadeiras; registros extras no retrato da fonte podem refletir suplentes em transição.</p>'
    : '';
  return `<details class="card"><summary><b>Sobre estes dados</b></summary>
    <p class="muted">Despesas observadas para ${deputados.withExpenses} de ${deputados.count} deputados(as) e ${senadores.withExpenses} de ${senadores.count} senadores(as).</p>${senado}
  </details>`;
}
function cidPolListHTML() {
  const p = cid.pol;
  if (p.erro) return `<section class="card"><p>Não deu para carregar a lista agora.</p><p class="muted">${esc(p.erro)}</p><button type="button" class="more" data-pol-retry>Tentar de novo</button></section>`;
  if (!p.itens.length && p.loading) return skel('lista', 8);
  if (!p.itens.length) return `<section class="card"><p>Ninguém encontrado com “${esc(p.q)}”.</p><p class="muted">Tente só o sobrenome, a sigla do partido (PT, PL…) ou do estado (SP, MG…).</p></section>`;
  const gastosObservados = p.itens.filter(x => x.gasto != null).map(x => x.gasto);
  const max = Math.max(1, ...gastosObservados, ...Object.values(p.medias || {}).map(m => (m.media || 0) * 1.5));
  return `<span class="muted" role="status">${p.total} ${p.total === 1 ? 'pessoa' : 'pessoas'} · valor gasto da cota em 2026</span><section class="card cid-list">${p.itens.map(x => cidPolRow(x, max)).join('')}</section>
    ${p.loading ? skel('lista', 3) : p.itens.length < p.total ? '<button type="button" class="opt cid-more" data-pol-more>Mostrar mais</button>' : ''}`;
}
function cidRenderPolList() {
  const resumo = document.getElementById('cid-pol-summary');
  if (resumo) resumo.innerHTML = cidPolCoverageHTML(cid.pol.cobertura);
  const notas = document.getElementById('cid-pol-notes');
  if (notas) notas.innerHTML = cidPolCoverageNotesHTML(cid.pol.cobertura);
  const el = document.getElementById('cid-pol-list');
  if (el) el.innerHTML = cidPolListHTML();
}
function vPoliticos() {
  const p = cid.pol; cidLoadPol(false);
  return `${pageHead('Deputados(as) e senadores(as)', 'Políticos', 'Busque qualquer um(a) e veja quanto gastou da cota em 2026, com os alertas.')}
    <div id="cid-pol-summary" class="cid-roster-summary" role="status">${cidPolCoverageHTML(p.cobertura)}</div>
    <label class="search" for="cid-busca"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="cid-busca" type="search" placeholder="Nome, partido ou estado" value="${esc(p.q)}" autocomplete="off"></label>
    <div class="cid-filters">
      <div class="chips" role="group" aria-label="Cargo">${[['', 'Todos'], ['deputado', 'Deputados(as)'], ['senador', 'Senadores(as)']].map(([k, n]) => `<button type="button" class="fchip" data-pol-cargo="${k}" aria-pressed="${p.cargo === k}">${n}</button>`).join('')}</div>
      <div class="chips" role="group" aria-label="Ordenar">${[['nome', 'A–Z'], ['gasto', 'Quem mais gastou'], ['alertas', 'Mais alertas']].map(([k, n]) => `<button type="button" class="fchip" data-pol-ordem="${k}" aria-pressed="${p.ordem === k}">${n}</button>`).join('')}</div>
    </div>
    <div class="cid-actions"><button type="button" class="fchip" data-cmp-start="">Comparar dois(duas) lado a lado →</button><button type="button" class="fchip" data-go="partidos">Comparar partidos →</button><button type="button" class="fchip" data-go="presenca">Presença dos deputados →</button></div>
    <div id="cid-pol-list" class="cid-stack" aria-live="polite">${cidPolListHTML()}</div>
    <div id="cid-pol-notes">${cidPolCoverageNotesHTML(p.cobertura)}</div>
    <span class="src">Valor: quanto cada um(a) gastou da cota em 2026, pelas notas publicadas. Não é salário. A barra roxa mais forte indica gasto acima da média.</span>
    ${advLink('data-public-go="autoridades"', 'Busca avançada: ministros(as), juízes(as) e servidores(as)')}`;
}

/* ---------- Ficha leve (qualquer deputado ou senador) ---------- */
function cidLoadFicha(id) {
  if (cid.fichaId === id) return;
  cid.fichaId = id; cid.ficha = null; cid.fichaErro = null; cid.fichaLoading = true;
  cidGet('/api/c/politico/' + encodeURIComponent(id)).then(d => { if (cid.fichaId !== id) return; cid.ficha = d; cid.fichaLoading = false; if (state.view === 'politico') rerender(); })
    .catch(e => { if (cid.fichaId !== id) return; cid.fichaLoading = false; cid.fichaErro = cidErroMsg(e); if (state.view === 'politico') rerender(); });
}
function cidCustoResposta(f, p, hasExpenseData) {
  const media = f.media || 0, dif = media ? f.total / media - 1 : 0;
  const totalLabel = f.total === 0 ? '0' : Math.round(f.total / 1e3).toLocaleString('pt-BR') + ' mil';
  const verdict = Math.abs(dif) < 0.1 ? 'Parecido com a média' : `${Math.round(Math.abs(dif) * 100)}% ${dif > 0 ? 'acima' : 'abaixo'} da média`;
  return `<section class="card hero cid-answer" data-profile-answer="custo">
    <h2 class="h">Quanto custa?</h2><span class="k">Cota parlamentar · 2026</span>
    <div class="huge">${hasExpenseData ? `<small>R$</small>${totalLabel}` : 'Sem dados'}</div>
    <p class="cid-salary">Salário à parte: ${brl(PROFILE_SALARY[p.role].amount)}/mês</p>
    ${hasExpenseData ? (media ? `<div class="cid-vs">
      <div><span>${esc(cidNome(p.name).split(' ')[0])}</span><b class="mono">${f.total === 0 ? 'R$ 0' : cidMil(f.total)}</b></div><div class="cid-vsbar"><i style="width:${Math.min(100, f.total / Math.max(f.total, media) * 100)}%"></i></div>
      <div><span>Média dos(as) ${CARGO_PL[p.role] || 'colegas'}</span><b class="mono">${cidMil(media)}</b></div><div class="cid-vsbar avg"><i style="width:${Math.min(100, media / Math.max(f.total, media) * 100)}%"></i></div>
    </div><span class="fchip cid-verdict">${verdict}</span>` : '<p class="muted">Média do cargo indisponível neste recorte.</p>')
    : '<p class="muted">Nenhuma despesa de reembolso foi observada para este perfil no recorte importado. Ausência não significa gasto zero.</p>'}
  </section>`;
}
function cidTrabalhoResposta(shared) {
  const head = '<section class="card cid-answer" data-profile-answer="trabalho"><h2 class="h">Trabalha?</h2>';
  if (shared.pessoa.role === 'senador') return `${head}<span class="k">Presença e votos · Senado</span>
    <p class="cid-empty">Presença e votos do Senado ainda não foram coletados.</p><p class="muted">Sem dados para avaliar neste recorte.</p></section>`;
  const p = shared.presenca, rows = profilePresenceRows();
  const media = rows.length ? Math.round(rows.reduce((s, x) => s + x.presente / x.dias, 0) / rows.length * 100) : null;
  const percent = p ? Math.round(p.presente / p.dias * 100) : null;
  const votos = extVotosDe(shared.id), known = votos.filter(r => r.voto !== null);
  const presenceOnly = known.filter(r => ['Presente', 'Presidiu'].includes(r.voto)).length;
  const identified = known.filter(r => !['Presente', 'Presidiu'].includes(r.voto));
  const voted = identified.filter(r => r.voto !== 'Não votou').length;
  return `${head}<span class="k">Presença no Plenário · 2026</span>
    ${p ? `<div class="huge">${percent}<small>%</small></div>
      <p>${p.presente} de ${p.dias} dias${media !== null ? ` · média da Câmara: ${media}%` : ''}</p>
      ${extPresBar(p)}
      <div class="legend"><span><i style="background:var(--accent)"></i>Presente ${p.presente}</span><span><i style="background:var(--muted);opacity:.55"></i>Justificada ${p.justificadas}</span><span><i style="background:var(--warn)"></i>Falta ${p.falta}</span></div>`
      : '<p class="cid-empty">Presença sem registro importado.</p><p class="muted">Ausência de dado não significa zero presença.</p>'}
    <p class="cid-vote-count">${identified.length ? `Votou em <b>${voted} de ${votos.length}</b> votações do Placar` : presenceOnly ? 'Sem voto nominal identificado neste recorte.' : 'Sem registros individuais nas votações do Placar.'}</p>
    ${presenceOnly ? `<p class="muted">${presenceOnly} ${presenceOnly === 1 ? 'registro só de presença ou presidência' : 'registros só de presença ou presidência'}.</p>` : ''}
    ${p && media !== null ? `<span class="fchip cid-verdict">${percent === media ? 'Perto da média' : percent > media ? 'Acima da média' : 'Abaixo da média'}</span>` : ''}
  </section>`;
}
function cidAlertaResposta(alertas, hasExpenseData) {
  const ranks = { alto: 3, medio: 2, info: 1 };
  const top = [...alertas].sort((a, b) => (ranks[b.nivel] || 0) - (ranks[a.nivel] || 0))[0];
  return `<section class="card cid-answer cid-answer-alert" data-profile-answer="alerta">
    <h2 class="h">Tem algo estranho?</h2>
    ${top ? `<span class="fchip cid-alert-count">${alertas.length} ${alertas.length === 1 ? 'alerta' : 'alertas'}</span>
      <h3 class="cid-title">${esc(top.titulo)}</h3>${cidVisual(top)}<p class="cid-frase">${esc(top.frase)}</p>
      <button type="button" class="more" data-profile-open="alertas">${alertas.length > 1 ? `Ver os demais alertas (${alertas.length - 1})` : 'Ver alerta em detalhe'} →</button>`
    : `<p class="cid-empty">${hasExpenseData ? 'Nada fora do normal nas regras que checamos' : 'Sem dados de cota para checar alertas.'}</p>`}
  </section>`;
}
function cidVotosDetalhe(shared) {
  if (shared.pessoa.role === 'senador') return '<p class="muted">Votos nominais do Senado ainda não foram coletados.</p>';
  const votos = extVotosDe(shared.id), p = shared.presenca;
  return `<span class="k">Votações selecionadas do Placar · ${votos.length}</span>
    ${votos.length ? `<div class="votes">${votos.map(({ v, voto }) => {
      const label = voto == null ? 'Sem registro importado' : v.secreta ? 'Presença registrada · voto secreto' : String(voto).toLowerCase();
      return `<button type="button" class="vt" data-vote="${esc(v.id)}"><b>${esc(label)}</b><span>${esc(v.titulo)}</span></button>`;
    }).join('')}</div>` : '<p class="muted">Nenhuma votação selecionada do Placar em 2026.</p>'}
    <p class="muted">O resumo conta votos identificados na fonte. Presença em voto secreto e quem presidiu aparecem à parte. Ausência de registro não significa que a pessoa não votou.</p>
    ${p?.motivos?.length ? `<p class="note">Justificativas de presença: ${p.motivos.map(([k, n]) => `${esc(k.toLowerCase())} (${n})`).join(', ')}.</p>` : ''}
    <button type="button" class="more" data-go="presenca">Ver a presença de todos(as)</button>`;
}
function cidGastosDetalhe(f, hasExpenseData) {
  if (!hasExpenseData) return '<p class="muted">Não há lançamentos observados para calcular total, média, série mensal ou alertas.</p>';
  const maxMes = Math.max(1, ...f.meses.map(m => m.valor)), catTot = f.categorias.reduce((s, c) => s + c.valor, 0) || 1;
  return `<section class="cid-detail-part"><h3 class="k">Mês a mês</h3>
    <div class="cid-months">${f.meses.map(m => `<div><small>${Math.round(m.valor / 1e3)}k</small><b class="mt"><i style="height:${m.valor > 0 ? Math.max(2, m.valor / maxMes * 100) : 0}%" class="${f.alertas.some(a => a.tipo === 'pico' && a.mes === m.month) ? 'hot' : ''}"></i></b><span>${MES[m.month]}</span></div>`).join('')}</div>
    <p class="muted">Os últimos meses ainda podem crescer: as notas são publicadas com atraso.</p>
  </section>
  <section class="cid-detail-part"><h3 class="k">Com o que gastou</h3>
    ${f.categorias.slice(0, 6).map(c => `<div class="cid-bar"><div><span>${esc(c.nome)}</span><b class="mono">${c.valor === 0 ? 'R$ 0' : cidMil(c.valor)}</b></div><div class="bar"><i style="width:${f.categorias[0].valor ? c.valor / f.categorias[0].valor * 100 : 0}%"></i></div><small class="muted">${Math.round(c.valor / catTot * 100)}% do total</small></div>`).join('')}
  </section>
  <section class="cid-detail-part"><h3 class="k">Para quem foi o dinheiro</h3>
    ${f.fornecedores.map(x => `<div class="cid-bar"><div><span>${esc(cidNome(x.name))}</span><b class="mono">${cidMil(x.valor)}</b></div><div class="bar"><i style="width:${f.total ? x.valor / f.total * 100 : 0}%;background:${f.total && x.valor / f.total >= 0.5 ? 'var(--warn)' : 'var(--accent)'}"></i></div><small class="muted">${f.total ? Math.round(x.valor / f.total * 100) : 0}% do total · ${x.notas} ${x.notas === 1 ? 'nota' : 'notas'}</small></div>`).join('')}
  </section>
  <section class="cid-detail-part"><h3 class="k">Maiores notas do ano</h3>
    ${f.maiores.map(m => `<${m.documentUrl ? `a href="${esc(m.documentUrl)}" target="_blank" rel="noopener"` : 'div'} class="item"><span class="mono muted" style="width:52px">${MES[m.month]}/${String(m.year).slice(2)}</span><span class="g"><span>${esc(cidNome(m.fornecedor || 'Fornecedor não informado'))}</span><span class="muted">${esc(m.categoria)}${m.documentUrl ? ' · ver nota ↗' : ''}</span></span><span class="mono" style="font-weight:700">${brl(m.valor)}</span></${m.documentUrl ? 'a' : 'div'}>`).join('')}
  </section>`;
}
function vPolitico() {
  const id = state.pol;
  cidLoadFicha(id);
  const back = '<button type="button" class="back" data-back>‹ Voltar</button>';
  if (cid.fichaErro) return back + `<section class="card"><p>Não deu para abrir esta ficha.</p><p class="muted">${esc(cid.fichaErro)}</p></section>`;
  const f = cid.ficha;
  if (!f) return back + skel('ficha-respostas');
  const shared = profileData(f.pessoa || id), p = shared.pessoa;
  const hasExpenseData = f.hasExpenseData === undefined ? f.total != null : Boolean(f.hasExpenseData);
  const alertas = f.alertas || [], camara = p.role === 'deputado';
  const num = String(p.id).split(':')[1];
  const presenceUrl = camara && /^\d+$/.test(num || '') ? `https://www.camara.leg.br/deputados/${num}/presenca-plenario/2026` : null;
  const fontes = `<p>Cota é reembolso de gastos com o trabalho: escritório, divulgação, carro e viagens.</p>
    <p class="src">Fonte: notas da cota publicadas ${camara ? 'pela Câmara (sem as passagens aéreas, que ficam fora do arquivo aberto)' : 'pelo Senado'}. Retrato de ${f.snapshotAt ? esc(f.snapshotAt.slice(0, 10)) : 'data não informada'}.</p>
    ${camara ? `<p class="muted">Presença em sessões deliberativas de 2026. Média da Câmara: média das proporções individuais entre registros válidos. O selo compara os percentuais arredondados. Os dias observados podem variar entre mandatos.</p>
    ${presenceUrl ? `<a class="src" href="${esc(presenceUrl)}" target="_blank" rel="noopener">Fonte da presença no Plenário ↗</a>` : ''}
    <p class="muted">Os votos cobrem apenas a seleção do Placar em 2026. Cada votação abre seu resumo e fontes oficiais.</p>` : ''}
    <p class="muted">Alertas indicam registros para conferir, não conclusões de irregularidade. “Parecido com a média” mantém a faixa de diferença inferior a 10% na cota.</p>
    ${cidFonte(p) ? `<a class="fchip" href="${esc(cidFonte(p))}" target="_blank" rel="noopener">Página oficial ↗</a>` : ''}
    ${advLink(cidPublicAuthorityAttrs(p, shared.mandato), 'Busca avançada: todos os lançamentos')}`;
  return `${back}
    <div class="cid-profile-head"><div class="profile">${cidAvatar(p, 64)}<div><h1 class="n">${esc(cidNome(p.name))}</h1><span class="muted">${cidQuem(p)}</span></div></div>
      <button type="button" class="fchip" data-cmp-start="${esc(shared.id)}">Comparar com outro(a) →</button></div>
    <span class="k cid-answer-label">Em 3 respostas</span>
    <div class="cid-answers">${cidCustoResposta(f, p, hasExpenseData)}${cidTrabalhoResposta(shared)}${cidAlertaResposta(alertas, hasExpenseData)}</div>
    <h2 class="h">Ver mais</h2>
    ${profileSectionsHTML(p, {
      gastos: cidGastosDetalhe(f, hasExpenseData),
      alertas: alertas.length ? alertas.map(a => cidCard(a, { semPessoa: true })).join('') : `<p class="muted">${hasExpenseData ? 'Nada fora do normal nas regras que checamos: nenhum mês com gasto muito acima do normal e nenhuma empresa com metade do dinheiro.' : 'Sem dados de cota para checar alertas.'}</p>`,
      votos: cidVotosDetalhe(shared), fontes,
    })}`;
}

/* ---------- Eventos ---------- */
function cidOpenPol(id) {
  const canonical = String(id || '').includes(':') ? String(id) : 'camara:' + String(id || '');
  state.pol = canonical;
  state.dep = cidLocalId(canonical);
  go('politico');
}
document.addEventListener('click', e => {
  const t = e.target.closest('[data-profile-toggle],[data-profile-open],[data-pol],[data-home-retry],[data-lupa-tipo],[data-lupa-cargo],[data-lupa-more],[data-lupa-retry],[data-pol-cargo],[data-pol-ordem],[data-pol-more],[data-pol-retry]');
  if (!t) return;
  if (t.dataset.profileToggle) { profileToggle(t); return; }
  if (t.dataset.profileOpen) {
    const button = document.querySelector(`[data-profile-toggle="${t.dataset.profileOpen}"]`);
    if (button) { profileToggle(button, true); button.focus(); button.scrollIntoView({ block: 'start', behavior: 'instant' }); }
    return;
  }
  if (t.dataset.pol) { e.preventDefault(); cidOpenPol(t.dataset.pol); return; }
  if (t.hasAttribute('data-home-retry')) { const path = '/api/c/radar?pageSize=8&tipo=pico,fornecedor'; cid.cache.delete(path); cid.pending.delete(path); return rerender(); }
  const l = cid.lupa, p = cid.pol;
  if (t.dataset.lupaTipo !== undefined) { l.tipo = t.dataset.lupaTipo; return rerender(); }
  if (t.dataset.lupaCargo !== undefined) { l.cargo = t.dataset.lupaCargo; return rerender(); }
  if (t.hasAttribute('data-lupa-more')) { l.page += 1; cidLoadLupa(true); return rerender(); }
  if (t.hasAttribute('data-lupa-retry')) { l.key = ''; cid.cache.clear(); return rerender(); }
  if (t.dataset.polCargo !== undefined) { p.cargo = t.dataset.polCargo; return rerender(); }
  if (t.dataset.polOrdem !== undefined) { p.ordem = t.dataset.polOrdem; return rerender(); }
  if (t.hasAttribute('data-pol-more')) { p.page += 1; cidLoadPol(true); cidRenderPolList(); return; }
  if (t.hasAttribute('data-pol-retry')) { p.key = ''; cid.cache.clear(); return rerender(); }
});
let cidTimer = null;
document.addEventListener('input', e => {
  if (e.target.id !== 'cid-busca') return;
  clearTimeout(cidTimer);
  cid.pol.q = e.target.value.trim();
  cidTimer = setTimeout(() => { cidLoadPol(false); cidRenderPolList(); }, 250);
});
// Atualiza apenas os padrões responsivos; escolhas feitas nos acordeões são preservadas.
if (typeof matchMedia === 'function') {
  matchMedia('(min-width: 900px)').addEventListener('change', profileRefreshAccordions);
}
