# Sims 4 Multiplayer - test du transport hors du jeu.
# Compatible Python 3.7. A lancer avec :  py -3.7 test_transport.py
#
# Host et client tournent dans le meme processus sur 127.0.0.1, sans thread :
# la boucle appelle alternativement server.poll() et client.poll(), comme le
# fera la pompe du jeu.

import socket
import sys
import time

import protocol
import transport

MOD_VERSION = '0.1.0'
TIMEOUT = 3.0

results = []


def report(step, ok, detail=''):
    results.append(ok)
    line = '[{}] {}'.format('OK' if ok else 'ECHEC', step)
    if detail:
        line += ' - ' + detail
    print(line)


def find_free_port(exclude=()):
    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        finally:
            s.close()
        if port not in exclude:
            return port


def pump(endpoints, inboxes, until, timeout=TIMEOUT):
    """Fait tourner les poll() jusqu'a until() vrai ou timeout. inboxes : listes d'evenements."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for endpoint, inbox in zip(endpoints, inboxes):
            inbox.extend(endpoint.poll())
        if until():
            return True
        time.sleep(0.005)
    return False


def take(inbox, kind, msg_type=None):
    """Retire et renvoie le premier evenement correspondant, ou None."""
    for i, (ev_kind, value) in enumerate(inbox):
        if ev_kind != kind:
            continue
        if msg_type is not None and value.get('type') != msg_type:
            continue
        del inbox[i]
        return value
    return None


def has(inbox, kind, msg_type=None):
    for ev_kind, value in inbox:
        if ev_kind == kind and (msg_type is None or value.get('type') == msg_type):
            return True
    return False


# ---------------------------------------------------------------------------

def test_protocol():
    msg = protocol.ping(1, 12.5)
    decoded = protocol.decode_message(protocol.encode_message(msg))
    report('protocole : encodage/decodage JSON', decoded == msg)

    msg = protocol.event('test', {'texte': 'Été à Willow Creek'})
    decoded = protocol.decode_message(protocol.encode_message(msg))
    report('protocole : accents UTF-8', decoded == msg)

    refused = 0
    for bad in (b'pas du json', b'[1,2]', b'{"type":"INCONNU","v":1,"data":{}}',
                b'{"type":"PING","v":1}', b'\xff\xfe'):
        try:
            protocol.decode_message(bad)
        except protocol.ProtocolError:
            refused += 1
    report('protocole : messages invalides refuses', refused == 5, '{}/5'.format(refused))


def test_framing():
    a = protocol.encode_message(protocol.ping(1, 0.0))
    b = protocol.encode_message(protocol.pong(1, 0.0))
    stream = transport.frame(a) + transport.frame(b)

    decoder = transport.FrameDecoder()
    report('decoupage : deux trames dans un seul paquet', decoder.feed(stream) == [a, b])

    decoder = transport.FrameDecoder()
    out = []
    for i in range(len(stream)):
        out.extend(decoder.feed(stream[i:i + 1]))
    report('decoupage : flux recu octet par octet', out == [a, b])

    decoder = transport.FrameDecoder(max_size=10)
    try:
        decoder.feed(transport.frame(b'x' * 11))
        report('decoupage : trame trop grosse refusee', False)
    except protocol.ProtocolError:
        report('decoupage : trame trop grosse refusee', True)


def test_network():
    host_port = find_free_port()
    client_port = find_free_port(exclude=(host_port,))

    server = transport.Server('127.0.0.1', host_port)
    try:
        server.start()
        report('host : ecoute', True, '127.0.0.1:{}'.format(server.port))
    except OSError as e:
        report('host : ecoute', False, repr(e))
        return

    client = transport.Client('127.0.0.1', host_port, local_port=client_port)
    s_inbox, c_inbox = [], []
    endpoints = [server, client]
    inboxes = [s_inbox, c_inbox]

    try:
        # --- Connexion -----------------------------------------------------
        try:
            client.connect()
        except OSError as e:
            report('client : connexion', False, repr(e))
            return
        ok = pump(endpoints, inboxes, lambda: has(s_inbox, 'connected') and has(c_inbox, 'connected'))
        take(s_inbox, 'connected')
        take(c_inbox, 'connected')
        report('connexion host <-> client', ok,
               'port host {} / port client {}'.format(host_port, client.local_port))
        report('ports differents', client.local_port == client_port and client_port != host_port)
        if not ok:
            return

        # --- HELLO / WELCOME -----------------------------------------------
        client.send(protocol.hello(MOD_VERSION, household='Test'))
        ok = pump(endpoints, inboxes, lambda: has(s_inbox, 'message', protocol.HELLO))
        hello = take(s_inbox, 'message', protocol.HELLO)
        report('host recoit HELLO', ok and hello is not None)
        if hello is None:
            return

        if hello['data'].get('protocol') == protocol.PROTOCOL_VERSION:
            server.send(protocol.welcome('bienvenue'))
        else:
            server.send(protocol.reject('version incompatible'))
        ok = pump(endpoints, inboxes, lambda: has(c_inbox, 'message', protocol.WELCOME)
                  or has(c_inbox, 'message', protocol.REJECT))
        welcome = take(c_inbox, 'message', protocol.WELCOME)
        report('client recoit WELCOME', ok and welcome is not None)
        if welcome is None:
            return

        # --- PING / PONG ---------------------------------------------------
        sent_at = time.monotonic()
        client.send(protocol.ping(1, sent_at))
        ok = pump(endpoints, inboxes, lambda: has(s_inbox, 'message', protocol.PING))
        ping = take(s_inbox, 'message', protocol.PING)
        report('host recoit PING', ok and ping is not None)
        if ping is None:
            return

        server.send(protocol.pong(ping['data']['seq'], ping['data']['sent_at']))
        ok = pump(endpoints, inboxes, lambda: has(c_inbox, 'message', protocol.PONG))
        pong = take(c_inbox, 'message', protocol.PONG)
        good = ok and pong is not None and pong['data'].get('seq') == 1
        latency = (time.monotonic() - sent_at) * 1000.0
        report('client recoit PONG', good, 'aller-retour {:.1f} ms'.format(latency))

        # --- Un seul client ------------------------------------------------
        intruder = transport.Client('127.0.0.1', host_port)
        i_inbox = []
        try:
            intruder.connect()
            ok = pump(endpoints + [intruder], inboxes + [i_inbox],
                      lambda: has(i_inbox, 'disconnected'))
            rejected = take(i_inbox, 'message', protocol.REJECT) is not None
            report('second client refuse', ok,
                   'REJECT recu' if rejected else 'fermeture sans REJECT')
        except OSError as e:
            report('second client refuse', False, repr(e))
        finally:
            intruder.close()
        report('premier client toujours connecte', server.is_connected and client.is_connected)

        # --- BYE -----------------------------------------------------------
        client.send(protocol.bye('fin du test'))
        ok = pump(endpoints, inboxes, lambda: has(s_inbox, 'message', protocol.BYE))
        report('host recoit BYE', ok)
        client.close()
        ok = pump(endpoints, inboxes, lambda: has(s_inbox, 'disconnected'))
        report('host detecte la deconnexion', ok and not server.is_connected)
    finally:
        client.close()
        server.close()


def main():
    print('Python {}'.format(sys.version.split()[0]))
    if sys.version_info[:2] != (3, 7):
        print('ATTENTION : ce test doit etre lance avec Python 3.7 (version du jeu).')
    print()
    test_protocol()
    test_framing()
    test_network()
    print()
    passed = sum(1 for ok in results if ok)
    print('{} / {} etapes OK'.format(passed, len(results)))
    return 0 if results and all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
