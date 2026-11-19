import logging
from urllib.parse import urlsplit

import requests


log = logging.getLogger("ois_connector")


class OISClient:
    """
    Cliente para la API REST de OIS Mobile Inventory.

    Endpoint:
        {ois_url}?key={api_token}

    La respuesta tiene la forma:
        { "ResultItems": [ { ... }, ... ] }
    """

    def __init__(self, ois_url: str, api_token: str):
        self.ois_url = ois_url.strip()
        self.api_token = api_token.strip()

    @staticmethod
    def has_url_key(url: str) -> bool:
        return any(
            name == "key" and value
            for name, _, value in (
                part.partition("=") for part in urlsplit(url).query.split("&")
            )
        )

        log.info("OISClient inicializado")

    def _build_url(self) -> str:
        """
        Construye la URL completa.
        El token ya viene URL-encoded (%2B, %3D, etc.) desde el formulario,
        por lo que se concatena directamente sin re-encodear.
        """
        if self.has_url_key(self.ois_url):
            return self.ois_url
        url = urlsplit(self.ois_url)
        params = [part for part in url.query.split("&") if part and part.partition("=")[0] != "key"]
        params.append(f"key={self.api_token}")
        return url._replace(path=url.path.rstrip("/"), query="&".join(params)).geturl()

    def fetch_items(self) -> list[dict]:
        return self.fetch_catalog()["ResultItems"]

    def fetch_catalog(self) -> dict:
        """Devuelve el catálogo y sus tablas de precios en una sola consulta."""
        url = self._build_url()
        log.info("OIS fetch_items → GET catálogo")

        # Se pasa la URL ya armada — NO usar params={} para evitar re-encodear el token
        response = requests.get(url, timeout=30)
        log.debug("  HTTP %s  (%d bytes)", response.status_code, len(response.content))

        if response.status_code != 200:
            log.error("OIS devolvió HTTP %s.", response.status_code)
            raise RuntimeError(f"OIS devolvió HTTP {response.status_code}.")

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
        return data

def build_ois_client_from_db(tbl_settings, client_type=OISClient) -> OISClient:
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


    missing = [
        name for name, val in [
            ("OIS Products URL", ois_url),
            ("Token / API Key", api_token),
        ]
        if not val
    ]
    if OISClient.has_url_key(ois_url) and "Token / API Key" in missing:
        missing.remove("Token / API Key")

    if missing:
        log.error("  Faltan campos: %s", missing)
        raise ValueError(f"Faltan campos en Settings: {', '.join(missing)}")

    log.info("  ✓ OISClient construido correctamente")
    return client_type(ois_url=ois_url, api_token=api_token)
