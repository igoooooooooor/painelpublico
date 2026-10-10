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
   ou, na comparação de políticos, { layout: 'faceoff', title, people: [{ name, meta, stats, categories, top }] x2, agreement, alerts, footnote, fileName }. */
function shareActionsHTML(card) {
  if (SHARE_STATE.card?.fileName !== card?.fileName) SHARE_STATE.message = '';
  SHARE_STATE.card = card;
  if (!card) return '';
  return `<div class="share-actions" role="group" aria-label="Compartilhar">
    <button type="button" class="fchip" data-share="image"${SHARE_STATE.busy ? ' disabled' : ''}>Compartilhar imagem</button>
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

function sharePill(context, text, x, y, color) {
  context.font = shareFont(700, 18);
  const width = context.measureText(text).width + 28;
  shareRoundRect(context, x, y, width, 34, 17, color);
  context.fillStyle = SHARE_DARK.bg;
  context.fillText(text, x + 14, y + 23);
}

/* Dois cards lado a lado (custo, presença, cota por categoria, maior nota), votos em comum e alertas embaixo. */
function shareDrawFaceoff(card, context) {
  const { width, height } = SHARE_SIZE, padding = 56, gap = 18;
  const cardWidth = (width - padding * 2 - gap) / 2, inner = cardWidth - 56, cardTop = padding, cardHeight = 900;
  context.fillStyle = SHARE_DARK.bg;
  context.fillRect(0, 0, width, height);
  card.people.slice(0, 2).forEach((person, index) => {
    const color = SHARE_DARK.people[index], left = padding + index * (cardWidth + gap), x = left + 28;
    shareRoundRect(context, left, cardTop, cardWidth, cardHeight, 28, SHARE_DARK.surface);
    // Nome: uma linha grande; se não couber, duas menores.
    context.fillStyle = color;
    context.font = shareFont(600, 50, SHARE_FONTS.display);
    let y = cardTop + 28;
    const oneLine = context.measureText(person.name).width <= inner;
    const nameLines = oneLine ? [person.name] : shareWrap(context, person.name, inner, 2).length > 1 ? (context.font = shareFont(600, 38, SHARE_FONTS.display), shareWrap(context, person.name, inner, 2)) : [person.name];
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
    y += 14;
    const categories = person.categories || [];
    if (categories.length) {
      const colors = [color, ...SHARE_DARK.others];
      let barX = x;
      categories.forEach((category, position) => {
        const segment = Math.max(4, inner * category.share - 3);
        shareRoundRect(context, barX, y, segment, 18, 4, colors[position]);
        barX += segment + 3;
      });
      if (barX < x + inner - 4) shareRoundRect(context, barX, y, x + inner - barX, 18, 4, SHARE_DARK.rest);
      y += 18;
      categories.forEach((category, position) => {
        y += 36;
        shareRoundRect(context, x, y - 13, 12, 12, 3, colors[position]);
        const share = `${Math.round(category.share * 100)}%`;
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
      context.fillText('Sem notas da cota no período', x, y);
    }
    // Maior nota única, com categoria, mês e fornecedor.
    y = cardTop + cardHeight - 160;
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
    context.fillText('Votaram igual em', padding + 28, y + 62);
    const labelWidth = context.measureText('Votaram igual em').width;
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
  context.fillText('Alertas na cota', padding + 28, y);
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
  const notes = [...shareWrap(context, card.footnote || '', width - padding * 2 - 200, 2), ...shareWrap(context, SHARE_DISCLAIMER, width - padding * 2 - 200, 2)];
  let footY = height - 48 - (notes.length - 1) * 22;
  for (const line of notes) { context.fillText(line, padding, footY); footY += 22; }
  context.textAlign = 'right';
  context.fillStyle = SHARE_DARK.muted;
  context.font = shareFont(600, 16, SHARE_FONTS.data);
  context.fillText(SHARE_SITE, width - padding, height - 48);
  context.textAlign = 'left';
  return context.canvas;
}

function shareDrawCard(card, canvas) {
  const { width, height, padding } = SHARE_SIZE;
  const inner = width - padding * 2;
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  context.textBaseline = 'alphabetic';
  if (card.layout === 'faceoff') return shareDrawFaceoff(card, context);
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
    const blob = await shareCanvasBlob(shareDrawCard(card, document.createElement('canvas')));
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
