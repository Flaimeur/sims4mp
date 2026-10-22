# Sims 4 Multiplayer - test hors jeu de la latence (0.15.0).
# Compatible Python 3.7. A lancer avec :  py -3.7 test_latency.py
#
# Vraies sockets sur 127.0.0.1 (transport.Server / transport.Client), sans thread :
# TCP_NODELAY regle par le mod, envoi immediat sans attendre le poll suivant.

import os
import shutil
import socket
import sys
import tempfile
import time
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
import transport  # noqa: E402
import sims4mp_hello as mod  # noqa: E402

results = []
mod.show_notification = lambda title, text, *args: None
TMP = tempfile.mkdtemp(prefix='sims4mp_latency_')
mod.LOG_PATH = os.path.join(TMP, 'sims4mp.log')


def report(step, ok, detail=''):
    results.append(bool(ok))
    print('[{}] {}{}'.format('OK' if ok else 'ECHEC', step, ' - ' + detail if detail else ''))


def log_text():
    with open(mod.LOG_PATH, encoding='utf-8') as handle:
        return handle.read()


def nodelay(sock):
    return sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0


def wait(until, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if until():
            return True
        time.sleep(0.005)
    return False


# --- Connexion reelle -------------------------------------------------------------------
server = transport.Server('127.0.0.1', 0)
server.start()
client = transport.Client('127.0.0.1', server.port)
client.connect()
server_events, client_events = [], []
wait(lambda: (server_events.extend(server.poll()), client_events.extend(client.poll()))
     and server.is_connected and client.is_connected)
host = mod.NetSession('host', server)
guest = mod.NetSession('client', client)
report('connexion locale etablie', server.is_connected and client.is_connected)

# --- 1. TCP_NODELAY ---------------------------------------------------------------------
before = nodelay(server.conn.sock) or nodelay(client.conn.sock)
mod._set_nodelay(host)
mod._set_nodelay(guest)
mod._set_nodelay(host)                                 # deja reglee : rien de plus
report('TCP_NODELAY regle sur les deux sockets (pas avant)',
       not before and nodelay(server.conn.sock) and nodelay(client.conn.sock))
report('reglage note une seule fois par socket', log_text().count('TCP_NODELAY') == 2)

# --- 2. Envoi immediat ------------------------------------------------------------------
server.send(protocol.make_message(protocol.EVENT, {'kind': 'presence'}))
waiting = server.conn.wants_write()
mod._flush_now(host)
report('fin de passage : le message prepare part tout de suite', waiting and not server.conn.wants_write())
received = []
report('l\'autre PC le recoit sans nouveau poll de l\'envoyeur',
       wait(lambda: received.extend(client.poll()) or any(k == 'message' for k, _ in received)))

mod._session = host
host.handshake_done = True
mod._gate['waiting'] = False
order_id = mod.send_player_order({'sim_id': 1, 'affordance': 5, 'name': 'seating_Sit',
                                  'target': {'t': 'none'}, 'auto': False})
report('ordre du joueur : parti au clic, sans attendre la pompe',
       order_id == 'host-1' and not server.conn.wants_write())

# --- 3. Sans connexion -----------------------------------------------------------------
idle = mod.NetSession('client', transport.Client('127.0.0.1', 1))
mod._set_nodelay(idle)
mod._flush_now(idle)
report('sans connexion : rien a faire, aucune erreur', idle.nodelay_sock is None)
report('pompe plus frequente (20 ms)', mod.PUMP_INTERVAL == 0.02)

mod._session = None
client.close() if hasattr(client, 'close') else None
server.close()
shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
