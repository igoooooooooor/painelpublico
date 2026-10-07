#!/usr/bin/env bash
# Prepara um servidor Ubuntu/Debian novo para o Painel Público. Rode uma vez, como root:
#   ssh root@SERVIDOR 'bash -s' < deploy/setup-server.sh
set -euo pipefail

apt-get update -y
apt-get install -y python3 rsync sqlite3 curl ufw
id painel >/dev/null 2>&1 || useradd --system --home /opt/painel --shell /usr/sbin/nologin painel
install -d -o painel -g painel /opt/painel /opt/painel/app /opt/painel/data

# cloudflared (repositório oficial da Cloudflare)
if ! command -v cloudflared >/dev/null; then
  install -d -m 0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -y && apt-get install -y cloudflared
fi

# Firewall: só SSH. O site não abre porta; o túnel sai do servidor para a Cloudflare.
ufw allow OpenSSH
ufw --force enable
echo "Pronto. Próximo passo no seu computador: make deploy-db SERVER=root@ESTE_SERVIDOR e make deploy SERVER=root@ESTE_SERVIDOR"
