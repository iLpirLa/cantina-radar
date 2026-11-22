#!/bin/bash
# Cantina Radar - avvio su Mac (doppio clic, oppure: bash avvia-mac.command)
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 non trovato: installalo da https://www.python.org/downloads/ e riapri questo file."
  read -r -p "Premi Invio per chiudere"; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Prima installazione, attendi qualche minuto..."
  python3 -m venv .venv || exit 1
fi
source .venv/bin/activate
python -m pip install -q --disable-pip-version-check -r requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Si apre il file .env: inserisci token del bot e chat id, salva e chiudi."
  open -e .env
  read -r -p "Premi Invio quando hai salvato il file .env "
fi
# caffeinate impedisce al Mac di andare in stop mentre l'app è aperta
caffeinate -i python -m cwmon start --lan
