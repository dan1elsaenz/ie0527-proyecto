#!/usr/bin/env bash
# Uso:  sudo ./install.sh [tx|rx]
set -euo pipefail

ROLE="${1:-rx}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Instalando dependencias del sistema"
apt-get update
apt-get install -y python3-pip python3-numpy libportaudio2 python3-lgpio \
                   cmake build-essential python3-dev

echo "==> Instalando dependencias de Python"
pip3 install --break-system-packages --root-user-action=ignore \
     -r "${SRC_DIR}/requirements.txt"

case "${ROLE}" in
  tx) UNIT="audio-tx.service" ;;
  rx) UNIT="audio-rx.service" ;;
  *) echo "Rol inválido: ${ROLE} (usar tx o rx)"; exit 1 ;;
esac

if ! id -u "${ROLE}" >/dev/null 2>&1; then
  echo "Advertencia: no existe el usuario '${ROLE}'."
fi

echo "==> Instalando servicio systemd: ${UNIT}"
install -m 644 "${SRC_DIR}/setup/${UNIT}" "/etc/systemd/system/${UNIT}"
systemctl daemon-reload
systemctl enable "${UNIT}"