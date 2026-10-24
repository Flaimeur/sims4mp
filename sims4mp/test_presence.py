# Sims 4 Multiplayer - test hors jeu de la presence (0.18.0) : l'invite a sur le lot les memes
# Sims que l'hote (famille entiere, animaux, visiteurs), sauf le Sim qu'il controle.
# Compatible Python 3.7. A lancer avec :  py -3.7 test_presence.py

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


commands = module('sims4.commands', Command=lambda *a, **k: (lambda f: f),
                  CommandType=types.SimpleNamespace(Live='Live'), CheatOutput=lambda connection: print)
module('sims4', commands=commands)


class _Zone(object):
    def update(self, *args):
        return 'update'

    def on_loading_screen_animation_finished(self):
        return 'loaded'


module('zone', Zone=_Zone)

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import protocol  # noqa: E402
import sims4mp_hello as mod  # noqa: E402

results = []
mod.show_notification = lambda title, text, *args: None
TMP = tempfile.mkdtemp(prefix='sims4mp_presence_')
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


# --- Faux lot : Sims presents ici, Sims connus de la partie ----------------------------------
ZONE = 555
present = {}                 # sim_id -> (x, y, z)
known = {1, 2, 3, 4, 50, 60, 70}
spawned, destroyed = [], []


def spawn(sim_id, x, y, z):
    if sim_id not in known:
        return 'inconnu'
    if sim_id in present:
        return 'deja'
    present[sim_id] = (x, y, z)
    spawned.append(sim_id)
    return 'ok'


def despawn(sim_id):
    if sim_id not in present:
        return False
    del present[sim_id]
    destroyed.append(sim_id)
    return True


mod.bridge_current_zone_id = lambda: ZONE
mod.bridge_instanced_sim_ids = lambda: sorted(present)
mod.bridge_spawn_sim = spawn
mod.bridge_despawn_sim = despawn
mod.bridge_sim_snapshot = lambda sim_id: {'sim_id': sim_id, 'name': 'Sim {}'.format(sim_id), 'zone_id': ZONE,
                                          'x': present[sim_id][0], 'y': 0.0, 'z': present[sim_id][2],
                                          'level': 0, 'action': None}
mine = {'id': 2}
mod._my_active_id = lambda: mine['id']
mod._gate['waiting'] = False


def roster(*sims, zone=ZONE):
    return {'kind': 'roster', 'zone_id': zone,
            'list': [{'sim_id': s, 'name': 'Sim {}'.format(s), 'zone_id': zone, 'x': 10.0 + s, 'y': 0.0,
                      'z': 5.0, 'level': 0, 'action': None} for s in sims]}


# --- 1. Hote : liste envoyee toutes les 5 s ---------------------------------------------------
host = mod.NetSession('host', Endpoint())
host.handshake_done = True
present.update({1: (1.0, 0, 1.0), 3: (3.0, 0, 3.0), 50: (5.0, 0, 5.0)})      # famille (1, 3) + animal 50
mod._roster_tick(host, 100.0)
mod._roster_tick(host, 102.0)
sent = [m['data'] for m in host.endpoint.sent if m['data'].get('kind') == 'roster']
report('hote : liste de tous les Sims presents, au plus une toutes les {:.0f} s'.format(mod.ROSTER_INTERVAL),
       len(sent) == 1 and [e['sim_id'] for e in sent[0]['list']] == [1, 3, 50] and sent[0]['zone_id'] == ZONE)
mod._roster_tick(host, 105.5)
report('hote : nouvelle liste apres {:.0f} s'.format(mod.ROSTER_INTERVAL),
       len([m for m in host.endpoint.sent if m['data'].get('kind') == 'roster']) == 2)
client_side = mod.NetSession('client', Endpoint())
client_side.handshake_done = True
mod._roster_tick(client_side, 100.0)
report('invite : n\'envoie jamais de liste', client_side.endpoint.sent == [])

# --- 2. Invite : recopie la presence de l'hote ------------------------------------------------
present.clear()
present.update({2: (0.0, 0, 0.0), 60: (6.0, 0, 6.0), 70: (7.0, 0, 7.0)})      # 2 : Sim de l'invite
guest = mod.NetSession('client', Endpoint())
guest.handshake_done = True
mod._handle_roster(guest, roster(1, 3, 4, 50))
report('au plus {} actions par liste (pas de va-et-vient)'.format(mod.ROSTER_ACTIONS),
       len(spawned) + len(destroyed) == mod.ROSTER_ACTIONS and spawned == [1, 3], str((spawned, destroyed)))
report('Sims de l\'hote apparus a leur place chez l\'hote', present[1] == (11.0, 0.0, 5.0))
mod._handle_roster(guest, roster(1, 3, 4, 50))
report('liste suivante : famille complete et animal, visiteurs d\'ici retires',
       spawned == [1, 3, 4, 50] and destroyed == [], str((spawned, destroyed)))
mod._handle_roster(guest, roster(1, 3, 4, 50))
report('visiteurs presents seulement chez l\'invite : retires', sorted(destroyed) == [60, 70],
       str(destroyed))
report('le Sim controle par l\'invite n\'est jamais retire', 2 in present)
report('compteurs', guest.roster_spawned == 4 and guest.roster_despawned == 2)

# --- 3. Cas limites ----------------------------------------------------------------------------
before = (list(spawned), list(destroyed))
mod._handle_roster(guest, roster(1, 3, 4, 50, zone=999))
report('l\'hote sur un autre lot : rien ne change ici', (spawned, destroyed) == before)
mod._handle_roster(guest, roster(1, 3, 4, 50, 99))
mod._handle_roster(guest, roster(1, 3, 4, 50, 99))
report('Sim inconnu dans cette partie : essaye une fois, puis ignore (sauvegarde differente)',
       99 in guest.roster_unknown and 99 not in present and spawned.count(99) == 0)
del present[4]                                                     # le jeu de l'invite l'a fait partir
mod._handle_roster(guest, roster(1, 3, 4, 50))
report('un Sim deja remis puis reparti : pas retente avant {:.0f} s'.format(mod.ROSTER_RETRY),
       4 not in present)
guest.roster_retry[4] = 0.0
mod._handle_roster(guest, roster(1, 3, 4, 50))
report('... puis retente', 4 in present)
mod._gate['waiting'] = True
present.pop(1)
mod._handle_roster(guest, roster(1, 3, 4, 50))
report('pause d\'attente de l\'autre joueur : rien ne change', 1 not in present)
mod._gate['waiting'] = False
for bad in ({'kind': 'roster', 'zone_id': ZONE, 'list': 'x'},
            {'kind': 'roster', 'zone_id': ZONE, 'list': [{'sim_id': 'x'}] * (mod.ROSTER_MAX + 1)}):
    mod._handle_roster(guest, bad)
report('listes mal formees ignorees', 1 not in present)
lines = '\n'.join(mod.sync_lines(guest))
report('etat de la synchro : ligne de presence', 'Presence (comme chez l\'hote) : 5 Sim(s) apparu(s), 2 retire(s), '
       '1 inconnu(s) ici' in lines, lines[-300:])

shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
