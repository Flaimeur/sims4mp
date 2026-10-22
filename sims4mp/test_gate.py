# Sims 4 Multiplayer - test hors jeu de l'attente de l'autre joueur (etape M2).
# Compatible Python 3.7. A lancer avec :  py -3.7 test_gate.py
#
# Faux modules du jeu : l'horloge reproduit l'arbitrage verifie dans clock.pyc
# (sources par valeur croissante, demande la plus recente d'abord ; le bouton
# Play passe par set_clock_speed en source GAMEPLAY) ; la file d'attente
# imite InteractionQueue.append. L'autre joueur est un transport.Client local.
# Aucun thread, aucun reglage du lanceur : session ouverte par mp.host.

import os
import socket
import sys
import tempfile
import shutil
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

clock = types.ModuleType('clock')


class ClockSpeedMode(object):
    PAUSED = 0
    NORMAL = 1
    SPEED2 = 2


class GameSpeedChangeSource(object):
    SITUATION = 0
    UI_MODAL = 1
    GAMEPLAY = 2
    INITIAL = 3
    values = (0, 1, 2, 3)


class _Request(object):
    def __init__(self, speed, validity_check=None):
        self.speed = speed
        self.validity_check = validity_check


class FakeClock(object):
    def __init__(self):
        self.speed_controllers = {s: [] for s in GameSpeedChangeSource.values}
        self.speed_controllers[GameSpeedChangeSource.INITIAL].append(_Request(ClockSpeedMode.PAUSED))
        self.clock_speed = ClockSpeedMode.PAUSED
        self.broken = False

    def _update_speed(self):
        for source in sorted(GameSpeedChangeSource.values):
            for request in reversed(self.speed_controllers[source]):
                if request.validity_check is None or request.validity_check():
                    self.clock_speed = request.speed
                    return

    def push_speed(self, speed, source=GameSpeedChangeSource.GAMEPLAY, validity_check=None, reason='',
                   immediate=False):
        if self.broken:
            raise RuntimeError('horloge indisponible')
        request = _Request(speed, validity_check)
        self.speed_controllers[source].append(request)
        self._update_speed()
        return request

    def remove_request(self, request, source=GameSpeedChangeSource.GAMEPLAY, reason='', immediate=False):
        if request in self.speed_controllers[source]:
            self.speed_controllers[source].remove(request)
        self._update_speed()

    def set_clock_speed(self, speed, source=GameSpeedChangeSource.GAMEPLAY, reason='', immediate=False):
        # Bouton Play / pause du joueur (server_commands.clock_commands.set_speed_internal).
        self.speed_controllers[source][:] = [_Request(speed)]
        self._update_speed()
        return True


clock.ClockSpeedMode = ClockSpeedMode
clock.GameSpeedChangeSource = GameSpeedChangeSource
GAME_CLOCK = FakeClock()

services = types.ModuleType('services')
services.game_clock_service = lambda: GAME_CLOCK

event_testing = types.ModuleType('event_testing')
results_module = types.ModuleType('event_testing.results')


class TestResult(object):
    def __init__(self, result, reason=None):
        self.result = result
        self.reason = reason

    def __bool__(self):
        return self.result


TestResult.TRUE = TestResult(True)
results_module.TestResult = TestResult
event_testing.results = results_module

interactions = types.ModuleType('interactions')
queue_module = types.ModuleType('interactions.interaction_queue')


class InteractionQueue(object):
    def __init__(self):
        self.items = []

    def append(self, interaction):
        self.items.append(interaction)
        return TestResult.TRUE


queue_module.InteractionQueue = InteractionQueue
interactions.interaction_queue = queue_module


class Interaction(object):
    def __init__(self, name, user_directed):
        self.name = name
        self.is_user_directed = user_directed


sys.modules.update({'sims4': sims4, 'sims4.commands': commands, 'zone': zone, 'clock': clock,
                    'services': services, 'event_testing': event_testing,
                    'event_testing.results': results_module, 'interactions': interactions,
                    'interactions.interaction_queue': queue_module})

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
TMP = tempfile.mkdtemp(prefix='sims4mp_gate_')
mod.LOG_PATH = os.path.join(TMP, 'sims4mp.log')
mod._mods_dir = TMP                         # pas de dossier Mods : aucun reglage du lanceur


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


def paused():
    return GAME_CLOCK.clock_speed == ClockSpeedMode.PAUSED


queue = InteractionQueue()
player_action = Interaction('Discuter', True)
autonomous = Interaction('Boire (autonome)', False)

# --- 1. Hooks ----------------------------------------------------------------------
report('file d\'attente enveloppee', getattr(InteractionQueue.append, '_sims4mp_hook', False))

# --- 2. Solo : rien n'est impose ---------------------------------------------------
GAME_CLOCK.set_clock_speed(ClockSpeedMode.NORMAL)
mod.pump_tick()
report('solo (aucune session, aucun reglage) : pas de pause, actions acceptees',
       not paused() and bool(queue.append(player_action)) and not mod._gate['waiting'] and notes == [])

# --- 3. Host sans joueur : pause imposee, Play sans effet ----------------------------
port = free_port()
mod.mp_host(port)
mod.pump_tick()
report('host sans autre joueur : pause imposee et notification',
       paused() and mod._gate['waiting'] and any('En attente de l\'autre joueur' in n for n in notes))
GAME_CLOCK.set_clock_speed(ClockSpeedMode.NORMAL, source=GameSpeedChangeSource.GAMEPLAY)
GAME_CLOCK.set_clock_speed(ClockSpeedMode.SPEED2, source=GameSpeedChangeSource.UI_MODAL)
mod.pump_tick()
report('bouton Play (GAMEPLAY) et fenetre (UI_MODAL) : la pause reste', paused())
GAME_CLOCK.speed_controllers[GameSpeedChangeSource.UI_MODAL][:] = []     # fenetre fermee

# --- 4. File d'attente bloquee pour le joueur seulement --------------------------------
del notes[:]
before = len(queue.items)
refused_1 = queue.append(player_action)
refused_2 = queue.append(player_action)
accepted = queue.append(autonomous)
report('action du joueur refusee (TestResult False), action autonome acceptee',
       not refused_1 and not refused_2 and bool(accepted) and queue.items[before:] == [autonomous])
report('une seule notification pour deux refus rapproches',
       sum('Action refusée' in n for n in notes) == 1 and mod._gate['refused'] == 2)

# --- 5. Une autre demande SITUATION masque la pause : reposee ----------------------------
other = GAME_CLOCK.push_speed(ClockSpeedMode.NORMAL, source=GameSpeedChangeSource.SITUATION)
mod.pump_tick()
report('demande SITUATION concurrente : pause reposee au tick suivant',
       paused() and mod._gate['repushed'] == 1)
GAME_CLOCK.remove_request(other, source=GameSpeedChangeSource.SITUATION)

# --- 6. L'autre joueur arrive et envoie sa presence ---------------------------------------
peer = transport.Client('127.0.0.1', port)
peer.connect()
peer.send(protocol.hello(mod.MOD_VERSION))
inbox = []


def peer_side():
    inbox.extend(peer.poll())
    if any(k == 'message' and v['type'] == protocol.WELCOME for k, v in inbox):
        peer.send(protocol.make_message(protocol.EVENT, {'kind': 'presence'}))


del notes[:]
released = pump_until(lambda: not mod._gate['waiting'], extra=peer_side)
report('presence recue : pause levee, le jeu reprend la vitesse du joueur',
       released and GAME_CLOCK.clock_speed == ClockSpeedMode.NORMAL
       and any('Les deux joueurs sont en jeu' in n for n in notes))
report('actions du joueur de nouveau acceptees', bool(queue.append(player_action)))

# Ordres du joueur notes pour « le dernier ordre gagne » (pas ceux du mod ni l'autonomie).
queue.sim = types.SimpleNamespace(sim_info=types.SimpleNamespace(sim_id=777))
mod._sync['orders'].clear()
queue.append(autonomous)
no_auto = 777 not in mod._sync['orders']
mod._sync['pushing'] = True
queue.append(player_action)
mod._sync['pushing'] = False
no_mod = 777 not in mod._sync['orders']
queue.append(player_action)
queue.append(player_action)
report('ordres du joueur notes par Sim (pas l\'autonomie, pas les ordres du mod)',
       no_auto and no_mod and mod._sync['orders'].get(777, (0, 0))[1] == 2)
got_presence = pump_until(lambda: any(k == 'message' and v['type'] == protocol.EVENT
                                      and v['data'].get('kind') == 'presence' for k, v in inbox),
                          extra=peer_side)
report('le host envoie aussi sa presence', got_presence)
report('versions identiques : pas d\'avertissement', not any('Versions du mod' in n for n in notes))

# --- 7. Plus de nouvelles (chargement, menu) : pause de nouveau ------------------------------
# Sans passer par la pompe : des presences deja envoyees attendent encore dans le socket.
mod._session.peer_seen_at = time.monotonic() - mod.PRESENCE_TIMEOUT - 1
mod._gate_tick(time.monotonic())
report('presence absente depuis plus de {:.0f} s : pause de nouveau'.format(mod.PRESENCE_TIMEOUT),
       mod._gate['waiting'] and paused())
pump_until(lambda: not mod._gate['waiting'], extra=peer_side)

# --- 8. Depart de l'autre joueur ------------------------------------------------------------
peer.close()
left = pump_until(lambda: mod._gate['waiting'])
report('l\'autre joueur part : pause de nouveau', left and paused())

# --- 9. Version differente ----------------------------------------------------------------
old = transport.Client('127.0.0.1', port)
old.connect()
old.send(protocol.hello('0.5.0'))
del notes[:]
warned = pump_until(lambda: any('Versions du mod différentes' in n for n in notes),
                    extra=lambda: old.poll())
report('mod plus ancien en face : avertissement, la pause reste', warned and mod._gate['waiting'] and paused())
old.close()
pump_until(lambda: mod._session is not None and mod._session.peer is None)

# --- 10. Horloge en panne : pas d'exception, erreur journalisee --------------------------
mod._release_pause()
GAME_CLOCK.broken = True
mod.pump_tick()
mod.pump_tick()
report('horloge en panne : aucune exception, erreur visible dans mp.status',
       mod._gate['error'] is not None and mod._pump['error'] is None)
GAME_CLOCK.broken = False
mod._gate['error'] = None
mod.pump_tick()
report('horloge revenue : pause posee', paused() and mod._gate['request'] is not None)

# --- 11. mp.disconnect : solo tout de suite ------------------------------------------------
del notes[:]
mod.mp_disconnect()
report('mp.disconnect : pause levee tout de suite, notification « vous jouez seul »',
       not mod._gate['waiting'] and not paused() and any('vous jouez seul' in n for n in notes)
       and bool(queue.append(player_action)))
report('aucune demande Sims4MP restee dans l\'horloge',
       all(r.speed != ClockSpeedMode.PAUSED for r in GAME_CLOCK.speed_controllers[GameSpeedChangeSource.SITUATION]))

# --- Fin -------------------------------------------------------------------------------------
shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
