-include .env
PYTHON ?= python3
NODE ?= node
PORT ?= 8000
HOST ?= 127.0.0.1


.PHONY: ci deploy-data remote-build
.PHONY: help build dev prod test check db-init db-check db-backup import collect-legislative collect-profiles collect-senate deploy deploy-db deploy-status
help:
	@echo "make dev                Gera o app e inicia em localhost:8000"
	@echo "make check              Build, sintaxe e testes (sem downloads)"
	@echo "make db-init/db-check/db-backup  Preparação, verificação e backup SQLite"
	@echo "make import             Importa snapshots normalizados locais"
	@echo "make collect-legislative YEAR=2026  Coleta Câmara e Senado"
	@echo "make collect-profiles   Coleta manual de contatos, projetos e gabinete"
	@echo "make collect-senate     Coleta manual de atividade e autoria do Senado"
	@echo "make prod               Roda como em produção (cache, só localhost)"
	@echo "make deploy SERVER=...  Testa e publica o código no servidor"
	@echo "make deploy-data SERVER=...  Envia banco e snapshots (alias: deploy-db)"
	@echo "make ci                 Sintaxe e testes sem dados privados (CI)"

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
	$(PYTHON) ingest/legislative.py --year $(or $(YEAR),2026)

collect-profiles:
	$(PYTHON) ingest/profiles.py --collect

collect-senate:
	$(PYTHON) ingest/senado_attendance.py --collect --year $(or $(YEAR),2026)
	$(PYTHON) ingest/senado_activity.py --collect --year $(or $(YEAR),2026)
	$(PYTHON) ingest/senado_projects.py --collect --year $(or $(YEAR),2026)

prod: build
	$(PYTHON) -m backend.server --prod --host 127.0.0.1 --port $(PORT)

# ---- Publicação (ver docs/deploy.md). SERVER e APP_DIR podem vir do .env ----
APP_DIR ?= /opt/painel
SSH ?= ssh
# Usuário comum com sudo (ex.: ubuntu na Magalu Cloud). Para root, use SUDO= (vazio).
SUDO ?= sudo
# Monta a página no servidor com os snapshots complementares que estiverem lá e reinicia o serviço.
REMOTE_BUILD = cd $(APP_DIR)/app && PAINEL_SNAPSHOTS=$(APP_DIR)/data/snapshots python3 scripts/build.py && chown -R painel:painel $(APP_DIR)/app && install -m 0644 deploy/painel.service /etc/systemd/system/painel.service && systemctl daemon-reload && systemctl enable --now painel && systemctl restart painel

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
	rsync -az --delete --rsync-path="$(SUDO) rsync" data/snapshots/ $(SERVER):$(APP_DIR)/data/snapshots/
	$(SSH) $(SERVER) "$(SUDO) sh -c 'cd $(APP_DIR)/data && chown -R painel:painel na-lupa.sqlite3.new snapshots && rm -f na-lupa.sqlite3-wal na-lupa.sqlite3-shm && mv -f na-lupa.sqlite3.new na-lupa.sqlite3 && ( [ -d $(APP_DIR)/app/scripts ] && $(REMOTE_BUILD) || true )'"
	rm -f data/backups/deploy.sqlite3
	@echo "Banco e snapshots publicados; página remontada e serviço reiniciado."

deploy-db: deploy-data

deploy-status:
	$(SSH) $(SERVER) 'systemctl is-active painel && curl -fsS http://127.0.0.1:8000/healthz && echo'
