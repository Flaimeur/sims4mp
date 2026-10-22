# Sims 4 Multiplayer - test hors jeu du prototype P1 (mesure du trafic
# simulation -> affichage, lecture seule). Compatible Python 3.7.
# A lancer avec :  py -3.7 test_traffic.py
#
# Faux module omega (comme omega.pyc : send(session_id, msg_id, data) appelle le
# natif et leve KeyError pour une session inconnue) et faux Consts_pb2.

import os
import shutil
import sys
import tempfile
import time
import types

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

SENT = []
SESSIONS = {0x1234}


def _native_send(session_id, msg_id, data):
    SENT.append((session_id, msg_id, data))
    if session_id not in SESSIONS:
        raise KeyError('Failed to find ZoneSessionContext for [ZoneSessionId: 0x{:016x}]'.format(session_id))
    return None


omega = types.ModuleType('omega')
omega.send = _native_send

protocolbuffers = types.ModuleType('protocolbuffers')
Consts_pb2 = types.ModuleType('protocolbuffers.Consts_pb2')
Consts_pb2.MSG_OBJECTS_VIEW_UPDATE = 4
Consts_pb2.MSG_UI_NOTIFICATION = 77
Consts_pb2.TELEMETRY_MONEY_CHEAT = 5                # pas un MSG_ : ignore
protocolbuffers.Consts_pb2 = Consts_pb2

sys.modules.update({'sims4': sims4, 'sims4.commands': commands, 'zone': zone, 'omega': omega,
                    'protocolbuffers': protocolbuffers, 'protocolbuffers.Consts_pb2': Consts_pb2})

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, 'sims4mp.log')
LOG_EXISTED = os.path.exists(LOG_FILE)

import sims4mp_hello as mod  # noqa: E402

results = []
TMP = tempfile.mkdtemp(prefix='sims4mp_traffic_')
mod.LOG_PATH = os.path.join(TMP, 'sims4mp.log')


def report(step, ok, detail=''):
    results.append(bool(ok))
    line = '[{}] {}'.format('OK' if ok else 'ECHEC', step)
    if detail:
        line += ' - ' + detail
    print(line)


def run(action=None):
    del _CheatOutput.lines[:]
    mod.mp_traffic(action)
    return '\n'.join(_CheatOutput.lines)


report('omega.send enveloppe au chargement', getattr(omega.send, '_sims4mp_hook', False)
       and mod._traffic['installed'])

# --- 1. Mesure arretee par defaut ---------------------------------------------------
omega.send(0x1234, 4, b'x' * 10)
report('arretee par defaut : rien compte, message transmis tel quel',
       mod._traffic['total'] == [0, 0] and SENT[-1] == (0x1234, 4, b'x' * 10))
report('jamais lancee : mp.traffic le dit', 'jamais lancee' in run())

# --- 2. Mesure lancee -----------------------------------------------------------------
run('on')
for size in (100, 300, 50):
    omega.send(0x1234, 4, b'v' * size)
omega.send(0x1234, 77, b'n' * 20)
omega.send(0x1234, 999, b'?' * 5)
report('compte par type : messages, octets, plus gros',
       mod._traffic['by_type'][4] == [3, 450, 300] and mod._traffic['by_type'][77] == [1, 20, 20]
       and mod._traffic['total'] == [5, 475])
report('chaque message transmis a l\'original sans changement', SENT[-5:] == [
    (0x1234, 4, b'v' * 100), (0x1234, 4, b'v' * 300), (0x1234, 4, b'v' * 50),
    (0x1234, 77, b'n' * 20), (0x1234, 999, b'?' * 5)])
text = run()
report('mp.traffic : noms MSG_ du jeu, tri par octets, sessions',
       'MSG_OBJECTS_VIEW_UPDATE (4) : 3 msg' in text and 'MSG_UI_NOTIFICATION (77)' in text
       and '? (999)' in text and '1234 : 5 msg' in text
       and text.index('MSG_OBJECTS_VIEW_UPDATE') < text.index('MSG_UI_NOTIFICATION'), text)

# --- 3. Comportement de l'original conserve -------------------------------------------
try:
    omega.send(0xdead, 4, b'z')
    raised = False
except KeyError:
    raised = True
report('session inconnue : la KeyError de l\'original remonte comme avant', raised)
original_record = mod.traffic_record
mod.traffic_record = lambda *args: 1 / 0
omega.send(0x1234, 4, b'ok')
mod.traffic_record = original_record
report('erreur de comptage : comptee, message quand meme transmis',
       mod._traffic['errors'] == 1 and SENT[-1] == (0x1234, 4, b'ok'))

# --- 4. Resume periodique et arret ----------------------------------------------------
mod._traffic['reported_at'] -= mod.TRAFFIC_REPORT_INTERVAL + 1
mod._traffic_tick(time.monotonic())
with open(mod.LOG_PATH, encoding='utf-8') as f:
    journal = f.read()
report('resume dans le journal toutes les {:.0f} s'.format(mod.TRAFFIC_REPORT_INTERVAL),
       'trafic :' in journal and 'MSG_OBJECTS_VIEW_UPDATE' in journal)
before = list(mod._traffic['total'])
run('off')
omega.send(0x1234, 4, b'apres')
report('mp.traffic off : plus rien compte, resultat garde',
       mod._traffic['total'] == before and 'arrete' in run())
report('commande inconnue refusee', 'Usage' in run('tout'))
run('on')
report('relancer remet les compteurs a zero', mod._traffic['total'] == [0, 0])
run('off')

shutil.rmtree(TMP, ignore_errors=True)
if not LOG_EXISTED and os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)
print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
