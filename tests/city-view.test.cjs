const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function makeView(fetchImpl = async () => ({ ok: true, async json() { return {}; } })) {
  const elements = {};
  const listeners = {};
  const document = {
    getElementById: id => elements[id] || null,
    addEventListener(name, handler) { (listeners[name] ||= []).push(handler); },
  };
  const context = vm.createContext({
    document, state: { view: 'city' }, fetch: fetchImpl,
    esc: value => String(value).replace(/[&<>\"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[character])),
    pageHead: (kicker, title, lead) => `<header><span>${kicker}</span><h1>${title}</h1><p>${lead}</p></header>`,
    skel: () => '<div>Carregando…</div>', rerender() {}, navigateToView() {},
    citizenErrorMessage: error => error.message,
    profileSafeUrl: value => /^https?:\/\//i.test(String(value || '')) ? String(value) : '',
    setTimeout: () => 1, clearTimeout() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/scripts/city-view.js'), 'utf8'), context);
  context.cityApi = vm.runInContext('({ state: cityViewState, view: cityView, loadMatches: cityLoadMatches, searchResults: citySearchResultsMarkup, searchKeydown: citySearchKeydown, updateSearchResults: cityUpdateSearchResults, keepActiveVisible: cityKeepActiveVisible, loadDetail: cityLoadDetail })', context);
  return { context, elements, listeners };
}

test('city view explains missing data blocks and the Brasília and Fernando de Noronha exceptions', () => {
  const { context } = makeView();
  const city = context.cityApi.state;
  city.selectedId = '5300108';
  city.selectedCity = { id: '5300108', name: 'Brasília', uf: 'DF' };
  city.detail = {
    municipality: { id: '5300108', name: 'Brasília', uf: 'DF', population: null, populationYear: null },
    sources: {},
    municipalElected: [], stateElected: [], topFederalVotes: [], currentFederal: [],
    messages: {
      municipalElection: 'A eleição municipal não se aplica ao DF.',
      generalElection: 'Resultado eleitoral não disponível.',
      votes: 'Apuração ainda não disponível.',
      currentFederal: 'Lista parlamentar indisponível.',
    },
  };

  const html = context.cityApi.view();
  assert.match(html, /não tem municípios, prefeitura ou Câmara de Vereadores/);
  assert.match(html, /não há eleição municipal de 2024/);
  assert.match(html, /Brasília representa o Distrito Federal/);
  assert.match(html, /Os mandatos correspondentes começam em 2027/);
  assert.match(html, /População[\s\S]*Sem registro[\s\S]*habitantes não informados/);
  assert.match(html, /Resultado eleitoral não disponível\./);
  assert.match(html, /Apuração ainda não disponível\./);
  assert.match(html, /Lista parlamentar indisponível\./);

  city.selectedId = null;
  city.selectedCity = null;
  const picker = context.cityApi.view();
  assert.match(picker, /Fernando de Noronha é um distrito estadual de Pernambuco e não elege prefeito nem vereadores/);
  assert.doesNotMatch(picker, /consulte Recife/);

  city.selectedId = '2605459';
  city.selectedCity = { id: '2605459', name: 'Fernando de Noronha', uf: 'PE' };
  city.detail = {
    municipality: { id: '2605459', name: 'Fernando de Noronha', uf: 'PE' },
    municipalElected: [], stateElected: [], topFederalVotes: [], currentFederal: [], messages: {}, sources: {},
  };
  const fernando = context.cityApi.view();
  assert.match(fernando, /Sobre Fernando de Noronha/);
  assert.match(fernando, /não elege prefeito nem vereadores/);
  assert.match(fernando, /Resultados municipais não se aplicam/);
  assert.doesNotMatch(fernando, /consulte Recife/);
});

test('election rows keep office labels, hide null vote counts, and keep current federal sources separate', () => {
  const { context } = makeView();
  const city = context.cityApi.state;
  city.selectedId = '3550308';
  city.selectedCity = { id: '3550308', name: 'São Paulo', uf: 'SP' };
  city.detail = {
    municipality: { id: '3550308', name: 'São Paulo', uf: 'SP', population: 1000000, populationYear: 2025 },
    sources: {
      generalElection: { label: 'TSE <oficial>', url: 'javascript:alert(1)' },
      currentFederal: {
        camara: { label: 'Câmara dos Deputados', url: 'https://camara.example/roster', period: 'setembro de 2026' },
        senado: { label: 'Senado Federal', url: 'https://senado.example/roster', period: 'outubro de 2026' },
      },
    },
    municipalElected: [{ id: 'tse:1', ballotName: 'Prefeita <img src=x onerror=alert(1)>', office: 'PREFEITO', party: 'ABC', result: 'ELEITO' }],
    stateElected: [
      { id: 'tse:2', name: 'Governadora Exemplo', office: 'GOVERNADOR', party: 'XYZ', result: 'ELEITO', votes: null },
      { id: 'tse:3', name: 'Deputada Estadual Exemplo', office: 'DEPUTADO ESTADUAL', party: 'ABC', result: 'ELEITO' },
      { id: 'tse:4', name: 'Deputado Federal Exemplo', office: 'DEPUTADO FEDERAL', party: 'XYZ', result: 'ELEITO' },
      { id: 'tse:5', name: 'Senadora Exemplo', office: 'SENADOR', party: 'DEF', result: 'ELEITO' },
    ],
    topFederalVotes: [{ id: 'tse:4', name: 'Deputado Federal Exemplo', office: 'DEPUTADO FEDERAL', party: 'XYZ', votes: 12000 }],
    currentFederal: [
      { id: 'camara:10', name: 'Deputada da Câmara', office: 'Deputado(a) federal', party: 'ABC', uf: 'SP' },
      { id: 'senado:20', name: 'Senador do Senado', office: 'Senador(a)', party: 'DEF', uf: 'SP' },
    ],
    messages: {},
  };

  const html = context.cityApi.view();
  assert.match(html, /Prefeita &lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /TSE &lt;oficial&gt;/);
  assert.doesNotMatch(html, /href="javascript:/);
  assert.match(html, /Prefeito\(a\) · ABC · ELEITO/);
  assert.match(html, /Governador\(a\) · XYZ · ELEITO/);
  assert.match(html, /Deputado\(a\) estadual · ABC · ELEITO/);
  assert.match(html, /Congresso Nacional: deputados\(as\) federais e senadores\(as\) eleitos\(as\)/);
  assert.doesNotMatch(html, /<b class="city-votes[^>]*>0 votos/);
  const voteBlock = html.match(/<section class="card city-data-section" aria-labelledby="city-federal-votes-title">[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(voteBlock, /Deputados\(as\) federais/);
  assert.doesNotMatch(voteBlock, /senadores/);
  assert.match(html, /Câmara dos Deputados[\s\S]*Câmara dos Deputados ↗/);
  assert.match(html, /Senado Federal[\s\S]*Senado Federal ↗/);
  assert.match(html, /data-deputy="camara:10"/);
  assert.match(html, /data-deputy="senado:20"/);
  assert.match(html, /Lista parlamentar atual/);
  assert.doesNotMatch(html, /Mandatos em exercício/);
  assert.match(html, /<details class="city-collapsible city-roster"><summary>Câmara dos Deputados · 1/);
  assert.match(html, /<details class="city-collapsible city-roster"><summary>Senado Federal · 1/);
});

test('stale city search responses cannot replace newer data and unavailable catalog is not reported as no match', async () => {
  const pending = [];
  const { context } = makeView(url => new Promise(resolve => pending.push({ url, resolve })));
  const search = context.cityApi.state;
  search.query = 'São';
  const older = context.cityApi.loadMatches();
  search.query = 'Sao';
  const newer = context.cityApi.loadMatches();
  assert.match(pending[0].url, /q=S%C3%A3o/);
  assert.match(pending[1].url, /q=Sao/);

  pending[1].resolve({ ok: true, async json() { return { available: false, items: [], total: 0 }; } });
  await newer;
  pending[0].resolve({ ok: true, async json() { return { available: true, items: [{ id: '3550308', name: 'São Paulo', uf: 'SP' }] }; } });
  await older;
  assert.equal(search.searchStatus, 'unavailable');
  assert.deepEqual(Array.from(search.items), []);
  assert.match(context.cityApi.searchResults(), /lista de municípios não está disponível/);
  assert.doesNotMatch(context.cityApi.searchResults(), /Nenhuma cidade encontrada/);
});

test('Escape closes the autocomplete options while preserving the query', () => {
  const { context, elements } = makeView();
  const input = {
    id: 'city-search', setAttribute(name, value) { this[name] = value; },
    removeAttribute(name) { delete this[name]; },
  };
  elements['city-search'] = input;
  elements['city-results'] = { innerHTML: '' };
  Object.assign(context.cityApi.state, {
    query: 'Brasília', searchStatus: 'ready', suggestionsOpen: true, activeIndex: 0,
    items: [{ id: '5300108', name: 'Brasília', uf: 'DF' }],
  });
  const event = { target: input, key: 'Escape', preventDefault() {} };
  context.cityApi.searchKeydown(event);
  context.cityApi.updateSearchResults();
  assert.equal(context.cityApi.state.query, 'Brasília');
  assert.equal(input['aria-expanded'], 'false');
  assert.match(elements['city-results'].innerHTML, /Sugestões ocultas/);
  assert.doesNotMatch(elements['city-results'].innerHTML, /role="option"/);
});

test('search source refreshes with each response and keyboard focus scrolls only the suggestion panel', async () => {
  const { context, elements } = makeView(async () => ({
    ok: true,
    async json() {
      return {
        available: true,
        items: Array.from({ length: 8 }, (_, index) => ({ id: String(1000000 + index), name: `Cidade ${index}`, uf: 'SP' })),
        source: { label: 'IBGE', url: 'https://ibge.example/cities', fetchedAt: '2026-10-07T08:15:00Z' },
      };
    },
  }));
  const input = {
    id: 'city-search', setAttribute(name, value) { this[name] = value; },
    removeAttribute(name) { delete this[name]; },
  };
  const list = {
    scrollTop: 0,
    getBoundingClientRect() { return { top: 100, bottom: 300 }; },
  };
  elements['city-search'] = input;
  elements['city-results'] = { innerHTML: '' };
  elements['city-search-source'] = { innerHTML: '' };
  context.document.getElementById = id => {
    if (id === 'city-suggestions') return list;
    const optionMatch = id.match(/^city-option-(\d{7})$/);
    if (optionMatch) {
      const index = Number(optionMatch[1]) - 1000000;
      return { getBoundingClientRect() { const top = 100 + index * 56 - list.scrollTop; return { top, bottom: top + 56 }; } };
    }
    return elements[id] || null;
  };
  const search = context.cityApi.state;
  search.query = 'Cidade';
  await context.cityApi.loadMatches();
  assert.match(elements['city-search-source'].innerHTML, /IBGE ↗/);
  assert.match(elements['city-search-source'].innerHTML, /consulta em 07\/10\/2026/);
  context.cityApi.searchKeydown({ target: input, key: 'ArrowUp', preventDefault() {} });
  assert.equal(input['aria-activedescendant'], 'city-option-1000007');
  search.activeIndex = -1;
  list.scrollTop = 0;
  for (let index = 0; index < 6; index++) context.cityApi.searchKeydown({ target: input, key: 'ArrowDown', preventDefault() {} });
  assert.equal(input['aria-activedescendant'], 'city-option-1000005');
  assert.ok(list.scrollTop > 0, 'active option scrolls inside the result list');
});

test('stale detail responses cannot overwrite a different selected city', async () => {
  const pending = [];
  const { context } = makeView(url => new Promise(resolve => pending.push({ url, resolve })));
  const city = context.cityApi.state;
  city.selectedId = '3550308';
  const older = context.cityApi.loadDetail();
  city.selectedId = '3304557';
  const newer = context.cityApi.loadDetail();
  pending[1].resolve({ ok: true, async json() { return { municipality: { id: '3304557', name: 'Rio de Janeiro', uf: 'RJ' } }; } });
  await newer;
  pending[0].resolve({ ok: true, async json() { return { municipality: { id: '3550308', name: 'São Paulo', uf: 'SP' } }; } });
  await older;
  assert.equal(city.detail.municipality.id, '3304557');
});
