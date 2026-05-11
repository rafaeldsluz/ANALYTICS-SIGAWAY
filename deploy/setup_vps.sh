#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Setup VPS Ubuntu 22.04 — Sigaway Agent Web Platform
# Uso: bash setup_vps.sh
# ──────────────────────────────────────────────────────────────────────────────
set -e

echo "==> Atualizando sistema..."
sudo apt update && sudo apt upgrade -y

echo "==> Instalando dependências..."
sudo apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git

echo "==> Criando diretório da aplicação..."
sudo mkdir -p /opt/sigaway
sudo chown $USER:$USER /opt/sigaway

echo "==> Copiando arquivos do projeto..."
# Execute este script de dentro do diretório do projeto
cp -r . /opt/sigaway/

echo "==> Criando ambiente virtual Python..."
python3 -m venv /opt/sigaway/venv
source /opt/sigaway/venv/bin/activate

echo "==> Instalando dependências Python..."
pip install --upgrade pip
pip install -r /opt/sigaway/requirements.txt
pip install gunicorn

echo "==> Criando diretório de logs..."
sudo mkdir -p /var/log/sigaway
sudo chown $USER:$USER /var/log/sigaway

echo "==> Configurando serviço systemd..."
sudo cp /opt/sigaway/deploy/sigaway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sigaway
sudo systemctl start sigaway

echo "==> Configurando nginx..."
sudo cp /opt/sigaway/deploy/nginx.conf /etc/nginx/sites-available/sigaway
sudo ln -sf /etc/nginx/sites-available/sigaway /etc/nginx/sites-enabled/sigaway
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

echo ""
echo "✓ Deploy concluído!"
echo ""
echo "Próximos passos:"
echo "  1. Edite /etc/nginx/sites-available/sigaway e troque SEU_DOMINIO_OU_IP"
echo "  2. Para SSL gratuito: sudo certbot --nginx -d seudominio.com"
echo "  3. Edite /opt/sigaway/.env com suas credenciais"
echo "  4. sudo systemctl restart sigaway"
echo ""
echo "  Acesse: http://SEU_IP"
