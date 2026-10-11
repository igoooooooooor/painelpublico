import gzip
import importlib.util
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("publish_data", ROOT / "scripts" / "publish_data.py")
PUBLISH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISH)


CURRENT = "a" * 64
STALE = "b" * 64


def make_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        "PRAGMA user_version = 7;"
        "CREATE TABLE authorities(id TEXT PRIMARY KEY, name TEXT);"
        "CREATE TABLE expenses(id TEXT PRIMARY KEY, amountCents INTEGER);"
        "INSERT INTO authorities VALUES ('a1', 'Fulana'), ('a2', 'Beltrano');"
        "INSERT INTO expenses VALUES ('e1', 1000);"
    )
    connection.commit()
    connection.close()


def make_tree(root):
    snapshots = root / "snapshots"
    details = snapshots / "chamber-vote-details"
    (details / CURRENT).mkdir(parents=True)
    (details / STALE).mkdir(parents=True)
    (snapshots / "perfis.json").write_text('{"perfil": true}', encoding="utf-8")
    (snapshots / "chamber-votes.json").write_text(json.dumps({"detailsVersion": CURRENT}), encoding="utf-8")
    (details / "1-2.json").write_text("{}", encoding="utf-8")
    (details / CURRENT / "1-2.json").write_text("{}", encoding="utf-8")
    (details / STALE / "1-2.json").write_text("{}", encoding="utf-8")
    (snapshots / "chamber-payroll-2024.json").write_text("{}", encoding="utf-8")  # insumo local
    (snapshots / ".DS_Store").write_bytes(b"\x00")
    reviews = root / "reviews"
    reviews.mkdir()
    (reviews / "chamber-vote-reviews-2026-10-09.json").write_text("[]", encoding="utf-8")
    (reviews / "chamber-vote-segment-reviews-2026-10-09.json").write_text("[]", encoding="utf-8")
    (reviews / "chamber-vote-reviews-2023-12-31.draft.json").write_text("[]", encoding="utf-8")
    (reviews / "scoreboard-audit-2025.json").write_text("{}", encoding="utf-8")
    (reviews / "scoreboard-audit-2025").mkdir()
    (reviews / "scoreboard-audit-2025" / "chamber-vote-reviews-2026-10-09.json").write_text("[]", encoding="utf-8")
    return snapshots, reviews


def tar_names(path):
    with tarfile.open(path, "r:gz") as archive:
        return sorted(archive.getnames())


class PublishDataTests(unittest.TestCase):
    def test_package_contains_database_snapshots_reviews_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "na-lupa.sqlite3"
            make_database(db_path)
            snapshots, reviews = make_tree(root)
            logs = []
            out_dir, files, notes = PUBLISH.build_package(
                "data-2026-10-11", db_path, snapshots, reviews, root / "releases",
                local_only_patterns=["chamber-payroll*.json"], commit="abcdef1234567890", log=logs.append)

            self.assertEqual(out_dir, root / "releases" / "data-2026-10-11")
            self.assertEqual([path.name for path in files], [
                "na-lupa-data-2026-10-11.sqlite3.gz", "snapshots-data-2026-10-11.tar.gz",
                "reviews-data-2026-10-11.tar.gz", "manifest.json"])
            self.assertFalse((out_dir / "na-lupa-data-2026-10-11.sqlite3").exists(), "cópia intermediária deve ser apagada")

            with gzip.open(files[0], "rb") as packed:
                restored = root / "restored.sqlite3"
                restored.write_bytes(packed.read())
            connection = sqlite3.connect(restored)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM authorities").fetchone()[0], 2)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 7)
            connection.close()

            self.assertEqual(tar_names(files[1]), ["snapshots/chamber-vote-details/1-2.json", f"snapshots/chamber-vote-details/{CURRENT}/1-2.json", "snapshots/chamber-votes.json", "snapshots/perfis.json"])
            self.assertEqual(tar_names(files[2]), [
                "reviews/chamber-vote-reviews-2026-10-09.json", "reviews/chamber-vote-segment-reviews-2026-10-09.json"])

            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["tag"], "data-2026-10-11")
            self.assertEqual(manifest["commit"], "abcdef1234567890")
            self.assertEqual(manifest["database"], {"schemaVersion": 7, "tables": {"authorities": 2, "expenses": 1}})
            self.assertEqual([entry["name"] for entry in manifest["files"]], [path.name for path in files[:3]])
            for entry in manifest["files"]:
                self.assertEqual(len(entry["sha256"]), 64)
                self.assertEqual(entry["bytes"], (out_dir / entry["name"]).stat().st_size)
            self.assertEqual(manifest["snapshots"], ["chamber-vote-details/1-2.json", f"chamber-vote-details/{CURRENT}/1-2.json", "chamber-votes.json", "perfis.json"])

            text = notes.read_text(encoding="utf-8")
            self.assertIn("# Dados do Painel Público — data-2026-10-11", text)
            self.assertIn("2 cadastros, 1 notas da cota", text)
            self.assertIn("PAINEL_DB=na-lupa-data-2026-10-11.sqlite3 PAINEL_SNAPSHOTS=snapshots make dev", text)
            self.assertIn("2 arquivos de revisão", text)
            self.assertIn("LEGAL-NOTICE.md", text)
            self.assertIn("CC BY 4.0", text)

    def test_package_without_reviews_skips_the_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "na-lupa.sqlite3"
            make_database(db_path)
            snapshots, _ = make_tree(root)
            out_dir, files, notes = PUBLISH.build_package(
                "data-2026-10-11", db_path, snapshots, root / "missing-reviews", root / "releases",
                local_only_patterns=[], log=lambda _message: None)
            self.assertEqual([path.name for path in files], [
                "na-lupa-data-2026-10-11.sqlite3.gz", "snapshots-data-2026-10-11.tar.gz", "manifest.json"])
            self.assertFalse((out_dir / "reviews-data-2026-10-11.tar.gz").exists())
            self.assertNotIn("arquivos de revisão", notes.read_text(encoding="utf-8"))

    def test_local_only_patterns_come_from_the_deploy_list(self):
        patterns = PUBLISH.read_patterns(ROOT / "deploy" / "snapshots-local-only.txt")
        self.assertIn("chamber-payroll*.json", patterns)
        self.assertFalse(any(line.startswith("#") for line in patterns))
        self.assertTrue(PUBLISH.matches_any("chamber-payroll-2024.json", patterns))
        self.assertFalse(PUBLISH.matches_any("perfis.json", patterns))

    def test_review_filter_keeps_only_reviewed_catalog_files(self):
        self.assertTrue(PUBLISH.is_review_file("chamber-vote-reviews-2026-10-09.json"))
        self.assertTrue(PUBLISH.is_review_file("chamber-vote-segment-reviews-2025-12-31.json"))
        self.assertFalse(PUBLISH.is_review_file("chamber-vote-reviews-2023-12-31.draft.json"))
        self.assertFalse(PUBLISH.is_review_file("chamber-vote-inventory-2026-10-09.json"))
        self.assertFalse(PUBLISH.is_review_file("alert-triage-2026-10-09.md"))

    def test_main_dry_run_does_not_touch_github(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "na-lupa.sqlite3"
            make_database(db_path)
            snapshots, reviews = make_tree(root)
            with patch.object(PUBLISH, "github_token") as github_token, patch.object(PUBLISH, "publish_release") as publish, \
                    patch.object(PUBLISH, "release_exists") as exists, patch("builtins.print"):
                code = PUBLISH.main(["--dry-run", "--tag", "data-2026-10-11", "--db", str(db_path),
                                     "--snapshots", str(snapshots), "--reviews", str(reviews),
                                     "--output", str(root / "releases")])
            self.assertEqual(code, 0)
            github_token.assert_not_called()
            exists.assert_not_called()
            publish.assert_not_called()
            self.assertTrue((root / "releases" / "data-2026-10-11" / "manifest.json").exists())

    def test_main_refuses_an_existing_release(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "na-lupa.sqlite3"
            make_database(db_path)
            snapshots, reviews = make_tree(root)
            with patch.object(PUBLISH, "github_token", return_value="token"), \
                    patch.object(PUBLISH, "release_exists", return_value=True), \
                    patch.object(PUBLISH, "publish_release") as publish:
                with self.assertRaises(SystemExit) as raised:
                    PUBLISH.main(["--tag", "data-2026-10-11", "--db", str(db_path), "--snapshots", str(snapshots),
                                  "--reviews", str(reviews), "--output", str(root / "releases")])
            self.assertIn("já existe", str(raised.exception))
            publish.assert_not_called()
            self.assertFalse((root / "releases").exists(), "não deve montar o pacote quando o release já existe")

    def test_stale_vote_detail_generations_are_pruned_only_when_the_index_names_one(self):
        self.assertTrue(PUBLISH.is_stale_details_generation(Path("chamber-vote-details") / STALE / "1-2.json", CURRENT))
        self.assertFalse(PUBLISH.is_stale_details_generation(Path("chamber-vote-details") / CURRENT / "1-2.json", CURRENT))
        self.assertFalse(PUBLISH.is_stale_details_generation(Path("chamber-vote-details") / "1-2.json", CURRENT))
        self.assertFalse(PUBLISH.is_stale_details_generation(Path("chamber-vote-details") / STALE / "1-2.json", None))
        self.assertFalse(PUBLISH.is_stale_details_generation(Path("other") / STALE / "1-2.json", CURRENT))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertIsNone(PUBLISH.current_details_version(root))
            (root / "chamber-votes.json").write_text("{}", encoding="utf-8")
            self.assertIsNone(PUBLISH.current_details_version(root))
            (root / "chamber-votes.json").write_text(json.dumps({"detailsVersion": CURRENT}), encoding="utf-8")
            self.assertEqual(PUBLISH.current_details_version(root), CURRENT)

    def test_counts_use_brazilian_thousands_separator(self):
        self.assertEqual(PUBLISH._count(127850), "127.850")
        self.assertEqual(PUBLISH._count(765), "765")

    def test_main_refuses_a_tag_without_the_data_prefix(self):
        with self.assertRaises(SystemExit) as raised:
            PUBLISH.main(["--dry-run", "--tag", "v1.0"])
        self.assertIn("data-", str(raised.exception))

    def test_github_token_prefers_environment_over_gh(self):
        self.assertEqual(PUBLISH.github_token({"PAINEL_GITHUB_TOKEN": " abc "}), "abc")
        self.assertEqual(PUBLISH.github_token({"GH_TOKEN": "ghs"}), "ghs")
        with patch.object(PUBLISH.shutil, "which", return_value=None):
            self.assertIsNone(PUBLISH.github_token({}))
        with self.assertRaises(SystemExit):
            PUBLISH.check_token(None)

    def test_publish_release_creates_the_release_and_uploads_each_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes = root / "NOTES.md"
            notes.write_text("# notas", encoding="utf-8")
            files = [root / "manifest.json", root / "na-lupa-data-2026-10-11.sqlite3.gz"]
            for path in files:
                path.write_bytes(b"conteudo")
            calls = []

            def request(url, token, method="GET", data=None, content_type=None, content_length=None):
                payload = data.read() if hasattr(data, "read") else data
                calls.append((method, url, token, payload, content_type, content_length))
                if url.endswith("/releases/tags/data-2026-10-11"):
                    raise PUBLISH.urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
                if url.endswith("/releases") and method == "POST":
                    return {"upload_url": "https://uploads.test/repos/x/y/releases/7/assets{?name,label}",
                            "html_url": "https://github.com/x/y/releases/tag/data-2026-10-11"}
                return {}

            url = PUBLISH.publish_release("data-2026-10-11", files, notes, token="tok", repo="x/y", request=request,
                                          log=lambda _m: None)
            self.assertEqual(url, "https://github.com/x/y/releases/tag/data-2026-10-11")
            self.assertEqual(calls[0][:3], ("GET", f"{PUBLISH.API_URL}/repos/x/y/releases/tags/data-2026-10-11", "tok"))
            created = json.loads(calls[1][3])
            self.assertEqual(calls[1][:2], ("POST", f"{PUBLISH.API_URL}/repos/x/y/releases"))
            self.assertEqual((created["tag_name"], created["target_commitish"], created["name"], created["body"]),
                             ("data-2026-10-11", "main", "Dados data-2026-10-11", "# notas"))
            self.assertEqual([call[1] for call in calls[2:]], [
                "https://uploads.test/repos/x/y/releases/7/assets?name=manifest.json",
                "https://uploads.test/repos/x/y/releases/7/assets?name=na-lupa-data-2026-10-11.sqlite3.gz"])
            self.assertEqual([call[4] for call in calls[2:]], ["application/json", "application/gzip"])
            self.assertEqual([call[5] for call in calls[2:]], [8, 8])
            self.assertEqual(calls[2][3], b"conteudo")

    def test_publish_release_refuses_an_existing_tag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            notes = Path(temp_dir) / "NOTES.md"
            notes.write_text("x", encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                PUBLISH.publish_release("data-2026-10-11", [], notes, token="tok", request=lambda *a, **k: {})
            self.assertIn("já existe", str(raised.exception))

    def test_default_tag_uses_the_date(self):
        from datetime import date
        self.assertEqual(PUBLISH.default_tag(date(2026, 10, 11)), "data-2026-10-11")


if __name__ == "__main__":
    unittest.main()
