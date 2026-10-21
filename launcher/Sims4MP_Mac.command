#!/bin/bash
# Lanceur Sims4MP sur Mac : double-cliquer sur ce fichier (dossier launcher du depot).
# Il faut Python 3 de python.org (le python3 d'Apple a un Tk trop ancien).
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 introuvable : installez Python 3 depuis https://www.python.org/downloads/macos/"
    read -r -p "Entree pour fermer..." _
    exit 1
fi
python3 sims4mp_launcher_gui.py
status=$?
if [ "$status" -ne 0 ]; then
    read -r -p "Le lanceur s'est arrete (code $status). Entree pour fermer..." _
fi
exit "$status"
