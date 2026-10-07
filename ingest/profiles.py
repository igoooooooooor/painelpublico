"""Build a local, whitelisted profile snapshot for current federal legislators.

The default run is offline. ``--collect`` refreshes Câmara contact/projects and
the Câmara office collector; no response body from the deputy detail endpoint is
written to disk because that response also contains personal data outside this
snapshot's public-profile contract.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
IMPORT_PATH = ROOT / "data" / "imports" / "legislative.json"
RAW_LEGISLATIVE = ROOT / "data" / "raw" / "legislative"
RAW_EDITORIAL_EXTRA = ROOT / "data" / "raw" / "editorial-extra"
RAW_PROFILES = ROOT / "data" / "raw" / "profiles"
DEFAULT_OUTPUT = ROOT / "data" / "snapshots" / "perfis.json"
SENATE_XML = RAW_LEGISLATIVE / "senadores-atual.xml"

CHAMBER_API = "https://dadosabertos.camara.leg.br/api/v2"
CHAMBER_LIST_URL = f"{CHAMBER_API}/deputados?itens=100&pagina=1"
CHAMBER_PROJECTS_PERIOD = "PL, PLP e PEC apresentados desde 2023-02-01"
CHAMBER_PROJECTS_PARAMS = {
    "siglaTipo": "PL,PLP,PEC",
    "dataApresentacaoInicio": "2023-02-01",
    "itens": 100,
    "ordem": "DESC",
    "ordenarPor": "id",
}
SENATE_ROSTER_URL = "https://legis.senado.leg.br/dadosabertos/senador/lista/atual"
SENATE_PROFILE_PAGE = "https://www25.senado.leg.br/web/senadores/senador/-/perfil/{}"
USER_AGENT = "QuantoCusta/1.0 (public-profile collector)"
HTTP_TIMEOUT = 20
HTTP_RETRIES = 1
MAX_WORKERS = 4
ID_PATTERN = re.compile(r"^(camara|senado):(\d+)$")
ALLOWED_ROLES = {
    "camara_deputies_current": "deputado",
    "senado_senators_current": "senador",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text(value: Any, limit: int = 12000) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] or None


def _official_url(value: Any, suffixes: tuple[str, ...] = ("camara.leg.br", "senado.leg.br")) -> str | None:
    if not isinstance(value, str):
        return None
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or not host
        or parts.username
        or parts.password
        or not any(host == suffix or host.endswith("." + suffix) for suffix in suffixes)
    ):
        return None
    return value


def _json_from_path(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in payload.get("sources", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _current_roster(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for authority in payload.get("authorities", []):
        if not isinstance(authority, dict):
            continue
        source_id = authority.get("sourceId")
        role = ALLOWED_ROLES.get(source_id)
        match = ID_PATTERN.fullmatch(str(authority.get("id") or ""))
        if not role or not match or match.group(1) != ("camara" if role == "deputado" else "senado"):
            continue
        if not _text(authority.get("name")):
            continue
        rows.append(authority)
    return sorted(rows, key=_authority_sort_key)


def _authority_sort_key(authority: dict[str, Any]) -> tuple[Any, ...]:
    match = ID_PATTERN.fullmatch(str(authority.get("id") or ""))
    return (0 if authority.get("role") == "deputado" else 1, int(match.group(2)) if match else 0)


def _chamber(authority_id: str) -> tuple[str, str]:
    match = ID_PATTERN.fullmatch(authority_id)
    if not match:
        raise ValueError("ID parlamentar inválido")
    return match.group(1), match.group(2)


def _profile_page(authority: dict[str, Any]) -> str:
    chamber, identifier = _chamber(str(authority["id"]))
    if chamber == "camara":
        return f"https://www.camara.leg.br/deputados/{identifier}?ano=2026"
    return SENATE_PROFILE_PAGE.format(identifier)


def _chamber_cache_roster(root: Path = ROOT) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Read only public identity fields from the cached Câmara roster pages."""
    cache: dict[str, dict[str, Any]] = {}
    stamp = None
    raw_legislative = root / "data" / "raw" / "legislative"
    raw_editorial_extra = root / "data" / "raw" / "editorial-extra"
    paths = sorted(raw_legislative.glob("camara-deputies-page-*.json"))
    if not paths and (raw_editorial_extra / "deps.json").exists():
        paths = [raw_editorial_extra / "deps.json"]
    for path in paths:
        try:
            payload = _json_from_path(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("dados"), list):
            continue
        stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()
        for row in payload["dados"]:
            if not isinstance(row, dict) or not str(row.get("id", "")).isdigit():
                continue
            identifier = str(row["id"])
            cache[identifier] = {
                "email": _text(row.get("email"), 254),
                "photo": _official_url(row.get("urlFoto")),
                "profileUrl": _official_url(row.get("uri")),
            }
    # The older roster cache can fill only fields missing from the current API pages.
    older = raw_editorial_extra / "deps.json"
    if older.exists():
        try:
            payload = _json_from_path(older)
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("dados"), list):
            older_stamp = datetime.fromtimestamp(older.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()
            if stamp is None:
                stamp = older_stamp
            for row in payload["dados"]:
                if not isinstance(row, dict) or not str(row.get("id", "")).isdigit():
                    continue
                identifier = str(row["id"])
                current = cache.setdefault(identifier, {"email": None, "photo": None, "profileUrl": None})
                current["email"] = current["email"] or _text(row.get("email"), 254)
                current["photo"] = current["photo"] or _official_url(row.get("urlFoto"))
                current["profileUrl"] = current["profileUrl"] or _official_url(row.get("uri"))
    return cache, stamp


def _senate_xml_profiles(
    sources: dict[str, dict[str, Any]], xml_path: Path = SENATE_XML
) -> dict[str, dict[str, Any]]:
    """Extract public profile/contact fields from the current official XML only."""
    if not xml_path.exists():
        return {}
    from ingest.legislative import senate_xml_authorities

    content = xml_path.read_bytes()
    authorities, _ = senate_xml_authorities(content, "senado_senators_current", SENATE_ROSTER_URL)
    root = ET.fromstring(content)
    items = root.findall("./Parlamentares/Parlamentar")
    by_id = {row["id"]: row for row in authorities}
    source_fetched = sources.get("senado_senators_current", {}).get("fetchedAt")
    stamp = source_fetched or datetime.fromtimestamp(xml_path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()
    out = {}
    for item in items:
        ident = item.find("IdentificacaoParlamentar")
        if ident is None:
            continue
        code = _text(ident.findtext("CodigoParlamentar"))
        if not code:
            continue
        authority_id = f"senado:{code}"
        authority = by_id.get(authority_id)
        if not authority:
            continue
        email = _text(ident.findtext("EmailParlamentar"), 254)
        phones = []
        for node in item.iter():
            if node.tag == "NumeroTelefone":
                phone = _text(node.text, 80)
                if phone and phone not in phones:
                    phones.append(phone)
        participation = _text(item.findtext("Mandato/DescricaoParticipacao"))
        exercise = _text(authority.get("employmentStatus"))
        contact = {
            "email": email,
            "telefones": phones,
            "endereco": None,
            "redes": [],
            "sourceUrl": SENATE_ROSTER_URL,
            "fetchedAt": stamp,
            "status": "imported" if email or phones else "partial",
        }
        if not email or not phones:
            contact["detail"] = "O XML oficial não informa todos os campos de contato para este registro."
        mandate = {
            "participacao": participation,
            "exercicio": exercise,
            "sourceUrl": SENATE_ROSTER_URL,
            "fetchedAt": stamp,
        }
        photo = _official_url(ident.findtext("UrlFotoParlamentar"))
        page_url = _official_url(ident.findtext("UrlPaginaParlamentar"))
        out[authority_id] = {
            "contact": contact,
            "mandato": mandate,
            "photo": photo,
            "sourceUrl": page_url or authority.get("sourceUrl") or SENATE_ROSTER_URL,
        }
    return out


def _empty_contact(source_url: str | None = None, fetched_at: str | None = None) -> dict[str, Any]:
    return {
        "email": None,
        "telefones": [],
        "endereco": None,
        "redes": [],
        "sourceUrl": source_url,
        "fetchedAt": fetched_at,
        "status": "unavailable",
    }


def _empty_mandate(source_url: str | None = None, fetched_at: str | None = None) -> dict[str, Any]:
    return {
        "participacao": None,
        "exercicio": None,
        "sourceUrl": source_url,
        "fetchedAt": fetched_at,
    }


def _empty_projects(source_url: str | None, period: str | None = CHAMBER_PROJECTS_PERIOD) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "period": period,
        "sourceUrl": source_url,
        "fetchedAt": None,
        "total": None,
        "items": [],
    }


def _cache_path(authority_id: str, raw_root: Path = RAW_PROFILES) -> Path:
    chamber, identifier = _chamber(authority_id)
    return raw_root / f"{chamber}-{identifier}.json"


def _clean_contact(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    numbers = value.get("telefones")
    networks = value.get("redes")
    clean_networks = []
    if isinstance(networks, list):
        for item in networks:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("nome"), 60)
            url = _official_url(item.get("url"), ("camara.leg.br", "senado.leg.br", "x.com", "twitter.com", "instagram.com", "facebook.com", "youtube.com", "tiktok.com"))
            if name and url:
                clean_networks.append({"nome": name, "url": url})
    result = {
        "email": _text(value.get("email"), 254),
        "telefones": [_text(item, 80) for item in numbers if _text(item, 80)] if isinstance(numbers, list) else [],
        "endereco": _text(value.get("endereco"), 500),
        "redes": clean_networks,
        "sourceUrl": _official_url(value.get("sourceUrl")),
        "fetchedAt": _text(value.get("fetchedAt"), 40),
        "status": value.get("status") if value.get("status") in ("imported", "partial", "unavailable") else "unavailable",
    }
    for key in ("detail",):
        detail = _text(value.get(key), 300)
        if detail:
            result[key] = detail
    if value.get("stale") is True:
        result["stale"] = True
    return result


def _clean_mandate(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result = {
        "participacao": _text(value.get("participacao")),
        "exercicio": _text(value.get("exercicio")),
        "sourceUrl": _official_url(value.get("sourceUrl")),
        "fetchedAt": _text(value.get("fetchedAt"), 40),
    }
    detail = _text(value.get("detail"), 300)
    if detail:
        result["detail"] = detail
    if value.get("stale") is True:
        result["stale"] = True
    return result


def _clean_projects(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    items = []
    raw_items = value.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            identifier = _text(str(item.get("id") or ""), 60)
            if not identifier:
                continue
            items.append({
                "id": identifier,
                "titulo": _text(item.get("titulo"), 300),
                "ementa": _text(item.get("ementa"), 12000),
                "situacao": _text(item.get("situacao"), 300),
                "url": _official_url(item.get("url")),
            })
    total = value.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        total = None
    result = {
        "status": value.get("status") if value.get("status") in ("imported", "partial", "unavailable") else "unavailable",
        "period": _text(value.get("period"), 200) or CHAMBER_PROJECTS_PERIOD,
        "sourceUrl": _official_url(value.get("sourceUrl")),
        "fetchedAt": _text(value.get("fetchedAt"), 40),
        "total": total,
        "items": items,
    }
    detail = _text(value.get("detail"), 300)
    if detail:
        result["detail"] = detail
    if value.get("stale") is True:
        result["stale"] = True
    return result


def _read_profile_cache(authority_id: str, raw_root: Path = RAW_PROFILES) -> dict[str, Any]:
    path = _cache_path(authority_id, raw_root)
    try:
        payload = _json_from_path(path)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("id") != authority_id:
        return {}
    return {
        "contact": _clean_contact(payload.get("contact")),
        "mandato": _clean_mandate(payload.get("mandato")),
        "projetos": _clean_projects(payload.get("projetos")),
        "photo": _official_url(payload.get("photo")),
    }


def _write_profile_cache(authority_id: str, sections: dict[str, Any], raw_root: Path = RAW_PROFILES) -> None:
    path = _cache_path(authority_id, raw_root)
    payload = {
        "id": authority_id,
        "contact": _clean_contact(sections.get("contact")),
        "mandato": _clean_mandate(sections.get("mandato")),
        "projetos": _clean_projects(sections.get("projetos")),
        "photo": _official_url(sections.get("photo")),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(path, payload)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            file_name = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(file_name, path)
    finally:
        if file_name and os.path.exists(file_name):
            os.unlink(file_name)


def _request_json(url: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=HTTP_TIMEOUT) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ValueError("Resposta da Câmara sem objeto JSON")
            return payload
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < HTTP_RETRIES:
                time.sleep(0.25)
    raise RuntimeError(f"Falha de consulta oficial: {type(last_error).__name__ if last_error else 'erro'}")


def _api_next_url(current_url: str, links: Any) -> str | None:
    if not isinstance(links, list):
        return None
    href = next((link.get("href") for link in links if isinstance(link, dict) and link.get("rel") == "next"), None)
    if not href:
        return None
    result = urljoin(current_url, str(href))
    parts = urlsplit(result)
    if parts.scheme != "https" or parts.hostname != "dadosabertos.camara.leg.br":
        raise ValueError("Link de paginação fora do domínio oficial da Câmara")
    return result


def _project_list_url(authority_id: str) -> str:
    _, identifier = _chamber(authority_id)
    return f"{CHAMBER_API}/proposicoes?" + urlencode({"idDeputadoAutor": identifier, **CHAMBER_PROJECTS_PARAMS})


def fetch_chamber_projects(authority_id: str, request_json=_request_json) -> dict[str, Any]:
    """Read summary rows from all pages; never call a detail endpoint per project."""
    first_url = _project_list_url(authority_id)
    current_url = first_url
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    ids: set[str] = set()
    page = 0
    failure = None
    while current_url:
        if current_url in seen:
            failure = "A paginação repetiu uma página; total não confirmado."
            break
        seen.add(current_url)
        page += 1
        try:
            payload = request_json(current_url)
            rows = payload.get("dados")
            if not isinstance(rows, list):
                raise ValueError("Resposta sem lista de proposições")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                identifier = _text(str(row.get("id") or ""), 60)
                if not identifier or identifier in ids:
                    continue
                ids.add(identifier)
                kind = _text(str(row.get("siglaTipo") or ""), 40)
                number = _text(str(row.get("numero") or ""), 40)
                year = _text(str(row.get("ano") or ""), 40)
                title = f"{kind} {number}/{year}" if kind and number and year else None
                items.append({
                    "id": identifier,
                    "titulo": title,
                    "ementa": _text(row.get("ementa")),
                    "situacao": None,
                    "url": f"https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={identifier}"
                    if identifier.isdigit() else None,
                })
            current_url = _api_next_url(current_url, payload.get("links"))
        except Exception as error:
            failure = f"Falha na página {page} de proposições ({type(error).__name__}); resultado incompleto."
            break
    if failure:
        return {
            "status": "partial" if items else "unavailable",
            "period": CHAMBER_PROJECTS_PERIOD,
            "sourceUrl": first_url,
            "fetchedAt": utc_now(),
            "total": None,
            "items": items,
            "detail": failure,
        }
    return {
        "status": "imported",
        "period": CHAMBER_PROJECTS_PERIOD,
        "sourceUrl": first_url,
        "fetchedAt": utc_now(),
        "total": len(items),
        "items": items,
    }


def parse_chamber_detail(payload: dict[str, Any], authority_id: str, fetched_at: str | None = None) -> dict[str, Any]:
    """Whitelist contact/status fields from the Câmara detail response."""
    data = payload.get("dados") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("Resposta da Câmara sem dados do parlamentar")
    _, identifier = _chamber(authority_id)
    url = f"{CHAMBER_API}/deputados/{identifier}"
    status = data.get("ultimoStatus") if isinstance(data.get("ultimoStatus"), dict) else {}
    office = status.get("gabinete") if isinstance(status.get("gabinete"), dict) else {}
    email = _text(office.get("email"), 254) or _text(data.get("email"), 254)
    phone = _text(office.get("telefone"), 80)
    phones = [phone] if phone else []
    address_parts = []
    if _text(office.get("predio"), 60):
        address_parts.append(f"Anexo {_text(office.get('predio'), 60)}")
    if _text(office.get("andar"), 60):
        address_parts.append(f"Andar {_text(office.get('andar'), 60)}")
    if _text(office.get("sala"), 60):
        address_parts.append(f"Gabinete {_text(office.get('sala'), 60)}")
    social = data.get("redeSocial") if isinstance(data.get("redeSocial"), list) else []
    networks = []
    for raw in social:
        candidate = _official_url(raw, ("camara.leg.br", "x.com", "twitter.com", "instagram.com", "facebook.com", "youtube.com", "tiktok.com"))
        if not candidate or any(row["url"] == candidate for row in networks):
            continue
        host = (urlsplit(candidate).hostname or "").lower()
        name = next((label for domain, label in (
            ("x.com", "X"), ("twitter.com", "X"), ("instagram.com", "Instagram"),
            ("facebook.com", "Facebook"), ("youtube.com", "YouTube"), ("tiktok.com", "TikTok"),
        ) if host == domain or host.endswith("." + domain)), "Site")
        networks.append({"nome": name, "url": candidate})
    fetched = fetched_at or utc_now()
    contact = {
        "email": email,
        "telefones": phones,
        "endereco": ", ".join(address_parts) or None,
        "redes": networks,
        "sourceUrl": url,
        "fetchedAt": fetched,
        "status": "imported" if email or phones or address_parts or networks else "partial",
    }
    if not email or not phones or not address_parts:
        contact["detail"] = "Campos de contato ausentes foram mantidos sem valor."
    mandate = {
        "participacao": _text(status.get("condicaoEleitoral")),
        "exercicio": _text(status.get("situacao")),
        "sourceUrl": url,
        "fetchedAt": fetched,
    }
    photo = _official_url(status.get("urlFoto") or data.get("urlFoto"), ("camara.leg.br",))
    return {"contact": contact, "mandato": mandate, "photo": photo}


def _failure_section(previous: dict[str, Any] | None, fallback: dict[str, Any], detail: str, section: str) -> dict[str, Any]:
    existing = deepcopy(previous) if isinstance(previous, dict) else deepcopy(fallback)
    fetched = existing.get("fetchedAt")
    if section == "projetos":
        if not fetched:
            existing["status"] = "unavailable"
        else:
            existing["status"] = "partial"
            existing["stale"] = True
    elif section == "contato":
        has_data = bool(existing.get("email") or existing.get("telefones") or existing.get("endereco") or existing.get("redes"))
        existing["status"] = "partial" if has_data else "unavailable"
        if fetched and has_data:
            existing["stale"] = True
    existing["detail"] = detail
    return existing


def _keep_project_observation(
    previous: dict[str, Any] | None, refreshed: dict[str, Any]
) -> dict[str, Any]:
    """Keep a prior observation when a refresh did not complete all pages."""
    if refreshed.get("status") == "imported":
        return refreshed
    if isinstance(previous, dict) and previous.get("fetchedAt"):
        preserved = deepcopy(previous)
        preserved["stale"] = True
        reason = _text(refreshed.get("detail"), 300) or "A paginação não foi concluída."
        old_detail = _text(preserved.get("detail"), 300)
        preserved["detail"] = f"Atualização incompleta; última observação preservada. {reason}"
        if old_detail and old_detail not in preserved["detail"]:
            preserved["detail"] += f" Observação anterior: {old_detail}"
        return preserved
    return refreshed


def _office_section(authority: dict[str, Any], raw_root: Path, collect: bool, refresh: bool) -> dict[str, Any]:
    if authority.get("role") != "deputado":
        return {
            "status": "unavailable", "amount": None, "months": {},
            "staffActive": None, "staffYear": None, "sourceUpdatedAt": None,
            "sourceUrl": None, "fetchedAt": None, "period": "2026",
            "detail": "A fonte de gabinete integrada nesta etapa é exclusiva da Câmara.",
        }
    try:
        from ingest.profile_office import load_office
        _, identifier = _chamber(str(authority["id"]))
        return load_office(identifier, raw_root, collect=collect, refresh=refresh, year=2026)
    except Exception as error:
        return {
            "status": "unavailable", "amount": None, "months": {},
            "staffActive": None, "staffYear": None, "sourceUpdatedAt": None,
            "sourceUrl": None, "fetchedAt": None, "period": "2026",
            "detail": f"Coletor de gabinete indisponível ({type(error).__name__}).",
        }


def build_profile(
    authority: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    chamber_roster: dict[str, dict[str, Any]],
    senate_profiles: dict[str, dict[str, Any]],
    raw_root: Path = RAW_PROFILES,
    collect: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    authority_id = str(authority["id"])
    chamber, identifier = _chamber(authority_id)
    source_id = authority.get("sourceId")
    roster_stamp = _text(sources.get(str(source_id), {}).get("fetchedAt"), 40)
    official_profile_url = _profile_page(authority)
    base = {
        "id": authority_id,
        "name": _text(authority.get("name")),
        "role": authority.get("role"),
        "party": _text(authority.get("party")),
        "uf": _text(authority.get("uf"), 20),
        "photo": None,
        "sourceUrl": official_profile_url,
        "fetchedAt": roster_stamp,
    }
    if chamber == "camara":
        source_contact = chamber_roster.get(identifier, {})
        contact_stamp = roster_stamp or chamber_roster.get("fetchedAt")
        contact_url = f"{CHAMBER_API}/deputados/{identifier}"
        contact = {
            "email": source_contact.get("email"), "telefones": [], "endereco": None, "redes": [],
            "sourceUrl": contact_url, "fetchedAt": contact_stamp,
            "status": "partial" if source_contact.get("email") else "unavailable",
        }
        if source_contact.get("email"):
            contact["detail"] = "O cadastro local informa e-mail; telefone e gabinete dependem do detalhe do perfil."
        mandate = _empty_mandate(contact_url)
        projects = _empty_projects(_project_list_url(authority_id))
        photo = source_contact.get("photo")
    else:
        senate = senate_profiles.get(authority_id, {})
        contact = senate.get("contact") or _empty_contact(SENATE_ROSTER_URL, roster_stamp)
        mandate = senate.get("mandato") or _empty_mandate(SENATE_ROSTER_URL, roster_stamp)
        projects = _empty_projects(official_profile_url, None)
        projects["detail"] = "Consulte a atividade legislativa na página oficial do Senado."
        photo = senate.get("photo")
        base["sourceUrl"] = senate.get("sourceUrl") or official_profile_url
    cache = _read_profile_cache(authority_id, raw_root)
    if cache.get("contact"):
        contact = cache["contact"]
    if cache.get("mandato") and chamber == "camara":
        mandate = cache["mandato"]
    if cache.get("projetos"):
        projects = cache["projetos"]
    if cache.get("photo"):
        photo = cache["photo"]
    base["photo"] = photo

    if collect and chamber == "camara":
        needs_collect = refresh or not cache.get("contact") or cache["contact"].get("status") == "unavailable"
        needs_projects = (
            refresh or not cache.get("projetos") or cache["projetos"].get("status") != "imported"
        )
        if needs_collect:
            detail_url = f"{CHAMBER_API}/deputados/{identifier}"
            try:
                data = _request_json(detail_url)
                sections = parse_chamber_detail(data, authority_id)
                contact = sections["contact"]
                mandate = sections["mandato"]
                photo = sections.get("photo") or photo
            except Exception as error:
                detail = f"Falha ao atualizar detalhes de contato ({type(error).__name__})."
                contact = _failure_section(cache.get("contact"), contact, detail, "contato")
                mandate = deepcopy(cache.get("mandato") or mandate)
                mandate["detail"] = detail
                if mandate.get("fetchedAt"):
                    mandate["stale"] = True
            if needs_projects:
                try:
                    refreshed_projects = fetch_chamber_projects(authority_id)
                except Exception as error:
                    refreshed_projects = _failure_section(
                        cache.get("projetos"), projects,
                        f"Falha ao atualizar projetos ({type(error).__name__}).", "projetos",
                    )
                projects = _keep_project_observation(cache.get("projetos"), refreshed_projects)
            new_cache = {"contact": contact, "mandato": mandate, "projetos": projects, "photo": photo}
            _write_profile_cache(authority_id, new_cache, raw_root)
        elif needs_projects:
            previous = cache.get("projetos")
            try:
                refreshed_projects = fetch_chamber_projects(authority_id)
            except Exception as error:
                refreshed_projects = _failure_section(
                    previous, projects, f"Falha ao atualizar projetos ({type(error).__name__}).", "projetos"
                )
            projects = _keep_project_observation(previous, refreshed_projects)
            _write_profile_cache(authority_id, {"contact": contact, "mandato": mandate, "projetos": projects, "photo": photo}, raw_root)
    base.update({"contato": contact, "mandato": mandate, "projetos": projects})
    base["gabinete"] = _office_section(authority, raw_root, collect=collect, refresh=refresh)
    return base


def build_snapshot(
    root: Path = ROOT,
    output: Path | None = None,
    collect: bool = False,
    refresh: bool = False,
    limit: int | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    import_path = root / "data" / "imports" / "legislative.json"
    payload = _json_from_path(import_path)
    if not isinstance(payload, dict):
        raise ValueError("Importação legislativa precisa ser um objeto JSON")
    roster = _current_roster(payload)
    sources = _source_map(payload)
    chamber_roster, _ = _chamber_cache_roster(root)
    senate_profiles = _senate_xml_profiles(
        sources, root / "data" / "raw" / "legislative" / "senadores-atual.xml"
    )
    raw_root = root / "data" / "raw" / "profiles"
    profiles: list[dict[str, Any]] = []
    collect_targets = roster[:limit] if limit is not None else roster
    target_ids = {row["id"] for row in collect_targets} if collect else set()
    target_indices = {authority["id"]: index for index, authority in enumerate(roster)}
    for authority in roster:
        profiles.append(build_profile(
            authority,
            sources,
            chamber_roster,
            senate_profiles,
            raw_root=raw_root,
            collect=False,
        ))
    if collect and target_ids:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(
                    build_profile,
                    authority,
                    sources,
                    chamber_roster,
                    senate_profiles,
                    raw_root,
                    True,
                    refresh,
                ): authority["id"]
                for authority in collect_targets
            }
            done = 0
            for future in as_completed(futures):
                authority_id = futures[future]
                try:
                    profiles[target_indices[authority_id]] = future.result()
                except Exception as error:
                    # The offline snapshot remains usable if one profile fails.
                    profiles[target_indices[authority_id]]["coleta"] = {
                        "status": "unavailable",
                        "detail": f"Falha na coleta ({type(error).__name__}).",
                    }
                done += 1
                print(f"perfis consultados: {done}/{len(target_ids)}")
    generated = utc_now()
    snapshot = {"generatedAt": generated, "profiles": {profile["id"]: profile for profile in profiles}}
    destination = output or (root / "data" / "snapshots" / "perfis.json")
    _atomic_json(destination, snapshot)
    projects = sum(len(profile["projetos"].get("items", [])) for profile in profiles)
    stats = {
        "profiles": len(profiles),
        "camara": sum(profile["role"] == "deputado" for profile in profiles),
        "senado": sum(profile["role"] == "senador" for profile in profiles),
        "collected": len(target_ids),
        "projects": projects,
        "snapshotBytes": destination.stat().st_size,
    }
    return snapshot, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera snapshot local whitelisted de fichas parlamentares")
    parser.add_argument("--collect", action="store_true", help="consulta contatos e projetos da Câmara")
    parser.add_argument("--refresh", action="store_true", help="refaz dados que já têm cache")
    parser.add_argument("--limit", type=int, help="limita perfis que fazem consultas; o snapshot mantém todos")
    parser.add_argument("--output", type=Path, help="caminho do snapshot JSON de saída")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit deve ser pelo menos 1")
    if args.refresh and not args.collect:
        parser.error("--refresh exige --collect")
    destination = args.output
    if destination is not None and not destination.is_absolute():
        destination = ROOT / destination
    snapshot, stats = build_snapshot(
        ROOT,
        destination,
        collect=args.collect,
        refresh=args.refresh,
        limit=args.limit,
    )
    print(
        "snapshot",
        f"perfis={stats['profiles']}",
        f"camara={stats['camara']}",
        f"senado={stats['senado']}",
        f"consultados={stats['collected']}",
        f"projetos={stats['projects']}",
        f"bytes={stats['snapshotBytes']}",
        f"saida={destination or DEFAULT_OUTPUT}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
