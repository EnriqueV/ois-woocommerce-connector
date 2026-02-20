# Manual de Usuario — WooCommerce Connector

**Versión:** 1.0
**Sistema operativo:** Windows 10 / 11

---

## Tabla de Contenidos

1. [Requisitos del sistema](#1-requisitos-del-sistema)
2. [Instalación en Windows](#2-instalación-en-windows)
3. [Primera ejecución y configuración](#3-primera-ejecución-y-configuración)
4. [Paso 1 — Settings (Configuración)](#4-paso-1--settings-configuración)
5. [Paso 2 — Programming (Programación)](#5-paso-2--programming-programación)
6. [Paso 3 — Sincronizar](#6-paso-3--sincronizar)
7. [Dónde se guardan los datos](#7-dónde-se-guardan-los-datos)
8. [Solución de problemas](#8-solución-de-problemas)

---

## 1. Requisitos del sistema

| Requisito | Detalle |
|-----------|---------|
| Sistema operativo | Windows 10 (64-bit) o Windows 11 |
| RAM | Mínimo 4 GB |
| Espacio en disco | ~150 MB para la carpeta de la aplicación |
| Conexión a internet | Requerida para sincronizar productos |
| Python | **No necesario** — la app ya incluye todo lo necesario |

---

## 2. Instalación en Windows

La aplicación se distribuye como una carpeta comprimida `.zip`. No requiere instalador.

### Pasos

1. **Descargar** el archivo `WooCommerceConnector-Windows.zip` desde el enlace que le fue compartido
   *(o desde la sección **Actions → Artifacts** del repositorio GitHub)*.

2. **Extraer** el archivo `.zip`:
   - Clic derecho sobre el archivo → **"Extraer todo..."**
   - Elija una ubicación, por ejemplo: `C:\WooCommerceConnector\`
   - Haga clic en **"Extraer"**

3. Dentro de la carpeta extraída encontrará:

   ```
   WooCommerceConnector\
   ├── WooCommerceConnector.exe   ← ejecutable principal
   ├── _internal\                 ← librerías internas (no mover ni borrar)
   └── data.json                  ← se crea automáticamente al guardar datos
   ```

4. **Ejecutar** la aplicación haciendo doble clic en `WooCommerceConnector.exe`.

> ⚠️ **Importante:** No mueva el archivo `.exe` fuera de su carpeta. La aplicación necesita todos los archivos de la carpeta `_internal\` para funcionar correctamente.

> ⚠️ **Windows SmartScreen:** La primera vez que ejecute la aplicación, Windows puede mostrar una advertencia de seguridad. Haga clic en **"Más información"** y luego en **"Ejecutar de todas formas"** para continuar.

---

## 3. Primera ejecución y configuración

Al abrir la aplicación verá una ventana con un **stepper de 3 pasos** en la parte superior:

```
[1] Settings  ──────  [2] Programming  ──────  [3] Sincronizar
```

**Se recomienda seguir el orden: Settings → Programming → Sincronizar.**

Use los botones **"Anterior"** y **"Siguiente"** en la parte inferior para navegar entre pasos.

---

## 4. Paso 1 — Settings (Configuración)

Este paso es donde se ingresan las credenciales y URLs de conexión.

### Campos disponibles

| Campo | Descripción |
|-------|-------------|
| **WordPress URL** | URL de su sitio WordPress/WooCommerce, sin `www` |
| **WordPress Client Key** | Consumer Key de la API REST de WooCommerce |
| **WordPress Client Secret** | Consumer Secret de la API REST de WooCommerce *(oculto con asteriscos)* |
| **OIS Products URL** | URL del endpoint de inventario OIS |
| **OIS App URL** | URL base de la aplicación OIS |
| **Token / API Key** | Token de autenticación para la API de OIS *(oculto con asteriscos)* |

### Cómo obtener las credenciales de WooCommerce

1. Inicie sesión en el panel de administración de WordPress (`/wp-admin`)
2. Vaya a **WooCommerce → Ajustes → Avanzado → API REST**
3. Haga clic en **"Añadir clave"**
4. Complete el formulario:
   - **Descripción:** WooCommerce Connector
   - **Usuario:** su usuario administrador
   - **Permisos:** Lectura/Escritura
5. Haga clic en **"Generar clave API"**
6. Copie la **Consumer Key** y el **Consumer Secret** en los campos correspondientes

### Guardar la configuración

Haga clic en el botón **"Guardar Settings"** al final del formulario.
Aparecerá un mensaje de confirmación cuando los datos se hayan guardado correctamente.

> 💡 La configuración se guarda automáticamente en el archivo `data.json` dentro de la carpeta de la aplicación.

---

## 5. Paso 2 — Programming (Programación)

Este paso permite configurar los días y la hora en que se ejecutará la sincronización automática.

> **Nota:** En la versión actual, esta configuración guarda las preferencias para referencia futura. La sincronización automática programada se ejecutará según lo configurado aquí.

### Campos disponibles

- **Días de la semana:** Seleccione uno o más días marcando las casillas correspondientes:
  - Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo

- **Hora de ejecución:** Ingrese la hora en formato 24 horas (`HH:MM`), por ejemplo: `08:00` o `14:30`

### Guardar la programación

Haga clic en el botón **"Save Programming"** para guardar los días y hora seleccionados.

---

## 6. Paso 3 — Sincronizar

Este paso permite ejecutar la sincronización de productos desde OIS hacia WooCommerce.

### Opciones de sincronización

Seleccione el tipo de sincronización antes de ejecutar:

| Opción | Descripción |
|--------|-------------|
| **Sincronizar y borrar todo** | Elimina todos los productos existentes en WooCommerce y los reemplaza con los productos de OIS |
| **Sincronizar solo productos nuevos** | Agrega únicamente los productos que no existen aún en WooCommerce |

### Ejecutar la sincronización

1. Seleccione la opción deseada
2. Haga clic en el botón **"Sincronizar"**
3. Observe el panel de logs en la parte inferior de la pantalla

### Panel de Logs

El panel de logs muestra en tiempo real el progreso de la sincronización:

| Color | Tipo de mensaje |
|-------|-----------------|
| 🔵 Azul | Información general (INFO) |
| 🟡 Amarillo | Advertencias (WARNING) |
| 🔴 Rojo | Errores (ERROR) |
| ⚪ Gris | Detalles técnicos (DEBUG) |

**Ejemplo de una sincronización exitosa:**

```
10:23:01  INFO      Iniciando sincronización…
10:23:01  INFO      Leyendo configuración desde base de datos…
10:23:02  INFO      Consultando OIS API…
10:23:03  INFO      OIS devolvió 553 productos
10:23:03  INFO      Enviando lote de 5 productos a WooCommerce…
10:23:05  INFO      Creados OK: 4 producto(s)
10:23:05  INFO      Sincronización completada
```

### Requisitos antes de sincronizar

La aplicación validará automáticamente que todos los campos de **Settings** estén completos antes de iniciar la sincronización. Si falta algún dato, se mostrará un mensaje de error indicando qué campo completar.

---

## 7. Dónde se guardan los datos

Todos los datos ingresados en la aplicación se guardan en el archivo:

```
[Carpeta de instalación]\data.json
```

Por ejemplo: `C:\WooCommerceConnector\data.json`

Este archivo se crea automáticamente la primera vez que guarda datos. Contiene:
- Configuración de Settings (URLs y credenciales)
- Configuración de programación (días y hora)
- Preferencias de sincronización

> ⚠️ **Seguridad:** Este archivo contiene sus credenciales de API. No lo comparta ni lo suba a repositorios públicos.

---

## 8. Solución de problemas

### La aplicación no abre / aparece error de Windows SmartScreen

**Solución:** Haga clic en "Más información" en el diálogo de SmartScreen y luego en "Ejecutar de todas formas". Esto ocurre porque el ejecutable no está firmado digitalmente.

---

### Error: "No se pudo conectar con WooCommerce" / código 403

**Causas posibles:**
- La URL de WordPress incluye `www.` — la aplicación lo elimina automáticamente, pero verifique que la URL sea correcta
- Las credenciales Consumer Key / Consumer Secret son incorrectas
- El servidor está bloqueando la conexión (Cloudflare u otro WAF)

**Solución:**
1. Verifique que la URL en Settings sea correcta (ej: `https://mitienda.com`)
2. Regenere las claves API en WooCommerce y actualice el campo correspondiente
3. Haga clic en **"Guardar Settings"** nuevamente

---

### Error: "Login keyError" en los logs / ResultItems vacío

**Causa:** El Token de OIS es incorrecto o ha expirado.

**Solución:** Solicite un nuevo token a su administrador de OIS y actualícelo en el campo **"Token / API Key"** de Settings.

---

### La sincronización termina con 0 productos creados

**Causas posibles:**
- Los productos de OIS tienen nombres vacíos (se omiten automáticamente)
- Los productos ya existen en WooCommerce y se seleccionó "solo productos nuevos"

**Solución:** Revise el panel de logs para ver el detalle de qué ocurrió con cada producto.

---

### Los datos no se guardan entre sesiones

**Causa:** La aplicación no tiene permisos de escritura en la carpeta de instalación.

**Solución:**
1. Mueva la carpeta de la aplicación a `C:\WooCommerceConnector\` o a otra ubicación donde el usuario tenga permisos de escritura
2. Evite instalarla en `C:\Program Files\` ya que esa carpeta requiere permisos de administrador

---

### El archivo `data.json` fue eliminado o está corrupto

**Solución:** Simplemente vuelva a completar los formularios de Settings y Programming y guárde los datos nuevamente. La aplicación creará un nuevo archivo `data.json` automáticamente.

---

## Soporte

Para reportar problemas o solicitar ayuda, contacte al administrador del sistema o al equipo de desarrollo.

---

*Manual generado para WooCommerce Connector v1.0*
