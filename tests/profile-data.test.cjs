const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/scripts/profile-data.js'), 'utf8');

function load(data = {}, { width = 390 } = {}) {
  const elements = new Map();
  const accordionButtons = [];
  const viewport = { width };
  const media = query => ({ matches: query.includes('900') && viewport.width >= 900, addEventListener() {} });
  const context = {
    DATA: { deputados: [], votacoes: [], presencaTodos: [], ...data }, URL,
    innerWidth: width,
    window: { innerWidth: width, matchMedia: media },
    matchMedia: media,
    document: {
      documentElement: { clientWidth: width },
      getElementById: id => elements.get(id) || null,
      querySelectorAll: () => accordionButtons,
      _elements: elements,
      _accordionButtons: accordionButtons,
    },
    esc: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
  };
  context.__setWidth = next => { viewport.width = next; };
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
  assert.doesNotMatch(ctx.profileSectionsHTML('camara:2'), /0 projetos/);
});

test('external fields and URLs are safe in shared cards', () => {
  const ctx = load({ perfis: { profiles: { 'camara:1': {
    contato: { email: '<script>email</script>', redes: [{ nome: 'malicioso', url: 'javascript:alert(1)' }] },
    projetos: { status: 'partial', total: null, items: [
      { titulo: '<img onerror=x>', ementa: 'Texto & conteúdo', url: 'data:text/html,test' },
    ], sourceUrl: 'https://user:secret@example.test/' },
  } } } });
  const html = ctx.profileSectionsHTML('camara:1');
  assert.match(html, /&lt;script&gt;email&lt;\/script&gt;/);
  assert.match(html, /&lt;img onerror=x&gt;/);
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
