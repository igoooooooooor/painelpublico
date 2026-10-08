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

const baseDetail = (municipality, extra = {}) => ({
  municipality, sources: {}, municipalElected: [], stateElected: [], topFederalVotes: [], currentFederal: [], messages: {}, ...extra,
});
function showCity(context, municipality, extra = {}) {
  const city = context.cityApi.state;
  city.selectedId = municipality.id;
  city.selectedCity = municipality;
  city.detail = baseDetail(municipality, extra);
  return context.cityApi.view();
}
const SP = { id: '3550308', name: 'São Paulo', uf: 'SP', population: 1351284, populationYear: 2026 };

test('city page answers three questions first and keeps the rest in collapsed sections', () => {
  const { context } = makeView();
  const html = showCity(context, SP, {
    municipalElected: [
      { id: 'tse:1', ballotName: 'LUCAS DA SILVA', office: 'PREFEITO', party: 'ABC', result: 'ELEITO' },
      { id: 'tse:2', ballotName: 'VICE EXEMPLO', office: 'VICE-PREFEITO', party: 'DEF', result: 'ELEITO' },
      { id: 'tse:3', ballotName: 'ANA VEREADORA', office: 'VEREADOR', party: 'ABC', result: 'ELEITO POR QP' },
      { id: 'tse:4', ballotName: 'BIA VEREADORA', office: 'VEREADOR', party: 'ABC', result: 'ELEITO POR MÉDIA' },
      { id: 'tse:5', ballotName: 'CAIO VEREADOR', office: 'VEREADOR', party: 'XYZ', result: 'ELEITO POR QP' },
    ],
  });
  const answers = [...html.matchAll(/data-city-answer="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(answers, ['govern', 'spend', 'amendments']);
  assert.match(html, /São Paulo em 3 respostas/);
  assert.match(html, /1,35 milhão de habitantes/);
  assert.match(html, /Lucas da Silva/);
  assert.doesNotMatch(html, /LUCAS DA SILVA/);
  assert.match(html, /Vice: <b>Vice Exemplo<\/b> \(DEF\)/);
  assert.match(html, /data-profile-open="council"><span>Câmara Municipal: 3 vereadores\(as\)/);
  assert.match(html, /<b>ABC<\/b> 2/);
  assert.doesNotMatch(html, /ELEITO POR QP|ELEITO POR MÉDIA/);
  assert.doesNotMatch(html, /intraorçamentária|DCA|FINBRA/);
  assert.match(html, /data-profile-section="council"/);
  assert.match(html, /data-profile-section="sources"/);
});

test('Brasília and Fernando de Noronha explain who governs instead of showing a missing mayor', () => {
  const { context } = makeView();
  const df = showCity(context, { id: '5300108', name: 'Brasília', uf: 'DF', population: null },
    { stateElected: [{ id: 'tse:9', ballotName: 'GOVERNADORA EXEMPLO', office: 'GOVERNADOR', party: 'XYZ', result: 'ELEITO' }],
      accounts: { status: 'not_applicable' } });
  assert.match(df, /Brasília não tem prefeitura nem vereadores/);
  assert.match(df, /Eleito\(a\) em 2026 para governar a partir de 2027: <b>Governadora Exemplo<\/b>/);
  assert.match(df, /não é município/);
  assert.match(df, /População não informada/);
  assert.doesNotMatch(df, /data-profile-section="accounts"/);
  assert.doesNotMatch(df, /Ausência de dado não significa gasto zero/);
  const noronha = showCity(context, { id: '2605459', name: 'Fernando de Noronha', uf: 'PE' }, { accounts: { status: 'not_applicable' } });
  assert.match(noronha, /administrado pelo governo de Pernambuco e não elege prefeito nem vereadores/);
  assert.doesNotMatch(noronha, /data-profile-section="votes"/);
});

test('missing municipal results, accounts and amendments are explained, never shown as zero', () => {
  const { context } = makeView();
  const html = showCity(context, SP, { messages: { municipalElection: 'Resultado municipal não confirmado.' } });
  assert.match(html, /Resultado municipal não confirmado\./);
  assert.match(html, /Ausência de dado não significa que não houve eleição/);
  assert.match(html, /Ausência de dado não significa gasto zero/);
  assert.match(html, /Os dados de emendas não estão disponíveis agora/);
  assert.doesNotMatch(html, /R\$ 0\b|R\$ 0,00/);
  const noRecords = showCity(context, SP, { amendments: { year: 2026, status: 'no_records', recordCount: 0, totals: { committedCents: 0 } } });
  assert.match(noRecords, /Nenhuma emenda de 2026 indica São Paulo como destino/);
  assert.match(noRecords, /não significa que a cidade não recebeu recursos/);
  assert.doesNotMatch(noRecords, /data-profile-section="amendments"/);
  const notFiled = showCity(context, SP, { accounts: { status: 'not_filed', year: 2025, message: 'A prefeitura não entregou ao Tesouro.' } });
  assert.match(notFiled, /A prefeitura não entregou ao Tesouro\./);
  assert.doesNotMatch(notFiled, /R\$ 0/);
});

test('spending is compared per resident with the typical city of the same size, never by totals', () => {
  const { context } = makeView();
  const comparisonMetric = (id, perCapitaMedianCents, perCapitaSampleSize = 40) => ({ id, medianCents: 999999999999, sampleSize: 40, perCapitaMedianCents, perCapitaSampleSize });
  const html = showCity(context, SP, { accounts: {
    year: 2025, status: 'available', population: { value: 1349100, year: 2025 },
    source: { label: 'Tesouro <dados>', url: 'https://dados.example/contas', period: 'exercício de 2025', fetchedAt: '2026-10-08' },
    metrics: [
      { id: 'total-expense', label: 'Despesa', amountCents: 696657561510, perCapitaCents: 516387 },
      { id: 'health', label: 'Saúde', amountCents: 160557376086, perCapitaCents: 119011 },
      { id: 'education', label: 'Educação', amountCents: 173393246295, perCapitaCents: 128525 },
      { id: 'revenue', label: 'Receita <img src=x>', amountCents: 0, perCapitaCents: 0 },
    ],
    comparison: { available: true, band: { minPopulation: 500001, maxPopulation: null }, reportingCount: 46,
      metrics: [comparisonMetric('total-expense', 617605), comparisonMetric('health', 144396), comparisonMetric('education', 124102, 2)] },
  } });
  const spend = html.match(/<section[^>]*data-city-answer="spend"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(spend, /<small>R\$<\/small>5\.164/);
  assert.match(spend, /dividido pelos 1\.349\.100 moradores/);
  assert.match(spend, /16% abaixo do típico/);
  assert.match(spend, /cidades com mais de 500 mil habitantes/);
  assert.match(spend, /Saúde<\/span><b class="mono">R\$ 1\.190[\s\S]*Típico: R\$ 1\.444/);
  assert.doesNotMatch(spend, /Típico: R\$ 1\.241/);
  assert.doesNotMatch(spend, /9\.999/);
  const accounts = html.match(/<section[^>]*data-profile-section="accounts"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(accounts, /title="R\$ 6\.966\.575\.615,10">R\$ 7,0 bilhões/);
  assert.match(accounts, /Menos de 3 cidades para comparar/);
  assert.match(accounts, /title="R\$ 0,00"/);
  assert.match(accounts, /Receita/);
  assert.doesNotMatch(accounts, /<img src=x/);
  assert.match(accounts, /mediana[\s\S]*46 cidades com mais de 500 mil habitantes/);
  assert.match(accounts, /não é o limite da Lei de Responsabilidade Fiscal/);
  assert.match(accounts, /Tesouro &lt;dados&gt; ↗/);
});

test('amendments lead with reserved and paid values, top authors and a Pix subset that is not added again', () => {
  const { context } = makeView();
  const html = showCity(context, SP, { amendments: {
    year: 2026, status: 'available', recordCount: 3,
    source: { label: 'Portal', url: 'https://dados.example/emendas', fetchedAt: '2026-10-07' },
    totals: { committedCents: 1198543640, paidCents: 50426200, restosPaidCents: null },
    specialTransfers: { identified: true, recordCount: 1, totals: { committedCents: 30000 } },
    authors: [
      { id: 'a', name: 'AUTORA <img src=x onerror=alert(1)>', committedCents: 100000000, paidCents: 0, profileId: 'camara:9' },
      { id: 'b', name: 'BANCADA SP', committedCents: 998543640, paidCents: 50426200 },
      { id: 'c', name: null, committedCents: 100000000, paidCents: null, profileId: 'javascript:alert(1)' },
      { id: 'd', name: 'QUARTO NOME', committedCents: 1, paidCents: 0 },
    ],
  } });
  const answer = html.match(/<section[^>]*data-city-answer="amendments"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(answer, /<small>R\$<\/small>12,0<small class="city-unit">mi<\/small>/);
  assert.match(answer, /em 3 emendas/);
  assert.match(answer, /R\$ 504 mil<\/b> já foram pagos \(4%\)/);
  assert.ok(answer.indexOf('Bancada Sp') < answer.indexOf('Autora'));
  assert.equal((answer.match(/data-deputy=/g) || []).length, 1);
  assert.match(answer, /Ver as 4 autorias/);
  assert.doesNotMatch(answer, /Quarto Nome/);
  const detail = html.match(/<section[^>]*data-profile-section="amendments"[\s\S]*?<\/section>/)?.[0] || '';
  assert.match(detail, /Restos a pagar pagos<\/span><b class="mono">Não informado/);
  assert.match(detail, /1 é transferência especial[\s\S]*já estão incluídos acima/);
  assert.match(detail, /Autoria não identificada/);
  assert.doesNotMatch(html, /<img src=x/);
  assert.doesNotMatch(html, /javascript:/);
});

test('federal votes and 2026 results use plain labels, link profiles and keep current members separate', () => {
  const { context } = makeView();
  const html = showCity(context, SP, {
    sources: { generalElection: { label: 'TSE <oficial>', url: 'javascript:alert(1)' } },
    stateElected: [
      { id: 'tse:2', ballotName: 'GOVERNADORA EXEMPLO', office: 'GOVERNADOR', party: 'XYZ', result: '2º TURNO' },
      { id: 'tse:3', ballotName: 'DEPUTADA ESTADUAL', office: 'DEPUTADO ESTADUAL', party: 'ABC', result: 'ELEITO POR QP' },
      { id: 'tse:5', ballotName: 'SENADORA EXEMPLO', office: 'SENADOR', party: 'DEF', result: 'ELEITO', profileId: 'senado:20' },
    ],
    topFederalVotes: [
      { id: 'tse:4', ballotName: 'DEPUTADO MAIS VOTADO', party: 'XYZ', votes: 12000, profileId: 'camara:10' },
      { id: 'tse:6', ballotName: 'SEM VOTOS', party: 'XYZ', votes: null },
    ],
    currentFederal: [{ id: 'camara:10', name: 'DEPUTADA DA CÂMARA', party: 'ABC', uf: 'SP' }],
  });
  assert.match(html, /Em quem São Paulo votou para deputado\(a\) federal/);
  assert.match(html, /Deputado Mais Votado[\s\S]*12\.000/);
  assert.doesNotMatch(html, /Sem Votos/);
  assert.match(html, /Governadora Exemplo <small class="city-tag">2º turno em 25\/10<\/small>/);
  assert.match(html, /Os mandatos começam em 2027/);
  assert.match(html, /data-deputy="senado:20"/);
  assert.match(html, /Quem representa SP no Congresso hoje/);
  assert.match(html, /Não necessariamente mora nesta cidade/);
  assert.match(html, /TSE &lt;oficial&gt;/);
  assert.doesNotMatch(html, /href="javascript:/);
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
