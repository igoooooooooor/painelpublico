# Desenvolvimento

## Branches e commits

- `main`: versão validada compartilhada no GitHub.
- Branch curta por tarefa: `codex/feature-name`, `codex/fix-name` ou `codex/chore-name`.
- Não precisamos de `develop`, release branches ou Gitflow neste estágio.
- Commits pequenos e coerentes: `feat: ...`, `fix: ...`, `refactor: ...`, `docs: ...`, `test: ...`, `chore: ...`. Descrição clara em inglês; o prefixo indica o tipo.
- Execute `make check`, revise `git diff --check` e confira a interface antes de integrar. Use fast-forward quando possível; evite reescrever histórico compartilhado.
- Não versionar qualquer conteúdo de `data/` (inclusive snapshots complementares), SQLite, downloads, caches, backups, `.env`, chaves ou `dist/`. Versione somente modelos sem credenciais, como `.env.example`.
- Antes de enviar, revise `git diff --cached` e `git diff --cached --name-only`. Adicione arquivos explicitamente e envie apenas a branch de trabalho; nunca use `git push --all`, `--mirror` ou publique branches de arquivo local. Remover um segredo do último commit não o remove dos anteriores.

```sh
git switch -c codex/change-name
make check
git add <changed-files>
git commit -m "feat: describe delivered behavior"
git switch main
git merge --ff-only codex/change-name
```

O remoto é `https://github.com/igor05k/painelpublico.git`. Publicação de repositório e deploy são decisões separadas. O histórico público começa com a exportação revisada do código; o histórico anterior com dados fica somente no ambiente local.

`make check` monta a interface sem snapshots privados e roda as verificações de sintaxe e testes locais. Os testes não fazem downloads nem dependem de `data/snapshots/editorial.json`.

## Linguagem e neutralidade

O projeto é apartidário e só usa informações públicas ([Aviso legal](LEGAL-NOTICE.md)). Textos da interface descrevem números, não intenções:

- Prefira termos descritivos como “incomum”, “acima do habitual” e “para conferir”. Evite “fora do normal”, “estranho”, “suspeito”, “abuso”, “farra” e termos que sugiram culpa ou crime.
- Todo alerta deve ter regra fixa, documentada e igual para todas as pessoas, de qualquer partido, além de indicar a fonte oficial e lembrar que não indica irregularidade.
- Não selecione, destaque ou ordene pessoas por partido ou posição política, exceto em comparações explícitas e simétricas entre partidos.

## Código e dados

Use inglês em nomes de arquivos, diretórios e identificadores internos do código (funções, classes, variáveis, constantes, classes CSS e IDs do DOM). Comentários e docstrings podem ficar em pt-BR; mantenha os textos da interface em pt-BR. Preserve nomes oficiais e contratos de integração: campos das fontes, rotas e campos públicos da API, esquema SQLite, snapshots existentes, variáveis de ambiente e identidade dos serviços em produção. Traduções desses contratos exigem migração explícita e compatível; não renomeie dados locais mecanicamente. Ao renomear código, atualize imports, referências, testes e documentação.

Python usa quatro espaços; JavaScript/CSS usam dois, conforme `.editorconfig`. Preserve o estilo do trecho editado e evite reformatação em massa. O build, a API e as coletas principais não precisam de dependências de terceiros. Pandas é opcional para `ingest/editorial/scrape_travel.py` e `ingest/editorial/tse_totals.py`. A coleta opcional dos PDFs de presença do Senado usa `pdfplumber`, isolado em `ingest/senate-requirements.txt`; a reconstrução offline e os testes não dependem dele.

Use o design system existente, mantenha bordas neutras e preserve a home. Ao alterar uma regra financeira ou consulta, teste resultados e casos ausentes; não crie testes que só espelham CSS. Antes de mexer no esquema ou reimportar dados relevantes, use `make db-backup`. Registre novas fontes e limitações em `docs/data.md`.
