const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/scripts/profile-data.js'), 'utf8');

function load(data = {}, { width = 390 } = {}) {
  const elements = new Map();
  const accordionButtons = [];
  const listeners = new Map();
  const viewport = { width };
  const media = query => ({ matches: query.includes('900') && viewport.width >= 900, addEventListener() {} });
  const context = {
    DATA: { deputados: [], votacoes: [], presencaTodos: [], ...data }, URL,
    innerWidth: width,
    window: { innerWidth: width, matchMedia: media },
    matchMedia: media,
    document: {
      documentElement: { clientWidth: width },
      addEventListener: (type, listener) => listeners.set(type, listener),
      getElementById: id => elements.get(id) || null,
      querySelectorAll: selector => selector.includes('.cid-detail-toggle') ? accordionButtons : [],
      _elements: elements,
      _accordionButtons: accordionButtons,
    },
    esc: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
  };
  context.__setWidth = next => { viewport.width = next; };
  context.__dispatch = (type, target) => listeners.get(type)?.({ target });
  vm.createContext(context); vm.runInContext(source, context);
  return context;
}

test('canonical identities use API and profile snapshots without editorial roster fallbacks', () => {
  const ctx = load({ perfis: { profiles: { 'camara:1': {
    name: 'Nome na coleta', uf: 'SP', contato: { email: 'dep@example.gov.br' },
  } } }, deputados: Array.from({ length: 12 }, (_, i) => ({ id: i + 1,
    nome: `Nome editorial ${i + 1}`, partido: 'PT', uf: 'SP', contato: { email: 'amostra@example.gov.br' },
    projetos: { lista: [{ id: i + 1 }] }, custo: { gabineteGasto: 1000 },
  })) });
  assert.equal(ctx.profileData(1).id, 'camara:1');
  assert.equal(ctx.profileData('camara:1').contato.email, 'dep@example.gov.br');
  assert.equal(ctx.profileData({ id: 'camara:1', name: 'Nome no cadastro' }).pessoa.name, 'Nome no cadastro');
  const outsideOldSample = ctx.profileData('camara:12');
  assert.equal(outsideOldSample.pessoa.name, undefined);
  assert.equal(outsideOldSample.pessoa.party, undefined);
  assert.equal(outsideOldSample.contato, null);
  assert.equal(outsideOldSample.projetos, null);
  assert.equal(outsideOldSample.gabinete, null);
  assert.equal('editorial' in outsideOldSample, false);
  assert.equal(ctx.profileData('senado:1').pessoa.role, 'senador');
});

test('presence rejects zero denominators and incoherent counts without manufacturing attendance', () => {
  const ctx = load({ presencaTodos: [
    { id: 1, dias: 10, presente: 8, falta: 1, justificadas: 1 },
    { id: 2, dias: 0, presente: 0, falta: 0, justificadas: 0 },
    { id: 3, dias: 10, presente: 11, falta: 0, justificadas: 0 },
  ] });
  assert.equal(ctx.profilePresence('camara:1').presente, 8);
  assert.equal(ctx.profilePresence('camara:2'), null);
  assert.equal(ctx.profilePresence('senado:1'), null);
  assert.equal(ctx.profilePresenceRows().length, 1);
});

test('missing vote rows never become absences and secret votes never reveal a choice', () => {
  const open = { id: 'v1' }, secret = { id: 'v2', secreta: true };
  const ctx = load({ votacoes: [open, secret], presencaTodos: [{ id: 2 }],
    votosCompletos: { v1: [[1, 'Pessoa', 'P', 'SP', 'Sim']], v2: [[1, 'Pessoa', 'P', 'SP', 'Não']] } });
  assert.equal(ctx.profileVoteRows(open).length, 1);
  assert.equal(ctx.profileVotes('camara:2')[0].voto, null);
  assert.equal(ctx.profileVotes('camara:1')[1].voto, 'Presente');
  assert.equal(ctx.profileVotes('senado:1').length, 0);
});

test('Senate activity loads once on demand and keeps identities and non-vote records distinct', async () => {
  const ctx = load({ senado: { sobDemanda: true }, presencaTodos: [{ id: 1, dias: 10, presente: 10, falta: 0, justificadas: 0 }] });
  let release;
  const calls = [];
  ctx.fetch = url => { calls.push(url); return new Promise(resolve => { release = resolve; }); };
  ctx.profileData('senado:1');
  ctx.profileData('senado:2');
  assert.equal(ctx.profileSenateLoading(), true);
  assert.deepEqual(calls, ['/api/c/senado/atividade']);
  release({ ok: true, json: async () => ({
    presenca: { status: 'unavailable', items: [] },
    votacoes: { items: ['Sim', 'Presente – Não registrou voto', 'Atividade parlamentar', 'Presidente (art. 51 RISF)'].map((vote, n) => ({
      id: `senado:${n}`, rows: [['senado:1', 'Senadora', 'PT', 'SP', vote]],
    })) },
  }) });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ctx.profileSenateLoading(), false);
  assert.equal(ctx.profilePresence('senado:1'), null);
  assert.deepEqual(Array.from(ctx.profileVotes('senado:1'), r => r.voto), ['Sim', 'Presente', 'Atividade parlamentar', 'Presidiu']);
  assert.ok(ctx.profileVotes('senado:2').every(r => r.voto === null));
  assert.equal(ctx.profileVotes('camara:1').length, 0);
  assert.equal(calls.length, 1);
});

test('failed Senate activity does not create attendance or vote counts', async () => {
  const ctx = load({ senado: { sobDemanda: true } });
  ctx.fetch = async () => ({ ok: false });
  ctx.profileData('senado:1');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ctx.profileSenateLoading(), false);
  assert.equal(ctx.profilePresence('senado:1'), null);
  assert.equal(ctx.profileVotes('senado:1').length, 0);
});

test('Senate secret votes are excluded even if a malformed snapshot contains a choice', () => {
  const ctx = load();
  assert.equal(ctx.profileVoteRows({ id: 'senado:1', secreta: true, rows: [['senado:1', 'Pessoa', 'PT', 'SP', 'Sim']] }).length, 0);
});

test('every legislative profile has explicit coverage for salary, staff, contact and projects', () => {
  const ctx = load();
  const html = ctx.profileSectionsHTML({ id: 'senado:9', role: 'senador' }, {
    gastos: '<p>Slot de gastos</p>', alertas: '<p>Slot de alertas</p>',
    votos: '<p>Slot de votos</p>', fontes: '<p>Slot de fontes</p>',
  });
  assert.match(html, /cid-details/);
  assert.match(html, /subsídio bruto mensal de referência do cargo/);
  assert.match(html, /Pagamento individual, descontos e outras verbas não foram importados/);
  assert.match(html, /Gastos com a equipe ainda não importados/);
  assert.match(html, /Não informado no recorte/);
  assert.match(html, /Projetos ainda não importados/);
  assert.doesNotMatch(html, /0 projetos|NaN|undefined/);
  assert.equal(ctx.profileSectionsHTML({ id: 'siape:9', role: 'servidor' }), '');
});

test('shared detail accordions keep their DOM order, accessible controls and responsive defaults', () => {
  const keys = ['gastos', 'alertas', 'votos', 'projetos', 'equipe', 'contato', 'mandato', 'fontes'];
  const slots = { gastos: '<p>Gastos</p>', alertas: '<p>Alertas</p>', votos: '<p>Votos</p>', fontes: '<p>Fontes</p>' };
  const mobile = load().profileSectionsHTML({ id: 'senado:9', role: 'senador' }, slots);
  const desktop = load({}, { width: 1024 }).profileSectionsHTML({ id: 'senado:9', role: 'senador' }, slots);
  const domKeys = html => [...html.matchAll(/data-profile-section=["']([^"']+)["']/g)].map(match => match[1]);
  assert.deepEqual(domKeys(mobile), keys);
  assert.deepEqual(domKeys(desktop), keys);
  assert.match(mobile, /<div class="cid-details[^"]*"/);

  for (const html of [mobile, desktop]) {
    for (const key of keys) {
      const section = html.match(new RegExp(`<section[^>]*data-profile-section=["']${key}["'][\\s\\S]*?<\\/section>`))?.[0];
      assert.ok(section, `section ${key} exists`);
      const button = section.match(/<button[^>]*data-profile-toggle=["'][^"']+["'][^>]*>/)?.[0];
      assert.ok(button, `${key} has a toggle button`);
      const panelId = button.match(/aria-controls=["']([^"']+)["']/)?.[1];
      assert.ok(panelId, `${key} toggle identifies its panel`);
      assert.match(section, new RegExp(`id=["']${panelId}["']`));
      assert.match(button, /aria-expanded=["'](?:true|false)["']/);
      const expanded = /aria-expanded=["']true["']/.test(button);
      const panel = section.match(new RegExp(`<[^>]+id=["']${panelId}["'][^>]*>`))?.[0];
      assert.ok(panel, `${key} panel exists`);
      assert.equal(/\shidden(?:[ =]|>)/.test(panel), !expanded, `${key} hidden state matches aria-expanded`);
    }
  }

  const expanded = html => Object.fromEntries([...html.matchAll(/<button[^>]*data-profile-toggle=["']([^"']+)["'][^>]*aria-expanded=["'](true|false)["']/g)]
    .map(match => [match[1], match[2] === 'true']));
  assert.deepEqual(expanded(mobile), Object.fromEntries(keys.map(key => [key, key === 'gastos'])));
  assert.deepEqual(expanded(desktop), Object.fromEntries(keys.map(key => [key, ['gastos', 'votos'].includes(key)])));
});

test('accordion choices update their panel and persist when the profile HTML is rendered again', () => {
  const ctx = load();
  const slots = { gastos: '<p>Gastos</p>', alertas: '<p>Alertas</p>', votos: '<p>Votos</p>', fontes: '<p>Fontes</p>' };
  const value = { id: 'camara:1', role: 'deputado' };
  const html = ctx.profileSectionsHTML(value, slots);
  const section = html.match(/<section[^>]*data-profile-section="alertas"[\s\S]*?<\/section>/)?.[0] || '';
  const tag = section.match(/<button[^>]*data-profile-toggle="alertas"[^>]*>/)?.[0] || '';
  const panelId = tag.match(/aria-controls="([^"]+)"/)?.[1];
  assert.ok(panelId);
  const panel = { hidden: true };
  ctx.document._elements.set(panelId, panel);
  const attrs = {
    'aria-expanded': tag.match(/aria-expanded="([^"]+)"/)?.[1],
    'aria-controls': panelId,
  };
  const button = {
    dataset: { profileToggle: 'alertas', profileId: 'camara:1' },
    getAttribute(name) {
      if (name === 'data-profile-toggle') return 'alertas';
      if (name === 'data-profile-id') return 'camara:1';
      return attrs[name] ?? null;
    },
    setAttribute(name, value) { attrs[name] = value; },
  };

  assert.equal(ctx.profileToggle(button), true);
  assert.equal(panel.hidden, false);
  let rerendered = ctx.profileSectionsHTML(value, slots);
  assert.match(rerendered, /data-profile-toggle="alertas"[^>]*aria-expanded="true"/);
  assert.doesNotMatch(rerendered.match(/<div class="cid-detail-body"[^>]*id="[^"]*alertas"[^>]*>/)?.[0] || '', / hidden/);

  assert.equal(ctx.profileToggle(button), false);
  assert.equal(panel.hidden, true);
  rerendered = ctx.profileSectionsHTML(value, slots);
  assert.match(rerendered, /data-profile-toggle="alertas"[^>]*aria-expanded="false"/);
});

test('responsive refresh applies defaults and preserves explicit accordion choices', () => {
  const ctx = load();
  const slots = { gastos: '<p>Gastos</p>', alertas: '<p>Alertas</p>', votos: '<p>Votos</p>', fontes: '<p>Fontes</p>' };
  const html = ctx.profileSectionsHTML({ id: 'camara:1', role: 'deputado' }, slots);
  const keys = ['gastos', 'alertas', 'votos', 'projetos', 'equipe', 'contato', 'fontes'];
  for (const key of keys) {
    const section = html.match(new RegExp(`<section[^>]*data-profile-section="${key}"[\\s\\S]*?<\\/section>`))?.[0] || '';
    const tag = section.match(/<button[^>]*>/)?.[0] || '';
    const button = makeButton(tag, key, 'camara:1', ctx.document._elements);
    ctx.document._accordionButtons.push(button);
  }
  const alertas = ctx.document._accordionButtons.find(button => button.dataset.profileToggle === 'alertas');
  const votos = ctx.document._accordionButtons.find(button => button.dataset.profileToggle === 'votos');
  ctx.profileToggle(alertas); // Explicitly open the mobile-collapsed section.
  ctx.profileToggle(votos);
  ctx.profileToggle(votos); // Explicitly keep desktop's default-open section closed.

  ctx.__setWidth(1024);
  ctx.profileRefreshAccordions();
  const current = Object.fromEntries(ctx.document._accordionButtons.map(button => [
    button.dataset.profileToggle,
    button.getAttribute('aria-expanded') === 'true',
  ]));
  assert.equal(current.gastos, true);
  assert.equal(current.projetos, false);
  assert.equal(current.alertas, true);
  assert.equal(current.votos, false);
  assert.equal(ctx.document._elements.get(alertas.getAttribute('aria-controls')).hidden, false);
  assert.equal(ctx.document._elements.get(votos.getAttribute('aria-controls')).hidden, true);
});

function makeButton(tag, key, profile, elements) {
  const attr = name => tag.match(new RegExp(`${name}="([^"]*)"`))?.[1] ?? null;
  const attrs = {
    'aria-expanded': attr('aria-expanded'),
    'aria-controls': attr('aria-controls'),
    'data-profile-toggle': key,
    'data-profile-id': profile,
    'data-profile-desktop-open': attr('data-profile-desktop-open'),
    'data-profile-mobile-open': attr('data-profile-mobile-open'),
  };
  const body = { hidden: tag.includes('aria-expanded="true"') ? false : true };
  elements.set(attrs['aria-controls'], body);
  return {
    dataset: { profileToggle: key, profileId: profile },
    getAttribute(name) { return attrs[name] ?? null; },
    setAttribute(name, value) { attrs[name] = value; },
  };
}

test('only a complete project collection supports an observed zero', () => {
  const ctx = load({ perfis: { profiles: {
    'camara:1': { projetos: { status: 'imported', total: 0, items: [] } },
    'camara:2': { projetos: { status: 'unavailable', total: 0, items: [] } },
  } } });
  assert.match(ctx.profileSectionsHTML('camara:1'), /0 projetos no recorte consultado/);
  assert.match(ctx.profileSectionsHTML('camara:1'), /Projetos apresentados · 0 projetos · situação não consultada/);
  assert.doesNotMatch(ctx.profileSectionsHTML('camara:2'), /0 projetos/);
});

test('missing project snapshot never presents a zero law count', () => {
  const html = load().profileSectionsHTML({ id: 'camara:99', role: 'deputado' });
  assert.match(html, /Projetos apresentados · total não confirmado · situação não consultada/);
  assert.doesNotMatch(html, /0 (?:virou|viraram) lei/);
  assert.match(html, /Projetos ainda não importados para este perfil/);
});

test('project situation groups need an explicit dated imported enum and counts each profile list entry', () => {
  const situation = (grupo, overrides = {}) => ({
    grupo, descricao: `Descrição ${grupo}`, consultadoEm: '2026-10-01T12:00:00Z',
    sourceUrl: 'https://fonte.example.test/projeto', status: 'imported', normas: [], detail: null,
    ...overrides,
  });
  const repeatedCoauthoredProject = { titulo: 'Projeto em coautoria', ementa: 'Ementa original', situacao: 'Aprovado e convertido',
    situacaoAtual: situation('lei'), url: 'https://projetos.example.test/1' };
  const items = [
    repeatedCoauthoredProject,
    { titulo: 'Em tramitação', ementa: 'Texto', situacao: 'Tramitando na comissão', situacaoAtual: situation('tramitando') },
    { titulo: 'Arquivado', ementa: 'Texto', situacaoAtual: situation('arquivado') },
    repeatedCoauthoredProject,
    { titulo: 'Enum não reconhecido', situacaoAtual: situation('lei falsa') },
    { titulo: 'Data ausente', situacaoAtual: situation('lei', { consultadoEm: null }) },
  ];
  const ctx = load({ perfis: { profiles: {
    'camara:1': { projetos: { status: 'partial', total: null, items } },
    'camara:2': { projetos: { status: 'partial', total: null, items: [items[1]] } },
  } } });
  const html = ctx.profileSectionsHTML('camara:1');
  assert.match(html, /6 projetos · 2 leis confirmadas · situação parcial/);
  assert.match(html, /Consulta registrada em 5 de 6 projetos; grupo confirmado em 4; 2 sem grupo confirmado \(1 sem consulta\)/);
  assert.equal((html.match(/data-project-item data-project-group="lei"/g) || []).length, 2);
  assert.equal((html.match(/data-project-item data-project-group="sem-situacao"/g) || []).length, 2);
  assert.match(html, /Descrição lei/);
  assert.doesNotMatch(html, /Aprovado e convertido/);
  assert.match(html, /Consulta da situação: 2026-10-01/);
  assert.match(html, /href="https:\/\/fonte\.example\.test\/projeto"[^>]*>Fonte da situação/);
  assert.match(html, /data-project-filter="arquivado"[^>]*>Arquivados\/rejeitados/);
  assert.match(html, /data-project-filter="sem-situacao"[^>]*>Outras \/ sem classificação/);
  assert.doesNotMatch(html, /Emendas promulgadas/);
  assert.match(html, /data-project-empty role="status" aria-live="polite" hidden>Nenhum projeto nesta situação neste recorte/);
  assert.doesNotMatch(html, /<a class="proj"/);
});

test('promulgated PECs are counted and filtered as amendments, outside the law count', () => {
  const ctx = load({ perfis: { profiles: { 'camara:1': { projetos: { status: 'partial', items: [
    { titulo: 'Projeto que virou lei', situacaoAtual: {
      grupo: 'lei', status: 'imported', consultadoEm: '2026-10-01T12:00:00Z', sourceUrl: 'https://fonte.example.test/lei',
    } },
    { titulo: 'PEC promulgada', situacao: 'Emenda constitucional promulgada', situacaoAtual: {
      grupo: 'emenda', status: 'imported', consultadoEm: '2026-10-01T12:00:00Z', sourceUrl: 'https://fonte.example.test/emenda',
      normas: [
        { tipo: 'EC', numero: '99', ano: 2026, url: 'https://normas.example.test/ec-99' },
        { tipo: 'EC', numero: '100', ano: 2026 },
        { tipo: 'EC', numero: '101', ano: 2026, url: 'urn:normas:ec-101' },
      ],
    } },
  ] } } } } });
  const html = ctx.profileSectionsHTML('camara:1');
  assert.match(html, /2 projetos · 1 virou lei · 1 emenda/);
  assert.match(html, /PEC aprovada e promulgada é emenda constitucional; por isso não entra na contagem de leis/);
  assert.match(html, /data-project-item data-project-group="emenda"/);
  assert.match(html, /data-project-filter="emenda"[^>]*>Emendas promulgadas/);
  assert.match(html, /href="https:\/\/normas\.example\.test\/ec-99"/);
  assert.match(html, /<span>EC 100 2026<\/span>/);
  assert.match(html, /<span>EC 101 2026<\/span>/);
  assert.doesNotMatch(html, /href="urn:/);
});

test('an imported consultation with no group stays unclassified, not unconsulted', () => {
  const ctx = load({ perfis: { profiles: { 'camara:1': { projetos: { status: 'partial', items: [{
    titulo: 'Proposição retirada', situacao: 'Texto legado de tramitação', situacaoAtual: {
      grupo: null, descricao: 'Proposição retirada da tramitação', status: 'imported',
      consultadoEm: '2026-10-02T09:30:00Z', sourceUrl: 'https://fonte.example.test/retirada',
      detail: '<script>Consulta antiga preservada</script>',
    },
  }] } } } } });
  const html = ctx.profileSectionsHTML('camara:1');
  assert.match(html, /1 projeto · situação consultada · classificação não confirmada/);
  assert.match(html, /Consulta registrada em 1 de 1 projetos; grupo confirmado em 0; 1 sem grupo confirmado/);
  assert.match(html, /data-project-item data-project-group="sem-situacao"/);
  assert.match(html, /Proposição retirada da tramitação/);
  assert.doesNotMatch(html, /Texto legado de tramitação/);
  assert.match(html, /Consulta da situação: 2026-10-02/);
  assert.match(html, /href="https:\/\/fonte\.example\.test\/retirada"/);
  assert.match(html, /&lt;script&gt;Consulta antiga preservada&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(html, /0 (?:virou|viraram) lei/);
});

test('partial group coverage never renders zero laws as a complete count', () => {
  const situation = grupo => ({ grupo, status: 'imported', consultadoEm: '2026-10-03T12:00:00Z' });
  const items = [{ titulo: 'Projeto com grupo conhecido', situacaoAtual: situation('tramitando') },
    ...Array.from({ length: 99 }, (_, index) => ({ titulo: `Sem grupo ${index}`, situacaoAtual: {
      grupo: null, status: 'imported', consultadoEm: '2026-10-03T12:00:00Z',
    } }))];
  const ctx = load({ perfis: { profiles: {
    'camara:1': { projetos: { status: 'imported', total: 100, items } },
    'camara:2': { projetos: { status: 'imported', total: 100, items: [
      { titulo: 'Uma lei confirmada', situacaoAtual: situation('lei') }, ...items.slice(1),
    ] } },
    'camara:3': { projetos: { status: 'imported', total: 2, items: [items[0]] } },
  } } });
  const zeroKnownLaws = ctx.profileSectionsHTML('camara:1');
  assert.match(zeroKnownLaws, /100 projetos · leis: consulta parcial/);
  assert.doesNotMatch(zeroKnownLaws, /0 (?:virou|viraram) lei/);
  assert.match(zeroKnownLaws, /grupo confirmado em 1; 99 sem grupo confirmado/);

  const someKnownLaws = ctx.profileSectionsHTML('camara:2');
  assert.match(someKnownLaws, /100 projetos · 1 lei confirmada · situação parcial/);
  assert.doesNotMatch(someKnownLaws, /0 (?:virou|viraram) lei/);

  const mismatchedTotal = ctx.profileSectionsHTML('camara:3');
  assert.match(mismatchedTotal, /2 projetos · leis: consulta parcial/);
  assert.match(mismatchedTotal, /A lista mostra 1 projeto de 2 no total/);
  assert.doesNotMatch(mismatchedTotal, /0 (?:virou|viraram) lei/);
});

test('project filters expose empty results and persist per profile without replacing the focused control', () => {
  const ctx = load({ perfis: { profiles: {
    'camara:1': { projetos: { status: 'partial', items: [{ titulo: 'Lei', situacaoAtual: {
      grupo: 'lei', status: 'imported', consultadoEm: '2026-10-01T12:00:00Z',
    } }] } },
    'camara:2': { projetos: { status: 'partial', items: [{ titulo: 'Lei', situacaoAtual: {
      grupo: 'lei', status: 'imported', consultadoEm: '2026-10-01T12:00:00Z',
    } }] } },
  } } });
  const controls = ['todos', 'lei', 'tramitando', 'arquivado', 'sem-situacao'].map(value => ({
    dataset: { projectFilter: value, projectProfile: 'camara:1' },
    attrs: { 'data-project-filter': value, 'data-project-profile': 'camara:1', 'aria-pressed': 'false' },
    getAttribute(name) { return this.attrs[name] ?? null; },
    setAttribute(name, value) { this.attrs[name] = value; },
    closest(selector) {
      if (selector === '[data-project-filter]') return this;
      return selector === '[data-project-filter-root]' ? root : null;
    },
  }));
  const rows = [{ dataset: { projectGroup: 'lei' }, hidden: false }, { dataset: { projectGroup: 'sem-situacao' }, hidden: false }];
  const empty = { hidden: true };
  const root = {
    querySelectorAll(selector) { return selector === '[data-project-filter]' ? controls : selector === '[data-project-item]' ? rows : []; },
    querySelector(selector) { return selector === '[data-project-empty]' ? empty : null; },
  };
  let rerenders = 0;
  ctx.rerender = () => { rerenders += 1; };
  const focusedButton = controls.find(control => control.dataset.projectFilter === 'tramitando');
  ctx.__dispatch('click', focusedButton);
  assert.equal(focusedButton.getAttribute('aria-pressed'), 'true');
  assert.equal(rows[0].hidden, true);
  assert.equal(rows[1].hidden, true);
  assert.equal(empty.hidden, false);
  assert.equal(rerenders, 0);
  const rerendered = ctx.profileSectionsHTML('camara:1');
  assert.match(rerendered, /data-project-filter="tramitando"[^>]*aria-pressed="true"/);
  assert.match(rerendered, /data-project-empty role="status" aria-live="polite">Nenhum projeto nesta situação/);
  assert.match(ctx.profileSectionsHTML('camara:2'), /data-project-filter="todos"[^>]*aria-pressed="true"/);
});

test('2026 election results are stated only for a single TSE match, in plain language', () => {
  const fonte = { sourceUrl: 'https://dadosabertos.tse.jus.br/dataset/candidatos-2026', fetchedAt: '2026-10-07T20:00:00+00:00', geradoNoTse: '07/10/2026 16:30:39' };
  const base = { fonte, metodo: 'Nome civil e data de nascimento, sem CPF.', segundoTurno: '2026-10-25' };
  const found = (cargo, uf, situacao) => ({ ...base, status: 'encontrada', cargo, uf, situacao, dataEleicao: '2026-10-04' });
  const ctx = load({ perfis: { profiles: {
    'camara:1': { role: 'deputado', eleicao2026: found('DEPUTADO FEDERAL', 'SP', 'ELEITO POR QP') },
    'camara:2': { role: 'deputado', eleicao2026: found('SENADOR', 'MG', 'NÃO ELEITO') },
    'senado:3': { role: 'senador', eleicao2026: found('GOVERNADOR', 'AM', '2º TURNO') },
    'camara:4': { role: 'deputado', eleicao2026: found('DEPUTADO FEDERAL', 'RJ', 'SUPLENTE') },
    'camara:5': { role: 'deputado', eleicao2026: found('DEPUTADO FEDERAL', 'RJ', '#NULO') },
    'camara:6': { role: 'deputado', eleicao2026: { ...base, status: 'sem-correspondencia' } },
    'senado:7': { role: 'senador', eleicao2026: found('PRESIDENTE', 'BR', '2º TURNO') },
    'senado:8': { role: 'senador', eleicao2026: found('1º SUPLENTE', 'PA', 'ELEITO') },
  } } });
  const e = id => ctx.profileElection(ctx.profileData(id));
  assert.equal(e('camara:1').curto, 'Reeleito(a) em 2026');
  assert.equal(e('camara:1').frase, 'Reeleito(a) deputado(a) federal por SP na eleição de 4/10/2026.');
  assert.equal(e('camara:2').curto, 'Não eleito(a) para senador(a)');
  assert.equal(e('camara:2').frase, 'Concorreu a senador(a) por MG em 2026 e não foi eleito(a).');
  assert.equal(e('senado:3').curto, '2º turno para governador(a)');
  assert.equal(e('senado:3').frase, 'Disputa o 2º turno para governador(a) por AM em 25/10/2026.');
  assert.equal(e('camara:4').curto, 'Não reeleito(a) em 2026');
  assert.equal(e('camara:4').frase, 'Concorreu à reeleição para deputado(a) federal por RJ em 2026 e ficou como suplente.');
  assert.equal(e('camara:5').curto, 'Candidato(a) a deputado(a) federal em 2026');
  assert.equal(e('camara:6').curto, null);
  assert.match(e('camara:6').frase, /^Não encontramos candidatura em 2026/);
  assert.equal(e('senado:7').frase, 'Disputa o 2º turno para presidente em 25/10/2026.');
  assert.equal(e('senado:8').curto, 'Eleito(a) 1º(ª) suplente de senador(a) em 2026');
  assert.equal(ctx.profileElection(ctx.profileData('camara:99')), null);
  const html = ctx.profileSectionsHTML('camara:1');
  assert.match(html, /<b>Eleição de 2026<\/b><p>Reeleito\(a\) deputado\(a\) federal por SP na eleição de 4\/10\/2026\.<\/p>/);
  assert.match(html, /Arquivo gerado pelo TSE em 07\/10\/2026 16:30:39/);
  assert.match(html, /href="https:\/\/dadosabertos\.tse\.jus\.br\/dataset\/candidatos-2026"/);
  assert.doesNotMatch(ctx.profileSectionsHTML('camara:99'), /Eleição de 2026/);
});

test('external fields and URLs are safe in shared cards', () => {
  const ctx = load({ perfis: { profiles: { 'camara:1': {
    contato: { email: '<script>email</script>', redes: [{ nome: 'malicioso', url: 'javascript:alert(1)' }] },
    projetos: { status: 'partial', total: null, items: [
      { titulo: '<img onerror=x>', ementa: 'Texto & conteúdo', url: 'data:text/html,test', situacao: '<script>estado</script>', situacaoAtual: {
        grupo: 'lei', descricao: '<script>descrição</script>', consultadoEm: '2026-06-01T12:00:00Z',
        sourceUrl: 'https://user:secret@example.test/status', status: 'imported', normas: [
          { tipo: '<script>norma</script>', numero: '1', ano: 2026, url: 'javascript:alert(2)' },
        ],
      } },
    ], sourceUrl: 'https://user:secret@example.test/' },
  } } } });
  const html = ctx.profileSectionsHTML('camara:1');
  assert.match(html, /&lt;script&gt;email&lt;\/script&gt;/);
  assert.match(html, /&lt;img onerror=x&gt;/);
  assert.match(html, /&lt;script&gt;descrição&lt;\/script&gt;/);
  assert.doesNotMatch(html, /&lt;script&gt;estado&lt;\/script&gt;/);
  assert.doesNotMatch(html, /href="(?:javascript|data):|user:secret|<script>|<img onerror/);
});

test('profiles outside the old sample load on demand once and keep detail headings while loading', async () => {
  const calls = [];
  let release;
  const ctx = load({ perfis: { profiles: {}, sobDemanda: true } });
  ctx.skel = () => '<skeleton>';
  ctx.rerender = () => calls.push('rerender');
  ctx.fetch = url => { calls.push(url); return new Promise(ok => { release = () => ok({ ok: true, json: async () => ({ name: 'Ana', role: 'deputado', contato: { email: 'ana@camara.leg.br' } }) }); }); };
  const loading = ctx.profileSectionsHTML({ id: 'camara:513', role: 'deputado' });
  assert.match(loading, /data-profile-section=["']projetos["']/);
  assert.match(loading, /data-profile-section=["']equipe["']/);
  assert.match(loading, /data-profile-section=["']contato["']/);
  assert.match(loading, /data-profile-section=["']fontes["']/);
  assert.match(loading, /<skeleton>/);
  ctx.profileData('camara:513');
  assert.deepEqual(calls, ['/api/c/perfil/camara%3A513']);
  release(); await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  assert.equal(ctx.profileData('camara:513').contato.email, 'ana@camara.leg.br');
  assert.equal(calls.filter(c => c !== 'rerender').length, 1);
  assert.ok(calls.includes('rerender'));

  const failedCalls = [];
  const failed = load({ perfis: { profiles: {}, sobDemanda: true } });
  failed.rerender = () => failedCalls.push('rerender');
  failed.fetch = url => { failedCalls.push(url); return Promise.reject(new Error('offline')); };
  assert.equal(failed.profileData('camara:514').loading, true);
  await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  assert.equal(failed.profileData('camara:514').loading, false);
  assert.equal(failedCalls.filter(c => c !== 'rerender').length, 1);
  assert.ok(failedCalls.includes('rerender'));

  const offline = load({ perfis: { profiles: {} } });
  offline.fetch = () => { throw new Error('não deveria buscar'); };
  assert.equal(offline.profileData('camara:8').loading, false);
});
