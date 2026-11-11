import logging

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
        self.ois_url   = ois_url.rstrip("/")
        self.api_token = api_token

        log.info("OISClient inicializado")
        log.debug("  ois_url  : %s", self.ois_url)

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
        log.info("OIS fetch_items → GET catálogo")

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

    log.debug("  OIS Products URL  : %s", ois_url or "(vacío)")

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
    return client_type(ois_url=ois_url, api_token=api_token)
