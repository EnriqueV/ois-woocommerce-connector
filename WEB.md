# Conector Shopify web

Desde la carpeta del repositorio:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
python web_app.py
```

Abre http://127.0.0.1:8080 en el navegador. El servidor se ejecuta en este equipo.

En Configuración de conexión puedes guardar las credenciales en .env. También se
leen las variables del entorno, que tienen prioridad, y la configuración de OIS
guardada por la aplicación de escritorio. Los campos protegidos vacíos conservan
su valor. La URL de OIS puede incluir ?key= o usar el token por separado.

Previsualizar cambios consulta OIS y Shopify y muestra productos, grupos,
precios, existencias y errores. Aplicar cambios utiliza esa vista previa y
solicita confirmación. Cada vista previa sirve para una aplicación y vence a los
30 minutos. Si el producto cambió en Shopify, genera otra vista previa.
Puedes recargar la página para consultar una operación que sigue ejecutándose.

Los productos nuevos tienen Unidad y Caja y se publican en Online Store. El
stock de OIS se asigna a Caja en Shop location. Unidad empieza con stock cero.
Los productos anteriores de una sola variante mantienen la estructura que
soporta el motor actual.

Permisos de Shopify: write_products, write_inventory, read_locations,
read_publications y write_publications. Aprueba cambios de permisos en la tienda.

Esta versión está preparada para uso local con un único proceso. Las operaciones
y vistas previas viven en memoria. Para instalarla en un servidor compartido hace
falta configurar acceso autenticado, HTTPS y almacenamiento de trabajos.

## Login

El único usuario se configura con ADMIN_USERNAME y ADMIN_PASSWORD en .env o en
las variables del hosting. SESSION_SECRET firma las sesiones y debe ser estable.
Las sesiones duran 8 horas. El login admite hasta 5 intentos por minuto.
Para usar otro dominio fuera de Render, agrégalo a ALLOWED_HOSTS (separado por comas).

## Render gratuito

Conecta esta rama con Render mediante New > Blueprint y el archivo render.yaml.
Completa ADMIN_PASSWORD, las credenciales Shopify y la URL/token de OIS cuando
Render solicite las variables. El usuario configurado es AdminOis.
Si OIS_PRODUCTS_URL incluye ?key=, OIS_API_TOKEN puede quedar vacío.

Para crear el servicio manualmente:
- Build: pip install -r requirements-web.txt
- Start: gunicorn --workers 1 --threads 4 --bind 0.0.0.0:$PORT 'web_app:create_app()'
- Health check: /health
- Plan: Free
- Agrega SESSION_SECRET con un valor aleatorio largo y las variables de .env.example.

Guarda la configuración permanente en Environment de Render. Los cambios al
archivo .env hechos desde la interfaz se pierden al reiniciarse el servicio
gratuito. Las variables del servicio tienen prioridad.
Render puede suspender el servicio por inactividad. Al despertar, genera una
vista previa nueva. Si se interrumpe una sincronización, consulta otra vista previa
para verificar lo aplicado antes de continuar.
