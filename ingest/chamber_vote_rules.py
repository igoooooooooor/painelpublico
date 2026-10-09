"""Conservative rules for auditing Plenary vote records."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


RULE_VERSION = "chamber-vote-inventory-v2"


def _normalized(value: Any) -> str:
    text = value if isinstance(value, str) else ""
    text = unicodedata.normalize("NFD", text.casefold())
    return " ".join(
        "".join(character for character in text if unicodedata.category(character) != "Mn").split()
    )


def _valid_affected_proposition(value: Any) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("siglaTipo"), str):
        return False
    identifier = value.get("id")
    return (
        value["siglaTipo"].strip() != ""
        and isinstance(identifier, (int, str))
        and not isinstance(identifier, bool)
        and str(identifier).strip() != ""
    )


def _has_valid_affected_propositions(record: dict[str, Any]) -> bool:
    values = record.get("proposicoesAfetadas")
    return isinstance(values, list) and any(_valid_affected_proposition(value) for value in values)


def _target_propositions(record: dict[str, Any]) -> list[dict[str, Any]]:
    values = record.get("proposicoesAfetadas")
    if not isinstance(values, list):
        return []
    result = []
    seen_ids = set()
    for value in values:
        if not _valid_affected_proposition(value) or value.get("siglaTipo") not in {"PL", "PLP", "PEC"}:
            continue
        identifier = value.get("id")
        key = str(identifier).strip()
        if key in seen_ids:
            continue
        seen_ids.add(key)
        result.append(value)
    return result


def _method(description: str, opening_description: str) -> str:
    found = set()
    for source in (description, opening_description):
        text = _normalized(source)
        text = _REQUESTED_NOMINAL_RE.sub("", text)
        if re.search(r"\bnominal\b", text):
            found.add("nominal")
        if re.search(r"\bsimbolic[oa]s?\b", text):
            found.add("symbolic")
        if re.search(r"\bsecret[oa]s?\b", text):
            found.add("secret")
    return found.pop() if len(found) == 1 else "unknown"


def _recorded_partial_tally(description: str) -> dict[str, int | None]:
    text = _normalized(description)
    labels = {
        "yes": r"sim",
        "no": r"nao",
        "abstention": r"abstenc(?:ao|oes)",
        "total": r"total",
    }
    tally: dict[str, int | None] = {}
    for key, label in labels.items():
        matches = re.findall(
            rf"\b{label}\s*:\s*(\d{{1,3}}(?:\.\d{{3}})+|\d+)"
            rf"(?=$|[\s;),!?]|\.(?:\s|$))",
            text,
        )
        if len(matches) == 1:
            tally[key] = int(matches[0].replace(".", ""))
        else:
            tally[key] = None
    return tally


def _recorded_tally(description: str) -> dict[str, int | None] | None:
    tally = _recorded_partial_tally(description)
    if tally["yes"] is None or tally["no"] is None:
        return None
    return tally


_OUTCOME_RE = re.compile(r"\b(?:aprovad[oa]s?|rejeitad[oa]s?|aprovou|rejeitou)\b")
_APPROVAL_RE = re.compile(r"\b(?:aprovad[oa]s?|aprovou)\b")
_REJECTION_RE = re.compile(r"\b(?:rejeitad[oa]s?|rejeitou)\b")
_REQUESTED_NOMINAL_RE = re.compile(r"\b(?:pedido|requerimento)\b[^.;]{0,80}\bnominal\b")
_MAIN_RE = re.compile(
    r"\b(?:projeto|plp|pl|pec|mpv|plv|pdl|prc|medida\s+provisoria|substitutiv[oa]s?|"
    r"subemenda\s+substitutiva|emenda\s+constitucional|"
    r"proposta\s+de\s+emenda\s+a\s+constituicao)\b"
)
_TEXT_REFERENCE_RE = _MAIN_RE
_OUT_OF_SCOPE_MAIN_RE = re.compile(
    r"\b(?:projeto\s+de\s+decreto\s+legislativo|projeto\s+de\s+resolucao|"
    r"projeto\s+de\s+lei\s+de\s+conversao|medida\s+provisoria|"
    r"mpv|plv|pdl|prc)\b"
)
_PROCEDURE_RE = re.compile(
    r"\b(?:urgencia|retirad[oa]s?|adiamento|adiad[oa]s?|"
    r"encerramento|encerrad[oa]s?|suspensao|suspens[oa]s?|"
    r"verificacao|admissibilidade|admissivel|inadmissivel)\b|"
    r"\bregime\s+de\s+tramitacao\b|\bapreciacao\s+preliminar\b|"
    r"\bpressupostos\s+constitucionais\b|"
    r"\b(?:pedido|requerimento)\b[^.;]{0,80}\bnominal\b"
)
_AMENDMENT_RE = re.compile(
    r"\b(?:emendas?|subemendas?|destaques?|trechos?|supress(?:ao|oes)|manutenc(?:ao|oes))\b"
)
_AMENDMENT_OUTCOME_RE = re.compile(
    r"\b(?:aprovad[oa]s?|rejeitad[oa]s?|aprovou|rejeitou)\b.{0,60}"
    r"\b(?:emendas?|subemendas?|destaques?|trechos?|supress(?:ao|oes)|manutenc(?:ao|oes))\b|"
    r"\b(?:emendas?|subemendas?|destaques?|trechos?|supress(?:ao|oes)|manutenc(?:ao|oes))\b.{0,60}"
    r"\b(?:aprovad[oa]s?|rejeitad[oa]s?|aprovou|rejeitou)\b"
)


def _category(description: str) -> str:
    text = _normalized(description)
    if re.search(r"\bredacao\s+final\b", text):
        return "final_wording"
    if (_PROCEDURE_RE.search(text)
            or re.match(r"^(?:aprovad[oa]|rejeitad[oa])\s+(?:o|a)\s+(?:requerimento|recurso)\b", text)):
        return "procedure"

    # A recorded exception about previously rejected devices is not a second
    # outcome of the main Senate substitute (PL 3780/2023, 18/03/2026).
    text = re.sub(r"\bcom excecao dos dispositivos rejeitados\b", "", text)

    # “Ressalvados os destaques” is a caveat attached to the main vote, not a
    # record of voting on a highlight itself.
    amendment_text = re.sub(r"\bressalvad[oa]s?\s+(?:o|a)s?\s+destaques?\b", "", text)
    amendment_text = re.sub(r"\bsubemenda\s+substitutiva\b|\bemenda\s+constitucional\b", "", amendment_text)
    has_amendment = bool(_AMENDMENT_RE.search(amendment_text))
    has_main = bool(_MAIN_RE.search(text))
    has_outcome = bool(_OUTCOME_RE.search(text))
    has_both_outcomes = bool(_APPROVAL_RE.search(text) and _REJECTION_RE.search(text))

    if has_both_outcomes:
        return "unknown"
    if has_amendment and has_outcome and _AMENDMENT_OUTCOME_RE.search(amendment_text):
        return "amendment"
    if has_main and has_amendment:
        return "unknown"
    if has_amendment and has_outcome:
        return "amendment"
    if has_main and has_outcome:
        return "main_text"
    return "unknown"


def _opening_category(description: str, opening_description: str) -> str:
    """Resolve only generic dispositions with an explicitly named separate object."""
    text, opening = _normalized(description), _normalized(opening_description)
    if (re.match(r"^(?:(?:aprovada|rejeitada) a )?preferencia(?:\.|$)", text)
            and re.match(r"^votacao d[oa]s? (?:dtq|destaque)\b", opening)
            and "destaque de preferencia" in opening):
        return "procedure"
    if (re.match(r"^(?:(?:mantido|suprimido) o texto|resultado)(?:\.|$)", text)
            and re.match(r"^votacao d[oa]s? (?:dtq|destaque)\b", opening)):
        return "amendment"
    # The real result of PL 2736/2019 misspells “Subemenda” as “Submenda”.
    # The opening names an amendment to the substitute, not a global substitute.
    if (re.match(r"^aprovada a submenda\b", text)
            and re.match(r"^votacao da subemenda\b", opening)
            and " ao substitutivo " in f"{opening} "
            and not re.search(r"\bsubemenda substitutiva\b", opening)):
        return "amendment"
    return "unknown"


def classify_vote(record: dict[str, Any]) -> dict[str, Any]:
    """Classify a single official Chamber vote row for provisional auditing."""
    if not isinstance(record, dict):
        record = {}
    description = record.get("descricao") if isinstance(record.get("descricao"), str) else ""
    opening_description = (
        record.get("descUltimaAberturaVotacao")
        if isinstance(record.get("descUltimaAberturaVotacao"), str)
        else ""
    )
    normalized_description = _normalized(description)
    combined_text = _normalized(f"{description} {opening_description}")
    targets = _target_propositions(record)
    has_valid_affected_propositions = _has_valid_affected_propositions(record)
    category = _category(description)
    if category == "unknown":
        category = _opening_category(description, opening_description)
    method = _method(description, opening_description)
    tally = _recorded_tally(description)
    candidate = False

    if category == "main_text":
        if record.get("siglaOrgao") != "PLEN":
            reason = "Descrição indica texto principal, mas o registro não é do Plenário (PLEN)."
        elif re.search(r"\b(?:secret[oa]s?|simbolic[oa]s?)\b", combined_text):
            reason = "Descrição indica texto principal, mas a votação foi secreta ou simbólica."
        elif _OUT_OF_SCOPE_MAIN_RE.search(normalized_description):
            reason = "Descrição identifica matéria fora do escopo proposto para a versão v1."
        elif has_valid_affected_propositions and not targets:
            reason = "Proposição afetada está fora do escopo proposto para a versão v1."
        elif not targets and not _TEXT_REFERENCE_RE.search(normalized_description):
            reason = "Descrição indica texto principal, mas não identifica projeto elegível para a auditoria."
        else:
            candidate = True
            reason = "Descrição identifica votação do texto principal; classificação provisória para auditoria."
            if method == "unknown":
                reason += " O método não está explícito no texto oficial."
    elif category == "amendment":
        reason = "Descrição identifica votação de emenda, destaque ou trecho, fora do texto principal."
    elif category == "procedure":
        reason = "Descrição identifica votação ou ato procedimental, fora do texto principal."
    elif category == "final_wording":
        reason = "Descrição identifica votação de redação final, registrada separadamente do texto principal."
    else:
        reason = "Descrição não identifica com clareza uma votação elegível do texto principal."

    return {
        "category": category,
        "candidate": candidate,
        "reason": reason,
        "method": method,
        "recordedTally": tally,
        "targetPropositions": targets,
    }
