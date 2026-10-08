/* Compartilhar ficha e comparações como imagem (PNG 4:5, bom para redes sociais).
   Cada tela monta um cartão com os mesmos números que mostra; aqui só desenhamos e entregamos o arquivo.
   O cartão é desenhado em canvas, sem fotos de outros domínios (elas impediriam exportar a imagem). */
const SHARE_STATE = { card: null, busy: false, message: '' };
const SHARE_SIZE = { width: 1080, height: 1350, padding: 72 };
const SHARE_COLORS = { bg: '#F4F5F7', surface: '#FFFFFF', ink: '#111318', ink2: '#3B3F48', muted: '#5B606B', line: '#E3E5EA', accent: '#5B3DF5' };
const SHARE_FONTS = { display: "'Newsreader', Georgia, serif", body: "'Geist', system-ui, sans-serif", data: "'Geist Mono', ui-monospace, monospace" };
const SHARE_DISCLAIMER = 'Projeto pessoal e apartidário com dados públicos oficiais. Alertas não indicam irregularidade.';

/* card: { kicker, title, subtitle?, columns?: [nome, nome], rows: [{ label, values: [..], notes?: [..] }], footnote, fileName } */
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
    await Promise.all(['400 24px Geist', '600 24px Geist', '700 24px "Geist Mono"', '500 48px Newsreader']
      .map(font => document.fonts.load(font)));
  } catch (error) { /* Sem as fontes do site, o canvas usa as de reserva. */ }
}

function shareDrawCard(card, canvas) {
  const { width, height, padding } = SHARE_SIZE;
  const inner = width - padding * 2;
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  context.textBaseline = 'alphabetic';
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
        await navigator.share({ files: [file], title: card.title, text: `${card.title} · Painel Público ${location.origin}` });
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
