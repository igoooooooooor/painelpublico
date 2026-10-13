# Plano de ação de SEO e GEO

Criado em 11 de outubro de 2026. **Status em 13/10/2026: etapas 1, 2 e 3 implementadas no código (branch `feat/seo-server-content`); publicação, etapa 0 e etapa 5 dependem do responsável pelas contas do site.**

## O que foi implementado (13/10/2026)

- **Conteúdo no HTML (1A, 1C):** todas as seções, as fichas e cada votação do Placar chegam com o conteúdo essencial dentro de `#app`, montado por `backend/seo_sections.py` com as mesmas funções da API. O app mantém esse bloco até a API responder e, se ela falhar, ele permanece; outra ficha nunca herda o resumo anterior. Título, canonical, descrição e `noindex` acompanham a navegação interna com os mesmos textos do servidor (`frontend/data/site-pages.json`).
- **Links reais (1B):** menu, rodapé, linhas de lista, rostos, atalhos, ranking da home e cartões de votação são `<a href>`; Ctrl/Cmd e botão do meio abrem em nova aba. `/politicos` traz o diretório completo das fichas no HTML; a busca da home funciona sem JavaScript (`/politicos?q=`).
- **Páginas institucionais (2):** `/sobre` nova e `/metodologia` com fontes e frequência de atualização, ambas com HTML no servidor e no app a partir do mesmo JSON. Dados estruturados: `WebSite` com `publisher`, `WebPage`/`CollectionPage`/`AboutPage`, `Person` com `mainEntityOfPage`, `BreadcrumbList`; `Legislation` como `about` nas votações.
- **Votações com endereço próprio:** `/placar/<id>` tem título, canonical, conteúdo (decisão, Sim/Não, resultado, votos por pessoa e por partido, fontes) e entra no sitemap com a data da revisão. Votações selecionadas fora do catálogo ficam com `noindex`.
- **Compartilhamento e carregamento (3):** `og:image`/`twitter:image` (`summary_large_image`) com imagem padrão 1200×630 gerada de `frontend/static/og-image-source.html`; JavaScript e CSS em `dist/assets/app.<hash>.{js,css}` com cache de um ano e imutável, HTML por página com cerca de 10–60 KB (o Placar e a presença, com todas as linhas, são maiores) e `max-age=60`; cache de páginas invalidado também por mudança nos snapshots.
- **Página 404 do site** em HTML, com `noindex` e `no-store`; `llms.txt` ampliado; `robots.txt` mantido (`Disallow: /api/`).
- **Fora desta entrega:** imagens de compartilhamento por parlamentar (sem biblioteca de imagem no Python, só a imagem padrão), páginas de municípios (etapa 4) e as medições das etapas 0 e 5.

A auditoria abaixo descreve a situação em 11/10/2026, antes dessas mudanças; os itens marcados foram concluídos no código e devem ser conferidos no domínio real após a publicação.

## Objetivo

Permitir que buscadores e ferramentas de IA encontrem, leiam e referenciem as informações que o Painel Público já apresenta, com fonte, período, cálculo e limitações claros. Preservar a home, a identidade visual e a arquitetura Python, SQLite e JavaScript sem framework.

GEO neste plano significa otimização para mecanismos generativos. Páginas de municípios são uma frente de conteúdo regional, que pode contribuir tanto para SEO quanto para GEO.

## Ponto de partida e limites da auditoria

Na consulta pública de 11/10/2026:

- O sitemap respondeu com 602 URLs: 513 deputados, 81 senadores e oito seções. É uma fotografia da base publicada, não uma contagem fixa esperada em testes.
- As duas fichas consultadas entregaram resumo textual, canonical e schema `Person`; a home tem `WebSite`.
- Home, Políticos, Alertas e Minha cidade não entregaram seu conteúdo principal no HTML inicial. A navegação principal usa botões.
- O `robots.txt` bloqueia `/api/`. O aplicativo depende desses endpoints e substitui o resumo inicial antes de concluir o carregamento: há risco de perder o conteúdo durante a renderização de um buscador.
- As páginas consultadas não tinham `og:image`; `/metodologia` respondeu 404.
- A home respondeu com aproximadamente 656 KB de HTML sem compressão, cache de 60 segundos e `CF-Cache-Status: DYNAMIC` na requisição observada. Isso não constitui uma medição de Core Web Vitals.

Não houve acesso ao Search Console, Bing Webmaster Tools, estatísticas de tráfego ou configuração do Cloudflare. Indexação, autoridade, desempenho real e acesso dos robôs autênticos permanecem sem diagnóstico conclusivo. Revalidar a versão publicada ao iniciar a implementação.

## Ordem de execução

| Etapa | Prioridade | Entrega | Dependência |
| --- | --- | --- | --- |
| 0 | P0 | Linha de base e acesso à medição | Pode ocorrer em paralelo às correções locais |
| 1 | P0 | Conteúdo legível, navegação rastreável e carregamento resiliente | Usa os dados e a arquitetura existentes |
| 2 | P1 | Metodologia, fontes, autoria e semântica coerente | Base de renderização da etapa 1 |
| 3 | P1 | Compartilhamento e carregamento mais eficiente | URLs e conteúdo estabilizados nas etapas 1 e 2 |
| 4 | P2 | Páginas de municípios e conteúdo explicativo útil | Etapas anteriores validadas e cobertura conferida |
| 5 | Contínua | Avaliação de resultados e divulgação fundamentada | Publicação de cada entrega e dados disponíveis |

Responsabilidade técnica: implementação e verificações locais pelo agente que executar cada lote. O responsável pelas contas do site fornece os relatórios ou acesso necessários à etapa 0 e às verificações em produção. A ausência desses acessos não bloqueia o trabalho local.

## Etapa 0 — Registrar a situação antes das mudanças

- [ ] Confirmar propriedade e sitemap no Google Search Console e no Bing Webmaster Tools; aproveitar configurações existentes.
- [ ] Registrar páginas indexadas e motivos de exclusão, impressões, cliques, consultas e páginas de entrada. Separar buscas pela marca de consultas sobre parlamentares ou temas.
- [ ] Inspecionar a home, Políticos, Alertas, uma ficha de cada Casa e uma página com dados incompletos. Guardar o HTML renderizado e os recursos bloqueados, quando as ferramentas os fornecerem.
- [ ] Conferir nos registros e nas configurações do Cloudflare o acesso de Googlebot, Bingbot e OAI-SearchBot. Um teste com user-agent alterado não comprova acesso dos robôs autênticos.
- [ ] Medir páginas representativas no PageSpeed Insights. Registrar separadamente dados reais disponíveis e testes de laboratório, incluindo tamanho transferido e tempo de resposta.
- [ ] Criar um conjunto inicial de 10–15 perguntas para avaliação manual de GEO, cobrindo custo, presença, alertas, metodologia e municípios. Registrar data, ferramenta, pergunta, URL citada e fidelidade da resposta ao período e à fonte.

**Concluída quando:** existe uma linha de base datada, com lacunas de acesso explicitadas. Relatórios e exportações permanecem fora do Git quando contiverem dados de conta ou tráfego. Não atribuir nota de SEO nem meta percentual de crescimento sem essa referência.

## Etapa 1 — Tornar o conteúdo existente acessível

### Lote 1A: preservar conteúdo durante o carregamento

- [x] Manter o resumo inicial da ficha enquanto a API está pendente ou falha; substituí-lo somente quando existir conteúdo equivalente disponível.
- [x] Tratar navegação entre pessoas sem mostrar o resumo da pessoa anterior como se fosse da nova ficha. Preservar identidade, URL e estado de erro corretos.
- [x] Aplicar o mesmo princípio às seções que receberem conteúdo no servidor.
- [x] Manter título, descrição, canonical, diretivas de indexação e dados estruturados coerentes com a página, tanto no acesso direto quanto na navegação interna. Evitar que o título específico vire apenas “Ficha” durante o carregamento ou que o `noindex` de uma comparação permaneça na próxima ficha.

**Decisão de arquitetura:** o conteúdo essencial deve estar no HTML, independentemente de acesso à API. Não liberar toda a API como solução automática. Se algum recurso público continuar indispensável à renderização, avaliar uma exceção restrita de rastreamento e a política de indexação desse recurso; bloquear rastreamento e impedir indexação são controles diferentes.

### Lote 1B: navegação com links reais

- [x] Converter destinos de navegação em `<a href>`: menu principal, entradas de fichas e caminhos entre páginas. Ações, filtros e seletores continuam sendo botões quando não representam navegação.
- [x] Preservar a experiência SPA, voltar/avançar, teclado, foco e abertura em nova aba com Ctrl/Cmd ou botão do meio.
- [x] Tornar as fichas da lista oficial alcançáveis a partir de um diretório HTML, com links simples de nome e Casa. Evitar embutir fichas completas na listagem. O sitemap continua sendo uma via complementar.

### Lote 1C: conteúdo das seções no servidor

- [x] Começar por `/`, `/politicos` e `/alertas`: título principal, conteúdo útil já existente, links, fontes, períodos e estados de ausência.
- [x] Completar `/placar`, `/presenca` e `/minha-cidade` com a informação disponível e as explicações necessárias para entender o recorte.
- [x] Revisar `/partidos` e `/comparar`: suas páginas de entrada devem explicar a ferramenta e oferecer caminhos úteis. Preservar o `noindex` já adotado para pares de comparação; não colocar combinações arbitrárias no sitemap.
- [x] Reutilizar consultas e regras do backend. A camada de SEO formata os resultados, sem criar outra fórmula de custo, presença ou alertas.
- [x] Mostrar o mesmo conteúdo essencial a pessoas e robôs. O HTML inicial deve fazer parte da interface, com o design existente, e não ser um bloco oculto exclusivo para buscadores.
- [x] Conferir cache e invalidação para todas as fontes usadas pelo HTML, inclusive snapshots complementares. A atualização de um snapshot deve aparecer mesmo quando o SQLite não mudar.

**Arquivos principais:** `backend/seo.py`, `backend/server.py`, `frontend/index.template.html`, `frontend/scripts/app.script.js` e os scripts das telas afetadas. Alterações visuais somente para preservar componentes e estados do design system.

**Concluída quando:** as páginas prioritárias entregam conteúdo útil sem JavaScript; o conteúdo continua disponível com API bloqueada ou com erro; todas as fichas atuais são descobertas por links HTML; metadados correspondem à página; números e períodos coincidem com a interface; navegação e visual permanecem corretos.

## Etapa 2 — Explicar como os dados viram respostas

- [x] Publicar `/metodologia`, `/fontes` e `/sobre`, com HTML no servidor e links permanentes no rodapé e nas métricas relacionadas. (As fontes ficaram como seção de `/metodologia`, `#methodology-sources`, em vez de uma página `/fontes` separada, para não manter dois textos.)
- [x] Derivar os textos de `docs/data.md`, `docs/alerts.md` e dos documentos de custo do mandato, reconciliando eventuais diferenças com a implementação antes de publicar.
- [x] Explicar custo total versus cota, componentes por Casa, denominadores das médias, períodos com lacunas, valores nominais, presença e limites de comparação.
- [x] Documentar regras dos alertas e esclarecer, junto dos resultados, que um alerta não comprova irregularidade e que ausência de dado não significa zero.
- [x] Separar período dos dados, data da coleta e data de atualização da página. Não apresentar uma nova publicação do código como atualização dos dados.
- [ ] Identificar autoria e responsabilidade editorial conforme informações confirmadas pelo responsável pelo projeto; manter independência, canal de correção e fontes oficiais explícitos. (`/sobre` diz apenas o que o aviso legal já afirma: pessoa física, iniciativa própria; nomear a pessoa é decisão do responsável.)
- [x] Manter `Person` e `WebSite`; acrescentar `WebPage` e referências consistentes às entidades onde útil. Usar `BreadcrumbList` quando houver navegação correspondente e `Dataset` apenas em páginas que realmente descrevam um conjunto de dados.
- [x] Incluir as novas páginas no sitemap e atualizar os links do `llms.txt`, sem tratá-lo como requisito de indexação ou garantia de citação.

**Concluída quando:** uma pessoa consegue reconstruir a interpretação de cada indicador a partir da página e das fontes vinculadas; JSON-LD corresponde ao conteúdo visível; páginas institucionais têm URLs, metadados e links válidos.

## Etapa 3 — Melhorar distribuição e eficiência

### Compartilhamento

- [x] Adicionar uma imagem padrão acessível em PNG/JPEG, `og:image`, `twitter:image` e `summary_large_image`, com URL absoluta.
- [ ] Validar o acesso público à imagem e a aparência dos links em ferramentas de preview e no fluxo de compartilhamento usado pelo projeto.
- [ ] Depois, avaliar imagens por parlamentar reaproveitando a linguagem dos cartões existentes. Se houver números, incluir período, fonte e invalidação quando os dados mudarem; oferecer a imagem padrão quando faltarem dados.

### Carregamento e cache

- [x] Separar JavaScript e CSS estáticos do HTML, com nomes versionados pelo conteúdo e cache longo para esses arquivos; manter o build Python existente.
- [x] Servir apenas os arquivos gerados previstos, preservando a restrição de acesso a dados, snapshots e arquivos privados.
- [x] Conferir publicação e compatibilidade entre HTML e arquivos estáticos para que uma atualização não cause referências quebradas.
- [ ] Medir novamente as mesmas páginas e condições da etapa 0. Registrar tamanho transferido, reutilização de cache, tempo de resposta e métricas de renderização disponíveis.
- [ ] Ajustar cache de HTML no servidor/edge somente com regra explícita de atualização e invalidação após mudanças de dados ou código. Não adotar horas de cache apenas porque a coleta é manual.

**Concluída quando:** links têm imagem de preview válida; páginas reutilizam arquivos estáticos; a publicação não produz arquivos ausentes; atualizações de dados aparecem conforme a política definida; medições comparáveis demonstram o efeito da mudança, sem regressão funcional ou visual.

## Etapa 4 — Expandir por utilidade e cobertura

- [ ] Criar um piloto de páginas municipais com identidade estável pelo código IBGE, URL própria, canonical, HTML útil, fontes e recortes explícitos. Selecionar casos com cobertura completa, parcial e ausente para validar o comportamento antes de ampliar.
- [ ] Preservar `/minha-cidade` como entrada da busca e manter contratos da API. Definir redirects de slugs pelo identificador estável.
- [ ] Colocar no sitemap as páginas que realmente ofereçam informação útil. Dados ausentes em um indicador não tornam automaticamente toda a página inútil; explicar as lacunas sem inventar zeros.
- [ ] Publicar primeiro duas explicações úteis: “Como calculamos o custo de um deputado federal” e “O que significa um alerta de gasto”. Reutilizar a metodologia, evitando repetir manualmente números que ficam desatualizados.
- [ ] Avaliar páginas por estado e detalhes de votações conforme cobertura e procura observadas. Os detalhes do Placar hoje merecem avaliação de identidade e canonical próprios antes de serem tratados como novas páginas indexáveis.

**Concluída quando:** cada nova URL responde a uma pergunta concreta com conteúdo próprio; links, sitemap e canonical são consistentes; limites de cobertura aparecem na página; o custo de manutenção é compatível com as coletas existentes.

## Etapa 5 — Medir resultado e divulgar com evidências

Após cada publicação, registrar a versão e a data para comparar os resultados. Os pontos de revisão abaixo são planejamento, não automações já configuradas.

| Momento | Verificação | Decisão esperada |
| --- | --- | --- |
| Na publicação | HTML, status HTTP, links, metadados, imagem e acesso aos arquivos | Confirmar entrega ou corrigir regressões |
| Após 2–4 semanas | Rastreamento, HTML renderizado, indexação e motivos de exclusão | Identificar obstáculos que continuam presentes |
| Após 6–8 semanas | Impressões, cliques, consultas, páginas de entrada e citações disponíveis | Escolher a próxima expansão de conteúdo |

Esses intervalos são pontos de avaliação, não promessa de indexação ou crescimento. Comparar janelas equivalentes e considerar notícias e eventos eleitorais, que podem alterar a demanda independentemente das mudanças técnicas.

- [ ] Acompanhar páginas prioritárias indexadas e excluir do denominador URLs que deliberadamente têm `noindex`, redirects ou erros.
- [ ] Medir descoberta orgânica por grupo de páginas e consultas de marca/não marca; não avaliar sucesso somente pelo total de URLs indexadas.
- [ ] Consultar citações disponíveis no relatório AI Performance do Bing e referências de tráfego identificáveis. Registrar a cobertura limitada de cada ferramenta.
- [ ] Repetir o conjunto de perguntas de GEO e conferir se as respostas preservam fonte, período e significado. Uma amostra manual não representa participação total nas respostas das IAs.
- [ ] Preparar exemplos verificáveis de uso para jornalistas, pesquisadores e organizações de transparência, com URLs estáveis e metodologia. O envio a terceiros é uma ação posterior; este plano não envia mensagens.

## Lotes de trabalho, dependências e verificação

Abrir mudanças pequenas por finalidade: 1A, 1B, 1C, páginas institucionais, compartilhamento, arquivos/cache e piloto municipal. Os lotes 1A e 1B tocam o roteador e precisam ser integrados de forma coordenada; revisão dos textos da etapa 2 e levantamento de métricas podem acontecer em paralelo.

- Testar comportamento real: API pendente/indisponível, dados ausentes, navegação, canonical, respostas HTTP, atualização de snapshots e correspondência dos números. Não criar testes que só repitam texto ou CSS.
- Reaproveitar os testes de SEO/backend e os testes Node existentes para as telas e o roteador afetados. Usar dados temporários, sem rede ou snapshots privados obrigatórios.
- Conferir a interface no navegador em desktop e celular, com JavaScript habilitado, desabilitado e com falha da API. Validar navegação por teclado e nova aba.
- Rodar checks do escopo a cada lote, `git diff --check` antes de concluir e `make check` para mudanças transversais e antes de integração/publicação.
- Publicar conforme [Publicação](deploy.md) e repetir uma amostra das verificações no domínio real. Um teste local não confirma configuração de CDN nem HTML recebido pelo Google.
- Mudanças exclusivas deste plano exigem revisão documental e `git diff --check`, sem executar a suíte da aplicação.

Verificações disponíveis para os futuros lotes de implementação:

| Escopo | Teste existente a estender | Comando limitado ao escopo |
| --- | --- | --- |
| HTML, metadados, redirects, robots e sitemap | `tests/test_seo.py` | `python3 -m unittest discover -s tests -p 'test_seo.py'` |
| Carregamento, links e navegação SPA | `tests/app-routing.test.cjs`, `tests/citizen-view.test.cjs` | `node --test tests/app-routing.test.cjs tests/citizen-view.test.cjs` |
| Arquivos públicos e comportamento HTTP/cache | `tests/test_server.py` | `python3 -m unittest discover -s tests -p 'test_server.py'` |
| Build e separação de arquivos estáticos | `tests/test_build.py` | `python3 -m unittest discover -s tests -p 'test_build.py'` |

As lacunas prioritárias são preservar um resumo SSR real durante API pendente/com erro, comparar canonical/título entre navegação interna e acesso direto e validar abertura de links em nova aba. Os testes de cartões em canvas não validam Open Graph: a imagem de preview precisa de verificação de metadados e de resposta HTTP/MIME próprias. Ampliar os comandos apenas para os chamadores e contratos afetados pelo lote.

## O que não entra na primeira entrega

Migração de framework, nova infraestrutura de coleta, compra de backlinks, reformulação da marca, geração em massa de textos, schema sem correspondência com o conteúdo ou expansão automática para milhares de URLs. As coletas e o backup previstos no [roadmap](roadmap.md) mantêm sua prioridade operacional.

O primeiro marco é concluir a etapa 1 e registrar a medição disponível: conteúdo essencial acessível, links rastreáveis e renderização resiliente, com o visual preservado.

## Referências da auditoria

- [Google: JavaScript e indexação](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics).
- [Google: links rastreáveis](https://developers.google.com/search/docs/crawling-indexing/links-crawlable).
- [Google: recursos de IA e requisitos para sites](https://developers.google.com/search/docs/appearance/ai-features).
- [OpenAI: distinção entre OAI-SearchBot e GPTBot](https://developers.openai.com/api/docs/bots).
- [Bing: relatório AI Performance](https://blogs.bing.com/webmaster/2026/2/Introducing-AI-Performance-in-Bing-Webmaster-Tools-Public-Preview/).
