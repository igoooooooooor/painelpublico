"""Normalize current Senate process status without inferring unsupported outcomes."""
from __future__ import annotations

from datetime import date, datetime
import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit


API_BASE = "https://legis.senado.leg.br/dadosabertos"
OFFICIAL_HOSTS = {"legis.senado.leg.br", "legis.senado.gov.br"}

_LAW_CODES = {"LEI", "LCP", "LEI_COMPLEMENTAR", "LEI_ORDINARIA"}
_AMENDMENT_CODES = {"EC", "EMENDA_CONSTITUCIONAL"}
_ARCHIVE_CODES = {"ARQV", "ARQVD", "ARQV_CD"}
_REJECTION_CODES = {"RJTDA", "RJTDA(DT)"}
_LAW_STATUS_CODES = {"TNJR", "TNJRVETO"}


def _text(value: Any, limit: int = 500) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] or None


def _fold(value: Any) -> str:
    text = _text(value) or ""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).upper()


def _date_value(value: Any) -> str | None:
    """Return an ISO date or datetime only when the source value parses cleanly."""
    text = _text(value, 50)
    if not text:
        return None
    try:
        if len(text) == 10:
            return date.fromisoformat(text).isoformat()
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.isoformat()


def _movement_date(value: Any) -> date | None:
    text = _text(value, 50)
    if not text:
        return None
    try:
        return date.fromisoformat(text) if len(text) == 10 else datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).date()
    except ValueError:
        return None


def _official_url(value: Any) -> str | None:
    text = _text(value, 2000)
    if not text:
        return None
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or host not in OFFICIAL_HOSTS
        or parts.username
        or parts.password
    ):
        return None
    return text


def _project_id(row: dict[str, Any]) -> str | None:
    value = row.get("id")
    if isinstance(value, bool):
        return None
    text = str(value) if isinstance(value, (int, str)) else ""
    return text if text.isdigit() else None


def _in_progress(value: Any) -> bool | None:
    folded = _fold(value)
    if folded in {"S", "SIM", "TRUE", "1"}:
        return True
    if folded in {"N", "NAO", "FALSE", "0"}:
        return False
    return None


def _status_code(value: Any) -> str:
    return _fold(value).replace(" ", "")


def _state_kind(code: Any, description: Any) -> str | None:
    """Classify only specific terminal status codes or official descriptions."""
    status_code = _status_code(code)
    state = _fold(description)
    if status_code in _LAW_STATUS_CODES or state in {
        "TRANSFORMADA EM NORMA JURIDICA",
        "TRANSFORMADA EM NORMA JURIDICA COM VETO PARCIAL",
    }:
        return "norma"
    if status_code in _ARCHIVE_CODES or state in {
        "ARQUIVADA",
        "ARQUIVADA AO FINAL DA LEGISLATURA",
        "ARQUIVADO NA CAMARA DOS DEPUTADOS",
    }:
        return "arquivado"
    if status_code in _REJECTION_CODES or state in {
        "REJEITADA",
        "REJEITADA A MATERIA (DECISAO TERMINATIVA)",
    }:
        return "arquivado"
    return None


def _state_needs_detail(code: Any, description: Any) -> bool:
    if _state_kind(code, description):
        return True
    status_code = _status_code(code)
    state = _fold(description)
    return (
        status_code == "RTPA"
        or "RETIRAD" in state
        or "PREJUDICAD" in state
    )


def _unclassified_final(code: Any, description: Any) -> str | None:
    status_code = _status_code(code)
    state = _fold(description)
    if status_code == "RTPA" or "RETIRAD" in state:
        return "retirada"
    if "PREJUDICAD" in state:
        return "prejudicada"
    return None


def needs_detail(row: Any) -> bool:
    """Whether a batch row needs the richer process response for safe handling."""
    if not isinstance(row, dict) or not _project_id(row):
        return True
    if _norm_is_present(row.get("normaGerada")):
        return True
    situation = row.get("situacaoAtual")
    code = row.get("siglaSituacao")
    if _state_needs_detail(code, situation):
        return True
    if _in_progress(row.get("tramitando")) is False:
        return True
    # A missing flag or situation is incomplete; do not infer activity from it.
    if _in_progress(row.get("tramitando")) is None or not _text(situation):
        return True
    return False


def _norm_is_present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_text(value.get(key)) or value.get(key) is not None for key in (
            "tipo", "siglaTipo", "numero", "codigo"
        ))
    if isinstance(value, list):
        return any(_norm_is_present(item) for item in value)
    return False


def _canonical_norm_type(value: Any) -> tuple[str | None, str | None]:
    """Return the display type and supported class for explicit norm types."""
    folded = _fold(value).replace(" ", "_").replace("-", "_")
    if folded in {
        "LEI", "LEI_ORDINARIA", "LEI_COMPLEMENTAR", "LCP",
        "LEI_NUMERADA", "LEI_N",
    }:
        display = "Lei Complementar" if folded in {"LEI_COMPLEMENTAR", "LCP"} else "Lei"
        return display, "lei"
    if folded in {"EMENDA_CONSTITUCIONAL", "EC"}:
        return "Emenda Constitucional", "emenda"
    # These names are useful provenance but do not qualify as a law/EC result.
    if folded:
        return _text(value, 120), None
    return None, None


def _norm_type_key(value: Any) -> str:
    display, _ = _canonical_norm_type(value)
    return display or _fold(value)


def _number_key(value: Any) -> str | None:
    text = _text(str(value), 40) if value is not None else None
    if not text:
        return None
    if re.fullmatch(r"[\d\s.,/_-]+", text):
        digits = "".join(char for char in text if char.isdigit())
        return digits or None
    return _fold(text)


_NUMBER_RE = re.compile(r"\b(?:N[º°O.]?\s*)?(\d[\d.]*)\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _norm_from_text(value: str) -> tuple[dict[str, Any] | None, str | None]:
    text = _text(value, 500)
    if not text:
        return None, None
    folded = _fold(text)
    if folded.startswith("EMENDA CONSTITUCIONAL"):
        display, group = "Emenda Constitucional", "emenda"
    elif folded.startswith("LEI COMPLEMENTAR"):
        display, group = "Lei Complementar", "lei"
    elif folded.startswith("LEI ORDINARIA") or folded.startswith("LEI ") or folded == "LEI":
        display, group = "Lei", "lei"
    else:
        return None, None
    number_match = _NUMBER_RE.search(text)
    year_matches = _YEAR_RE.findall(text)
    number = number_match.group(1) if number_match else None
    year = int(year_matches[-1]) if year_matches else None
    return {"tipo": display, "numero": number, "ano": year, "url": None}, group


def _norm_from_object(value: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, bool]:
    raw_type = _text(value.get("tipo"), 120)
    sigla_type = _text(value.get("siglaTipo"), 80)
    display, group = _canonical_norm_type(raw_type)
    code_display, code_group = _canonical_norm_type(sigla_type)
    conflict = bool(group and code_group and group != code_group)
    if display is None:
        display, group = code_display, code_group
    number_value = value.get("numero")
    number = None if number_value is None else _text(str(number_value), 40)
    year_value = value.get("anoAssinatura", value.get("ano"))
    year: int | None = None
    if isinstance(year_value, int) and not isinstance(year_value, bool):
        year = year_value if 1900 <= year_value <= 2099 else None
    elif isinstance(year_value, str) and re.fullmatch(r"(?:19|20)\d{2}", year_value.strip()):
        year = int(year_value)
    code = value.get("codigo")
    url = f"https://legis.senado.leg.br/norma/{code}" if (
        isinstance(code, int) and not isinstance(code, bool) and code > 0
    ) else None
    if not display and not number and year is None and not url:
        return None, None, conflict
    return {"tipo": display or raw_type or sigla_type, "numero": number,
            "ano": year, "url": url}, group, conflict


def _norm_records(value: Any) -> tuple[list[dict[str, Any]], set[str], bool]:
    values = value if isinstance(value, list) else [value]
    records: list[dict[str, Any]] = []
    groups: set[str] = set()
    conflict = False
    for item in values:
        if isinstance(item, str):
            record, group = _norm_from_text(item)
            if record:
                records.append(record)
            if group:
                groups.add(group)
        elif isinstance(item, dict):
            record, group, type_conflict = _norm_from_object(item)
            conflict = conflict or type_conflict
            if record:
                records.append(record)
            if group:
                groups.add(group)
    return records, groups, conflict


def _merge_norms(row_value: Any, detail_value: Any) -> tuple[list[dict[str, Any]], set[str], bool]:
    batch, batch_groups, batch_conflict = _norm_records(row_value)
    detailed, detail_groups, detail_conflict = _norm_records(detail_value)
    conflict = batch_conflict or detail_conflict
    for batch_norm in batch:
        _, batch_group = _canonical_norm_type(batch_norm.get("tipo"))
        if not batch_group:
            continue
        for detailed_norm in detailed:
            _, detailed_group = _canonical_norm_type(detailed_norm.get("tipo"))
            if detailed_group != batch_group:
                continue
            for field in ("tipo", "numero", "ano"):
                left, right = batch_norm.get(field), detailed_norm.get(field)
                if field == "numero":
                    left, right = _number_key(left), _number_key(right)
                if left is not None and right is not None and left != right:
                    conflict = True
    merged = list(batch)
    for norm in detailed:
        matching = next((
            index for index, candidate in enumerate(merged)
            if _norm_type_key(candidate.get("tipo")) == _norm_type_key(norm.get("tipo"))
            and (_number_key(candidate.get("numero")) == _number_key(norm.get("numero"))
                 or not candidate.get("numero") or not norm.get("numero"))
            and (candidate.get("ano") == norm.get("ano")
                 or candidate.get("ano") is None or norm.get("ano") is None)
        ), None)
        if matching is None:
            merged.append(norm)
        else:
            merged[matching] = {
                key: norm.get(key) if norm.get(key) is not None else merged[matching].get(key)
                for key in ("tipo", "numero", "ano", "url")
            }
    return merged, batch_groups | detail_groups, conflict


def _principal_history(detail: Any) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if not isinstance(detail, dict):
        return None, None, None
    filing_records = detail.get("autuacoes")
    if not isinstance(filing_records, list):
        return None, None, None
    principal = [
        item for item in filing_records
        if isinstance(item, dict) and _fold(item.get("descricao")) == "AUTUACAO PRINCIPAL"
    ]
    if len(principal) != 1:
        if len(principal) > 1:
            return None, None, "Histórico ambíguo: mais de uma autuação principal."
        return None, None, None
    raw_situations = principal[0].get("situacoes")
    if not isinstance(raw_situations, list):
        return None, None, None
    valid: list[tuple[date, date, int, dict[str, Any]]] = []
    all_dates: list[date] = []
    for index, item in enumerate(raw_situations):
        if not isinstance(item, dict):
            continue
        start = _movement_date(item.get("inicio"))
        end_raw = item.get("fim")
        end = _movement_date(end_raw) if end_raw not in (None, "") else None
        if start is None or (end_raw not in (None, "") and end is None) or (end and end < start):
            continue
        all_dates.append(start)
        if end:
            all_dates.append(end)
        valid.append((start, end or start, index, item))
    if not valid:
        if raw_situations:
            return None, None, "Histórico sem datas válidas na autuação principal."
        return None, None, None
    last_key = max((start, end) for start, end, _, _ in valid)
    latest = [entry for entry in valid if (entry[0], entry[1]) == last_key]
    states = {
        (_status_code(item.get("sigla")), _fold(item.get("descricao")))
        for _, _, _, item in latest
    }
    if len(states) > 1:
        return None, max(all_dates).isoformat(), "Histórico ambíguo: estados finais conflitantes."
    selected = latest[-1][3]
    updated = max(all_dates).isoformat()
    return selected, updated, None


def _status_object(
    group: str | None,
    description: str | None,
    consulted_at: Any,
    source_url: Any,
    updated_at: str | None,
    status: str,
    norms: list[dict[str, Any]],
    detail_message: str | None,
) -> dict[str, Any]:
    consulted = _date_value(consulted_at)
    source = _official_url(source_url)
    return {
        "grupo": group,
        "descricao": description,
        "consultadoEm": consulted,
        "sourceUrl": source,
        "atualizadoEm": updated_at,
        "status": status,
        "normas": norms,
        "detail": detail_message,
    }


def normalize_status(
    row: Any,
    consulted_at: Any,
    source_url: Any,
    detail: Any = None,
) -> dict[str, Any]:
    """Normalize one process response, preserving unknown and conflicting cases."""
    if not isinstance(row, dict) or not _project_id(row):
        return _status_object(
            None, None, consulted_at, source_url, None, "unavailable", [],
            "Resposta do Senado sem processo válido.",
        )

    current_description = _text(row.get("situacaoAtual"), 300)
    current_code = row.get("siglaSituacao")
    current_kind = _state_kind(current_code, current_description)
    current_unclassified = _unclassified_final(current_code, current_description)
    active = _in_progress(row.get("tramitando"))
    history_state, history_updated, history_error = _principal_history(detail)
    history_description = _text(history_state.get("descricao"), 300) if history_state else None
    history_code = history_state.get("sigla") if history_state else None
    history_kind = _state_kind(history_code, history_description)
    history_unclassified = _unclassified_final(history_code, history_description)
    detail_norm = detail.get("normaGerada") if isinstance(detail, dict) else None
    norms, norm_groups, norm_conflict = _merge_norms(row.get("normaGerada"), detail_norm)

    updated_at = _date_value(row.get("dataSituacaoAtual")) or history_updated or _date_value(
        row.get("dataUltimaAtualizacao")
    )
    description = current_description or history_description
    notes: list[str] = []
    conflicts: list[str] = []
    if history_error:
        notes.append(history_error)

    # A newer detail response and the batch row must agree on terminal outcomes.
    if current_kind and history_kind and current_kind != history_kind:
        conflicts.append("Situação do lote e histórico principal estão em conflito.")
    if current_kind in {"norma", "arquivado"} and history_state and not history_kind:
        conflicts.append("Situação do lote diverge do último estado da autuação principal.")
    if history_kind in {"norma", "arquivado"} and current_description and not current_kind:
        conflicts.append("Histórico principal diverge da situação informada no lote.")
    if norm_conflict or len(norm_groups) > 1:
        conflicts.append("Tipos de norma gerada conflitantes.")
    if active is True and (current_kind or history_kind):
        conflicts.append("O processo consta como ativo e com situação final.")
    if active is True and (current_unclassified or history_unclassified):
        conflicts.append("A situação de retirada ou prejudicialidade conflita com tramitação ativa.")
    if norm_groups and active is True:
        conflicts.append("A norma gerada conflita com a indicação de tramitação ativa.")
    if norm_groups and (current_kind == "arquivado" or history_kind == "arquivado"):
        conflicts.append("A norma gerada conflita com situação de arquivamento ou rejeição.")
    if norm_groups and (current_unclassified or history_unclassified):
        conflicts.append("A norma gerada conflita com situação de retirada ou prejudicialidade.")

    if conflicts:
        group = None
    elif norm_groups == {"lei"}:
        group = "lei"
    elif norm_groups == {"emenda"}:
        group = "emenda"
    elif current_kind == "arquivado" or history_kind == "arquivado":
        group = "arquivado"
    elif active is True and current_kind is None and history_kind is None:
        group = "tramitando"
    else:
        group = None

    if group == "tramitando" and not description:
        description = "Em tramitação"
    elif group == "lei" and not description:
        description = "Transformada em norma jurídica"
    elif group == "emenda" and not description:
        description = "Emenda Constitucional"
    elif group == "arquivado" and not description:
        description = "Arquivada ou rejeitada"

    if not conflicts and group is None:
        special_state = _fold(current_description or history_description)
        special_code = _status_code(current_code or history_code)
        if special_code == "RTPA" or "RETIRAD" in special_state:
            notes.append("A proposição foi retirada; o coletor não presume arquivamento.")
        elif "PREJUDICAD" in special_state:
            notes.append("A proposição foi prejudicada; o coletor não presume arquivamento.")
        elif current_kind == "norma" or history_kind == "norma":
            notes.append("A situação indica transformação, mas o tipo da norma não foi confirmado.")
        elif active is False:
            notes.append("A tramitação não está ativa, mas o desfecho não foi classificado.")

    description = description or None
    detail_message = " ".join(conflicts + notes) or None
    safe_source_url = _official_url(source_url) or _official_url(row.get("urlDocumento"))
    if not safe_source_url:
        identifier = _project_id(row)
        safe_source_url = f"{API_BASE}/processo/{identifier}" if identifier else None
    return _status_object(
        group, description, consulted_at, safe_source_url, updated_at, "imported", norms,
        detail_message,
    )
