/* Datas na tela sempre em dia/mês/ano. Carregado antes das outras telas. */
/* "2026-10-07" ou "2026-10-07T12:00:00Z" viram "07/10/2026"; outro formato volta como veio. */
function dateBR(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:$|[T ])/.exec(String(value ?? ''));
  return match ? `${match[3]}/${match[2]}/${match[1]}` : value == null ? '' : String(value);
}
/* Textos das fontes ("apresentados de 2026-01-01 a 2026-10-07") com as datas em dia/mês/ano.
   Só para texto corrido: URLs e atributos ficam como vieram. */
function datesInTextBR(text) {
  return text == null ? '' : String(text).replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, (_, y, m, d) => `${d}/${m}/${y}`);
}
