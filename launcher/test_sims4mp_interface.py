# Tests de l'interface du lanceur (etape 5) : Accueil, pastilles, journal en bas, page Mod
# (version a installer), page Outils (diagnostic lisible, mettre de cote, fichiers).
# Dossiers temporaires imitant « Les Sims 4 » (espaces insecables), aucun reseau.
#
# Lancer :  py -3.12 -m unittest launcher/test_sims4mp_interface.py -v

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sims4mp_launcher_gui as gui  # noqa: E402
from test_sims4mp_update import icons_bytes, mod_bytes  # noqa: E402

NBSP_GAME = 'Les Sims 4'
TAGS = [{'tag': 'v0.18.0', 'statut': 'test', 'date': '2026-10-25'},
        {'tag': 'v0.17.0', 'statut': 'stable', 'date': '2026-10-23'}]


class InterfaceTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tmp = Path(tempfile.mkdtemp(prefix='sims4mp_interface_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.object(gui, 'base_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.documents = self.tmp / 'Documents'
        self.mods = self.documents / 'Electronic Arts' / NBSP_GAME / 'Mods'
        self.mods.mkdir(parents=True)
        (self.mods / 'Resource.cfg').write_text('Priority 500\n')
        (self.mods / gui.MOD_FILE).write_bytes(mod_bytes('0.17.0'))
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        with mock.patch.object(gui, 'detect_game', return_value=gui.GameInstall('steam', self.tmp / 'x.exe')):
            self.app = gui.LauncherApp(self.root, documents=self.documents)

    def local(self, icons=False, running=False):
        if icons:
            (self.mods / gui.ICONS_FILE).write_bytes(icons_bytes())
        self.app._apply_background(('local', gui.installed_state(self.documents), running))

    def configure(self, tag=''):
        gui.write_config(gui.config_path(), {'depot': 'Flaimeur/sims4mp', 'tag': tag})

    # --- barre laterale et journal --------------------------------------------------------
    def test_sidebar_pages_badges_and_version(self):
        self.assertEqual(list(self.app.nav), ['accueil', 'connexion', 'mod', 'outils', 'options'])
        self.assertEqual(str(self.app.nav['accueil'][1].cget('style')), 'NavActive.TButton')   # page d'ouverture
        texts, stack = [], [self.root]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            try:
                texts.append(widget.cget('text'))
            except Exception:
                pass
        self.assertIn('lanceur {}'.format(gui.LAUNCHER_VERSION), texts)
        self.local()
        self.assertEqual(self.app.badges['mod'].cget('text'), '0.17.0')
        self.assertEqual(self.app.badges['connexion'].cget('text'), 'seul')
        self.app._fill_tags('Flaimeur/sims4mp', TAGS)
        self.app.allow_test.set(True)
        self.app._refresh_badges()
        self.assertEqual(self.app.badges['mod'].cget('text'), 'v0.18.0 dispo')
        self.assertEqual(str(self.app.badges['mod'].cget('style')), 'BadgeWarn.TLabel')
        self.app.allow_test.set(False)                          # la 0.18.0 est une version de test
        self.app._refresh_badges()
        self.assertEqual(self.app.badges['mod'].cget('text'), '0.17.0')

    def test_journal_fold_copy_clear(self):
        self.app.show('ligne de test')
        self.app._copy_journal()
        self.assertIn('ligne de test', self.root.clipboard_get())
        self.app._toggle_journal()
        self.assertEqual(self.app.journal_body.winfo_manager(), '')
        self.assertEqual(self.app.journal_toggle.cget('text'), 'Journal ▸')
        self.app._toggle_journal()
        self.assertEqual(self.app.journal_body.winfo_manager(), 'pack')
        self.app._clear_journal()
        self.assertEqual(self.app.messages.get('1.0', 'end').strip(), '')

    # --- Accueil ---------------------------------------------------------------------------
    def test_home_cards(self):
        self.local(icons=True)
        self.app._fill_tags('Flaimeur/sims4mp', TAGS)
        cards = self.app.home_cards
        self.assertEqual(cards['mod']['installed'].cget('text'), '0.17.0')
        self.assertEqual(cards['mod']['icons'].cget('text'), 'installée')
        self.assertEqual(cards['mod']['latest'].cget('text'), 'v0.17.0 (stable) · 23/10/2026')
        self.assertEqual(cards['game']['kind'].cget('text'), 'Steam')
        self.assertEqual(cards['game']['running'].cget('text'), 'fermé')
        self.assertEqual(cards['game']['mods'].cget('text'), 'trouvé (Resource.cfg)')
        self.assertEqual(cards['party']['room'].cget('text'), 'aucune')
        self.assertEqual(self.app.status.cget('text'), 'Tout est prêt pour jouer')
        self.app.allow_test.set(True)                           # « Choix enregistré » dans la barre d'etat
        self.app._refresh_home()
        self.assertEqual(self.app.home_update_button.cget('text'), 'Mettre à jour vers v0.18.0')
        self.assertEqual(self.app.status.cget('text'), 'Choix enregistré')   # un vrai message n'est pas ecrase
        self.app.set_status('Prêt')
        self.app._refresh_home()
        self.assertEqual(self.app.status.cget('text'), 'Nouvelle version disponible')

    def test_home_mod_missing_and_game_open(self):
        (self.mods / gui.MOD_FILE).unlink()
        self.local(running=True)
        self.assertEqual(self.app.home_cards['mod']['installed'].cget('text'), 'aucun')
        self.assertEqual(self.app.home_cards['mod']['icons'].cget('text'), 'absente')
        self.assertEqual(self.app.home_cards['game']['running'].cget('text'), 'ouvert')
        self.assertEqual(self.app.badges['mod'].cget('text'), 'absent')

    def test_home_party_buttons_open_party_page(self):
        self.app._go_party(gui.ROLE_JOIN)
        self.assertEqual(self.app.role.get(), gui.ROLE_JOIN)
        self.assertEqual(str(self.app.nav['connexion'][1].cget('style')), 'NavActive.TButton')

    # --- page Mod : version a installer --------------------------------------------------
    def test_install_target(self):
        self.assertEqual(self.app._install_target(), (gui.MANIFEST_URL, None))     # depot non configure
        self.configure()
        self.app._fill_tags('Flaimeur/sims4mp', TAGS)
        url, tag = self.app._install_target()
        self.assertEqual(tag, 'v0.17.0')                       # derniere stable (case test decochee)
        self.assertEqual(url, gui.manifest_url_for('Flaimeur/sims4mp', 'v0.17.0'))
        self.assertEqual(self.app.update_button.cget('text'), 'Installer v0.17.0')
        self.app.allow_test.set(True)
        self.assertEqual(self.app._install_target()[1], 'v0.18.0')
        self.assertEqual(self.app.update_button.cget('text'), 'Installer v0.18.0')
        self.assertEqual(self.app.mod_target_label.cget('text'), 'v0.18.0 (test) · 25/10/2026')
        self.app.version_choice.set('v0.17.0 · stable · 23/10/2026')                  # choix dans le menu
        self.app._refresh_mod_page()
        self.assertEqual(self.app._install_target()[1], 'v0.17.0')
        self.assertEqual(list(self.app.version_box.cget('values'))[0], gui.LATEST_CHOICE)

    def test_install_uses_chosen_version(self):
        self.configure()
        self.app._fill_tags('Flaimeur/sims4mp', TAGS)
        seen = []
        with mock.patch.object(gui, 'run_update', lambda url, *a, **k: seen.append(url) or (['ok'], 'ok')), \
                mock.patch.object(self.app, '_spawn', lambda worker: worker()):
            self.app._update()
        self.assertEqual(seen, [gui.manifest_url_for('Flaimeur/sims4mp', 'v0.17.0')])

    # --- page Outils -----------------------------------------------------------------------
    def test_diagnostic_shown_as_checks(self):
        copy = self.mods / 'vieux' / 'sims4mp_hello.ts4script'
        lines = ['Mod : present, version 0.17.0',
                 gui.CHECK_REMINDER + 'icone de la roue absente',
                 'ATTENTION : autre copie du mod : {}'.format(copy),
                 'Resultat : 1 point(s) a verifier.']
        self.app._show_diagnostic(lines)
        rows = {}
        for widget in self.app.diag_list.grid_slaves():
            rows.setdefault(int(widget.grid_info()['row']), {})[int(widget.grid_info()['column'])] = widget
        self.assertEqual(len(rows), 3)                          # la ligne « Resultat » n'est pas montree
        self.assertEqual([rows[r][0].cget('text') for r in sorted(rows)], ['✔', '⚠', '✖'])
        self.assertEqual(rows[2][2].cget('text'), 'Mettre de côté')
        self.assertEqual(self.app.badges['outils'].cget('text'), '1')

    def test_set_aside_copy(self):
        copy = self.mods / 'vieux' / 'sims4mp_hello.ts4script'
        copy.parent.mkdir()
        copy.write_bytes(mod_bytes('0.4.0'))
        backups = self.tmp / gui.BACKUP_DIR_NAME
        target = gui.set_aside_copy(copy, self.mods, backups, is_running=lambda: False)
        self.assertFalse(copy.exists())
        self.assertEqual(target.parent, backups / gui.SET_ASIDE_DIR)
        self.assertEqual(target.read_bytes(), mod_bytes('0.4.0'))
        other = self.mods / 'autre.package'
        other.write_bytes(b'x')
        for path in (other, self.mods / gui.MOD_FILE, self.tmp / 'sims4mp_hello_dehors.ts4script'):
            with self.assertRaises(gui.LauncherError, msg=path):
                gui.set_aside_copy(path, self.mods, backups, is_running=lambda: False)
        copy.write_bytes(b'x')
        with self.assertRaisesRegex(gui.LauncherError, 'Fermez'):
            gui.set_aside_copy(copy, self.mods, backups, is_running=lambda: True)

    def test_set_aside_from_window_needs_confirmation(self):
        copy = self.mods / 'vieux' / 'sims4mp_hello.ts4script'
        copy.parent.mkdir()
        copy.write_bytes(mod_bytes('0.4.0'))
        with mock.patch.object(self.app, '_confirm', return_value=False):
            self.app._set_aside(str(copy))
        self.assertTrue(copy.exists())
        with mock.patch.object(self.app, '_confirm', return_value=True), \
                mock.patch.object(gui, 'game_is_running', lambda: False), \
                mock.patch.object(self.app, '_diagnostic'):
            self.app._set_aside(str(copy))
        self.assertFalse(copy.exists())
        self.assertEqual(self.app.status.cget('text'), 'Ancienne copie du mod mise de côté')

    def test_diagnostic_extra_lines(self):
        copy = self.mods / 'vieux' / 'sims4mp_hello.ts4script'
        copy.parent.mkdir()
        copy.write_bytes(mod_bytes('0.4.0'))
        lines, summary = gui.run_diagnostic(
            self.documents, is_running=lambda: False, list_ips=lambda: ['192.168.1.20'],
            listeners=lambda port: [], proc_name=lambda pid: 'x', firewall=lambda: [('Privé', 'Actif')],
            probe=lambda ip, port: (True, 'Joignable'))
        self.assertIn(gui.CHECK_REMINDER + 'icone de la roue absente : page Mod → Installer pour l\'ajouter', lines)
        self.assertIn('ATTENTION : autre copie du mod : {}'.format(copy), lines)
        self.assertTrue(any(line.startswith(gui.CHECK_REMINDER + 'mods de script') for line in lines))
        self.assertIn('2 point(s)', summary)                   # copie + aucun reglage ; les rappels ne comptent pas

    def test_copy_mod_log_tail(self):
        (self.mods / gui.MOD_LOG_NAME).write_text('\n'.join('ligne {}'.format(i) for i in range(500)),
                                                  encoding='utf-8')
        self.app._copy_mod_log()
        copied = self.root.clipboard_get().splitlines()
        self.assertEqual(len(copied), gui.COPY_TAIL_LINES)
        self.assertEqual(copied[-1], 'ligne 499')
        self.app._open_mod_file(gui.MOD_REPORT_NAME)               # pas encore de rapport : message clair
        self.assertIn('introuvable', self.app.status.cget('text'))


if __name__ == '__main__':
    unittest.main()
