"""Conservatively normalize the Câmara's latest status for one proposition.

The annual Câmara archive is the efficient source for a large set of IDs. Its
``ultimoStatus`` objects use slightly different field names from the individual
API detail endpoint's ``statusProposicao`` object; both shapes are accepted here.
This module does no network access and does not infer status from related
propositions, ementas, or unanchored free-text dispatches.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from urllib.parse import urlsplit
from typing import Any


CHAMBER_API = "https://dadosabertos.camara.leg.br/api/v2"
CHAMBER_PROFILE = "https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={}"

# These are the active labels observed in the official 2023–2026 annual
# archives for IDs in the local profile snapshot. Unknown or newly introduced
# labels remain unclassified until an explicit mapping is reviewed.
IN_PROGRESS_LABELS = frozenset({
    "aguardando apreciacao pelo senado federal",
    "aguardando apreciacao do veto",
    "aguardando autorizacao do despacho",
    "aguardando apensacao",
    "aguardando autografos na mesa",
    "aguardando constituicao de comissao temporaria",
    "aguardando criacao de comissao temporaria",
    "aguardando deliberacao",
    "aguardando deliberacao de recurso",
    "aguardando definicao encaminhamento",
    "aguardando designacao - aguardando devolucao de relator(a) que deixou de ser membro",
    "aguardando designacao de relator(a)",
    "aguardando despacho do presidente",
    "aguardando despacho do presidente da camara dos deputados",
    "aguardando despacho do presidente da camara dos deputados (analise)",
    "aguardando despacho do presidente da camara dos deputados (autorizacao)",
    "aguardando despacho do presidente da camara dos deputados (chancela)",
    "aguardando encaminhamento",
    "aguardando envio ao senado federal",
    "aguardando parecer",
    "aguardando redacao final",
    "aguardando recurso",
    "aguardando sancao",
    "aguardando vistas",
    "ag. analise de inconstitucionalidade",
    "pronta para pauta",
    "tramitando em conjunto",
})

ARQUIVADO_LABELS = frozenset({"arquivada", "arquivado", "rejeitada", "rejeitado"})
PROJECT_TYPES = frozenset({"pl", "plp", "pec"})

_DIRECT_TRANSFORMATION = re.compile(r"^transformad[oa]\s+(?:em|na|no)\s+(.+)$")
_URN_FINAL = re.compile(
    r"^urn:lex:br:federal:(lei(?:\.[a-z]+)?|emenda\.constitucional):"
    r"(\d{4})-(\d{2})-(\d{2});([\d.]+)(?:;.*)?$",
    re.IGNORECASE,
)
_NORM_REFERENCE = re.compile(
    r"\b(lei(?:\s+(?:ordinaria|complementar|delegada))?|emenda\s+constitucional)"
    r"\s*(?:n(?:[ºo°.]|umero)?\s*)?([\d.]+)\s*/\s*(\d{4})\b",
    re.IGNORECASE,
)
_OWN_EC_DISPATCH = re.compile(
    r"^transformad[oa]\s+na\s+emenda\s+constitucional\s+(\d+(?:\.\d+)*)/(\d{4})\.",
    re.IGNORECASE,
)


def _text(value: Any, limit: int = 12000) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] or None


def _key(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def _official_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or not host
        or parts.username
        or parts.password
        or not (host == "camara.leg.br" or host.endswith(".camara.leg.br"))
    ):
        return None
    return value


def _normalize_norm_type(value: str) -> str:
    normalized = _key(value).replace(" ", ".")
    if normalized == "emenda.constitucional":
        return "Emenda Constitucional"
    if normalized == "lei.complementar":
        return "Lei Complementar"
    if normalized == "lei.delegada":
        return "Lei Delegada"
    return "Lei"


def _norms_from_urn(value: Any) -> list[dict[str, Any]]:
    urn = _text(value, 500)
    match = _URN_FINAL.fullmatch(urn or "")
    if not match:
        return []
    kind, year, month, day, number = match.groups()
    if not number.replace(".", "").isdigit():
        return []
    try:
        date(int(year), int(month), int(day))
    except ValueError:
        return []
    return [{
        "tipo": _normalize_norm_type(kind),
        "numero": number.replace(".", ""),
        "ano": int(year),
        # Keep the official URN as the direct identifier when no HTTP URL is
        # published for the final norm.
        "url": urn,
    }]


def _norms_from_status(status_texts: list[str], urn_norms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found = list(urn_norms)
    for original in status_texts:
        normalized = _key(original)
        if not _DIRECT_TRANSFORMATION.match(normalized):
            continue
        for match in _NORM_REFERENCE.finditer(normalized):
            kind, number, year = match.groups()
            item = {
                "tipo": _normalize_norm_type(kind),
                "numero": number.replace(".", ""),
                "ano": int(year),
                "url": None,
            }
            if item not in found:
                found.append(item)
    unique: dict[tuple[str, str, int], dict[str, Any]] = {}
    for item in found:
        key = (item["tipo"], item["numero"], item["ano"])
        previous = unique.get(key)
        if previous is None or (previous.get("url") is None and item.get("url") is not None):
            unique[key] = item
    return list(unique.values())


def _directly_transformed(status_texts: list[str]) -> list[str]:
    return [text for text in status_texts if _DIRECT_TRANSFORMATION.match(_key(text))]


def needs_detail(row: Any) -> bool:
    """Whether a transformation needs the individual endpoint for norm evidence.

    Only own, explicit transformations that are legal-norm candidates are
    selected. Ordinary rows with an empty situation and transformations into a
    new proposition do not trigger detail fetches.
    """
    data = row.get("dados") if isinstance(row, dict) and isinstance(row.get("dados"), dict) else row
    if not isinstance(data, dict):
        return False
    latest = data.get("ultimoStatus")
    if not isinstance(latest, dict):
        latest = data.get("statusProposicao")
    if not isinstance(latest, dict):
        return False

    status_texts = [
        value for value in (
            _text(latest.get("descricaoSituacao"), 500),
            _text(latest.get("descricaoTramitacao"), 1000),
        ) if value
    ]
    direct_texts = _directly_transformed(status_texts)
    if not direct_texts:
        return False

    if _key(_text(latest.get("descricaoSituacao"), 500)) in ARQUIVADO_LABELS:
        return False

    proposition_type = _key(_text(data.get("siglaTipo"), 40))
    if proposition_type not in {"pl", "plp", "pec"}:
        return False

    urn_norms = _norms_from_urn(data.get("urnFinal"))
    norms = _norms_from_status(status_texts, urn_norms)
    dispatch_ec_norm = _own_ec_norm_from_dispatch(
        latest,
        proposition_type,
        _text(latest.get("descricaoSituacao"), 500),
        urn_norms,
    )
    if dispatch_ec_norm and not any(
        norm["tipo"] == dispatch_ec_norm["tipo"]
        and norm["numero"] == dispatch_ec_norm["numero"]
        and norm["ano"] == dispatch_ec_norm["ano"]
        for norm in norms
    ):
        norms.append(dispatch_ec_norm)
    if proposition_type in {"pl", "plp"}:
        if any(norm["tipo"] == "Emenda Constitucional" for norm in urn_norms):
            return False
        return _has_law_transformation(direct_texts) and not any(
            _key(norm["tipo"]).startswith("lei") for norm in norms
        )

    # PECs transformed into a generic "norma jurídica" require a detail/URN
    # to distinguish a constitutional amendment from another norm type.
    if any(_key(norm["tipo"]).startswith("lei") for norm in urn_norms):
        return False
    return (
        (_has_law_transformation(direct_texts) or _has_ec_transformation(direct_texts))
        and not any(norm["tipo"] == "Emenda Constitucional" for norm in norms)
    )


def _has_law_transformation(texts: list[str]) -> bool:
    for text in texts:
        match = _DIRECT_TRANSFORMATION.match(_key(text))
        if not match:
            continue
        tail = match.group(1)
        if re.search(r"\bnorma(?:\s+juridica)?\b|\blei(?:\s|$)", tail):
            return True
    return False


def _has_ec_transformation(texts: list[str]) -> bool:
    return any(
        _DIRECT_TRANSFORMATION.match(_key(text))
        and re.search(r"\bemenda\s+constitucional\b", _key(text))
        for text in texts
    )


def _own_ec_norm_from_dispatch(
    latest: dict[str, Any],
    proposition_type: str,
    situation: str | None,
    urn_norms: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Read only a directly attributed EC dispatch after an own norm status."""
    if proposition_type != "pec":
        return None

    normalized_situation = _key(situation)
    own_norm_situation = normalized_situation in {
        "transformado em norma juridica",
        "transformada em norma juridica",
    } or _has_ec_transformation([situation] if situation else [])
    if not own_norm_situation or normalized_situation in ARQUIVADO_LABELS:
        return None

    dispatch = _key(_text(latest.get("despacho"), 12000))
    match = _OWN_EC_DISPATCH.match(dispatch)
    if not match:
        return None
    number, year = match.groups()
    numeric_year = int(year)
    if not 1 <= numeric_year <= 9999:
        return None
    normalized_number = number.replace(".", "")
    # A final URN that disagrees on type, number, or year conflicts with the
    # dispatch; retain the URN as evidence without adding the dispatch claim.
    if any(
        norm["tipo"] != "Emenda Constitucional"
        or norm["numero"] != normalized_number
        or norm["ano"] != numeric_year
        for norm in urn_norms
    ):
        return None
    return {
        "tipo": "Emenda Constitucional",
        "numero": normalized_number,
        "ano": numeric_year,
        "url": None,
    }


def _status_result(
    *,
    group: str | None,
    description: str | None,
    consulted_at: Any,
    source_url: str | None,
    updated_at: str | None,
    status: str,
    norms: list[dict[str, Any]],
    detail: str | None,
    situation_code: Any,
) -> dict[str, Any]:
    return {
        "grupo": group,
        "descricao": description,
        "consultadoEm": _text(consulted_at, 80),
        "sourceUrl": source_url,
        "atualizadoEm": updated_at,
        "status": status,
        "normas": norms,
        "detail": detail,
        "codSituacao": _text(str(situation_code), 40) if situation_code is not None else None,
    }


def normalize_status(row: Any, consulted_at: Any, source_url: Any) -> dict[str, Any]:
    """Return a small, auditable status object for an annual row or API detail.

    ``status='imported'`` means a valid proposition row was read. A missing,
    blank, or unrecognized situation keeps ``grupo`` as ``None``. Only explicit
    own-proposition transformations, exact archived/rejected labels, and an
    allowlist of observed active labels receive a group.
    """
    data = row.get("dados") if isinstance(row, dict) and isinstance(row.get("dados"), dict) else row
    if not isinstance(data, dict):
        data = {}
    identifier = _text(str(data.get("id") or ""), 60)
    if not identifier or not identifier.isdigit() or int(identifier) < 1:
        return _status_result(
            group=None,
            description=None,
            consulted_at=consulted_at,
            source_url=_official_url(source_url),
            updated_at=None,
            status="unavailable",
            norms=[],
            detail="Resposta sem identificador válido de proposição.",
            situation_code=None,
        )

    latest = data.get("ultimoStatus")
    if not isinstance(latest, dict):
        latest = data.get("statusProposicao")
    if not isinstance(latest, dict):
        latest = {}

    description = _text(latest.get("descricaoSituacao"), 500)
    movement_description = _text(latest.get("descricaoTramitacao"), 1000)
    dispatch = _text(latest.get("despacho"), 12000)
    status_texts = [value for value in (description, movement_description) if value]
    direct_texts = _directly_transformed(status_texts)
    urn_norms = _norms_from_urn(data.get("urnFinal"))
    norms = _norms_from_status(status_texts, urn_norms)
    proposition_type = _key(_text(data.get("siglaTipo"), 40))
    normalized_description = _key(description)
    dispatch_ec_norm = _own_ec_norm_from_dispatch(
        latest, proposition_type, description, urn_norms
    )
    if dispatch_ec_norm and not any(
        norm["tipo"] == dispatch_ec_norm["tipo"]
        and norm["numero"] == dispatch_ec_norm["numero"]
        and norm["ano"] == dispatch_ec_norm["ano"]
        for norm in norms
    ):
        norms.append(dispatch_ec_norm)
    group = None

    # A valid final legal URN is direct evidence tied to this proposition ID.
    has_law_urn = any(_key(norm["tipo"]).startswith("lei") for norm in urn_norms)
    has_ec_urn = any(norm["tipo"] == "Emenda Constitucional" for norm in urn_norms)
    conflicting_urn = (
        proposition_type in {"pl", "plp"} and has_ec_urn
    ) or (proposition_type == "pec" and has_law_urn)
    if proposition_type in PROJECT_TYPES and normalized_description in ARQUIVADO_LABELS:
        group = "arquivado"
    elif not conflicting_urn and proposition_type in {"pl", "plp"} and (
        has_law_urn or _has_law_transformation(direct_texts)
    ):
        group = "lei"
    elif not conflicting_urn and proposition_type == "pec" and (
        has_ec_urn or _has_ec_transformation(direct_texts) or dispatch_ec_norm
    ):
        group = "emenda"
    elif proposition_type in PROJECT_TYPES and normalized_description in IN_PROGRESS_LABELS:
        group = "tramitando"

    status_code = latest.get("idSituacao")
    if status_code is None:
        status_code = latest.get("codSituacao")
    updated_at = _text(latest.get("data") or latest.get("dataHora"), 80)

    details = []
    if movement_description:
        details.append(f"Tramitação: {movement_description}.")
    if dispatch:
        details.append(dispatch)
    detail = " ".join(details) or None

    individual_url = _official_url(data.get("uri"))
    if not individual_url and identifier:
        individual_url = f"{CHAMBER_API}/proposicoes/{identifier}"
    resolved_source_url = individual_url or _official_url(source_url) or _official_url(latest.get("url"))

    return _status_result(
        group=group,
        description=description,
        consulted_at=consulted_at,
        source_url=resolved_source_url,
        updated_at=updated_at,
        status="imported",
        norms=norms,
        detail=detail,
        situation_code=status_code,
    )
