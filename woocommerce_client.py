import logging
import requests
from requests.auth import HTTPBasicAuth
from typing import Optional
from dataclasses import dataclass, field

# ── logger central del módulo ──────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  [%(levelname)-8s]  %(name)s  →  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("woo_connector")

# Imagen por defecto: PNG accesible que WordPress puede importar vía sideload.
# Se usa un PNG de WordPress.org para garantizar compatibilidad con el uploader.
# Dejar en cadena vacía ("") para no enviar imagen (WordPress usará el placeholder del tema).
DEFAULT_IMAGE_URL = ""
SYNC_LIMIT = 5  # Productos a enviar en modo prueba


def _mask(value: str, visible: int = 6) -> str:
    """Muestra solo los primeros `visible` caracteres y enmascara el resto."""
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible)


def _normalize_wp_url(url: str) -> str:
    """
    Cloudflare en algunos sitios bloquea peticiones sin User-Agent browser
    cuando el host incluye 'www.'. Normalizamos removiendo el 'www.' del host
    para usar el dominio raíz, que sí acepta la API REST de WooCommerce.

    Ejemplos:
        https://www.mitienda.com  →  https://mitienda.com
        https://mitienda.com      →  https://mitienda.com  (sin cambios)
    """
    normalized = url.strip().rstrip("/")
    if "://www." in normalized:
        normalized = normalized.replace("://www.", "://", 1)
        log.debug("  URL normalizada (www removido): %s", normalized)
    return normalized


# User-Agent de browser para evitar bloqueos de Cloudflare / WAF
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class WooCommerceProduct:
    name: str
    regular_price: str
    description: str = ""
    short_description: str = ""
    sku: str = ""
    status: str = "publish"           # publish, draft, pending
    catalog_visibility: str = "visible"
    stock_quantity: Optional[int] = None
    manage_stock: bool = False
    stock_status: str = "instock"     # instock, outofstock, onbackorder
    weight: str = ""
    categories: list[dict] = field(default_factory=list)   # [{"id": 1}]
    images: list[dict] = field(default_factory=list)       # [{"src": "url"}]
    attributes: list[dict] = field(default_factory=list)
    type: str = "simple"              # simple, variable, grouped, external

    def to_dict(self) -> dict:
        data = {
            "name": self.name,
            "type": self.type,
            "status": self.status,
            "catalog_visibility": self.catalog_visibility,
            "description": self.description,
            "short_description": self.short_description,
            "sku": self.sku,
            "regular_price": self.regular_price,
            "manage_stock": self.manage_stock,
            "stock_status": self.stock_status,
            "weight": self.weight,
            "categories": self.categories,
            "images": self.images,
            "attributes": self.attributes,
        }
        if self.manage_stock and self.stock_quantity is not None:
            data["stock_quantity"] = self.stock_quantity
        # Limpiar campos vacíos opcionales
        return {k: v for k, v in data.items() if v != "" and v is not None}


class WooCommerceClient:
    def __init__(self, base_url: str, consumer_key: str, consumer_secret: str):
        """
        base_url:        URL de la tienda WordPress,  ej: https://mitienda.com
        consumer_key:    WordPress Client Key  (ck_xxxx)
        consumer_secret: WordPress Client Secret (cs_xxxx)
        """
        self.base_url = _normalize_wp_url(base_url)
        self.auth = HTTPBasicAuth(consumer_key, consumer_secret)
        self.api_url = f"{self.base_url}/wp-json/wc/v3"
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": _BROWSER_UA,
            "Accept": "application/json",
        }

        log.info("WooCommerceClient inicializado")
        log.debug("  base_url    : %s", self.base_url)
        log.debug("  api_url     : %s", self.api_url)
        log.debug("  consumer_key: %s", _mask(consumer_key))
        log.debug("  consumer_sec: %s", _mask(consumer_secret))

    # ── helpers ────────────────────────────────────────────────────────
    def _handle_response(self, response: requests.Response) -> dict:
        log.debug("  HTTP %s  ←  %s", response.status_code, response.url)
        if response.status_code in (200, 201):
            return response.json()
        try:
            err_msg = response.json().get("message", response.text)
        except Exception:
            err_msg = response.text
        log.error("  WooCommerce error %s: %s", response.status_code, err_msg[:300])
        raise Exception(f"Error {response.status_code}: {err_msg}")

    # ── productos ──────────────────────────────────────────────────────
    def create_product(self, product: WooCommerceProduct) -> dict:
        """Crea un producto simple en WooCommerce."""
        log.info("create_product → '%s' (sku=%s)", product.name, product.sku)
        response = requests.post(
            f"{self.api_url}/products",
            json=product.to_dict(),
            auth=self.auth,
            headers=self.headers,
        )
        result = self._handle_response(response)
        log.info("  ✓ producto creado id=%s", result.get("id"))
        return result

    def create_products_batch(self, products: list[WooCommerceProduct]) -> dict:
        """Crea múltiples productos en una sola petición (máx 100)."""
        log.info("create_products_batch → %d producto(s)", len(products))
        for i, p in enumerate(products, 1):
            log.debug("  [%d] name='%s'  price=%s  sku=%s", i, p.name, p.regular_price, p.sku)

        payload = {"create": [p.to_dict() for p in products]}
        url = f"{self.api_url}/products/batch"
        log.debug("  POST %s", url)
        response = requests.post(
            url,
            json=payload,
            auth=self.auth,
            headers=self.headers,
        )
        result = self._handle_response(response)

        created = result.get("create", [])
        ok     = [p for p in created if "id" in p]
        errors = [p for p in created if "error" in p]
        log.info("  batch result → %d ok, %d errores", len(ok), len(errors))
        for e in errors:
            log.warning("  error en producto: %s", e.get("error", {}).get("message", e))
        return result

    def update_product(self, product_id: int, data: dict) -> dict:
        """Actualiza un producto existente por ID."""
        log.info("update_product → id=%s", product_id)
        response = requests.put(
            f"{self.api_url}/products/{product_id}",
            json=data,
            auth=self.auth,
            headers=self.headers,
        )
        result = self._handle_response(response)
        log.info("  ✓ producto actualizado id=%s", result.get("id"))
        return result

    def get_product(self, product_id: int) -> dict:
        """Obtiene un producto por ID."""
        log.info("get_product → id=%s", product_id)
        response = requests.get(
            f"{self.api_url}/products/{product_id}",
            auth=self.auth,
            headers=self.headers,
        )
        return self._handle_response(response)

    def delete_product(self, product_id: int, force: bool = True) -> dict:
        """Elimina un producto por ID."""
        log.info("delete_product → id=%s  force=%s", product_id, force)
        response = requests.delete(
            f"{self.api_url}/products/{product_id}",
            params={"force": force},
            auth=self.auth,
            headers=self.headers,
        )
        result = self._handle_response(response)
        log.info("  ✓ producto eliminado id=%s", product_id)
        return result


# ── OIS Inventory Client ───────────────────────────────────────────────
class OISClient:
    """
    Cliente para la API REST de OIS Mobile Inventory.

    Endpoint:
        {ois_url}?key={api_token}

    La respuesta tiene la forma:
        { "ResultItems": [ { "name": ..., "priceList": ..., "sku": ... }, ... ] }
    """

    def __init__(self, ois_url: str, api_token: str):
        self.ois_url   = ois_url.rstrip("/")
        self.api_token = api_token

        log.info("OISClient inicializado")
        log.debug("  ois_url  : %s", self.ois_url)
        log.debug("  api_token: %s", _mask(self.api_token, visible=8))

    def _build_url(self) -> str:
        """
        Construye la URL completa.
        El token ya viene URL-encoded (%2B, %3D, etc.) desde el formulario,
        por lo que se concatena directamente sin re-encodear.
        """
        return f"{self.ois_url}?key={self.api_token}"

    def fetch_items(self) -> list[dict]:
        """Hace el GET y devuelve la lista cruda de ResultItems."""
        url = self._build_url()
        log.info("OIS fetch_items → GET %s?key=%s...", self.ois_url, _mask(self.api_token, visible=8))

        # Se pasa la URL ya armada — NO usar params={} para evitar re-encodear el token
        response = requests.get(url, timeout=30)
        log.debug("  HTTP %s  (%d bytes)", response.status_code, len(response.content))

        if response.status_code != 200:
            log.error("  OIS error %s: %s", response.status_code, response.text[:300])
            raise Exception(
                f"OIS API error {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        login_status = data.get("Login", {}).get("status", "unknown")
        log.debug("  Login status: %s", login_status)

        if login_status != "Logged In":
            log.error("  Autenticación OIS fallida: '%s'", login_status)
            raise Exception(
                f"OIS autenticación fallida (status='{login_status}'). "
                "Verifica el Token / API Key en Settings."
            )

        items = data.get("ResultItems")
        if not isinstance(items, list):
            log.error("  'ResultItems' no es lista: %s", type(items))
            raise Exception(
                f"Respuesta OIS inesperada: 'ResultItems' es {type(items).__name__}, se esperaba list."
            )

        log.info("  ✓ OIS devolvió %d item(s) en total  (TotalRecords=%s)",
                 len(items), data.get("TotalRecords"))
        return items

    def fetch_as_woo_products(self, limit: int = SYNC_LIMIT) -> list[WooCommerceProduct]:
        """
        Obtiene los items OIS y los mapea a WooCommerceProduct.

        Mapeo OIS → WooCommerce:
            name       → name, description, short_description
            listPrice  → regular_price
            upcCode    → sku
            inStock    → stock_quantity  (si > 0)
            (default)  → images[0].src
        """
        all_items  = self.fetch_items()
        raw_items  = all_items[:limit]
        log.info("fetch_as_woo_products → mapeando %d item(s) de %d totales (límite=%d)",
                 len(raw_items), len(all_items), limit)

        products = []
        for i, item in enumerate(raw_items, 1):
            name  = str(item.get("name", "")).strip()
            price = str(item.get("listPrice", 0) or 0)
            sku   = str(item.get("upcCode", "")).strip()
            stock = item.get("inStock", 0) or 0

            if not name:
                log.warning("  [%d] item sin nombre, omitido. upcCode=%s", i, item.get("upcCode"))
                continue

            log.debug("  [%d] name='%s'  price=%s  sku=%s  inStock=%s",
                      i, name, price, sku, stock)

            product = WooCommerceProduct(
                name=name,
                regular_price=price,
                description=name,
                short_description=name,
                sku=sku,
                manage_stock=True,
                stock_quantity=int(stock),
                stock_status="instock" if stock > 0 else "outofstock",
                images=[{"src": DEFAULT_IMAGE_URL}] if DEFAULT_IMAGE_URL else [],
            )
            products.append(product)

        log.info("  ✓ %d WooCommerceProduct(s) listos para subir", len(products))
        return products


def build_ois_client_from_db(tbl_settings) -> OISClient:
    """
    Lee las credenciales OIS desde TinyDB y devuelve un OISClient.

    Mapeo de campos del formulario:
        "OIS Products URL"  → ois_url
        "Token / API Key"   → api_token
    """
    log.info("build_ois_client_from_db → leyendo settings de TinyDB")
    rows = tbl_settings.all()
    if not rows:
        log.error("  TinyDB settings vacío")
        raise ValueError(
            "No hay configuración guardada. "
            "Completa el paso Settings antes de sincronizar."
        )

    cfg = rows[-1]
    ois_url   = cfg.get("OIS Products URL", "").strip()
    api_token = cfg.get("Token / API Key", "").strip()

    log.debug("  OIS Products URL  : %s", ois_url or "(vacío)")
    log.debug("  Token / API Key   : %s", _mask(api_token, 8) if api_token else "(vacío)")

    missing = [
        name for name, val in [
            ("OIS Products URL", ois_url),
            ("Token / API Key", api_token),
        ]
        if not val
    ]
    if missing:
        log.error("  Faltan campos: %s", missing)
        raise ValueError(f"Faltan campos en Settings: {', '.join(missing)}")

    log.info("  ✓ OISClient construido correctamente")
    return OISClient(ois_url=ois_url, api_token=api_token)


# ── factory: construye el cliente leyendo desde TinyDB ────────────────
def build_client_from_db(tbl_settings) -> WooCommerceClient:
    """
    Lee las credenciales guardadas en la tabla 'settings' de TinyDB
    y devuelve una instancia de WooCommerceClient lista para usar.

    Mapeo de campos del formulario → parámetros del cliente:
        "WordPress URL"            → base_url
        "WordPress Client Key"     → consumer_key
        "WordPress Client Secret"  → consumer_secret
    """
    log.info("build_client_from_db → leyendo settings de TinyDB")
    rows = tbl_settings.all()
    if not rows:
        log.error("  TinyDB settings vacío")
        raise ValueError(
            "No hay configuración guardada. "
            "Completa el paso Settings antes de sincronizar."
        )

    cfg = rows[-1]

    base_url        = cfg.get("WordPress URL", "").strip()
    consumer_key    = cfg.get("WordPress Client Key", "").strip()
    consumer_secret = cfg.get("WordPress Client Secret", "").strip()

    log.debug("  WordPress URL          : %s", base_url or "(vacío)")
    log.debug("  WordPress Client Key   : %s", _mask(consumer_key, 6) if consumer_key else "(vacío)")
    log.debug("  WordPress Client Secret: %s", _mask(consumer_secret, 6) if consumer_secret else "(vacío)")

    missing = [
        name for name, val in [
            ("WordPress URL", base_url),
            ("WordPress Client Key", consumer_key),
            ("WordPress Client Secret", consumer_secret),
        ]
        if not val
    ]
    if missing:
        log.error("  Faltan credenciales: %s", missing)
        raise ValueError(
            f"Faltan credenciales en Settings: {', '.join(missing)}"
        )

    log.info("  ✓ WooCommerceClient construido correctamente")
    return WooCommerceClient(
        base_url=base_url,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
    )
