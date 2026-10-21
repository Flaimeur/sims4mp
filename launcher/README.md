# Lanceur Sims4MP : guide d'utilisation

Sims4MP est un projet de fan, non affilié à Electronic Arts. Il est expérimental :
gardez une copie de vos sauvegardes avant de jouer.

## 1. Installation

1. Créez un dossier à vous, par exemple `Documents\Sims4MP` ou sur le Bureau.
   Évitez `C:\Program Files` : le lanceur doit pouvoir écrire à côté de lui
   (journal `launcher.log`, dossier `sims4mp_backups`, options).
2. Copiez-y `Sims4MP_Launcher_GUI.exe`. Le mod n'est pas fourni à côté : le lanceur
   le télécharge depuis GitHub (voir 3).
3. Lancez Les Sims 4 au moins une fois avant, pour que le dossier
   `Documents\Electronic Arts\Les Sims 4\Mods` existe. Dans les options du jeu,
   activez le contenu personnalisé et les mods de script.

## 2. Premier lancement et SmartScreen

L'exe n'est pas signé. Windows peut afficher « Windows a protégé votre ordinateur » :
cliquez sur **Informations complémentaires**, puis **Exécuter quand même**.
Un antivirus peut aussi le signaler : c'est fréquent pour les exe créés avec PyInstaller.
En cas de doute, reconstruisez-le vous-même depuis les sources (voir le README du dépôt).

En bas à droite, le lanceur indique où il a trouvé le jeu : **Jeu : Steam**, **Jeu : EA app**
ou **Jeu : introuvable** (le bouton « Lancer Les Sims 4 » est alors désactivé).

## 3. Installer ou mettre à jour le mod

1. Page **Options** : **Dépôt** `compte/dépôt` (par exemple `Flaimeur/sims4mp`).
   **Dernière stable** pour une version publiée normalement ; **Tag précis** (par exemple
   `v0.4.0`) pour une pré-version de test. **Enregistrer**, puis **Tester le manifeste**.
2. Page **Mod** → **Installer / mettre à jour depuis GitHub**. Le jeu doit être fermé.
   Le fichier téléchargé est vérifié (taille et SHA-256) avant d'être copié dans Mods ;
   l'ancien mod est d'abord rangé dans `sims4mp_backups`.
3. Une version de test demande de cocher « Installer une version de test » ; une version
   plus ancienne demande « Autoriser le retour à une version plus ancienne ».

« Aucune version stable publiée » : le dépôt n'a que des pré-versions, choisissez **Tag précis**.

## 4. Partie à deux (page Connexion)

Les deux joueurs ferment le jeu, ont la même version du mod, sont sur le même réseau local
et ont le même **Port du jeu** (Options → Réseau, 7777 par défaut ; la room utilise le port + 1).
Le réglage (rôle, IP, port) est enregistré automatiquement quand on crée ou rejoint une room.

**Hôte** : **Héberger** → choisissez la **Partie à partager** → **Créer la room**.
La liste propose d'abord vos parties sauvegardées à la main ; la sauvegarde automatique
(`Slot_ffffffff`) est en dernier et affiche un avertissement si vous la choisissez.
Le code de la room s'affiche en grand, avec l'IP et le port : **Copier l'invitation** et envoyez-la
à l'invité. Quand il clique sur Rejoindre, une ligne « pseudo · IP demande à rejoindre » apparaît
sous **Joueurs** : **Accepter** ou **Refuser**. Sans votre accord, l'invité ne peut lire ni le nom de
la partie, ni le foyer, ni le fichier ; un refus vaut jusqu'à la fermeture de la room.
Chaque invité accepté reçoit la partie **une seule fois** ; quand chacun l'a reçue et vérifiée, le
**partage se ferme** (la copie est supprimée) mais la room reste ouverte pour les joueurs et
« Lancer pour tous ». **Fermer la room** (ou quitter le lanceur) arrête tout.

**Invité** : **Rejoindre** → **Pseudo**, **IP de l'hôte** et **Code de room**. Le premier clic
envoie une demande : « en attente de l'accord de l'hôte », puis l'action continue toute seule
une fois acceptée.
- **Vérifier sans copier** : affiche la partie, le foyer et ce qui serait fait, sans rien écrire.
- **Rejoindre la room** : après confirmation, la partie est téléchargée et vérifiée (taille, SHA-256),
  toutes vos sauvegardes sont copiées dans `sims4mp_backups\saves_AAAAMMJJ_HHMMSS\`, puis la partie
  est installée dans un slot réservé Sims4MP (`Slot_534d5000.save`). Vos autres parties ne sont pas modifiées.

Ensuite, lancez le jeu et chargez cette partie. Les actions en jeu ne sont pas encore synchronisées :
les deux parties évoluent séparément après le chargement. Sécurité : seulement des adresses de réseau
privé avec le bon code ; la room se verrouille après 5 codes faux. Le transfert n'est pas chiffré.

**Joueurs et lancement à deux.** Une fois la room trouvée, le lanceur de l'invité se signale à
l'hôte toutes les 2 s : l'hôte voit « pseudo · IP · état » (connecté, partie reçue, jeu lancé,
lancement refusé). Un invité silencieux depuis 10 s disparaît de la liste ; **Quitter la room**
arrête la présence. **Lancer pour tous** (hôte) lance le jeu de l'hôte et prévient les invités :
le lanceur d'un invité lance alors **son propre** jeu, seulement si la case
**Laisser l'hôte lancer mon jeu** est cochée (décochée par défaut), si la partie de l'hôte a été
reçue pendant cette session et si son jeu n'est pas déjà ouvert. L'hôte n'envoie ni commande ni
chemin, seulement un signal. Chacun choisit ensuite la partie dans le menu du jeu.

**En jeu** (console Ctrl + Maj + C) : l'hôte tape `mp.host` (ou `mp.host 7777`), l'invité
`mp.join 192.168.1.20` (l'IP de l'hôte). Le mod ne lit pas encore le réglage : ces commandes
restent nécessaires. Autres commandes : `mp.status`, `mp.ping`, `mp.state`, `mp.disconnect`.

## 5. Pare-feu

Au premier `mp.host`, Windows peut demander d'autoriser Les Sims 4 sur le réseau ; à la
première room, il le demande pour le lanceur.
Cochez **Réseaux privés** uniquement, pas « Réseaux publics ». Votre connexion
domestique doit être en profil « Privé » (Paramètres → Réseau et Internet → Propriétés).
Le lanceur ne modifie jamais le pare-feu.

Jouer par Internet (hors réseau local) demande d'ouvrir un port sur la box : ce n'est
pas géré par le lanceur et expose votre PC. Préférez un réseau local ou un VPN de jeu.

## 6. Lancer le jeu

Bouton vert **Lancer Les Sims 4** : passe par Steam, ou ouvre le jeu détecté pour l'app EA.
Refusé si le jeu tourne déjà.

## 7. Diagnostic

Page **Options** → **Diagnostic**. Rien n'est modifié. Il affiche dans le journal :
le mod et sa version, si le jeu est ouvert, le réglage enregistré, vos IP locales,
l'état du pare-feu, et :
- en mode Héberger : si le port est libre ou déjà pris par une autre application ;
- en mode Rejoindre : un essai de connexion de 3 s vers l'hôte (« Joignable », ou
  « le port ne répond pas » : vérifiez que l'hôte a lancé `mp.host` et que son pare-feu
  autorise le réseau privé).

**Ouvrir le journal** affiche `launcher.log`, utile pour signaler un problème.

## 8. Restaurer l'ancien mod

Page **Mod** → **Restaurer l'ancien mod** : choisissez une sauvegarde (date, version),
confirmez. Le jeu doit être fermé. Le mod en place est lui-même sauvegardé avant d'être remplacé.

## 9. Sur Mac

Le mod est le même fichier sur Mac et sur PC. Le lanceur fonctionne aussi sur macOS, mais
il n'y a pas d'exe : on le lance avec Python.

1. Installez **Python 3** depuis python.org (rubrique macOS). Le `python3` fourni par Apple
   a une bibliothèque de fenêtres (Tk) trop ancienne.
2. Téléchargez le dépôt (bouton **Code → Download ZIP** sur GitHub) et décompressez-le,
   par exemple dans `Documents/Sims4MP`.
3. Double-cliquez sur `launcher/Sims4MP_Mac.command`. La première fois, macOS peut refuser
   (« développeur non identifié ») : clic droit → **Ouvrir** → **Ouvrir**. Si le fichier ne
   s'ouvre pas, dans Terminal : `chmod +x launcher/Sims4MP_Mac.command`, ou lancez
   directement `python3 launcher/sims4mp_launcher_gui.py`.

Le jeu est détecté dans la bibliothèque Steam (`~/Library/Application Support/Steam`) puis dans
`/Applications` ou `~/Applications` (app EA : `The Sims 4.app`, `The Sims™ 4.app`, aussi dans un
sous-dossier). Le téléchargement du mod utilise les certificats de macOS si Python n'a pas les
siens (sinon : lancez une fois « Install Certificates.command » du dossier Python 3 dans Applications). Les dossiers sont ceux du jeu sur Mac :
`~/Documents/Electronic Arts/Les Sims 4/Mods` et `saves`. Le journal, `sims4mp_backups/` et
les options sont écrits dans le dossier `launcher` à côté du script.

Pare-feu : si le pare-feu de macOS est activé, il demande d'autoriser **Python** (pour la room)
et **The Sims 4** (pour `mp.host`) à recevoir des connexions : cliquez sur **Autoriser**.
Le diagnostic affiche « Pare-feu, macOS : activé / désactivé ». En jeu, la console s'ouvre
avec Cmd + Maj + C.

## Fichiers créés par le lanceur

À côté de l'exe (ou du script) : `launcher.log`, `sims4mp_backups\`, `sims4mp_launcher_config.json` (dépôt GitHub).
Dans `Documents\Electronic Arts\` : `sims4mp_settings.json` (rôle, IP, port).
Le lanceur ne lit ni ne modifie vos sauvegardes de partie.
