# Instruções do projeto

Leia README.md e CONTRIBUTING.md. Preserve o visual e a home; siga docs/design-system.md. Não adicione framework, ORM ou ferramenta de build sem uma necessidade concreta. Frontend em frontend/, API e SQLite em backend/, coletores em ingest/, dados locais em data/.

Mudanças devem ter escopo pequeno, testes proporcionais e commits claros. Execute make check e git diff --check antes de concluir. Nunca commite bancos, downloads, caches, backups ou segredos. Não altere a cobertura declarada sem evidência nas fontes. Ausência não equivale a zero.

Delegue trabalho independente quando isso economizar tempo: worker luna_max_worker, fork_turns none, responsabilidade e caminhos explícitos. Não clone o agente raiz. Workers não devem reverter alterações de outras pessoas nem fazer commits sem coordenação.

A instrução atual do usuário prevalece. Termine mudanças locais autorizadas sem pedir confirmação desnecessária; preserve dados e trabalhos existentes.
