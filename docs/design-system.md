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

`.share-actions` (em `share-card.js`) oferece compartilhar imagem na ficha, na comparação de políticos e na de partidos. Cada tela monta um cartão com os mesmos números que mostra (`profileShareCard`, `comparisonShareCard`, `partyShareCard`); o cartão é desenhado em canvas, 1080×1350, tema escuro, sem logotipo, com fontes, data, o aviso de independência e o endereço no rodapé. A foto oficial entra pelo próprio domínio (`/api/c/foto/camara:ID` ou `senado:ID`, em `backend/photos.py`): uma foto direto da Câmara, sem CORS, impediria exportar o PNG. Ela é recortada em círculo, com o crédito "Foto: Câmara dos Deputados" ou "Senado Federal" no rodapé; sem foto em até 9 s, ficam as iniciais. A ficha (`layout: 'profile'`) mostra a foto (ou as iniciais), o nome e o cargo; o custo em violeta, com o valor exato e as partes (o mês mais recente com as notas da cota já assentadas e a média na nota; na Câmara, gabinete, salário, cota e auxílios; no Senado, remuneração, gabinete e cota); a presença com a média da Casa (no Senado, a contagem de presenças registradas, sem porcentagem); a maior nota única; e para onde vai a cota, com as 3 maiores categorias e "Outras", que fecham 100%. A contagem de alertas fica fora da imagem: sem as regras e a fonte ao lado, o número não se explica. A comparação de políticos usa outro desenho (`layout: 'faceoff'`), no tema escuro e sem logotipo: um card por pessoa, numa cor para cada uma (violeta e laranja, só para distinguir os lados), com a foto no canto e um anel nessa cor, com custo e presença em números grandes, para onde vai a cota (3 maiores categorias e "Outras", fechando 100%) e a maior nota única; embaixo, os votos em comum com a referência de dois deputados quaisquer e os alertas, sem destaque. A etiqueta ("R$ … a menos por mês", "mais presente") só aparece entre pessoas da mesma Casa, e o número de quem fica atrás fica cinza. O endereço vai em letras miúdas no rodapé. A comparação de partidos usa o mesmo desenho: em cada card, cota média por deputado(a) e presença média com as mesmas etiquetas, para onde vai a cota dos(as) deputados(as) (`cotaCategorias` de `/api/c/partidos`) e a unidade nas votações (deputados(as) votando com a maioria da bancada); embaixo, quantas vezes as maiorias das bancadas votaram igual e quantos(as) parlamentares têm algum alerta, entre os(as) que têm notas (por exemplo "61 de 113"), sem destaque e sem taxa extrapolada. O botão se chama "Compartilhar imagem" na ficha e nas duas comparações. No celular, abre o compartilhamento nativo; nos demais, baixa o arquivo.

## Bordas, estados e acessibilidade

Bordas de componentes usam tons neutros do tema: em geral `--line` em superfícies comuns e `--hero-line` sobre heróis; `--ink` e `--hero-bg` servem para casos de contraste. Não use `--accent`, `--warn` ou cores de categoria em bordas. Estados podem usar cor no texto ou no fundo; gráficos também podem usar cores nos próprios dados.

O foco visível usa contorno neutro de alto contraste, inclusive ao redor do campo de busca. Estados de seleção e navegação são indicados por atributos como `aria-pressed` e `aria-current`; controles indisponíveis mantêm indicação visual própria. Animações só rodam quando o sistema não solicita movimento reduzido.

## Links reais e conteúdo do servidor

Navegação principal, rodapé, linhas de lista (`.citizen-row`, `.attendance-row`, `.citizen-who`, `.face`, ranking da home), atalhos e cartões de votação são `<a href>` com o mesmo desenho dos botões que substituíram: as regras usam `:is(button, a)` e `base.css` tira o sublinhado e herda a cor. Controles que não navegam (filtros, ordenação, "Comparar", tema) continuam botões. O conteúdo que o servidor põe em `#app` antes do JavaScript usa os mesmos componentes das telas, mais três classes só dele em `base.css`: `.seo-directory` (lista de fichas em colunas), `.seo-table` (tabela de partidos) e `.seo-plain-list`; `.seo-summary` é o resumo da ficha. Ao criar um componente de lista, dê a ele uma versão em link quando a linha abre uma página.

## Como estender

Antes de criar uma medida ou cor, reutilize o token correspondente. Compartilhe regras gerais em `base.css`; mantenha regras de uma área junto ao seu CSS de funcionalidade. Quando vários componentes repetirem uma regra, extraia uma classe ou token comum em vez de copiar declarações. Preserve os indicadores de foco, estados sem depender apenas de cor e as bordas neutras.
