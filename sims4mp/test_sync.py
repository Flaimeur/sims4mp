# Sims 4 Multiplayer - test hors jeu de la synchro en jeu (etape M4) :
# argent, heure et vitesse, marche du double. Compatible Python 3.7.
# A lancer avec :  py -3.7 test_sync.py
#
# Faux modules du jeu : foyer et argent, horloge (arbitrage des vitesses comme
# clock.pyc), Sims et ordres de marche (comme sims.gohere). L'autre joueur est
# un transport local (client puis hote). Aucun thread, aucun reglage du lanceur.

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
math_module = types.ModuleType('sims4.math')


class _CommandType(object):
    Live = 'Live'


class _CheatOutput(object):
    lines = []

    def __init__(self, connection):
        pass

    def __call__(self, text):
        _CheatOutput.lines.append(text)


class Vector3(object):
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


commands.Command = lambda *names, **kwargs: (lambda func: func)
commands.CommandType = _CommandType
commands.CheatOutput = _CheatOutput
math_module.Vector3 = Vector3
sims4.commands = commands
sims4.math = math_module

zone = types.ModuleType('zone')


class _Zone(object):
    def update(self, *args):
        return 'update'

    def on_loading_screen_animation_finished(self):
        return 'loaded'


zone.Zone = _Zone


class _ClockSpeedMode(object):
    PAUSED, NORMAL, SPEED2, SPEED3 = 0, 1, 2, 3
    values = (0, 1, 2, 3, 4, 5)

    def __call__(self, value):
        if value not in self.values:
            raise ValueError(value)
        return value


ClockSpeedMode = _ClockSpeedMode()


class GameSpeedChangeSource(object):
    SITUATION, UI_MODAL, GAMEPLAY, INITIAL = 0, 1, 2, 3
    values = (0, 1, 2, 3)


class _Request(object):
    def __init__(self, speed):
        self.speed = speed


class _Now(object):
    def __init__(self, seconds):
        self.seconds = seconds

    def absolute_seconds(self):
        return self.seconds


class FakeClock(object):
    def __init__(self):
        self.speed_controllers = {s: [] for s in GameSpeedChangeSource.values}
        self.speed_controllers[GameSpeedChangeSource.GAMEPLAY].append(_Request(1))
        self.clock_speed = 1
        self.seconds = 100000.0
        self.advanced = []

    def _update(self):
        for source in sorted(GameSpeedChangeSource.values):
            if self.speed_controllers[source]:
                self.clock_speed = self.speed_controllers[source][-1].speed
                return

    def push_speed(self, speed, source=2, validity_check=None, reason='', immediate=False):
        request = _Request(speed)
        self.speed_controllers[source].append(request)
        self._update()
        return request

    def remove_request(self, request, source=2, reason='', immediate=False):
        if request in self.speed_controllers[source]:
            self.speed_controllers[source].remove(request)
        self._update()

    def set_clock_speed(self, speed, source=2, reason='', immediate=False):
        # Comme clock.pyc : remplace les demandes de cette source (bouton de vitesse).
        self.speed_controllers[source][:] = [_Request(speed)]
        self._update()
        return True

    def pop_speed(self, speed=None, source=2, reason='', immediate=False):
        requests = self.speed_controllers[source]
        request = requests.pop() if requests else None
        self._update()
        return request

    def now(self):
        return _Now(self.seconds)

    def advance_game_time(self, hours=0, minutes=0, seconds=0):
        self.advanced.append(seconds)
        self.seconds += hours * 3600 + minutes * 60 + seconds

    def situation_speeds(self):
        return [r.speed for r in self.speed_controllers[GameSpeedChangeSource.SITUATION]]


clock = types.ModuleType('clock')
clock.ClockSpeedMode = ClockSpeedMode
clock.GameSpeedChangeSource = GameSpeedChangeSource
clock.GameClock = FakeClock
GAME_CLOCK = FakeClock()


class Funds(object):
    def __init__(self, money):
        self.money = money
        self.calls = []

    def add(self, amount, reason, sim):
        self.calls.append(('add', amount, reason))
        self.money += amount

    def try_remove(self, amount, reason, sim, require_full_amount=True):
        self.calls.append(('remove', amount, reason, require_full_amount))
        self.money -= amount
        return True


class Household(object):
    def __init__(self, hid, name, money):
        self.id = hid
        self.name = name
        self.funds = Funds(money)

    def sim_info_gen(self):
        return iter(())


HOUSEHOLD = Household(4242, 'Dupont', 10000)


class FakeQueue(object):
    running = None


class FakeSimInfo(object):
    def __init__(self, sim_id, first, last):
        self.sim_id = sim_id
        self.first_name, self.last_name = first, last
        self.instance = None

    def get_sim_instance(self, allow_hidden_flags=None):
        return self.instance

    def get_mood(self):
        return None


class FakeSim(object):
    def __init__(self, sim_info, x, z, level=0):
        self.sim_info = sim_info
        sim_info.instance = self
        self.position = Vector3(x, 0.0, z)
        self.level = level
        self.queue = FakeQueue()
        self.pushed = []
        self.accept = True
        self.broken = False
        self.placed = []

    def push_super_affordance(self, affordance, target, context):
        if self.broken:
            raise RuntimeError('affordance non reglee')
        self.pushed.append((affordance, target, context))
        return self.accept

    def move_to(self, translation=None, routing_surface=None):
        self.placed.append((translation.x, translation.z, routing_surface.level))
        self.position = translation


class FakeClient(object):
    active_sim = None


CLIENT = FakeClient()
SIM_INFOS = {}
ZONE = {'id': 555}

services = types.ModuleType('services')
services.client_manager = lambda: types.SimpleNamespace(get_first_client=lambda: CLIENT)
services.sim_info_manager = lambda: types.SimpleNamespace(get=SIM_INFOS.get)
services.current_zone_id = lambda: ZONE['id']
services.active_household = lambda: HOUSEHOLD
services.game_clock_service = lambda: GAME_CLOCK
services.time_service = lambda: None

objects = types.ModuleType('objects')
objects.ALL_HIDDEN_REASONS = 'ALL'
terrain_module = types.ModuleType('objects.terrain')


class TerrainPoint(object):
    def __init__(self, location):
        self.location = location


terrain_module.TerrainPoint = TerrainPoint
objects.terrain = terrain_module

routing = types.ModuleType('routing')


class SurfaceIdentifier(object):
    def __init__(self, zone_id, level, kind):
        self.zone_id, self.level, self.kind = zone_id, level, kind


routing.SurfaceIdentifier = SurfaceIdentifier
routing.SurfaceType = types.SimpleNamespace(SURFACETYPE_WORLD='WORLD')

server = types.ModuleType('server')
pick_info = types.ModuleType('server.pick_info')
pick_info.PickType = types.SimpleNamespace(PICK_TERRAIN='TERRAIN')
server.pick_info = pick_info

server_commands = types.ModuleType('server_commands')
sim_commands = types.ModuleType('server_commands.sim_commands')
GOHERE, TELEPORT = 'terrain-GoHere', 'terrain-Teleport'
sim_commands.CommandTuning = types.SimpleNamespace(TERRAIN_GOHERE_AFFORDANCE=GOHERE,
                                                   TERRAIN_TELEPORT_AFFORDANCE=TELEPORT)


def _build(sim, pos, surface, pick_type, target_cls):
    return target_cls((pos, surface)), {'sim': sim, 'pick': pick_type}


sim_commands._build_terrain_interaction_target_and_context = _build
server_commands.sim_commands = sim_commands

protocolbuffers = types.ModuleType('protocolbuffers')
Consts_pb2 = types.ModuleType('protocolbuffers.Consts_pb2')
Consts_pb2.TELEMETRY_MONEY_CHEAT = 'CHEAT'
protocolbuffers.Consts_pb2 = Consts_pb2

sys.modules.update({'sims4': sims4, 'sims4.commands': commands, 'sims4.math': math_module, 'zone': zone,
                    'clock': clock, 'services': services, 'objects': objects, 'objects.terrain': terrain_module,
                    'routing': routing, 'server': server, 'server.pick_info': pick_info,
                    'server_commands': server_commands, 'server_commands.sim_commands': sim_commands,
                    'protocolbuffers': protocolbuffers, 'protocolbuffers.Consts_pb2': Consts_pb2})

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import protocol  # noqa: E402
import sims4mp_hello as mod  # noqa: E402
import transport  # noqa: E402

TIMEOUT = 3.0
results = []
notes = []
mod.show_notification = lambda title, text: notes.append(text)
mod.PUMP_INTERVAL = 0.0
mod.POSITION_INTERVAL = 0.02
mod.MONEY_INTERVAL = 0.02
mod.CLOCK_INTERVAL = 0.05
TMP = tempfile.mkdtemp(prefix='sims4mp_sync_')
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
peer = None


def presence():
    peer.send(protocol.make_message(protocol.EVENT, {'kind': 'presence'}))


def step(extra=None):
    mod.pump_tick()
    for item in peer.poll():
        inbox.append(item)
    if extra is not None:
        extra()


def pump_until(until, extra=None, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        step(extra)
        if until():
            return True
        time.sleep(0.005)
    return False


def pump_for(seconds, extra=None):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        step(extra)
        time.sleep(0.005)


def events(kind):
    return [v['data'] for k, v in inbox if k == 'message' and v['type'] == protocol.EVENT
            and v['data'].get('kind') == kind]


def send(data):
    peer.send(protocol.make_message(protocol.EVENT, data))


mine = FakeSimInfo(1001, 'Élise', 'Petrova')
other = FakeSimInfo(2002, 'Alex', 'Martin')
SIM_INFOS.update({1001: mine, 2002: other})
my_sim = FakeSim(mine, 0.0, 0.0)
double = FakeSim(other, 10.0, 10.0)
CLIENT.active_sim = my_sim


def position(**fields):
    data = {'kind': 'position', 'sim_id': 2002, 'name': 'Alex Martin', 'zone_id': 555,
            'x': 15.0, 'y': 0.0, 'z': 10.0, 'level': 0, 'action': None}
    data.update(fields)
    return data


# ================= Ce PC est l'hote, l'autre joueur est un client local =================
port = free_port()
mod.mp_host(port)
peer = transport.Client('127.0.0.1', port)
peer.connect()
peer.send(protocol.hello(mod.MOD_VERSION))
pump_until(lambda: not mod._gate['waiting'], extra=presence)
session = mod._session

# --- 1. Argent ----------------------------------------------------------------------------
got_total = pump_until(lambda: events('money'), extra=presence)
report('hote : solde envoye une fois pour l\'alignement initial',
       got_total and events('money')[0] == {'kind': 'money', 'total': 10000, 'household_id': 4242})
HOUSEHOLD.funds.money -= 350                               # achat fait sur ce PC
pump_until(lambda: any(e.get('delta') == -350 for e in events('money')), extra=presence)
report('depense locale (-350) envoyee', any(e.get('delta') == -350 for e in events('money')))
before = len(events('money'))
send({'kind': 'money', 'delta': 120, 'household_id': 4242})  # salaire chez l'autre
pump_until(lambda: HOUSEHOLD.funds.money == 9770, extra=presence)
pump_for(0.15, extra=presence)
report('gain de l\'autre (+120) applique, sans renvoi en echo',
       HOUSEHOLD.funds.money == 9770 and len(events('money')) == before
       and HOUSEHOLD.funds.calls[-1] == ('add', 120, 'CHEAT'))
HOUSEHOLD.funds.money += 40                                 # gain local juste avant une depense recue
send({'kind': 'money', 'delta': -500, 'household_id': 4242})
pump_until(lambda: HOUSEHOLD.funds.money == 9310, extra=presence)
pump_for(0.15, extra=presence)
report('gain local et depense recue au meme moment : les deux comptent',
       HOUSEHOLD.funds.money == 9310 and any(e.get('delta') == 40 for e in events('money'))
       and HOUSEHOLD.funds.calls[-1] == ('remove', 500, 'CHEAT', False))
for bad in ({'delta': 'x'}, {'delta': True}, {'delta': 10 ** 12}, {'delta': 0},
            {'delta': 5, 'household_id': 1}, {'delta': 5, 'household_id': None}):
    data = {'kind': 'money', 'household_id': 4242}
    data.update(bad)
    send(data)
pump_for(0.2, extra=presence)
report('differences invalides ou autre foyer ignorees', HOUSEHOLD.funds.money == 9310)

# --- 2. Heure envoyee par l'hote ------------------------------------------------------------
pump_until(lambda: events('clock'), extra=presence)
clock_msg = events('clock')[-1] if events('clock') else {}
report('hote : heure et vitesse envoyees', clock_msg.get('seconds') == 100000.0 and clock_msg.get('speed') == 1)
send({'kind': 'clock', 'seconds': 1.0, 'speed': 3})
pump_for(0.1, extra=presence)
report('hote : l\'heure envoyee par l\'invite est ignoree', GAME_CLOCK.advanced == [] and GAME_CLOCK.clock_speed == 1)

# --- 3. Marche du double --------------------------------------------------------------------
send(position(x=15.0, z=10.0))
pump_until(lambda: double.pushed, extra=presence)
first = double.pushed[0] if double.pushed else (None, None, None)
target = first[1]
report('le double marche vers la position recue (sims.gohere)',
       first[0] == GOHERE and target.location[0].x == 15.0 and target.location[1].zone_id == 555
       and target.location[1].level == 0)
send(position(x=15.2, z=10.0))                               # meme destination, a peu pres
pump_for(0.2, extra=presence)
report('meme destination : pas de nouvel ordre', len(double.pushed) == 1)
send(position(x=18.0, z=12.0))
pump_until(lambda: len(double.pushed) >= 2, extra=presence)
report('nouvelle destination : nouvel ordre', len(double.pushed) == 2 and double.pushed[1][1].location[0].x == 18.0)
session.walk['started'] -= mod.WALK_TIMEOUT + 1               # toujours loin apres 15 s
session.walk['at'] -= mod.WALK_RETRY
pump_until(lambda: double.pushed[-1][0] == TELEPORT, extra=presence)
report('toujours loin apres {:.0f} s : teleporte'.format(mod.WALK_TIMEOUT), double.pushed[-1][0] == TELEPORT)
double.position = Vector3(18.0, 0.0, 12.0)                    # arrive
count = len(double.pushed)
send(position(x=18.3, z=12.0))
pump_for(0.2, extra=presence)
report('double deja sur place : aucun ordre', len(double.pushed) == count)
send(position(x=80.0, z=12.0))
pump_until(lambda: len(double.pushed) > count, extra=presence)
report('ecart de plus de {:.0f} : teleportation directe'.format(mod.TELEPORT_DIST), double.pushed[-1][0] == TELEPORT)
double.position = Vector3(80.0, 0.0, 12.0)
send(position(x=80.0, z=12.0, level=1))
pump_until(lambda: double.pushed[-1][1].location[1].level == 1, extra=presence)
report('autre niveau : teleportation', double.pushed[-1][0] == TELEPORT)
double.position = Vector3(80.0, 0.0, 12.0)
double.level = 1
double.accept = False                                          # chemin refuse par le jeu
count = len(double.pushed)
send(position(x=85.0, z=12.0, level=1))
pump_until(lambda: len(double.pushed) >= count + 2, extra=presence)
report('marche refusee : teleportation a la place',
       [p[0] for p in double.pushed[count:count + 2]] == [GOHERE, TELEPORT])
double.accept = True
count_mine = len(my_sim.pushed)
send(position(sim_id=1001, name='Élise Petrova', x=30.0, z=30.0))
pump_for(0.2, extra=presence)
report('le Sim que ce joueur controle n\'est jamais deplace', len(my_sim.pushed) == count_mine)
count = len(double.pushed)
ZONE['id'] = 777
send(position(x=5.0, z=5.0))
pump_for(0.2, extra=presence)
ZONE['id'] = 555
report('autre zone : aucun ordre', len(double.pushed) == count)

# --- 3b. Diagnostic et repli ---------------------------------------------------------------
del _CheatOutput.lines[:]
mod.mp_positions()
report('mp.positions dit pourquoi le double ne bouge pas', 'autre lot (zone 555 , ici 555)' in
       '\n'.join(_CheatOutput.lines) or 'autre lot' in session.walk_status,
       session.walk_status)
del notes[:]
send(position(sim_id=1001, name='Élise Petrova', x=40.0, z=40.0))
pump_until(lambda: 'meme Sim' in session.walk_status, extra=presence)
report('meme Sim controle des deux cotes : notification une fois',
       sum('même Sim' in n for n in notes) == 1)
double.position = Vector3(18.0, 0.0, 12.0)
double.level = 0
double.broken = True                                         # ordres du jeu en erreur
del double.placed[:]
send(position(x=25.0, z=14.0))
pump_until(lambda: double.placed, extra=presence)
report('ordres de marche en erreur : double pose directement (repli)',
       double.placed == [(25.0, 14.0, 0)] and 'pose directement' in session.walk_status,
       '{} / {}'.format(double.placed, session.walk_status))
double.broken = False

# --- 3c. Vitesse demandee par l'invite --------------------------------------------------------
before = len(events('clock'))
send({'kind': 'speed_request', 'speed': 3})
pump_until(lambda: GAME_CLOCK.clock_speed == 3, extra=presence)
pump_until(lambda: any(e.get('speed') == 3 for e in events('clock')[before:]), extra=presence)
report('hote : vitesse demandee par l\'invite appliquee comme son bouton, renvoyee aussitot',
       GAME_CLOCK.speed_controllers[GameSpeedChangeSource.GAMEPLAY][-1].speed == 3
       and session.speed_requests == 1 and any(e.get('speed') == 3 for e in events('clock')[before:]))
send({'kind': 'speed_request', 'speed': 9})
pump_for(0.1, extra=presence)
report('hote : vitesse invalide refusee', GAME_CLOCK.clock_speed == 3 and session.speed_requests == 1)
GAME_CLOCK.set_clock_speed(1, source=GameSpeedChangeSource.GAMEPLAY)
pump_for(0.1, extra=presence)
report('hote : ses propres boutons ne sont pas renvoyes', events('speed_request') == [])

# --- 4. Pendant l'attente : rien n'est applique ----------------------------------------------
session.peer_seen_at = time.monotonic() - mod.PRESENCE_TIMEOUT - 1
mod._gate_tick(time.monotonic())
count = len(double.pushed)
mod._maybe_walk(session, time.monotonic())
report('attente de l\'autre joueur : pas de marche', mod._gate['waiting'] and len(double.pushed) == count)
pump_until(lambda: not mod._gate['waiting'], extra=presence)

peer.close()
mod._close_session()
mod.pump_tick()

# ================= Ce PC est l'invite, l'autre joueur est un hote local ===================
del inbox[:]
del notes[:]
HOUSEHOLD.funds.money = 7000
GAME_CLOCK.seconds = 100000.0
host_port = free_port()
peer = transport.Server('127.0.0.1', host_port)
peer.start()


def host_side():
    for kind, value in list(inbox):
        if kind == 'message' and value['type'] == protocol.HELLO:
            peer.send(protocol.welcome('faux hote'))
            inbox.remove((kind, value))
    if peer.is_connected:
        presence()


mod.mp_join('127.0.0.1', host_port)
pump_until(lambda: mod._session is not None and mod._session.handshake_done and not mod._gate['waiting'],
           extra=host_side)
session = mod._session

# --- 5. Alignement initial de l'argent ----------------------------------------------------------
send({'kind': 'money', 'total': 9310, 'household_id': 4242})
pump_until(lambda: HOUSEHOLD.funds.money == 9310, extra=host_side)
report('invite : solde aligne une fois sur celui de l\'hote, notification',
       HOUSEHOLD.funds.money == 9310 and any('Argent aligné sur l\'hôte' in n for n in notes))
send({'kind': 'money', 'total': 1, 'household_id': 4242})
pump_for(0.15, extra=host_side)
report('second alignement ignore', HOUSEHOLD.funds.money == 9310)

# --- 6. Heure et vitesse de l'hote ---------------------------------------------------------------
send({'kind': 'clock', 'seconds': 100600.0, 'speed': 2})
pump_until(lambda: GAME_CLOCK.advanced, extra=host_side)
report('invite en retard de 600 s de jeu : heure avancee, vitesse de l\'hote (2)',
       GAME_CLOCK.advanced == [600] and GAME_CLOCK.clock_speed == 2 and GAME_CLOCK.situation_speeds() == [2])
GAME_CLOCK.speed_controllers[GameSpeedChangeSource.GAMEPLAY][:] = [_Request(0)]   # bouton pause du joueur
GAME_CLOCK._update()
send({'kind': 'clock', 'seconds': 100610.0, 'speed': 2})
pump_for(0.1, extra=host_side)
report('le bouton du joueur ne change pas la vitesse de l\'hote', GAME_CLOCK.clock_speed == 2
       and GAME_CLOCK.situation_speeds() == [2])
send({'kind': 'clock', 'seconds': 100000.0, 'speed': 2})           # l'invite est en avance de 600 s
pump_until(lambda: GAME_CLOCK.clock_speed == 0, extra=host_side)
report('invite en avance : pause jusqu\'a etre rattrape (jamais de retour en arriere)',
       GAME_CLOCK.clock_speed == 0 and GAME_CLOCK.advanced == [600] and session.clock_ahead)
send({'kind': 'clock', 'seconds': 100580.0, 'speed': 3})
pump_until(lambda: GAME_CLOCK.clock_speed == 3, extra=host_side)
report('rattrape : reprend a la vitesse de l\'hote', GAME_CLOCK.clock_speed == 3 and not session.clock_ahead)
for bad in ({'seconds': 'x', 'speed': 1}, {'seconds': 1.0, 'speed': 9}, {'seconds': -5.0, 'speed': 1},
            {'seconds': float('nan'), 'speed': 1}):
    data = {'kind': 'clock'}
    data.update(bad)
    send(data)
pump_for(0.15, extra=host_side)
report('heures invalides ignorees', GAME_CLOCK.clock_speed == 3 and GAME_CLOCK.advanced == [600])

GAME_CLOCK.seconds = 100580.0 - 120.0                               # 2 min de jeu de retard
send({'kind': 'clock', 'seconds': 100580.0, 'speed': 3})
pump_until(lambda: len(GAME_CLOCK.advanced) == 2, extra=host_side)
report('2 minutes de jeu de retard : rattrapees (ecart tolere plus petit)',
       GAME_CLOCK.advanced[-1:] == [120])

# Boutons de vitesse de l'invite : la demande part a l'hote.
del inbox[:]
GAME_CLOCK.set_clock_speed(2, source=GameSpeedChangeSource.GAMEPLAY)      # bouton vitesse 2
GAME_CLOCK.push_speed(0, source=GameSpeedChangeSource.GAMEPLAY)           # bouton pause
GAME_CLOCK.pop_speed(0, source=GameSpeedChangeSource.GAMEPLAY)            # reprise
GAME_CLOCK.push_speed(0, source=GameSpeedChangeSource.UI_MODAL)           # fenetre : pas un bouton
pump_until(lambda: len(events('speed_request')) >= 3, extra=host_side)
pump_for(0.1, extra=host_side)
report('invite : vitesse 2, pause, reprise envoyees a l\'hote (pas les fenetres)',
       [e['speed'] for e in events('speed_request')] == [2, 0, 2], str(events('speed_request')))
GAME_CLOCK.speed_controllers[GameSpeedChangeSource.UI_MODAL][:] = []
GAME_CLOCK._update()

del _CheatOutput.lines[:]
mod.mp_positions()
text = '\n'.join(_CheatOutput.lines)
report('mp.positions affiche la synchro (argent, heure, double)',
       'Argent :' in text and 'vitesse de l\'hote 3' in text and 'Double de l\'autre joueur' in text, text[-200:])

# --- 7. Fin de session : la vitesse de l'hote est retiree -------------------------------------
mod.mp_disconnect()
report('mp.disconnect : vitesse de l\'hote retiree, le joueur reprend la main',
       GAME_CLOCK.situation_speeds() == [] and GAME_CLOCK.clock_speed == 2)       # dernier bouton du joueur
report('aucune erreur de pompe', mod._pump['error'] is None, str(mod._pump['error']))

# --- Fin -------------------------------------------------------------------------------------
peer.close()
shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
