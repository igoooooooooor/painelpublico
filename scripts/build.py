"""Build estático sem dependências: python3 scripts/build.py."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SNAPSHOTS = Path(os.environ.get("PAINEL_SNAPSHOTS") or ROOT / "data" / "snapshots")
STYLES = ("tokens.css", "base.css", "public-data.css", "cidadao.css")
# Ordem explícita: helpers/views antes do bootstrap e router.
SCRIPTS = ("profile-data.js", "spending-analysis.js", "spending-view.js", "public-data-view.js",
           "cidadao-view.js", "extras-view.js", "partidos-view.js", "app.script.js")


def build(output=None):
    editorial = SNAPSHOTS / "editorial.json"
    if not editorial.is_file():
        raise FileNotFoundError(
            "Falta data/snapshots/editorial.json. Os dados não são versionados; "
            "consulte README.md para preparar uma cópia local."
        )
    data = json.loads(editorial.read_text(encoding="utf-8"))
    for key, filename in (("votosCompletos", "votos.json"), ("presencaTodos", "presenca.json"),
                          ("arrecadacao", "arrecadacao.json")):
        path = SNAPSHOTS / filename
        data[key] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    # perfis.json (~15 MB) não entra na página: cada ficha busca o seu em /api/c/perfil/<id>.
    data["perfis"] = {"profiles": {}, "sobDemanda": (SNAPSHOTS / "perfis.json").exists()}
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    script = "\n".join((FRONTEND / "scripts" / name).read_text(encoding="utf-8") for name in SCRIPTS)
    if script.count("/*DATA*/null") != 1:
        raise ValueError("Marcador de dados ausente ou duplicado")
    script = script.replace("/*DATA*/null", payload)
    styles = "\n".join((FRONTEND / "styles" / name).read_text(encoding="utf-8") for name in STYLES)
    html = (FRONTEND / "index.template.html").read_text(encoding="utf-8")
    for marker in ("{{STYLES}}", "{{SCRIPTS}}"):
        if html.count(marker) != 1:
            raise ValueError(f"Marcador {marker} ausente ou duplicado")
    html = html.replace("{{STYLES}}", styles).replace("{{SCRIPTS}}", script)
    output = Path(output) if output else ROOT / "dist" / "index.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".html.tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(output)
    return output


if __name__ == "__main__":
    try:
        print(f"Gerado: {build().relative_to(ROOT)}")
    except FileNotFoundError as error:
        raise SystemExit(str(error)) from None
