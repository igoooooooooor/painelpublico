/* Metodologia e perguntas (/metodologia) e Sobre o projeto (/sobre).
   Os textos vêm de frontend/data/site-pages.json (DATA.sitePages), o mesmo arquivo que o servidor usa para montar
   estas páginas no HTML inicial: o que o buscador lê é o que a pessoa vê. Ao mudar uma regra, mude lá e em
   docs/alerts.md ou docs/voting-scoreboard.md. */
/* DATA é declarado em app.script.js, que entra no bundle depois desta tela: por isso a leitura é adiada. */
const sitePages = () => (typeof DATA !== 'undefined' && DATA && typeof DATA.sitePages === 'object' && DATA.sitePages) || {};
const methodologyPage = () => sitePages().methodology || { title: 'Como o painel funciona', lead: '', notice: '', sections: [] };
const aboutPage = () => sitePages().about || { title: 'Sobre o Painel Público', lead: '', sections: [] };
const methodologyAnchor = section => `methodology-${section.id}`;
const sitePageIsInternal = url => /^(\/|mailto:)/.test(String(url || ''));
function methodologyAnswer(part) {
  return Array.isArray(part) ? `<ul>${part.map(item => `<li>${esc(item)}</li>`).join('')}</ul>` : `<p>${esc(part)}</p>`;
}
/* Links internos navegam no app; os externos abrem em nova aba, com a seta. */
function sitePageLinks(links = []) {
  if (!links.length) return '';
  return `<p class="methodology-links">${links.map(([label, url]) => sitePageIsInternal(url)
    ? `<a href="${esc(url)}"${/^\/(metodologia|sobre)(#|$)/.test(url) ? ` data-go="${url.startsWith('/sobre') ? 'about' : 'methodology'}"` : ''}>${esc(label)}</a>`
    : `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)} ↗</a>`).join('')}</p>`;
}
function methodologyQuestion({ question, answer = [], links = [] }) {
  return `<details class="methodology-question"><summary>${esc(question)}</summary>
    <div class="methodology-answer">${answer.map(methodologyAnswer).join('')}${sitePageLinks(links)}</div>
  </details>`;
}
function methodologyView() {
  const METHODOLOGY_PAGE = methodologyPage();
  const sections = Array.isArray(METHODOLOGY_PAGE.sections) ? METHODOLOGY_PAGE.sections : [];
  const notice = String(METHODOLOGY_PAGE.notice || '').replace(/^Picos e concentrações não indicam irregularidade\.\s*/, '');
  return `<div class="methodology-page">
    <section class="methodology-intro">
      <h1 class="h ph-t">${esc(METHODOLOGY_PAGE.title)}</h1>
      <p class="ph-lead">${esc(METHODOLOGY_PAGE.lead)}</p>
      <p class="card methodology-notice"><span><b>Picos e concentrações não indicam irregularidade.</b> ${esc(notice)}</span></p>
    </section>
    <div class="methodology-layout">
      <nav class="methodology-toc" aria-label="Nesta página"><span class="k">Nesta página</span>
        ${sections.map(section => `<a href="#${methodologyAnchor(section)}">${esc(section.title)}</a>`).join('')}
      </nav>
      <div class="methodology-sections">
        ${sections.map(section => `<section class="methodology-section" id="${methodologyAnchor(section)}">
          <header><h2 class="h">${esc(section.title)}</h2><p>${esc(section.lead)}</p></header>
          <div class="methodology-questions">${(section.questions || []).map(methodologyQuestion).join('')}</div>
          ${Array.isArray(section.view) && section.view.length === 2 ? `<a class="methodology-view-link" href="${PATH_BY_VIEW[section.view[0]] || '/'}" data-go="${section.view[0]}">${esc(section.view[1])} →</a>` : ''}
        </section>`).join('')}
      </div>
    </div>
  </div>`;
}
function aboutView() {
  const ABOUT_PAGE = aboutPage();
  const sections = Array.isArray(ABOUT_PAGE.sections) ? ABOUT_PAGE.sections : [];
  return `<div class="methodology-page">
    <section class="methodology-intro">
      <h1 class="h ph-t">${esc(ABOUT_PAGE.title)}</h1>
      <p class="ph-lead">${esc(ABOUT_PAGE.lead)}</p>
    </section>
    <div class="methodology-sections">
      ${sections.map(section => `<section class="methodology-section" id="about-${esc(section.id)}">
        <header><h2 class="h">${esc(section.title)}</h2></header>
        <div class="methodology-answer">${(section.paragraphs || []).map(methodologyAnswer).join('')}${sitePageLinks(section.links || [])}</div>
      </section>`).join('')}
    </div>
  </div>`;
}
