# Design system do Painel Público

A interface usa CSS próprio, sem dependência de framework. O template contém apenas os pontos de montagem `{{STYLES}}` e `{{SCRIPTS}}`; os estilos são organizados em `frontend/styles/`.

## Tokens

- **Cores:** `--bg`, `--surface`, `--ink`, `--ink-2`, `--muted`, `--line` e `--chip` formam a paleta neutra. `--accent` e `--warn` destacam ações, estados e dados; `--hero-*` ajusta o contraste dos cartões escuros.
- **Tipografia:** `--f-display` é usada em títulos, `--f-body` no texto e `--f-data` em números e dados tabulares.
- **Medidas:** `--space-1` a `--space-4` cobrem espaçamentos recorrentes. `--radius-card`, `--radius-control` e `--control-height` padronizam cartões, campos e alvos de toque.

Os valores de cor e tipografia são definidos em `tokens.css`. O tema claro é o padrão; o tema escuro responde à preferência do sistema e a `data-theme="dark"`, enquanto `data-theme="light"` mantém o tema claro.

## Classes comuns

- `.app` define a largura e o recuo geral; `.view` organiza o conteúdo da tela.
- `.card` e `.tile` são superfícies neutras; `.card.hero` usa a paleta de alto contraste.
- `.fchip`, `.pill` e `.search` são controles visuais compartilhados. Campos usam `--control-height`, `--radius-control` e `--line`.
- `.muted` e `.mono` padronizam texto secundário e números tabulares.
- Regras de telas específicas ficam em `cidadao.css`; componentes compartilhados e navegação ficam em `base.css`.

## Bordas, estados e acessibilidade

Bordas de componentes usam tons neutros do tema: em geral `--line` em superfícies comuns e `--hero-line` sobre heróis; `--ink` e `--hero-bg` servem para casos de contraste. Não use `--accent`, `--warn` ou cores de categoria em bordas. Estados podem usar cor no texto ou no fundo; gráficos também podem usar cores nos próprios dados.

O foco visível usa contorno neutro de alto contraste, inclusive ao redor do campo de busca. Estados de seleção e navegação são indicados por atributos como `aria-pressed` e `aria-current`; controles indisponíveis mantêm indicação visual própria. Animações só rodam quando o sistema não solicita movimento reduzido.

## Como estender

Antes de criar uma medida ou cor, reutilize o token correspondente. Compartilhe regras gerais em `base.css`; mantenha regras de uma área junto ao seu CSS de funcionalidade. Quando vários componentes repetirem uma regra, extraia uma classe ou token comum em vez de copiar declarações. Preserve os indicadores de foco, estados sem depender apenas de cor e as bordas neutras.
