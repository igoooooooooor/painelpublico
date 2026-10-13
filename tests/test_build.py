import importlib.util
import json
import os
import re
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dashboard_build", ROOT / "scripts" / "build.py")
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


def embedded_data(path):
    """Payload do app, que fica no arquivo JavaScript com hash referenciado pelo HTML (não mais no documento)."""
    html = path.read_text(encoding="utf-8")
    script_name = re.search(r'<script src="/assets/(app\.[0-9a-f]{12}\.js)" defer></script>', html).group(1)
    script = (path.parent / "assets" / script_name).read_text(encoding="utf-8")
    marker = "const DATA = "
    start = script.index(marker) + len(marker)
    end = script.index(";\n", start)
    return json.loads(script[start:end]), html + script


class BuildTests(unittest.TestCase):
    def test_build_works_without_any_snapshot_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "dist" / "index.html"
            with patch.object(BUILD, "SNAPSHOTS", root / "snapshots"):
                BUILD.build(output)

            data, _ = embedded_data(output)
            self.assertEqual(set(data), {
                "geradoEm", "ultimaVotacao", "votacoes", "presencaTodos", "votosCompletos",
                "arrecadacao", "arrecadacaoEstadual", "perfis", "senado", "sitePages",
            })
            self.assertEqual([section["path"] for section in data["sitePages"]["sections"]][:3], ["/", "/alertas", "/placar"])
            self.assertIn("alerts", [section["id"] for section in data["sitePages"]["methodology"]["sections"]])
            self.assertTrue(data["sitePages"]["about"]["sections"])
            self.assertIsNone(data["geradoEm"])
            self.assertEqual(data["presencaTodos"], [])
            self.assertEqual(data["votosCompletos"], {})
            self.assertIsNone(data["arrecadacao"])
            self.assertIsNone(data["arrecadacaoEstadual"])
            self.assertEqual(data["perfis"], {"profiles": {}, "sobDemanda": False})
            self.assertEqual(data["senado"], {"sobDemanda": False})
            self.assertEqual(len(data["votacoes"]), 4)

    def test_assets_are_hashed_referenced_by_the_html_and_stale_ones_are_pruned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "dist" / "index.html"
            assets = root / "dist" / "assets"
            assets.mkdir(parents=True)
            stale = assets / "app.000000000000.js"
            stale.write_text("old", encoding="utf-8")
            old_time = time.time() - 30 * 86400
            os.utime(stale, (old_time, old_time))
            recent = assets / "app.111111111111.css"
            recent.write_text("recent", encoding="utf-8")
            foreign = assets / "notes.txt"
            foreign.write_text("keep", encoding="utf-8")
            with patch.object(BUILD, "SNAPSHOTS", root / "snapshots"):
                BUILD.build(output)
                html = output.read_text(encoding="utf-8")
                script = re.search(r'<script src="/assets/(app\.[0-9a-f]{12}\.js)" defer></script>', html).group(1)
                style = re.search(r'<link rel="stylesheet" href="/assets/(app\.[0-9a-f]{12}\.css)">', html).group(1)
                self.assertTrue((assets / script).is_file())
                self.assertTrue((assets / style).is_file())
                self.assertNotIn("const DATA = ", html)
                self.assertLess(len(html.encode("utf-8")), 20_000)
                # Mesmo conteúdo, mesmo nome: um build repetido não muda a referência nem o cache.
                BUILD.build(output)
                self.assertEqual(sorted(entry.name for entry in assets.iterdir() if entry.name.startswith("app.") and entry.name.endswith(".js")),
                                 sorted({script}))
            self.assertFalse(stale.exists(), "arquivo de build antigo e com mais de 7 dias é removido")
            self.assertTrue(recent.exists(), "arquivo recente fica para páginas ainda em cache")
            self.assertTrue(foreign.exists())

    def test_senate_snapshots_are_markers_only_in_the_build(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshots = root / "snapshots"
            snapshots.mkdir()
            (snapshots / "senado-atividade.json").write_text(
                '{"private":"SENATE_ACTIVITY_PRIVATE"}', encoding="utf-8")
            (snapshots / "senado-projetos.json").write_text(
                '{"profiles":{"senado:1":{"private":"SENATE_PROJECTS_PRIVATE"}}}', encoding="utf-8")
            (snapshots / "perfis.json").write_text(
                '{"profiles":{"senado:1":{"private":"PROFILE_PRIVATE"}}}', encoding="utf-8")
            output = root / "dist" / "index.html"

            with patch.object(BUILD, "SNAPSHOTS", snapshots):
                BUILD.build(output)

            data, html = embedded_data(output)
            self.assertEqual(data["senado"], {"sobDemanda": True})
            self.assertEqual(data["perfis"], {"profiles": {}, "sobDemanda": True})
            for private_marker in ("SENATE_ACTIVITY_PRIVATE", "SENATE_PROJECTS_PRIVATE", "PROFILE_PRIVATE"):
                self.assertNotIn(private_marker, html)

    def test_senate_projects_enable_profile_fetch_without_profiles_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshots = root / "snapshots"
            snapshots.mkdir()
            (snapshots / "senado-projetos.json").write_text("{}", encoding="utf-8")
            output = root / "dist" / "index.html"

            with patch.object(BUILD, "SNAPSHOTS", snapshots):
                BUILD.build(output)

            data, _ = embedded_data(output)
            self.assertEqual(data["perfis"], {"profiles": {}, "sobDemanda": True})
            self.assertEqual(data["senado"], {"sobDemanda": False})

    def test_editorial_sample_is_ignored_and_all_vote_rows_are_kept(self):
        metadata = json.loads((ROOT / "frontend" / "data" / "votes.json").read_text(encoding="utf-8"))
        selected_id = metadata[0]["id"]
        rows = [
            [10000 + index, f"Parlamentar fictício {index}", "XP" if index < 8 else "YZ",
             "DF", "Sim" if index < 8 else "Não"]
            for index in range(14)
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshots = root / "snapshots"
            snapshots.mkdir()
            (snapshots / "editorial.json").write_text(json.dumps({
                "geral": {"marcadorPrivado": "RESUMO_EDITORIAL_IGNORADO"},
                "deputados": [{"nome": f"Amostra fictícia {index}"} for index in range(10)],
            }), encoding="utf-8")
            (snapshots / "votos.json").write_text(json.dumps({
                selected_id: rows,
                "votacao-nao-selecionada": [[1, "Fora do Placar", "ZZ", "SP", "Sim"]],
            }), encoding="utf-8")
            output = root / "dist" / "index.html"

            with patch.object(BUILD, "SNAPSHOTS", snapshots):
                BUILD.build(output)

            data, html = embedded_data(output)
            self.assertNotIn("deputados", data)
            self.assertNotIn("geral", data)
            self.assertNotIn("RESUMO_EDITORIAL_IGNORADO", html)
            self.assertNotIn("Amostra fictícia", html)
            self.assertEqual(set(data["votosCompletos"]), {selected_id})
            self.assertEqual(len(data["votosCompletos"][selected_id]), 14)
            vote = next(vote for vote in data["votacoes"] if vote["id"] == selected_id)
            self.assertEqual(vote["partidos"], [
                {"p": "XP", "sim": 8, "nao": 0, "outros": 0},
                {"p": "YZ", "sim": 0, "nao": 6, "outros": 0},
            ])
            self.assertNotIn("votos", vote)

    def test_versioned_vote_metadata_has_only_card_and_summary_fields(self):
        metadata = json.loads((ROOT / "frontend" / "data" / "votes.json").read_text(encoding="utf-8"))
        allowed = {
            "id", "proposicao", "titulo", "naPratica", "situacao", "texto", "ficha", "curto",
            "data", "sim", "nao", "aprovada", "secreta",
        }
        self.assertEqual(len(metadata), 4)
        for vote in metadata:
            self.assertEqual(set(vote), allowed)


if __name__ == "__main__":
    unittest.main()
