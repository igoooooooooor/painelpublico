# Próximas etapas

Atualizado em 7 de outubro de 2026. Itens pendentes são planejamento; não descrevem cobertura já disponível. A cobertura e suas datas estão em [Dados e SQLite](data.md).

## Agora

1. **Concluído:** organizar o projeto com arquitetura simples, Git, SQLite e design system, preservando a home e as telas atuais.
2. **Concluído:** consulta principal dos 513 deputados e dos registros do Senado, com cobertura explícita e distinção entre ausência e zero.
3. **Concluído para a fotografia de 6/10:** reconciliar metadados do Senado. O adaptador recupera UF do mandato, importa participação (titular/suplente) e intervalo do último exercício; a ficha mostra esses dados com a fonte. Os 82 registros e suas despesas são preservados, sem tratá-los como 82 cadeiras ou inferir exercício atual. Novas coletas ainda precisam de validação.
4. **Entregue nesta etapa:** home e lista consultam os 513 deputados e 82 registros do Senado importados no SQLite; gastos sem lançamento continuam ausentes. As fichas usam a mesma identidade canônica, com complementos manuais para os 595 registros da fotografia. Presença (512 deputados) e quatro votações selecionadas usam linhas da fonte e não inferem ausência. Salário aparece como referência do cargo, sem afirmar pagamento individual. **Ainda pendente:** apurar faltas/justificativas e integrar gabinete do Senado, situação atual das proposições e folha parlamentar; ampliar os históricos e preencher as lacunas da Câmara somente com fonte validada.
5. **Completar as fichas — Etapa 1 revisada:** fichas canônicas e entradas legadas usam “Em 3 respostas” (cota, presença/Placar e maior alerta), seguidas de detalhes em acordeões. No celular, gastos começam abertos; a partir de 900 px, gastos e votos abrem lado a lado. Fontes e datas, salário de referência e limitações foram preservados. Os complementos continuam sob demanda em `/api/c/perfil/<id>`. Sem despesas, presença ou votos, a ficha indica ausência. Esta etapa reorganiza somente o frontend; não amplia a cobertura nem altera as regras de cálculo/alertas. **Etapa 2 pronta para revisão local:** 19 votações nominais abertas de 2026 e 788 associações de autoria/coautoria (462 PL, PLP e PEC distintos) do Senado integram fichas e comparadores por consultas sob demanda. A coleta dos Diários adiciona 42 listas validadas de comparecimento, com observações associadas a 80 perfis e links por sessão. Três eventos da agenda ficaram sem tabela validada e 215 linhas não tiveram associação segura ao cadastro; faltas, justificativas e percentual de assiduidade continuam ausentes. Os comparadores separam Câmara/Senado e não atribuem ranking a essa contagem de presença. Fontes, datas, recortes e lacunas estão documentados em `docs/data.md`. A ampliação é local, em branch própria; a home permanece preservada. **Etapa 3 aguarda revisão da Etapa 2 e branch própria:** consultar a situação atual de projetos da Câmara/Senado, guardar a data e exibir contagens/filtros por situação. Sem push ou deploy nesta entrega.
6. Integrar resultados eleitorais para cobertura ampla antes de reintroduzir o bloco eleitoral na home. O recorte antigo de dez perfis, seu PDF e a análise editorial de despesas foram removidos.

## Expansão de dados

- Remuneração completa e histórico mensal: salário-base, benefícios, indenizações, retroativos e descontos separados.
- Contratos, licitações, atas e fornecedores pelo [PNCP](https://www.gov.br/pncp/). Contratos pertencem ao órgão; não são gastos pessoais de uma autoridade.
- Bens declarados, doadores e fornecedores eleitorais pelo [TSE](https://dadosabertos.tse.jus.br/).
- Governadores, prefeitos, vices, deputados estaduais/distritais, vereadores e servidores locais; integração por órgão e localidade.
- Ministério Público, tribunais de contas, militares, Banco Central, aposentados, pensionistas e servidores do Legislativo ainda fora do recorte atual.

## Qualidade e operação

- **Implementado:** modo de produção com cache, gzip, health check e limite de tempo de consultas; scripts de deploy e documentação do Cloudflare Tunnel. Há workflow de testes/deploy no GitHub Actions, mas a configuração e a execução no servidor não foram confirmadas nesta revisão.
- **Concluído:** `make check` e o build de deploy funcionam em checkout limpo sem `data/snapshots/editorial.json`. A lista e os resumos parlamentares são lidos do SQLite; os snapshots complementares seguem locais.
- Otimizar a consulta ampla de despesas e medir com a base real antes de exposição pública.
- Automatizar atualização com data da coleta, validação e registro das falhas; hoje as coletas são manuais e o app não agenda nem inicia downloads.
- Reconciliar entradas e saídas entre fotografias: o importador ainda pode manter um `sourceId` de cadastro atual em autoridades ausentes de uma nova lista, caso nenhuma outra fonte as atualize. Separar pertencimento à lista da preservação do histórico, sem apagar despesas.
- Aumentar cobertura de presença, votações e demais dados biográficos sem perder rastreabilidade da fonte e período.
- Definir e validar backups externos, restauração e testes de concorrência. O backup local consistente já existe; a política externa continua pendente.

Ordem de execução definida pelo usuário: completar fichas e refletir os dados em todo o app; ampliar remunerações; integrar contratos. Automação de atualização/deploy e backups externos ficam para depois. Dados eleitorais e expansão territorial continuam planejados. Toda ampliação deve mostrar dados ausentes como ausência, nunca como zero. Sinais de atenção não são conclusões de irregularidade.
