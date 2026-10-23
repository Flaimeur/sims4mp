# Sims 4 Multiplayer - icone de la roue : logo A « deux joueurs » dessine ici en pixels
# (formes simples, aucun element d'EA), encode en PNG, range dans un fichier .package.
# Compatible Python 3.7. Utilise par build.py ; ne tourne pas dans le jeu.
#
# Le jeu (bytecode verifie, lecture seule) :
#   - Interaction.get_pie_menu_icon_info appelle cls.pie_menu_icon(resolver), qui renvoie un
#     distributor.shared_messages.IconInfoData(icon_resource=cle) ;
#   - sims4.resources.CompoundTypes.IMAGE = [Types.PNG] : les icones sont des ressources PNG
#     (Types.PNG = 0x2F7D0004) ;
#   - sims4.resources.get_resource_key(instance, Types.PNG) -> Key(type, instance), groupe 0.
# 0.16.1 : une ressource PNG est bien trouvee par la simulation mais l'affichage montre le
# lama (image illisible). Les icones qui s'affichent dans la roue (autres mods) sont des DDS
# (Types.DDS = 0x00B2D882) : l'icone est donc un DDS 32 bits non compresse (A8R8G8B8) avec
# mipmaps, le format le plus simple accepte par l'affichage.

import struct
import zlib

PNG_TYPE = 0x2F7D0004
DDS_TYPE = 0x00B2D882
# Identifiant fixe de l'icone : FNV-1a 64 bits de 'sims4mp:icon:menu', bit haut force
# (convention des contenus personnalises). Le mod utilise la meme valeur (MENU_ICON_INSTANCE).
ICON_NAME = 'sims4mp:icon:menu'
ICON_SIZE = 128
SUPERSAMPLE = 4


def fnv1a64(text):
    value = 0xCBF29CE484222325
    for byte in text.lower().encode('utf-8'):
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return value


ICON_INSTANCE = fnv1a64(ICON_NAME) | 0x8000000000000000


# -- dessin (repere 128 x 128 du fichier design/sims4mp_logo_propositions.svg, logo A) --

def _hex(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


BLUE_LIGHT, BLUE_DARK = _hex('#2d6cdf'), _hex('#1b3f8f')
WHITE, YELLOW, MINT = (255, 255, 255), _hex('#ffd166'), _hex('#7ee0c3')


def _inside_circle(x, y, cx, cy, r):
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _inside_shoulders(x, y, cx, cy):
    # Demi-ellipse haute (rayons 24 x 22) posee sur y = cy, comme le chemin SVG « a24 22 ».
    return y <= cy and ((x - cx) / 24.0) ** 2 + ((y - cy) / 22.0) ** 2 <= 1.0


def _sample(x, y):
    """Couleur (r, g, b, a) du logo au point (x, y) du repere 128, ou None (transparent)."""
    if not _inside_circle(x, y, 64, 64, 63):
        return None
    if not _inside_circle(x, y, 64, 64, 57):
        return WHITE + (255,)                                  # anneau blanc
    color = None
    if _inside_circle(x, y, 46, 50, 13) or _inside_shoulders(x, y, 46, 92):
        color = YELLOW                                         # joueur de gauche
    if _inside_circle(x, y, 82, 50, 13) or _inside_shoulders(x, y, 82, 92):
        color = MINT                                           # joueur de droite, devant
    if color is None:
        t = max(0.0, min(1.0, (x + y - 8) / 240.0))            # degrade en diagonale
        color = tuple(int(round(a + (b - a) * t)) for a, b in zip(BLUE_LIGHT, BLUE_DARK))
    return color + (255,)


def draw_logo(size=ICON_SIZE, supersample=SUPERSAMPLE):
    """Pixels RGBA (bytes, size * size * 4), bords lisses par sur-echantillonnage."""
    scale = 128.0 / size
    step = 1.0 / supersample
    count = supersample * supersample
    pixels = bytearray()
    for py in range(size):
        for px in range(size):
            r = g = b = a = 0
            for sy in range(supersample):
                for sx in range(supersample):
                    color = _sample((px + (sx + 0.5) * step) * scale, (py + (sy + 0.5) * step) * scale)
                    if color is not None:
                        r += color[0] * color[3]
                        g += color[1] * color[3]
                        b += color[2] * color[3]
                        a += color[3]
            if a:
                pixels += bytes((r // a, g // a, b // a, a // count))
            else:
                pixels += b'\x00\x00\x00\x00'
    return bytes(pixels)


# -- PNG (RGBA 8 bits, sans entrelacement) --

def _chunk(kind, data):
    return (struct.pack('>I', len(data)) + kind + data
            + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF))


def encode_png(rgba, width, height):
    rows = b''.join(b'\x00' + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return (b'\x89PNG\r\n\x1a\n'
            + _chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + _chunk(b'IDAT', zlib.compress(rows, 9))
            + _chunk(b'IEND', b''))


# -- DDS (32 bits non compresse, octets B, G, R, A ; mipmaps jusqu'a 1 x 1) --

DDS_HEADER_FLAGS = 0x0002100F    # CAPS | HEIGHT | WIDTH | PITCH | PIXELFORMAT | MIPMAPCOUNT
DDS_PIXEL_FLAGS = 0x00000041     # RGB | ALPHAPIXELS
DDS_CAPS = 0x00401008            # COMPLEX | TEXTURE | MIPMAP


def mip_sizes(size):
    sizes = [size]
    while sizes[-1] > 1:
        sizes.append(sizes[-1] // 2)
    return sizes


def encode_dds(size=ICON_SIZE):
    """DDS carre size x size (puissance de 2), chaque niveau redessine a sa taille."""
    levels = mip_sizes(size)
    header = struct.pack('<4sIIIIIII44x', b'DDS ', 124, DDS_HEADER_FLAGS, size, size, size * 4, 0,
                         len(levels))
    header += struct.pack('<IIIIIIII', 32, DDS_PIXEL_FLAGS, 0, 32,
                          0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    header += struct.pack('<IIIII', DDS_CAPS, 0, 0, 0, 0)
    body = bytearray()
    for level in levels:
        rgba = draw_logo(level, SUPERSAMPLE if level >= 8 else 8)
        for i in range(0, len(rgba), 4):
            body += bytes((rgba[i + 2], rgba[i + 1], rgba[i], rgba[i + 3]))
    return header + bytes(body)


# -- .package (DBPF 2.1, ressources non compressees) --

HEADER_SIZE = 96
INDEX_ENTRY = struct.Struct('<IIIIIIIHH')       # type, groupe, inst. haut, inst. bas, position,
                                                # taille (bit 31), taille en memoire, compression, 1


def build_package(resources):
    """resources : liste de (type, groupe, instance, donnees). Renvoie les octets du .package."""
    body = bytearray()
    index = bytearray(struct.pack('<I', 0))     # drapeaux d'index : chaque entree est complete
    for res_type, group, instance, data in resources:
        offset = HEADER_SIZE + len(body)
        index += INDEX_ENTRY.pack(res_type, group, instance >> 32, instance & 0xFFFFFFFF,
                                  offset, len(data) | 0x80000000, len(data), 0x0000, 1)
        body += data
    index_position = HEADER_SIZE + len(body)
    header = bytearray(HEADER_SIZE)
    header[0:4] = b'DBPF'
    struct.pack_into('<II', header, 4, 2, 1)                       # version 2.1
    struct.pack_into('<I', header, 36, len(resources))             # nombre d'entrees
    struct.pack_into('<I', header, 44, len(index))                 # taille de l'index
    struct.pack_into('<I', header, 60, 3)                          # version mineure de l'index
    struct.pack_into('<I', header, 64, index_position)             # position de l'index
    return bytes(header) + bytes(body) + bytes(index)


def read_package(data):
    """Relit un .package ecrit par build_package : liste de (type, groupe, instance, donnees)."""
    if data[0:4] != b'DBPF' or struct.unpack_from('<II', data, 4) != (2, 1):
        raise ValueError('pas un DBPF 2.1')
    count = struct.unpack_from('<I', data, 36)[0]
    position = struct.unpack_from('<I', data, 64)[0]
    if struct.unpack_from('<I', data, position)[0] != 0:
        raise ValueError('drapeaux d\'index non geres')
    resources = []
    for n in range(count):
        (res_type, group, high, low, offset, size, memsize,
         compression, _) = INDEX_ENTRY.unpack_from(data, position + 4 + n * INDEX_ENTRY.size)
        size &= 0x7FFFFFFF
        if compression != 0 or size != memsize:
            raise ValueError('ressource compressee non geree')
        resources.append((res_type, group, (high << 32) | low, bytes(data[offset:offset + size])))
    return resources


def icon_png():
    return encode_png(draw_logo(), ICON_SIZE, ICON_SIZE)


def icon_package():
    return build_package([(DDS_TYPE, 0, ICON_INSTANCE, encode_dds())])
