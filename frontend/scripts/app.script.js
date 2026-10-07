const DATA = /*DATA*/null;
const G = DATA.geral, D = DATA.deputados, byId = Object.fromEntries(D.map(d => [d.id, d]));
const VOT = Object.fromEntries(DATA.votacoes.map(v => [v.id, v]));
const $app = document.getElementById('app');
const MES = ['', 'jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const brl = (v, d = 0) => 'R$ ' + v.toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const mi = v => (v / 1e6).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const mil = v => (v / 1e3).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
const pct = (a, b) => Math.round(a / b * 100);
const dmy = s => `${+s.slice(8, 10)}/${MES[+s.slice(5, 7)]}`;
const first = n => n.split(' ')[0];
const CATS = ['--cat1', '--cat2', '--cat3', '--cat4', '--cat5', '--cat6'];
const CATS_H = ['--cat1', '--hero-fg', '--cat3', '--cat4', '--cat5', '--cat6']; // em fundo escuro, o tom escuro some
const SALARIO = D[0].custo.salario;
const GAB_LIM = Math.round(D[0].custo.gabineteLimite / D[0].custo.gabineteMeses);
const custoMedio = D.reduce((s, d) => s + d.custo.mes, 0) / D.length;
// Jan–jul é o intervalo considerado fechado pela coleta fornecida.
const RADAR = SpendingAnalysis.analyze(D, { closedThrough: 7, year: 2026 });

const store = { get(k, f) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : f; } catch (e) { return f; } },
                set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
let state = { pfilter: 'todos', view: 'inicio', dep: null, vote: null, from: 'inicio', quiz: null, open: {}, q: '', plimit: 12, follow: store.get('nl-follow', []), spendingType: 'todos', spendingDep: 'todos', spendingSort: 'sinais', spendingMode: 'alertas' };

function res(e) {
  const s = e.situacao;
  if (s.startsWith('ELEITO')) return { t: e.cargo === 'Senador' ? 'ELEITO(A) AO SENADO' : 'REELEITO(A)', win: true };
  if (s === 'SUPLENTE') return { t: 'SUPLENTE', win: false };
  return { t: 'NÃO ELEITO(A)', win: false };
}
const voto = v => ({ 'Ausente': 'não votou', 'Artigo 17': 'presidiu', 'Obstrução': 'obstrução', 'Abstenção': 'abstenção' }[v] || v);
const pres = d => { const p = d.presenca; return { total: p.dias.length, ok: p.presente, just: p.justificadas, falta: p.naoJustificadas }; };
const grupoProj = s => s.includes('Norma Jurídica') ? 'lei' : /Arquivad|Retirad|Rejeitad|Prejudicad/.test(s) ? 'arquivado' : 'tramitando';
const motivos = d => { const c = {}; d.presenca.dias.filter(x => x.s !== 'Presença' && x.s !== 'Ausência').forEach(x => c[x.s] = (c[x.s] || 0) + 1); return Object.entries(c).sort((a, b) => b[1] - a[1]); };

/* Salário x Cota x Gabinete: o bloco que explica para onde vai o dinheiro de cada deputado */
function custoBloco(d, hero) {
  const c = d.custo;
  const parts = [
    { n: 'Salário', v: c.salario, cor: '--hero-fg', t: 'O que ele(a) ganha. Vai para o bolso dele(a). É igual para os(as) 513 deputados(as) (valor bruto, antes do imposto).' },
    { n: 'Cota parlamentar', v: c.cotaMes, cor: '--cat1', t: `Não é salário: paga despesas do trabalho, como passagens, combustível, escritório e divulgação. Média por mês; no ano já são ${brl(d.cota.total)}.` },
    { n: 'Verba de gabinete', v: c.gabineteMes, cor: '--cat3', t: `Paga o salário da equipe dele(a): ${c.pessoal ? c.pessoal.ativos + ' pessoas hoje' : 'os assessores'}. Média por mês; no ano já são ${brl(c.gabineteGasto)}.` },
  ];
  if (c.auxilioMoradia) parts.push({ n: 'Auxílio-moradia', v: c.auxilioMoradia / 9, cor: '--cat4', t: `Ajuda para morar em Brasília. Em 2026 recebeu ${brl(c.auxilioMoradia)} no total.` });
  const tot = parts.reduce((s, p) => s + p.v, 0);
  return `
    <span class="k">Quanto ele(a) custa por mês</span>
    <div class="huge"><small>R$</small>${mil(tot)} mil</div>
    <span class="muted">média de jan a jul de 2026 · cerca de ${Math.round(tot / SALARIO)} salários dele(a)</span>
    <div class="stack grow-x" role="img" aria-label="Divisão do custo mensal">${parts.map(p => `<i style="width:${p.v / tot * 100}%;background:var(${p.cor})"></i>`).join('')}</div>
    <div>${parts.map(p => `<div class="cost-row"><i style="background:var(${p.cor})"></i><b>${p.n}</b><span class="val">${brl(p.v)}</span><p>${p.t}</p></div>`).join('')}</div>
    <span class="muted">${c.imovelFuncional.startsWith('Faz uso') ? 'Também mora em apartamento da Câmara em Brasília (' + esc(c.imovelFuncional.toLowerCase()) + '). ' : ''}Não entram aqui: plano de saúde e outros benefícios sem valor publicado.</span>`;
}

/* ---------- HOJE ---------- */
function vHoje() {
  const cats = G.categorias, catTot = cats.reduce((s, c) => s + c.valor, 0);
  const quizOpts = ['Aluguel de carro', 'Divulgação', 'Escritório'];
  const answered = state.quiz !== null;
  const eleitos = D.filter(d => res(d.eleicao).win).length;
  const topMax = G.topGastos[0].valor;
  const ausente = [...D].sort((a, b) => pres(a).ok / pres(a).total - pres(b).ok / pres(b).total)[0], pa = pres(ausente), ma = motivos(ausente);
  return `
  <div class="top">${brandMark()}<span class="pill"><i></i>Última votação ${dmy(DATA.ultimaVotacao)}</span></div>

  <section class="card hero">
    <span class="k">Quanto custa um(a) deputado(a)</span>
    <div class="huge"><small>R$</small>${mil(custoMedio)} mil</div>
    <span class="muted">por mês, em média, entre os ${D.length} que acompanhamos. O salário é só ${pct(SALARIO, custoMedio)}% disso.</span>
    <div style="display:flex;flex-direction:column;gap:0">
      <div class="cost-row"><i style="background:var(--hero-fg)"></i><b>Salário</b><span class="val">${brl(SALARIO)}</span><p>O que ele(a) ganha. Igual para todos(as).</p></div>
      <div class="cost-row"><i style="background:var(--cat1)"></i><b>Cota parlamentar</b><span class="val">${mil(Math.min(...D.map(d => d.cota.limite / 10)))}–${mil(Math.max(...D.map(d => d.cota.limite / 10)))} mil</span><p>Despesas do trabalho: gasolina, escritório, passagens, divulgação. Limite mensal, muda conforme o estado.</p></div>
      <div class="cost-row"><i style="background:var(--cat3)"></i><b>Verba de gabinete</b><span class="val">até ~${mil(GAB_LIM)} mil</span><p>Salário da equipe de assessores.</p></div>
    </div>
    <button type="button" class="opt" data-go="politicos" style="justify-content:center">Ver quanto gasta cada um(a)</button>
  </section>

  ${extImpostoCard()}

  ${cidHomeCard()}

  <section class="card alarm">
    <span class="k">Quem menos foi às sessões</span>
    <div style="display:flex;align-items:center;gap:12px"><img src="${ausente.foto}" alt="" style="width:52px;height:52px;border-radius:26px;object-fit:cover;object-position:top">
      <div><div style="font-weight:700;font-size:17px">${esc(ausente.nome)}</div><div class="muted">${esc(ausente.partido)} · ${ausente.uf}</div></div></div>
    <div><span class="big">${pa.ok} de ${pa.total}</span> <span class="muted">dias com sessão de votação em 2026</span></div>
    <div class="dots" role="img" aria-label="${pa.ok} presenças em ${pa.total} dias">${ausente.presenca.dias.map(x => `<i class="${x.s === 'Presença' ? '' : x.s === 'Ausência' ? 'f' : 'j'}"></i>`).join('')}</div>
    <p style="margin:0;font-size:14px">${ma.length ? `Nos outros ${pa.just} dias a falta foi abonada como <b>“${esc(ma[0][0].toLowerCase())}”</b>. ` : ''}A página dele(a) lista <b>${ausente.presenca.viagensMissao} viagens oficiais</b> no ano. A Câmara não publica o que foi cada missão.</p>
    <div class="cid-actions"><button type="button" class="fchip" data-dep="${ausente.id}">Abrir a ficha</button><button type="button" class="fchip cid-cta" data-go="presenca">Ver presença dos deputados →</button></div>
  </section>

  <section class="card hero">
    <span class="k">Câmara · notas da cota em 2026, sem passagens aéreas</span>
    <div class="huge" style="font-size:clamp(40px,12vw,54px)"><small>R$</small>${mi(G.cotaTotal)} mi</div>
    <h2 class="h" style="font-size:21px">Com o que a Câmara mais gastou?</h2>
    <div class="opts">${quizOpts.map(o => {
      const c = cats.find(x => x.nome === o), right = o === cats[0].nome;
      return `<button type="button" class="opt" data-quiz="${esc(o)}" data-state="${!answered ? '' : right ? 'right' : 'wrong'}" ${answered ? 'disabled' : ''}><span>${o}</span><span>${answered ? 'R$ ' + mi(c.valor) + ' mi' : ''}</span></button>`; }).join('')}</div>
    ${answered ? `<p style="margin:0;font-size:14px">${state.quiz === cats[0].nome ? 'Acertou!' : 'Errou.'} Divulgação levou <b>${pct(cats[0].valor, catTot)}%</b>: vídeos, anúncios e posts dos(as) próprios(as) deputados(as).</p>` : ''}
    <div class="stack" role="img" aria-label="Divisão por categoria">${cats.map((c, i) => `<i style="width:${c.valor / catTot * 100}%;background:var(${CATS_H[i]})"></i>`).join('')}</div>
    <div class="legend" style="color:var(--hero-muted)">${cats.map((c, i) => `<span><i style="background:var(${CATS_H[i]})"></i>${c.nome} ${pct(c.valor, catTot)}%</span>`).join('')}</div>
  </section>

  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:6px"><h2 class="h">Placar da Câmara</h2><button class="more" data-go="votacoes">Ver tudo</button></div>
  <div class="carousel">${DATA.votacoes.map(cardVoto).join('')}</div>

  <section class="card hero">
    <span class="k">Urnas · 4/out</span>
    <h2 class="h">${eleitos} dos ${D.length} que acompanhamos se elegeram.</h2>
    <div class="faces">${D.map(d => { const r = res(d.eleicao); return `<button type="button" class="face" data-dep="${d.id}" data-r="${r.win ? 'win' : 'lose'}"><img src="${d.foto}" alt=""><span>${esc(first(d.nome))}</span><em>${r.t}</em></button>`; }).join('')}</div>
  </section>

  <section class="card">
    <span class="k">Quem mais gastou a cota em 2026</span>
    <div>${G.topGastos.map((t, i) => `<div class="who" style="${i ? '' : 'border-top:0'}">
      <img src="${t.foto}" alt=""><span class="n">${i + 1}. ${esc(t.nome)}</span><span class="v">${mil(t.valor)} mil</span>
      <span class="s">${esc(t.partido)} · ${t.uf}</span><span class="b"><i class="grow-x" style="width:${t.valor / topMax * 100}%"></i></span></div>`).join('')}</div>
    <span class="muted">Pelas notas do arquivo aberto, que não inclui passagens aéreas. Estados longe de Brasília têm limite maior.</span>
  </section>
  <span class="src">Câmara dos Deputados (dados abertos, arquivo da cota e páginas dos(as) deputados(as)) e TSE. Baixados em 6/out/2026.</span>`;
}

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
    <div class="party-grid">${v.partidos.map(partyRow).join('')}</div>
    <div class="legend"><span><i style="background:var(--accent)"></i>Sim</span><span><i style="background:var(--no)"></i>Não</span></div>
    <button type="button" class="more" data-go="partidos">Comparar dois partidos →</button>
  </section>`}
  ${DATA.votosCompletos?.[v.id] ? '' : `<section class="card">
    <span class="k">Os(as) deputados(as) que acompanhamos</span>
    <div>${D.map((d, i) => `<button type="button" class="who" data-dep="${d.id}" style="${i ? '' : 'border-top:0'}"><img src="${d.foto}" alt=""><span class="n">${esc(d.nome)}</span><span class="v">${v.secreta ? '—' : esc(voto(v.votos[d.id]))}</span><span class="s">${esc(d.partido)} · ${d.uf}</span></button>`).join('')}</div>
  </section>`}
  ${v.secreta ? '' : '<span class="muted">“Não votou” quer dizer que não registrou voto: pode ter faltado ou estar na sessão sem votar. “Presidiu” indica quem preside a Câmara, que só vota para desempatar.</span>'}
  <span class="src">Fonte: Câmara dos Deputados. O resumo foi escrito a partir do texto aprovado.</span>`;
}

/* ---------- PLACAR ---------- */
function vVotacoes() {
  const V = DATA.votacoes, apr = V.filter(v => v.aprovada).length;
  const ab = V.filter(v => !v.secreta).map(v => ({ v, gap: Math.abs(v.sim - v.nao) / Math.max(1, v.sim + v.nao) })).sort((a, b) => a.gap - b.gap)[0];
  const tot = V.reduce((s, v) => s + v.sim + v.nao, 0), sim = V.reduce((s, v) => s + v.sim, 0);
  return `${pageHead('Câmara · Plenário', 'Placar', 'Como os(as) deputados(as) votaram nas últimas propostas. Toque numa votação para entender o que muda.')}
  <section class="card hero">
    <span class="k">Últimas ${V.length} votações</span>
    <div class="huge">${apr}<small style="margin-left:6px">de ${V.length}</small></div>
    <span class="muted">foram aprovadas. A última votação foi em ${dmy(DATA.ultimaVotacao)}.</span>
    <div class="hero-split">
      <div><b class="mono">${pct(sim, tot)}%</b><span>dos votos foram “sim”</span></div>
      ${ab ? `<div><b class="mono">${ab.v.sim}×${ab.v.nao}</b><span>a mais apertada: ${esc(ab.v.titulo)}</span></div>` : ''}
    </div>
    <div class="stack grow-x" role="img" aria-label="Todos os votos: ${pct(sim, tot)}% sim"><i style="width:${sim / tot * 100}%;background:var(--accent-2)"></i><i style="width:${(tot - sim) / tot * 100}%;background:var(--hero-muted)"></i></div>
    <div class="legend" style="color:var(--hero-muted)"><span><i style="background:var(--accent-2)"></i>Sim · ${sim.toLocaleString('pt-BR')} votos</span><span><i style="background:var(--hero-muted)"></i>Não · ${(tot - sim).toLocaleString('pt-BR')}</span></div>
  </section>
  <div class="cid-actions"><button type="button" class="fchip" data-go="partidos">Comparar partidos →</button></div>
  ${V.map(cardVoto).join('')}
  <span class="src">Fonte: Câmara dos Deputados (dados abertos de votações do Plenário).</span>`;
}

/* ---------- DEPUTADOS ---------- */
function vDeputados() {
  const q = state.q.trim().toLowerCase();
  const list = D.filter(d => !q || (d.nome + ' ' + d.partido + ' ' + d.uf).toLowerCase().includes(q));
  const seg = list.filter(d => state.follow.includes(d.id)), out = list.filter(d => !state.follow.includes(d.id));
  const star = d => { const on = state.follow.includes(d.id); return `<button type="button" class="star" data-follow="${d.id}" aria-pressed="${on}" aria-label="${on ? 'Deixar de seguir' : 'Seguir'} ${esc(d.nome)}"><svg width="18" height="18" viewBox="0 0 24 24" fill="${on ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/></svg></button>`; };
  const row = d => `<div style="display:flex;align-items:center;gap:8px;border-top:1px solid var(--line)">
      <button type="button" class="who" data-dep="${d.id}" style="border-top:0;flex:1">
        <img src="${d.foto}" alt=""><span class="n">${esc(d.nome)}</span><span class="v" style="font-size:13px">${mil(d.custo.mes)} mil/mês</span>
        <span class="s">${esc(d.partido)} · ${d.uf} · ${res(d.eleicao).t.toLowerCase()}</span></button>${star(d)}</div>`;
  return `<h1 class="h" style="font-size:30px">Deputados(as)</h1>
  <label class="search" for="busca"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="busca" type="search" placeholder="Nome, partido ou estado" value="${esc(state.q)}" autocomplete="off"></label>
  ${seg.length ? `<section class="card" style="padding-block:8px 4px"><span class="k" style="padding-top:8px">Seguindo</span><div>${seg.map(row).join('')}</div></section>` : ''}
  <section class="card" style="padding-block:8px 4px"><span class="k" style="padding-top:8px">${seg.length ? 'Outros' : 'Toque na estrela para seguir'}</span><div>${out.map(row).join('') || '<p class="muted">Ninguém com esse nome por aqui ainda.</p>'}</div></section>
  <span class="src">Nesta versão de teste, 10 deputados(as) de partidos e estados diferentes. O valor ao lado é quanto cada um(a) custa por mês.</span>`;
}

function vFicha() {
  const d = byId[state.dep], p = pres(d), c = d.cota, r = res(d.eleicao), mot = motivos(d);
  const presP = pct(p.ok, p.total), gov = d.governo.total >= 20 ? pct(d.governo.ok, d.governo.total) : null;
  const ctot = c.total || 1, top3 = c.categorias.slice(0, 3), rest = ctot - top3.reduce((s, x) => s + x.valor, 0);
  const segs = [...top3, ...(rest > 1 ? [{ nome: 'Outros', valor: rest }] : [])];
  const following = state.follow.includes(d.id), low = presP < 50;
  const plist = d.projetos.lista, showP = state.open['p' + d.id];
  return `<button type="button" class="back" data-back>‹ Voltar</button>
  <div class="profile"><img src="${d.foto}" alt="Foto oficial de ${esc(d.nome)}"><div style="display:flex;flex-direction:column;gap:4px;min-width:0;flex:1">
    <span class="n">${esc(d.nome)}</span><span class="muted">${esc(d.partido)} · ${d.uf}</span><span class="badge">${r.t} · ${d.eleicao.votos.toLocaleString('pt-BR')} votos</span></div>
    <button type="button" class="star" data-follow="${d.id}" aria-pressed="${following}" aria-label="${following ? 'Deixar de seguir' : 'Seguir'}"><svg width="18" height="18" viewBox="0 0 24 24" fill="${following ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/></svg></button>
    <button type="button" class="star dl-only" data-pdf="${d.id}" aria-label="Compartilhar relatório em PDF"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg></button></div>
  <div class="cid-actions"><button type="button" class="fchip" data-cmp-start="camara:${d.id}">Comparar com outro(a) →</button></div>
  ${d.nota ? `<p class="note">${esc(d.nota)}</p>` : ''}

  <section class="card hero">${custoBloco(d)}</section>

  <section class="card radar-intro">
    <span class="k">Gastos para conferir</span>
    <h2 class="h">${RADAR.alerts.filter(a => a.depId === d.id).length} sinais para conferir</h2>
    <p class="radar-note">Evolução mensal, concentração por categoria e notas de valor alto. Cada sinal traz o critério usado.</p>
    <button type="button" class="more" data-spending-detail="${d.id}">Investigar os gastos</button>
  </section>

  <section class="card ${low ? 'alarm' : ''}">
    <div style="display:flex;justify-content:space-between;align-items:baseline"><span class="k">Presença nas sessões de votação</span><span class="muted">2026</span></div>
    <div><span class="big">${p.ok}/${p.total}</span> <span class="muted">dias · média dos 10: ${Math.round(D.reduce((s, x) => s + pres(x).ok / pres(x).total, 0) / D.length * 100)}%</span></div>
    <div class="dots" role="img" aria-label="${p.ok} presenças em ${p.total} dias">${d.presenca.dias.map(x => `<i class="${x.s === 'Presença' ? '' : x.s === 'Ausência' ? 'f' : 'j'}" title="${dmy(x.d)}: ${esc(x.s)}"></i>`).join('')}</div>
    <div class="legend"><span><i style="background:var(--ink)"></i>Presente ${p.ok}</span><span><i style="background:var(--muted);opacity:.55"></i>Falta justificada ${p.just}</span><span><i style="background:var(--warn)"></i>Falta ${p.falta}</span></div>
    ${mot.length ? `<p class="note">Justificativas: ${mot.map(([k, n]) => `${esc(k.toLowerCase())} (${n})`).join(', ')}. ${low ? `A página dele(a) lista ${d.presenca.viagensMissao} viagens oficiais no ano.` : ''}</p>` : ''}
    <button type="button" class="more" data-go="presenca">Ver a presença de todos(as)</button>
  </section>

  <section class="card">
    <span class="k">Como votou · toque para entender</span>
    <div class="votes">${DATA.votacoes.map(v => `<button type="button" class="vt" data-vote="${v.id}"><b>${v.secreta ? 'voto secreto' : esc(voto(v.votos[d.id]))}</b><span>${esc(v.titulo)}</span></button>`).join('')}</div>
    <div class="note">${gov === null ? 'Votou poucas vezes no ano para medir o alinhamento com o governo.' : `Votou como o governo orientou em <b>${gov}%</b> das ${d.governo.total} votações nominais. A média da Câmara é ${Math.round(G.govMedia)}%.`}</div>
  </section>

  <section class="card">
    <div style="display:flex;justify-content:space-between;align-items:baseline"><span class="k">Cota parlamentar 2026</span><span class="muted">usou ${pct(c.total, c.limite)}% do limite</span></div>
    <div><span class="big">${brl(c.total)}</span> <span class="muted">de jan até agora</span></div>
    <span class="muted">Dá uma média de <b>${brl(d.custo.cotaMes)} por mês</b>, o valor que aparece em “quanto ele(a) custa”.</span>
    <div class="stack grow-x" role="img" aria-label="Divisão dos gastos">${segs.map((x, i) => `<i style="width:${x.valor / ctot * 100}%;background:var(${CATS[i]})"></i>`).join('')}</div>
    <div class="legend">${segs.map((x, i) => `<span><i style="background:var(${CATS[i]})"></i>${esc(x.nome)} ${pct(x.valor, ctot)}%</span>`).join('')}</div>
    <span class="muted">As passagens aéreas vêm do site da Câmara: elas não estão no arquivo aberto de notas de 2026.</span>
    ${state.open['n' + d.id] ? `<div>${c.lancamentos.map(l => `<a class="item" href="${esc(l.url)}" target="_blank" rel="noopener"><span class="mono muted" style="width:44px">${dmy(l.data)}</span><span class="g"><span>${esc(l.fornecedor)}</span><span class="muted">${esc(l.cat)}</span></span><span class="mono" style="font-weight:600">${brl(l.valor, 2)}</span></a>`).join('')}</div>` :
      `<button type="button" class="more" data-open="n${d.id}">Ver as últimas notas fiscais</button>`}
  </section>


  <section class="card">
    <span class="k">Fale com ele(a)</span>
    ${[['E-mail institucional', d.contato.email], ['Telefone do gabinete', d.contato.telefone]].filter(x => x[1]).map(([l, v]) => `<div class="contact"><span class="muted">${l}</span><span class="cv" id="c-${l.length}">${esc(v)}</span><button type="button" class="fchip" data-copy="${esc(v)}">Copiar</button></div>`).join('')}
    <div class="contact"><span class="muted">Endereço do gabinete</span><span class="cv">${esc(d.contato.endereco)}<br><span class="muted">${esc(d.contato.cidade)}</span></span></div>
    <div style="display:flex;flex-direction:column;gap:8px"><span class="muted">Redes sociais</span>
      ${d.contato.redes.length ? `<div class="chips">${d.contato.redes.map(r => `<a class="fchip" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.nome)}</a>`).join('')}</div>` : '<span style="font-size:14px">Nenhuma rede social cadastrada na Câmara.</span>'}</div>
  </section>
  <section class="card">
    <span class="k">Projetos apresentados desde 2023</span>
    <div class="row2" style="gap:6px">
      <div><span class="big" style="font-size:26px;color:var(--accent)">${d.projetos.lei}</span><div class="muted">viraram lei</div></div>
      <div><span class="big" style="font-size:26px">${d.projetos.tramitando}</span><div class="muted">tramitando</div></div>
      <div><span class="big" style="font-size:26px">${d.projetos.encerrado}</span><div class="muted">arquivados</div></div>
    </div>
    ${showP ? `<div class="chips" role="group" aria-label="Filtrar projetos">${[['todos', 'Todos', plist.length], ['lei', 'Viraram lei', d.projetos.lei], ['tramitando', 'Tramitando', d.projetos.tramitando], ['arquivado', 'Arquivados', d.projetos.encerrado]].map(([k, n, q]) => `<button type="button" class="fchip" data-pf="${k}" aria-pressed="${state.pfilter === k}">${n} <b>${q}</b></button>`).join('')}</div>
      <div>${(fl => fl.length ? fl.slice(0, state.plimit).map(x => { const lei = x.s.includes('Norma Jurídica'); return `<a class="proj" href="https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=${x.id}" target="_blank" rel="noopener"><b>${esc(x.t)}</b><span class="e">${esc(x.e)}</span><span class="st ${lei ? 'lei' : ''}">${lei ? 'Virou lei' : esc(x.s || 'Sem situação informada')}</span></a>`; }).join('') + (fl.length > state.plimit ? `<button type="button" class="more" data-pmore>Mostrar mais (${fl.length - state.plimit})</button>` : '') : '<p class="muted">Nenhum projeto nesse filtro.</p>')(plist.filter(x => state.pfilter === 'todos' || grupoProj(x.s) === state.pfilter))}</div>` :
      `<button type="button" class="more" data-open="p${d.id}">Ver os ${plist.length} projetos</button>`}
  </section>
  <section class="card hero dl-only" style="align-items:stretch">
    <span class="k">Relatório completo</span>
    <h2 class="h" style="font-size:21px">Leve tudo isso num PDF para mandar no grupo.</h2>
    <button type="button" class="opt" data-pdf="${d.id}" style="justify-content:center">Baixar e compartilhar o PDF</button>
    <span id="dl-msg" class="muted" role="status"></span>
  </section>
  <span class="src">Câmara dos Deputados (página oficial do(a) deputado(a), dados abertos e arquivo da cota) e TSE.</span>`;
}

function render() {
  const v = state.view;
  const html = { inicio: vHoje, base: vBasePublica, autoridades: vAutoridades, despesas: vDespesas, fornecedores: vFornecedores,
    fornecedor: vFornecedor, autoridade: vAutoridade, radar: vRadarPublico, cobertura: vCobertura, investigacoes: vInvestigacoes,
    hoje: vHoje, votacoes: vVotacoes, deputados: vDeputados, ficha: vFicha, votacao: vVotacao, gastos: vGastos, gasto: vGasto,
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
function go(view, keep) { if (!keep) hist.push({ view: state.view, dep: state.dep, vote: state.vote, pol: state.pol, y: window.scrollY, publicContext: state.publicContext }); state.view = view; render(); window.scrollTo(0, 0); }
function back() { const h = hist.pop() || { view: 'inicio', y: 0 }; Object.assign(state, { view: h.view, dep: h.dep, vote: h.vote, pol: h.pol }); if (h.publicContext) Object.assign(publicState, h.publicContext); render(); window.scrollTo(0, h.y || 0); }
const rerender = () => { const y = window.scrollY; render(); window.scrollTo(0, y); };

document.addEventListener('click', e => {
  const t = e.target.closest('[data-copy],[data-go],[data-dep],[data-quiz],[data-open],[data-follow],[data-vote],[data-back],[data-pmore],[data-pf],[data-spending-detail],[data-spending-type],[data-spending-mode],[data-export-alerts]');
  if (!t) return;
  if (t.dataset.spendingDetail) { goSpendingDetail(t.dataset.spendingDetail); return; }
  if (t.dataset.spendingType || t.dataset.spendingMode) {
    const key = t.dataset.spendingType ? 'spendingType' : 'spendingMode';
    state[key] = t.dataset[key]; rerender();
    document.querySelector(`[data-${key === 'spendingType' ? 'spending-type' : 'spending-mode'}="${state[key]}"]`)?.focus({ preventScroll: true });
    return;
  }
  if (t.hasAttribute('data-export-alerts')) { exportSpendingAlerts(); return; }
  if (t.dataset.copy) {
    const done = () => { t.textContent = 'Copiado'; setTimeout(() => { t.textContent = 'Copiar'; }, 1500); };
    const pick = () => { const r = document.createRange(); r.selectNodeContents(t.previousElementSibling); const s = getSelection(); s.removeAllRanges(); s.addRange(r); t.textContent = 'Selecionado'; };
    try { navigator.clipboard.writeText(t.dataset.copy).then(done, pick); } catch (err) { pick(); }
    return;
  }
  if (t.hasAttribute('data-back')) return back();
  if (t.hasAttribute('data-pmore')) { state.plimit += 20; return rerender(); }
  if (t.dataset.pf) { state.pfilter = t.dataset.pf; state.plimit = 12; return rerender(); }
  if (t.dataset.quiz) { state.quiz = t.dataset.quiz; return rerender(); }
  if (t.dataset.open) { state.open[t.dataset.open] = true; return rerender(); }
  if (t.dataset.follow) { const id = t.dataset.follow; state.follow = state.follow.includes(id) ? state.follow.filter(x => x !== id) : [...state.follow, id]; store.set('nl-follow', state.follow); return rerender(); }
  if (t.dataset.vote) { state.vote = t.dataset.vote; return go('votacao'); }
  if (t.dataset.dep) { state.dep = t.dataset.dep; state.plimit = 12; state.pfilter = 'todos'; return go('ficha'); }
  if (t.dataset.go) { hist.length = 0; go(t.dataset.go, true); }
});
document.addEventListener('change', e => {
  const key = { 'spending-dep': 'spendingDep', 'spending-sort': 'spendingSort' }[e.target.id];
  if (!key) return;
  const id = e.target.id; state[key] = e.target.value; rerender();
  document.getElementById(id)?.focus({ preventScroll: true });
});
document.addEventListener('input', e => {
  if (e.target.id !== 'busca') return;
  state.q = e.target.value; const pos = e.target.selectionStart; render();
  const i = document.getElementById('busca'); i.focus(); i.setSelectionRange(pos, pos);
});
initPublicData();
render();

/* ---------- Relatório em PDF (download padrão do navegador) ---------- */
document.documentElement.classList.add('can-dl');
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
function loadJsPDF() {
  if (window.jspdf) return Promise.resolve(window.jspdf.jsPDF);
  return new Promise((ok, fail) => {
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';
    s.onload = () => ok(window.jspdf.jsPDF); s.onerror = () => fail(new Error('jspdf'));
    document.head.appendChild(s);
  });
}
const pdfTxt = s => String(s).replace(/[“”]/g, '"').replace(/[‘’]/g, "'").replace(/—/g, '-');

async function relatorioPDF(d) {
  const jsPDF = await loadJsPDF();
  const doc = new jsPDF({ unit: 'mm', format: 'a4' });
  const W = 210, M = 16, CW = W - 2 * M; let y = 0;
  const INK = [17, 19, 24], MUT = [91, 96, 107], ACC = [91, 61, 245], LINE = [227, 229, 234], WARN = [184, 61, 10];
  const font = (sz, st = 'normal', c = INK) => { doc.setFont('helvetica', st); doc.setFontSize(sz); doc.setTextColor(...c); };
  const need = h => { if (y + h > 282) { doc.addPage(); y = 18; } };
  const para = (t, sz = 10, st = 'normal', c = INK, x = M, w = CW, lh = 4.6) => { font(sz, st, c); const ls = doc.splitTextToSize(pdfTxt(t), w); need(ls.length * lh); doc.text(ls, x, y); y += ls.length * lh; };
  const section = t => { y += 5; need(14); doc.setDrawColor(...LINE); doc.line(M, y, W - M, y); y += 7; font(8.5, 'bold', MUT); doc.text(pdfTxt(t.toUpperCase()), M, y, { charSpace: 0.4 }); y += 6; };
  const row = (l, v, sub) => { need(8); font(10.5, 'bold'); doc.text(pdfTxt(l), M, y); font(10.5, 'bold'); doc.text(pdfTxt(v), W - M, y, { align: 'right' }); y += 4.8; if (sub) para(sub, 9, 'normal', MUT, M, CW - 30, 4.2); y += 1.5; };
  const p = pres(d), c = d.custo, r = res(d.eleicao), mot = motivos(d);

  // Cabeçalho
  doc.setFillColor(...INK); doc.rect(0, 0, W, 22, 'F');
  font(17, 'bold', [255, 255, 255]); doc.text('Painel Público', M, 14);
  font(9, 'normal', [180, 184, 194]); doc.text(pdfTxt(`Relatório do(a) deputado(a) · dados de 6/out/2026`), W - M, 14, { align: 'right' });
  y = 32;
  try { doc.addImage(d.foto, 'JPEG', M, y - 2, 26, 26 * 1.25); } catch (e) {}
  const nx = M + 32;
  font(20, 'bold'); doc.text(pdfTxt(d.nome), nx, y + 5);
  font(11, 'normal', MUT); doc.text(pdfTxt(`${d.partido} · ${d.uf} · deputado(a) federal`), nx, y + 12);
  font(10.5, 'bold', ACC); doc.text(pdfTxt(`Eleição 2026: ${r.t} · ${d.eleicao.votos.toLocaleString('pt-BR')} votos`), nx, y + 19);
  y += 36;

  section('Quanto ele(a) custa por mês');
  font(26, 'bold'); doc.text(pdfTxt(brl(c.mes)), M, y + 4); font(9.5, 'normal', MUT); doc.text(pdfTxt('média de jan a jul de 2026'), M + 72, y + 4); y += 11;
  const parts = [['Salário', c.salario, 'O que ele(a) ganha. Vai para o bolso dele(a). Igual para os(as) 513 (bruto).'],
    ['Cota parlamentar', c.cotaMes, `Despesas do trabalho (passagens, combustível, escritório, divulgação). No ano: ${brl(d.cota.total)}.`],
    ['Verba de gabinete', c.gabineteMes, `Salário da equipe${c.pessoal ? ' (' + c.pessoal.ativos + ' pessoas hoje)' : ''}. No ano: ${brl(c.gabineteGasto)}.`]];
  if (c.auxilioMoradia) parts.push(['Auxílio-moradia', c.auxilioMoradia / 9, `Ajuda para morar em Brasília. Em 2026: ${brl(c.auxilioMoradia)}.`]);
  let bx = M; const cols = [INK, ACC, [142, 123, 255], MUT];
  parts.forEach(([, v], i) => { const w = v / c.mes * CW; doc.setFillColor(...cols[i]); doc.rect(bx, y, Math.max(w - 0.6, 0.5), 4, 'F'); bx += w; }); y += 9;
  parts.forEach(([l, v, s]) => row(l, brl(v), s));
  para(`Custo em 2026 até agora: ${brl(c.ano)} (salário de jan a set, cota até hoje, gabinete até jul). Não inclui plano de saúde nem benefícios sem valor publicado.${c.imovelFuncional.startsWith('Faz uso') ? ' Usa apartamento funcional da Câmara.' : ''}`, 9, 'normal', MUT);

  section('Presença nas sessões de votação em 2026');
  font(20, 'bold', pct(p.ok, p.total) < 50 ? WARN : INK); doc.text(`${p.ok}/${p.total}`, M, y + 4);
  font(10, 'normal', MUT); doc.text(pdfTxt(`dias presente · ${p.just} faltas justificadas · ${p.falta} faltas`), M + 30, y + 4); y += 9;
  const sq = 3.2, gap = 0.9; let sx = M;
  d.presenca.dias.forEach(x => { if (sx + sq > W - M) { sx = M; y += sq + gap; } doc.setFillColor(...(x.s === 'Presença' ? INK : x.s === 'Ausência' ? WARN : [190, 194, 202])); doc.rect(sx, y, sq, sq, 'F'); sx += sq + gap; });
  y += sq + 5;
  if (mot.length) para('Justificativas: ' + mot.map(([k, n]) => `${k.toLowerCase()} (${n})`).join(', ') + `. Viagens em missão oficial no ano: ${d.presenca.viagensMissao}.`, 9.5, 'normal', MUT);
  if (d.nota) para(d.nota, 9.5, 'normal', MUT);

  section('Como votou');
  DATA.votacoes.forEach(v => row(`${v.titulo}`, v.secreta ? 'voto secreto' : voto(v.votos[d.id]), `${v.proposicao} · ${dmy(v.data)} · placar ${v.sim} x ${v.nao} · ${v.curto}`));
  if (d.governo.total >= 20) para(`Votou como o governo orientou em ${pct(d.governo.ok, d.governo.total)}% das ${d.governo.total} votações nominais de 2026 (média da Câmara: ${Math.round(G.govMedia)}%).`, 9.5, 'normal', MUT);

  section('Cota parlamentar 2026');
  font(16, 'bold'); doc.text(pdfTxt(brl(d.cota.total)), M, y + 3); font(9.5, 'normal', MUT); doc.text(pdfTxt(`${pct(d.cota.total, d.cota.limite)}% do limite disponível no ano`), M + 50, y + 3); y += 8;
  d.cota.categorias.slice(0, 6).forEach(k => { need(7); font(9.5, 'normal'); doc.text(pdfTxt(k.nome), M, y); doc.text(pdfTxt(brl(k.valor, 2)), W - M, y, { align: 'right' }); doc.setFillColor(...LINE); doc.rect(M + 62, y - 2.6, 70, 2.6, 'F'); doc.setFillColor(...ACC); doc.rect(M + 62, y - 2.6, 70 * k.valor / d.cota.categorias[0].valor, 2.6, 'F'); y += 5.6; });

  section('Projetos apresentados desde 2023');
  para(`${d.projetos.total} projetos: ${d.projetos.lei} viraram lei, ${d.projetos.tramitando} tramitando, ${d.projetos.encerrado} arquivados.`, 10.5, 'bold');
  d.projetos.lista.filter(x => grupoProj(x.s) === 'lei').slice(0, 4).forEach(x => { y += 1; para(`Virou lei - ${x.t}: ${x.e}`, 9.5, 'normal', INK); });

  section('Contato');
  [['E-mail', d.contato.email], ['Telefone', d.contato.telefone], ['Gabinete', d.contato.endereco + ' - ' + d.contato.cidade]].filter(x => x[1]).forEach(([l, v]) => { need(6); font(9.5, 'bold'); doc.text(l, M, y); para(v, 9.5, 'normal', INK, M + 22, CW - 22); y += 1; });
  if (d.contato.redes.length) d.contato.redes.forEach(rd => { need(5); font(9.5, 'bold'); doc.text(pdfTxt(rd.nome), M, y); font(9.5, 'normal', ACC); doc.textWithLink(rd.url, M + 22, y, { url: rd.url }); y += 5; });

  y += 4; para('Fontes: Câmara dos Deputados (página oficial, dados abertos, arquivo da cota e consulta de passagens aéreas) e TSE. Os resumos de votação foram escritos a partir do texto aprovado.', 8, 'normal', MUT);
  const n = doc.getNumberOfPages();
  for (let i = 1; i <= n; i++) { doc.setPage(i); font(8, 'normal', MUT); doc.text(`Painel Público · ${i}/${n}`, W - M, 292, { align: 'right' }); }
  return doc.output('blob');
}

async function baixarRelatorio(btn, id) {
  const d = byId[id], msg = document.getElementById('dl-msg');
  const say = t => { if (msg) msg.textContent = t; };
  btn.disabled = true; const old = btn.innerHTML; btn.textContent = 'Gerando o PDF...'; say('');
  try {
    const blob = await relatorioPDF(d);
    const nome = 'painel-publico-' + d.nome.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-') + '.pdf';
    salvarArquivo(blob, nome);
    say('Download iniciado. Depois de salvar, é só compartilhar.');
  } catch (e) {
    const code = e && e.code;
    say(code === 'declined' ? 'Download cancelado.' : code === 'rate_limited' ? 'Já tem um download aberto. Tente de novo em instantes.' : e && e.message === 'jspdf' ? 'Não consegui carregar o gerador de PDF. Verifique a conexão.' : 'Não deu para gerar o relatório aqui.');
  } finally { btn.disabled = false; btn.innerHTML = old; }
}
document.addEventListener('click', e => { const b = e.target.closest('[data-pdf]'); if (b) baixarRelatorio(b, b.dataset.pdf); });
