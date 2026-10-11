"""Períodos derivados da data: ano corrente, último mês fechado, anos do mandato e legislatura.

Centraliza o que antes era data fixa nos coletores (``2026``, ``1-9``, ``(2026, 9)``), para que
a atualização automática atravesse viradas de mês e de ano sem edição de código. A variável de
ambiente ``PAINEL_TODAY=AAAA-MM-DD`` fixa "hoje" para reconstruções reproduzíveis e testes.
"""
from __future__ import annotations

from datetime import date
import os
import re

# Mandato atual: legislatura 57 da Câmara, a partir de 1º de fevereiro de 2023; mesmo recorte no Senado.
MANDATE_START = date(2023, 2, 1)
MANDATE_LEGISLATURE = 57
LEGISLATURE_YEARS = 4
# Prazo oficial da Câmara para apresentar a nota da cota: 90 dias após o mês da despesa (ver docs/alerts.md).
CHAMBER_QUOTA_DEADLINE_DAYS = 90


def today() -> date:
    """Data de referência: ``PAINEL_TODAY`` quando definida, senão a data local."""
    value = os.environ.get("PAINEL_TODAY")
    if value:
        try:
            return date.fromisoformat(value.strip())
        except ValueError as error:
            raise ValueError(f"PAINEL_TODAY inválida: {value!r} (use AAAA-MM-DD)") from error
    return date.today()


def current_year(reference: date | None = None) -> int:
    return (reference or today()).year


def previous_month(reference: date | None = None) -> tuple[int, int]:
    """(ano, mês) do mês anterior ao de referência; em janeiro, dezembro do ano anterior."""
    reference = reference or today()
    if reference.month == 1:
        return reference.year - 1, 12
    return reference.year, reference.month - 1


def closed_months(year: int, reference: date | None = None, start: date = MANDATE_START) -> tuple[int, ...]:
    """Meses de ``year`` já encerrados na data de referência, a partir do início do mandato.

    Ano anterior: todos (em 2023, de fevereiro); ano corrente: até o mês anterior; ano futuro: nenhum.
    """
    reference = reference or today()
    if year > reference.year or year < start.year:
        return ()
    last = 12 if year < reference.year else reference.month - 1
    first = start.month if year == start.year else 1
    return tuple(range(first, last + 1))


def history_years(reference: date | None = None, start: date = MANDATE_START) -> tuple[int, ...]:
    """Anos fechados do mandato: do início até o ano anterior ao corrente."""
    reference = reference or today()
    return tuple(range(start.year, reference.year))


def quota_closed_through(reference: date | None = None, deadline_days: int = CHAMBER_QUOTA_DEADLINE_DAYS) -> tuple[int, int]:
    """Último (ano, mês) cujo prazo de apresentação das notas da cota já encerrou na data de referência."""
    reference = reference or today()
    year, month = previous_month(reference)
    while True:
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        last_day = date(next_year, next_month, 1).toordinal() - 1
        if last_day + deadline_days <= reference.toordinal():
            return year, month
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)


def legislature(reference: date | None = None) -> int:
    """Número da legislatura da Câmara em vigor na data (57ª: fev/2023 a jan/2027)."""
    reference = reference or today()
    months = (reference.year - MANDATE_START.year) * 12 + reference.month - MANDATE_START.month
    return MANDATE_LEGISLATURE + months // (12 * LEGISLATURE_YEARS)


def legislature_start(number: int) -> date:
    """1º de fevereiro do ano em que a legislatura começou."""
    return date(MANDATE_START.year + LEGISLATURE_YEARS * (number - MANDATE_LEGISLATURE), MANDATE_START.month, 1)


def parse_months(value: str | None, default: tuple[int, ...] | None = None) -> tuple[int, ...]:
    """Meses em lista ou intervalos: ``1,2,3``, ``1-9``, ``2..12``; sem valor, devolve ``default``."""
    if value is None or not value.strip():
        if default is None:
            raise ValueError("Informe ao menos um mês")
        return tuple(default)
    months: set[int] = set()
    for part in re.split(r"[,;]", value):
        token = part.strip()
        if not token:
            continue
        match = re.fullmatch(r"(\d{1,2})(?:(?:-|\.\.)(\d{1,2}))?", token)
        if not match:
            raise ValueError(f"Mês inválido: {token}")
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if not 1 <= first <= 12 or not 1 <= last <= 12 or last < first:
            raise ValueError(f"Mês fora do intervalo: {token}")
        months.update(range(first, last + 1))
    if not months:
        raise ValueError("Informe ao menos um mês")
    return tuple(sorted(months))


def parse_period(value: str) -> tuple[int, int]:
    """``AAAA-MM`` → (ano, mês)."""
    match = re.fullmatch(r"(\d{4})-(\d{2})", value.strip())
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise ValueError(f"Período inválido: {value!r} (use AAAA-MM)")
    return int(match.group(1)), int(match.group(2))
