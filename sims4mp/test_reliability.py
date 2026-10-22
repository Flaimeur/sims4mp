# Sims 4 Multiplayer - test hors jeu de la phase C (0.13.0) : seul l'hote sauvegarde,
# resynchro complete, detecteur d'ecarts, journal lisible. Compatible Python 3.7.
# A lancer avec :  py -3.7 test_reliability.py

import os
import shutil
import sys
import tempfile
import types


def module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


class _CheatOutput(object):
    lines = []

    def __init__(self, connection):
        pass

    def __call__(self, text):
        _CheatOutput.lines.append(text)


commands = module('sims4.commands', Command=lambda *a, **k: (lambda f: f),
                  CommandType=types.SimpleNamespace(Live='Live'), CheatOutput=_CheatOutput)
localization = module('sims4.localization',
                      LocalizationHelperTuning=types.SimpleNamespace(get_raw_text=lambda text: 'raw:' + text))
module('sims4', commands=commands, localization=localization)


class _Zone(object):
    def update(self, *args):
        return 'update'

    def on_loading_screen_animation_finished(self):
        return 'loaded'


module('zone', Zone=_Zone)


class Persistence(object):
    def __init__(self):
        self.locks = []

    def lock_save(self, holder):
        self.locks.append(holder)

    def unlock_save(self, holder):
        self.locks.remove(holder)


PERSISTENCE = Persistence()
module('services', get_persistence_service=lambda: PERSISTENCE)

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import protocol  # noqa: E402
import sims4mp_hello as mod  # noqa: E402

results = []
notes = []
mod.show_notification = lambda title, text, *args: notes.append((title, text))
TMP = tempfile.mkdtemp(prefix='sims4mp_reliability_')
mod.LOG_PATH = os.path.join(TMP, 'sims4mp.log')


def report(step, ok, detail=''):
    results.append(bool(ok))
    print('[{}] {}{}'.format('OK' if ok else 'ECHEC', step, ' - ' + detail if detail else ''))


class Endpoint(object):
    def __init__(self):
        self.sent = []
        self.is_connected = True

    def send(self, message):
        self.sent.append(message)
        return True


def kinds(endpoint):
    return [m['data'].get('kind') for m in endpoint.sent if m['type'] == protocol.EVENT]


# --- 1. Seul l'hote sauvegarde ---------------------------------------------------------
guest = mod.NetSession('client', Endpoint())
host = mod.NetSession('host', Endpoint())
mod._save_lock_tick(host)
report('hote : sauvegarde jamais verrouillee', PERSISTENCE.locks == [])
mod._save_lock_tick(guest)
report('invite pas encore connecte : pas de verrou', PERSISTENCE.locks == [])
guest.handshake_done = True
mod._save_lock_tick(guest)
mod._save_lock_tick(guest)
holder = PERSISTENCE.locks[0] if PERSISTENCE.locks else None
report('invite connecte : sauvegarde verrouillee une fois, motif affiche par le jeu',
       len(PERSISTENCE.locks) == 1
       and holder.get_lock_save_reason() == 'raw:Partie à deux : seul l\'hôte sauvegarde la partie commune.'
       and any('Sauvegarde désactivée chez vous' in n[1] for n in notes))
mod._save_lock_tick(None)
report('fin de la partie a deux : sauvegarde deverrouillee', PERSISTENCE.locks == [] and mod._save_lock['holder'] is None)

# --- 2. Resynchro complete ----------------------------------------------------------------
mod._session = guest
del notes[:]
mod.request_resync()
report('invite : la resynchro est demandee a l\'hote', kinds(guest.endpoint)[-1] == 'resync_request'
       and 'Resynchronisation demandée' in notes[-1][1])
host.handshake_done = True
host.money_total_sent = True
host.needs_sent[1] = ({}, 0.0)
host.sims_sent[2] = {}
host.position_sent = {'sim_id': 1}
host.clock_sent_at = 99.0
mod.do_resync(host)
report('hote : tout est renvoye (argent, besoins, positions, heure) et l\'invite prevenu',
       not host.money_total_sent and host.needs_sent == {} and host.sims_sent == {} and host.position_sent is None
       and host.clock_sent_at == 0.0 and kinds(host.endpoint)[-1] == 'resync')
guest.money_aligned = True
guest.walk = {'x': 1}
guest.sims_walk[3] = {'x': 1}
guest.action_hold[3] = 1e9
guest.clock_grace_until = 1e9
mod._handle_resync(guest)
report('invite : realignement de l\'argent permis, marches et attentes remises a zero',
       not guest.money_aligned and guest.walk is None and guest.sims_walk == {} and guest.action_hold == {}
       and guest.clock_grace_until == 0.0 and guest.clock_strikes == mod.CLOCK_CONFIRM - 1)
mod._session = None
del notes[:]
mod.request_resync()
report('sans partie a deux : message clair', 'rien à resynchroniser' in notes[-1][1])

# --- 3. Detecteur d'ecarts ------------------------------------------------------------------
mod._my_active_id = lambda: 10
remote = {'household_id': 5, 'money': 1000, 'seconds': 50000.0,
          'sims': {'10': [0.0, 0.0], '11': [5.0, 5.0], '12': [1.0, 1.0], '13': [9.0, 9.0]}}
local = {'household_id': 5, 'money': 1120, 'seconds': 50000.0 + 1200,
         'sims': {'10': [50.0, 50.0], '11': [5.5, 5.0], '12': [8.0, 1.0], '14': [0.0, 0.0]}}
gaps = mod.compare_digest(guest, remote, local)
report('ecarts lisibles : argent, heure, Sims d\'un seul cote, Sim loin (pas mon propre Sim)',
       gaps == ['argent +120 § par rapport à l\'hôte', 'heure +20 min de jeu', '1 Sim(s) seulement chez l\'hôte',
                '1 Sim(s) seulement chez vous', '1 Sim(s) loin de leur place chez l\'hôte'], str(gaps))
report('parties identiques : aucun ecart', mod.compare_digest(guest, remote, dict(remote)) == [])
report('autre foyer : argent non compare', 'argent' not in ' '.join(
    mod.compare_digest(guest, dict(remote, household_id=6), local)))
mod.bridge_digest = lambda: local
del notes[:]
before = len(guest.endpoint.sent)
mod._handle_digest(guest, remote)
report('invite : alerte des ecarts et compte rendu a l\'hote', guest.last_gaps == gaps
       and kinds(guest.endpoint)[before:] == ['gaps'] and notes and notes[-1][0] == 'Sims4MP · alerte'
       and 'Resynchroniser maintenant' in notes[-1][1])
del notes[:]
mod._notify['last'].clear()                  # hote et invite sont ici dans le meme processus
mod._handle_gaps(host, {'list': ['argent +120 § par rapport à l\'hôte', '\x07']})
report('hote : ecarts de l\'invite affiches (texte nettoye)', host.last_gaps == ['argent +120 § par rapport à l\'hôte']
       and 'Écarts chez l\'invité' in notes[-1][1])
mod.bridge_digest = lambda: {'kind': 'digest', 'sims': {}}
host.digest_sent_at = 0.0
mod._gate['waiting'] = False
mod._digest_tick(host, 100.0)
mod._digest_tick(host, 110.0)
report('hote : resume envoye toutes les {:.0f} s'.format(mod.DIGEST_INTERVAL), kinds(host.endpoint).count('digest') == 1)

# --- 4. Journal lisible -------------------------------------------------------------------
path = os.path.join(TMP, 'gros.log')
with open(path, 'w') as f:
    f.write('x' * 100)
report('journal trop gros : renomme en .old.log', mod.rotate_log(path, limit=10)
       and os.path.isfile(os.path.join(TMP, 'gros.old.log')) and not os.path.exists(path))
report('journal petit : laisse tel quel', not mod.rotate_log(mod.LOG_PATH, limit=10 ** 9))
mod.log('ligne de test du journal')
written = mod.write_report()
with open(written, encoding='utf-8') as f:
    content = f.read()
report('rapport ecrit a cote du journal (etat et fin du journal)',
       os.path.basename(written) == mod.REPORT_NAME and 'Rapport Sims4MP {}'.format(mod.MOD_VERSION) in content
       and 'ligne de test du journal' in content)

shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
