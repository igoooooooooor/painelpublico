/* Minha cidade: consulta os dados municipais e estaduais publicados pela API. */
const cityViewState = {
  query: '', items: [], searchStatus: 'idle', searchError: null, searchSource: null, searchSequence: 0,
  searchTimer: null, activeIndex: -1, suggestionsOpen: false,
  selectedId: null, selectedCity: null, detail: null, detailLoading: false,
  detailError: null, detailSequence: 0, detailCache: new Map(),
};

const cityNormalize = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
const cityIsBrasilia = municipality => cityNormalize(municipality?.name) === 'brasilia' && String(municipality?.uf || '').toUpperCase() === 'DF';
const cityIsFernandoDeNoronha = municipality => cityNormalize(municipality?.name) === 'fernando de noronha' && String(municipality?.uf || '').toUpperCase() === 'PE';
const cityPopulation = value => value !== null && value !== undefined && String(value).trim() !== '' && Number.isFinite(Number(value)) ? Number(value).toLocaleString('pt-BR') : null;
const cityYear = value => /^\d{4}$/.test(String(value || '')) ? String(value) : null;
const cityReadableDate = value => {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : String(value || '');
};
const citySafeUrl = value => {
  if (typeof profileSafeUrl === 'function') return profileSafeUrl(value);
  return /^https?:\/\//i.test(String(value || '')) ? String(value) : '';
};

function citySource(source, fallbackLabel = 'Fonte dos dados') {
  if (!source || typeof source !== 'object') return '<span class="src">Fonte e período não informados pela API.</span>';
  const url = citySafeUrl(source.url);
  const label = source.label || fallbackLabel;
  const metadata = [source.period, source.fetchedAt ? `consulta em ${cityReadableDate(source.fetchedAt)}` : null].filter(Boolean).map(esc).join(' · ');
  return `${source.note ? `<p class="note">${esc(source.note)}</p>` : ''}<span class="src">Fonte: ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)} ↗</a>` : esc(label)}${metadata ? ` · ${metadata}` : ''}</span>`;
}

function cityUnavailable(message, fallback) {
  const text = typeof message === 'string' && message.trim() ? message : fallback;
  return `<p class="note">${esc(text)}</p>`;
}

function citySearchResultsMarkup() {
  const search = cityViewState;
  if (search.searchError) return `<div class="city-search-message" role="alert"><p>Não foi possível buscar as cidades agora.</p><p class="muted">${esc(search.searchError)}</p><button type="button" class="fchip" data-city-retry-search>Tentar de novo</button></div>`;
  if (search.searchStatus === 'unavailable') return `<p class="city-search-message" role="status">A lista de municípios não está disponível neste momento. Tente novamente mais tarde.</p>`;
  if (search.searchStatus === 'loading' || search.searchStatus === 'waiting') return `<p class="city-search-message" role="status">${search.searchStatus === 'loading' ? 'Buscando cidades…' : 'Preparando a busca…'}</p>`;
  if (search.searchStatus === 'empty') return `<p class="city-search-message" role="status">Nenhuma cidade encontrada com esse nome. Confira a escrita ou tente outra forma.</p>`;
  if (search.searchStatus === 'ready' && search.items.length) {
    if (!search.suggestionsOpen) return '<p class="city-search-message muted">Sugestões ocultas. Digite mais letras para abrir a lista novamente.</p>';
    return `<div class="city-suggestions" id="city-suggestions" role="listbox" aria-label="Cidades encontradas">${search.items.map((item, index) => {
      const id = String(item.id || '');
      const population = cityPopulation(item.population);
      return `<div class="city-suggestion" role="option" id="city-option-${esc(id)}" aria-selected="${index === search.activeIndex}" data-city-select="${esc(id)}" data-city-index="${index}" tabindex="-1">
        <span class="city-suggestion-name"><b>${esc(item.name || 'Cidade sem nome')}</b><span class="city-uf">${esc(item.uf || '')}</span></span>
        <span class="muted">${population ? `${population} habitantes${cityYear(item.populationYear) ? ` · ${cityYear(item.populationYear)}` : ''}` : 'População sem registro'}</span>
      </div>`;
    }).join('')}</div>`;
  }
  return '<p class="city-search-message muted">Digite ao menos 2 letras para buscar.</p>';
}

function cityUpdateSearchResults() {
  const results = document.getElementById('city-results');
  if (!results) return;
  results.innerHTML = citySearchResultsMarkup();
  const source = document.getElementById('city-search-source');
  if (source) source.innerHTML = cityViewState.searchSource
    ? citySource(cityViewState.searchSource, 'Lista de municípios')
    : '<span class="src">A fonte da lista aparece junto aos resultados da busca.</span>';
  const input = document.getElementById('city-search');
  if (input) {
    const hasSuggestions = cityViewState.searchStatus === 'ready' && cityViewState.items.length > 0 && cityViewState.suggestionsOpen;
    input.setAttribute('aria-expanded', String(hasSuggestions));
    const active = hasSuggestions && cityViewState.activeIndex >= 0 ? cityViewState.items[cityViewState.activeIndex] : null;
    if (active) input.setAttribute('aria-activedescendant', `city-option-${active.id}`);
    else input.removeAttribute('aria-activedescendant');
    if (active) cityKeepActiveVisible(active.id);
  }
}

function cityKeepActiveVisible(cityId) {
  const list = document.getElementById('city-suggestions');
  const option = document.getElementById(`city-option-${cityId}`);
  if (!list?.getBoundingClientRect || !option?.getBoundingClientRect) return;
  const listRect = list.getBoundingClientRect(), optionRect = option.getBoundingClientRect();
  if (optionRect.top < listRect.top) list.scrollTop -= listRect.top - optionRect.top;
  else if (optionRect.bottom > listRect.bottom) list.scrollTop += optionRect.bottom - listRect.bottom;
}

async function cityLoadMatches() {
  const query = cityViewState.query.trim();
  const sequence = ++cityViewState.searchSequence;
  if (query.length < 2) {
    cityViewState.searchStatus = 'idle'; cityViewState.items = []; cityViewState.searchError = null;
    cityUpdateSearchResults();
    return;
  }
  cityViewState.searchStatus = 'loading'; cityViewState.items = []; cityViewState.searchError = null;
  cityViewState.activeIndex = -1; cityViewState.suggestionsOpen = true;
  cityUpdateSearchResults();
  try {
    const response = await fetch(`/api/c/cities?q=${encodeURIComponent(query)}`, { headers: { Accept: 'application/json' } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(data.error || 'Não deu para carregar a busca.'); error.status = response.status; throw error; }
    if (sequence !== cityViewState.searchSequence || query !== cityViewState.query.trim()) return;
    cityViewState.items = Array.isArray(data.items) ? data.items.slice(0, 20) : [];
    cityViewState.searchSource = data.source || null;
    cityViewState.searchStatus = data.available === false ? 'unavailable' : cityViewState.items.length ? 'ready' : 'empty';
  } catch (error) {
    if (sequence !== cityViewState.searchSequence || query !== cityViewState.query.trim()) return;
    cityViewState.searchStatus = 'error';
    cityViewState.searchError = typeof citizenErrorMessage === 'function' ? citizenErrorMessage(error) : error.message || 'Não deu para carregar agora.';
  }
  if (sequence === cityViewState.searchSequence && state.view === 'city') cityUpdateSearchResults();
}

function citySearchInput(value) {
  cityViewState.query = String(value || '');
  cityViewState.searchSequence++;
  cityViewState.searchStatus = cityViewState.query.trim().length < 2 ? 'idle' : 'waiting';
  cityViewState.searchError = null; cityViewState.searchSource = null; cityViewState.items = []; cityViewState.activeIndex = -1;
  cityViewState.suggestionsOpen = true;
  if (cityViewState.searchTimer !== null) clearTimeout(cityViewState.searchTimer);
  cityUpdateSearchResults();
  if (cityViewState.query.trim().length >= 2) cityViewState.searchTimer = setTimeout(() => cityLoadMatches(), 180);
}

function citySearchSubmit() {
  if (cityViewState.searchTimer !== null) clearTimeout(cityViewState.searchTimer);
  cityViewState.searchTimer = null;
  cityLoadMatches();
}

function citySearchKeydown(event) {
  if (event.target?.id !== 'city-search') return false;
  const search = cityViewState;
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    if (search.searchStatus !== 'ready' || !search.items.length) return false;
    event.preventDefault();
    search.suggestionsOpen = true;
    const delta = event.key === 'ArrowDown' ? 1 : -1;
    search.activeIndex = search.activeIndex < 0
      ? (delta > 0 ? 0 : search.items.length - 1)
      : (search.activeIndex + delta + search.items.length) % search.items.length;
    cityUpdateSearchResults();
    return true;
  }
  if (event.key === 'Enter') {
    event.preventDefault();
    if (search.searchStatus === 'ready' && search.items.length) {
      const item = search.items[search.activeIndex >= 0 ? search.activeIndex : 0];
      citySelect(item.id);
    } else citySearchSubmit();
    return true;
  }
  if (event.key === 'Escape' && search.suggestionsOpen) {
    search.suggestionsOpen = false; search.activeIndex = -1; cityUpdateSearchResults();
    return true;
  }
  return false;
}

function citySelect(cityId) {
  const item = cityViewState.items.find(candidate => String(candidate.id) === String(cityId));
  if (!item || !/^\d{7}$/.test(String(item.id))) return;
  cityViewState.selectedId = String(item.id); cityViewState.selectedCity = item;
  cityViewState.detail = cityViewState.detailCache.get(cityViewState.selectedId) || null;
  cityViewState.detailError = null; cityViewState.detailLoading = !cityViewState.detail;
  cityViewState.suggestionsOpen = false; cityViewState.detailSequence++;
  navigateToView('city', true);
  if (!cityViewState.detail) cityLoadDetail(cityViewState.selectedId);
}

async function cityLoadDetail(cityId = cityViewState.selectedId) {
  if (!/^\d{7}$/.test(String(cityId || ''))) return;
  const id = String(cityId), sequence = ++cityViewState.detailSequence;
  cityViewState.detailLoading = true; cityViewState.detailError = null;
  if (state.view === 'city') rerender();
  try {
    const response = await fetch(`/api/c/cities/${encodeURIComponent(id)}`, { headers: { Accept: 'application/json' } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(data.error || 'Não deu para carregar os dados desta cidade.'); error.status = response.status; throw error; }
    if (sequence !== cityViewState.detailSequence || id !== cityViewState.selectedId) return;
    cityViewState.detailCache.set(id, data); cityViewState.detail = data;
    cityViewState.detailLoading = false;
  } catch (error) {
    if (sequence !== cityViewState.detailSequence || id !== cityViewState.selectedId) return;
    cityViewState.detailLoading = false;
    cityViewState.detailError = typeof citizenErrorMessage === 'function' ? citizenErrorMessage(error) : error.message || 'Não deu para carregar agora.';
  }
  if (sequence === cityViewState.detailSequence && state.view === 'city') rerender();
}

function cityOfficeKey(value) {
  const office = cityNormalize(value).toUpperCase();
  if (office.includes('VICE') && (office.includes('PREFEIT') || office.includes('GOVERN'))) return 'vice';
  if (office.includes('PREFEIT')) return 'mayor';
  if (office.includes('GOVERN')) return 'governor';
  if (office.includes('VEREADOR')) return 'councillor';
  if (office.includes('DISTRITAL')) return 'districtDeputy';
  if (office.includes('ESTADUAL')) return 'stateDeputy';
  if (office.includes('SENADOR')) return 'senator';
  if (office.includes('FEDERAL')) return 'federalDeputy';
  return 'other';
}

function cityOfficeLabel(person, options = {}) {
  const key = cityOfficeKey(person.office);
  const labels = {
    mayor: 'Prefeito(a)', vice: options.municipal ? 'Vice-prefeito(a)' : 'Vice-governador(a)',
    governor: 'Governador(a)', councillor: 'Vereador(a)', districtDeputy: options.isDf ? 'Deputado(a) distrital' : 'Deputado(a) estadual',
    stateDeputy: 'Deputado(a) estadual', senator: 'Senador(a)', federalDeputy: 'Deputado(a) federal', other: person.office || 'Cargo não informado',
  };
  return labels[key] || person.office || 'Cargo não informado';
}

function cityPersonRow(person, options = {}) {
  const name = person.ballotName || person.name || 'Nome não informado';
  const identity = [cityOfficeLabel(person, options), person.party, person.uf, person.result].filter(Boolean).map(esc).join(' · ');
  const profileId = String(person.profileId || '');
  const profile = /^(?:camara|senado):\d+$/.test(profileId)
    ? `<button type="button" class="city-profile-link" data-deputy="${esc(profileId)}">Ver ficha parlamentar</button>` : '';
  const hasVotes = person.votes !== null && person.votes !== undefined && String(person.votes).trim() !== '' && Number.isFinite(Number(person.votes));
  const votes = hasVotes ? `<b class="city-votes mono">${Number(person.votes).toLocaleString('pt-BR')} votos</b>` : '';
  return `<li class="city-person"><span class="city-person-main"><b>${esc(name)}</b><span class="muted">${identity || esc(cityOfficeLabel(person, options))}</span></span>${votes}${profile}</li>`;
}

function cityGroupedPeople(people, keys, options = {}) {
  const groups = Object.fromEntries(keys.map(key => [key, []]));
  for (const person of people) (groups[cityOfficeKey(person.office)] || groups.other || []).push(person);
  return groups;
}

function cityMunicipalSection(data, isDf, isFernando) {
  const people = Array.isArray(data.municipalElected) ? data.municipalElected : [];
  const message = data.messages?.municipalElection;
  if (isDf || isFernando) return `<section class="card city-data-section" aria-labelledby="city-municipal-title"><div class="city-section-heading"><div><span class="k">Eleição municipal · 2024</span><h2 class="h" id="city-municipal-title">Prefeitura e Câmara</h2></div></div>
    ${isDf ? cityUnavailable('Brasília representa o Distrito Federal. O DF não tem municípios, prefeitura ou Câmara de Vereadores; não há eleição municipal de 2024.', 'A eleição municipal não se aplica ao Distrito Federal.') : cityUnavailable('Fernando de Noronha consta em cadastros estatísticos, mas é um distrito estadual de Pernambuco e não elege prefeito nem vereadores. Resultados municipais não se aplicam.', 'A eleição municipal não se aplica a este distrito.')}
    ${citySource(data.sources?.municipalElection, 'Resultados eleitorais municipais')}</section>`;
  if (!people.length) return `<section class="card city-data-section" aria-labelledby="city-municipal-title"><div class="city-section-heading"><div><span class="k">Eleição municipal · 2024</span><h2 class="h" id="city-municipal-title">Prefeitura e Câmara</h2></div></div>
    ${cityUnavailable(message, 'Os resultados municipais de 2024 não estão disponíveis para este município.')}${citySource(data.sources?.municipalElection, 'Resultados eleitorais municipais')}</section>`;
  const groups = cityGroupedPeople(people, ['mayor', 'vice', 'councillor', 'other']);
  const elected = [...groups.mayor, ...groups.vice];
  const councilors = groups.councillor;
  const other = groups.other;
  return `<section class="card city-data-section" aria-labelledby="city-municipal-title"><div class="city-section-heading"><div><span class="k">Eleição municipal · 2024</span><h2 class="h" id="city-municipal-title">Prefeitura e Câmara</h2></div><span class="pill">${people.length} eleitos(as)</span></div>
    ${elected.length ? `<ul class="city-people-list">${elected.map(person => cityPersonRow(person, { municipal: true })).join('')}</ul>` : cityUnavailable(message, 'Os resultados de prefeito(a) e vice-prefeito(a) não estão disponíveis neste recorte.')}
    ${councilors.length ? `<details class="city-collapsible"><summary>Vereadores(as) eleitos(as) · ${councilors.length}</summary><ul class="city-people-list">${councilors.map(person => cityPersonRow(person, { municipal: true })).join('')}</ul></details>` : cityUnavailable(message, 'Não há vereadores(as) eleitos(as) disponíveis neste recorte.')}
    ${other.length ? `<details class="city-collapsible"><summary>Outros resultados · ${other.length}</summary><ul class="city-people-list">${other.map(person => cityPersonRow(person, { municipal: true })).join('')}</ul></details>` : ''}
    ${citySource(data.sources?.municipalElection, 'Resultados eleitorais municipais')}</section>`;
}

function cityGeneralElectionSection(data, isDf) {
  const people = Array.isArray(data.stateElected) ? data.stateElected : [];
  const message = data.messages?.generalElection;
  const title = isDf ? 'Governo e Câmara Legislativa' : 'Governo e Assembleia';
  if (!people.length) return `<section class="card city-data-section" aria-labelledby="city-general-title"><div class="city-section-heading"><div><span class="k">Eleição geral · 2026</span><h2 class="h" id="city-general-title">${title}</h2></div></div>
    <p class="muted">Resultado da eleição de 2026. Os mandatos correspondentes começam em 2027.</p>${cityUnavailable(message, 'Os resultados de 2026 ainda não estão disponíveis para este estado ou o Distrito Federal.')}${citySource(data.sources?.generalElection, 'Resultados eleitorais gerais')}</section>`;
  const groups = cityGroupedPeople(people, ['governor', 'vice', 'stateDeputy', 'districtDeputy', 'federalDeputy', 'senator', 'other']);
  const executive = [...groups.governor, ...groups.vice];
  const legislature = [...groups.stateDeputy, ...groups.districtDeputy];
  const federal = [...groups.federalDeputy, ...groups.senator];
  const other = groups.other;
  return `<section class="card city-data-section" aria-labelledby="city-general-title"><div class="city-section-heading"><div><span class="k">Eleição geral · 2026</span><h2 class="h" id="city-general-title">${title}</h2></div><span class="pill">${people.length} eleitos(as)</span></div>
    <p class="note">Resultados da eleição de 2026. Os mandatos começam em 2027; estas pessoas não são apresentadas como ocupantes atuais.</p>
    ${executive.length ? `<ul class="city-people-list">${executive.map(person => cityPersonRow(person, { isDf })).join('')}</ul>` : cityUnavailable(message, 'Os resultados para governador(a) e vice-governador(a) não estão disponíveis neste recorte.')}
    ${legislature.length ? `<details class="city-collapsible"><summary>${isDf ? 'Deputados(as) distritais' : 'Deputados(as) estaduais'} eleitos(as) · ${legislature.length}</summary><ul class="city-people-list">${legislature.map(person => cityPersonRow(person, { isDf })).join('')}</ul></details>` : cityUnavailable(message, 'Os resultados legislativos de 2026 não estão disponíveis neste recorte.')}
    ${federal.length ? `<details class="city-collapsible"><summary>Congresso Nacional: deputados(as) federais e senadores(as) eleitos(as) · ${federal.length}</summary><ul class="city-people-list">${federal.map(person => cityPersonRow(person, { isDf })).join('')}</ul></details>` : cityUnavailable(message, 'Os resultados para deputados(as) federais e senadores(as) não estão disponíveis neste recorte.')}
    ${other.length ? `<details class="city-collapsible"><summary>Cargos sem classificação neste recorte · ${other.length}</summary><ul class="city-people-list">${other.map(person => cityPersonRow(person, { isDf })).join('')}</ul></details>` : ''}
    ${citySource(data.sources?.generalElection, 'Resultados eleitorais gerais')}</section>`;
}

function cityFederalVotesSection(data) {
  const people = Array.isArray(data.topFederalVotes) ? data.topFederalVotes : [];
  return `<section class="card city-data-section" aria-labelledby="city-federal-votes-title"><div class="city-section-heading"><div><span class="k">Votos na cidade · 2026</span><h2 class="h" id="city-federal-votes-title">Deputados(as) federais</h2></div></div>
    <p class="muted">Este destaque inclui somente candidatos(as) eleitos(as) a deputado(a) federal com votos registrados nesta cidade. Quem não se elegeu não aparece aqui.</p>
    ${people.length ? `<ol class="city-people-list city-ranked-list">${people.map(person => cityPersonRow(person)).join('')}</ol>` : cityUnavailable(data.messages?.votes, 'Os votos de candidatos(as) eleitos(as) não estão disponíveis para esta cidade.')}
    ${citySource(data.sources?.votes, 'Apuração de votos')}</section>`;
}

function cityCurrentFederalSection(data) {
  const people = Array.isArray(data.currentFederal) ? data.currentFederal : [];
  const sources = data.sources?.currentFederal || {};
  const chamber = people.filter(person => String(person.id || '').startsWith('camara:'));
  const senate = people.filter(person => String(person.id || '').startsWith('senado:'));
  const row = person => `<li class="city-person"><span class="city-person-main"><b>${esc(person.name || 'Nome não informado')}</b><span class="muted">${[person.office, person.party, person.uf].filter(Boolean).map(esc).join(' · ')}</span></span>${/^(?:camara|senado):\d+$/.test(String(person.id || '')) ? `<button type="button" class="city-profile-link" data-deputy="${esc(person.id)}">Ver ficha parlamentar</button>` : citySafeUrl(person.sourceUrl) ? `<a class="city-profile-link" href="${esc(citySafeUrl(person.sourceUrl))}" target="_blank" rel="noopener">Fonte oficial ↗</a>` : ''}</li>`;
  const sourceFor = (chamberKey, roster, label) => sources[chamberKey] || (roster[0] ? { label, url: roster[0].sourceUrl, period: roster[0].sourcePeriod, fetchedAt: roster[0].fetchedAt } : null);
  const rosterGroup = (title, roster, source, fallback) => roster.length
    ? `<details class="city-collapsible city-roster"><summary>${esc(title)} · ${roster.length}</summary><ul class="city-people-list">${roster.map(row).join('')}</ul></details>${citySource(source, title)}`
    : `<h3 class="city-subheading">${esc(title)}</h3>${cityUnavailable(data.messages?.currentFederal, fallback)}${citySource(source, title)}`;
  return `<section class="card city-data-section" aria-labelledby="city-current-federal-title"><div class="city-section-heading"><div><span class="k">Representação federal por UF</span><h2 class="h" id="city-current-federal-title">Lista parlamentar atual · ${esc(data.municipality.uf)}</h2></div></div>
    <p class="muted">Lista atual segundo os registros parlamentares consultados, separada dos resultados eleitorais de 2026. Os períodos e atualizações podem variar entre as fontes; as pessoas listadas não necessariamente moram neste município.</p>
    ${rosterGroup('Câmara dos Deputados', chamber, sourceFor('camara', chamber, 'Lista atual da Câmara'), 'A lista da Câmara dos Deputados não está disponível neste recorte.')}
    ${rosterGroup('Senado Federal', senate, sourceFor('senado', senate, 'Lista atual do Senado'), 'A lista do Senado Federal não está disponível neste recorte.')}
  </section>`;
}

function cityDetailView() {
  if (!cityViewState.selectedId || !cityViewState.selectedCity) return cityPickerView();
  if (cityViewState.detailLoading && !cityViewState.detail) return `<button type="button" class="back" data-city-search>‹ Voltar à busca</button>${pageHead('Minha cidade', 'Carregando cidade…', 'Consultando os registros disponíveis para este município.')}${skel('ficha', 2)}`;
  if (cityViewState.detailError && !cityViewState.detail) return `<button type="button" class="back" data-city-search>‹ Voltar à busca</button>${pageHead('Minha cidade', 'Não foi possível abrir esta cidade', 'Os dados municipais e eleitorais não carregaram.')}
    <section class="card" role="alert"><p class="muted">${esc(cityViewState.detailError)}</p><button type="button" class="opt" data-city-retry-detail>Tentar de novo</button></section>`;
  const data = cityViewState.detail;
  if (!data || !data.municipality) return `<button type="button" class="back" data-city-search>‹ Voltar à busca</button>${pageHead('Minha cidade', 'Dados indisponíveis', 'A resposta da API não contém os dados deste município.')}
    <section class="card"><p>Não foi possível montar a página desta cidade.</p><button type="button" class="opt" data-city-retry-detail>Tentar de novo</button></section>`;
  const municipality = data.municipality, isDf = cityIsBrasilia(municipality), isFernando = cityIsFernandoDeNoronha(municipality);
  const population = cityPopulation(municipality.population), year = cityYear(municipality.populationYear);
  return `<button type="button" class="back" data-city-search>‹ Voltar à busca</button>
    <header class="city-detail-header"><span class="k">Minha cidade · ${esc(municipality.uf)}</span><h1 class="h">${esc(municipality.name)}</h1><p class="ph-lead">Eleições e representantes, com fonte e período de cada conjunto de dados.</p></header>
    ${isDf ? `<section class="note city-special-note"><b>Sobre Brasília:</b> esta seleção representa o Distrito Federal, que não tem municípios, prefeitos ou vereadores. Os cargos locais são distritais.</section>` : isFernando ? `<section class="note city-special-note"><b>Sobre Fernando de Noronha:</b> embora conste em cadastros estatísticos, é um distrito estadual de Pernambuco e não elege prefeito nem vereadores.</section>` : ''}
    <section class="city-overview card"><div class="city-overview-label"><span class="k">População</span><span class="city-population">${population === null ? 'Sem registro' : population}</span><span class="muted">${population === null ? 'habitantes não informados' : `habitantes${year ? ` · ${year}` : ''}`}</span></div>${citySource(data.sources?.population, 'Estimativa de população')}</section>
    <div class="city-content-grid">${cityMunicipalSection(data, isDf, isFernando)}${cityGeneralElectionSection(data, isDf)}${cityFederalVotesSection(data)}${cityCurrentFederalSection(data)}</div>
    ${data.generatedAt ? `<span class="src">Base local montada em ${esc(cityReadableDate(data.generatedAt))}.</span>` : ''}`;
}

function cityPickerView() {
  const query = cityViewState.query;
  return `${pageHead('Dados públicos por município', 'Minha cidade', 'Consulte população, eleições municipais, resultados de 2026 e a lista parlamentar atual do seu estado.')}
    <section class="card city-search-card"><label class="k" for="city-search">Qual cidade você quer consultar?</label>
      <div class="city-search-row"><div class="search"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg><input id="city-search" type="search" value="${esc(query)}" placeholder="Digite o nome da cidade" autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="city-suggestions"></div><button type="button" class="fchip" data-city-search-submit>Buscar</button></div>
      <div id="city-results" class="city-results" aria-live="polite">${citySearchResultsMarkup()}</div>
      <div id="city-search-source">${cityViewState.searchSource ? citySource(cityViewState.searchSource, 'Lista de municípios') : '<span class="src">A fonte da lista aparece junto aos resultados da busca.</span>'}</div>
    </section>
    <section class="note city-geography-note"><b>Como interpretar:</b> Brasília representa o Distrito Federal, que não tem prefeitura nem vereadores. Embora conste em cadastros estatísticos, Fernando de Noronha é um distrito estadual de Pernambuco e não elege prefeito nem vereadores.</section>
    <section class="card city-intro-card"><span class="k">O que você vai encontrar</span><div class="city-intro-grid"><p><b>Dados do município</b><span>População e resultados de 2024 para prefeito(a), vice-prefeito(a) e vereadores(as).</span></p><p><b>Eleição geral de 2026</b><span>Resultados de governador(a) e deputados(as) estaduais ou distritais. Os mandatos começam em 2027.</span></p><p><b>Representação federal</b><span>Votos de pessoas eleitas na cidade e lista atual de deputados(as) e senadores(as) do estado, em blocos separados.</span></p></div></section>`;
}

function cityView() {
  return cityDetailView();
}

function cityHandleInput(event) {
  if (event.target?.id === 'city-search') citySearchInput(event.target.value);
}

function cityHandleKeydown(event) {
  citySearchKeydown(event);
}

document.addEventListener('input', cityHandleInput);
document.addEventListener('keydown', cityHandleKeydown);
