import gzip
import hashlib
import importlib.util
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_data", ROOT / "scripts" / "fetch_data.py")
FETCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FETCH)

TAG = "data-2026-10-11"


def make_release_files(directory):
    """Monta um release falso: banco gz, snapshots e revisões em tar.gz, manifesto com SHA-256."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    db = directory / "plain.sqlite3"
    connection = sqlite3.connect(db)
    connection.executescript("CREATE TABLE authorities(id TEXT); INSERT INTO authorities VALUES ('a1');")
    connection.commit()
    connection.close()
    db_gz = directory / f"na-lupa-{TAG}.sqlite3.gz"
    with open(db, "rb") as raw, gzip.open(db_gz, "wb") as packed:
        packed.write(raw.read())
    db.unlink()

    def add(archive, name, content):
        data = content.encode("utf-8")
        info = tarfile.TarInfo(name)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))

    snapshots = directory / f"snapshots-{TAG}.tar.gz"
    with tarfile.open(snapshots, "w:gz") as archive:
        add(archive, "snapshots/perfis.json", '{"novo": true}')
        add(archive, "snapshots/chamber-vote-details/aaa/1-2.json", "{}")
    reviews = directory / f"reviews-{TAG}.tar.gz"
    with tarfile.open(reviews, "w:gz") as archive:
        add(archive, "reviews/chamber-vote-reviews-2026-10-09.json", "[]")

    files = []
    for path in (db_gz, snapshots, reviews):
        files.append({"name": path.name, "bytes": path.stat().st_size,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"tag": TAG, "files": files}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def fake_release(directory, tag=TAG, **extra):
    assets = [{"name": path.name, "browser_download_url": f"file://{path}"} for path in sorted(Path(directory).iterdir())]
    return {"tag_name": tag, "created_at": "2026-10-11T00:00:00Z", "html_url": f"https://example.test/{tag}",
            "draft": False, "prerelease": False, "assets": assets, **extra}


def local_downloader(url, destination, token=None, log=print):
    source = Path(url[len("file://"):])
    Path(destination).write_bytes(source.read_bytes())
    return Path(destination)


class SelectReleaseTests(unittest.TestCase):
    def test_picks_the_newest_data_release_and_ignores_drafts_and_code_tags(self):
        releases = [
            {"tag_name": "v1.0", "created_at": "2026-12-01T00:00:00Z"},
            {"tag_name": "data-2026-11-10", "created_at": "2026-11-10T00:00:00Z", "draft": True},
            {"tag_name": "data-2026-10-11", "created_at": "2026-10-11T00:00:00Z"},
            {"tag_name": "data-2026-09-10", "created_at": "2026-09-10T00:00:00Z"},
        ]
        self.assertEqual(FETCH.select_release(releases)["tag_name"], "data-2026-10-11")
        self.assertEqual(FETCH.select_release(releases, "data-2026-09-10")["tag_name"], "data-2026-09-10")
        with self.assertRaises(FETCH.FetchError):
            FETCH.select_release(releases, "data-2026-11-10")
        with self.assertRaises(FETCH.FetchError):
            FETCH.select_release([{"tag_name": "v1.0"}])


class FetchTests(unittest.TestCase):
    def test_fetch_downloads_verifies_and_installs_everything(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            release_dir = make_release_files(root / "remote")
            data_dir = root / "data"
            (data_dir / "snapshots").mkdir(parents=True)
            (data_dir / "snapshots" / "perfis.json").write_text('{"velho": true}', encoding="utf-8")
            (data_dir / "snapshots" / "arrecadacao.json").write_text("{}", encoding="utf-8")
            logs = []
            summary = FETCH.fetch(None, data_dir, fetch_json=lambda url, token=None: [fake_release(release_dir)],
                                  downloader=local_downloader, log=logs.append)

            self.assertEqual(summary["tag"], TAG)
            self.assertEqual((summary["snapshots"], summary["reviews"]), (2, 1))
            connection = sqlite3.connect(data_dir / "na-lupa.sqlite3")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM authorities").fetchone()[0], 1)
            connection.close()
            self.assertEqual(json.loads((data_dir / "snapshots" / "perfis.json").read_text(encoding="utf-8")), {"novo": True})
            self.assertTrue((data_dir / "snapshots" / "arrecadacao.json").exists(), "arquivos locais sem equivalente ficam")
            self.assertTrue((data_dir / "snapshots" / "chamber-vote-details" / "aaa" / "1-2.json").exists())
            self.assertTrue((data_dir / "reviews" / "chamber-vote-reviews-2026-10-09.json").exists())
            self.assertFalse((data_dir / "releases").exists(), "downloads são apagados por padrão, com a pasta")
            self.assertFalse(any(path.name.startswith(".") for path in data_dir.iterdir()), "sem temporários sobrando")

    def test_existing_database_requires_force_and_is_kept_as_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            release_dir = make_release_files(root / "remote")
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "na-lupa.sqlite3").write_bytes(b"antigo")
            fetch_json = lambda url, token=None: [fake_release(release_dir)]  # noqa: E731
            with self.assertRaises(FETCH.FetchError) as raised:
                FETCH.fetch(None, data_dir, fetch_json=fetch_json, downloader=local_downloader, log=lambda _m: None)
            self.assertIn("--force", str(raised.exception))
            self.assertEqual((data_dir / "na-lupa.sqlite3").read_bytes(), b"antigo")

            FETCH.fetch(None, data_dir, force=True, fetch_json=fetch_json, downloader=local_downloader, log=lambda _m: None)
            backups = list((data_dir / "backups").glob("na-lupa-before-fetch-*.sqlite3"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b"antigo")
            self.assertNotEqual((data_dir / "na-lupa.sqlite3").read_bytes(), b"antigo")

    def test_corrupted_download_is_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            release_dir = make_release_files(root / "remote")
            manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
            manifest["files"][0]["sha256"] = "0" * 64
            (release_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            data_dir = root / "data"
            with self.assertRaises(FETCH.FetchError) as raised:
                FETCH.fetch(None, data_dir, fetch_json=lambda url, token=None: [fake_release(release_dir)],
                            downloader=local_downloader, log=lambda _m: None)
            self.assertIn("SHA-256", str(raised.exception))
            self.assertFalse((data_dir / "na-lupa.sqlite3").exists())

    def test_release_missing_a_manifest_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            release_dir = make_release_files(root / "remote")
            release = fake_release(release_dir)
            release["assets"] = [asset for asset in release["assets"] if not asset["name"].startswith("reviews-")]
            with self.assertRaises(FETCH.FetchError) as raised:
                FETCH.fetch(None, root / "data", fetch_json=lambda url, token=None: [release],
                            downloader=local_downloader, log=lambda _m: None)
            self.assertIn("reviews-", str(raised.exception))

    def test_tar_members_outside_the_destination_are_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "evil.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("snapshots/../../escape.json")
                info.size = 2
                archive.addfile(info, io.BytesIO(b"{}"))
            with self.assertRaises(FETCH.FetchError):
                FETCH._safe_extract(archive_path, root / "staging")
            self.assertFalse((root / "escape.json").exists())

    def test_install_backup_name_uses_the_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            release_dir = make_release_files(root / "remote")
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "na-lupa.sqlite3").write_bytes(b"antigo")
            found = {"database": release_dir / f"na-lupa-{TAG}.sqlite3.gz"}
            FETCH.install_package(found, data_dir, force=True, log=lambda _m: None,
                                  now=datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc))
            self.assertTrue((data_dir / "backups" / "na-lupa-before-fetch-20261011T120000Z.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
