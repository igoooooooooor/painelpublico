# Arquitetura

Aplicação pequena com HTML/CSS/JavaScript sem framework, API Python com biblioteca padrão e SQLite. Não há ORM, bundler JavaScript, serviços separados ou etapa npm.

```text
frontend/ + frontend/data/ + snapshots complementares opcionais → scripts/build.py → dist/index.html + dist/assets/app.<hash>.{js,css}
navegador → /api/* → backend/ → data/na-lupa.sqlite3 (base parlamentar e despesas)
fontes públicas → ingest/ → data/imports/ → importação transacional → SQLite
```

## Responsabilidades

- `backend/server.py`: HTTP e rotas. Serve apenas o HTML gerado, os arquivos do build em `dist/assets/` (nome com hash do conteúdo, cache de um ano), a imagem de compartilhamento e a API, nunca as pastas de dados.
- `backend/seo.py` e `backend/seo_sections.py`: metadados, dados estruturados, sitemap, robots, llms.txt e o conteúdo inicial de cada página em HTML (ver [Endereços e buscadores](#endereços-e-buscadores)).
- `backend/public_store.py`: importação transacional, agregados e sinais de triagem. Valores monetários em centavos; reembolso e remuneração permanecem separados.
- `backend/cities.py`: busca de municípios e página individual a partir de `cities.json`; consulta o roster federal em modo somente leitura e liga fichas apenas por correspondência única de nome, UF e cargo.
- `backend/citizen.py`: apresenta os dados e sinais existentes em linguagem simples para as telas e gera o CSV com as notas de cada ficha.
- `backend/config.py`, `schema.sql`, `database.py`: caminhos, esquema e manutenção do banco.
- `frontend/index.template.html`: estrutura do documento e navegação.
- `frontend/styles/`: tokens, componentes compartilhados e estilos por área. Ver [design system](design-system.md).
- `frontend/scripts/app.script.js`: estado e roteamento. `home-view.js` mostra resumos consultados no SQLite; os outros scripts agrupam as áreas de políticos, alertas, presença, comparações e partidos.
- `frontend/scripts/profile-data.js`: identidade canônica e leitura compartilhada de contatos, projetos, gabinete, presença, votos e eleição de 2026. Cada ficha pede seu complemento em `/api/c/perfil/<id>` quando disponível, sem embutir todos os perfis no HTML; salário de referência é separado de pagamento individual.
- `scripts/build.py`: montagem determinística, com ordem de CSS e JavaScript explícita. Gera `dist/index.html` (só o documento) e `dist/assets/app.<hash>.js` e `.css`; arquivos de builds anteriores ficam sete dias, para páginas ainda em cache. O build não precisa de snapshots locais; os quatro resumos do Placar vêm de metadados versionados em `frontend/data/votes.json`, e os textos de `/metodologia`, `/sobre` e os títulos das seções vêm de `frontend/data/site-pages.json`, compartilhado com o servidor.
- `ingest/pipeline.py`: orquestrador da atualização automática (coleta da cota, importação em cópia, verificação, publicação atômica, perfis, situação dos projetos e aviso). Roda no servidor por `deploy/painel-ingest.timer`.
- `ingest/calendar_events.py`: eventos com data (segundo turno, troca de legislatura), sem rede; o job semanal executa as ações pendentes.
- `ingest/editorial_queue.py`: fila editorial sem rede (candidatos do Placar sem revisão e arquivos mantidos à mão), gerada pelo job semanal; nunca publica.
- `ingest/chamber_projects.py`: projetos de cada deputado(a) a partir dos arquivos anuais da Câmara, compartilhados com a situação dos projetos; usado por `ingest/profiles.py --collect`.
- `ingest/`: adaptadores atuais. `ingest/editorial/`: comandos manuais que guardam respostas oficiais em cache e montam complementos de presença e votos; não definem o roster usado pela aplicação.
- `data/snapshots/`: complementos locais opcionais, não a base parlamentar. Toda a pasta `data/`, incluindo `imports/`, `raw/`, SQLite e snapshots, fica fora do Git.
- `tests/`: verificações Python e Node sem acesso à rede; bancos temporários nos testes.
- `archive/` e `artifacts/`: recuperação local e imagens, fora do Git.

## Regras simples

Preservar os contratos `/api/*` ao mover código. Filtrar e paginar no servidor; nunca embutir o SQLite no HTML. Views recebem valores calculados no backend, sem duplicar regras de sinais. Os scripts atuais compartilham escopo no bundle: novos helpers devem ter prefixo da área até uma futura migração justificada para módulos.

Home, resumo, lista e fichas consultam a lista oficial e os reembolsos importados no SQLite. Totais e médias usam os registros observados; cadastro sem lançamento permanece sem gasto, não zero. Os cinco nomes na classificação da home são apenas uma seleção visual do ranking calculado sobre todos os deputados com dados. Resultados eleitorais ainda não cobrem todo o roster e por isso não aparecem na home; a ficha em PDF e a análise editorial antiga também foram removidas. Presença, votos selecionados e perfis são complementos opcionais, com fonte e cobertura própria. O app não grava nada no navegador.

O servidor é de desenvolvimento e escuta em `127.0.0.1` por padrão. O suporte a `--host` permite teste de rede deliberado, mas não transforma este servidor em hospedagem de produção.

## Minha cidade — Fase 1

`ingest/cities.py --collect` consulta IBGE e TSE; sem a flag, reconstrói somente
com os caches de `data/raw/`. O snapshot `data/snapshots/cities.json` mantém a
base nacional fora do SQLite e do HTML. Assim não há migração nem reimportação
da base parlamentar para esta funcionalidade.

`GET /api/c/cities?q=...` normaliza acentos e caixa e limita a resposta a 20
localidades; `GET /api/c/cities/<código IBGE>` retorna apenas a cidade selecionada,
os resultados eleitorais de sua UF e a lista parlamentar atual dessa UF.
As duas rotas funcionam sem o SQLite. Nesse caso, apenas a lista atual e as ligações
às fichas ficam indisponíveis. Ausência ou erro no snapshot tem estado explícito.
O cache de arquivo acompanha o mtime; as rotas não usam o cache HTTP baseado só
na data do banco. Nenhuma consulta de visitante inicia coleta.

A eleição de 2026 e a lista parlamentar atual são conjuntos separados: vencer a
eleição não comprova exercício do mandato. A ligação de uma candidatura eleita
à ficha exige nome civil ou de urna exatamente igual após normalização, UF e cargo,
com uma única candidatura por ficha e uma única ficha por candidatura. Não consulta
CPF, título, e-mail ou nascimento. Casos sem correspondência continuam visíveis
como resultados do TSE, sem link inventado.

## Minha cidade — Emendas

`ingest/amendments.py` projeta somente a tabela por emenda do ZIP do Portal da
Transparência e reconstrói `data/snapshots/amendments.json` sem rede por padrão.
O ZIP permanece em memória; tabelas de favorecidos não são processadas ou salvas.
O snapshot independente evita migração e reimportação do banco eleitoral.

`backend/amendments.py` complementa a mesma rota de detalhe da cidade e usa o cache
por modificação de arquivo. Ausência do snapshot ou do código municipal recebe
estado explícito. A ligação com fichas consulta o roster nacional somente para
leitura: nome público exato e único, sem usar a UF de destino como UF do autor.
Os valores permanecem em centavos até a formatação na interface.

## Minha cidade — Contas municipais

`ingest/accounts.py` consulta DCA/SICONFI e mantém as contas em
`data/snapshots/accounts.json`, sem alteração do SQLite. Cada município tem estado
de disponibilidade; uma falha de consulta não comprova falta de entrega. Brasília
e Fernando de Noronha ficam fora da comparação municipal. A população usada nas
faixas é uma fotografia IBGE do mesmo exercício, independente da população mais
recente exibida no cabeçalho da cidade.

`backend/accounts.py` complementa a rota de detalhe municipal. Só libera medianas
após confirmação da coleta nacional completa. Para cada indicador, exclui a cidade
consultada, dados ausentes e observações de outra etapa ou classificação. Exige
três outros municípios com valores válidos, mostra o tamanho da amostra e mantém
zeros efetivamente declarados. Não calcula ranking.

`ingest/finbra.py` importa os três CSVs nacionais para um estágio separado, com
hashes e fontes por indicador. A instalação opcional completa caches ausentes e
retém evidências de divergências antes de ocultar valores conflitantes. O estágio
não escreve o snapshot: `ingest/accounts.py` continua responsável pela publicação
local e pela verificação de cobertura nacional.

## Custo médio mensal do mandato

Os coletores de folha, moradia e exercício mantêm caches minimizados e snapshots
locais. `ingest/chamber_quota_audit.py` reconcilia o arquivo CEAP com os registros
importados, sem alterar o banco. `ingest/mandate_cost_composition.py` gera a
composição do mandato até o último mês com prazo da cota encerrado (regra em `ingest/periods.py`) e os motivos de exclusão de meses.
`backend/profiles.py` carrega `mandate-cost.json` pelo cache de mtime e anexa
somente o registro da pessoa solicitada, exclusivamente para a Câmara e o período
aprovado. Visitantes não iniciam coleta nem cálculo sobre o arquivo CEAP.

A interface recebe centavos, meses usados, parcelas, períodos de exercício e
fontes. Ela formata os valores; não decide elegibilidade, corrige sinais ou
soma moradia. O complemento permanece separado uma vez e com o sinal original.
A lista e a comparação mostram o mesmo mês principal da ficha, com a média do mandato como contexto; a home mostra a média do grupo.

## Endereços e buscadores

Cada deputado(a) e senador(a) tem endereço próprio (`/deputado/<id>-<nome>`, `/senador/<id>-<nome>`), cada
votação do Placar também (`/placar/<id>`), assim como as seções (`/alertas`, `/placar`, `/politicos`, `/partidos`,
`/comparar`, `/presenca`, `/minha-cidade`, `/metodologia`, `/sobre`). `backend/seo.py` entrega o mesmo
`dist/index.html` com título, descrição, endereço canônico, Open Graph (com `og-image.png`), dados estruturados
(schema.org: `WebSite`, `WebPage`/`CollectionPage`/`AboutPage`, `Person`, `BreadcrumbList`) e, dentro de `#app`,
o conteúdo essencial da página em HTML, montado por `backend/seo_sections.py` com as mesmas funções que servem a
API (`citizen`, `votes`, `cities`): resumo da ficha, números e alertas da home, diretório de todas as fichas em
`/politicos`, lista de presença, catálogo do Placar com link para cada votação, decisão e votos de cada votação,
tabela de partidos, metodologia e sobre. É o que pessoas sem JavaScript, buscadores e assistentes leem; o bloco
usa o design system e vem marcado com `data-server-render="<endereço>"`.

No app, `app.script.js` guarda esse bloco ao abrir e cada tela o mantém enquanto a API não respondeu (e se ela
falhar), só no endereço a que ele pertence: outra ficha nunca herda o resumo anterior. Título da aba, canonical,
descrição e `noindex` acompanham a tela, com os mesmos textos do servidor (`frontend/data/site-pages.json`), para
que o que o buscador lê depois de executar o JavaScript seja o mesmo do HTML. Menu, rodapé, linhas de lista,
rostos, atalhos e cartões de votação são links reais (`<a href>`), que abrem em nova aba com Ctrl/Cmd ou botão do
meio; o clique simples continua navegando dentro do app. Endereço sem o nome redireciona (301) para o canônico;
endereço desconhecido recebe a página 404 do site, com `noindex`. Pares de comparação (`/comparar/a-vs-b`,
`/partidos/A-vs-B`) têm metadados próprios e `noindex`.

As páginas usam o cache do modo de produção, invalidado quando o banco, o build ou qualquer snapshot muda. O
servidor também responde `robots.txt` (a API fica fora do rastreamento), `sitemap.xml` (seções, fichas da lista
atual e votações do Placar, com a data da revisão de cada votação) e `llms.txt`. O endereço público vem de
`PAINEL_SITE_URL` (ex.: `https://seudominio.com.br`) ou, sem ela, do `Host` recebido pelo túnel.
