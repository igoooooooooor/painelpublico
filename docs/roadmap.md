# Próximas etapas

Atualizado em 7 de outubro de 2026. Itens pendentes são planejamento; não descrevem cobertura já disponível. A cobertura e suas datas estão em [Dados e SQLite](data.md).

## Agora

1. **Concluído:** organizar o projeto com arquitetura simples, Git, SQLite e design system, preservando a home e as telas atuais.
2. **Concluído:** consulta principal dos 513 deputados e dos registros do Senado, com cobertura explícita e distinção entre ausência e zero.
3. **Concluído para a fotografia de 6/10:** reconciliar metadados do Senado. O adaptador recupera UF do mandato, importa participação (titular/suplente) e intervalo do último exercício; a ficha mostra esses dados com a fonte. Os 82 registros e suas despesas são preservados, sem tratá-los como 82 cadeiras ou inferir exercício atual. Novas coletas ainda precisam de validação.
4. **Entregue nesta etapa:** ficha compartilhada nos caminhos principais, busca avançada e comparações; coleta manual de contato, situação e projetos para os 513 deputados, com gabinete/equipe publicados para 512. Os 82 registros do Senado recebem os contatos e o mandato disponíveis no XML reconciliado. Presença (512 deputados) e quatro votações do Placar usam a mesma leitura e não inferem ausência. Salário aparece como referência do cargo, sem afirmar pagamento individual. **Ainda pendente:** integrar projetos, gabinete, presença e votos do Senado, situação atual das proposições e folha parlamentar; ampliar os históricos e preencher as lacunas da Câmara somente com fonte validada. Os dez perfis editoriais mantêm seus detalhes e PDF separados.
5. Tornar a amostra editorial reproduzível em um clone novo: os coletores antigos não reconstroem todos os insumos de `editorial.json`.

## Expansão de dados

- Remuneração completa e histórico mensal: salário-base, benefícios, indenizações, retroativos e descontos separados.
- Contratos, licitações, atas e fornecedores pelo [PNCP](https://www.gov.br/pncp/). Contratos pertencem ao órgão; não são gastos pessoais de uma autoridade.
- Bens declarados, doadores e fornecedores eleitorais pelo [TSE](https://dadosabertos.tse.jus.br/).
- Governadores, prefeitos, vices, deputados estaduais/distritais, vereadores e servidores locais; integração por órgão e localidade.
- Ministério Público, tribunais de contas, militares, Banco Central, aposentados, pensionistas e servidores do Legislativo ainda fora do recorte atual.

## Qualidade e operação

- **Implementado:** modo de produção com cache, gzip, health check e limite de tempo de consultas; scripts de deploy e documentação do Cloudflare Tunnel. Há workflow de testes/deploy no GitHub Actions, mas a configuração e a execução no servidor não foram confirmadas nesta revisão.
- **Pendente no workflow:** resolver o build em checkout limpo. `make check` e o passo de deploy chamam o build, que exige `data/snapshots/editorial.json`; esse arquivo não é versionado nem preparado pelo workflow. Validar o pipeline sem publicar dados locais no Git.
- Otimizar a consulta ampla de despesas e medir com a base real antes de exposição pública.
- Automatizar atualização com data da coleta, validação e registro das falhas; hoje as coletas são manuais.
- Reconciliar entradas e saídas entre fotografias: o importador ainda pode manter um `sourceId` de cadastro atual em autoridades ausentes de uma nova lista, caso nenhuma outra fonte as atualize. Separar pertencimento à lista da preservação do histórico, sem apagar despesas.
- Aumentar cobertura de presença, votações e demais dados biográficos sem perder rastreabilidade da fonte e período.
- Definir e validar backups externos, restauração e testes de concorrência. O backup local consistente já existe; a política externa continua pendente.

Ordem de execução definida pelo usuário: completar fichas e refletir os dados em todo o app; ampliar remunerações; integrar contratos. Automação de atualização/deploy e backups externos ficam para depois. Dados eleitorais e expansão territorial continuam planejados. Toda ampliação deve mostrar dados ausentes como ausência, nunca como zero. Sinais de atenção não são conclusões de irregularidade.
