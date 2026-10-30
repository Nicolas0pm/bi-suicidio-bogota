#!/usr/bin/env bash
# Genera el .exe de Windows desde Linux usando Wine (sin tocar ~/.wine).
# Uso:  bash escritorio/construir_con_wine.sh
# Resultado: escritorio/dist/BI_Suicidio/  (BI_Suicidio.exe + config.json + LEEME.txt) listo para la USB.
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
export WINEPREFIX="$HOME/.cache/bi-suicidio-wine"
export WINEDEBUG=-all
export WINEDLLOVERRIDES="mscoree,mshtml="
VERSION=3.12.10
INSTALADOR="$WINEPREFIX/python-$VERSION-amd64.exe"
PY='C:\Python312\python.exe'

command -v wine >/dev/null || { echo "Falta Wine: sudo pacman -S wine"; exit 1; }

if [ ! -f "$WINEPREFIX/drive_c/Python312/python.exe" ]; then
  echo "==> Preparando Wine en $WINEPREFIX"
  mkdir -p "$WINEPREFIX"
  wineboot -i >/dev/null 2>&1 || true
  echo "==> Descargando Python $VERSION para Windows (python.org)"
  curl -fSL -o "$INSTALADOR" "https://www.python.org/ftp/python/$VERSION/python-$VERSION-amd64.exe"
  echo "==> Instalando Python en Wine (tarda 1-2 minutos)"
  wine "$INSTALADOR" /quiet InstallAllUsers=0 'TargetDir=C:\Python312' PrependPath=0 \
       Include_test=0 Include_doc=0 Include_launcher=0 Include_tcltk=1
fi

echo "==> Instalando dependencias de la app"
wine "$PY" -m pip install --disable-pip-version-check -q -r "$(winepath -w "$AQUI/requirements.txt")"

echo "==> Empaquetando con PyInstaller"
cd "$AQUI"
rm -rf build dist BI_Suicidio.spec
wine "$PY" -m PyInstaller --noconfirm --onefile --windowed --name BI_Suicidio \
     --distpath 'dist\BI_Suicidio' app.py
cp config.json LEEME.txt dist/BI_Suicidio/

echo
echo "Listo: $AQUI/dist/BI_Suicidio/"
ls -la "$AQUI/dist/BI_Suicidio/"
echo "Copie esa carpeta a la memoria USB."
