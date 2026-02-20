#!/bin/bash
# ================================================================
#  build_mac.sh  —  Genera WooCommerceConnector.app (macOS)
#  También sirve para probar el empaquetado antes de ir a Windows
# ================================================================

set -e

echo ""
echo " WooCommerce Connector — Build para macOS"
echo " ==========================================="
echo ""

# 1. Instalar dependencias
echo "[1/3] Instalando dependencias..."
pip3 install -r requirements.txt --break-system-packages 2>/dev/null || pip3 install -r requirements.txt
pip3 install pyinstaller --break-system-packages 2>/dev/null || pip3 install pyinstaller

# 2. Limpiar builds anteriores
echo ""
echo "[2/3] Limpiando build anterior..."
rm -rf dist/WooCommerceConnector build/WooCommerceConnector

# 3. Empaquetar
echo ""
echo "[3/3] Empaquetando con PyInstaller..."
pyinstaller woocommerce_connector.spec --noconfirm

echo ""
echo " ==========================================="
echo " Build completado!"
echo " App en: dist/WooCommerceConnector/WooCommerceConnector"
echo " ==========================================="
echo ""
echo " Para probar:"
echo "   ./dist/WooCommerceConnector/WooCommerceConnector"
echo ""
