# Arquitetura

Aplicação pequena com HTML/CSS/JavaScript sem framework, API Python com biblioteca padrão e SQLite. Não há ORM, bundler JavaScript, serviços separados ou etapa npm.

```text
frontend/ + data/snapshots/ → scripts/build.py → dist/index.html
navegador → /api/* → backend/ → data/na-lupa.sqlite3
fontes públicas → ingest/ → data/imports/ → importação transacional → SQLite
```

## Responsabilidades

- `backend/server.py`: HTTP e rotas. Serve apenas o HTML gerado e a API, nunca as pastas de dados.
- `backend/public_store.py`: importação, consultas e agregados. Valores monetários em centavos; reembolso e remuneração permanecem separados.
- `backend/cidadao.py`: apresenta os dados e sinais existentes em linguagem simples para as telas principais.
- `backend/config.py`, `schema.sql`, `database.py`: caminhos, esquema e manutenção do banco.
- `frontend/index.template.html`: estrutura do documento e navegação.
- `frontend/styles/`: tokens, componentes compartilhados e estilos por área. Ver [design system](design-system.md).
- `frontend/scripts/app.script.js`: estado, roteamento e telas editoriais. Os outros scripts agrupam as áreas de políticos, exploração, presença e análise.
- `scripts/build.py`: montagem determinística, com ordem de CSS e JavaScript explícita. O script principal inicializa após as views. Arquivos gerados não são editados manualmente.
- `ingest/`: adaptadores atuais. `ingest/editorial/`: coletores da amostra original e dos dados complementares, separados do runtime.
- `data/snapshots/`: snapshots editoriais locais; não são a base nacional. Toda a pasta `data/`, incluindo `imports/`, `raw/` e os snapshots, fica fora do Git.
- `tests/`: verificações Python e Node sem acesso à rede; bancos temporários nos testes.
- `archive/` e `artifacts/`: recuperação local e imagens, fora do Git.

## Regras simples

Preservar os contratos `/api/*` ao mover código. Filtrar e paginar no servidor; nunca embutir o SQLite no HTML. Views recebem valores calculados no backend, sem duplicar regras de sinais. Os scripts atuais compartilham escopo no bundle: novos helpers devem ter prefixo da área até uma futura migração justificada para módulos.

A home editorial e os perfis detalhados originais são um recorte de dez deputados. A consulta dinâmica deve informar cobertura própria, sem apresentar essa amostra como toda a Câmara. Anotações e acompanhamentos ficam no `localStorage` do navegador.

O servidor é de desenvolvimento e escuta em `127.0.0.1` por padrão. O suporte a `--host` permite teste de rede deliberado, mas não transforma este servidor em hospedagem de produção.
