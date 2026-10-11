-include .env
PYTHON ?= python3
NODE ?= node
PORT ?= 8000
HOST ?= 127.0.0.1
# Padrões derivados da data (os coletores também derivam os seus; ver ingest/periods.py).
CURRENT_YEAR := $(shell date +%Y)
HISTORY_YEARS := $(shell seq 2023 $$(( $(CURRENT_YEAR) - 1 )))


.PHONY: ci deploy-data remote-build collect-vote-inventory collect-votes update-daily update-monthly pipeline-status pipeline-test-mail
.PHONY: help build dev prod test check db-init db-check db-backup import collect-legislative collect-profiles collect-senate collect-senate-mandate collect-project-status collect-elections collect-cities collect-amendments collect-accounts collect-mandate-cost audit-mandate-cost collect-mandate-history collect-senate-cost collect-tenure collect-senate-participation deploy deploy-db deploy-status
help:
	@echo "make dev                Gera o app e inicia em localhost:8000"
	@echo "make check              Build, sintaxe e testes (sem downloads)"
	@echo "make db-init/db-check/db-backup  Preparação, verificação e backup SQLite"
	@echo "make import             Importa snapshots normalizados locais"
	@echo "make collect-legislative [YEAR=AAAA]  Coleta Câmara e Senado (padrão: ano corrente)"
	@echo "make collect-profiles   Coleta manual de contatos, projetos e gabinete"
	@echo "make collect-senate     Presença de 2026 e votos/autoria do Senado no mandato"
	@echo "make collect-senate-mandate  Votos e autoria desde fev/2023, sem coletar PDFs"
	@echo "make collect-project-status  Consulta a situação dos projetos já listados"
	@echo "make collect-vote-inventory  Inventário do Placar, sem alterar o app (ano corrente por padrão)"
	@echo "make collect-votes     Catálogo do Placar a partir das revisões locais conferidas"
	@echo "make collect-elections  Liga a lista atual às candidaturas de 2026 no TSE"
	@echo "make collect-accounts [YEAR=AAAA]  Coleta contas municipais do SICONFI (padrão: ano anterior)"
	@echo "make collect-amendments [YEAR=AAAA]  Coleta emendas municipais do Portal da Transparência (padrão: ano corrente)"
	@echo "make collect-cities     Coleta manual da base nacional IBGE e TSE"
	@echo "make collect-mandate-cost  Coleta retomável de folha e moradia da Câmara nos meses já encerrados do ano"
	@echo "make audit-mandate-cost    Reconstrói os novos snapshots sem rede"
	@echo "make collect-mandate-history  Coleta os anos fechados do mandato na Câmara e recompõe a média"
	@echo "make collect-senate-participation  Votações nominais do mandato e licenças dos senadores (ficha)"
	@echo "make collect-tenure  Desde quando cada parlamentar está no cargo sem interrupção (rótulo da ficha)"
	@echo "make collect-senate-cost  Remuneração e equipe dos gabinetes do Senado no mandato (só agregados)"
	@echo "make prod               Roda como em produção (cache, só localhost)"
	@echo "make deploy SERVER=...  Testa e publica o código no servidor"
	@echo "make deploy-data SERVER=...  Envia banco e snapshots (alias: deploy-db)"
	@echo "make ci                 Sintaxe e testes sem dados privados (CI)"
	@echo "make update-daily       Atualização diária da cota: coleta, importa, verifica e publica (docs/deploy.md)"
	@echo "make update-monthly     Cadeia mensal: custo do mandato, histórico da cota, Senado e página (docs/deploy.md)"
	@echo "make pipeline-status    Último resultado da atualização automática"

build:
	$(PYTHON) scripts/build.py

dev: build
	$(PYTHON) -m backend.server --host $(HOST) --port $(PORT)

test:
	$(PYTHON) -m unittest discover -s tests
	$(NODE) --test tests/*.test.cjs

# CI roda sintaxe e testes sem dados privados nem downloads; check também monta o build sem snapshots.
ci:
	$(PYTHON) -m compileall -q backend ingest scripts
	@for file in frontend/scripts/*.js; do $(NODE) --check "$$file" || exit 1; done
	$(MAKE) test

check: build
	$(PYTHON) -m compileall -q backend ingest scripts
	@for file in frontend/scripts/*.js; do $(NODE) --check "$$file" || exit 1; done
	$(MAKE) test

db-init:
	$(PYTHON) -m backend.database init

db-check:
	$(PYTHON) -m backend.database check

db-backup:
	$(PYTHON) -m backend.database backup

import:
	$(PYTHON) -m backend.public_store

collect-legislative:
	$(PYTHON) ingest/legislative.py --year $(or $(YEAR),$(CURRENT_YEAR))

# Atualização automática (ver docs/deploy.md). DRY_RUN=1 faz tudo, menos trocar o banco publicado;
# DB_ONLY=1 pula perfis e situação dos projetos.
update-daily:
	$(PYTHON) -m ingest.pipeline daily $(if $(YEAR),--year $(YEAR),) $(if $(DRY_RUN),--dry-run,) $(if $(DB_ONLY),--db-only,)

# Cadeia mensal (custo do mandato, histórico da cota, Senado, página). PERIOD=AAAA-MM, ONLY=a,b e SKIP=c filtram.
update-monthly:
	$(PYTHON) -m ingest.pipeline monthly $(if $(PERIOD),--period $(PERIOD),) $(if $(DRY_RUN),--dry-run,) $(if $(ONLY),--only $(ONLY),) $(if $(SKIP),--skip $(SKIP),)

pipeline-status:
	$(PYTHON) -m ingest.pipeline status

pipeline-test-mail:
	$(PYTHON) -m ingest.pipeline test-mail

collect-profiles:
	$(PYTHON) ingest/profiles.py --collect

collect-senate:
	$(PYTHON) ingest/senate_attendance.py --collect $(if $(YEAR),--year $(YEAR),)
	$(MAKE) collect-senate-mandate

collect-senate-mandate:
	$(PYTHON) ingest/senate_activity.py --collect --mandate $(if $(THROUGH),--through $(THROUGH))
	$(PYTHON) ingest/senate_projects.py --collect --mandate $(if $(THROUGH),--through $(THROUGH))

collect-project-status:
	$(PYTHON) ingest/project_status.py --collect

collect-vote-inventory:
	$(PYTHON) -m ingest.chamber_vote_inventory --collect $(if $(YEAR),--year $(YEAR),) $(if $(START),--start $(START),) $(if $(THROUGH),--through $(THROUGH),) $(if $(OMISSIONS),--audit-omissions,)

collect-votes:
	$(PYTHON) -m ingest.chamber_votes --collect $(foreach through,$(THROUGH),--through $(through)) $(if $(REVIEWS),--reviews $(REVIEWS),)

collect-accounts:
	$(PYTHON) ingest/accounts.py --collect $(if $(YEAR),--year $(YEAR),)

collect-amendments:
	$(PYTHON) ingest/amendments.py --collect $(if $(YEAR),--year $(YEAR),)

collect-cities:
	$(PYTHON) ingest/cities.py --collect

collect-elections:
	$(PYTHON) ingest/elections_2026.py --collect

# Custos do ano corrente: retomável; sem MONTHS, os meses já encerrados do ano (ingest/periods.py).
collect-mandate-cost:
	$(PYTHON) ingest/chamber_payroll.py --collect $(if $(YEAR),--year $(YEAR),) $(if $(MONTHS),--months $(MONTHS),)
	$(PYTHON) ingest/chamber_housing.py --collect $(if $(YEAR),--year $(YEAR),) $(if $(MONTHS),--months $(MONTHS),)
	$(PYTHON) ingest/senate_payroll_pilot.py --collect
	$(PYTHON) ingest/mandate_cost_audit.py $(if $(YEAR),--year $(YEAR),)

audit-mandate-cost:
	$(PYTHON) ingest/chamber_payroll.py $(if $(YEAR),--year $(YEAR),) $(if $(MONTHS),--months $(MONTHS),)
	$(PYTHON) ingest/chamber_housing.py $(if $(YEAR),--year $(YEAR),) $(if $(MONTHS),--months $(MONTHS),)
	$(PYTHON) ingest/senate_payroll_pilot.py
	$(PYTHON) ingest/mandate_cost_audit.py $(if $(YEAR),--year $(YEAR),)

# Mandato desde fev/2023: coleta por ano, recompõe a média da ficha, gera presenca.json e importa no SQLite
# as notas enxutas da cota de 2023–2025, Câmara e Senado (faça make db-backup antes).
collect-senate-cost:
	$(PYTHON) ingest/senate_office_pilot.py
	$(PYTHON) ingest/senate_cost.py --collect

collect-senate-participation:
	$(PYTHON) ingest/senate_participation.py --collect

collect-tenure:
	$(PYTHON) ingest/tenure.py --collect

collect-mandate-history:
	@for year in $(HISTORY_YEARS); do $(PYTHON) ingest/legislative.py --year $$year --output data/raw/legislative/history/legislative-$$year.json || exit 1; done
	@for year in $(HISTORY_YEARS); do $(PYTHON) ingest/chamber_housing.py --collect --year $$year || exit 1; done
	$(PYTHON) ingest/chamber_mandate_history.py --collect
	@for year in $(HISTORY_YEARS); do $(PYTHON) ingest/chamber_payroll.py --collect --year $$year --output data/snapshots/chamber-payroll-$$year.json || exit 1; done
	@for year in $(HISTORY_YEARS); do $(PYTHON) ingest/chamber_service.py --year $$year || exit 1; done
	$(PYTHON) -m ingest.mandate_cost_composition
	$(PYTHON) ingest/quota_history.py
	$(PYTHON) -m backend.quota_history

prod: build
	$(PYTHON) -m backend.server --prod --host 127.0.0.1 --port $(PORT)

# ---- Publicação (ver docs/deploy.md). SERVER e APP_DIR podem vir do .env ----
APP_DIR ?= /opt/painel
SSH ?= ssh
# Usuário comum com sudo (ex.: ubuntu na Magalu Cloud). Para root, use SUDO= (vazio).
SUDO ?= sudo
# Monta a página no servidor com os snapshots complementares que estiverem lá e reinicia o serviço.
REMOTE_BUILD = cd $(APP_DIR)/app && ln -sfn $(APP_DIR)/data $(APP_DIR)/app/data && PAINEL_SNAPSHOTS=$(APP_DIR)/data/snapshots python3 scripts/build.py && chown -R painel:painel $(APP_DIR)/app && install -m 0644 deploy/dashboard.service /etc/systemd/system/painel.service && install -m 0644 deploy/painel-ingest.service deploy/painel-ingest.timer deploy/painel-ingest-monthly.service deploy/painel-ingest-monthly.timer deploy/painel-ingest-failure@.service /etc/systemd/system/ && ( [ -x $(APP_DIR)/venv/bin/python3 ] || python3 -m venv $(APP_DIR)/venv ) && $(APP_DIR)/venv/bin/pip install -q -r ingest/senate-requirements.txt && systemctl daemon-reload && systemctl enable --now painel && systemctl restart painel

deploy: check
	@test -n "$(SERVER)" || (echo "Defina SERVER=usuario@host (ou no .env)"; exit 1)
	rsync -az --delete --rsync-path="$(SUDO) rsync" --exclude-from=deploy/rsync-exclude.txt ./ $(SERVER):$(APP_DIR)/app/
	$(SSH) $(SERVER) "$(SUDO) sh -c '$(REMOTE_BUILD)'"
	$(MAKE) deploy-status

# Banco + snapshots complementares (nada disso vai para o Git).
deploy-data:
	@test -n "$(SERVER)" || (echo "Defina SERVER=usuario@host (ou no .env)"; exit 1)
	@mkdir -p data/backups
	rm -f data/backups/deploy.sqlite3
	$(PYTHON) -c "import sqlite3; s=sqlite3.connect('data/na-lupa.sqlite3'); d=sqlite3.connect('data/backups/deploy.sqlite3'); s.backup(d); d.close()"
	rsync -az --progress --rsync-path="$(SUDO) rsync" data/backups/deploy.sqlite3 $(SERVER):$(APP_DIR)/data/na-lupa.sqlite3.new
	rsync -az --delete --exclude-from=deploy/snapshots-local-only.txt --rsync-path="$(SUDO) rsync" data/snapshots/ $(SERVER):$(APP_DIR)/data/snapshots/
	$(SSH) $(SERVER) "$(SUDO) sh -c 'cd $(APP_DIR)/data && chown -R painel:painel na-lupa.sqlite3.new snapshots && rm -f na-lupa.sqlite3-wal na-lupa.sqlite3-shm && mv -f na-lupa.sqlite3.new na-lupa.sqlite3 && ( [ -d $(APP_DIR)/app/scripts ] && $(REMOTE_BUILD) || true )'"
	rm -f data/backups/deploy.sqlite3
	@echo "Banco e snapshots publicados; página remontada e serviço reiniciado."

deploy-db: deploy-data

deploy-status:
	$(SSH) $(SERVER) 'systemctl is-active painel && curl -fsS http://127.0.0.1:8000/healthz && echo'
	@for job in daily monthly; do $(SSH) $(SERVER) "python3 -c \"import json; s = json.load(open('$(APP_DIR)/data/status/$$job.json')); print('atualização $$job:', s['result'], s['finishedAt'], s['error'] or '')\" 2>/dev/null || echo 'atualização $$job: nunca executada'"; done
