# Revisões do Placar

Aqui ficam as revisões editoriais das votações do Plenário que entram no Placar:
`chamber-vote-reviews-<data>.json` (decisões principais) e
`chamber-vote-segment-reviews-<data>.json` (destaques e emendas) e
`chamber-vote-urgency-reviews-<data>.json` (pedidos de urgência, piloto). São arquivos escritos à mão,
com ID, status, data, textos em linguagem simples, links oficiais e evidência, conforme a
[Metodologia do Placar](../docs/voting-scoreboard.md).

Estão no Git de propósito: a revisão é pública e auditável, e o deploy automático a leva ao
servidor junto com o código. Para revisar: a fila semanal deixa rascunhos em
`data/reviews/chamber-vote-reviews-draft-<data>.json`; complete, mude o `status`, copie as
entradas prontas para o arquivo desta pasta com a mesma data, rode
`make collect-votes THROUGH=<data>` e commite.

Nada de dado pessoal entra aqui: só IDs públicos de votações e proposições, textos e links oficiais.
