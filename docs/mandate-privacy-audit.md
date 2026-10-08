# Auditoria de dados de servidores do Senado

A busca foi somente de leitura e procurou registros com a estrutura de 23 campos do CSV do Senado, sem imprimir valores, nomes ou registros encontrados.

O cache `data/raw/mandate-cost/senate-pilot/csv-schema.json` contém metadados e os 23 nomes das colunas. O snapshot `data/snapshots/senate-payroll-pilot.json` está indisponível e registra somente a análise do esquema. O coletor final lê as duas linhas de metadados/cabeçalho e para antes das linhas de pessoas.

Não foram encontrados registros compatíveis com o esquema nos caches e snapshots examinados, diretórios `__pycache__`, arquivos `/private/tmp/mandate*`, `~/.zsh_history` ou na cópia do ambiente shell desta tarefa. A busca genérica encontrou dois textos narrativos em snapshots e três trechos de código compilado com formato superficial de 23 campos; eles não correspondem ao esquema conhecido. Uma linha de saída na sessão principal também tem 23 células, mas a posição do ano não contém ano e nenhuma das 15 posições monetárias tem formato numérico. Sua origem não foi estabelecida; ela não foi declarada inofensiva apenas por falhar nesse teste. Não havia cópia separada do ambiente shell do agente do incidente.

**O log da sessão do agente contém o registro do incidente anterior:** uma linha de 23 colunas, fora do cabeçalho, em quatro cópias serializadas. Portanto, a afirmação de que nenhuma linha ficou em logs seria falsa. Nenhum conteúdo dessa linha foi reproduzido nesta auditoria e nenhum log foi apagado. A declaração anterior de “nenhum arquivo salvo” referia-se ao cache de dados, mas não cobria o registro persistente da ferramenta; esta auditoria corrige essa limitação.

Comando executado a partir da raiz do repositório:

```sh
THREAD_ROOT=/Users/igorfernandes/.codex/sessions/2026/10/07/rollout-2026-10-07T22-26-23-01a1191e-614f-7461-afe5-f5f0c797eb4b.jsonl
INCIDENT_AGENT=/Users/igorfernandes/.codex/sessions/2026/10/07/rollout-2026-10-07T22-34-00-01a11925-5733-73e2-b6b1-82b35c4abb8d.jsonl
THREAD_SHELL=/Users/igorfernandes/.codex/shell_snapshots/01a1191e-614f-7461-afe5-f5f0c797eb4b.1791422784892565000.sh
python3 ingest/audit_payroll_privacy.py /private/tmp/mandate* ~/.zsh_history "$THREAD_ROOT" "$INCIDENT_AGENT" "$THREAD_SHELL"
```

O script sempre inclui `data/raw/mandate-cost`, `data/snapshots` e os diretórios `__pycache__` do repositório. Mostra apenas caminhos, posições e contagens. As sessões nomeadas no comando pertencem à tarefa e ao incidente; não houve busca indiscriminada em conversas alheias.

A inspeção é limitada aos caminhos acessíveis e ao esquema conhecido. Um padrão de 23 campos não prova por si só que exista um registro de folha, e uma busca sem resultados não prova ausência de qualquer possível transformação ou cópia fora desse escopo.
