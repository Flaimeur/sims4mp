# Tests de la mise a jour du mod depuis un manifeste (Release GitHub).
# Aucun acces a Internet ni au vrai dossier Mods : faux opener en memoire,
# serveur HTTP local sur 127.0.0.1, dossiers temporaires.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_update.py -v

import hashlib
import http.server
import io
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as gui  # noqa: E402

MANIFEST_URL = 'https://example.invalid/releases/latest/download/sims4mp_manifest.json'
MOD_URL = 'https://example.invalid/releases/download/v0.5.0/sims4mp_hello.ts4script'


def mod_bytes(version='0.5.0', filler=b'\x00'):
    # Faux .ts4script : un zip avec un "pyc" contenant la chaine marshal de la version.
    payload = b'\x00' * 16 + b'\xda' + bytes([len(version)]) + version.encode() + filler * 64
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr('sims4mp_hello.pyc', payload)
    return buffer.getvalue()


def manifest_for(data, **changes):
    manifest = {'version': '0.5.0', 'fichier': gui.MOD_FILE, 'url': MOD_URL,
                'sha256': hashlib.sha256(data).hexdigest(), 'taille': len(data), 'statut': 'stable'}
    manifest.update(changes)
    return manifest


class FakeResponse(io.BytesIO):
    def __init__(self, data, length=True):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data))} if length else {}


class FakeOpener:
    """Opener en memoire : url -> bytes ou exception. Note les URL demandees."""

    def __init__(self, routes):
        self.routes = routes
        self.requested = []

    def open(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        value = self.routes.get(url)
        if value is None:
            raise urllib.error.URLError('hote introuvable')
        if isinstance(value, Exception):
            raise value
        return FakeResponse(value)


def json_bytes(obj):
    import json
    return json.dumps(obj).encode('utf-8')


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_update_test_'))
        patcher = mock.patch.object(gui, 'base_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)


# --- Validation ---------------------------------------------------------------

class ManifestValidationTest(unittest.TestCase):
    def test_valid(self):
        data = mod_bytes()
        m = gui.validate_manifest(manifest_for(data, sha256=hashlib.sha256(data).hexdigest().upper()))
        self.assertEqual(m['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(m['statut'], 'stable')

    def test_invalid(self):
        data = mod_bytes()
        good = manifest_for(data)
        cases = {
            'cle manquante': {k: v for k, v in good.items() if k != 'sha256'},
            'cle en trop': dict(good, notes='x'),
            'version': dict(good, version='0.5'),
            'version texte': dict(good, version='latest'),
            'autre fichier': dict(good, fichier='autre.ts4script'),
            'chemin': dict(good, fichier='..\\..\\sims4mp_hello.ts4script'),
            'url http': dict(good, url='http://example.invalid/mod.ts4script'),
            'url file': dict(good, url='file:///C:/Windows/win.ini'),
            'url identifiants': dict(good, url='https://user:pass@example.invalid/m'),
            'sha court': dict(good, sha256='abc'),
            'sha non hex': dict(good, sha256='z' * 64),
            'taille zero': dict(good, taille=0),
            'taille trop grande': dict(good, taille=gui.MAX_MOD_SIZE + 1),
            'taille texte': dict(good, taille='37429'),
            'taille bool': dict(good, taille=True),
            'statut': dict(good, statut='beta'),
            'liste': [good],
        }
        for name, manifest in cases.items():
            with self.assertRaises(gui.LauncherError, msg=name):
                gui.validate_manifest(manifest)

    def test_require_https(self):
        self.assertEqual(gui.require_https(' https://github.com/x '), 'https://github.com/x')
        for url in ['http://github.com/x', 'ftp://h/x', 'file:///C:/x', 'https://', 'github.com/x', '', None]:
            with self.assertRaises(gui.LauncherError, msg=repr(url)):
                gui.require_https(url)


class HttpsOnlyTest(unittest.TestCase):
    def test_redirect_to_http_refused(self):
        handler = gui.HTTPSOnlyRedirectHandler()
        req = urllib.request.Request('https://github.com/a')
        with self.assertRaisesRegex(gui.LauncherError, 'HTTPS obligatoire'):
            handler.redirect_request(req, None, 302, 'Found', {}, 'http://evil.invalid/a')
        new = handler.redirect_request(req, None, 302, 'Found', {}, 'https://objects.githubusercontent.com/a')
        self.assertEqual(new.full_url, 'https://objects.githubusercontent.com/a')

    def test_opener_cannot_open_http_or_file(self):
        opener = gui.make_https_opener()
        for url in ['http://127.0.0.1:9/x', 'file:///C:/Windows/win.ini']:
            with self.assertRaises(urllib.error.URLError, msg=url):
                opener.open(url, timeout=1)


# --- Telechargement sur un vrai serveur HTTP local -----------------------------

class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b'A' * 1000
        if self.path == '/ok':
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/gros-annonce':
            self.send_response(200)
            self.send_header('Content-Length', str(10 * 1024 * 1024))
            self.end_headers()
        elif self.path == '/gros-sans-taille':
            self.send_response(200)
            self.end_headers()
            try:
                for _ in range(40):
                    self.wfile.write(b'B' * 1024)
            except OSError:
                pass            # le client coupe volontairement apres la limite
        elif self.path == '/lent':
            self.send_response(200)
            self.end_headers()
            try:
                for _ in range(20):
                    self.wfile.write(b'C')
                    self.wfile.flush()
                    time.sleep(0.2)
            except OSError:
                pass
        else:
            self.send_error(404)


class LocalServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        cls.server.daemon_threads = True
        cls.base = 'http://127.0.0.1:{}'.format(cls.server.server_address[1])
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        # Opener HTTP pour le test uniquement : le vrai lanceur n'ouvre que HTTPS.
        cls.opener = urllib.request.build_opener()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def fetch(self, path, max_size=8 * 1024, timeout=5):
        out = io.BytesIO()
        size = gui.read_limited(self.base + path, out, max_size, timeout, self.opener)
        return size, out.getvalue()

    def test_ok(self):
        self.assertEqual(self.fetch('/ok'), (1000, b'A' * 1000))

    def test_announced_too_big(self):
        with self.assertRaisesRegex(gui.LauncherError, 'trop gros'):
            self.fetch('/gros-annonce')

    def test_stream_too_big_without_length(self):
        with self.assertRaisesRegex(gui.LauncherError, 'trop gros'):
            self.fetch('/gros-sans-taille', max_size=10 * 1024)

    def test_total_timeout(self):
        start = time.monotonic()
        with self.assertRaisesRegex(gui.LauncherError, 'trop long'):
            self.fetch('/lent', timeout=1)
        self.assertLess(time.monotonic() - start, 3)

    def test_http_error(self):
        with self.assertRaisesRegex(gui.LauncherError, 'HTTP 404'):
            self.fetch('/absent')

    def test_connection_refused(self):
        with self.assertRaisesRegex(gui.LauncherError, 'Telechargement impossible'):
            gui.read_limited('http://127.0.0.1:9/x', io.BytesIO(), 1024, 2, self.opener)


# --- Flux complet (sans reseau) ---------------------------------------------------

class UpdateFlowTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.documents = self.tmp / 'Documents'
        self.mods = self.documents / 'Electronic Arts' / 'Les\u00a0Sims\u00a04' / 'Mods'
        self.mods.mkdir(parents=True)
        (self.mods / 'Resource.cfg').write_text('Priority 500\n')
        self.backups = self.tmp / gui.BACKUP_DIR_NAME
        self.downloads = self.tmp / 'launcher'
        self.downloads.mkdir()
        self.old = mod_bytes('0.4.0')
        (self.mods / gui.MOD_FILE).write_bytes(self.old)
        self.new = mod_bytes('0.5.0')

    def update(self, manifest, mod=None, running=False, allow_test=False, url=MANIFEST_URL,
               allow_downgrade=False):
        routes = {MANIFEST_URL: manifest if isinstance(manifest, bytes) else json_bytes(manifest)}
        routes[MOD_URL] = self.new if mod is None else mod
        self.opener = FakeOpener(routes)
        return gui.run_update(url, self.documents, self.backups, self.downloads,
                              allow_test=allow_test, is_running=lambda: running, opener=self.opener,
                              allow_downgrade=allow_downgrade)

    def assert_mods_unchanged(self):
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.old)
        self.assertEqual(sorted(p.name for p in self.mods.iterdir()), ['Resource.cfg', gui.MOD_FILE])
        self.assertEqual(list(self.downloads.iterdir()), [])     # aucun fichier temporaire restant

    def test_success_with_backup(self):
        lines, summary = self.update(manifest_for(self.new))
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.new)
        backups = list(self.backups.iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.old)
        self.assertEqual(summary, 'Mod mis à jour (0.5.0)')
        self.assertEqual(sorted(p.name for p in self.mods.iterdir()), ['Resource.cfg', gui.MOD_FILE])
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_already_up_to_date(self):
        lines, summary = self.update(manifest_for(self.old, version='0.4.0'))
        self.assertTrue(summary.startswith('Déjà à jour'))
        self.assertNotIn(MOD_URL, self.opener.requested)                 # pas de telechargement du mod
        self.assertFalse(self.backups.exists())

    def test_test_status_refused_by_default(self):
        with self.assertRaisesRegex(gui.LauncherError, 'version de test'):
            self.update(manifest_for(self.new, statut='test'))
        self.assertEqual(self.opener.requested, [MANIFEST_URL])
        self.assert_mods_unchanged()

    def test_test_status_accepted_when_checked(self):
        lines, _ = self.update(manifest_for(self.new, statut='test'), allow_test=True)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.new)
        self.assertIn('(version de test)', lines[-1])

    def test_wrong_sha256(self):
        with self.assertRaisesRegex(gui.LauncherError, 'SHA-256 incorrect'):
            self.update(manifest_for(self.new, sha256='0' * 64))
        self.assert_mods_unchanged()

    def test_size_mismatch(self):
        with self.assertRaisesRegex(gui.LauncherError, 'trop gros|Taille incorrecte'):
            self.update(manifest_for(self.new, taille=len(self.new) - 10))
        self.assert_mods_unchanged()
        with self.assertRaisesRegex(gui.LauncherError, 'Taille incorrecte'):
            self.update(manifest_for(self.new, taille=len(self.new) + 10))
        self.assert_mods_unchanged()

    def test_manifest_too_big_size_refused(self):
        with self.assertRaisesRegex(gui.LauncherError, 'taille'):
            self.update(manifest_for(self.new, taille=6 * 1024 * 1024))
        self.assertEqual(self.opener.requested, [MANIFEST_URL])
        self.assert_mods_unchanged()

    def test_invalid_manifest(self):
        for bad in [b'pas du json', b'\xff\xfe', json_bytes({'version': '0.5.0'}),
                    json_bytes(manifest_for(self.new, url='http://example.invalid/m'))]:
            with self.assertRaises(gui.LauncherError, msg=bad[:30]):
                self.update(bad)
            self.assert_mods_unchanged()

    def test_manifest_url_not_https_or_not_configured(self):
        for url in ['À_REMPLIR', '', 'http://example.invalid/m.json', 'file:///C:/m.json']:
            with self.assertRaises(gui.LauncherError, msg=url):
                self.update(manifest_for(self.new), url=url)
            self.assert_mods_unchanged()

    def test_download_failure(self):
        with self.assertRaisesRegex(gui.LauncherError, 'Telechargement impossible'):
            self.update(manifest_for(self.new), mod=urllib.error.URLError('connexion coupee'))
        self.assert_mods_unchanged()
        self.assertFalse(self.backups.exists())

    def test_manifest_unreachable(self):
        self.opener = FakeOpener({})
        with self.assertRaisesRegex(gui.LauncherError, 'Telechargement impossible'):
            gui.run_update(MANIFEST_URL, self.documents, self.backups, self.downloads,
                           is_running=lambda: False, opener=self.opener)
        self.assert_mods_unchanged()

    def test_game_running(self):
        with self.assertRaisesRegex(gui.LauncherError, 'Fermez Les Sims 4'):
            self.update(manifest_for(self.new), running=True)
        self.assertNotIn(MOD_URL, self.opener.requested)
        self.assert_mods_unchanged()

    def test_game_started_during_download(self):
        calls = []

        def running():
            calls.append(1)
            return len(calls) > 1          # libre avant, lance apres le telechargement
        self.opener = FakeOpener({MANIFEST_URL: json_bytes(manifest_for(self.new)), MOD_URL: self.new})
        with self.assertRaisesRegex(gui.LauncherError, 'Fermez Les Sims 4'):
            gui.run_update(MANIFEST_URL, self.documents, self.backups, self.downloads,
                           is_running=running, opener=self.opener)
        self.assert_mods_unchanged()

    def test_version_mismatch_in_file(self):
        with self.assertRaisesRegex(gui.LauncherError, 'Version incoherente'):
            self.update(manifest_for(self.new, version='0.6.0'))
        self.assert_mods_unchanged()

    def test_not_a_zip(self):
        junk = b'MZ' + b'\x00' * 500
        with self.assertRaisesRegex(gui.LauncherError, 'archive'):
            self.update(manifest_for(junk), mod=junk)
        self.assert_mods_unchanged()

    def test_version_tuple(self):
        self.assertEqual(gui.version_tuple('0.10.2'), (0, 10, 2))
        self.assertGreater(gui.version_tuple('0.10.0'), gui.version_tuple('0.9.9'))
        for bad in ['inconnue', '0.4', '', None, '1.2.3.4']:
            self.assertIsNone(gui.version_tuple(bad), msg=repr(bad))

    def test_downgrade_refused_by_default(self):
        older = mod_bytes('0.3.0')
        with self.assertRaisesRegex(gui.LauncherError, 'plus ancienne'):
            self.update(manifest_for(older, version='0.3.0'), mod=older)
        self.assertEqual(self.opener.requested, [MANIFEST_URL])       # rien telecharge
        self.assert_mods_unchanged()
        self.assertFalse(self.backups.exists())

    def test_downgrade_refused_even_for_test_status(self):
        older = mod_bytes('0.3.0')
        with self.assertRaisesRegex(gui.LauncherError, 'plus ancienne'):
            self.update(manifest_for(older, version='0.3.0', statut='test'), mod=older, allow_test=True)
        self.assert_mods_unchanged()

    def test_downgrade_accepted_when_checked(self):
        older = mod_bytes('0.3.0')
        lines, _ = self.update(manifest_for(older, version='0.3.0'), mod=older, allow_downgrade=True)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), older)
        self.assertEqual(next(self.backups.iterdir()).read_bytes(), self.old)
        self.assertIn('Version installee : 0.4.0', lines)

    def test_same_version_different_file_allowed(self):
        rebuilt = mod_bytes('0.4.0', filler=b'\x01')    # meme version, contenu different
        self.assertNotEqual(rebuilt, self.old)
        self.update(manifest_for(rebuilt, version='0.4.0'), mod=rebuilt)
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), rebuilt)

    def test_unreadable_installed_version_allows_update(self):
        (self.mods / gui.MOD_FILE).write_bytes(b'pas un zip')
        lines, _ = self.update(manifest_for(self.new))
        self.assertIn('illisible', ' '.join(lines))
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.new)

    def test_no_installed_mod(self):
        (self.mods / gui.MOD_FILE).unlink()
        self.update(manifest_for(self.new))
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.new)
        self.assertFalse(self.backups.exists())

    def test_copy_failure_keeps_old_mod(self):
        real_copy2 = shutil.copy2

        def failing_copy(src, dst):
            if str(dst).endswith('.part'):
                Path(dst).write_bytes(b'partiel')
                raise OSError('disque plein')
            return real_copy2(src, dst)
        with mock.patch.object(gui.shutil, 'copy2', failing_copy):
            with self.assertRaises(OSError):
                self.update(manifest_for(self.new))
        self.assert_mods_unchanged()


ICONS_MANIFEST_URL = 'https://example.invalid/releases/latest/download/sims4mp_icons_manifest.json'
ICONS_URL = 'https://example.invalid/releases/download/v0.16.0/sims4mp_icons.package'


def icons_bytes(filler=b'\x00'):
    return b'DBPF\x02\x00\x00\x00\x01\x00\x00\x00' + filler * 84


def icons_manifest_for(data, **changes):
    manifest = {'fichier': gui.ICONS_FILE, 'url': ICONS_URL,
                'sha256': hashlib.sha256(data).hexdigest(), 'taille': len(data)}
    manifest.update(changes)
    return manifest


class IconsUpdateTest(UpdateFlowTest):
    """Second manifeste (icone de la roue) : le manifeste du mod ne change pas."""

    def update_with_icons(self, icons_manifest, icons=None, mod_manifest=None, running=False):
        self.icons = icons_bytes() if icons is None else icons
        routes = {MANIFEST_URL: json_bytes(mod_manifest or manifest_for(self.new)), MOD_URL: self.new,
                  ICONS_MANIFEST_URL: (icons_manifest if isinstance(icons_manifest, Exception)
                                       else json_bytes(icons_manifest)),
                  ICONS_URL: self.icons}
        self.opener = FakeOpener(routes)
        return gui.run_update(MANIFEST_URL, self.documents, self.backups, self.downloads,
                              is_running=lambda: running, opener=self.opener)

    def test_icons_manifest_url_next_to_mod_manifest(self):
        self.assertEqual(gui.icons_manifest_url(MANIFEST_URL), ICONS_MANIFEST_URL)
        self.assertEqual(gui.icons_manifest_url(
            'https://github.com/a/b/releases/download/v0.16.0/sims4mp_manifest.json'),
            'https://github.com/a/b/releases/download/v0.16.0/sims4mp_icons_manifest.json')

    def test_mod_and_icons_installed(self):
        lines, summary = self.update_with_icons(icons_manifest_for(icons_bytes()))
        self.assertEqual((self.mods / gui.MOD_FILE).read_bytes(), self.new)
        self.assertEqual((self.mods / gui.ICONS_FILE).read_bytes(), self.icons)
        self.assertIn('Icone copiee', ' '.join(lines))
        self.assertEqual(summary, 'Mod mis à jour (0.5.0)')
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_icons_already_installed_not_downloaded(self):
        (self.mods / gui.ICONS_FILE).write_bytes(icons_bytes())
        lines, _ = self.update_with_icons(icons_manifest_for(icons_bytes()))
        self.assertNotIn(ICONS_URL, self.opener.requested)
        self.assertIn('Icone deja installee', ' '.join(lines))

    def test_icons_added_when_mod_already_up_to_date(self):
        (self.mods / gui.MOD_FILE).write_bytes(self.new)
        lines, summary = self.update_with_icons(icons_manifest_for(icons_bytes()))
        self.assertTrue(summary.startswith('Déjà à jour'))
        self.assertEqual((self.mods / gui.ICONS_FILE).read_bytes(), self.icons)

    def test_old_release_without_icons(self):
        missing = urllib.error.HTTPError(ICONS_MANIFEST_URL, 404, 'Not Found', {}, None)
        lines, summary = self.update_with_icons(missing)
        self.assertEqual(summary, 'Mod mis à jour (0.5.0)')
        self.assertIn('aucune dans cette release', ' '.join(lines))
        self.assertFalse((self.mods / gui.ICONS_FILE).exists())

    def test_bad_icons_never_block_the_mod(self):
        for icons_manifest, icons in [(icons_manifest_for(icons_bytes(), sha256='0' * 64), None),
                                      (icons_manifest_for(b'pas un package'), b'pas un package'),
                                      (icons_manifest_for(icons_bytes(), url='http://example.invalid/i'), None),
                                      (icons_manifest_for(icons_bytes(), fichier='autre.package'), None),
                                      (icons_manifest_for(icons_bytes(), taille=2 * 1024 * 1024), None),
                                      (dict(icons_manifest_for(icons_bytes()), extra=1), None)]:
            (self.mods / gui.MOD_FILE).write_bytes(self.old)
            lines, summary = self.update_with_icons(icons_manifest, icons)
            self.assertEqual(summary, 'Mod mis à jour (0.5.0)', msg=icons_manifest)
            self.assertIn('ATTENTION : icone non installee', ' '.join(lines), msg=icons_manifest)
            self.assertFalse((self.mods / gui.ICONS_FILE).exists(), msg=icons_manifest)
            self.assertEqual(list(self.downloads.iterdir()), [])

    def test_old_icons_backed_up_outside_mods(self):
        (self.mods / gui.ICONS_FILE).write_bytes(icons_bytes(b'\x01'))
        self.update_with_icons(icons_manifest_for(icons_bytes()))
        self.assertEqual((self.mods / gui.ICONS_FILE).read_bytes(), icons_bytes())
        saved = [p for p in self.backups.iterdir() if p.suffix == '.package']
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), icons_bytes(b'\x01'))
        self.assertEqual(sorted(p.name for p in self.mods.iterdir()),
                         sorted(['Resource.cfg', gui.MOD_FILE, gui.ICONS_FILE]))

    def test_local_install_copies_icons_next_to_mod(self):
        source_dir = self.tmp / 'build'
        source_dir.mkdir()
        (source_dir / gui.MOD_FILE).write_bytes(self.new)
        (source_dir / gui.ICONS_FILE).write_bytes(icons_bytes())
        lines = gui.run_install(source_dir / gui.MOD_FILE, self.documents, self.backups, is_running=lambda: False)
        self.assertEqual((self.mods / gui.ICONS_FILE).read_bytes(), icons_bytes())
        self.assertIn('Icone copiee', ' '.join(lines))


class UpdateWindowTest(TempDirTest):
    def test_checkbox_and_unconfigured_url(self):
        import tkinter as tk
        (self.tmp / 'Electronic Arts').mkdir()
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = gui.LauncherApp(root, documents=self.tmp)
        self.assertFalse(app.allow_test.get())
        self.assertFalse(app.allow_downgrade.get())
        # Navigation : une seule entree active a la fois.
        app._show_page('mod')
        styles = {key: str(button.cget('style')) for key, (bar, button) in app.nav.items()}
        self.assertEqual(styles, {'accueil': 'Nav.TButton', 'connexion': 'Nav.TButton', 'mod': 'NavActive.TButton',
                                  'outils': 'Nav.TButton', 'options': 'Nav.TButton'})
        self.assertEqual(gui.MANIFEST_URL, 'À_REMPLIR')
        app._update_worker()                     # synchrone, sans thread
        app._poll_install()
        self.assertEqual(str(app.status.cget('style')), 'StatusError.TLabel')
        self.assertIn('non configuree', app.status.cget('text'))
        self.assertEqual(str(app.update_button.cget('state')), 'normal')

    def test_mod_choices_kept_between_openings(self):
        import tkinter as tk
        (self.tmp / 'Electronic Arts').mkdir()
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = gui.LauncherApp(root, documents=self.tmp)
        self.assertFalse(gui.prefs_path().exists())             # rien d'ecrit a l'ouverture
        app.allow_test.set(True)                                 # comme un clic sur la case
        self.assertEqual(gui.read_prefs(gui.prefs_path()), {'version_test': True, 'retour_arriere': False})
        self.assertEqual(app.status.cget('text'), 'Choix enregistré')
        app.allow_downgrade.set(True)
        app.allow_test.set(False)
        # Nouvelle ouverture du lanceur : les cases reprennent les derniers choix.
        second = tk.Toplevel(root)
        reopened = gui.LauncherApp(second, documents=self.tmp)
        self.assertFalse(reopened.allow_test.get())
        self.assertTrue(reopened.allow_downgrade.get())
        self.assertEqual(gui.read_prefs(gui.prefs_path()), {'version_test': False, 'retour_arriere': True})


RELEASES_URL = 'https://api.github.com/repos/Flaimeur/sims4mp/releases?per_page=30'


class ReleaseTagsTest(unittest.TestCase):
    def releases(self, data):
        opener = FakeOpener({RELEASES_URL: data if isinstance(data, bytes) else json_bytes(data)})
        return gui.fetch_release_tags('Flaimeur/sims4mp', opener), opener

    def test_tags_listed_newest_first_with_status_and_date(self):
        tags, opener = self.releases([
            {'tag_name': 'v0.17.0', 'prerelease': True, 'draft': False, 'published_at': '2026-10-23T19:40:00Z'},
            {'tag_name': 'v0.16.1', 'prerelease': False, 'draft': False, 'published_at': '2026-10-23T18:00:00Z'},
            {'tag_name': 'brouillon', 'prerelease': True, 'draft': True, 'published_at': None},
            {'tag_name': '../piege', 'prerelease': False},
            {'tag_name': 42}, 'pas un objet',
            {'tag_name': 'v0.1.0', 'prerelease': False, 'published_at': 'date bizarre'}])
        self.assertEqual(opener.requested, [RELEASES_URL])
        self.assertEqual(tags, [{'tag': 'v0.17.0', 'statut': 'test', 'date': '2026-10-23'},
                                {'tag': 'v0.16.1', 'statut': 'stable', 'date': '2026-10-23'},
                                {'tag': 'v0.1.0', 'statut': 'stable', 'date': ''}])
        self.assertEqual(gui.tag_label(tags[0]), 'v0.17.0 · test · 23/10/2026')
        self.assertEqual(gui.tag_label(tags[2]), 'v0.1.0 · stable')

    def test_bad_answers_refused(self):
        for bad in [b'pas du json', json_bytes({'message': 'API rate limit exceeded'})]:
            with self.assertRaises(gui.LauncherError, msg=bad[:20]):
                self.releases(bad)
        with self.assertRaises(ValueError):
            gui.fetch_release_tags('pas un depot', FakeOpener({}))


class TagsWindowTest(TempDirTest):
    def test_menu_save_and_check(self):
        import tkinter as tk
        (self.tmp / 'Electronic Arts').mkdir()
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = gui.LauncherApp(root, documents=self.tmp)
        app.repo.set('Flaimeur/sims4mp')
        app.tag_mode.set('tag')
        app._on_tag_mode()
        self.assertEqual(str(app.tags_button.cget('state')), 'normal')
        app._fill_tags('Flaimeur/sims4mp', [{'tag': 'v0.17.0', 'statut': 'test', 'date': '2026-10-23'}])
        self.assertEqual(list(app.tag_entry.cget('values')), ['v0.17.0 · test · 23/10/2026'])
        app.tag.set('v0.17.0 · test · 23/10/2026')                # choix dans le menu
        app._on_tag_selected()
        self.assertEqual(app.tag.get(), 'v0.17.0')
        checked = []
        app._check_manifest = lambda: checked.append(app.tag.get())
        app._save_config()
        self.assertEqual(gui.read_config(gui.config_path()), {'depot': 'Flaimeur/sims4mp', 'tag': 'v0.17.0'})
        self.assertEqual(checked, ['v0.17.0'])                    # verification juste apres
        app.tag_mode.set('latest')
        app._on_tag_mode()
        self.assertEqual(str(app.tags_button.cget('state')), 'disabled')

    def test_invalid_form_not_saved_nor_checked(self):
        import tkinter as tk
        (self.tmp / 'Electronic Arts').mkdir()
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = gui.LauncherApp(root, documents=self.tmp)
        app.repo.set('pas un depot')
        checked = []
        app._check_manifest = lambda: checked.append(1)
        app._save_config()
        self.assertEqual(checked, [])
        self.assertFalse(gui.config_path().exists())


class PrefsTest(TempDirTest):
    def test_defaults_when_missing(self):
        self.assertEqual(gui.read_prefs(self.tmp / 'absent.json'), {'version_test': False, 'retour_arriere': False})

    def test_write_then_read(self):
        path = self.tmp / gui.PREFS_NAME
        gui.write_prefs(path, {'version_test': True})
        self.assertEqual(gui.read_prefs(path), {'version_test': True, 'retour_arriere': False})

    def test_invalid_refused(self):
        path = self.tmp / gui.PREFS_NAME
        for bad in ['pas du json', '[]', '{"version_test": "oui"}', '{"autre": true}', '{"version_test": 1}']:
            path.write_text(bad, encoding='utf-8')
            with self.assertRaises(ValueError, msg=bad):
                gui.read_prefs(path)

    def test_config_file_unchanged(self):
        # Les options GitHub gardent leurs deux cles : un ancien lanceur les lit toujours.
        self.assertEqual(gui.CONFIG_KEYS, {'depot', 'tag'})
        self.assertNotEqual(gui.PREFS_NAME, gui.CONFIG_NAME)

    def test_invalid_file_ignored_by_window(self):
        import tkinter as tk
        (self.tmp / 'Electronic Arts').mkdir()
        gui.prefs_path().write_text('{"version_test": "oui"}', encoding='utf-8')
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = gui.LauncherApp(root, documents=self.tmp)
        self.assertFalse(app.allow_test.get())
        app.allow_test.set(True)                                  # le fichier est reecrit proprement
        self.assertEqual(gui.read_prefs(gui.prefs_path()), {'version_test': True, 'retour_arriere': False})


if __name__ == '__main__':
    unittest.main()
