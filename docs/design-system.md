# Design system do Painel Público

A interface usa CSS próprio, sem dependência de framework. O template contém apenas os pontos de montagem `{{STYLES}}` e `{{SCRIPTS}}`; os estilos são organizados em `frontend/styles/`.

## Tokens

- **Cores:** `--bg`, `--surface`, `--ink`, `--ink-2`, `--muted`, `--line` e `--chip` formam a paleta neutra. `--accent` e `--warn` destacam ações, estados e dados; `--hero-*` ajusta o contraste dos cartões escuros.
- **Tipografia:** `--f-display` é usada em títulos, `--f-body` no texto e `--f-data` em números e dados tabulares.
- **Medidas:** `--space-1` a `--space-4` cobrem espaçamentos recorrentes. `--radius-card`, `--radius-control` e `--control-height` padronizam cartões, campos e alvos de toque.
- **Elevação:** `--shadow-raised` dá profundidade a cartões de destaque (custo da home, painéis, busca). Tem versão própria em cada tema; use o token em vez de escrever uma sombra nova.

Os valores de cor e tipografia são definidos em `tokens.css`. O tema escuro é o padrão (`data-theme="dark"` no template). O botão de tema (no topo da home, no rodapé e na navegação do computador) alterna para `data-theme="light"` e guarda a escolha em `localStorage` (`painel-theme`), só neste navegador; um script no `<head>` aplica a escolha antes de pintar a página.

## Classes comuns

- `.app` define a largura e o recuo geral; `.view` organiza o conteúdo da tela.
- `.card` e `.tile` são superfícies neutras; `.card.hero` usa a paleta de alto contraste.
- `.fchip`, `.pill` e `.search` são controles visuais compartilhados. Campos usam `--control-height`, `--radius-control` e `--line`.
- `.muted` e `.mono` padronizam texto secundário e números tabulares.
- Regras de telas específicas ficam em `citizen.css`; componentes compartilhados e navegação ficam em `base.css`.

## Compartilhar

`.share-actions` (em `share-card.js`) oferece compartilhar imagem na ficha, na comparação de políticos e na de partidos. Cada tela monta um cartão com os mesmos números que mostra (`profileShareCard`, `comparisonShareCard`, `partyShareCard`); o cartão é desenhado em canvas, 1080×1350, tema claro, sem fotos de outros domínios, com fontes, data e o aviso de independência no rodapé. A comparação de políticos usa outro desenho (`layout: 'faceoff'`), no tema escuro e sem logotipo: um card por pessoa, numa cor para cada uma (violeta e laranja, só para distinguir os lados), com custo e presença em números grandes, para onde vai a cota (3 maiores categorias) e a maior nota única; embaixo, os votos em comum com a referência de dois deputados quaisquer e os alertas, sem destaque. A etiqueta ("R$ … a menos por mês", "mais presente") só aparece entre pessoas da mesma Casa, e o número de quem fica atrás fica cinza. O endereço vai em letras miúdas no rodapé. A comparação de partidos usa o mesmo desenho: em cada card, cota média por deputado(a) e presença média com as mesmas etiquetas, para onde vai a cota dos(as) deputados(as) (`cotaCategorias` de `/api/c/partidos`) e "Do lado vencedor nas votações" (maioria da bancada igual ao resultado final); embaixo, quantas vezes as maiorias das bancadas votaram igual e os alertas a cada 10 parlamentares, sem destaque. O botão das duas comparações se chama "Compartilhar"; na ficha, "Compartilhar imagem". No celular, abre o compartilhamento nativo; nos demais, baixa o arquivo.

## Bordas, estados e acessibilidade

Bordas de componentes usam tons neutros do tema: em geral `--line` em superfícies comuns e `--hero-line` sobre heróis; `--ink` e `--hero-bg` servem para casos de contraste. Não use `--accent`, `--warn` ou cores de categoria em bordas. Estados podem usar cor no texto ou no fundo; gráficos também podem usar cores nos próprios dados.

O foco visível usa contorno neutro de alto contraste, inclusive ao redor do campo de busca. Estados de seleção e navegação são indicados por atributos como `aria-pressed` e `aria-current`; controles indisponíveis mantêm indicação visual própria. Animações só rodam quando o sistema não solicita movimento reduzido.

## Como estender

Antes de criar uma medida ou cor, reutilize o token correspondente. Compartilhe regras gerais em `base.css`; mantenha regras de uma área junto ao seu CSS de funcionalidade. Quando vários componentes repetirem uma regra, extraia uma classe ou token comum em vez de copiar declarações. Preserve os indicadores de foco, estados sem depender apenas de cor e as bordas neutras.
