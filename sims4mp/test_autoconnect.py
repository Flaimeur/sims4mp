# Sims 4 Multiplayer - test hors jeu de la connexion automatique (etape M1).
# Compatible Python 3.7. A lancer avec :  py -3.7 test_autoconnect.py
#
# Les modules du jeu (sims4.commands, zone) sont remplaces par de faux modules.
# Le reglage du lanceur est ecrit dans un dossier temporaire qui imite
# Documents\Electronic Arts\Les Sims 4\Mods (espaces insecables). Aucun thread :
# la boucle appelle la pompe du mod comme le ferait Zone.update.

import json
import os
import shutil
import socket
import sys
import tempfile
import time
import types

# --- Faux modules du jeu ------------------------------------------------------

sims4 = types.ModuleType('sims4')
commands = types.ModuleType('sims4.commands')


class _CommandType(object):
    Live = 'Live'


def _command(*names, **kwargs):
    return lambda func: func


class _CheatOutput(object):
    lines = []

    def __init__(self, connection):
        pass

    def __call__(self, text):
        _CheatOutput.lines.append(text)


commands.Command = _command
commands.CommandType = _CommandType
commands.CheatOutput = _CheatOutput
sims4.commands = commands
zone = types.ModuleType('zone')


class _Zone(object):
    def update(self, *args):
        return 'update'

    def on_loading_screen_animation_finished(self):
        return 'loaded'


zone.Zone = _Zone
sys.modules.update({'sims4': sims4, 'sims4.commands': commands, 'zone': zone})

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import protocol  # noqa: E402
import sims4mp_hello as mod  # noqa: E402
import transport  # noqa: E402

TIMEOUT = 3.0
results = []
notes = []                              # notifications affichees par le mod
mod.show_notification = lambda title, text, *args: notes.append(text)
mod.PUMP_INTERVAL = 0.0

TMP = tempfile.mkdtemp(prefix='sims4mp_auto_')
EA = os.path.join(TMP, 'Documents', 'Electronic Arts')
MODS = os.path.join(EA, 'Les Sims 4', 'Mods')
os.makedirs(MODS)
SETTINGS = os.path.join(EA, 'sims4mp_settings.json')
mod._mods_dir = MODS
mod.LOG_PATH = os.path.join(TMP, 'sims4mp.log')


def report(step, ok, detail=''):
    results.append(ok)
    line = '[{}] {}'.format('OK' if ok else 'ECHEC', step)
    if detail:
        line += ' - ' + detail
    print(line)


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]
    finally:
        s.close()


def write_settings(data):
    with open(SETTINGS, 'w', encoding='utf-8') as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


def remove_settings():
    if os.path.exists(SETTINGS):
        os.remove(SETTINGS)


def reset():
    mod._close_session()
    mod._auto['target'] = None
    mod._auto['attempts'] = 0
    mod._auto['last_error'] = None
    del notes[:]


def pump_until(until, extra=None, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mod.pump_tick()
        if extra is not None:
            extra()
        if until():
            return True
        time.sleep(0.005)
    return False


def load_zone():
    # Comme le jeu : la fin du chargement passe par la methode enveloppee.
    return zone.Zone().on_loading_screen_animation_finished()


# --- 1. Hooks ------------------------------------------------------------------
report('hooks installes (Zone.update et fin de chargement)',
       mod._pump['installed'] and getattr(zone.Zone.on_loading_screen_animation_finished, '_sims4mp_hook', False)
       and load_zone() == 'loaded')

# --- 2. Chemin du reglage --------------------------------------------------------
sub = os.path.join(MODS, 'Sims4MP')
os.makedirs(sub)
report('reglage retrouve depuis Mods et depuis un sous-dossier de Mods',
       mod.settings_path(MODS) == SETTINGS and mod.settings_path(sub) == SETTINGS)
report('pas de dossier Mods : aucun chemin', mod.settings_path(TMP) is None)

# --- 3. Validation (memes regles que le lanceur) -----------------------------------
valid = [{'role': 'host', 'ip': '', 'port': 7777}, {'role': 'join', 'ip': ' 192.168.1.20 ', 'port': 1024},
         {'role': 'join', 'ip': '10.0.0.5', 'port': 65535}]
invalid = [[], {'role': 'host', 'ip': '', 'port': 80}, {'role': 'host', 'ip': '', 'port': '7777'},
           {'role': 'host', 'ip': '', 'port': True}, {'role': 'admin', 'ip': '', 'port': 7777},
           {'role': 'join', 'ip': '', 'port': 7777}, {'role': 'join', 'ip': '192.168.1', 'port': 7777},
           {'role': 'join', 'ip': '192.168.01.2', 'port': 7777}, {'role': 'join', 'ip': '0.0.0.0', 'port': 7777},
           {'role': 'join', 'ip': '224.0.0.1', 'port': 7777}, {'role': 'join', 'ip': '256.1.1.1', 'port': 7777},
           {'role': 'host', 'ip': '', 'port': 7777, 'save': 'x'}, {'role': 'host', 'port': 7777}]
report('reglages valides acceptes', all(mod.validate_settings(d)[0] is not None for d in valid))
report('reglages invalides refuses ({} cas)'.format(len(invalid)),
       all(mod.validate_settings(d)[0] is None for d in invalid))

# --- 4. Reglage absent ------------------------------------------------------------
reset()
remove_settings()
load_zone()
report('reglage absent : aucune session, aucune notification', mod._session is None and notes == []
       and mod._auto['target'] is None)

# --- 5. Reglage invalide -------------------------------------------------------------
reset()
write_settings('{pas du json')
load_zone()
ok_json = mod._session is None and len(notes) == 1 and 'Réglage Sims4MP ignoré' in notes[0]
reset()
write_settings({'role': 'join', 'ip': '1.2.3', 'port': 7777})
load_zone()
report('reglage invalide : ignore, une notification, aucune session',
       ok_json and mod._session is None and 'ip de l\'hote invalide' in notes[0])

# --- 6. Host automatique ---------------------------------------------------------------
reset()
host_port = free_port()
write_settings({'role': 'host', 'ip': '', 'port': host_port})
load_zone()
session = mod._session
report('host automatique : ecoute sur le port du reglage',
       session is not None and session.role == 'host' and session.endpoint.port == host_port
       and any('Vous hébergez la partie' in n for n in notes))
load_zone()
report('second chargement : rien n\'est relance (meme session)', mod._session is session)

peer = transport.Client('127.0.0.1', host_port)
peer.connect()
peer.send(protocol.hello(mod.MOD_VERSION))
inbox = []
got = pump_until(lambda: any(v.get('type') == protocol.WELCOME for k, v in inbox if k == 'message'),
                 extra=lambda: inbox.extend(peer.poll()))
report('un client se connecte : WELCOME et notification « a rejoint »',
       got and any('L\'invité a rejoint la partie' in n for n in notes))
peer.close()
left = pump_until(lambda: any('a quitté la partie' in n for n in notes))
report('le client part : notification « a quitté »', left)

# --- 7. Client automatique vers un hote ----------------------------------------------------
reset()
fake_port = free_port()
fake_host = transport.Server('127.0.0.1', fake_port)
fake_host.start()


def fake_host_answers():
    for kind, value in fake_host.poll():
        if kind == 'message' and value['type'] == protocol.HELLO:
            fake_host.send(protocol.welcome('faux host'))


write_settings({'role': 'join', 'ip': '127.0.0.1', 'port': fake_port})
load_zone()
connected = pump_until(lambda: mod._session is not None and mod._session.handshake_done, extra=fake_host_answers)
report('client automatique : connexion et handshake sans commande',
       connected and mod._session.role == 'client' and any('Connecté à l\'hôte' in n for n in notes))

# Perte de connexion : pas de nouvelle tentative avant 30 s.
fake_host.close()
lost = pump_until(lambda: mod._session is None)
lost_at = time.monotonic()
attempts = mod._auto['attempts']
mod._auto_tick(lost_at + 5)
no_retry = mod._session is None and mod._auto['attempts'] == attempts
report('connexion perdue : notification, pas de nouvelle tentative avant 30 s',
       lost and no_retry and any('Connexion à l\'hôte perdue' in n for n in notes))

# --- 8. Hote absent : une tentative toutes les 30 s au plus ------------------------------
reset()
closed_port = free_port()
write_settings({'role': 'join', 'ip': '127.0.0.1', 'port': closed_port})
load_zone()
failed = pump_until(lambda: mod._session is None)
t0 = time.monotonic()
first = mod._auto['attempts']
mod._auto_tick(t0 + 10)
after_10s = mod._auto['attempts']
mod._auto_tick(t0 + mod.AUTO_RETRY_INTERVAL + 1)
after_31s = mod._auto['attempts']
report('hote absent : echec signale une seule fois',
       failed and first == 1 and sum('injoignable' in n for n in notes) == 1)
report('hote absent : pas de tentative a 10 s, une nouvelle a 31 s', after_10s == 1 and after_31s == 2)
pump_until(lambda: mod._session is None)

# --- 9. mp.disconnect arrete la connexion automatique ---------------------------------------
mod.mp_disconnect()
mod._auto_tick(time.monotonic() + 10 * mod.AUTO_RETRY_INTERVAL)
report('mp.disconnect : plus aucune tentative automatique',
       mod._auto['target'] is None and mod._session is None
       and any('Connexion automatique arretee' in line for line in _CheatOutput.lines))

# --- 10. Session manuelle deja ouverte au chargement ----------------------------------------
reset()
manual_port = free_port()
mod.mp_host(manual_port)
manual = mod._session
write_settings({'role': 'join', 'ip': '127.0.0.1', 'port': free_port()})
load_zone()
report('session manuelle deja active : le reglage ne la remplace pas',
       mod._session is manual and manual.role == 'host' and mod._auto['target'] is None)
reset()

# --- 11. mp.solo : seul jusqu'a la fermeture du jeu -----------------------------------------
write_settings({'role': 'host', 'ip': '', 'port': free_port()})
load_zone()
auto_session = mod._session
del _CheatOutput.lines[:]
mod.mp_solo()
report('mp.solo : partie a deux fermee, pause levee, message clair',
       auto_session is not None and mod._session is None and not mod._gate['waiting']
       and any('Mode solo' in line and 'Partie a deux arretee' in line for line in _CheatOutput.lines))
load_zone()                                           # voyage ou autre partie : nouveau chargement
load_zone()
mod._auto_tick(time.monotonic() + 10 * mod.AUTO_RETRY_INTERVAL)
report('mp.solo : reglage du lanceur ignore aux chargements suivants',
       mod._session is None and mod._auto['target'] is None and mod._auto['solo']
       and not mod._gate['waiting'])
solo_port = free_port()
mod.mp_host(solo_port)
report('mp.solo : mp.host reste possible a la main', mod._session is not None and mod._session.role == 'host')
reset()
mod._auto['solo'] = False

# --- Fin -------------------------------------------------------------------------------------
shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)                   # journal du chargement du mod, cree par l'import
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
