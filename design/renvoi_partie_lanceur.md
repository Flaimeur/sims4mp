# Renvoi de la partie de l'hôte en cours de partie : ce qu'il faut côté lanceur

Partie mod faite dans le mod 0.21.8 (branche `worktree-simulation-unique`). Le mod ne transporte pas la
sauvegarde : il demande au lanceur de refaire, en cours de partie, ce que la room fait déjà au départ
(copie de la sauvegarde de l'hôte, installation dans le slot réservé de l'invité).

## Fichiers échangés

Les deux fichiers sont dans le même dossier que `sims4mp_settings.json`
(`Documents\Electronic Arts\`). Le mod les écrit en entier dans `<nom>.tmp` puis les renomme
(`os.replace`) : le lanceur ne lit jamais un fichier à moitié écrit, mais doit ignorer un JSON invalide
et réessayer au passage suivant.

### `sims4mp_resync.json` — écrit par le mod de l'hôte, lu par le lanceur de l'hôte

```json
{"version": 1, "id": "18f3a2b4c5d", "slot": "Slot_0000000a.save", "demande": "2026-10-25T21:14:03"}
```

- `id` : texte alphanumérique (40 caractères au plus), nouveau à chaque demande.
- `slot` : fichier de la partie en cours chez l'hôte (`Slot_XXXXXXXX.save`, même forme que
  `SAVE_NAME_RE`), dans son dossier `saves`.
- Le mod vient de lancer l'enregistrement (commande du jeu `persistence.save_game`), qui se termine
  **après** l'écriture de ce fichier : le lanceur doit attendre que le fichier du slot soit stable
  (taille et date inchangées pendant ~3 s, et date postérieure à la demande) avant de le copier.

### `sims4mp_resync_done.json` — écrit par le lanceur de l'invité, lu par le mod de l'invité

```json
{"version": 1, "id": "18f3a2b4c5d", "etat": "installee", "detail": ""}
```

- `id` : celui de la demande de l'hôte.
- `etat` : `installee` (partie copiée dans `Slot_534d5000.save`) ou `erreur` (`detail` : texte court
  affiché au joueur, 64 caractères au plus).
- Écrit en entier puis renommé, comme ci-dessus.

## Ce que doit faire le lanceur de l'hôte

1. Pendant qu'une room est ouverte, surveiller `sims4mp_resync.json` (par exemple toutes les 2 s) ; une
   demande dont l'`id` n'a pas déjà été traitée la déclenche.
2. Vérifier `slot` comme une sauvegarde choisie au départ (nom `SAVE_NAME_RE`, fichier dans le dossier
   `saves`, taille ≤ `MAX_SAVE_SIZE`), attendre qu'il soit stable, puis refaire la copie figée de la room
   (`RoomServer` : nouveau `snapshot`, nouvelle taille, nouveau SHA-256, nouveau nom de partie) sans fermer
   la room ni changer le code.
3. Exposer la nouvelle version dans `/info`, par exemple deux nouvelles clés `revision` (entier qui
   augmente à chaque copie) et `resync_id` (l'`id` de la demande). Attention : `INFO_KEYS` est vérifié
   à l'égalité côté invité, il faut donc les accepter dans les deux sens et monter `ROOM_PROTOCOL`
   (ou les rendre facultatives pour qu'un ancien lanceur ne casse pas).
4. Garder la règle « un envoi par invité accepté » par révision : l'accord déjà donné à un invité vaut
   pour les révisions suivantes de la même room.

## Ce que doit faire le lanceur de l'invité

1. Pendant qu'il est dans la room (il se signale déjà toutes les 2 s), relire `/info` ; si `revision`
   augmente, télécharger `/save` et l'installer exactement comme au départ (`apply_join` : taille,
   SHA-256, copie de secours des sauvegardes, remplacement atomique de `Slot_534d5000.save`).
   Le jeu tourne pendant ce temps : ne toucher qu'au fichier du slot réservé (le jeu ne le relit qu'au
   chargement) et à ses versions `.verN`.
2. Écrire `sims4mp_resync_done.json` avec `resync_id` comme `id` et `etat` `installee`, ou `erreur` avec
   un `detail` court (place disque, SHA-256 différent, room fermée…).
3. Afficher dans le journal du lanceur ce qui a été fait.

## Ce que fait déjà le mod

- Hôte : bouton « Renvoyer ma partie à l'invité (lanceur) » dans « Sims4MP… → Partie à deux » ; il
  enregistre la partie, écrit la demande et prévient l'invité (« gardez le lanceur ouvert »).
- Invité : attend la demande annoncée, lit `sims4mp_resync_done.json` toutes les 2 s ; partie installée :
  notification « retournez au menu principal et chargez la partie Sims4MP », et l'hôte est prévenu.
  Erreur : alerte avec le `detail` du lanceur.
- Rien n'est automatique côté jeu : c'est le joueur invité qui recharge la partie.
