/* Minha cidade: quem governa, quanto a prefeitura gasta por morador e quanto chegou de emendas, em linguagem simples. */
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
const cityHasCents = value => value !== null && value !== undefined && String(value).trim() !== '' && Number.isFinite(Number(value));
const cityMoneyFromCents = value => cityHasCents(value)
  ? `R$ ${(Number(value) / 100).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : null;
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
  return '<p class="city-search-message muted">Comece a digitar o nome da cidade.</p>';
}

function cityUpdateSearchResults() {
  const results = document.getElementById('city-results');
  if (!results) return;
  results.innerHTML = citySearchResultsMarkup();
  const source = document.getElementById('city-search-source');
  if (source) source.innerHTML = cityViewState.searchSource
    ? citySource(cityViewState.searchSource, 'Lista de municípios')
    : '';
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

/* ---------- Apresentação: nomes, números e frases curtas ---------- */
const CITY_NAME_PARTICLES = new Set(['de', 'da', 'do', 'das', 'dos', 'e']);
function cityTitleCase(value) {
  return String(value || '').toLocaleLowerCase('pt-BR').split(/\s+/).filter(Boolean)
    .map((word, index) => index > 0 && CITY_NAME_PARTICLES.has(word) ? word : word.charAt(0).toLocaleUpperCase('pt-BR') + word.slice(1))
    .join(' ');
}
const cityPersonName = person => cityTitleCase(person?.ballotName || person?.name) || 'Nome não informado';
const cityInitials = name => String(name || '').split(' ').filter(word => word && !CITY_NAME_PARTICLES.has(word.toLowerCase()))
  .slice(0, 2).map(word => word.charAt(0)).join('').toUpperCase();
const cityIsElected = person => /^ELEIT/i.test(String(person?.result || ''));
const cityNumber = (value, digits = 0) => Number(value).toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const cityProfileButton = (profileId, label = 'Ver ficha') => /^(?:camara|senado):\d+$/.test(String(profileId || ''))
  ? `<button type="button" class="city-profile-link" data-deputy="${esc(profileId)}">${esc(label)} →</button>` : '';

function cityCompactMoney(cents, long = false) {
  if (!cityHasCents(cents)) return null;
  const value = Number(cents) / 100, size = Math.abs(value);
  if (size >= 1e9) return `R$ ${cityNumber(value / 1e9, 1)} ${long ? (size >= 2e9 ? 'bilhões' : 'bilhão') : 'bi'}`;
  if (size >= 1e6) return `R$ ${cityNumber(value / 1e6, 1)} ${long ? (size >= 2e6 ? 'milhões' : 'milhão') : 'mi'}`;
  if (size >= 1e4) return `R$ ${cityNumber(value / 1e3)} mil`;
  return `R$ ${cityNumber(value)}`;
}
function cityHugeMoney(cents) {
  const value = Number(cents) / 100, size = Math.abs(value);
  const [amount, unit] = size >= 1e9 ? [cityNumber(value / 1e9, 1), 'bi'] : size >= 1e6 ? [cityNumber(value / 1e6, 1), 'mi']
    : size >= 1e4 ? [cityNumber(value / 1e3), 'mil'] : [cityNumber(value), ''];
  return `<small>R$</small>${amount}${unit ? `<small class="city-unit">${unit}</small>` : ''}`;
}
const cityExactCompact = cents => cityHasCents(cents)
  ? `<span title="${esc(cityMoneyFromCents(cents))}">${esc(cityCompactMoney(cents, true))}</span>` : 'Não informado';
const cityPerResident = cents => cityHasCents(cents) ? `R$ ${cityNumber(Number(cents) / 100)}` : null;
function cityPopulationText(value) {
  if (!cityHasCents(value) || Number(value) <= 0) return null;
  const count = Number(value);
  if (count >= 1e6) return `${cityNumber(count / 1e6, count >= 1e7 ? 1 : 2).replace(/,?0+$/, '')} ${count >= 2e6 ? 'milhões' : 'milhão'} de habitantes`;
  return `${cityNumber(count)} ${count === 1 ? 'habitante' : 'habitantes'}`;
}
function cityVerdict(value, typical) {
  if (!cityHasCents(value) || !cityHasCents(typical) || Number(typical) <= 0) return null;
  const difference = Number(value) / Number(typical) - 1;
  return Math.abs(difference) < 0.1 ? 'Parecido com o típico' : `${Math.round(Math.abs(difference) * 100)}% ${difference > 0 ? 'acima' : 'abaixo'} do típico`;
}
function cityBandText(band) {
  const short = count => count >= 1e6 ? `${cityNumber(count / 1e6)} ${count >= 2e6 ? 'milhões' : 'milhão'}` : count >= 1000 ? `${cityNumber(count / 1000)} mil` : cityNumber(count);
  const min = Number(band?.minPopulation), max = band?.maxPopulation === null || band?.maxPopulation === undefined ? null : Number(band.maxPopulation);
  if (!band || !Number.isFinite(min)) return 'cidades do mesmo porte';
  if (max === null) return `cidades com mais de ${short(min - 1)} habitantes`;
  if (min <= 1) return `cidades com até ${short(max)} habitantes`;
  return `cidades de ${short(min - 1)} a ${short(max)} habitantes`;
}
function cityResultText(person, secondRound) {
  const result = String(person?.result || '');
  if (/^ELEIT/i.test(result)) return '';
  if (/2º TURNO/i.test(result)) return `2º turno${secondRound ? ` em ${secondRound}` : ''}`;
  return result ? cityTitleCase(result) : '';
}
function cityAccordion(cityId, key, title, content) {
  if (typeof profileAccordionHTML === 'function') return profileAccordionHTML(`city:${cityId}`, key, title, content);
  return `<section class="card citizen-detail" data-profile-section="${esc(key)}"><h3 class="citizen-detail-heading">${esc(title)}</h3><div class="citizen-detail-body">${content}</div></section>`;
}
const cityAccountsUsable = accounts => ['available', 'partial', 'stale'].includes(accounts?.status);
const cityAccountMetric = (accounts, id) => (Array.isArray(accounts?.metrics) ? accounts.metrics : []).find(item => item && item.id === id) || null;
const cityAccountTypical = (accounts, id) => (Array.isArray(accounts?.comparison?.metrics) ? accounts.comparison.metrics : []).find(item => item && item.id === id) || null;
const cityTypicalPerResident = (accounts, id) => {
  const typical = cityAccountTypical(accounts, id);
  return accounts?.comparison?.available && Number(typical?.perCapitaSampleSize) >= 3 && cityHasCents(typical?.perCapitaMedianCents)
    ? Number(typical.perCapitaMedianCents) : null;
};
const CITY_ACCOUNT_LABELS = { revenue: 'Receita', 'total-expense': 'Gasto total', personnel: 'Pessoal', health: 'Saúde', education: 'Educação' };

function cityAccountsMessage(accounts, isDf, isFernando) {
  if (isDf) return 'O Distrito Federal não é município, então não presta contas como prefeitura.';
  if (isFernando) return 'Fernando de Noronha é um distrito estadual e não tem contas de prefeitura.';
  if (accounts?.status === 'not_filed') return accounts.message || 'A prefeitura não entregou as contas do ano ao Tesouro Nacional.';
  return accounts?.message || 'As contas desta prefeitura não estão disponíveis nesta base.';
}

function cityCouncilSeats(council) {
  const seats = new Map();
  for (const person of council) seats.set(person.party || 'Sem partido', (seats.get(person.party || 'Sem partido') || 0) + 1);
  return [...seats].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0], 'pt-BR'));
}

/* ---------- As 3 respostas ---------- */
function cityGovernAnswer(data, isDf, isFernando) {
  const people = Array.isArray(data.municipalElected) ? data.municipalElected : [];
  const mayor = people.find(person => cityOfficeKey(person.office) === 'mayor');
  const vice = people.find(person => cityOfficeKey(person.office) === 'vice');
  const council = people.filter(person => cityOfficeKey(person.office) === 'councillor');
  const open = '<section class="card hero citizen-answer city-answer" data-city-answer="govern"><h2 class="h">Quem governa?</h2>';
  if (isDf || isFernando) {
    const governor = (Array.isArray(data.stateElected) ? data.stateElected : []).find(person => cityOfficeKey(person.office) === 'governor' && cityIsElected(person));
    return `${open}<span class="k">${isDf ? 'Distrito Federal' : 'Distrito estadual de Pernambuco'}</span>
      <p class="city-answer-lead">${isDf ? 'Brasília não tem prefeitura nem vereadores. Quem governa é o governo do Distrito Federal, com a Câmara Legislativa.'
        : 'Fernando de Noronha é administrado pelo governo de Pernambuco e não elege prefeito nem vereadores.'}</p>
      ${isDf && governor ? `<p class="city-answer-note">Eleito(a) em 2026 para governar a partir de 2027: <b>${esc(cityPersonName(governor))}</b>${governor.party ? ` (${esc(governor.party)})` : ''}.</p>` : ''}
    </section>`;
  }
  if (!mayor) return `${open}<span class="k">Prefeitura · eleição de 2024</span>
    <p class="city-answer-lead">${esc(data.messages?.municipalElection || 'O resultado de 2024 para prefeito(a) não está nesta base.')}</p>
    <p class="city-answer-note">Ausência de dado não significa que não houve eleição.</p></section>`;
  const name = cityPersonName(mayor);
  return `${open}<span class="k">Prefeitura · eleição de 2024</span>
    <div class="city-mayor"><span class="city-initials" aria-hidden="true">${esc(cityInitials(name))}</span><div><b>${esc(name)}</b><span>Prefeito(a)${mayor.party ? ` · ${esc(mayor.party)}` : ''}</span></div></div>
    ${vice ? `<p class="city-answer-note">Vice: <b>${esc(cityPersonName(vice))}</b>${vice.party ? ` (${esc(vice.party)})` : ''}</p>` : ''}
    <p class="city-answer-note">Mandato de 2025 a 2028.</p>
    ${council.length ? `<div class="city-mini-seats"><span class="k">Maiores bancadas na Câmara Municipal</span><div class="city-seats">${cityCouncilSeats(council).slice(0, 4).map(([party, count]) => `<span class="fchip city-seat"><b>${esc(party)}</b> ${count}</span>`).join('')}</div></div>` : ''}
    ${council.length ? `<button type="button" class="opt city-answer-action" data-profile-open="council"><span>Câmara Municipal: ${council.length} ${council.length === 1 ? 'vereador(a)' : 'vereadores(as)'}</span><span>→</span></button>` : ''}
  </section>`;
}

function citySpendAnswer(data, isDf, isFernando) {
  const accounts = data.accounts && typeof data.accounts === 'object' ? data.accounts : {};
  const year = cityYear(accounts.year);
  const total = cityAccountMetric(accounts, 'total-expense');
  const open = '<section class="card citizen-answer city-answer" data-city-answer="spend"><h2 class="h">Quanto a prefeitura gasta por morador?</h2>';
  if (!cityAccountsUsable(accounts) || !cityHasCents(total?.perCapitaCents)) {
    const message = cityAccountsUsable(accounts)
      ? 'Não foi possível calcular o gasto por morador: falta a população do mesmo ano ou o gasto total.'
      : cityAccountsMessage(accounts, isDf, isFernando);
    return `${open}<span class="k">Contas da prefeitura${year ? ` · ${esc(year)}` : ''}</span>
      <p class="city-answer-lead">${esc(message)}</p>
      ${isDf || isFernando ? '' : '<p class="city-answer-note">Ausência de dado não significa gasto zero.</p>'}</section>`;
  }
  const typicalTotal = cityTypicalPerResident(accounts, 'total-expense');
  const verdict = cityVerdict(total.perCapitaCents, typicalTotal);
  const bars = [['health', 'Saúde'], ['education', 'Educação']].map(([id, label]) => {
    const metric = cityAccountMetric(accounts, id);
    if (!cityHasCents(metric?.perCapitaCents)) return '';
    const value = Number(metric.perCapitaCents), typical = cityTypicalPerResident(accounts, id);
    const scale = Math.max(value, typical || 0) || 1;
    return `<div class="city-bar-row"><div class="city-bar-label"><span>${label}</span><b class="mono">${cityPerResident(value)}</b></div>
      <div class="city-bar" role="img" aria-label="${label}: ${cityPerResident(value)} por morador${typical ? `; típico ${cityPerResident(typical)}` : ''}"><i style="width:${(value / scale * 100).toFixed(1)}%"></i>${typical ? `<span class="city-bar-mark" style="left:${(typical / scale * 100).toFixed(1)}%"></span>` : ''}</div>
      ${typical ? `<small class="muted">Típico: ${cityPerResident(typical)}</small>` : ''}</div>`;
  }).join('');
  const residents = accounts.population?.value;
  return `${open}<span class="k">Contas de ${esc(year || '')} · por morador, no ano</span>
    <div class="huge"><small>R$</small>${cityNumber(Number(total.perCapitaCents) / 100)}</div>
    <p class="city-answer-note">Tudo o que a prefeitura gastou${residents ? `, dividido pelos ${cityNumber(residents)} moradores` : ' por morador'}.</p>
    ${bars ? `<div class="city-bars">${bars}</div>` : ''}
    ${verdict ? `<div class="city-verdict"><span class="fchip citizen-verdict">${esc(verdict)}</span><small class="muted">Comparado com ${esc(cityBandText(accounts.comparison?.band))}. A marca na barra é o típico.</small></div>` : ''}
  </section>`;
}

function cityAmendmentsAnswer(data, cityName) {
  const amendments = data.amendments && typeof data.amendments === 'object' ? data.amendments : {};
  const year = Number.isInteger(amendments.year) ? amendments.year : null;
  const records = Number(amendments.recordCount) > 0 ? Number(amendments.recordCount) : 0;
  const hasRecords = records > 0 && ['available', 'partial', 'stale'].includes(amendments.status) && cityHasCents(amendments.totals?.committedCents);
  const open = `<section class="card citizen-answer city-answer" data-city-answer="amendments"><h2 class="h">Quanto chegou de emendas?</h2><span class="k">Emendas${year ? ` propostas em ${year}` : ''}</span>`;
  if (!hasRecords) {
    const unavailable = !amendments.status || amendments.status === 'unavailable';
    return `${open}<p class="city-answer-lead">${esc(unavailable ? (amendments.message || 'Os dados de emendas não estão disponíveis agora.')
      : `Nenhuma emenda${year ? ` de ${year}` : ''} indica ${cityName} como destino.`)}</p>
      <p class="city-answer-note">Muitas emendas não informam a cidade de destino. Ausência de registro não significa que a cidade não recebeu recursos.</p></section>`;
  }
  const committed = Number(amendments.totals.committedCents);
  const paid = cityHasCents(amendments.totals.paidCents) ? Number(amendments.totals.paidCents) : null;
  const share = paid !== null && committed > 0 ? Math.min(100, paid / committed * 100) : null;
  const authors = (Array.isArray(amendments.authors) ? amendments.authors : []).filter(author => author && cityHasCents(author.committedCents))
    .sort((left, right) => Number(right.committedCents) - Number(left.committedCents));
  const paidText = paid === null ? 'O valor pago não foi informado pela fonte.'
    : paid === 0 ? 'Nada foi pago até a data da consulta.'
      : `<b>${esc(cityCompactMoney(paid, true))}</b> já ${paid >= 200 ? 'foram pagos' : 'foi pago'} (${share < 1 ? 'menos de 1' : cityNumber(share)}%).`;
  return `${open}<div class="huge">${cityHugeMoney(committed)}</div>
    <p class="city-answer-note">reservados para a cidade em ${records} ${records === 1 ? 'emenda' : 'emendas'}.</p>
    ${share !== null ? `<div class="city-progress" role="img" aria-label="${cityNumber(share)}% pago"><i style="width:${share.toFixed(1)}%"></i></div>` : ''}
    <p class="city-answer-note">${paidText}</p>
    ${authors.length ? `<ol class="city-top-authors">${authors.slice(0, 3).map(author => `<li><span>${esc(cityTitleCase(author.name) || 'Autoria não identificada')}</span><b class="mono">${esc(cityCompactMoney(author.committedCents))}</b>${cityProfileButton(author.profileId, 'Ficha')}</li>`).join('')}</ol>` : ''}
    ${authors.length > 3 ? `<button type="button" class="more" data-profile-open="amendments">Ver as ${authors.length} autorias →</button>` : ''}
  </section>`;
}

/* ---------- Ver mais ---------- */
function cityCouncilDetail(data) {
  const council = (Array.isArray(data.municipalElected) ? data.municipalElected : []).filter(person => cityOfficeKey(person.office) === 'councillor');
  if (!council.length) return null;
  const parties = cityCouncilSeats(council);
  const people = [...council].sort((left, right) => cityPersonName(left).localeCompare(cityPersonName(right), 'pt-BR'));
  return `<p class="muted">Cadeiras por partido na Câmara Municipal, eleição de 2024.</p>
    <div class="city-seats">${parties.map(([party, count]) => `<span class="fchip city-seat"><b>${esc(party)}</b> ${count}</span>`).join('')}</div>
    <ul class="city-name-list">${people.map(person => `<li><span><b>${esc(cityPersonName(person))}</b><small class="muted">${esc(person.party || '')}</small></span></li>`).join('')}</ul>
    ${citySource(data.sources?.municipalElection, 'TSE — eleição municipal')}`;
}

function cityVotesDetail(data) {
  const people = Array.isArray(data.topFederalVotes) ? data.topFederalVotes.filter(person => cityHasCents(person.votes)) : [];
  if (!people.length) return `${cityUnavailable(data.messages?.votes, 'Os votos por cidade ainda não estão disponíveis.')}${citySource(data.sources?.votes, 'TSE — votação por município')}`;
  const top = Math.max(...people.map(person => Number(person.votes))) || 1;
  return `<p class="muted">Entre os(as) deputados(as) federais eleitos(as) em 2026, quem teve mais votos aqui.</p>
    <ol class="city-rank">${people.map((person, index) => `<li><span class="city-rank-n mono">${index + 1}</span>
      <span class="city-rank-name"><b>${esc(cityPersonName(person))}</b><small class="muted">${esc(person.party || '')}</small></span>
      <span class="city-rank-votes mono">${cityNumber(person.votes)}</span>
      <span class="city-bar"><i style="width:${(Number(person.votes) / top * 100).toFixed(1)}%"></i></span>
      ${cityProfileButton(person.profileId)}</li>`).join('')}</ol>
    ${citySource(data.sources?.votes, 'TSE — votação por município')}`;
}

function cityStateDetail(data, isDf) {
  const people = Array.isArray(data.stateElected) ? data.stateElected : [];
  if (!people.length) return `${cityUnavailable(data.messages?.generalElection, 'Os resultados de 2026 não estão disponíveis para este estado.')}${citySource(data.sources?.generalElection, 'TSE — eleição geral')}`;
  const byKey = key => people.filter(person => cityOfficeKey(person.office) === key);
  const row = person => {
    const result = cityResultText(person, '25/10');
    return `<li><span><b>${esc(cityPersonName(person))}</b><small class="muted">${esc(person.party || '')}${result ? ` · <span class="city-tag">${esc(result)}</span>` : ''}</small></span>${cityProfileButton(person.profileId)}</li>`;
  };
  const group = (title, list) => list.length ? `<div class="citizen-detail-part"><h3 class="k">${esc(title)} · ${list.length}</h3><ul class="city-name-list city-people">${list.map(row).join('')}</ul></div>` : '';
  return `<p class="muted">Eleitos(as) em 4/10/2026. Os mandatos começam em 2027; até lá, seguem os atuais.</p>
    ${group(isDf ? 'Governo do Distrito Federal' : 'Governo do estado', [...byKey('governor'), ...byKey('vice')])}
    ${group(isDf ? 'Deputados(as) distritais' : 'Deputados(as) estaduais', [...byKey('stateDeputy'), ...byKey('districtDeputy')])}
    ${group('Deputados(as) federais', byKey('federalDeputy'))}
    ${group('Senadores(as)', byKey('senator'))}
    ${citySource(data.sources?.generalElection, 'TSE — eleição geral')}`;
}

function cityCongressDetail(data) {
  const people = Array.isArray(data.currentFederal) ? data.currentFederal : [];
  if (!people.length) return cityUnavailable(data.messages?.currentFederal, 'A lista atual do Congresso não está disponível.');
  const row = person => `<li><span><b>${esc(cityTitleCase(person.name))}</b><small class="muted">${esc(person.party || '')}</small></span>${cityProfileButton(person.id)}</li>`;
  const chamber = people.filter(person => String(person.id || '').startsWith('camara:'));
  const senate = people.filter(person => String(person.id || '').startsWith('senado:'));
  return `<p class="muted">Quem está no mandato hoje, eleito(a) pelo estado inteiro. Não necessariamente mora nesta cidade.</p>
    ${senate.length ? `<div class="citizen-detail-part"><h3 class="k">Senado · ${senate.length}</h3><ul class="city-name-list city-people">${senate.map(row).join('')}</ul>${citySource(data.sources?.currentFederal?.senado, 'Lista atual do Senado')}</div>` : ''}
    ${chamber.length ? `<div class="citizen-detail-part"><h3 class="k">Câmara dos Deputados · ${chamber.length}</h3><ul class="city-name-list city-people">${chamber.map(row).join('')}</ul>${citySource(data.sources?.currentFederal?.camara, 'Lista atual da Câmara')}</div>` : ''}`;
}

function cityAccountsDetail(data, isDf, isFernando) {
  const accounts = data.accounts && typeof data.accounts === 'object' ? data.accounts : {};
  const metrics = Array.isArray(accounts.metrics) ? accounts.metrics.filter(metric => metric && typeof metric === 'object') : [];
  if (!cityAccountsUsable(accounts) || !metrics.length) return `${cityUnavailable(cityAccountsMessage(accounts, isDf, isFernando), 'As contas não estão disponíveis.')}${citySource(accounts.source, 'Tesouro Nacional')}`;
  const comparison = accounts.comparison || {};
  const rows = metrics.map(metric => {
    const typical = cityAccountTypical(accounts, metric.id), typicalValue = cityTypicalPerResident(accounts, metric.id);
    const typicalText = !comparison.available ? 'Sem comparação'
      : typicalValue !== null ? cityPerResident(typicalValue)
        : Number(typical?.perCapitaSampleSize ?? typical?.sampleSize) < 3 ? 'Menos de 3 cidades para comparar' : 'Não informado';
    return `<div class="city-account-row"><b>${esc(CITY_ACCOUNT_LABELS[metric.id] || metric.label || 'Indicador')}</b>
      <div><span>Total</span><b class="mono">${cityExactCompact(metric.amountCents)}</b></div>
      <div><span>Por morador</span><b class="mono">${cityPerResident(metric.perCapitaCents) || 'Não informado'}</b></div>
      <div><span>Típico por morador</span><b class="mono">${esc(typicalText)}</b></div></div>`;
  }).join('');
  const peers = Number.isInteger(comparison.reportingCount) ? comparison.reportingCount : null;
  return `${accounts.status !== 'available' && accounts.message ? `<p class="note">${esc(accounts.message)}</p>` : ''}
    <div class="city-account-table">${rows}</div>
    ${comparison.available ? `<p class="muted"><b>Típico</b> é o valor do meio (mediana) por morador entre ${peers ? `${cityNumber(peers)} ` : ''}${esc(cityBandText(comparison.band))} com contas de ${esc(cityYear(accounts.year) || 'mesmo ano')}. A própria cidade fica de fora. Não é meta nem ranking.</p>`
      : `<p class="muted">${esc(comparison.message || 'Comparação com cidades do mesmo porte indisponível.')}</p>`}
    <p class="muted">Gasto é o valor empenhado, isto é, os compromissos assumidos no ano, e não só o que já foi pago. Receita e gasto total incluem repasses entre órgãos da própria prefeitura; pessoal, saúde e educação não. Saúde e educação também incluem salários, então as linhas não devem ser somadas. Pessoal aqui não é o limite da Lei de Responsabilidade Fiscal.</p>
    ${citySource(accounts.source, 'Tesouro Nacional')}`;
}

function cityAmendmentsDetail(data) {
  const amendments = data.amendments && typeof data.amendments === 'object' ? data.amendments : {};
  const records = Number(amendments.recordCount) > 0 ? Number(amendments.recordCount) : 0;
  if (!records || !['available', 'partial', 'stale'].includes(amendments.status)) return null;
  const totals = amendments.totals || {};
  const figure = (label, cents, note) => `<div class="city-figure"><span class="k">${label}</span><b class="mono">${cityExactCompact(cents)}</b><small class="muted">${note}</small></div>`;
  const special = amendments.specialTransfers;
  const specialCount = Number(special?.recordCount) > 0 ? Number(special.recordCount) : 0;
  const authors = (Array.isArray(amendments.authors) ? amendments.authors : []).filter(Boolean)
    .sort((left, right) => Number(right.committedCents || 0) - Number(left.committedCents || 0));
  return `${amendments.message && amendments.status !== 'available' ? `<p class="note">${esc(amendments.message)}</p>` : ''}
    <div class="city-figures">${figure('Reservado', totals.committedCents, 'Empenhado: compromisso, ainda não é pagamento.')}${figure('Pago', totals.paidCents, 'Já saiu do caixa federal.')}${figure('Restos a pagar pagos', totals.restosPaidCents, 'Pago agora, de compromisso de ano anterior.')}</div>
    ${special?.identified === true ? `<p class="muted">${specialCount ? `Destas, ${specialCount} ${specialCount === 1 ? 'é transferência especial' : 'são transferências especiais'} (“emendas Pix”), com ${esc(cityMoneyFromCents(special.totals?.committedCents) || 'valor não informado')} reservados. Esses valores já estão incluídos acima.` : 'Nenhuma é transferência especial (“emenda Pix”).'}</p>` : ''}
    ${authors.length ? `<div class="citizen-detail-part"><h3 class="k">Quem destinou · ${authors.length}</h3><ol class="city-name-list city-people city-authors">${authors.map(author => `<li><span>${esc(cityTitleCase(author.name) || 'Autoria não identificada')}${Array.isArray(author.types) && author.types.length ? `<small class="muted">${author.types.map(esc).join(' · ')}</small>` : ''}</span>
      <span class="mono">${cityExactCompact(author.committedCents)}<small class="muted">pago: ${cityHasCents(author.paidCents) ? cityExactCompact(author.paidCents) : 'não informado'}</small></span>${cityProfileButton(author.profileId)}</li>`).join('')}</ol></div>` : ''}
    <p class="muted">O ano é o da proposta da emenda; o pagamento pode acontecer depois. Só entram emendas que informam esta cidade como destino.</p>
    ${citySource(amendments.source, 'Portal da Transparência')}`;
}

function citySourcesDetail(data) {
  const sources = data.sources || {}, accounts = data.accounts || {}, amendments = data.amendments || {};
  const items = [
    ['População', sources.population], ['Lista de municípios', sources.municipalities],
    ['Eleição municipal de 2024', sources.municipalElection], ['Eleição geral de 2026', sources.generalElection],
    ['Votos por cidade', sources.votes], ['Códigos TSE e IBGE', sources.tseIbgeMapping],
    ['Lista atual da Câmara', sources.currentFederal?.camara], ['Lista atual do Senado', sources.currentFederal?.senado],
    ['Emendas parlamentares', amendments.source], ['Contas da prefeitura', accounts.source],
    ['População usada na comparação', accounts.comparison?.populationSource],
  ].filter(([, source]) => source && typeof source === 'object' && (source.label || source.url));
  const methods = [accounts.comparison?.method, data.profileLinks?.method ? `Ligação com as fichas: ${data.profileLinks.method}` : null,
    amendments.profileLinks?.method ? `Autorias de emendas: ${amendments.profileLinks.method}` : null].filter(Boolean);
  return `<div class="citizen-source-list">${items.map(([label, source]) => `<article class="citizen-source"><b>${esc(label)}</b>${citySource(source, label)}</article>`).join('')}</div>
    ${methods.map(method => `<p class="muted">${esc(method)}</p>`).join('')}
    ${data.generatedAt ? `<p class="muted">Base montada em ${esc(cityReadableDate(data.generatedAt))}.</p>` : ''}`;
}

function cityDetailView() {
  if (!cityViewState.selectedId || !cityViewState.selectedCity) return cityPickerView();
  const back = '<button type="button" class="back" data-city-search>‹ Trocar de cidade</button>';
  if (cityViewState.detailLoading && !cityViewState.detail) return `${back}${pageHead('Minha cidade', esc(cityViewState.selectedCity.name || 'Carregando cidade…'), 'Juntando eleições, contas e emendas desta cidade.')}${skel('ficha', 2)}`;
  if (cityViewState.detailError && !cityViewState.detail) return `${back}${pageHead('Minha cidade', 'Não foi possível abrir esta cidade', 'Os dados não carregaram.')}
    <section class="card" role="alert"><p class="muted">${esc(cityViewState.detailError)}</p><button type="button" class="opt" data-city-retry-detail>Tentar de novo</button></section>`;
  const data = cityViewState.detail;
  if (!data || !data.municipality) return `${back}${pageHead('Minha cidade', 'Dados indisponíveis', 'A resposta não trouxe os dados desta cidade.')}
    <section class="card"><p>Não foi possível montar a página desta cidade.</p><button type="button" class="opt" data-city-retry-detail>Tentar de novo</button></section>`;
  const municipality = data.municipality, isDf = cityIsBrasilia(municipality), isFernando = cityIsFernandoDeNoronha(municipality);
  const name = municipality.name || 'Cidade', id = String(municipality.id || cityViewState.selectedId);
  const population = cityPopulationText(municipality.population), year = cityYear(municipality.populationYear);
  const uf = municipality.uf || '';
  const accountsYear = cityYear(data.accounts?.year);
  const amendmentsYear = Number.isInteger(data.amendments?.year) ? data.amendments.year : null;
  const sections = [
    ['council', `Vereadores(as) eleitos(as) em 2024`, cityCouncilDetail(data)],
    ['votes', `Em quem ${name} votou para deputado(a) federal`, isFernando ? null : cityVotesDetail(data)],
    ['state', `${isDf ? 'Eleitos(as) em 2026 no DF' : `Eleitos(as) em 2026 em ${uf}`} · assumem em 2027`, cityStateDetail(data, isDf)],
    ['congress', `Quem representa ${uf} no Congresso hoje`, cityCongressDetail(data)],
    ['accounts', `Contas da prefeitura${accountsYear ? ` em ${accountsYear}` : ''}`, isDf || isFernando ? null : cityAccountsDetail(data, isDf, isFernando)],
    ['amendments', `Emendas para ${name}${amendmentsYear ? ` em ${amendmentsYear}` : ''}`, cityAmendmentsDetail(data)],
    ['sources', 'Fontes e datas', citySourcesDetail(data)],
  ].filter(([, , content]) => typeof content === 'string' && content.trim());
  return `${back}
    <header class="city-head"><span class="k">Minha cidade · ${esc(uf)}</span><h1 class="h city-title">${esc(name)}</h1>
      <p class="city-sub">${population ? `${esc(population)}${year ? ` <span class="muted">· estimativa de ${esc(year)}</span>` : ''}` : 'População não informada'}</p></header>
    <span class="k citizen-answer-label">${esc(name)} em 3 respostas</span>
    <div class="citizen-answers city-answers">${cityGovernAnswer(data, isDf, isFernando)}${citySpendAnswer(data, isDf, isFernando)}${cityAmendmentsAnswer(data, name)}</div>
    <h2 class="h">Ver mais</h2>
    <div class="citizen-details city-details">${sections.map(([key, title, content]) => cityAccordion(id, key, title, content)).join('')}</div>
    <span class="src">Dados públicos do IBGE, do TSE, do Portal da Transparência e do Tesouro Nacional. Datas e métodos em “Fontes e datas”.</span>`;
}

function cityPickerView() {
  const query = cityViewState.query;
  return `${pageHead('Onde você mora', 'Minha cidade', 'Digite sua cidade e veja quem governa, quanto a prefeitura gasta por morador e quanto dinheiro de emendas chegou.')}
    <section class="card city-search-card"><label class="k" for="city-search">Sua cidade</label>
      <div class="city-search-row"><div class="search"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg><input id="city-search" type="search" value="${esc(query)}" placeholder="Ex.: Guarulhos" autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="city-suggestions"></div><button type="button" class="fchip" data-city-search-submit>Buscar</button></div>
      <div id="city-results" class="city-results" aria-live="polite">${citySearchResultsMarkup()}</div>
      <div id="city-search-source">${cityViewState.searchSource ? citySource(cityViewState.searchSource, 'Lista de municípios') : ''}</div>
    </section>`;
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
