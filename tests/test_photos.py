import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import photos

JPEG = b'\xff\xd8\xff\xe0' + b'0' * 200


class PhotoCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, result):
        def run(url):
            self.calls.append(url)
            if isinstance(result, Exception):
                raise result
            return result
        return run

    def test_only_known_identifiers_build_an_official_url(self):
        for bad in ('', 'camara:', 'camara:abc', 'tse:1', 'camara:1/../../x', 'https://evil.test/x.jpg', 'camara:1234567890'):
            self.assertIsNone(photos.photo(bad, fetch=self.fetch(JPEG), cache_dir=self.folder))
        self.assertEqual(self.calls, [])
        photos.photo('camara:204515', fetch=self.fetch(JPEG), cache_dir=self.folder)
        photos.photo('senado:5672', fetch=self.fetch(JPEG), cache_dir=self.folder)
        self.assertEqual(self.calls, ['https://www.camara.leg.br/internet/deputado/bandep/204515.jpg',
                                      'https://www.senado.leg.br/senadores/img/fotos-oficiais/senador5672.jpg'])

    def test_person_outside_the_database_never_reaches_the_source_or_the_disk(self):
        known = {'camara:204515'}.__contains__
        self.assertIsNone(photos.photo('camara:987654321', fetch=self.fetch(JPEG), cache_dir=self.folder, known=known))
        self.assertEqual((self.calls, list(self.folder.iterdir())), ([], []))
        self.assertEqual(photos.photo('camara:204515', fetch=self.fetch(JPEG), cache_dir=self.folder, known=known), JPEG)

    def test_downloads_once_and_refreshes_after_thirty_days(self):
        self.assertEqual(photos.photo('camara:1', fetch=self.fetch(JPEG), now=1000, cache_dir=self.folder), JPEG)
        self.assertEqual(photos.photo('camara:1', fetch=self.fetch(JPEG), now=2000, cache_dir=self.folder), JPEG)
        self.assertEqual(len(self.calls), 1)
        (self.folder / 'camara-1.jpg').touch()
        later = (self.folder / 'camara-1.jpg').stat().st_mtime + photos.FRESH_SECONDS + 1
        photos.photo('camara:1', fetch=self.fetch(JPEG), now=later, cache_dir=self.folder)
        self.assertEqual(len(self.calls), 2)

    def test_failures_and_non_jpeg_answers_fall_back_without_retrying_every_request(self):
        self.assertIsNone(photos.photo('camara:2', fetch=self.fetch(TimeoutError()), cache_dir=self.folder))
        self.assertIsNone(photos.photo('camara:2', fetch=self.fetch(JPEG), cache_dir=self.folder))
        self.assertEqual(len(self.calls), 1)  # a falha fica anotada por um dia
        self.assertIsNone(photos.photo('camara:3', fetch=self.fetch(b'<html>erro</html>'), cache_dir=self.folder))
        self.assertFalse((self.folder / 'camara-3.jpg').exists())

    def test_an_old_copy_is_kept_when_the_source_fails(self):
        photos.photo('senado:9', fetch=self.fetch(JPEG), now=0, cache_dir=self.folder)
        stale_time = (self.folder / 'senado-9.jpg').stat().st_mtime + photos.FRESH_SECONDS + 1
        self.assertEqual(photos.photo('senado:9', fetch=self.fetch(TimeoutError()), now=stale_time, cache_dir=self.folder), JPEG)

    def test_download_rejects_other_hosts_types_and_oversized_files(self):
        def response(url, content_type, body):
            fake = mock.MagicMock()
            fake.__enter__.return_value = fake
            fake.geturl.return_value = url
            fake.headers = {'Content-Type': content_type}
            fake.read.side_effect = lambda limit: body[:limit]
            return fake
        cases = [
            (response('https://legis.senado.leg.br/senadores/fotos-oficiais/5672', 'image/jpeg', JPEG), JPEG),
            (response('https://evil.test/x.jpg', 'image/jpeg', JPEG), None),
            (response('https://www.camara.leg.br/x.jpg', 'text/html', JPEG), None),
            (response('https://www.camara.leg.br/x.jpg', 'image/jpeg', JPEG + b'0' * photos.MAX_BYTES), None),
        ]
        for fake, expected in cases:
            with mock.patch('urllib.request.urlopen', return_value=fake):
                self.assertEqual(photos.download('https://www.camara.leg.br/x.jpg'), expected)


if __name__ == '__main__':
    unittest.main()
