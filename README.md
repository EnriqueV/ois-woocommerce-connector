# OIS WooCommerce Connector Web

Conector web para sincronizar datos desde OIS Mobile Inventory hacia WooCommerce.

La version web permite:

- Probar conexion con OIS.
- Crear categorias de producto en WooCommerce desde `ResultItemGroups`.
- Sincronizar productos desde `ResultItems`, creando nuevos y actualizando existentes solo cuando cambian.
- Asociar productos a categorias usando `cItemGroupId`.
- Agregar el tag `sincronizado by ois connector` a los productos creados.
- Guardar programacion de ejecucion.

## Requisitos

- Un servidor web con PHP y cURL habilitado.
- Acceso de escritura en la carpeta `web/` para que pueda guardar `config.json` y logs.
- WooCommerce con REST API activa.
- Consumer Key y Consumer Secret de WooCommerce con permisos de lectura/escritura.
- Token/API Key de OIS.
- DigitalOcean Spaces con credenciales de escritura si el hosting no puede subir imagenes a WordPress.

> Importante: no abras `web/index.html` como `file://` para operar el conector. Debe abrirse desde una URL `http://` o `https://` donde PHP pueda ejecutar `api.php`.

## Instalacion

1. Sube la carpeta `web/` al hosting o servidor donde correra el conector.
2. Asegurate de que estos archivos queden accesibles:
   - `index.html`
   - `api.php`
   - `sync_lib.php`
   - `cron_sync.php`
   - `config.json`
3. Abre en el navegador la URL donde quedo instalado, por ejemplo:

```text
https://tudominio.com/connector/index.html
```

## Configuracion

Entra a la seccion **Settings**. La pantalla esta bloqueada para evitar cambios accidentales.

Clave de acceso:

```text
Ois2026#
```

Completa los campos:

- **OIS Products URL:** endpoint de items de OIS, por ejemplo `https://www.oisimobile.com/OISWC/Inventory.svc/item`.
- **Image URL:** endpoint de imagenes de OIS.
- **DigitalOcean Spaces Endpoint:** endpoint publico del Space, por ejemplo `https://instancias.nyc3.digitaloceanspaces.com`.
- **DigitalOcean Spaces Access Key:** access key de DigitalOcean Spaces.
- **DigitalOcean Spaces Secret Key:** secret key de DigitalOcean Spaces.
- **DigitalOcean Spaces Directory:** carpeta del Space donde se guardaran las imagenes, por ejemplo `file_img`.
- **Local Images Directory:** ruta local donde se guardaran imagenes si aplica.
- **Public Images Base URL:** URL publica desde donde WordPress/WooCommerce podra leer imagenes.
- **Token / API Key:** token de OIS.
- **WordPress URL:** URL base del sitio WooCommerce.
- **WordPress Username:** usuario WordPress, si se usa para subir media.
- **WordPress Application Password:** application password, si se usa para subir media.
- **WordPress Client Key:** Consumer Key de WooCommerce.
- **WordPress Client Secret:** Consumer Secret de WooCommerce.

Luego presiona **Guardar configuracion**.

## Uso Recomendado

1. En **Settings**, guarda la configuracion.
2. En **Sincronizacion**, presiona **Probar conexion**.
3. Presiona **Crear categorias**.
   - Borra las categorias existentes de WooCommerce.
   - Lee `ResultItemGroups` desde OIS.
   - Crea categorias usando la propiedad `name`.
4. Presiona **Sincronizar cambios**.
   - Lee productos desde `ResultItems`.
   - Asocia cada producto a su categoria usando `cItemGroupId`.
   - Agrega el tag `sincronizado by ois connector`.
   - Descarga las imagenes desde OIS, las sube a DigitalOcean Spaces y envia a WooCommerce la URL publica.
   - Busca productos existentes por SKU/UPC.
   - Crea productos nuevos y actualiza productos existentes solo si detecta cambios en datos, stock, categoria, tag o imagenes.

## Programacion

La seccion **Programming** guarda dias y hora de ejecucion.

La hora se interpreta como:

```text
Hora de Utah
```

Para ejecutar desde cron puedes llamar:

```text
https://tudominio.com/connector/cron_sync.php
```

Tambien puedes pasar el modo:

```text
https://tudominio.com/connector/cron_sync.php?mode=new
```

## Logs

La actividad se muestra en pantalla en el panel **Registro de actividad**.

Ademas, el conector escribe logs diarios en:

```text
web/logs/
```

## Notas

- El flujo de categorias debe ejecutarse antes de sincronizar productos si quieres que los productos queden categorizados correctamente.
- Las categorias se relacionan por `cItemGroupId` de OIS y por el nombre creado en WooCommerce.
- El tag de sincronizacion se crea una vez si no existe y luego se reutiliza.
- La sincronizacion usa el SKU/UPC como identificador. Los productos sin SKU se omiten para evitar duplicados.
- Cada producto sincronizado guarda un hash interno `_ois_connector_hash`; esto permite saltar productos existentes sin cambios en corridas posteriores.
- Si DigitalOcean Spaces esta configurado, las imagenes se guardan ahi y WooCommerce recibe `images[].src`; si no esta configurado, el conector conserva el fallback anterior hacia WordPress Media Library.
- El modo `all` aparece en configuracion interna, pero la interfaz web actual ejecuta sincronizacion de productos nuevos.
- No compartas `config.json` si contiene tokens, Consumer Secret o claves privadas.
