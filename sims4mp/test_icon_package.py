# Sims 4 Multiplayer - test hors jeu du fichier sims4mp_icons.package (0.16.0).
# Compatible Python 3.7. A lancer avec :  py -3.7 test_icon_package.py

import struct
import sys
import zlib

import icon_package as ip

results = []


def report(step, ok, detail=''):
    results.append(bool(ok))
    print('[{}] {}{}'.format('OK' if ok else 'ECHEC', step, ' - ' + detail if detail else ''))


def png_chunks(png):
    chunks, pos = [], 8
    while pos < len(png):
        length = struct.unpack_from('>I', png, pos)[0]
        kind = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + length]
        crc = struct.unpack_from('>I', png, pos + 8 + length)[0]
        chunks.append((kind, data, crc == zlib.crc32(kind + data) & 0xFFFFFFFF))
        pos += 12 + length
    return chunks


# --- 1. Identifiant ---------------------------------------------------------------------
report('FNV-1a 64 : valeur de reference (chaine vide)', ip.fnv1a64('') == 0xCBF29CE484222325)
report('identifiant de l\'icone : fixe, bit haut force (contenu personnalise)',
       ip.ICON_INSTANCE == ip.fnv1a64('sims4mp:icon:menu') | (1 << 63) and ip.ICON_INSTANCE >> 63 == 1,
       '{:016X}'.format(ip.ICON_INSTANCE))

# --- 2. Dessin ----------------------------------------------------------------------------
rgba = ip.draw_logo(32, 2)


def pixel(x, y, size=32):
    return tuple(rgba[(y * size + x) * 4:(y * size + x) * 4 + 4])


report('dessin : 32 x 32 x 4 octets', len(rgba) == 32 * 32 * 4)
report('coins transparents, centre du rond opaque',
       pixel(0, 0)[3] == 0 and pixel(31, 31)[3] == 0 and pixel(16, 6)[3] == 255)
report('anneau blanc en haut, joueurs jaune et vert d\'eau',
       pixel(16, 1)[:3] == (255, 255, 255) and pixel(11, 12)[:3] == ip.YELLOW
       and pixel(20, 12)[:3] == ip.MINT)

# --- 3. PNG -------------------------------------------------------------------------------
png = ip.encode_png(rgba, 32, 32)
chunks = png_chunks(png)
ihdr = struct.unpack('>IIBBBBB', chunks[0][1])
raw = zlib.decompress(chunks[1][1])
rows_ok = all(raw[y * 129] == 0 and raw[y * 129 + 1:(y + 1) * 129] == rgba[y * 128:(y + 1) * 128]
              for y in range(32))
report('PNG : signature, IHDR RGBA 8 bits, IDAT, IEND, CRC justes',
       png[:8] == b'\x89PNG\r\n\x1a\n' and [c[0] for c in chunks] == [b'IHDR', b'IDAT', b'IEND']
       and ihdr == (32, 32, 8, 6, 0, 0, 0) and all(c[2] for c in chunks))
report('PNG : les pixels relus sont ceux du dessin', rows_ok)

# --- 4. .package --------------------------------------------------------------------------
package = ip.icon_package()
resources = ip.read_package(package)
report('.package : en-tete DBPF 2.1, une ressource, index en fin de fichier',
       package[:4] == b'DBPF' and struct.unpack_from('<III', package, 4) == (2, 1, 0)
       and struct.unpack_from('<I', package, 36)[0] == 1
       and struct.unpack_from('<I', package, 64)[0] + struct.unpack_from('<I', package, 44)[0] == len(package))
report('.package : ressource DDS (0x00B2D882), groupe 0, identifiant de l\'icone',
       len(resources) == 1 and resources[0][:3] == (ip.DDS_TYPE, 0, ip.ICON_INSTANCE)
       and resources[0][3] == ip.encode_dds())

# --- 5. DDS (meme en-tete que les DDS 32 bits qui s'affichent dans la roue) ---------------
dds = resources[0][3]
size, flags, height, width, pitch, _, mips = struct.unpack_from('<IIIIIII', dds, 4)
pf = struct.unpack_from('<IIIIIIII', dds, 76)
caps = struct.unpack_from('<I', dds, 108)[0]
report('DDS : en-tete 128 octets, 128 x 128, pitch 512, 8 niveaux',
       dds[:4] == b'DDS ' and size == 124 and flags == 0x0002100F and (width, height) == (128, 128)
       and pitch == 512 and mips == 8 and caps == 0x00401008)
report('DDS : pixels 32 bits A8R8G8B8 (masques standards, sans FourCC)',
       pf == (32, 0x41, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000))
report('DDS : taille = en-tete + tous les niveaux (128 a 1)',
       len(dds) == 128 + sum(s * s * 4 for s in ip.mip_sizes(128)) and ip.mip_sizes(128)[-1] == 1)
logo = ip.draw_logo(128)
first = dds[128:128 + 128 * 128 * 4]
pos = (50 * 128 + 46) * 4                                          # tete du joueur de gauche (jaune)
report('DDS : octets dans l\'ordre B, G, R, A',
       first[pos:pos + 4] == bytes((logo[pos + 2], logo[pos + 1], logo[pos], logo[pos + 3]))
       and first[pos + 2] == ip.YELLOW[0])
two = ip.read_package(ip.build_package([(1, 2, 3, b'abc'), (4, 5, (7 << 32) | 9, b'')]))
report('.package : plusieurs ressources, identifiant 64 bits decoupe haut/bas',
       two == [(1, 2, 3, b'abc'), (4, 5, (7 << 32) | 9, b'')])
report('le mod et le .package utilisent le meme identifiant',
       'MENU_ICON_INSTANCE = 0x{:016X}'.format(ip.ICON_INSTANCE)
       in open('sims4mp_hello.py', encoding='utf-8').read())

print()
print('{} / {} etapes OK'.format(sum(results), len(results)))
sys.exit(0 if all(results) else 1)
