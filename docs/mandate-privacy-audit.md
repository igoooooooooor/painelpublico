# Auditoria de dados de servidores do Senado

A busca foi somente de leitura e procurou registros com a estrutura de 23 campos do CSV do Senado, sem imprimir valores, nomes ou registros encontrados.

O cache `data/raw/mandate-cost/senate-pilot/csv-schema.json` contém metadados e os 23 nomes das colunas. O snapshot `data/snapshots/senate-payroll-pilot.json` está indisponível e registra somente a análise do esquema. O coletor final lê as duas linhas de metadados/cabeçalho e para antes das linhas de pessoas.

Não foram encontrados registros compatíveis com o esquema nos caches e snapshots examinados, diretórios `__pycache__`, arquivos temporários `mandate*`, histórico do shell ou na cópia do ambiente shell desta tarefa. A busca genérica encontrou dois textos narrativos em snapshots e três trechos de código compilado com formato superficial de 23 campos; eles não correspondem ao esquema conhecido. Uma linha de saída na sessão principal também tem 23 células, mas a posição do ano não contém ano e nenhuma das 15 posições monetárias tem formato numérico. Sua origem não foi estabelecida; ela não foi declarada inofensiva apenas por falhar nesse teste. Não havia cópia separada do ambiente shell do agente do incidente.

**O log da sessão do agente continha o registro do incidente anterior:** uma linha de 23 colunas, fora do cabeçalho, em quatro cópias serializadas. Nenhum conteúdo dessa linha foi reproduzido nesta auditoria. Em 8/10/2026, o arquivo de log da sessão do incidente foi retirado da pasta de sessões do agente e movido para a Lixeira do computador local; a exclusão definitiva depende de esvaziar a Lixeira. A declaração anterior de “nenhum arquivo salvo” referia-se ao cache de dados e não cobria o registro persistente da ferramenta; esta auditoria corrige essa limitação.

Comando executado a partir da raiz do repositório:

```sh
THREAD_ROOT=<log da sessão principal do agente>
INCIDENT_AGENT=<log da sessão do incidente>
THREAD_SHELL=<cópia do ambiente shell da sessão>
python3 ingest/audit_payroll_privacy.py "$TMPDIR"/mandate* ~/.zsh_history "$THREAD_ROOT" "$INCIDENT_AGENT" "$THREAD_SHELL"
```

O script sempre inclui `data/raw/mandate-cost`, `data/snapshots` e os diretórios `__pycache__` do repositório. Mostra apenas caminhos, posições e contagens. As sessões nomeadas no comando pertencem à tarefa e ao incidente; não houve busca indiscriminada em conversas alheias.

A inspeção é limitada aos caminhos acessíveis e ao esquema conhecido. Um padrão de 23 campos não prova por si só que exista um registro de folha, e uma busca sem resultados não prova ausência de qualquer possível transformação ou cópia fora desse escopo.
