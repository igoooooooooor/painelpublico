const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/scripts/profile-data.js'), 'utf8');

function load(data = {}) {
  const context = {
    DATA: { deputados: [], votacoes: [], presencaTodos: [], ...data }, URL,
    esc: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
  };
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

test('every legislative profile has explicit coverage for salary, staff, contact and projects', () => {
  const ctx = load();
  const html = ctx.profileSectionsHTML({ id: 'senado:9', role: 'senador' });
  assert.match(html, /subsídio bruto mensal de referência do cargo/);
  assert.match(html, /Pagamento individual, descontos e outras verbas não foram importados/);
  assert.match(html, /Gastos com a equipe ainda não importados/);
  assert.match(html, /Não informado no recorte/);
  assert.match(html, /Projetos ainda não importados/);
  assert.doesNotMatch(html, /0 projetos|NaN|undefined/);
  assert.equal(ctx.profileSectionsHTML({ id: 'siape:9', role: 'servidor' }), '');
});

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

test('profiles outside the old sample load on demand once, show a skeleton meanwhile and never fetch without the snapshot', async () => {
  const calls = [];
  let release;
  const ctx = load({ perfis: { profiles: {}, sobDemanda: true } });
  ctx.skel = () => '<skeleton>';
  ctx.rerender = () => calls.push('rerender');
  ctx.fetch = url => { calls.push(url); return new Promise(ok => { release = () => ok({ ok: true, json: async () => ({ name: 'Ana', role: 'deputado', contato: { email: 'ana@camara.leg.br' } }) }); }); };
  assert.equal(ctx.profileSectionsHTML({ id: 'camara:513', role: 'deputado' }), '<skeleton>');
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
