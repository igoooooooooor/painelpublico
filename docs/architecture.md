# Arquitetura

Aplicação pequena com HTML/CSS/JavaScript sem framework, API Python com biblioteca padrão e SQLite. Não há ORM, bundler JavaScript, serviços separados ou etapa npm.

```text
frontend/ + frontend/data/ + snapshots complementares opcionais → scripts/build.py → dist/index.html
navegador → /api/* → backend/ → data/na-lupa.sqlite3 (base parlamentar e despesas)
fontes públicas → ingest/ → data/imports/ → importação transacional → SQLite
```

## Responsabilidades

- `backend/server.py`: HTTP e rotas. Serve apenas o HTML gerado e a API, nunca as pastas de dados.
- `backend/public_store.py`: importação transacional, agregados e sinais de triagem. Valores monetários em centavos; reembolso e remuneração permanecem separados.
- `backend/cidadao.py`: apresenta os dados e sinais existentes em linguagem simples para as telas e gera o CSV com as notas de cada ficha.
- `backend/config.py`, `schema.sql`, `database.py`: caminhos, esquema e manutenção do banco.
- `frontend/index.template.html`: estrutura do documento e navegação.
- `frontend/styles/`: tokens, componentes compartilhados e estilos por área. Ver [design system](design-system.md).
- `frontend/scripts/app.script.js`: estado e roteamento. `home-view.js` mostra resumos consultados no SQLite; os outros scripts agrupam as áreas de políticos, alertas, presença, comparações e partidos.
- `frontend/scripts/profile-data.js`: identidade canônica e leitura compartilhada de contatos, projetos, gabinete, presença, votos e eleição de 2026. Cada ficha pede seu complemento em `/api/c/perfil/<id>` quando disponível, sem embutir todos os perfis no HTML; salário de referência é separado de pagamento individual.
- `scripts/build.py`: montagem determinística, com ordem de CSS e JavaScript explícita. O build não precisa de snapshots locais; os quatro resumos do Placar vêm de metadados versionados em `frontend/data/votacoes.json`.
- `ingest/`: adaptadores atuais. `ingest/editorial/`: comandos manuais que guardam respostas oficiais em cache e montam complementos de presença e votos; não definem o roster usado pela aplicação.
- `data/snapshots/`: complementos locais opcionais, não a base parlamentar. Toda a pasta `data/`, incluindo `imports/`, `raw/`, SQLite e snapshots, fica fora do Git.
- `tests/`: verificações Python e Node sem acesso à rede; bancos temporários nos testes.
- `archive/` e `artifacts/`: recuperação local e imagens, fora do Git.

## Regras simples

Preservar os contratos `/api/*` ao mover código. Filtrar e paginar no servidor; nunca embutir o SQLite no HTML. Views recebem valores calculados no backend, sem duplicar regras de sinais. Os scripts atuais compartilham escopo no bundle: novos helpers devem ter prefixo da área até uma futura migração justificada para módulos.

Home, resumo, lista e fichas consultam a lista oficial e os reembolsos importados no SQLite. Totais e médias usam os registros observados; cadastro sem lançamento permanece sem gasto, não zero. Os cinco nomes na classificação da home são apenas uma seleção visual do ranking calculado sobre todos os deputados com dados. Resultados eleitorais ainda não cobrem todo o roster e por isso não aparecem na home; a ficha em PDF e a análise editorial antiga também foram removidas. Presença, votos selecionados e perfis são complementos opcionais, com fonte e cobertura própria. O app não grava nada no navegador.

O servidor é de desenvolvimento e escuta em `127.0.0.1` por padrão. O suporte a `--host` permite teste de rede deliberado, mas não transforma este servidor em hospedagem de produção.
