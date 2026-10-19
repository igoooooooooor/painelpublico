/* Compartilhar ficha e comparações como imagem (PNG 4:5, bom para redes sociais).
   Cada tela monta um cartão com os mesmos números que mostra; aqui só desenhamos e entregamos o arquivo.
   O cartão é desenhado em canvas, sem fotos de outros domínios (elas impediriam exportar a imagem). */
const SHARE_STATE = { card: null, busy: false, message: '' };
const SHARE_SIZE = { width: 1080, height: 1350, padding: 72 };
const SHARE_COLORS = { bg: '#F4F5F7', surface: '#FFFFFF', ink: '#111318', ink2: '#3B3F48', muted: '#5B606B', line: '#E3E5EA', accent: '#5B3DF5' };
const SHARE_FONTS = { display: "'Newsreader', Georgia, serif", body: "'Geist', system-ui, sans-serif", data: "'Geist Mono', ui-monospace, monospace" };
const SHARE_DISCLAIMER = 'Projeto pessoal e apartidário com dados públicos oficiais. Alertas não indicam irregularidade.';
/* Comparação de políticos: tema escuro, uma cor para cada pessoa (só distingue os lados). */
const SHARE_DARK = { bg: '#0E0F13', surface: '#17191F', ink: '#ECEDF1', ink2: '#C9CCD4', muted: '#A2A7B2', faint: '#6B707B', behind: '#8A8F9A',
  line: '#2A2D36', track: '#3A3E48', people: ['#A898FA', '#FF9A6B'], others: ['#6B707B', '#4E535E'], rest: '#22252D' };
const SHARE_SITE = 'painelpublico.com';

/* card: { kicker, title, subtitle?, columns?: [nome, nome], rows: [{ label, values: [..], notes?: [..] }], footnote, fileName }
   ou, na comparação de políticos, { layout: 'faceoff', title, people: [{ name, meta, stats, categories, top }] x2, agreement, alerts, footnote, fileName }
   ou, na ficha, { layout: 'profile', title, initials, kicker, subtitle, cost, presence, categories, top, footnote, disclaimer, fileName }. */
function shareActionsHTML(card, label = 'Compartilhar imagem') {
  if (SHARE_STATE.card?.fileName !== card?.fileName) SHARE_STATE.message = '';
  SHARE_STATE.card = card;
  if (!card) return '';
  sharePrefetchPhotos(card);
  return `<div class="share-actions" role="group" aria-label="Compartilhar">
    <button type="button" class="fchip" data-share="image"${SHARE_STATE.busy ? ' disabled' : ''}>${esc(label)}</button>
    <span class="share-status muted" role="status">${esc(SHARE_STATE.message)}</span>
  </div>`;
}

function shareSlug(text) {
  return String(text || 'painel').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'painel';
}

function shareFont(weight, size, family = SHARE_FONTS.body) {
  return `${weight} ${size}px ${family}`;
}

/* Quebra em linhas que cabem na largura; a última linha ganha reticências se faltar espaço. */
function shareWrap(context, text, maxWidth, maxLines) {
  const words = String(text ?? '').split(/\s+/).filter(Boolean);
  const lines = [];
  let line = '';
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (context.measureText(candidate).width <= maxWidth || !line) line = candidate;
    else { lines.push(line); line = word; }
  }
  if (line) lines.push(line);
  if (lines.length <= maxLines) return lines;
  const kept = lines.slice(0, maxLines);
  let last = kept[maxLines - 1];
  while (last && context.measureText(`${last}…`).width > maxWidth) last = last.slice(0, -1);
  kept[maxLines - 1] = `${last.trimEnd()}…`;
  return kept;
}

/* Reduz a fonte até o texto caber numa linha. */
function shareFit(context, text, maxWidth, size, weight, family, minimum = 18) {
  let current = size;
  context.font = shareFont(weight, current, family);
  while (current > minimum && context.measureText(String(text)).width > maxWidth) {
    current -= 2;
    context.font = shareFont(weight, current, family);
  }
  return current;
}

function shareRoundRect(context, x, y, width, height, radius, color) {
  context.fillStyle = color;
  context.beginPath();
  context.roundRect(x, y, width, height, radius);
  context.fill();
}

async function shareFontsReady() {
  if (!document.fonts?.load) return;
  try {
    await Promise.all(['400 24px Geist', '600 24px Geist', '700 24px "Geist Mono"', '500 48px Newsreader', '600 48px Newsreader', '600 24px "Geist Mono"']
      .map(font => document.fonts.load(font)));
  } catch (error) { /* Sem as fontes do site, o canvas usa as de reserva. */ }
}

/* "Para onde vai a cota": as 3 maiores categorias e "Outras" com o resto, em porcentagens inteiras que somam 100. */
function shareQuotaLegend(categories) {
  const top = (categories || []).filter(category => Number.isFinite(category?.share) && category.share > 0).slice(0, 3);
  const rounded = top.map(category => Math.round(category.share * 100));
  const legend = top.map((category, index) => ({ name: category.name, share: category.share, pct: rounded[index] }));
  const rest = 1 - top.reduce((sum, category) => sum + category.share, 0);
  if (top.length && rest > 0.004) legend.push({ name: 'Outras', share: rest, pct: Math.max(0, 100 - rounded.reduce((sum, value) => sum + value, 0)), rest: true });
  return legend;
}

/* Shares use positive category balances; negative balances remain outside the distribution. */
function shareQuotaCategories(categories, limit = 3) {
  const rows = Array.isArray(categories) ? categories : [];
  const positive = rows.filter(category => Number.isFinite(category?.valor) && category.valor > 0);
  const total = positive.reduce((sum, category) => sum + category.valor, 0);
  return {
    total,
    items: total > 0 ? positive.slice(0, limit).map(category => ({
      name: category.nome || category.name || 'Categoria não informada',
      share: category.valor / total,
    })) : [],
    hasRefunds: rows.some(category => Number.isFinite(category?.valor) && category.valor < 0),
  };
}

/* Fotos oficiais pelo próprio domínio (/api/c/foto/...), para não contaminar o canvas. Cada uma tem 9 s para
   carregar (o servidor desiste da fonte em 8 s); sem foto, o card usa as iniciais. */
const SHARE_PHOTO_PATH = /^\/api\/c\/foto\/(camara|senado)%3A\d+$/;
function sharePhotoUrl(id) {
  return /^(camara|senado):\d+$/.test(String(id || '')) ? `/api/c/foto/${encodeURIComponent(id)}` : null;
}
// Pede as fotos assim que a tela abre: quando a pessoa tocar em compartilhar, o servidor já tem a foto em cache.
const SHARE_PREFETCHED = new Set();
const sharePhotoUrls = card => [card?.photo, ...(card?.people || []).map(person => person?.photo)].filter(url => SHARE_PHOTO_PATH.test(String(url || '')));
function sharePrefetchPhotos(card) {
  if (typeof Image !== 'function') return;
  for (const url of sharePhotoUrls(card)) {
    if (SHARE_PREFETCHED.has(url)) continue;
    SHARE_PREFETCHED.add(url);
    const image = new Image();
    image.onerror = () => SHARE_PREFETCHED.delete(url);
    image.src = url;
  }
}
async function shareLoadImages(card) {
  const images = new Map();
  if (typeof fetch !== 'function' || typeof createImageBitmap !== 'function') return images;
  await Promise.all([...new Set(sharePhotoUrls(card))].map(async url => {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 9000);
    try {
      const response = await fetch(url, { signal: controller.signal });
      if (response.ok && (response.headers.get('Content-Type') || '').startsWith('image/')) images.set(url, await createImageBitmap(await response.blob()));
    } catch (error) { /* fica com as iniciais */ } finally { clearTimeout(timer); }
  }));
  return images;
}
/* Foto recortada em círculo, preenchendo o círculo e alinhada pelo alto (o rosto fica na parte de cima). */
function shareDrawPhoto(context, image, cx, cy, radius) {
  const imageWidth = image.naturalWidth || image.width, imageHeight = image.naturalHeight || image.height;
  const side = Math.min(imageWidth, imageHeight);
  const sx = (imageWidth - side) / 2, sy = Math.max(0, (imageHeight - side) * 0.15);
  context.save();
  context.beginPath(); context.arc(cx, cy, radius, 0, Math.PI * 2); context.closePath(); context.clip();
  context.drawImage(image, sx, sy, side, side, cx - radius, cy - radius, radius * 2, radius * 2);
  context.restore();
}
const sharePhotoCredit = sources => sources.length ? ` ${sources.length > 1 ? 'Fotos' : 'Foto'}: ${[...new Set(sources)].join(' e ')}.` : '';

function sharePill(context, text, x, y, color) {
  context.font = shareFont(700, 18);
  const width = context.measureText(text).width + 28;
  shareRoundRect(context, x, y, width, 34, 17, color);
  context.fillStyle = SHARE_DARK.bg;
  context.fillText(text, x + 14, y + 23);
}

/* Dois cards lado a lado (custo, presença, cota por categoria, maior nota), votos em comum e alertas embaixo. */
function shareDrawFaceoff(card, context, images = new Map()) {
  const { width, height } = SHARE_SIZE, padding = 56, gap = 18;
  const cardWidth = (width - padding * 2 - gap) / 2, inner = cardWidth - 56, cardTop = padding, cardHeight = 900;
  context.fillStyle = SHARE_DARK.bg;
  context.fillRect(0, 0, width, height);
  const credits = [];
  card.people.slice(0, 2).forEach((person, index) => {
    const color = SHARE_DARK.people[index], left = padding + index * (cardWidth + gap), x = left + 28;
    shareRoundRect(context, left, cardTop, cardWidth, cardHeight, 28, SHARE_DARK.surface);
    // Foto oficial no canto, com um anel na cor da pessoa; sem foto, o nome usa a largura toda.
    const portrait = images.get(person.photo), photoSize = 84;
    if (portrait) {
      const pcx = left + cardWidth - 28 - photoSize / 2, pcy = cardTop + 28 + photoSize / 2;
      context.fillStyle = color; context.beginPath(); context.arc(pcx, pcy, photoSize / 2 + 3, 0, Math.PI * 2); context.fill();
      shareDrawPhoto(context, portrait, pcx, pcy, photoSize / 2);
      if (person.photoCredit) credits.push(person.photoCredit);
    }
    const nameWidth = portrait ? inner - photoSize - 16 : inner;
    // Nome: uma linha grande; se não couber, duas menores.
    context.fillStyle = color;
    context.font = shareFont(600, 50, SHARE_FONTS.display);
    let y = cardTop + 28;
    const oneLine = context.measureText(person.name).width <= nameWidth;
    // Duas linhas menores; se ainda não couber, diminui mais antes de cortar o nome.
    let nameLines = [person.name];
    if (!oneLine) {
      for (const size of [38, 32, 28]) {
        context.font = shareFont(600, size, SHARE_FONTS.display);
        nameLines = shareWrap(context, person.name, nameWidth, 2);
        if (!nameLines.at(-1).endsWith('…')) break;
      }
    }
    for (const line of nameLines) { y += oneLine ? 46 : 38; context.fillText(line, x, y); }
    context.fillStyle = SHARE_DARK.muted;
    context.font = shareFont(600, 19, SHARE_FONTS.data);
    y += 32;
    context.fillText(String(person.meta || '').toUpperCase(), x, y);
    y = Math.max(y, cardTop + 140);
    // Custo e presença: número grande, etiqueta na cor da pessoa só para quem leva.
    for (const stat of person.stats || []) {
      y += 32;
      context.fillStyle = SHARE_DARK.muted;
      context.font = shareFont(400, 18);
      context.fillText(shareWrap(context, stat.label, inner, 1)[0] || '', x, y);
      const available = stat.value !== 'Sem dados';
      context.fillStyle = !available ? SHARE_DARK.muted : stat.behind ? SHARE_DARK.behind : SHARE_DARK.ink;
      const size = shareFit(context, stat.value, inner, available ? 66 : 40, 700, SHARE_FONTS.data, 28);
      y += size + 6;
      context.fillText(stat.value, x, y);
      if (stat.tag) sharePill(context, stat.tag, x, y + 16, color);
      y += 70;
    }
    // Para onde vai a cota: barra com as 3 maiores categorias e o resto.
    y += 18;
    context.fillStyle = SHARE_DARK.line;
    context.fillRect(x, y, inner, 1);
    y += 38;
    context.fillStyle = SHARE_DARK.muted;
    context.font = shareFont(400, 18);
    context.fillText('Onde vai a cota', x, y);
    if (person.categoryNote) {
      y += 18;
      context.fillStyle = SHARE_DARK.behind;
      context.font = shareFont(400, 14);
      for (const line of shareWrap(context, person.categoryNote, inner, 2)) { y += 16; context.fillText(line, x, y); }
    }
    y += person.categoryNote ? 8 : 14;
    const categories = shareQuotaLegend(person.categories);
    if (categories.length) {
      const colors = [color, ...SHARE_DARK.others];
      const colorOf = (category, position) => category.rest ? SHARE_DARK.track : colors[position];
      let barX = x;
      categories.forEach((category, position) => {
        const barHeight = person.categoryNote ? 14 : 18;
        const segment = position === categories.length - 1 ? x + inner - barX : Math.max(4, inner * category.share - 3);
        if (segment > 0) shareRoundRect(context, barX, y, segment, barHeight, 4, colorOf(category, position));
        barX += segment + 3;
      });
      y += person.categoryNote ? 14 : 18;
      categories.forEach((category, position) => {
        y += person.categoryNote ? 26 : 34;
        shareRoundRect(context, x, y - 13, 12, 12, 3, colorOf(category, position));
        const share = `${category.pct}%`;
        context.font = shareFont(600, 19, SHARE_FONTS.data);
        const shareWidth = context.measureText(share).width;
        context.fillStyle = SHARE_DARK.ink;
        context.textAlign = 'right';
        context.fillText(share, x + inner, y);
        context.textAlign = 'left';
        context.font = shareFont(400, 19);
        context.fillText(shareWrap(context, category.name, inner - shareWidth - 40, 1)[0] || '', x + 22, y);
      });
    } else {
      y += 30;
      context.fillStyle = SHARE_DARK.muted;
      context.font = shareFont(400, 19);
      context.fillText(person.categoryEmptyLabel || 'Sem notas da cota no período', x, y);
    }
    // Rodapé do card: medidor (partidos) ou maior nota única, com categoria, mês e fornecedor.
    y = cardTop + cardHeight - 160;
    if (person.meter) {
      const meter = person.meter;
      context.fillStyle = SHARE_DARK.line;
      context.fillRect(x, y, inner, 1);
      y += 40;
      context.fillStyle = SHARE_DARK.muted;
      context.font = shareFont(400, 18);
      context.fillText(meter.label, x, y);
      const value = Number.isFinite(meter.share) ? `${Math.round(meter.share * 100)}%` : 'Sem dados';
      context.textAlign = 'right';
      context.fillStyle = SHARE_DARK.ink;
      context.font = shareFont(700, 32, SHARE_FONTS.data);
      context.fillText(value, x + inner, y + 4);
      context.textAlign = 'left';
      y += 26;
      shareRoundRect(context, x, y, inner, 12, 6, SHARE_DARK.track);
      if (Number.isFinite(meter.share) && meter.share > 0) shareRoundRect(context, x, y, Math.max(12, inner * meter.share), 12, 6, color);
      context.fillStyle = SHARE_DARK.behind;
      context.font = shareFont(400, 16);
      for (const line of shareWrap(context, meter.note || '', inner, 2)) { y += 26; context.fillText(line, x, y + 10); }
      return;
    }
    context.fillStyle = SHARE_DARK.line;
    context.fillRect(x, y, inner, 1);
    y += 34;
    context.fillStyle = SHARE_DARK.muted;
    context.font = shareFont(400, 18);
    context.fillText('Maior nota única', x, y);
    context.fillStyle = SHARE_DARK.ink;
    y += 40;
    shareFit(context, person.top?.value || 'Sem dados', inner, 32, 700, SHARE_FONTS.data, 22);
    context.fillText(person.top?.value || 'Sem dados', x, y);
    context.fillStyle = SHARE_DARK.ink2;
    context.font = shareFont(400, 17);
    for (const line of [person.top?.what, person.top?.who].filter(Boolean)) { y += 26; context.fillText(shareWrap(context, line, inner, 1)[0] || '', x, y); }
  });

  // Votos em comum, com a referência de dois deputados(as) quaisquer quando houver.
  let y = cardTop + cardHeight + gap;
  const boxWidth = width - padding * 2;
  shareRoundRect(context, padding, y, boxWidth, 128, 28, SHARE_DARK.surface);
  const agreement = card.agreement;
  if (agreement) {
    const share = agreement.matching / agreement.total;
    context.fillStyle = SHARE_DARK.ink;
    context.font = shareFont(600, 26);
    const lead = agreement.lead || 'Votaram igual em';
    context.fillText(lead, padding + 28, y + 62);
    const labelWidth = context.measureText(lead).width;
    context.font = shareFont(700, 56, SHARE_FONTS.data);
    context.fillText(`${Math.round(share * 100)}%`, padding + 28 + labelWidth + 14, y + 66);
    context.textAlign = 'right';
    context.fillStyle = SHARE_DARK.muted;
    context.font = shareFont(400, 18);
    context.fillText(`${agreement.matching} de ${agreement.total} ${agreement.source}`, width - padding - 28, y + 40);
    if (Number.isFinite(agreement.typical)) context.fillText(`dois deputados quaisquer: ${Math.round(agreement.typical * 100)}%`, width - padding - 28, y + 66);
    context.textAlign = 'left';
    const barWidth = boxWidth - 56, split = barWidth * share;
    if (split > 2) shareRoundRect(context, padding + 28, y + 92, Math.max(6, split - 2), 12, 6, SHARE_DARK.ink);
    if (barWidth - split > 2) shareRoundRect(context, padding + 28 + split + 2, y + 92, barWidth - split - 2, 12, 6, SHARE_DARK.track);
  } else {
    context.fillStyle = SHARE_DARK.muted;
    context.font = shareFont(500, 24);
    context.fillText('Sem votações em comum para comparar', padding + 28, y + 72);
  }

  // Alertas: só a contagem, sem destaque.
  y += 128 + 46;
  context.fillStyle = SHARE_DARK.ink2;
  context.font = shareFont(400, 21);
  context.fillText(card.alertsLabel || 'Alertas na cota', padding + 28, y);
  const alerts = card.alerts || [];
  context.textAlign = 'right';
  context.font = shareFont(700, 26, SHARE_FONTS.data);
  let alertX = width - padding - 28;
  [[alerts[1] ?? 'Sem dados', SHARE_DARK.people[1]], [' × ', SHARE_DARK.faint], [alerts[0] ?? 'Sem dados', SHARE_DARK.people[0]]].forEach(([text, color]) => {
    context.fillStyle = color;
    context.fillText(text, alertX, y);
    alertX -= context.measureText(text).width;
  });
  context.textAlign = 'left';

  // Rodapé miúdo: fontes, aviso de independência e endereço.
  context.font = shareFont(400, 15);
  context.fillStyle = SHARE_DARK.faint;
  const notes = [...shareWrap(context, `${card.footnote || ''}${sharePhotoCredit(credits)}`, width - padding * 2 - 200, 2), ...shareWrap(context, SHARE_DISCLAIMER, width - padding * 2 - 200, 2)];
  let footY = height - 48 - (notes.length - 1) * 22;
  for (const line of notes) { context.fillText(line, padding, footY); footY += 22; }
  context.textAlign = 'right';
  context.fillStyle = SHARE_DARK.muted;
  context.font = shareFont(600, 16, SHARE_FONTS.data);
  context.fillText(SHARE_SITE, width - padding, height - 48);
  context.textAlign = 'left';
  return context.canvas;
}

/* Ficha: nome grande, custo médio com as partes, presença com a média da Casa, maior nota e para onde vai a cota.
   Mesmo tema escuro das comparações; o violeta é o único destaque. Sem marca no topo: o endereço fica no rodapé. */
function shareDrawProfile(card, context, images = new Map()) {
  const { width, height } = SHARE_SIZE, padding = 56, inner = width - padding * 2, accent = SHARE_DARK.people[0];
  const box = (x, y, w, h, radius = 28) => {
    shareRoundRect(context, x, y, w, h, radius, SHARE_DARK.line);
    shareRoundRect(context, x + 1, y + 1, w - 2, h - 2, radius - 1, SHARE_DARK.surface);
  };
  const label = (text, x, y, maxWidth, size = 20) => {
    context.fillStyle = SHARE_DARK.muted; context.font = shareFont(400, size);
    context.fillText(shareWrap(context, text, maxWidth, 1)[0] || '', x, y);
  };
  context.fillStyle = SHARE_DARK.bg;
  context.fillRect(0, 0, width, height);

  // Quem é: iniciais, tipo de ficha, nome e cargo.
  let y = 56;
  const avatar = 124, cx = padding + avatar / 2, cy = y + avatar / 2;
  context.fillStyle = SHARE_DARK.line; context.beginPath(); context.arc(cx, cy, avatar / 2 + 8, 0, Math.PI * 2); context.fill();
  context.fillStyle = SHARE_DARK.bg; context.beginPath(); context.arc(cx, cy, avatar / 2 + 6, 0, Math.PI * 2); context.fill();
  context.fillStyle = '#262046'; context.beginPath(); context.arc(cx, cy, avatar / 2, 0, Math.PI * 2); context.fill();
  const portrait = images.get(card.photo);
  if (portrait) shareDrawPhoto(context, portrait, cx, cy, avatar / 2);
  else {
    context.fillStyle = '#C9BFFF'; context.font = shareFont(600, 46, SHARE_FONTS.display);
    context.textAlign = 'center'; context.fillText(card.initials || '', cx, cy + 16); context.textAlign = 'left';
  }
  const textX = padding + avatar + 32, textWidth = width - padding - textX;
  context.fillStyle = SHARE_DARK.muted; context.font = shareFont(600, 17, SHARE_FONTS.data);
  context.fillText(String(card.kicker || '').toUpperCase(), textX, y + 18);
  context.fillStyle = SHARE_DARK.ink;
  const nameSize = shareFit(context, card.title, textWidth, 80, 600, SHARE_FONTS.display, 56);
  const nameLines = context.measureText(card.title).width <= textWidth ? [card.title]
    : (context.font = shareFont(600, 52, SHARE_FONTS.display), shareWrap(context, card.title, textWidth, 2));
  let nameY = y + 18 + (nameLines.length > 1 ? 52 : nameSize) + 8;
  for (const line of nameLines) { context.fillText(line, textX, nameY); nameY += 54; }
  context.fillStyle = SHARE_DARK.ink2; context.font = shareFont(400, 23);
  context.fillText(shareWrap(context, card.subtitle || '', textWidth, 1)[0] || '', textX, nameY + (nameLines.length > 1 ? -10 : 0) + 4);

  // Custo: número grande no violeta, valor exato ao lado, barra com as partes e o período.
  y = 244;
  const cost = card.cost || {}, parts = (cost.parts || []).filter(part => part && part.name);
  const costHeight = parts.length ? 396 : 252;
  box(padding, y, inner, costHeight, 32);
  const cx0 = padding + 36, cw = inner - 72;
  label(cost.label || 'Custa em média por mês', cx0, y + 54, cw, 22);
  const hasValue = cost.value && cost.value !== 'Sem dados';
  context.fillStyle = hasValue ? accent : SHARE_DARK.muted;
  const exactWidth = cost.exact ? 230 : 0;
  const valueSize = shareFit(context, cost.value || 'Sem dados', cw - exactWidth, hasValue ? 132 : 64, 700, SHARE_FONTS.data, 48);
  const valueY = y + 74 + valueSize * 0.86;
  context.fillText(cost.value || 'Sem dados', cx0, valueY);
  if (cost.exact) {
    const ex = cx0 + context.measureText(cost.value).width + 26;
    label('valor exato', ex, valueY - 34, 220, 19);
    context.fillStyle = SHARE_DARK.ink; context.font = shareFont(600, 24, SHARE_FONTS.data);
    context.fillText(cost.exact, ex, valueY);
  }
  let py = valueY + 40;
  if (parts.length && Number.isFinite(cost.totalCents) && cost.totalCents > 0) {
    const colors = [accent, SHARE_DARK.faint, SHARE_DARK.others[1], SHARE_DARK.track];
    let bx = cx0;
    parts.forEach((part, index) => {
      if (!Number.isFinite(part.cents) || part.cents <= 0) return;
      const w = Math.max(4, cw * Math.min(1, part.cents / cost.totalCents) - 3);
      shareRoundRect(context, bx, py, Math.min(w, cx0 + cw - bx), 22, 6, colors[index]);
      bx += w + 3;
    });
    py += 22 + 46;
    const colWidth = cw / parts.length;
    parts.forEach((part, index) => {
      const x = cx0 + index * colWidth;
      shareRoundRect(context, x, py - 14, 12, 12, 3, colors[index]);
      label(part.name, x + 20, py - 2, colWidth - 28, 18);
      context.fillStyle = SHARE_DARK.ink; context.font = shareFont(600, 26, SHARE_FONTS.data);
      const value = Number.isFinite(part.cents) ? (part.cents >= 100000 ? `R$ ${Math.round(part.cents / 100000).toLocaleString('pt-BR')} mil` : `R$ ${Math.round(part.cents / 100).toLocaleString('pt-BR')}`) : 'Sem dado';
      context.fillText(value, x, py + 34);
    });
    py += 88;
  }
  context.fillStyle = SHARE_DARK.behind; context.font = shareFont(400, 17);
  for (const line of shareWrap(context, cost.note || '', cw, 2)) { context.fillText(line, cx0, py); py += 24; }

  // Presença e maior nota, lado a lado.
  y += costHeight + 22;
  const tileGap = 18, tileWidth = (inner - tileGap) / 2, tileHeight = 276, tw = tileWidth - 60;
  const presence = card.presence || {};
  box(padding, y, tileWidth, tileHeight);
  let tx = padding + 30, ty = y + 56;
  label(presence.label || 'Presença no Plenário', tx, ty, tw);
  const presenceKnown = presence.value && presence.value !== 'Sem registro';
  context.fillStyle = presenceKnown ? SHARE_DARK.ink : SHARE_DARK.muted;
  const pSize = shareFit(context, presence.value || 'Sem registro', tw * 0.55, presenceKnown ? 72 : 40, 700, SHARE_FONTS.data, 32);
  ty += 22 + pSize * 0.86;
  context.fillText(presence.value || 'Sem registro', tx, ty);
  if (presence.detail) {
    const dx = tx + context.measureText(presence.value).width + 14;
    context.fillStyle = SHARE_DARK.ink2; context.font = shareFont(400, 19);
    context.fillText(shareWrap(context, presence.detail, tx + tw - dx, 1)[0] || '', dx, ty);
  }
  ty += 30;
  if (Number.isFinite(presence.share)) {
    shareRoundRect(context, tx, ty, tw, 12, 6, SHARE_DARK.line);
    shareRoundRect(context, tx, ty, Math.max(12, tw * presence.share), 12, 6, SHARE_DARK.ink);
    if (Number.isFinite(presence.average)) shareRoundRect(context, tx + tw * presence.average - 1.5, ty - 6, 3, 24, 1.5, accent);
    ty += 50;
    if (presence.averageLabel) {
      shareRoundRect(context, tx, ty - 15, 3, 18, 1.5, accent);
      label(presence.averageLabel, tx + 12, ty, tw - 12, 17);
    }
  } else if (presence.note) {
    context.fillStyle = SHARE_DARK.muted; context.font = shareFont(400, 17);
    for (const line of shareWrap(context, presence.note, tw, 3)) { context.fillText(line, tx, ty + 6); ty += 24; }
  }
  const topX = padding + tileWidth + tileGap;
  box(topX, y, tileWidth, tileHeight);
  tx = topX + 30; ty = y + 56;
  label('Maior nota única', tx, ty, tw);
  const top = card.top;
  context.fillStyle = top ? SHARE_DARK.ink : SHARE_DARK.muted;
  const tSize = shareFit(context, top?.value || 'Sem dados', tw, top ? 60 : 40, 700, SHARE_FONTS.data, 30);
  ty += 22 + tSize * 0.86;
  context.fillText(top?.value || 'Sem dados', tx, ty);
  ty += 14;
  if (top) {
    context.fillStyle = SHARE_DARK.ink2; context.font = shareFont(400, 19);
    for (const line of shareWrap(context, top.who, tw, 2)) { ty += 28; context.fillText(line, tx, ty); }
    context.fillStyle = SHARE_DARK.behind; context.font = shareFont(400, 17);
    if (top.what) { ty += 28; context.fillText(shareWrap(context, top.what, tw, 1)[0] || '', tx, ty); }
  }

  // Para onde vai a cota: as 3 maiores categorias e "Outras", que fecham 100% (o resto da barra também tem nome).
  y += tileHeight + 22;
  const legend = shareQuotaLegend(card.categories);
  const catHeight = card.categoryNote ? 260 : 224;
  box(padding, y, inner, catHeight);
  const kx = padding + 30, kw = inner - 60;
  let ky = y + 56;
  label('Para onde vai a cota', kx, ky, kw);
  if (card.categoryNote) {
    ky += 24;
    context.fillStyle = SHARE_DARK.behind; context.font = shareFont(400, 16);
    for (const line of shareWrap(context, card.categoryNote, kw, 2)) { ky += 19; context.fillText(line, kx, ky); }
  }
  ky += 22;
  if (legend.length) {
    const colors = [accent, SHARE_DARK.faint, SHARE_DARK.others[1]];
    const colorOf = (item, index) => item.rest ? SHARE_DARK.track : colors[index];
    let bx = kx;
    legend.forEach((item, index) => {
      const w = index === legend.length - 1 ? kx + kw - bx : Math.max(4, kw * item.share - 3);
      if (w > 0) shareRoundRect(context, bx, ky, w, 16, 5, colorOf(item, index));
      bx += w + 3;
    });
    ky += 16 + 56;
    const colWidth = kw / legend.length;
    legend.forEach((item, index) => {
      const x = kx + index * colWidth;
      shareRoundRect(context, x, ky - 22, 14, 14, 3, colorOf(item, index));
      context.font = shareFont(700, 32, SHARE_FONTS.data); context.fillStyle = SHARE_DARK.ink;
      context.fillText(`${item.pct}%`, x + 24, ky - 6);
      context.fillStyle = SHARE_DARK.ink2; context.font = shareFont(400, 19);
      context.fillText(shareWrap(context, item.name, colWidth - 16, 1)[0] || '', x, ky + 30);
    });
  } else {
    context.fillStyle = SHARE_DARK.muted; context.font = shareFont(400, 19);
    context.fillText(card.categoryEmptyLabel || 'Sem notas da cota no período', kx, ky + 30);
  }

  // Rodapé: fontes, aviso de independência e o endereço do site.
  context.font = shareFont(400, 15);
  context.fillStyle = SHARE_DARK.faint;
  const credit = sharePhotoCredit(portrait && card.photoCredit ? [card.photoCredit] : []);
  const notes = [...shareWrap(context, `${card.footnote || ''}${credit}`, inner - 220, 2), ...shareWrap(context, card.disclaimer || SHARE_DISCLAIMER, inner - 220, 1)];
  let footY = height - 48 - (notes.length - 1) * 22;
  for (const line of notes) { context.fillText(line, padding, footY); footY += 22; }
  context.textAlign = 'right';
  context.fillStyle = SHARE_DARK.muted;
  context.font = shareFont(600, 18, SHARE_FONTS.data);
  context.fillText(SHARE_SITE, width - padding, height - 48);
  context.textAlign = 'left';
  return context.canvas;
}

function shareDrawCard(card, canvas, images = new Map()) {
  const { width, height, padding } = SHARE_SIZE;
  const inner = width - padding * 2;
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  context.textBaseline = 'alphabetic';
  if (card.layout === 'faceoff') return shareDrawFaceoff(card, context, images);
  if (card.layout === 'profile') return shareDrawProfile(card, context, images);
  context.fillStyle = SHARE_COLORS.bg;
  context.fillRect(0, 0, width, height);

  // Marca do site
  let y = padding;
  shareRoundRect(context, padding, y, 56, 56, 16, SHARE_COLORS.accent);
  context.fillStyle = '#FFFFFF';
  [[13, 30, 15], [25, 22, 23], [37, 14, 31]].forEach(([x, top, barHeight], index) => {
    context.globalAlpha = index === 2 ? 0.7 : 1;
    context.beginPath(); context.roundRect(padding + x, y + top, 7, barHeight, 2.5); context.fill();
  });
  context.globalAlpha = 1;
  context.fillStyle = SHARE_COLORS.ink;
  context.font = shareFont(600, 40, SHARE_FONTS.display);
  context.fillText('Painel Público', padding + 76, y + 42);

  // Título
  y += 130;
  context.fillStyle = SHARE_COLORS.muted;
  context.font = shareFont(700, 24, SHARE_FONTS.data);
  context.fillText(String(card.kicker || '').toUpperCase(), padding, y);
  y += 18;
  context.fillStyle = SHARE_COLORS.ink;
  context.font = shareFont(500, 66, SHARE_FONTS.display);
  for (const line of shareWrap(context, card.title, inner, 2)) { y += 72; context.fillText(line, padding, y); }
  if (card.subtitle) {
    y += 46;
    context.fillStyle = SHARE_COLORS.ink2;
    context.font = shareFont(400, 30);
    context.fillText(shareWrap(context, card.subtitle, inner, 1)[0] || '', padding, y);
  }

  const columns = Array.isArray(card.columns) && card.columns.length === 2 ? card.columns : null;
  const gap = 24, columnWidth = (inner - 48 - gap) / 2;
  if (columns) {
    y += 56;
    context.fillStyle = SHARE_COLORS.ink;
    columns.forEach((name, index) => {
      const x = padding + 24 + index * (columnWidth + gap);
      shareFit(context, name, columnWidth, 32, 700, SHARE_FONTS.body);
      context.fillText(shareWrap(context, name, columnWidth, 1)[0] || '', x, y);
    });
  }

  // Linhas de dados em cartões brancos, com altura dividida pelo espaço disponível.
  const footerTop = height - padding - 150;
  const rows = (card.rows || []).slice(0, 6);
  const top = y + 32;
  const rowGap = 16;
  const rowHeight = rows.length ? Math.min(columns ? 190 : 250, (footerTop - top - rowGap * (rows.length - 1)) / rows.length) : 0;
  rows.forEach((row, index) => {
    const rowTop = top + index * (rowHeight + rowGap);
    shareRoundRect(context, padding, rowTop, inner, rowHeight, 28, SHARE_COLORS.surface);
    context.fillStyle = SHARE_COLORS.muted;
    context.font = shareFont(400, 25);
    context.fillText(shareWrap(context, row.label, inner - 48, 1)[0] || '', padding + 24, rowTop + 44);
    const values = (row.values || []).slice(0, columns ? 2 : 1);
    const notes = row.notes || [];
    const slotWidth = columns ? columnWidth : inner - 48;
    const valueSize = columns ? 46 : 64;
    values.forEach((value, valueIndex) => {
      const x = padding + 24 + valueIndex * (columnWidth + gap);
      const text = value ?? 'Sem dados';
      const size = shareFit(context, text, slotWidth, Math.min(valueSize, rowHeight * 0.42), 700, SHARE_FONTS.data);
      context.fillStyle = SHARE_COLORS.ink;
      context.fillText(text, x, rowTop + 50 + size);
      if (notes[valueIndex] && rowHeight >= 150) {
        context.fillStyle = SHARE_COLORS.muted;
        context.font = shareFont(400, 22);
        context.fillText(shareWrap(context, notes[valueIndex], slotWidth, 1)[0] || '', x, rowTop + 50 + size + 36);
      }
    });
  });

  // Rodapé: independência, fontes e data
  context.strokeStyle = SHARE_COLORS.line;
  context.lineWidth = 2;
  context.beginPath(); context.moveTo(padding, footerTop + 16); context.lineTo(width - padding, footerTop + 16); context.stroke();
  context.fillStyle = SHARE_COLORS.ink2;
  context.font = shareFont(400, 22);
  let footY = footerTop + 54;
  for (const line of shareWrap(context, card.footnote || '', inner, 2)) { context.fillText(line, padding, footY); footY += 30; }
  context.fillStyle = SHARE_COLORS.muted;
  for (const line of shareWrap(context, SHARE_DISCLAIMER, inner, 2)) { context.fillText(line, padding, footY); footY += 30; }
  context.fillStyle = SHARE_COLORS.accent;
  context.font = shareFont(700, 24, SHARE_FONTS.data);
  context.fillText(location.host || 'Painel Público', padding, height - padding + 8);
  return canvas;
}

function shareCanvasBlob(canvas) {
  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('imagem')), 'image/png'));
}

function shareDownload(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  try { link.click(); } finally {
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
}

function shareSetStatus(message, busy = SHARE_STATE.busy) {
  SHARE_STATE.message = message;
  SHARE_STATE.busy = busy;
  document.querySelectorAll('.share-status').forEach(element => { element.textContent = message; });
  document.querySelectorAll('[data-share]').forEach(button => { button.disabled = busy; });
}

async function shareCurrentCard() {
  const card = SHARE_STATE.card;
  if (!card || SHARE_STATE.busy) return;
  shareSetStatus('Gerando a imagem…', true);
  try {
    await shareFontsReady();
    const images = await shareLoadImages(card);
    const blob = await shareCanvasBlob(shareDrawCard(card, document.createElement('canvas'), images));
    const name = `painel-publico-${shareSlug(card.fileName || card.title)}.png`;
    const file = typeof File === 'function' ? new File([blob], name, { type: 'image/png' }) : null;
    // No celular, abre a folha de compartilhamento (WhatsApp, Instagram...). No computador, baixa a imagem.
    if (file && navigator.canShare?.({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: card.title, text: `${card.title} · Painel Público ${location.href}` });
        shareSetStatus('', false);
        return;
      } catch (error) {
        if (error?.name === 'AbortError') { shareSetStatus('', false); return; }
      }
    }
    shareDownload(blob, name);
    shareSetStatus('Imagem baixada.', false);
  } catch (error) {
    shareSetStatus('Não deu para gerar a imagem agora. Tente de novo.', false);
  }
}

document.addEventListener('click', event => {
  const button = event.target.closest('[data-share]');
  if (button) shareCurrentCard();
});
