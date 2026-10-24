# Sims 4 Multiplayer - test hors jeu des ordres des joueurs (M5) et des besoins.
# Compatible Python 3.7. A lancer avec :  py -3.7 test_orders.py
#
# Faux modules du jeu : file d'attente (InteractionQueue.append), contexte
# d'interaction, gestionnaires d'objets / d'instances / de Sims, commodites.
# Ce PC est l'hote ; l'autre joueur est un transport.Client local.

import os
import shutil
import socket
import sys
import tempfile
import time
import types

# --- Faux modules du jeu ------------------------------------------------------

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


class Vector3(object):
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


math_module = module('sims4.math', Vector3=Vector3)
resources = module('sims4.resources', Types=types.SimpleNamespace(INTERACTION='INTERACTION', STATISTIC='STATISTIC'))
module('sims4', commands=commands, math=math_module, resources=resources)


class _Zone(object):
    def update(self, *args):
        return 'update'

    def on_loading_screen_animation_finished(self):
        return 'loaded'


module('zone', Zone=_Zone)


class Distributor(object):
    events = []

    def add_event(self, msg_id, msg, immediate=False):
        Distributor.events.append((msg_id, msg))


module('distributor')
module('distributor.system', Distributor=Distributor)
Consts_pb2 = types.SimpleNamespace(MSG_TRAVEL_SIMS_TO_ZONE=184)
module('protocolbuffers', Consts_pb2=Consts_pb2)
TRAVELS = []                                      # voyages lances par world.travel_service
module('world')
module('world.travel_service', travel_sims_to_zone=lambda sim_ids, zone_id: TRAVELS.append((sim_ids, zone_id)))
ZONES = {555: 'Maison Dupont', 777: 'Bar du Quai'}   # lots de la partie (persistence_service)


class InteractionContext(object):
    SOURCE_PIE_MENU, SOURCE_AUTONOMY, SOURCE_SCRIPT, SOURCE_SCRIPT_WITH_USER_INTENT = 1, 2, 3, 4

    def __init__(self, sim, source, priority, **kwargs):
        self.sim, self.source, self.priority = sim, source, priority


module('interactions')
module('interactions.context', InteractionContext=InteractionContext)
module('interactions.priority', Priority=types.SimpleNamespace(Low='Low', High='High'))


class TestResult(object):
    def __init__(self, result, reason=None):
        self.result = result
        self.reason = reason

    def __bool__(self):
        return self.result


TestResult.TRUE = TestResult(True)
module('event_testing')
module('event_testing.results', TestResult=TestResult)


class InteractionQueue(object):
    def __init__(self, sim):
        self.sim = sim
        self.items = []

    def append(self, interaction):
        if getattr(self, 'full', False):
            return TestResult(False, 'Interaction queue is full.')
        self.items.append(interaction)
        return TestResult.TRUE


module('interactions.interaction_queue', InteractionQueue=InteractionQueue)


class Affordance(object):
    is_super = True


def affordance(name, guid, is_super=True):
    return type(name, (Affordance,), {'guid64': guid, 'is_super': is_super})


SIT = affordance('sit_Chair', 500)
SLEEP = affordance('sleep_Bed', 600)
GOHERE = affordance('terrain_GoHere', 700)
CHAT = affordance('social_Chat', 800)
MIXER = affordance('mixer_Joke', 900, is_super=False)
AFFORDANCES = {a.guid64: a for a in (SIT, SLEEP, GOHERE, CHAT)}


class Interaction(object):
    def __init__(self, affordance, target, source=InteractionContext.SOURCE_PIE_MENU):
        self.affordance, self.target, self.source = affordance, target, source

    @property
    def is_user_directed(self):
        return self.source in (InteractionContext.SOURCE_PIE_MENU, InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT)


class GameObject(object):
    is_sim = is_terrain = is_part = False

    def __init__(self, oid):
        self.id = oid


class Part(GameObject):
    is_part = True

    def __init__(self, owner):
        self.part_owner = owner
        self.id = owner.id * 1000 + 1


class TerrainPoint(object):
    is_terrain = True
    is_sim = is_part = False

    def __init__(self, location):
        self.location = location
        if isinstance(location, tuple):
            self.position, surface = location
            self.level = surface.level
        else:
            self.position, self.level = location, 0


class Stat(object):
    is_skill = False

    def __init__(self, guid, value, visible=True, skill=False):
        self.guid64, self.value, self.is_visible, self.is_skill = guid, value, visible, skill
        self.stat_type = self

    def get_value(self):
        return self.value


class Tracker(object):
    def __init__(self, stats):
        self.stats = stats
        self.writes = []

    def get_all_commodities(self):
        return list(self.stats)

    def set_value(self, stat_type, value):
        stat_type.value = value
        self.writes.append((stat_type.guid64, value))


class FakeSimInfo(object):
    def __init__(self, sim_id, first):
        self.sim_id, self.first_name, self.last_name = sim_id, first, ''
        self.instance = None
        self.commodity_tracker = Tracker([Stat(1, 50.0), Stat(2, -20.0), Stat(3, 10.0, visible=False),
                                          Stat(4, 300.0, skill=True)])

    def get_sim_instance(self, allow_hidden_flags=None):
        return self.instance


class FakeSim(object):
    is_sim = True
    is_terrain = is_part = False

    def __init__(self, sim_info, x):
        self.sim_info = sim_info
        self.id = sim_info.sim_id
        sim_info.instance = self
        self.position = Vector3(x, 0.0, 0.0)
        self.level = 0
        self.queue = InteractionQueue(self)
        self.pushed = []

    def push_super_affordance(self, affordance, target, context):
        # Comme le jeu : l'ordre passe par la file d'attente du Sim.
        self.pushed.append((affordance, target, context))
        return self.queue.append(Interaction(affordance, target, context.source))


class FakeClient(object):
    active_sim = None


CLIENT = FakeClient()
SIM_INFOS = {}
OBJECTS = {}
INSTANCED = []
module('services', client_manager=lambda: types.SimpleNamespace(get_first_client=lambda: CLIENT),
       sim_info_manager=lambda: types.SimpleNamespace(
           get=SIM_INFOS.get, instanced_sims_gen=lambda allow_hidden_flags=None: list(INSTANCED)),
       object_manager=lambda zone_id=None: types.SimpleNamespace(get=OBJECTS.get),
       get_instance_manager=lambda kind: types.SimpleNamespace(get=AFFORDANCES.get),
       current_zone_id=lambda: 555, active_household=lambda: None,
       get_persistence_service=lambda: types.SimpleNamespace(
           get_zone_proto_buff=lambda zone_id: types.SimpleNamespace(name=ZONES[zone_id]) if zone_id in ZONES
           else None))
module('objects', ALL_HIDDEN_REASONS='ALL')
module('objects.terrain', TerrainPoint=TerrainPoint)
module('routing', SurfaceIdentifier=lambda zone, level, kind: types.SimpleNamespace(level=level),
       SurfaceType=types.SimpleNamespace(SURFACETYPE_WORLD='WORLD'))
module('server')
module('server.pick_info', PickType=types.SimpleNamespace(PICK_TERRAIN='TERRAIN'))
module('server_commands')
module('server_commands.sim_commands',
       _build_terrain_interaction_target_and_context=lambda sim, pos, surface, pick, cls: (
           cls((pos, surface)), InteractionContext(sim, InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT, 'High')),
       CommandTuning=types.SimpleNamespace(TERRAIN_GOHERE_AFFORDANCE=GOHERE, TERRAIN_TELEPORT_AFFORDANCE=GOHERE))

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import protocol  # noqa: E402
import sims4mp_hello as mod  # noqa: E402
mod._mirror['wanted'] = False                        # ancienne synchro (option A) : mp.mirror off depuis 0.21.0
import transport  # noqa: E402

results = []
notes = []
mod.show_notification = lambda title, text, *args: notes.append(text)
mod.PUMP_INTERVAL = 0.0
mod.POSITION_INTERVAL = 0.02
mod.NEEDS_INTERVAL = 0.05
TMP = tempfile.mkdtemp(prefix='sims4mp_orders_')
mod.LOG_PATH = os.path.join(TMP, 'sims4mp.log')
mod._mods_dir = TMP


def report(step, ok, detail=''):
    results.append(bool(ok))
    print('[{}] {}{}'.format('OK' if ok else 'ECHEC', step, ' - ' + detail if detail else ''))


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]
    finally:
        s.close()


inbox = []


def presence():
    peer.send(protocol.make_message(protocol.EVENT, {'kind': 'presence'}))


def pump_until(until, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mod.pump_tick()
        inbox.extend(peer.poll())
        presence()
        if until():
            return True
        time.sleep(0.005)
    return False


def pump_for(seconds):
    pump_until(lambda: False, timeout=seconds)


def events(kind):
    return [v['data'] for k, v in inbox if k == 'message' and v['type'] == protocol.EVENT
            and v['data'].get('kind') == kind]


def send(data):
    peer.send(protocol.make_message(protocol.EVENT, data))


mine = FakeSimInfo(1001, 'Elise')
other = FakeSimInfo(2002, 'Alex')
npc_info = FakeSimInfo(3003, 'Voisin')
SIM_INFOS.update({1001: mine, 2002: other, 3003: npc_info})
my_sim = FakeSim(mine, 0.0)
double = FakeSim(other, 5.0)
npc = FakeSim(npc_info, 20.0)
INSTANCED.extend([my_sim, double, npc])
CLIENT.active_sim = my_sim
chair, sofa, bed = GameObject(77), GameObject(88), GameObject(99)
OBJECTS.update({77: chair, 88: sofa, 99: bed})

report('file d\'attente enveloppee', getattr(InteractionQueue.append, '_sims4mp_hook', False))

port = free_port()
mod.mp_host(port)
peer = transport.Client('127.0.0.1', port)
peer.connect()
peer.send(protocol.hello(mod.MOD_VERSION))
pump_until(lambda: mod._session.handshake_done and not mod._gate['waiting'])
session = mod._session
send({'kind': 'position', 'sim_id': 2002, 'name': 'Alex', 'zone_id': 555, 'x': 5.0, 'y': 0.0, 'z': 0.0,
      'level': 0, 'action': None})
pump_until(lambda: session.remote_position is not None)
pump_for(0.1)
del inbox[:]                       # avant de connaitre le Sim de l'invite, l'hote faisait foi pour tous
session.needs_sent.clear()
session.sims_sent.clear()

# --- 1. Clics du joueur envoyes au moment du clic -----------------------------------------
my_sim.queue.append(Interaction(SIT, chair))
pump_until(lambda: events('order'))
first = events('order')[0] if events('order') else {}
report('clic « s\'asseoir » envoye aussitot (Sim, action, cible objet, identifiant)',
       first.get('sim_id') == 1001 and first.get('affordance') == 500 and first.get('target') == {'t': 'obj', 'id': 77}
       and first.get('name') == 'sit_Chair' and first.get('id') == 'host-1')
my_sim.queue.append(Interaction(SLEEP, Part(sofa)))
my_sim.queue.append(Interaction(CHAT, double))
my_sim.queue.append(Interaction(GOHERE, TerrainPoint(Vector3(3.0, 0.5, 4.0))))
pump_until(lambda: len(events('order')) >= 4)
targets = [e['target'] for e in events('order')[1:4]]
report('cible partie d\'objet -> objet entier, cible Sim, point de terrain',
       targets == [{'t': 'obj', 'id': 88}, {'t': 'sim', 'id': 2002},
                   {'t': 'terrain', 'x': 3.0, 'y': 0.5, 'z': 4.0, 'level': 0}], str(targets))
count = len(events('order'))
my_sim.queue.append(Interaction(SIT, chair, source=InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT))
my_sim.queue.append(Interaction(MIXER, double))
pump_for(0.15)
report('ordres de script et mixers non envoyes', len(events('order')) == count)
my_sim.queue.append(Interaction(SIT, chair, source=InteractionContext.SOURCE_AUTONOMY))
pump_until(lambda: len(events('order')) > count)
auto = events('order')[-1] if len(events('order')) > count else {}
report('M6 : autonomie d\'un Sim dont l\'hote fait foi envoyee (marquee autonomie)',
       auto.get('auto') is True and auto.get('sim_id') == 1001 and auto.get('affordance') == 500)

# --- 2. Ordres recus de l'autre joueur, rejoues --------------------------------------------
before = len(events('order'))
send({'kind': 'order', 'id': 'client-1', 'sim_id': 2002, 'affordance': 600, 'name': 'sleep_Bed',
      'target': {'t': 'obj', 'id': 99}})
pump_until(lambda: double.pushed)
pushed = double.pushed[-1] if double.pushed else (None, None, None)
report('ordre recu rejoue : meme Sim, meme action, meme objet, contexte « intention du joueur »',
       pushed[0] is SLEEP and pushed[1] is bed and pushed[2].source == InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT
       and pushed[2].priority == 'High')
pump_for(0.15)
report('ordre rejoue jamais renvoye a l\'autre PC (pas d\'echo)', len(events('order')) == before)
send({'kind': 'order', 'id': 'client-1', 'sim_id': 2002, 'affordance': 600, 'name': 'sleep_Bed',
      'target': {'t': 'obj', 'id': 99}})
pump_for(0.15)
report('meme identifiant recu deux fois : rejoue une seule fois', len(double.pushed) == 1
       and session.orders_replayed == 1)
send({'kind': 'order', 'id': 'client-2', 'sim_id': 2002, 'affordance': 700, 'name': 'terrain_GoHere',
      'target': {'t': 'terrain', 'x': 9.0, 'y': 0.0, 'z': 2.0, 'level': 0}})
pump_until(lambda: len(double.pushed) == 2)
report('marche cliquee chez l\'autre : rejouee vers le meme point',
       len(double.pushed) == 2 and double.pushed[1][0] is GOHERE and double.pushed[1][1].position.x == 9.0)
send({'kind': 'order', 'id': 'client-3', 'sim_id': 2002, 'affordance': 12345, 'name': 'pack_Inconnu',
      'target': {'t': 'none'}})
send({'kind': 'order', 'id': 'client-4', 'sim_id': 2002, 'affordance': 500, 'name': 'sit_Chair',
      'target': {'t': 'obj', 'id': 4242}})
pump_until(lambda: session.orders_failed == 2)
report('action inconnue ou cible absente : non rejouee, raison notee',
       session.orders_failed == 2 and 'cible absente' in session.last_order)
for bad in ({'id': 5, 'sim_id': 2002, 'affordance': 500, 'target': {'t': 'none'}},
            {'id': 'x', 'sim_id': 2002, 'affordance': 500, 'target': {'t': 'shell'}},
            {'id': 'y', 'sim_id': 'a', 'affordance': 500, 'target': {'t': 'none'}},
            {'id': 'z', 'sim_id': 2002, 'affordance': 500, 'target': {'t': 'terrain', 'x': 'nan'}}):
    send(dict(bad, kind='order'))
pump_for(0.15)
report('ordres mal formes ignores', session.orders_replayed == 2 and session.orders_failed == 2)
mod._maybe_walk(session, time.monotonic())
report('apres une action rejouee : le double n\'est pas recale pendant {:.0f} s'.format(mod.ACTION_HOLD),
       'pas de recalage' in session.walk_status, session.walk_status)

# --- 3. Besoins ------------------------------------------------------------------------------
pump_until(lambda: {e['sim_id'] for e in events('needs')} >= {1001, 3003})
by_sim = {e['sim_id']: e for e in events('needs')}
needs = by_sim.get(1001, {})
report('hote : besoins visibles de son Sim envoyes (pas les caches, pas les competences)',
       needs.get('values') == {'1': 50.0, '2': -20.0}, str(needs))
report('M6 : besoins du PNJ aussi (l\'hote fait foi), pas ceux du Sim de l\'invite',
       3003 in by_sim and 2002 not in by_sim)
count = len(events('needs'))
pump_for(0.2)
report('besoins inchanges : pas de renvoi avant {:.0f} s'.format(mod.NEEDS_RESEND), len(events('needs')) == count)
send({'kind': 'needs', 'sim_id': 2002, 'values': {'1': 12.5, '2': -20.4, '999': 3.0}})
pump_until(lambda: other.commodity_tracker.writes)
report('besoins du Sim de l\'autre recopies (ecart > {} seulement)'.format(mod.NEEDS_EPSILON),
       other.commodity_tracker.writes == [(1, 12.5)])
send({'kind': 'needs', 'sim_id': 1001, 'values': {'1': 0.0}})
pump_for(0.15)
report('besoins de mon propre Sim recus : ignores (je fais foi)', mine.commodity_tracker.writes == [])
for bad in ({'sim_id': 2002, 'values': {'²': 1.0}}, {'sim_id': 2002, 'values': 'x'},
            {'sim_id': 2002, 'values': {'1': float('nan')}}):
    send(dict(bad, kind='needs'))
pump_for(0.15)
report('besoins mal formes ignores', other.commodity_tracker.writes == [(1, 12.5)])
client = types.SimpleNamespace(role='client', remote_position={'sim_id': 1001})
report('invite : meme Sim que l\'hote -> l\'hote fait foi ; Sim different -> l\'invite fait foi',
       not mod._needs_authority(client, 1001, 1001)
       and mod._needs_authority(types.SimpleNamespace(role='client', remote_position={'sim_id': 2002}), 1001, 1001))

# --- 4. M6 : l'hote fait foi pour tous les Sims que personne ne controle ------------------------
report('qui fait foi : hote pour son Sim et le PNJ, invite pour le sien',
       [mod.sim_owner(session, s, 1001) for s in (1001, 3003, 2002)] == ['host', 'host', 'client'])
refused = double.queue.append(Interaction(SIT, chair, source=InteractionContext.SOURCE_AUTONOMY))
report('autonomie du Sim de l\'invite refusee chez l\'hote (l\'invite fait foi)',
       not refused and session.autonomy_refused == 1)
before = len(events('order'))
npc.queue.append(Interaction(SLEEP, bed, source=InteractionContext.SOURCE_AUTONOMY))
pump_until(lambda: len(events('order')) > before)
sent = events('order')[-1]
report('autonomie du PNJ envoyee a l\'invite', sent.get('sim_id') == 3003 and sent.get('auto') is True)
pump_until(lambda: any(e['sim_id'] == 3003 for s in events('sims') for e in s['list']))
listed = {e['sim_id'] for s in events('sims') for e in s['list']}
report('positions des autres Sims envoyees (PNJ ; ni mon Sim, ni celui de l\'invite)', listed == {3003}, str(listed))
replayed = session.orders_replayed
send({'kind': 'order', 'id': 'client-9', 'sim_id': 1001, 'affordance': 500, 'name': 'sit_Chair',
      'target': {'t': 'obj', 'id': 77}, 'auto': True})
send({'kind': 'order', 'id': 'client-10', 'sim_id': 2002, 'affordance': 500, 'name': 'sit_Chair',
      'target': {'t': 'obj', 'id': 77}, 'auto': True})
pump_until(lambda: session.orders_replayed > replayed)
pump_for(0.1)
last = double.pushed[-1]
report('autonomie recue : ignoree pour un Sim dont je fais foi, rejouee en priorite basse sinon',
       session.orders_replayed == replayed + 1 and last[0] is SIT
       and last[2].source == InteractionContext.SOURCE_SCRIPT and last[2].priority == 'Low',
       '{} -> {} ; {} {} {} ; {} ; echecs {}'.format(replayed, session.orders_replayed, last[0].__name__,
                                                     last[2].source, last[2].priority, session.last_order,
                                                     session.orders_failed))
guest = mod.NetSession('client', types.SimpleNamespace(is_connected=True))
guest.handshake_done = True
guest.remote_position = {'sim_id': 5005}                        # l'hote controle un autre Sim
npc.position = Vector3(20.0, 0.0, 0.0)
count = len(npc.pushed)
mod._handle_sims(guest, {'list': [{'sim_id': 3003, 'name': 'Voisin', 'zone_id': 555, 'x': 30.0, 'y': 0.0,
                                   'z': 0.0, 'level': 0, 'action': None},
                                  {'sim_id': 1001, 'name': 'Elise', 'zone_id': 555, 'x': 99.0, 'y': 0.0,
                                   'z': 0.0, 'level': 0, 'action': None}]})
report('invite : PNJ suivi (marche vers la position de l\'hote), son propre Sim ignore',
       len(npc.pushed) == count + 1 and npc.pushed[-1][1].position.x == 30.0 and 1001 not in guest.sims_remote)
npc.position = Vector3(29.0, 0.0, 0.0)
guest.sims_walk.clear()
real_push = npc.push_super_affordance
npc.push_super_affordance = lambda *a: TestResult(False)       # occupe (assis...) : marche refusee
mod._follow_sim(guest, 3003, time.monotonic())
npc.push_super_affordance = real_push
report('marche refusee a faible ecart : laisse en place, pas de pose directe',
       guest.sims_status[3003].startswith('occupe') and npc.position.x == 29.0)

# --- 5. Correctifs 0.13.1 : pas d'inondation, pas de voyage rejoue ------------------------------
CHAT_PICKER = affordance('SocialPickerSI', 1200)
before = len(events('order'))
npc.queue.full = True
for _ in range(5):
    npc.queue.append(Interaction(CHAT_PICKER, double, source=InteractionContext.SOURCE_AUTONOMY))
npc.queue.full = False
pump_for(0.1)
report('action autonome refusee par le jeu (file pleine) : jamais envoyee', len(events('order')) == before)
session.auto_sent.clear()
for _ in range(5):
    npc.queue.append(Interaction(CHAT_PICKER, double, source=InteractionContext.SOURCE_AUTONOMY))
pump_until(lambda: len(events('order')) > before)
pump_for(0.1)
report('meme action autonome proposee 5 fois de suite : envoyee une seule fois',
       len(events('order')) == before + 1 and session.auto_skipped >= 4)
TRAVEL = affordance('Travel_DummyInteractions_Phone_TravelWith', 1300)
before = len(events('order'))
my_sim.queue.append(Interaction(TRAVEL, None))
pump_for(0.15)
report('voyage choisi par le joueur : pas rejoue chez l\'autre (le lot part au depart reel du voyage)',
       len(events('order')) == before and not events('travel'))
del notes[:]
send({'kind': 'travel', 'sim_id': 2002, 'name': 'Travel_DummyInteractions_Phone_TravelWith'})
send({'kind': 'order', 'id': 'client-99', 'sim_id': 2002, 'affordance': 1300,
      'name': 'Travel_DummyInteractions_Phone_TravelWith', 'target': {'t': 'none'}})
pump_until(lambda: any('autre lot' in n for n in notes))
pump_for(0.1)
report('voyage de l\'autre : alerte, et un voyage recu d\'un ancien mod n\'est jamais rejoue',
       any('L\'invité part sur un autre lot' in n for n in notes)
       and not any(p[0].__name__ == TRAVEL.__name__ for p in double.pushed))

del _CheatOutput.lines[:]
mod.mp_positions()
text = '\n'.join(_CheatOutput.lines)
report('mp.positions : actions et besoins', 'Actions : 7 envoyee(s), 3 rejouee(s), 2 non rejouee(s)' in text
       and 'Autres Sims (ce PC fait foi)' in text and 'autonomie refusee ici 1 fois' in text
       and 'Besoins : 1 valeur' in text, text[-300:])
report('aucune erreur de pompe', mod._pump['error'] is None, str(mod._pump['error']))

# --- 6. Correctifs 0.17.1 : pas de recalage en boucle, actions impossibles plus rejouees ----------
# Ici la teleportation du faux jeu ne deplace pas le Sim : chaque recalage est « sans effet ».
guest.sims_fix.clear()
guest.sims_walk.clear()
guest.action_hold.clear()
npc.position = Vector3(20.0, 0.0, 0.0)
guest.sims_remote[3003] = dict(guest.sims_remote[3003], x=80.0)      # 60 d'ecart : teleportation
t0 = 1000.0
base = guest.teleports
mod._follow_sim(guest, 3003, t0)
mod._follow_sim(guest, 3003, t0 + 1)
mod._follow_sim(guest, 3003, t0 + 5)
report('PNJ loin : une teleportation, puis aucune autre avant {:.0f} s'.format(mod.TELEPORT_GAP),
       guest.teleports == base + 1, str(guest.teleports - base))
mod._follow_sim(guest, 3003, t0 + 11)
mod._follow_sim(guest, 3003, t0 + 12)
report('2 teleportations sans effet : Sim laisse en place, note une fois',
       guest.teleports == base + 2 and guest.sims_paused == 1
       and guest.sims_status[3003] == 'recalage sans effet : laisse en place')
for t in (t0 + 25, t0 + 40, t0 + 70):
    mod._follow_sim(guest, 3003, t)
report('pendant {:.0f} s : plus aucun recalage'.format(mod.FIX_PAUSE), guest.teleports == base + 2)
mod._follow_sim(guest, 3003, t0 + 12 + mod.FIX_PAUSE + 1)
report('apres la pause : nouvel essai', guest.teleports == base + 3)
npc.position = Vector3(79.0, 0.0, 0.0)                               # cette fois le Sim est arrive
mod._follow_sim(guest, 3003, t0 + 100)
report('recalage efficace : rien n\'est compte comme echec', guest.sims_fix[3003]['fails'] == 0
       and guest.sims_paused == 1)


class Unplayable(object):
    """Comme l'EnqueueResult du jeu pour put_down_anywhere chez l'autre PC."""

    def __bool__(self):
        return False

    def __str__(self):
        return ('<EnqueueResult: True <ExecuteResult: False: (Error instantiating affordance: __init__() missing '
                '7 required keyword-only arguments: \'slot_types_and_costs\')>>')


PUT_DOWN = affordance('put_down_anywhere', 1400)
AFFORDANCES[1400] = PUT_DOWN                                       # connue du faux jeu
calls = []
real_push = double.push_super_affordance
double.push_super_affordance = lambda *a: calls.append(a) or Unplayable()
skipped = session.unplayable_skipped
send({'kind': 'order', 'id': 'client-70', 'sim_id': 2002, 'affordance': 1400, 'name': 'put_down_anywhere',
      'target': {'t': 'none'}, 'auto': True})
pump_until(lambda: calls)
send({'kind': 'order', 'id': 'client-71', 'sim_id': 2002, 'affordance': 1400, 'name': 'put_down_anywhere',
      'target': {'t': 'none'}, 'auto': True})
pump_for(0.2)
double.push_super_affordance = real_push
report('action que le jeu ne sait pas recreer : essayee une fois, puis plus rejouee pendant la partie',
       len(calls) == 1 and 1400 in session.unplayable and session.unplayable_skipped == skipped + 1,
       '{} essai(s), ignores {} ; dernier ordre : {}'.format(len(calls), session.unplayable_skipped - skipped,
                                                            session.last_order))
with open(mod.LOG_PATH, encoding='utf-8') as handle:
    report('journal : une seule ligne pour cette action',
           handle.read().count('put_down_anywhere : le jeu ne sait pas recreer cette action ici') == 1)

# --- 7. Voyage a deux (0.19.0) ------------------------------------------------------------------
report('departs de voyage suivis (Distributor.add_event enveloppe)',
       getattr(Distributor.add_event, '_sims4mp_hook', False))
del inbox[:]
del Distributor.events[:]
Distributor().add_event(184, types.SimpleNamespace(zone_id=777, sim_ids=[1001]))
pump_until(lambda: events('travel'))
sent = events('travel')[-1] if events('travel') else {}
report('depart vers un autre lot : lot envoye a l\'autre joueur (id, nom, Sims), message du jeu transmis',
       sent.get('zone_id') == 777 and sent.get('lot') == 'Bar du Quai' and sent.get('sim_ids') == [1001]
       and sent.get('sim_id') == 1001 and len(Distributor.events) == 1, str(sent))
del inbox[:]
Distributor().add_event(184, types.SimpleNamespace(zone_id=555, sim_ids=[1001]))
Distributor().add_event(12, types.SimpleNamespace(zone_id=777, sim_ids=[1001]))
pump_for(0.15)
report('voyage vers le lot actuel ou autre message du jeu : rien envoye',
       not events('travel') and len(Distributor.events) == 3)

dialogs = []
mod.bridge_show_dialog = lambda title, text, choices, on_choice: dialogs.append((title, text, choices, on_choice))
send({'kind': 'travel', 'zone_id': 777, 'lot': 'Bar du Quai', 'sim_ids': [2002, 'x'], 'sim_id': 2002})
pump_until(lambda: dialogs)
send({'kind': 'travel', 'zone_id': 777, 'lot': 'Bar du Quai', 'sim_ids': [2002], 'sim_id': 2002})
pump_for(0.15)
title, text, choices, on_choice = dialogs[0] if dialogs else (None, '', (), None)
report('voyage de l\'autre : fenetre « Suivre sur le meme lot » (nom du lot de ma partie), une seule fois',
       len(dialogs) == 1 and title == 'Voyage à deux' and '« Bar du Quai »' in text
       and choices[0] == (mod.TRAVEL_FOLLOW, 'Suivre sur le même lot'), text)
on_choice(mod.TRAVEL_STAY)
report('« Rester ici » : aucun voyage', TRAVELS == [] and mod._travel['following'] is None)
on_choice(mod.TRAVEL_FOLLOW)
report('« Suivre » : mon Sim actif voyage vers le meme lot (world.travel_service)',
       TRAVELS == [((1001,), 777)] and mod._travel['following'] == 777, str(TRAVELS))
del inbox[:]
Distributor().add_event(184, types.SimpleNamespace(zone_id=777, sim_ids=[1001]))   # le jeu part
pump_for(0.15)
report('en suivant : pas d\'invitation renvoyee a l\'autre joueur', not events('travel'))
_Zone().on_loading_screen_animation_finished()
report('arrivee sur le lot : voyage termine', mod._travel['following'] is None)

del notes[:]
del dialogs[:]
send({'kind': 'travel', 'zone_id': 999, 'lot': 'Lot pirate', 'sim_id': 2002})
send({'kind': 'travel', 'zone_id': 555, 'lot': 'Maison Dupont', 'sim_id': 2002})
pump_until(lambda: len(notes) >= 2)
report('lot absent de ma partie : alerte, pas de fenetre ; mon lot : « vous rejoint »',
       not dialogs and any('introuvable' in n for n in notes) and any('vous rejoint sur ce lot' in n for n in notes),
       str(notes))

guest_lock = mod.NetSession('client', types.SimpleNamespace(is_connected=True))
guest_lock.handshake_done = True
locks = []
mod.bridge_lock_save = lambda holder: locks.append('lock')
mod.bridge_unlock_save = lambda holder: locks.append('unlock')
mod._save_lock_tick(guest_lock)
mod._travel['following'] = 777
mod._save_lock_tick(guest_lock)
mod._travel['following'] = None
mod._save_lock_tick(guest_lock)
report('invite : sauvegarde liberee pendant le voyage pour suivre, reverrouillee apres',
       locks == ['lock', 'unlock', 'lock'], str(locks))
mod._save_lock_tick(None)
report('aucune erreur de pompe (voyage)', mod._pump['error'] is None, str(mod._pump['error']))

peer.close()
mod._close_session()
shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
