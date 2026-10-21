# Comparaison des mods de l'hote et de l'invite (lecture seule, rien n'est copie).
#
# Python 3.12, bibliotheque standard uniquement.
# - scan_mods : inventaire d'un dossier Mods (.package et .ts4script, hors mod
#   Sims4MP), avec SHA-256 en option et cache a cote du lanceur.
# - validate_mods_list : controle la liste recue de l'hote (donnee non fiable).
# - compare_mods : manquants, differents, en plus ; correspondance par nom de
#   fichier quel que soit le sous-dossier, departage par taille (et SHA-256).
# - write_report : rapport texte a cote du lanceur (jamais dans Mods).

import datetime
import json
import os
import re
from pathlib import Path, PurePosixPath

import sims4mp_launcher_gui as core

MODS_PROTOCOL = 1
MOD_EXTENSIONS = ('.package', '.ts4script')
EXCLUDED_NAMES = {core.MOD_FILE.lower()}          # version deja comparee par la room
MAX_ENTRIES = 20000
MAX_LIST_SIZE = 5 * 1024 * 1024                   # reponse /mods
MAX_NAME = 255
MAX_PATH = 1024
MAX_FILE_SIZE = 64 * 1024 ** 3
CACHE_NAME = 'sims4mp_mods_cache.json'
LIST_KEYS = {'protocole', 'avec_sha', 'mods'}
ENTRY_KEYS = {'nom', 'chemin', 'taille', 'sha256'}


class ModsError(core.LauncherError):
    """Erreur de comparaison des mods : message affiche tel quel."""


def _is_mod(name):
    lower = name.lower()
    return lower.endswith(MOD_EXTENSIONS) and lower not in EXCLUDED_NAMES


def _read_cache(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    clean = {}
    for key, value in data.items():
        if (isinstance(key, str) and isinstance(value, dict) and isinstance(value.get('taille'), int)
                and isinstance(value.get('mtime_ns'), int) and isinstance(value.get('sha256'), str)
                and re.fullmatch(r'[0-9a-f]{64}', value['sha256'])):
            clean[key] = value
    return clean


def scan_mods(mods_dir, with_sha=False, cache_path=None):
    """Inventaire en lecture seule : [{'nom', 'chemin', 'taille', 'sha256'}], trie par chemin."""
    mods_dir = Path(mods_dir)
    entries = []
    for root, dirs, files in os.walk(mods_dir, followlinks=False):
        dirs.sort()
        for name in sorted(files):
            if not _is_mod(name):
                continue
            path = Path(root) / name
            if path.is_symlink() or not path.is_file():
                continue
            if len(entries) >= MAX_ENTRIES:
                raise ModsError('Trop de mods : plus de {} fichiers.'.format(MAX_ENTRIES))
            entries.append({'nom': name, 'chemin': path.relative_to(mods_dir).as_posix(),
                            'taille': path.stat().st_size, 'sha256': None})
    entries.sort(key=lambda e: e['chemin'])        # os.walk donne un dossier avant ses sous-dossiers
    if with_sha:
        cache = _read_cache(cache_path) if cache_path else {}
        fresh = {}
        for entry in entries:
            path = mods_dir / entry['chemin']
            stat = path.stat()
            key = str(path)
            hit = cache.get(key)
            if hit and hit['taille'] == stat.st_size and hit['mtime_ns'] == stat.st_mtime_ns:
                entry['sha256'] = hit['sha256']
            else:
                entry['sha256'] = core.sha256_of(path)
            fresh[key] = {'taille': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'sha256': entry['sha256']}
        if cache_path:
            try:
                core._write_json_atomic(Path(cache_path), fresh)
            except OSError:
                pass                                   # le cache est un confort, pas une obligation
    return entries


def mods_list(mods_dir, with_sha=False, cache_path=None):
    """Liste servie par la room sur /mods."""
    return {'protocole': MODS_PROTOCOL, 'avec_sha': bool(with_sha),
            'mods': scan_mods(mods_dir, with_sha, cache_path)}


def validate_mods_list(data):
    """Controle la liste recue de l'hote ; refuse tout ce qui sort du format attendu."""
    if not isinstance(data, dict) or set(data) != LIST_KEYS:
        raise ModsError('Liste de mods de l\'hôte invalide (champs inattendus).')
    if data['protocole'] != MODS_PROTOCOL or not isinstance(data['avec_sha'], bool):
        raise ModsError('Liste de mods de l\'hôte incompatible.')
    mods = data['mods']
    if not isinstance(mods, list) or len(mods) > MAX_ENTRIES:
        raise ModsError('Liste de mods de l\'hôte invalide ou trop longue.')
    clean = []
    for entry in mods:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise ModsError('Entrée de mod invalide dans la liste de l\'hôte.')
        name, rel, size, sha = entry['nom'], entry['chemin'], entry['taille'], entry['sha256']
        if (not isinstance(name, str) or not 0 < len(name) <= MAX_NAME or '/' in name or '\\' in name
                or name in ('.', '..') or not _is_mod(name)):
            raise ModsError('Nom de mod refusé : {!r}'.format(str(name)[:80]))
        parts = PurePosixPath(rel).parts if isinstance(rel, str) else ()
        if (not isinstance(rel, str) or len(rel) > MAX_PATH or '\\' in rel or rel.startswith('/')
                or ':' in rel or '..' in parts or not parts or parts[-1] != name):
            raise ModsError('Chemin de mod refusé : {!r}'.format(str(rel)[:80]))
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_FILE_SIZE:
            raise ModsError('Taille de mod refusée : {!r}'.format(size))
        if sha is not None and (not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha)):
            raise ModsError('Empreinte de mod refusée.')
        if data['avec_sha'] and sha is None:
            raise ModsError('Empreinte manquante alors que l\'hôte annonce une comparaison exacte.')
        clean.append({'nom': name, 'chemin': rel, 'taille': size, 'sha256': sha})
    return {'protocole': MODS_PROTOCOL, 'avec_sha': data['avec_sha'], 'mods': clean}


def _same(a, b, use_sha):
    return a['taille'] == b['taille'] and (not use_sha or a['sha256'] == b['sha256'])


def compare_mods(host, guest, use_sha=False):
    """{'manquants', 'differents', 'en_plus', 'identiques'} ; correspondance par nom de
    fichier (sans tenir compte de la casse ni du sous-dossier)."""
    use_sha = use_sha and all(e['sha256'] for e in host + guest)
    by_name = {}
    for entry in guest:
        by_name.setdefault(entry['nom'].casefold(), []).append(entry)
    host_names = {e['nom'].casefold() for e in host}
    missing, different, same = [], [], 0
    used = set()
    for entry in host:
        candidates = by_name.get(entry['nom'].casefold(), [])
        if not candidates:
            missing.append(entry)
            continue
        match = next((g for g in candidates if id(g) not in used and _same(entry, g, use_sha)), None)
        if match is not None:
            used.add(id(match))
            same += 1
        else:
            different.append((entry, candidates))
    extra = [g for g in guest if g['nom'].casefold() not in host_names]
    return {'manquants': missing, 'differents': different, 'en_plus': extra,
            'identiques': same, 'exacte': use_sha}


def _mo(size):
    return '{:.1f} Mo'.format(size / 1e6)


def summary_text(result):
    return 'Mods : {} manquant(s), {} différent(s), {} en plus'.format(
        len(result['manquants']), len(result['differents']), len(result['en_plus']))


def report_lines(result, host_label):
    """Rapport lisible (journal et fichier texte)."""
    lines = ['Comparaison des mods avec l\'hôte {} ({})'.format(
        host_label, 'exacte, SHA-256' if result['exacte'] else 'nom et taille'),
        '{} identique(s).'.format(result['identiques'])]
    missing = result['manquants']
    lines.append('Manquants chez vous : {} ({})'.format(len(missing), _mo(sum(e['taille'] for e in missing))))
    lines += ['  - {} ({}, {})'.format(e['nom'], e['chemin'], _mo(e['taille'])) for e in missing]
    lines.append('Différents : {}'.format(len(result['differents'])))
    for entry, yours in result['differents']:
        lines.append('  - {} : hôte {} ; vous {}'.format(
            entry['nom'], _mo(entry['taille']), ', '.join(_mo(g['taille']) for g in yours)))
    lines.append('En plus chez vous : {}'.format(len(result['en_plus'])))
    lines += ['  - {} ({})'.format(e['nom'], e['chemin']) for e in result['en_plus']]
    lines.append(summary_text(result) + '. Rien n\'a été copié ni modifié.')
    return lines


def write_report(folder, lines):
    """Ecrit le rapport a cote du lanceur ; renvoie son chemin."""
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    path = Path(folder) / 'sims4mp_mods_{}.txt'.format(stamp)
    n = 2
    while path.exists():
        path = Path(folder) / 'sims4mp_mods_{}_{}.txt'.format(stamp, n)
        n += 1
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
    return path
