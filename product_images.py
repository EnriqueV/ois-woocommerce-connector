"""Download OIS product images and attach reviewed files to Shopify products."""
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from ois_client import OISClient
from shopify_sync import sku_of


def download_image(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.oisimobile.com", "oisimobile.com"}:
        raise ValueError("La imagen debe provenir de OIS por HTTPS.")
    try:
        with requests.get(url, timeout=30, stream=True, allow_redirects=False) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > 20 * 1024 * 1024:
                    raise ValueError("Imagen mayor de 20 MB.")
    except requests.RequestException:
        raise RuntimeError("No se pudo descargar la imagen desde OIS.") from None
    raw = bytes(data)
    if raw.startswith(b"\xff\xd8\xff"):
        return raw, "image/jpeg", ".jpg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return raw, "image/png", ".png"
    if raw[:6] in {b"GIF87a", b"GIF89a"}:
        return raw, "image/gif", ".gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return raw, "image/webp", ".webp"
    raise ValueError("OIS no devolvió una imagen JPEG, PNG, GIF o WebP.")


def media_for_product(client, product_id):
    media, cursor = [], None
    while True:
        product = client.graphql("""
            query ($id: ID!, $after: String) {
              product(id: $id) {
                media(first: 100, after: $after) {
                  nodes { id alt mediaContentType status }
                  pageInfo { hasNextPage endCursor }
                }
              }
            }
        """, id=product_id, after=cursor)["product"]
        if product is None:
            raise ValueError("El producto ya no existe en Shopify.")
        connection = product["media"]
        media.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            return media
        cursor = connection["pageInfo"]["endCursor"]


def prepare_images(client, config, directory, catalog=None):
    try:
        if catalog is None:
            catalog = OISClient(config["OIS_PRODUCTS_URL"], config["OIS_API_TOKEN"]).fetch_catalog()
        response = requests.get(
            OISClient(config["OIS_IMAGES_URL"], config["OIS_API_TOKEN"])._build_url(), timeout=30
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        raise RuntimeError("No se pudo consultar OIS. Revisa la URL de imágenes y su clave.") from None
    if payload.get("Login", {}).get("status") != "Logged In" or not isinstance(payload.get("ResultImages"), list):
        raise ValueError("OIS no devolvió ResultImages con una sesión válida.")
    items = {}
    for item in catalog["ResultItems"]:
        items.setdefault(str(item.get("cItemId")), []).append(item)
    location, publication = client.location_id(), client.online_store_id()
    rows, errors = [], []
    for image in sorted(payload["ResultImages"], key=lambda row: -int(row.get("primary") or 0)):
        if str(image.get("active")) != "1":
            continue
        item_id = str(image.get("cItemId"))
        identity = str(image.get("cItemFileXrefId") or "")
        try:
            candidates = items.get(item_id, [])
            if len(candidates) != 1 or not sku_of(candidates[0]):
                raise ValueError("Falta un artículo único en ResultItems para esta imagen.")
            item = candidates[0]
            variant = client.find_variant(sku_of(item), location, publication)
            if not identity:
                raise ValueError("La imagen no tiene cItemFileXrefId.")
            raw, mime, extension = download_image(image.get("fileurl", ""))
            digest = sha256(raw).hexdigest()
            marker = f"OIS image {item_id}/{identity} {digest}"
            existing = media_for_product(client, variant["product"]["id"]) if variant else []
            matching = [media for media in existing if media["alt"] == marker and media["status"] != "FAILED"]
            token = uuid4().hex
            filename = f"ois-{item_id}-{identity}{extension}"
            path = Path(directory) / (token + extension)
            path.write_bytes(raw)
            rows.append({
                "id": token, "filename": filename, "path": str(path), "mime": mime,
                "sku": sku_of(item), "title": item.get("name") or sku_of(item),
                "product_id": variant["product"]["id"] if variant else None, "marker": marker,
                "status": "existing" if matching else "upload",
            })
        except (ValueError, RuntimeError) as exc:
            errors.append(f"Artículo {item_id}, imagen {identity}: {exc}")
    return rows, errors


def upload_image(client, row):
    existing = media_for_product(client, row["product_id"])
    if any(media["alt"] == row["marker"] and media["status"] != "FAILED" for media in existing):
        return False
    target = client.mutate("stagedUploadsCreate", """
        mutation ($input: [StagedUploadInput!]!) {
          stagedUploadsCreate(input: $input) {
            stagedTargets { url resourceUrl parameters { name value } }
            userErrors { field message }
          }
        }
    """, input=[{
        "filename": row["filename"], "mimeType": row["mime"],
        "resource": "PRODUCT_IMAGE", "httpMethod": "POST",
    }])["stagedTargets"][0]
    try:
        with open(row["path"], "rb") as file:
            response = requests.post(
                target["url"], data=[(p["name"], p["value"]) for p in target["parameters"]],
                files={"file": (row["filename"], file, row["mime"])}, timeout=90,
            )
        response.raise_for_status()
    except requests.RequestException:
        raise RuntimeError("Falló la transferencia del archivo a Shopify.") from None
    client.mutate("productUpdate", """
        mutation ($product: ProductUpdateInput!, $media: [CreateMediaInput!]) {
          productUpdate(product: $product, media: $media) {
            userErrors { field message }
          }
        }
    """, product={"id": row["product_id"]}, media=[{
        "originalSource": target["resourceUrl"], "mediaContentType": "IMAGE", "alt": row["marker"],
    }])
    return True
