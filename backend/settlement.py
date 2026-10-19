"""Meses com as notas da cota já assentadas: a regra única do custo do mandato e da média da cota.

As notas de um mês chegam por semanas (prazo de 90 dias na Câmara). Um mês só entra numa média com
``SETTLE_MONTHS`` meses de folga até a fotografia do banco (``meta.snapshotAt``). Sem nenhum mês com a
folga, valem todos: a tela avisa. Mesma regra de ``PROFILE_COST_SETTLE_MONTHS`` em
``frontend/scripts/profile-cost.js``.
"""
from __future__ import annotations

import re

SETTLE_MONTHS = 3


def serial(period):
    """Meses desde o ano zero para 'AAAA-MM'."""
    return int(period[:4]) * 12 + int(period[5:7]) - 1


def _period(serial_value):
    return f'{serial_value // 12:04d}-{serial_value % 12 + 1:02d}'


def settled_cutoff(as_of):
    """Último mês 'AAAA-MM' com as notas assentadas na fotografia ``as_of`` (ISO), ou None sem data."""
    if not isinstance(as_of, str) or not re.match(r'\d{4}-\d{2}', as_of):
        return None
    return _period(serial(as_of[:7]) - SETTLE_MONTHS)


def settled_periods(periods, as_of):
    """Meses com as notas da cota assentadas (3 meses de folga até ``as_of``); sem nenhum, todos, em ordem."""
    ordered = sorted({period for period in periods if isinstance(period, str) and re.fullmatch(r'\d{4}-\d{2}', period)})
    cutoff = settled_cutoff(as_of)
    settled = [period for period in ordered if cutoff is None or period <= cutoff]
    return settled or ordered
