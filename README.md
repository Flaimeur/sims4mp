# Sims4MP

Mod multijoueur expérimental pour Les Sims 4, avec son lanceur Windows.
Projet de fan, non affilié à Electronic Arts.

## Contenu

- `sims4mp/` : le mod (Python 3.7, la version embarquée par le jeu).
  - `sims4mp_hello.py` : commandes en jeu (`mp.hello`, `mp.host`, `mp.join`, `mp.state`...).
  - `protocol.py`, `transport.py` : protocole JSON et transport TCP non bloquant.
  - `build.py` : compile le mod en `build/sims4mp_hello.ts4script`.
- `launcher/` : le lanceur Windows (Python 3.12, tkinter, bibliothèque standard uniquement).
  - `sims4mp_launcher_gui.py` : installation du mod, mise à jour depuis les Releases GitHub
    (vérification de la taille et du SHA-256), réglage Héberger / Rejoindre, lancement du jeu.
  - `sims4mp_launcher.py` : ancien lanceur en console.

## Construire

```
py -3.7 sims4mp/build.py
py -3.12 -m PyInstaller --onefile --noconsole --noconfirm --name Sims4MP_Launcher_GUI --icon launcher/sims4mp.ico launcher/sims4mp_launcher_gui.py
```

## Tests

```
py -3.12 -m unittest launcher/test_sims4mp_launcher_gui.py launcher/test_sims4mp_update.py launcher/test_sims4mp_options.py launcher/test_sims4mp_launch.py
py -3.7 sims4mp/test_transport.py
```

## Releases

Chaque Release contient seulement `sims4mp_hello.ts4script` et `sims4mp_manifest.json`
(version, fichier, url, sha256, taille, statut). Les versions en statut `test` sont
publiées en pré-version : dans le lanceur, choisir « Tag précis » dans Options et cocher
« Installer une version de test ».

## Mentions

Aucune image d'Electronic Arts n'est fournie dans ce dépôt. Sans le fichier local
`launcher/sims4mp_assets.py` (non publié), le lanceur affiche un losange qu'il dessine lui-même.
Les Sims est une marque d'Electronic Arts. Guide d'utilisation : [launcher/README.md](launcher/README.md).
