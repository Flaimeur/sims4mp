# Sims 4 Multiplayer - protocole des messages.
# Compatible Python 3.7. Aucune dependance au jeu (pas d'import sims4).
#
# Un message est un dictionnaire JSON :
#   {"type": "PING", "v": 1, "data": {...}}
# encode en UTF-8. Le prefixe de longueur est ajoute par transport.py.
# Securite : JSON uniquement, jamais de pickle ni d'eval.

import json

PROTOCOL_VERSION = 1

HELLO = 'HELLO'
WELCOME = 'WELCOME'
REJECT = 'REJECT'
PING = 'PING'
PONG = 'PONG'
EVENT = 'EVENT'
BYE = 'BYE'

MESSAGE_TYPES = frozenset([HELLO, WELCOME, REJECT, PING, PONG, EVENT, BYE])

# Taille maximale d'un message (contenu JSON, hors prefixe).
MAX_MESSAGE_SIZE = 1024 * 1024


class ProtocolError(Exception):
    pass


# ---------------------------------------------------------------------------
# Encodage / decodage
# ---------------------------------------------------------------------------

def make_message(msg_type, data=None):
    if msg_type not in MESSAGE_TYPES:
        raise ProtocolError('type de message inconnu : {!r}'.format(msg_type))
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ProtocolError('data doit etre un dictionnaire')
    return {'type': msg_type, 'v': PROTOCOL_VERSION, 'data': data}


def encode_message(message):
    """dict -> bytes (JSON UTF-8)."""
    validate_message(message)
    try:
        text = json.dumps(message, ensure_ascii=False, separators=(',', ':'))
    except (TypeError, ValueError) as e:
        raise ProtocolError('message non serialisable : {}'.format(e))
    payload = text.encode('utf-8')
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ProtocolError('message trop gros : {} octets'.format(len(payload)))
    return payload


def decode_message(payload):
    """bytes (JSON UTF-8) -> dict valide. Leve ProtocolError sinon."""
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ProtocolError('message trop gros : {} octets'.format(len(payload)))
    try:
        text = payload.decode('utf-8')
        message = json.loads(text)
    except (UnicodeDecodeError, ValueError) as e:
        raise ProtocolError('JSON invalide : {}'.format(e))
    validate_message(message)
    return message


def validate_message(message):
    if not isinstance(message, dict):
        raise ProtocolError('le message doit etre un objet JSON')
    msg_type = message.get('type')
    if msg_type not in MESSAGE_TYPES:
        raise ProtocolError('type de message inconnu : {!r}'.format(msg_type))
    version = message.get('v')
    if not isinstance(version, int) or isinstance(version, bool):
        raise ProtocolError('version absente ou invalide')
    if not isinstance(message.get('data'), dict):
        raise ProtocolError('champ data absent ou invalide')


# ---------------------------------------------------------------------------
# Constructeurs de messages
# ---------------------------------------------------------------------------

def hello(mod_version, game_version='', household=''):
    return make_message(HELLO, {
        'protocol': PROTOCOL_VERSION,
        'mod_version': mod_version,
        'game_version': game_version,
        'household': household,
    })


def welcome(info=''):
    return make_message(WELCOME, {'info': info})


def reject(reason):
    return make_message(REJECT, {'reason': reason})


def ping(seq, sent_at):
    return make_message(PING, {'seq': seq, 'sent_at': sent_at})


def pong(seq, sent_at, host_info=None):
    data = {'seq': seq, 'sent_at': sent_at}
    if host_info is not None:
        data['host_info'] = host_info
    return make_message(PONG, data)


def event(name, payload=None):
    return make_message(EVENT, {'name': name, 'payload': payload if payload is not None else {}})


def bye(reason=''):
    return make_message(BYE, {'reason': reason})
