# Lanceur Sims4MP : guide d'utilisation

Sims4MP est un projet de fan, non affilié à Electronic Arts. Il est expérimental :
gardez une copie de vos sauvegardes avant de jouer.

## 1. Installation

1. Créez un dossier à vous, par exemple `Documents\Sims4MP` ou sur le Bureau.
   Évitez `C:\Program Files` : le lanceur doit pouvoir écrire à côté de lui
   (journal `launcher.log`, dossier `sims4mp_backups`, options).
2. Copiez-y `Sims4MP_Launcher_GUI.exe` **et** `sims4mp_hello.ts4script`, dans le même dossier.
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

- Page **Mod** → **Installer le mod** : copie `sims4mp_hello.ts4script` dans Mods.
  Le jeu doit être fermé. L'ancien mod est d'abord rangé dans `sims4mp_backups`.
- **Mettre à jour depuis GitHub** : renseignez d'abord le dépôt dans **Options**.
  Le fichier téléchargé est vérifié (taille et SHA-256) avant d'être copié. Une version
  de test demande de cocher « Installer une version de test » ; une version plus ancienne
  demande de cocher « Autoriser le retour à une version plus ancienne ».

## 4. Héberger ou rejoindre

Les deux joueurs doivent avoir la même version du mod.

**Celui qui héberge**
1. Page **Connexion** → **Héberger**, port (7777 par défaut) → **Enregistrer le réglage**.
2. **Copier l'IP principale** et envoyez-la à l'autre joueur.
3. En jeu, ouvrez la console (Ctrl + Maj + C) et tapez `mp.host` (ou `mp.host 7777`).

**Celui qui rejoint**
1. Page **Connexion** → **Rejoindre**, IP de l'hôte et même port → **Enregistrer le réglage**.
2. En jeu, console : `mp.join 192.168.1.20` (l'IP reçue), ou `mp.join 192.168.1.20 7777`.

Autres commandes : `mp.status` (état de la connexion), `mp.ping`, `mp.state`, `mp.disconnect`.

Le mod ne lit pas encore le réglage enregistré : les commandes ci-dessus restent nécessaires.
Le réglage sert déjà au **Diagnostic**.

## 5. Pare-feu

Au premier `mp.host`, Windows peut demander d'autoriser Les Sims 4 sur le réseau.
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

## Fichiers créés par le lanceur

À côté de l'exe : `launcher.log`, `sims4mp_backups\`, `sims4mp_launcher_config.json` (dépôt GitHub).
Dans `Documents\Electronic Arts\` : `sims4mp_settings.json` (rôle, IP, port).
Le lanceur ne lit ni ne modifie vos sauvegardes de partie.
