"""Orquestrador das atualizações automáticas.

O comando ``daily`` executa a atualização diária da cota (Câmara e Senado) do ano corrente:
coleta, importa em uma cópia de trabalho do banco, verifica integridade e regressão, publica a
cópia por troca atômica e avisa por e-mail. Depois do banco, recompõe offline o snapshot do custo
do mandato quando já existe uma fotografia-base; também atualiza os snapshots das fichas (projetos
pelos arquivos anuais da Câmara), a situação dos projetos e a autoria e as votações do Senado.
O comando ``monthly`` roda a cadeia mensal do custo do mandato e do Senado (folha, moradia,
exercício, gabinete e presença da Câmara, histórico da cota no banco, composição do custo, folha,
exercício, presença, participação e tempo de mandato do Senado) e remonta a página. O comando ``weekly`` refaz o inventário de votações do Plenário, monta a fila editorial do
Placar e dos arquivos mantidos à mão e executa os eventos com data pendentes (recoleta das eleições
após o segundo turno), avisando quando há trabalho novo para uma pessoa. Cada etapa fica registrada
em ``data/status/<job>.json``.

Regras do orquestrador:

- uma execução por vez (lock em ``data/status/pipeline.lock``);
- o banco em uso nunca recebe escrita direta: a importação acontece em ``data/pipeline/`` e só
  substitui o banco publicado depois de passar nas verificações;
- uma coleta indisponível preserva a fotografia anterior (regra já existente da importação);
- uma queda acima do limite na lista oficial ou nas notas não é publicada;
- falha ou resultado parcial gera aviso por e-mail quando o SMTP está configurado.

Uso:
    python3 -m ingest.pipeline daily [--dry-run] [--year AAAA] [--db-only]
    python3 -m ingest.pipeline monthly [--dry-run] [--period AAAA-MM] [--only a,b] [--skip c]
    python3 -m ingest.pipeline weekly
    python3 -m ingest.pipeline status
    python3 -m ingest.pipeline test-mail
    python3 -m ingest.pipeline notify-failure --unit painel-ingest.service
"""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import json
import os
import shutil
import smtplib
import sqlite3
import ssl
import subprocess
import sys
import time
import traceback
import urllib.request
from contextlib import closing
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import DB_PATH, ROSTER_SOURCES  # noqa: E402
from backend.database import backup_database, check_database  # noqa: E402
from backend.public_store import import_documents  # noqa: E402
from ingest import calendar_events  # noqa: E402
from ingest.periods import current_year, history_years, legislature_turnover, parse_period, previous_month, today as reference_today  # noqa: E402

QUOTA_SOURCES = ("camara_ceap", "senado_ceaps")
DAILY_BACKUP_PREFIX = "na-lupa-daily-"
COLLECTOR_TIMEOUT_SECONDS = 1800
SNAPSHOT_TIMEOUT_SECONDS = 3600
# Etapas mensais podem levar horas na primeira execução (histórico de folha e moradia desde 2023).
MONTHLY_TOOL_TIMEOUT_SECONDS = 4 * 3600
LOCK_WAIT_SECONDS = 1800
TURNOVER_ROSTER_DROP = 0.5
JOB_LABELS = {"daily": "diária", "monthly": "mensal", "weekly": "semanal"}
# Validade dos arquivos anuais da Câmara na situação dos projetos: ano corrente a cada execução diária;
# anos fechados (projetos antigos ainda tramitam) uma vez por semana.
ARCHIVE_MAX_AGE_HOURS = 20
CLOSED_YEAR_MAX_AGE_HOURS = 24 * 7
MAIL_SUBJECT_PREFIX = "[Painel Público]"
RESULT_LABELS = {"ok": "concluída", "partial": "parcial", "failed": "FALHOU"}


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def log(message: str) -> None:
    print(f"{utc_now().strftime('%H:%M:%S')} {message}", flush=True)


class PipelineError(RuntimeError):
    """Falha que interrompe a execução antes de publicar."""


@dataclass
class PipelineConfig:
    data_dir: Path = ROOT / "data"
    db_path: Path = DB_PATH
    year: int = field(default_factory=current_year)
    dry_run: bool = False
    db_only: bool = False
    job: str = "daily"
    period: tuple[int, int] | None = None
    only: tuple[str, ...] = ()
    skip: tuple[str, ...] = ()
    lock_wait_seconds: int = LOCK_WAIT_SECONDS
    keep_backups: int = 7
    max_roster_drop: float = 0.05
    max_expense_drop: float = 0.10
    python: str = sys.executable
    environ: dict = field(default_factory=lambda: dict(os.environ))

    @property
    def status_dir(self) -> Path:
        return self.data_dir / "status"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "pipeline"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def document_path(self) -> Path:
        return self.data_dir / "imports" / "legislative.json"

    @property
    def work_db(self) -> Path:
        return self.work_dir / "na-lupa.work.sqlite3"

    @property
    def lock_path(self) -> Path:
        return self.status_dir / "pipeline.lock"

    @property
    def status_path(self) -> Path:
        return self.status_dir / f"{self.job}.json"

    @property
    def history_path(self) -> Path:
        return self.status_dir / f"{self.job}-history.jsonl"

    def wants(self, step_name: str) -> bool:
        """Filtro --only/--skip por nome de etapa (prefixo: ``payroll`` cobre ``payroll-2026``)."""
        if self.only and not any(step_name == name or step_name.startswith(name + "-") for name in self.only):
            return False
        return not any(step_name == name or step_name.startswith(name + "-") for name in self.skip)


class Run:
    """Registro de uma execução: etapas, resultado e gravação atômica do status."""

    def __init__(self, config: PipelineConfig, job: str | None = None):
        self.config = config
        self.job = job or config.job
        self.started = utc_now()
        self.steps: list[dict] = []
        self.result = "ok"
        self.error: str | None = None
        self.summary: dict = {}

    def step(self, name: str):
        return _Step(self, name)

    def downgrade(self, result: str) -> None:
        order = ("ok", "partial", "failed")
        if order.index(result) > order.index(self.result):
            self.result = result

    def to_dict(self) -> dict:
        finished = utc_now()
        return {
            "job": self.job,
            "result": self.result,
            "year": self.config.year,
            "period": f"{self.config.period[0]:04d}-{self.config.period[1]:02d}" if self.config.period else None,
            "dryRun": self.config.dry_run,
            "startedAt": self.started.isoformat(timespec="seconds"),
            "finishedAt": finished.isoformat(timespec="seconds"),
            "seconds": round((finished - self.started).total_seconds(), 1),
            "database": str(self.config.db_path),
            "error": self.error,
            "summary": self.summary,
            "steps": self.steps,
        }

    def write(self, history: bool = False) -> dict:
        """Grava data/status/daily.json; com ``history``, acrescenta uma linha ao histórico."""
        payload = self.to_dict()
        self.config.status_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.config.status_path, payload)
        if history:
            with self.config.history_path.open("a", encoding="utf-8") as handle:
                compact = {key: payload[key] for key in ("job", "result", "startedAt", "finishedAt", "seconds", "error")}
                compact["summary"] = payload["summary"]
                handle.write(json.dumps(compact, ensure_ascii=False) + "\n")
        return payload


class _Step:
    def __init__(self, run: Run, name: str):
        self.run = run
        self.record = {"name": name, "status": "running", "startedAt": utc_now().isoformat(timespec="seconds")}
        self.run.steps.append(self.record)
        self.clock = time.monotonic()

    def __enter__(self):
        log(f"[{self.record['name']}] início")
        return self

    def detail(self, **values) -> None:
        self.record.update(values)

    def partial(self, message: str) -> None:
        self.record["status"] = "partial"
        self.record["message"] = message
        self.run.downgrade("partial")

    def __exit__(self, exc_type, exc, _tb):
        self.record["seconds"] = round(time.monotonic() - self.clock, 1)
        self.record["finishedAt"] = utc_now().isoformat(timespec="seconds")
        if exc is not None:
            self.record["status"] = "failed"
            self.record["message"] = f"{type(exc).__name__}: {exc}"
            self.run.downgrade("failed")
            log(f"[{self.record['name']}] falhou: {exc}")
            return False
        if self.record["status"] == "running":
            self.record["status"] = "ok"
        log(f"[{self.record['name']}] {self.record['status']} em {self.record['seconds']}s")
        return False


def _atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


# ---- Lock -------------------------------------------------------------------------------------

class Lock:
    """Lock de arquivo compartilhado pelos jobs: espera até ``wait_seconds`` por outra execução e então recusa."""

    def __init__(self, path: Path, wait_seconds: int = 0, poll_seconds: float = 15.0):
        self.path = path
        self.wait_seconds = wait_seconds
        self.poll_seconds = poll_seconds
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        deadline = time.monotonic() + self.wait_seconds
        while True:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    self.handle.close()
                    self.handle = None
                    raise PipelineError(
                        f"Outra execução do pipeline está em andamento (lock em {self.path})."
                    ) from error
                time.sleep(self.poll_seconds)
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(f"{os.getpid()} {utc_now().isoformat(timespec='seconds')}\n")
        self.handle.flush()
        return self

    def __exit__(self, *_exc):
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None
        return False


# ---- Etapas -----------------------------------------------------------------------------------

def run_collector(config: PipelineConfig) -> subprocess.CompletedProcess:
    """Executa o coletor da cota em subprocesso; substituível nos testes."""
    command = [
        config.python, str(ROOT / "ingest" / "legislative.py"),
        "--year", str(config.year), "--output", str(config.document_path),
    ]
    log("coleta: " + " ".join(command[1:]))
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=COLLECTOR_TIMEOUT_SECONDS,
        env={**config.environ, "PYTHONUNBUFFERED": "1"},
    )


def collect(run: Run) -> None:
    config = run.config
    with run.step("collect") as step:
        config.document_path.parent.mkdir(parents=True, exist_ok=True)
        before = config.document_path.stat().st_mtime_ns if config.document_path.exists() else None
        try:
            completed = run_collector(config)
        except subprocess.TimeoutExpired as error:
            raise PipelineError(f"Coleta excedeu {COLLECTOR_TIMEOUT_SECONDS}s.") from error
        stderr_tail = (completed.stderr or "").strip().splitlines()[-5:]
        step.detail(exitCode=completed.returncode, stderrTail=stderr_tail)
        if completed.returncode not in (0, 1):
            raise PipelineError(f"Coletor terminou com código {completed.returncode}: {' | '.join(stderr_tail)}")
        after = config.document_path.stat().st_mtime_ns if config.document_path.exists() else None
        if after is None or after == before:
            raise PipelineError("O coletor não gravou um documento novo em " + str(config.document_path))
        if completed.returncode == 1:
            step.partial("Ao menos uma fonte ficou indisponível; a fotografia anterior dessa fonte é preservada.")


def validate_document(run: Run) -> dict:
    """Confere o documento antes de importar: fontes, ano esperado e o que será substituído."""
    config = run.config
    with run.step("validate") as step:
        try:
            payload = json.loads(config.document_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PipelineError(f"Documento de importação ilegível: {error}") from error
        sources = {s.get("id"): s for s in payload.get("sources", []) if isinstance(s, dict)}
        if not sources:
            raise PipelineError("Documento sem fontes.")
        statuses = {sid: s.get("status") for sid, s in sources.items()}
        step.detail(sources=statuses)
        for source_id in QUOTA_SOURCES:
            source = sources.get(source_id)
            if source is None:
                raise PipelineError(f"Fonte {source_id} ausente do documento.")
            period = str(source.get("period") or "")
            if source.get("status") in ("imported", "partial") and not period.startswith(str(config.year)):
                raise PipelineError(
                    f"Fonte {source_id} cobre o período '{period}', não {config.year}; "
                    "importar substituiria as notas do ano corrente."
                )
        usable = [sid for sid, status in statuses.items() if status in ("imported", "partial")]
        if not usable:
            raise PipelineError("Nenhuma fonte disponível nesta coleta; nada a importar.")
        unavailable = [sid for sid, status in statuses.items() if status == "unavailable"]
        if unavailable:
            step.partial("Fontes indisponíveis: " + ", ".join(unavailable))
        step.detail(authorities=len(payload.get("authorities", [])), expenses=len(payload.get("expenses", [])))
        return payload


def backup(run: Run) -> Path | None:
    config = run.config
    with run.step("backup") as step:
        if not config.db_path.is_file():
            step.detail(skipped="banco publicado ainda não existe")
            return None
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        target = config.backups_dir / f"{DAILY_BACKUP_PREFIX}{stamp}.sqlite3"
        suffix = 1
        while target.exists():
            target = config.backups_dir / f"{DAILY_BACKUP_PREFIX}{stamp}-{suffix}.sqlite3"
            suffix += 1
        destination = backup_database(config.db_path, target)
        removed = prune_backups(config.backups_dir, config.keep_backups)
        step.detail(backup=str(destination), removed=[p.name for p in removed])
        return destination


def prune_backups(directory: Path, keep: int) -> list[Path]:
    """Mantém só os ``keep`` backups diários mais recentes; backups manuais não são tocados."""
    candidates = sorted(directory.glob(f"{DAILY_BACKUP_PREFIX}*.sqlite3"))
    removed = []
    for path in candidates[: max(0, len(candidates) - keep)]:
        path.unlink()
        removed.append(path)
    return removed


def stage(run: Run) -> None:
    """Copia o banco publicado para a área de trabalho; a importação nunca toca o banco em uso."""
    config = run.config
    with run.step("stage") as step:
        config.work_dir.mkdir(parents=True, exist_ok=True)
        for leftover in config.work_dir.glob(config.work_db.name + "*"):
            leftover.unlink()
        if config.db_path.is_file():
            backup_database(config.db_path, config.work_db)
            step.detail(source=str(config.db_path))
        else:
            step.detail(source=None, note="banco novo será criado pela importação")


def import_into_work(run: Run) -> dict:
    config = run.config
    with run.step("import") as step:
        counts = import_documents([config.document_path], config.work_db)
        step.detail(imported=counts)
        return counts


def import_history_into_work(run: Run) -> None:
    """Notas de anos anteriores (fev/2023 até o ano passado) importadas na cópia de trabalho, nunca no banco em uso."""
    config = run.config
    with run.step("import-history") as step:
        completed = run_snapshot_collector(config, ("-m", "backend.quota_history", "--db", str(config.work_db)),
                                           timeout=MONTHLY_TOOL_TIMEOUT_SECONDS)
        stderr_tail = (completed.stderr or "").strip().splitlines()[-5:]
        step.detail(exitCode=completed.returncode, stderrTail=stderr_tail)
        if completed.returncode != 0:
            raise PipelineError(f"Importação do histórico da cota terminou com código {completed.returncode}: "
                                + " | ".join(stderr_tail))


def publish_database(run: Run, importer, statuses: dict | None = None) -> None:
    """Backup, cópia de trabalho, importação, verificação e troca atômica, nesta ordem."""
    config = run.config
    try:
        backup(run)
        stage(run)
        importer(run)
        verify(run, statuses or {})
        publish(run)
    finally:
        cleanup(config)


def _counts(db_path: Path) -> dict:
    """Contagens usadas no guarda de regressão; banco ausente conta como vazio."""
    result = {"roster": {sid: 0 for sid in ROSTER_SOURCES}, "expenses": {sid: 0 for sid in QUOTA_SOURCES},
              "authorities": 0, "historyNotes": 0, "snapshotAt": None}
    if not Path(db_path).is_file():
        return result
    with closing(sqlite3.connect(db_path, timeout=30)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        if "roster" in tables:
            for sid in ROSTER_SOURCES:
                result["roster"][sid] = db.execute("SELECT COUNT(*) FROM roster WHERE sourceId=?", (sid,)).fetchone()[0]
        if "expenses" in tables:
            for sid in QUOTA_SOURCES:
                result["expenses"][sid] = db.execute("SELECT COUNT(*) FROM expenses WHERE sourceId=?", (sid,)).fetchone()[0]
        if "authorities" in tables:
            result["authorities"] = db.execute("SELECT COUNT(*) FROM authorities").fetchone()[0]
        if "quota_history_notes" in tables:
            result["historyNotes"] = db.execute("SELECT COUNT(*) FROM quota_history_notes").fetchone()[0]
        if "meta" in tables:
            row = db.execute("SELECT value FROM meta WHERE key='snapshotAt'").fetchone()
            result["snapshotAt"] = row[0] if row else None
    return result


def regression_problems(before: dict, after: dict, config: PipelineConfig, statuses: dict) -> list[str]:
    """Quedas acima do limite não são publicadas; fontes indisponíveis mantêm o valor anterior e passam."""
    problems = []
    # Nos primeiros 45 dias de uma legislatura a lista oficial cresce a cada posse: uma lista menor que a
    # anterior não é regressão, e o limite da queda fica relaxado (nunca aceita lista vazia).
    roster_limit = TURNOVER_ROSTER_DROP if legislature_turnover(reference_today()) else config.max_roster_drop
    for sid in ROSTER_SOURCES:
        old, new = before["roster"][sid], after["roster"][sid]
        if statuses.get(sid) != "imported":
            continue
        if new == 0 and old > 0:
            problems.append(f"lista {sid} ficou vazia (antes {old})")
        elif old and (old - new) / old > roster_limit:
            problems.append(f"lista {sid} caiu de {old} para {new} (limite {roster_limit:.0%})")
    for sid in QUOTA_SOURCES:
        old, new = before["expenses"][sid], after["expenses"][sid]
        if statuses.get(sid) not in ("imported", "partial"):
            continue
        if old and (old - new) / old > config.max_expense_drop:
            problems.append(f"notas {sid} caíram de {old} para {new} (limite {config.max_expense_drop:.0%})")
    old, new = before["historyNotes"], after["historyNotes"]
    if old and (old - new) / old > config.max_expense_drop:
        problems.append(f"notas do histórico caíram de {old} para {new} (limite {config.max_expense_drop:.0%})")
    return problems


def verify(run: Run, statuses: dict) -> dict:
    config = run.config
    with run.step("verify") as step:
        check = check_database(config.work_db)
        step.detail(check={k: check[k] for k in ("ok", "schemaVersion", "quickCheck", "missingTables")},
                    foreignKeyErrors=len(check.get("foreignKeyErrors") or []))
        if not check["ok"]:
            raise PipelineError("O banco de trabalho não passou na verificação de integridade.")
        before, after = _counts(config.db_path), _counts(config.work_db)
        step.detail(before=before, after=after)
        problems = regression_problems(before, after, config, statuses)
        if problems:
            raise PipelineError("Regressão detectada, publicação recusada: " + "; ".join(problems))
        run.summary.update({
            "roster": after["roster"], "expenses": after["expenses"], "historyNotes": after["historyNotes"],
            "snapshotAt": after["snapshotAt"], "previousSnapshotAt": before["snapshotAt"],
        })
        if legislature_turnover(reference_today()):
            run.summary["turnover"] = "início de legislatura: guarda da lista oficial relaxada por 45 dias"
        return after


def publish(run: Run) -> None:
    """Troca o banco publicado pela cópia verificada em uma única operação do sistema de arquivos."""
    config = run.config
    with run.step("publish") as step:
        if config.dry_run:
            step.detail(skipped="dry-run: banco publicado não foi alterado")
            return
        for suffix in ("-journal", "-wal", "-shm"):
            if Path(str(config.db_path) + suffix).exists():
                raise PipelineError(
                    f"Existe {config.db_path.name}{suffix} ao lado do banco publicado: há escrita em andamento "
                    "ou um journal pendente. Publicação recusada."
                )
        config.db_path.parent.mkdir(parents=True, exist_ok=True)
        _replace_file(config.work_db, config.db_path)
        step.detail(published=str(config.db_path))


# ---- Snapshots das fichas (depois do banco) ---------------------------------------------------

SNAPSHOT_STEPS = (
    # (nome da etapa, argumentos depois do interpretador, texto no stdout que indica resultado parcial)
    ("profiles", ("ingest/profiles.py", "--collect"), "completo=False"),
    ("project-status", ("ingest/project_status.py", "--collect", "--max-age-hours", str(ARCHIVE_MAX_AGE_HOURS),
                        "--closed-year-max-age-hours", str(CLOSED_YEAR_MAX_AGE_HOURS)), None),
    ("senate-projects", ("ingest/senate_projects.py", "--collect", "--mandate"), None),
    ("senate-activity", ("ingest/senate_activity.py", "--collect", "--mandate"), None),
)


def run_snapshot_collector(config: PipelineConfig, arguments: tuple[str, ...],
                           timeout: int = SNAPSHOT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """Executa um coletor em subprocesso (``-m módulo`` ou caminho de script); substituível nos testes."""
    if arguments[0] == "-m":
        command = [config.python, *arguments]
    else:
        command = [config.python, str(ROOT / arguments[0]), *arguments[1:]]
    log("ferramenta: " + " ".join(arguments))
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
        env={**config.environ, "PYTHONUNBUFFERED": "1"},
    )


def run_tool(run: Run, name: str, arguments: tuple[str, ...], *, partial_marker: str | None = None,
             timeout: int = SNAPSHOT_TIMEOUT_SECONDS, environ: dict | None = None, failure: str = "partial") -> bool:
    """Roda um coletor como etapa. Falha vira resultado parcial (padrão) e a execução segue: cada coletor
    preserva o snapshot anterior sozinho. Devolve True quando a etapa terminou sem ressalva."""
    config = run.config
    if not config.wants(name):
        return False
    with run.step(name) as step:
        tool_config = config if environ is None else PipelineConfig(**{**config.__dict__, "environ": {**config.environ, **environ}})
        try:
            completed = run_snapshot_collector(tool_config, arguments, timeout=timeout)
        except subprocess.TimeoutExpired:
            step.partial(f"Coletor excedeu {timeout}s; saída anterior preservada.")
            return False
        stdout_tail = (completed.stdout or "").strip().splitlines()[-6:]
        stderr_tail = (completed.stderr or "").strip().splitlines()[-5:]
        step.detail(exitCode=completed.returncode, stdoutTail=stdout_tail, stderrTail=stderr_tail)
        if completed.returncode != 0:
            message = (f"Coletor terminou com código {completed.returncode}; saída anterior preservada. "
                       + " | ".join(stderr_tail or stdout_tail))
            if failure == "failed":
                raise PipelineError(message)
            step.partial(message)
            return False
        if partial_marker and any(partial_marker in line for line in stdout_tail):
            step.partial("Arquivos anuais incompletos; observações anteriores preservadas nas fichas afetadas.")
            return False
        return True


def _mandate_cost_skip_reason(config: PipelineConfig) -> tuple[str | None, bool]:
    """Retorna motivo e se uma fotografia existente pode ficar desatualizada."""
    if config.dry_run:
        return "dry-run: banco publicado não foi alterado", False
    path = ROOT / "data" / "snapshots" / "mandate-cost.json"
    if not path.exists():
        return "snapshot-base de custo ausente; atualização diária não o cria", False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "snapshot-base de custo existente está ilegível; custo publicado pode ficar desatualizado", True
    if (not isinstance(payload, dict)
            or payload.get("schemaVersion") not in (3, 4)
            or not isinstance(payload.get("profiles"), dict)
            or not payload["profiles"]):
        return "snapshot-base de custo existente é inválido; custo publicado pode ficar desatualizado", True
    expected_db = ROOT / "data" / "na-lupa.sqlite3"
    if Path(config.db_path).resolve() != expected_db.resolve():
        return "banco configurado difere da base lida pelo coletor; custo publicado pode ficar desatualizado", True
    return None, False


def update_mandate_cost_snapshot(run: Run) -> None:
    """Recalcula o custo a partir do banco publicado e dos complementos locais, sem rede."""
    config = run.config
    if not config.wants("mandate-cost"):
        return
    skip_reason, stale_risk = _mandate_cost_skip_reason(config)
    if skip_reason:
        with run.step("mandate-cost") as step:
            if stale_risk:
                step.partial(skip_reason)
            else:
                step.detail(skipped=skip_reason)
        return
    run_tool(run, "mandate-cost", ("-m", "ingest.mandate_cost_composition", "--preserve-coverage"),
             timeout=SNAPSHOT_TIMEOUT_SECONDS)


def update_snapshots(run: Run) -> None:
    """Atualiza o custo offline e, salvo ``db_only``, os demais snapshots diários."""
    update_mandate_cost_snapshot(run)
    if run.config.db_only:
        return
    for name, arguments, partial_marker in SNAPSHOT_STEPS:
        run_tool(run, name, arguments, partial_marker=partial_marker)


def _replace_file(source: Path, destination: Path) -> None:
    """``os.replace`` atômico; em sistemas de arquivos diferentes, copia ao lado e então troca."""
    try:
        os.replace(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        staging = destination.with_name(destination.name + ".new")
        shutil.copyfile(source, staging)
        os.replace(staging, destination)
        source.unlink()


def cleanup(config: PipelineConfig) -> None:
    for leftover in config.work_dir.glob(config.work_db.name + "*"):
        try:
            leftover.unlink()
        except OSError:
            pass


# ---- Aviso por e-mail -------------------------------------------------------------------------

@dataclass
class MailConfig:
    to: list[str]
    sender: str
    host: str
    port: int = 587
    user: str | None = None
    password: str | None = None
    security: str = "starttls"
    on_success: bool = False

    @classmethod
    def from_environ(cls, environ: dict) -> "MailConfig | None":
        to = [item.strip() for item in (environ.get("PAINEL_MAIL_TO") or "").split(",") if item.strip()]
        host = environ.get("PAINEL_SMTP_HOST")
        if not to or not host:
            return None
        return cls(
            to=to,
            sender=environ.get("PAINEL_MAIL_FROM") or environ.get("PAINEL_SMTP_USER") or to[0],
            host=host,
            port=int(environ.get("PAINEL_SMTP_PORT") or 587),
            user=environ.get("PAINEL_SMTP_USER") or None,
            password=environ.get("PAINEL_SMTP_PASSWORD") or None,
            security=(environ.get("PAINEL_SMTP_SECURITY") or "starttls").lower(),
            on_success=(environ.get("PAINEL_MAIL_ON_SUCCESS") or "").lower() in ("1", "true", "yes", "sim"),
        )


def send_mail(config: MailConfig, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = ", ".join(config.to)
    message["Subject"] = subject
    message.set_content(body)
    # Sem contexto próprio, o smtplib aceita qualquer certificado: a senha iria a quem interceptasse a conexão.
    context = ssl.create_default_context()
    if config.security == "ssl":
        client = smtplib.SMTP_SSL(config.host, config.port, timeout=30, context=context)
    else:
        client = smtplib.SMTP(config.host, config.port, timeout=30)
    with client:
        if config.security == "starttls":
            client.starttls(context=context)
        if config.user:
            client.login(config.user, config.password or "")
        client.send_message(message)


def compose_report(status: dict) -> tuple[str, str]:
    """Assunto e corpo em texto puro, legíveis no celular."""
    label = RESULT_LABELS.get(status["result"], status["result"])
    day = status["startedAt"][:10]
    job = JOB_LABELS.get(status.get("job"), status.get("job"))
    subject = f"{MAIL_SUBJECT_PREFIX} Atualização {job} {label} em {day}"
    lines = [
        f"Resultado: {label}",
        f"Início: {status['startedAt']}   Fim: {status['finishedAt']}   Duração: {status['seconds']}s",
        f"Banco: {status['database']}",
    ]
    if status.get("dryRun"):
        lines.append("Modo dry-run: o banco publicado não foi alterado.")
    if status.get("error"):
        lines += ["", "Erro:", status["error"]]
    summary = status.get("summary") or {}
    if summary:
        lines += ["", "Fotografia:"]
        for sid, count in (summary.get("roster") or {}).items():
            lines.append(f"  lista {sid}: {count}")
        for sid, count in (summary.get("expenses") or {}).items():
            lines.append(f"  notas {sid}: {count}")
        if summary.get("historyNotes"):
            lines.append(f"  notas do histórico: {summary['historyNotes']}")
        if summary.get("snapshotAt"):
            lines.append(f"  snapshotAt: {summary['snapshotAt']} (anterior: {summary.get('previousSnapshotAt')})")
    if status.get("period"):
        lines.append(f"Período de referência: {status['period']}")
    if summary.get("turnover"):
        lines.append(f"Aviso: {summary['turnover']}")
    events = summary.get("events")
    if events:
        lines += ["", "Eventos com data:"]
        for event in events.get("events", []):
            lines.append(f"  {event['id']}: {event['status']} — {event['detail']}")
    editorial = summary.get("editorial")
    if editorial:
        lines += ["", "Fila editorial:"]
        if editorial.get("placar") == "ok":
            lines.append(f"  Placar: {editorial.get('candidatos')} candidatos no inventário, "
                         f"{editorial.get('semRevisao')} sem revisão, {editorial.get('pendentes')} pendentes com motivo")
            if editorial.get("novos"):
                lines.append("  Novos sem revisão desde a fila anterior: " + ", ".join(editorial["novos"]))
        else:
            lines.append(f"  Placar: inventário indisponível ({editorial.get('placar')})")
        for warning in editorial.get("arquivosManuais") or []:
            lines.append(f"  Arquivo mantido à mão: {warning}")
        lines.append("  Detalhes: data/reviews/editorial-queue.md no servidor")
    lines += ["", "Etapas:"]
    for step in status.get("steps", []):
        line = f"  {step['name']}: {step['status']} ({step.get('seconds', '?')}s)"
        if step.get("message"):
            line += f" — {step['message']}"
        lines.append(line)
        if step.get("sources"):
            lines.append("    fontes: " + ", ".join(f"{k}={v}" for k, v in step["sources"].items()))
    lines += ["", f"Status completo: data/status/{status.get('job', 'daily')}.json no servidor."]
    return subject, "\n".join(lines) + "\n"


def notify(run: Run, status: dict, mail_sender=send_mail) -> None:
    """Avisa por e-mail (falha e parcial sempre; sucesso se PAINEL_MAIL_ON_SUCCESS) e faz o ping opcional."""
    config = run.config
    record = {"name": "notify", "status": "ok", "startedAt": utc_now().isoformat(timespec="seconds")}
    mail = MailConfig.from_environ(config.environ)
    summary = status.get("summary") or {}
    attention = bool(summary.get("editorial", {}).get("atencao") or summary.get("events", {}).get("attention"))
    should_mail = status["result"] != "ok" or attention or (mail is not None and mail.on_success)
    if mail is None:
        record["mail"] = "não configurado (PAINEL_MAIL_TO e PAINEL_SMTP_HOST)"
        if status["result"] != "ok":
            log("aviso: SMTP não configurado; a falha fica só no status e no journal")
    elif should_mail:
        subject, body = compose_report(status)
        try:
            mail_sender(mail, subject, body)
            record["mail"] = f"enviado para {', '.join(mail.to)}"
        except (OSError, smtplib.SMTPException) as error:
            record["mail"] = f"falha no envio: {type(error).__name__}: {error}"
            record["status"] = "failed"
            log(record["mail"])
    else:
        record["mail"] = "sucesso sem aviso (PAINEL_MAIL_ON_SUCCESS desligado)"
    ping_url = config.environ.get({"monthly": "PAINEL_HEALTHCHECK_URL_MONTHLY", "weekly": "PAINEL_HEALTHCHECK_URL_WEEKLY"}
                                  .get(run.job, "PAINEL_HEALTHCHECK_URL"))
    if ping_url:
        record["ping"] = ping(ping_url if status["result"] == "ok" else ping_url.rstrip("/") + "/fail")
    record["finishedAt"] = utc_now().isoformat(timespec="seconds")
    run.steps.append(record)
    log(f"[notify] {record['mail']}")


def ping(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return f"{url}: {response.status}"
    except OSError as error:
        return f"{url}: falha ({error})"


# ---- Execução ---------------------------------------------------------------------------------

def run_daily(config: PipelineConfig, mail_sender=send_mail) -> dict:
    """Executa a atualização diária e devolve o status gravado. Nunca levanta exceção por falha de etapa."""
    run = Run(config, "daily")
    log(f"atualização diária de {config.year}" + (" (dry-run)" if config.dry_run else ""))
    try:
        with Lock(config.lock_path, config.lock_wait_seconds):
            collect(run)
            payload = validate_document(run)
            statuses = {s["id"]: s.get("status") for s in payload["sources"]}
            publish_database(run, import_into_work, statuses)
            update_snapshots(run)
    except PipelineError as error:
        run.error = str(error)
        run.downgrade("failed")
    except Exception as error:  # noqa: BLE001 - qualquer falha inesperada vira status e aviso
        run.error = f"{type(error).__name__}: {error}\n{traceback.format_exc()}"
        run.downgrade("failed")
    status = run.write()
    notify(run, status, mail_sender=mail_sender)
    status = run.write(history=True)
    log(f"resultado: {RESULT_LABELS.get(status['result'], status['result'])}")
    return status


def monthly_steps(config: PipelineConfig) -> list[tuple[str, tuple[str, ...], int]]:
    """Cadeia mensal, na ordem de dependência. ``(nome, argumentos, timeout)``."""
    reference = reference_today()
    current = reference.year
    years = (*history_years(reference), current)
    steps: list[tuple[str, tuple[str, ...], int]] = []
    for year in history_years(reference):
        steps.append((f"legislative-{year}", ("ingest/legislative.py", "--year", str(year), "--output",
                                               f"data/raw/legislative/history/legislative-{year}.json"), SNAPSHOT_TIMEOUT_SECONDS))
    steps.append(("quota-history", ("ingest/quota_history.py",), SNAPSHOT_TIMEOUT_SECONDS))
    for year in years:
        payroll: tuple[str, ...] = ("ingest/chamber_payroll.py", "--collect", "--year", str(year))
        if year != current:
            payroll += ("--output", f"data/snapshots/chamber-payroll-{year}.json")
        steps.append((f"payroll-{year}", payroll, MONTHLY_TOOL_TIMEOUT_SECONDS))
        steps.append((f"housing-{year}", ("ingest/chamber_housing.py", "--collect", "--year", str(year)), MONTHLY_TOOL_TIMEOUT_SECONDS))
        steps.append((f"service-{year}", ("ingest/chamber_service.py", "--collect", "--year", str(year)), MONTHLY_TOOL_TIMEOUT_SECONDS))
    steps += [
        ("chamber-mandate-history", ("ingest/chamber_mandate_history.py", "--collect"), MONTHLY_TOOL_TIMEOUT_SECONDS),
        ("mandate-cost", ("-m", "ingest.mandate_cost_composition"), SNAPSHOT_TIMEOUT_SECONDS),
        ("senate-office-pilot", ("ingest/senate_office_pilot.py", "--auto-accept"), SNAPSHOT_TIMEOUT_SECONDS),
        ("senate-cost", ("ingest/senate_cost.py", "--collect"), SNAPSHOT_TIMEOUT_SECONDS),
        ("senate-attendance", ("ingest/senate_attendance.py", "--collect"), MONTHLY_TOOL_TIMEOUT_SECONDS),
        ("senate-activity", ("ingest/senate_activity.py", "--collect", "--mandate"), SNAPSHOT_TIMEOUT_SECONDS),
        ("senate-participation", ("ingest/senate_participation.py", "--collect"), SNAPSHOT_TIMEOUT_SECONDS),
        ("tenure", ("ingest/tenure.py", "--collect"), SNAPSHOT_TIMEOUT_SECONDS),
        ("build", ("scripts/build.py",), SNAPSHOT_TIMEOUT_SECONDS),
    ]
    if wants_data_release(config.environ):
        # Release público de dados no GitHub (docs/data.md#publicar-a-base); em dry-run só monta o pacote.
        steps.append(("publish-data", ("scripts/publish_data.py", *(("--dry-run",) if config.dry_run else ())),
                      SNAPSHOT_TIMEOUT_SECONDS))
    return steps


def wants_data_release(environ: dict) -> bool:
    """PAINEL_DATA_RELEASE=1 liga o release mensal de dados; o token vem de PAINEL_GITHUB_TOKEN."""
    return (environ.get("PAINEL_DATA_RELEASE") or "").strip().lower() in ("1", "true", "yes", "sim")


def run_monthly(config: PipelineConfig, mail_sender=send_mail) -> dict:
    """Cadeia mensal do custo do mandato e do Senado. Cada coletor é retomável e preserva a saída anterior;
    só o histórico da cota passa pelo banco, com o mesmo backup, cópia, verificação e troca atômica."""
    config = PipelineConfig(**{**config.__dict__, "job": "monthly",
                               "period": config.period or previous_month(reference_today())})
    run = Run(config, "monthly")
    log(f"atualização mensal (referência {config.period[0]:04d}-{config.period[1]:02d})"
        + (" (dry-run)" if config.dry_run else ""))
    try:
        with Lock(config.lock_path, config.lock_wait_seconds):
            for name, arguments, timeout in monthly_steps(config):
                if name == "quota-history":
                    if run_tool(run, name, arguments, timeout=timeout) and config.wants("import-history"):
                        try:
                            publish_database(run, import_history_into_work)
                        except PipelineError as error:
                            run.error = str(error)
                            run.downgrade("failed")
                    continue
                run_tool(run, name, arguments, timeout=timeout)
    except PipelineError as error:
        run.error = str(error)
        run.downgrade("failed")
    except Exception as error:  # noqa: BLE001 - qualquer falha inesperada vira status e aviso
        run.error = f"{type(error).__name__}: {error}\n{traceback.format_exc()}"
        run.downgrade("failed")
    status = run.write()
    notify(run, status, mail_sender=mail_sender)
    status = run.write(history=True)
    log(f"resultado: {RESULT_LABELS.get(status['result'], status['result'])}")
    return status


def run_weekly(config: PipelineConfig, mail_sender=send_mail) -> dict:
    """Inventário do Plenário do ano corrente até hoje e fila editorial. Avisa quando há trabalho novo."""
    config = PipelineConfig(**{**config.__dict__, "job": "weekly"})
    run = Run(config, "weekly")
    reference = reference_today()
    log(f"atualização semanal (inventário até {reference.isoformat()})")
    try:
        with Lock(config.lock_path, config.lock_wait_seconds):
            run_tool(run, "vote-inventory", ("-m", "ingest.chamber_vote_inventory", "--collect", "--year", str(reference.year),
                                             "--through", reference.isoformat()))
            if config.wants("editorial-queue"):
                with run.step("editorial-queue") as step:
                    completed = run_snapshot_collector(config, ("-m", "ingest.editorial_queue"))
                    stdout_lines = (completed.stdout or "").strip().splitlines()
                    step.detail(exitCode=completed.returncode, stdoutTail=stdout_lines[-4:],
                                stderrTail=(completed.stderr or "").strip().splitlines()[-5:])
                    if completed.returncode != 0:
                        raise PipelineError("Fila editorial não gerada: código " + str(completed.returncode))
                    summary_text = next((line[len("resumo: "):] for line in stdout_lines if line.startswith("resumo: ")), None)
                    if summary_text:
                        run.summary["editorial"] = json.loads(summary_text)
            run_due_events(run, reference)
    except PipelineError as error:
        run.error = str(error)
        run.downgrade("failed")
    except Exception as error:  # noqa: BLE001
        run.error = f"{type(error).__name__}: {error}\n{traceback.format_exc()}"
        run.downgrade("failed")
    status = run.write()
    notify(run, status, mail_sender=mail_sender)
    status = run.write(history=True)
    log(f"resultado: {RESULT_LABELS.get(status['result'], status['result'])}")
    return status


def run_due_events(run: Run, reference) -> None:
    """Executa as ações dos eventos com data pendentes e registra o estado de todos no resumo."""
    config = run.config
    events = calendar_events.pending_events(ROOT, reference)
    for event in events:
        for action in event.get("actions") or []:
            if event["status"] == "due":
                run_tool(run, action["name"], tuple(action["arguments"]), timeout=MONTHLY_TOOL_TIMEOUT_SECONDS)
    if any(event.get("actions") and event["status"] == "due" for event in events):
        events = calendar_events.pending_events(ROOT, reference)
    run.summary["events"] = calendar_events.summary(events)


def read_status(config: PipelineConfig) -> dict | None:
    if not config.status_path.is_file():
        return None
    return json.loads(config.status_path.read_text(encoding="utf-8"))


def notify_failure(config: PipelineConfig, unit: str, mail_sender=send_mail) -> int:
    """Chamado pelo systemd (OnFailure) quando a unidade termina sem gravar status: aviso de último recurso."""
    mail = MailConfig.from_environ(config.environ)
    status = read_status(config)
    lines = [f"A unidade {unit} terminou com falha.", ""]
    if status:
        lines += [f"Último status gravado: {status['result']} em {status['finishedAt']} (job {status['job']})."]
        if status.get("error"):
            lines += ["", status["error"]]
    else:
        lines.append(f"Nenhum status gravado em data/status/{config.job}.json.")
    lines += ["", f"Veja: journalctl -u {unit} -n 100"]
    if mail is None:
        print("\n".join(lines))
        print("SMTP não configurado; aviso impresso apenas no journal.", file=sys.stderr)
        return 1
    mail_sender(mail, f"{MAIL_SUBJECT_PREFIX} {unit} falhou", "\n".join(lines) + "\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DB_PATH, help="banco publicado (padrão: PAINEL_DB)")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="raiz de imports/, backups/, status/")
    commands = parser.add_subparsers(dest="command", required=True)
    daily = commands.add_parser("daily", help="coleta e importa a cota do ano corrente")
    daily.add_argument("--year", type=int, default=None)
    daily.add_argument("--dry-run", action="store_true", help="faz tudo, menos substituir o banco publicado")
    daily.add_argument("--db-only", action="store_true", help="só a cota no banco; não atualiza perfis nem situação dos projetos")
    daily.add_argument("--keep-backups", type=int, default=7)
    daily.add_argument("--max-roster-drop", type=float, default=0.05)
    daily.add_argument("--max-expense-drop", type=float, default=0.10)
    monthly = commands.add_parser("monthly", help="cadeia mensal do custo do mandato e do Senado")
    monthly.add_argument("--period", type=str, default=None, help="mês de referência AAAA-MM (padrão: o anterior)")
    monthly.add_argument("--dry-run", action="store_true", help="faz tudo, menos substituir o banco publicado")
    monthly.add_argument("--only", type=str, default="", help="só estas etapas (nomes separados por vírgula)")
    monthly.add_argument("--skip", type=str, default="", help="pula estas etapas")
    monthly.add_argument("--keep-backups", type=int, default=7)
    monthly.add_argument("--max-roster-drop", type=float, default=0.05)
    monthly.add_argument("--max-expense-drop", type=float, default=0.10)
    weekly = commands.add_parser("weekly", help="inventário do Plenário e fila editorial do Placar")
    weekly.add_argument("--only", type=str, default="", help="só estas etapas (vote-inventory, editorial-queue)")
    weekly.add_argument("--skip", type=str, default="")
    commands.add_parser("status", help="imprime o último status gravado de cada job")
    commands.add_parser("test-mail", help="envia um e-mail de teste com a configuração atual")
    failure = commands.add_parser("notify-failure", help="aviso de último recurso, usado pelo systemd OnFailure")
    failure.add_argument("--unit", default="painel-ingest.service")
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    data_dir = args.data_dir if args.data_dir.is_absolute() else ROOT / args.data_dir
    db_path = args.db if args.db.is_absolute() else ROOT / args.db
    if args.command == "daily":
        config = PipelineConfig(
            data_dir=data_dir, db_path=db_path, year=args.year or utc_now().year, dry_run=args.dry_run, db_only=args.db_only,
            keep_backups=args.keep_backups, max_roster_drop=args.max_roster_drop,
            max_expense_drop=args.max_expense_drop,
        )
        status = run_daily(config)
        return 0 if status["result"] != "failed" else 1
    if args.command == "monthly":
        names = lambda value: tuple(item.strip() for item in value.split(",") if item.strip())  # noqa: E731
        config = PipelineConfig(
            data_dir=data_dir, db_path=db_path, dry_run=args.dry_run, keep_backups=args.keep_backups,
            max_roster_drop=args.max_roster_drop, max_expense_drop=args.max_expense_drop, job="monthly",
            period=parse_period(args.period) if args.period else None, only=names(args.only), skip=names(args.skip),
        )
        status = run_monthly(config)
        return 0 if status["result"] != "failed" else 1
    if args.command == "weekly":
        names = lambda value: tuple(item.strip() for item in value.split(",") if item.strip())  # noqa: E731
        status = run_weekly(PipelineConfig(data_dir=data_dir, db_path=db_path, job="weekly", only=names(args.only), skip=names(args.skip)))
        return 0 if status["result"] != "failed" else 1
    unit = getattr(args, "unit", "") or ""
    config = PipelineConfig(data_dir=data_dir, db_path=db_path,
                            job=next((job for job in ("monthly", "weekly") if job in unit), "daily"))
    if args.command == "status":
        statuses = {}
        for job in ("daily", "weekly", "monthly"):
            statuses[job] = read_status(PipelineConfig(data_dir=data_dir, db_path=db_path, job=job)) or {"status": "nunca executado"}
        print(json.dumps(statuses, ensure_ascii=False, indent=2))
        return 0 if all(s.get("result") == "ok" for s in statuses.values()) else 1
    if args.command == "test-mail":
        mail = MailConfig.from_environ(config.environ)
        if mail is None:
            print("Defina PAINEL_MAIL_TO e PAINEL_SMTP_HOST (ver deploy/pipeline.env.example).", file=sys.stderr)
            return 1
        send_mail(mail, f"{MAIL_SUBJECT_PREFIX} Teste de aviso", "Se você recebeu esta mensagem, o aviso por e-mail está configurado.\n")
        print(f"E-mail de teste enviado para {', '.join(mail.to)} via {mail.host}:{mail.port}")
        return 0
    return notify_failure(config, args.unit)


if __name__ == "__main__":
    raise SystemExit(main())
