# Sims 4 Multiplayer - test hors jeu des positions (etape M3, lecture seule).
# Compatible Python 3.7. A lancer avec :  py -3.7 test_positions.py
#
# Faux modules du jeu : client actif, Sims avec position / niveau / action en
# cours, gestionnaire de Sims, horloge minimale. L'autre joueur est un
# transport.Client local. Aucun thread, aucun reglage du lanceur.

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


class _CheatOutput(object):
    lines = []

    def __init__(self, connection):
        pass

    def __call__(self, text):
        _CheatOutput.lines.append(text)


commands.Command = lambda *names, **kwargs: (lambda func: func)
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


class Vector3(object):
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class Affordance(object):
    pass


class sit_Chair(Affordance):
    pass


class FakeQueue(object):
    def __init__(self):
        self.running = None


class FakeRunning(object):
    def __init__(self, affordance):
        self.affordance = affordance


class FakeSimInfo(object):
    def __init__(self, sim_id, first, last):
        self.sim_id = sim_id
        self.first_name = first
        self.last_name = last
        self.instance = None

    def get_sim_instance(self, allow_hidden_flags=None):
        return self.instance


class FakeSim(object):
    def __init__(self, sim_info, x, y, z, level=0):
        self.sim_info = sim_info
        sim_info.instance = self
        self.position = Vector3(x, y, z)
        self.level = level
        self.queue = FakeQueue()


class FakeClient(object):
    active_sim = None


CLIENT = FakeClient()
SIM_INFOS = {}
ZONE = {'id': 555}

services = types.ModuleType('services')
services.client_manager = lambda: types.SimpleNamespace(get_first_client=lambda: CLIENT)
services.sim_info_manager = lambda: types.SimpleNamespace(get=SIM_INFOS.get)
services.current_zone_id = lambda: ZONE['id']


def _no_clock():
    raise RuntimeError('pas d\'horloge dans ce test')


services.game_clock_service = _no_clock
objects = types.ModuleType('objects')
objects.ALL_HIDDEN_REASONS = 'ALL'

sys.modules.update({'sims4': sims4, 'sims4.commands': commands, 'zone': zone,
                    'services': services, 'objects': objects})

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import protocol  # noqa: E402
import sims4mp_hello as mod  # noqa: E402
import transport  # noqa: E402

TIMEOUT = 3.0
results = []
notes = []
mod.show_notification = lambda title, text, *args: notes.append(text)
mod.PUMP_INTERVAL = 0.0
mod.POSITION_INTERVAL = 0.02
TMP = tempfile.mkdtemp(prefix='sims4mp_positions_')
mod.LOG_PATH = os.path.join(TMP, 'sims4mp.log')
mod._mods_dir = TMP


def report(step, ok, detail=''):
    results.append(bool(ok))
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


inbox = []


def peer_poll():
    inbox.extend(peer.poll())


def pump_for(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        mod.pump_tick()
        peer_poll()
        time.sleep(0.005)


def pump_until(until, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mod.pump_tick()
        peer_poll()
        if until():
            return True
        time.sleep(0.005)
    return False


def positions_received():
    return [v['data'] for k, v in inbox
            if k == 'message' and v['type'] == protocol.EVENT and v['data'].get('kind') == 'position']


def send_position(**fields):
    data = {'kind': 'position', 'sim_id': 2002, 'name': 'Alex Martin', 'zone_id': 555,
            'x': 10.0, 'y': 0.0, 'z': 20.0, 'level': 0, 'action': None}
    data.update(fields)
    peer.send(protocol.make_message(protocol.EVENT, data))


def positions_text():
    del _CheatOutput.lines[:]
    mod.mp_positions()
    return '\n'.join(_CheatOutput.lines)


mine = FakeSimInfo(1001, 'Élise', 'Petrova')
other = FakeSimInfo(2002, 'Alex', 'Martin')
SIM_INFOS.update({1001: mine, 2002: other})
my_sim = FakeSim(mine, 1.0, 0.0, 2.0)
other_sim = FakeSim(other, 10.5, 0.0, 20.0)

# --- 1. Sans Sim actif : rien n'est envoye ----------------------------------------------
port = free_port()
mod.mp_host(port)
peer = transport.Client('127.0.0.1', port)
peer.connect()
peer.send(protocol.hello(mod.MOD_VERSION))
pump_until(lambda: mod._session.handshake_done)
pump_for(0.2)
report('pas de Sim actif : aucune position envoyee, aucune erreur',
       positions_received() == [] and mod._pump['error'] is None)

# --- 2. Sim actif : position envoyee une fois -----------------------------------------
CLIENT.active_sim = my_sim
got = pump_until(lambda: positions_received())
first = positions_received()[0] if got else {}
report('position du Sim actif envoyee (id, nom, zone, coordonnees, niveau)',
       got and first.get('sim_id') == 1001 and first.get('name') == 'Élise Petrova'
       and first.get('zone_id') == 555 and (first.get('x'), first.get('z')) == (1.0, 2.0)
       and first.get('level') == 0 and first.get('action') is None)
pump_for(0.2)
report('immobile : pas de renvoi', len(positions_received()) == 1)

# --- 3. Petits et grands deplacements, action en cours ---------------------------------
my_sim.position = Vector3(1.01, 0.0, 2.0)
pump_for(0.15)
small = len(positions_received())
my_sim.position = Vector3(3.0, 0.0, 2.0)
pump_until(lambda: len(positions_received()) == 2)
report('deplacement < {} : ignore ; deplacement de 2 : renvoye'.format(mod.POSITION_MIN_MOVE),
       small == 1 and len(positions_received()) == 2 and positions_received()[1]['x'] == 3.0)
my_sim.queue.running = FakeRunning(sit_Chair)
pump_until(lambda: len(positions_received()) == 3)
report('nouvelle action en cours : renvoyee avec son nom',
       positions_received()[-1].get('action') == 'sit_Chair')

# --- 4. Position recue de l'autre joueur ---------------------------------------------------
del notes[:]
send_position()
pump_until(lambda: mod._session.remote_position is not None)
remote = mod._session.remote_position
report('position recue gardee, notification « L\'autre joueur contrôle Alex Martin »',
       remote is not None and remote['sim_id'] == 2002 and remote['x'] == 10.0
       and any('contrôle Alex Martin' in n for n in notes))
send_position(x=11.0)
pump_until(lambda: mod._session.remote_position['x'] == 11.0)
report('mise a jour sans nouvelle notification', sum('contrôle' in n for n in notes) == 1)

# --- 5. Positions invalides ignorees -------------------------------------------------------
bad = [dict(x=float('nan')), dict(x='12'), dict(sim_id=None), dict(sim_id=-5), dict(z=1e9),
       dict(x=True), dict(sim_id='2002')]
for fields in bad:
    send_position(**fields)
send_position(x=12.0)                                    # la derniere valide
pump_until(lambda: mod._session.remote_position['x'] == 12.0)
report('positions invalides ignorees ({} cas), la suivante valide acceptee'.format(len(bad)),
       mod._session.remote_position['x'] == 12.0 and mod._session.remote_position['sim_id'] == 2002)
send_position(x=12.0, name='\x1b[31m' + 'N' * 200, level=999)
pump_until(lambda: mod._session.remote_position['level'] is None)
cleaned = mod._session.remote_position
report('texte nettoye et tronque, niveau hors bornes ignore',
       cleaned['name'].isprintable() and len(cleaned['name']) <= mod.STATE_MAX_TEXT and cleaned['level'] is None)
send_position(x=12.0)
pump_until(lambda: mod._session.remote_position['level'] == 0)

# --- 6. mp.positions -----------------------------------------------------------------------
text = positions_text()
report('mp.positions : mon Sim, celui de l\'autre et l\'ecart avec le meme Sim ici',
       'Mon Sim : Élise Petrova (1001)' in text and 'Sim de l\'autre joueur : Alex Martin (2002)' in text
       and 'ecart 1.50' in text, text.replace('\n', ' | '))
other.instance = None
report('Sim connu mais pas sur le lot', 'n\'est pas sur le lot' in positions_text())
del SIM_INFOS[2002]
report('Sim inconnu : pas la meme sauvegarde', 'pas la meme sauvegarde' in positions_text())
ZONE['id'] = 777
report('zone differente : pas de comparaison', 'Zone differente' in positions_text())
ZONE['id'] = 555
send_position(sim_id=1001, name='Élise Petrova', x=3.0, z=2.0)
pump_until(lambda: mod._session.remote_position['sim_id'] == 1001)
report('meme Sim des deux cotes : signale', 'tous les deux ce Sim' in positions_text())

# --- 7. Rien n'est deplace -------------------------------------------------------------------
report('lecture seule : aucune position locale modifiee',
       (my_sim.position.x, my_sim.position.z) == (3.0, 2.0))

# --- Fin -------------------------------------------------------------------------------------
peer.close()
mod._close_session()
shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
