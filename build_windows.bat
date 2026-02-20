@echo off
REM ================================================================
REM  build_windows.bat  —  Genera WooCommerceConnector.exe
REM  Ejecutar desde Windows con Python instalado
REM ================================================================

echo.
echo  WooCommerce Connector — Build para Windows
echo  ============================================
echo.

REM 1. Instalar dependencias
echo [1/3] Instalando dependencias...
pip install -r requirements.txt
pip install pyinstaller
if %errorlevel% neq 0 (
    echo ERROR: fallo pip install
    pause
    exit /b 1
)

REM 2. Limpiar builds anteriores
echo.
echo [2/3] Limpiando build anterior...
if exist dist\WooCommerceConnector rmdir /s /q dist\WooCommerceConnector
if exist build\WooCommerceConnector rmdir /s /q build\WooCommerceConnector

REM 3. Empaquetar
echo.
echo [3/3] Empaquetando con PyInstaller...
pyinstaller woocommerce_connector.spec --noconfirm

if %errorlevel% neq 0 (
    echo.
    echo ERROR: PyInstaller fallo. Revisa los mensajes arriba.
    pause
    exit /b 1
)

echo.
echo  ============================================
echo  Build completado exitosamente!
echo  Ejecutable en: dist\WooCommerceConnector\WooCommerceConnector.exe
echo  ============================================
echo.
pause
