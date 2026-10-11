"""Eventos com data: o que precisa acontecer depois de uma eleição ou de uma posse.

Sem rede. Lê os snapshots e caches locais e diz, para cada evento, se está pendente, concluído ou
se ainda não chegou a hora. A atualização semanal executa as ações dos eventos pendentes.

- **Segundo turno (25/10/2026).** Depois da data, o arquivo de candidaturas do TSE é regenerado com o
  resultado final; a fotografia das eleições nas fichas e as candidaturas e votos de Minha cidade
  precisam ser coletados de novo. O evento fica pendente até o TSE regenerar os arquivos (a data de
  geração no snapshot e o ``Last-Modified`` dos caches passam da data do turno) ou até 90 dias
  depois, quando vira aviso para uma pessoa.
- **Troca de legislatura (1º/2/2027).** Aviso 30 dias antes com o roteiro, e janela de 45 dias depois
  em que a lista oficial muda a cada posse. O recorte "mandato atual" não troca sozinho (ver
  ``ingest/periods.py``), porque apagaria o mandato anterior das fichas.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest import periods  # noqa: E402

SECOND_ROUND_GRACE_DAYS = 90
TURNOVER_NOTICE_DAYS = 30
TURNOVER_WINDOW_DAYS = 45
# Ações do segundo turno: fichas (eleicoes-2026.json) e Minha cidade (candidaturas e votos de 2026).
SECOND_ROUND_ACTIONS = (
    ("event-elections", ("ingest/elections_2026.py", "--collect")),
    ("event-cities", ("ingest/cities.py", "--collect", "--refresh-election")),
)


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def parse_date(value) -> date | None:
    """ISO (``2026-10-07``), brasileiro (``07/10/2026``) ou HTTP (``Sat, 10 Oct 2026 03:00:00 GMT``)."""
    text = str(value or "").strip()
    if not text:
        return None
    for pattern, order in ((r"(\d{4})-(\d{2})-(\d{2})", (1, 2, 3)), (r"(\d{2})/(\d{2})/(\d{4})", (3, 2, 1))):
        match = re.search(pattern, text)
        if match:
            try:
                return date(*(int(match.group(i)) for i in order))
            except ValueError:
                return None
    try:
        return datetime.strptime(text, "%a, %d %b %Y %H:%M:%S %Z").date()
    except ValueError:
        return None


def second_round_event(root: Path, reference: date) -> dict:
    snapshots = root / "data" / "snapshots"
    elections = _read_json(snapshots / "eleicoes-2026.json", {}) or {}
    second_round = parse_date(elections.get("segundoTurno")) or date(2026, 10, 25)
    event = {"id": "second-round-2026", "date": second_round.isoformat(), "label": "Segundo turno de 2026"}
    if reference <= second_round:
        return {**event, "status": "not_due", "detail": f"Aguarda o segundo turno em {second_round.isoformat()}."}
    generated = parse_date((elections.get("fonte") or {}).get("geradoNoTse"))
    tse = root / "data" / "raw" / "tse"
    sources = {
        "eleicoes-2026.json": generated,
        "candidacies_2026": parse_date((_read_json(tse / "candidacies_2026_v2.meta.json", {}) or {}).get("lastModified")),
        "votes_2026": parse_date((_read_json(tse / "votacao_candidato_munzona_2026.meta.json", {}) or {}).get("lastModified")),
    }
    stale = sorted(name for name, when in sources.items() if when is None or when <= second_round)
    if not stale:
        return {**event, "status": "done", "detail": "Fichas e Minha cidade já refletem arquivos gerados após o segundo turno."}
    days = (reference - second_round).days
    status = "due" if days <= SECOND_ROUND_GRACE_DAYS else "overdue"
    detail = (f"{days} dias após o turno; ainda sem arquivo posterior ao turno em: " + ", ".join(stale) + ".")
    if status == "overdue":
        detail += " Verifique à mão no TSE se os arquivos foram regenerados."
    return {**event, "status": status, "detail": detail, "stale": stale,
            "actions": [{"name": name, "arguments": list(arguments)} for name, arguments in SECOND_ROUND_ACTIONS]}


def legislature_event(reference: date) -> dict:
    start = periods.next_legislature_start(reference)
    current_start = periods.legislature_start(periods.legislature(reference))
    event = {"id": f"legislature-{periods.legislature(reference) + 1}", "label": "Troca de legislatura"}
    if periods.legislature_turnover(reference, TURNOVER_WINDOW_DAYS):
        return {**event, "date": current_start.isoformat(), "status": "window",
                "detail": (f"Legislatura {periods.legislature(reference)} começou em {current_start.isoformat()}: a lista oficial "
                           "muda a cada posse; a guarda de regressão da lista fica relaxada por "
                           f"{TURNOVER_WINDOW_DAYS} dias. Recorte do mandato: {periods.MANDATE_START.isoformat()} "
                           "(troca manual, ver docs/deploy.md).")}
    days = (start - reference).days
    if days <= TURNOVER_NOTICE_DAYS:
        return {**event, "date": start.isoformat(), "status": "notice",
                "detail": (f"Posse em {start.isoformat()}, em {days} dias. Prepare a troca de legislatura: "
                           "roteiro em docs/deploy.md (Troca de legislatura).")}
    return {**event, "date": start.isoformat(), "status": "not_due", "detail": f"Posse em {start.isoformat()}."}


def pending_events(root: Path = ROOT, reference: date | None = None) -> list[dict]:
    reference = reference or periods.today()
    return [second_round_event(root, reference), legislature_event(reference)]


def summary(events: list[dict]) -> dict:
    return {
        "attention": [e["id"] for e in events if e["status"] in ("due", "overdue", "notice", "window")],
        "events": [{"id": e["id"], "status": e["status"], "detail": e["detail"]} for e in events],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    events = pending_events(args.root)
    print(json.dumps(events, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
