"""Sync OIS catalog prices and available inventory to Shopify."""
import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from time import monotonic
from uuid import uuid4

import requests
from dotenv import dotenv_values

from ois_client import OISClient


LOCATION = "Shop location"
API_VERSION = "2026-10"
TOKEN_PATH = "/admin/oauth/access_token"
OAUTH_ERRORS = {
    "application_cannot_be_found": "Copia de nuevo el Client ID desde Settings → Credentials de la app instalada.",
    "app_not_installed": "Instala esta app en la tienda desde Dev Dashboard → Installs.",
    "invalid_client_secret": "Carga el Client secret vigente de la misma app en la terminal.",
    "shop_not_permitted": "Verifica que la app y la tienda estén en la misma organización.",
    "invalid_client": "Verifica que el Client ID y el Client secret activo sean de la misma app.",
    "invalid_grant": "Verifica que la app esté instalada en esta tienda y que sus credenciales estén vigentes.",
    "unauthorized_client": "Verifica que la app instalada pueda usar client_credentials en esta tienda.",
}


def read_connector_env():
    entry = sys.executable if getattr(sys, "frozen", False) else __file__
    values = dotenv_values(Path(entry).resolve().with_name(".env"), interpolate=False)
    return {**values, **os.environ}


class ShopifyClient:
    def __init__(self, shop, client_id, client_secret):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", shop):
            raise ValueError("SHOPIFY_SHOP debe ser el subdominio sin .myshopify.com.")
        self.url = f"https://{shop}.myshopify.com"
        self.credentials = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        self.session = requests.Session()
        self.token = ""
        self.expires_at = 0

    def post(self, path, **kwargs):
        try:
            response = self.session.post(
                self.url + path, timeout=30, allow_redirects=False, **kwargs
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Error de conexión con Shopify ({type(exc).__name__}).") from None
        if not response.ok or response.is_redirect:
            if path == TOKEN_PATH:
                request_id = response.headers.get("X-Request-ID", "")
                trace = f" Request ID: {request_id}." if re.fullmatch(
                    r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}(?:-\d+)?",
                    request_id,
                ) else ""
                for code, hint in OAUTH_ERRORS.items():
                    if re.search(rf"\b{code}\b", response.text.lower()):
                        raise RuntimeError(f"Shopify OAuth ({code}): {hint}{trace}")
                raise RuntimeError(
                    f"Shopify rechazó la autenticación (HTTP {response.status_code}). "
                    "Verifica el Client ID, el Client secret activo y la instalación de la app en la tienda."
                    + trace
                )
            raise RuntimeError(f"Shopify devolvió HTTP {response.status_code} en {path}.")
        return response.json()

    def graphql(self, query, **variables):
        if monotonic() >= self.expires_at:
            auth = self.post(TOKEN_PATH, data=self.credentials)
            self.token = auth["access_token"]
            self.expires_at = monotonic() + int(auth["expires_in"]) - 60
        response = self.post(
            f"/admin/api/{API_VERSION}/graphql.json",
            headers={"X-Shopify-Access-Token": self.token},
            json={"query": query, "variables": variables},
        )
        if response.get("errors"):
            raise RuntimeError(f"Shopify GraphQL: {response['errors']}")
        return response["data"]

    def mutate(self, field, query, **variables):
        result = self.graphql(query, **variables)[field]
        if result["userErrors"]:
            raise RuntimeError(f"{field}: {result['userErrors']}")
        return result

    def nodes(self, field, query, **variables):
        cursor = None
        while True:
            connection = self.graphql(query, after=cursor, **variables)[field]
            yield from connection["nodes"]
            if not connection["pageInfo"]["hasNextPage"]:
                return
            cursor = connection["pageInfo"]["endCursor"]

    def location_id(self):
        matches = [
            location["id"]
            for location in self.nodes("locations", """
                query ($after: String) {
                  locations(first: 100, after: $after) {
                    nodes { id name isActive }
                    pageInfo { hasNextPage endCursor }
                  }
                }
            """)
            if location["isActive"] and location["name"] == LOCATION
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Se esperaba una ubicación activa llamada {LOCATION!r}.")
        return matches[0]

    def online_store_id(self):
        matches = [
            publication["id"]
            for publication in self.nodes("publications", """
                query ($after: String) {
                  publications(first: 50, after: $after, catalogType: APP) {
                    nodes {
                      id
                      catalog { ... on AppCatalog { apps(first: 10) { nodes { title } } } }
                    }
                    pageInfo { hasNextPage endCursor }
                  }
                }
            """)
            if any(
                app["title"] in {"Online Store", "Tienda online"}
                for app in (publication["catalog"] or {}).get("apps", {}).get("nodes", [])
            )
        ]
        if len(matches) != 1:
            raise RuntimeError("No se encontró una única publicación del canal Online Store.")
        return matches[0]

    def publish_product(self, product_id, status, published, publication_id):
        if not published:
            self.mutate("publishablePublish", """
                mutation ($id: ID!, $publication: ID!) {
                  publishablePublish(id: $id, input: [{publicationId: $publication}]) {
                    userErrors { field message }
                  }
                }
            """, id=product_id, publication=publication_id)
        if status == "DRAFT":
            self.mutate("productUpdate", """
                mutation ($product: ProductUpdateInput!) {
                  productUpdate(product: $product) { userErrors { field message } }
                }
            """, product={"id": product_id, "status": "ACTIVE"})

    def find_variant(self, sku, location_id, publication_id):
        # Escape Shopify's search syntax independently of GraphQL variables.
        escaped = re.sub(r'([\\":()])', r'\\\1', sku)
        matches = [
            variant
            for variant in self.nodes("productVariants", """
                query ($after: String, $search: String!, $location: ID!, $publication: ID!) {
                  productVariants(first: 25, after: $after, query: $search) {
                    nodes {
                      id sku price
                      product { id handle status publishedOnPublication(publicationId: $publication) }
                      inventoryItem {
                        id tracked
                        inventoryLevel(locationId: $location) {
                          quantities(names: ["available"]) { quantity }
                        }
                      }
                    }
                    pageInfo { hasNextPage endCursor }
                  }
                }
            """, search=f'sku:"{escaped}"', location=location_id, publication=publication_id)
            if variant["sku"] == sku
        ]
        if len(matches) > 1:
            raise RuntimeError("SKU duplicado en Shopify.")
        return next(iter(matches), None)

    def create_product(self, title, sku, price, unit_price, quantity, location_id):
        # A stable handle lets a later run detect a prior creation even while
        # Shopify's SKU search index is catching up.
        handle = ois_handle(sku)
        existing = self.graphql("""
            query ($handle: String!) {
              productByIdentifier(identifier: {handle: $handle}) { id }
            }
        """, handle=handle)["productByIdentifier"]
        if existing:
            raise RuntimeError("Ya existe un producto con el identificador OIS; verifica su SKU.")
        result = self.mutate("productSet", """
            mutation ($input: ProductSetInput!) {
              productSet(input: $input, synchronous: true) {
                product { id }
                userErrors { field message }
              }
            }
        """, input={
            "title": title,
            "handle": handle,
            "status": "DRAFT",
            "productOptions": [{
                "name": "Presentación",
                "values": [{"name": "Unidad"}, {"name": "Caja"}],
            }],
            "variants": [
                {
                    "sku": variant_sku,
                    "price": str(variant_price),
                    "optionValues": [{"optionName": "Presentación", "name": name}],
                    "inventoryItem": {"tracked": True},
                    "inventoryQuantities": [
                        {"locationId": location_id, "name": "available", "quantity": stock}
                    ],
                }
                for name, variant_sku, variant_price, stock in (
                    ("Unidad", unit_sku(sku), unit_price, 0),
                    ("Caja", sku, price, quantity),
                )
            ],
        })
        return result["product"]["id"]

    def update_variant(self, variant, price, quantity, location_id, apply):
        item = variant["inventoryItem"]
        level = item["inventoryLevel"]
        current = level["quantities"][0]["quantity"] if level else None
        changes = {}
        if Decimal(variant["price"]) != price:
            changes["price"] = str(price)
        if quantity is not None and not item["tracked"]:
            changes["inventoryItem"] = {"tracked": True}

        if apply and changes:
            self.mutate("productVariantsBulkUpdate", """
                mutation ($product: ID!, $variants: [ProductVariantsBulkInput!]!) {
                  productVariantsBulkUpdate(productId: $product, variants: $variants) {
                    userErrors { field message }
                  }
                }
            """, product=variant["product"]["id"], variants=[{"id": variant["id"], **changes}])

        stock_changed = quantity is not None and current != quantity
        if apply and stock_changed and current is None:
            self.mutate("inventoryActivate", """
                mutation ($item: ID!, $location: ID!, $quantity: Int!, $key: String!) {
                  inventoryActivate(inventoryItemId: $item, locationId: $location,
                    available: $quantity) @idempotent(key: $key) {
                    userErrors { field message }
                  }
                }
            """, item=item["id"], location=location_id, quantity=quantity, key=str(uuid4()))
        elif apply and stock_changed:
            self.mutate("inventorySetQuantities", """
                mutation ($input: InventorySetQuantitiesInput!, $key: String!) {
                  inventorySetQuantities(input: $input) @idempotent(key: $key) {
                    userErrors { code field message }
                  }
                }
            """, key=str(uuid4()), input={
                "name": "available",
                "reason": "correction",
                "quantities": [{
                    "inventoryItemId": item["id"],
                    "locationId": location_id,
                    "quantity": quantity,
                    "changeFromQuantity": current,
                }],
            })
        return "update" if changes or stock_changed else "unchanged"


def ois_handle(sku):
    return "ois-" + sha256(sku.encode()).hexdigest()


def unit_sku(sku):
    return f"{sku}-UNIT"


def price_index(catalog):
    return {
        (str(row["cItemId"]), str(row["cCustomerGroupId"])): row.get("newPrice")
        for row in (catalog.get("ResultCustomerGroupPrice") or [])
    }


def item_prices(item, prices):
    item_id = str(item.get("cItemId"))
    case = prices.get((item_id, "4"))
    unit = prices.get((item_id, "3"))
    case_price = Decimal(str(item.get("listPrice") if case is None else case))
    if unit is not None:
        unit_price = Decimal(str(unit))
    else:
        packsize = Decimal(str(item.get("packsize") or 0))
        unit_price = (
            (case_price / packsize).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if packsize.is_finite() and packsize > 0 else None
        )
    return case_price, unit_price


def sku_of(item):
    upc = item.get("upcCode")
    if upc is not None and str(upc).strip():
        return str(upc).strip()
    item_id = str(item.get("cItemId") or "").strip()
    if item_id.isascii() and item_id.isdecimal() and int(item_id) > 0:
        return f"OIS-{int(item_id)}"
    return ""


def preview(shopify, catalog, *, selected_sku=None):
    items = catalog["ResultItems"]
    prices = price_index(catalog)
    location = shopify.location_id()
    publication = shopify.online_store_id()
    counts = Counter(map(sku_of, items))
    if selected_sku is not None and not counts[selected_sku]:
        raise ValueError(f"SKU {selected_sku!r} no encontrado en OIS.")

    changes, errors = [], []
    for item in items:
        sku = sku_of(item)
        if selected_sku is not None and sku != selected_sku:
            continue
        if not sku:
            errors.append("Artículo OIS sin UPC ni cItemId válido.")
            continue
        try:
            if counts[sku] > 1:
                raise ValueError("SKU duplicado en OIS.")
            price, unit_price = item_prices(item, prices)
            stock = Decimal(str(item.get("inStock")))
            if not price.is_finite() or price < 0:
                raise ValueError("Precio OIS inválido.")
            if not stock.is_finite() or not 0 <= stock <= 2147483647 or stock != int(stock):
                raise ValueError("Stock OIS inválido.")
            quantity = int(stock)
            variant = shopify.find_variant(sku, location, publication)
            unit_variant = None
            if variant is None or variant["product"]["handle"] == ois_handle(sku):
                if counts[unit_sku(sku)]:
                    raise ValueError("El SKU derivado de Unidad coincide con un SKU de OIS.")
                unit_variant = shopify.find_variant(unit_sku(sku), location, publication)
                if unit_variant and (
                    variant is None or unit_variant["product"]["id"] != variant["product"]["id"]
                ):
                    raise ValueError("El SKU de Unidad ya pertenece a otro producto.")
            if variant is None or unit_variant:
                if unit_price is None or not unit_price.is_finite() or unit_price < 0:
                    raise ValueError("Falta un precio de Unidad válido y no se pudo calcular con packsize.")
            title = str(item.get("name") or "").strip()
            publish = False
            if variant:
                action = shopify.update_variant(variant, price, quantity, location, False)
                if unit_variant and Decimal(unit_variant["price"]) != unit_price:
                    action = "update"
                product = variant["product"]
                publish = product["handle"] == ois_handle(sku) and (
                    product["status"] == "DRAFT" or (
                        product["status"] == "ACTIVE" and not product["publishedOnPublication"]
                    )
                )
                if publish and action == "unchanged":
                    action = "publish"
            elif title:
                action = "create_and_publish"
                publish = True
            else:
                raise ValueError("El artículo nuevo no tiene nombre en OIS.")
            changes.append({
                "sku": sku, "action": action, "price": str(price),
                "available": quantity, "variant": variant, "title": title,
                "publish": publish, "publication": publication,
                "unit_price": str(unit_price) if unit_price is not None else None,
                "unit_variant": unit_variant,
            })
        except (RuntimeError, ValueError, InvalidOperation, KeyError) as exc:
            errors.append(f"{sku!r}: {exc or 'Datos OIS inválidos.'}")
    return location, changes, errors


def apply_preview(shopify, location, changes):
    if shopify.location_id() != location:
        raise RuntimeError("La ubicación cambió. Genera una nueva vista previa.")
    applied, errors = [], []
    for row in changes:
        if row["action"] == "unchanged":
            continue
        sku = row["sku"]
        publication = row["publication"]
        try:
            variant = shopify.find_variant(sku, location, publication)
            if variant != row["variant"]:
                raise RuntimeError("El producto cambió en Shopify. Genera una nueva vista previa.")
            if variant is None or variant["product"]["handle"] == ois_handle(sku):
                unit_variant = shopify.find_variant(unit_sku(sku), location, publication)
                if unit_variant != row["unit_variant"]:
                    raise RuntimeError("La variante Unidad cambió. Genera una nueva vista previa.")
            price = Decimal(row["price"])
            quantity = row["available"]
            if variant:
                if row["action"] != "publish":
                    shopify.update_variant(variant, price, quantity, location, True)
                if row["unit_variant"]:
                    shopify.update_variant(
                        row["unit_variant"], Decimal(row["unit_price"]), None, location, True,
                    )
                if row["publish"]:
                    product = variant["product"]
                    shopify.publish_product(
                        product["id"], product["status"], product["publishedOnPublication"], publication,
                    )
            else:
                product_id = shopify.create_product(
                    row["title"], sku, price, Decimal(row["unit_price"]), quantity, location,
                )
                shopify.publish_product(product_id, "DRAFT", False, publication)
            applied.append({**row, "product_id": variant["product"]["id"] if variant else product_id})
        except (RuntimeError, ValueError, KeyError) as exc:
            errors.append(f"{sku!r}: {exc}")
    return applied, errors


def sync(shopify, items, *, apply, selected_sku):
    location, rows, errors = preview(shopify, items, selected_sku=selected_sku)
    if apply:
        applied, apply_errors = apply_preview(shopify, location, rows)
        rows = applied + [row for row in rows if row["action"] == "unchanged"]
        errors.extend(apply_errors)
    for row in rows:
        print(json.dumps({
            **{key: row[key] for key in ("sku", "action", "price", "unit_price", "available")},
            "location": LOCATION, "dry_run": not apply,
        }))
    for error in errors:
        print(error, file=sys.stderr)
    return int(bool(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Escribir en Shopify.")
    parser.add_argument("--sku", type=str.strip, help="Procesar un SKU de OIS.")
    args = parser.parse_args()
    if args.sku == "":
        parser.error("--sku requiere un valor.")
    env = read_connector_env()
    required = ("SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET", "OIS_PRODUCTS_URL")
    config = {name: (env.get(name) or "").strip() for name in required}
    missing = [name for name, value in config.items() if not value]
    config["OIS_API_TOKEN"] = (env.get("OIS_API_TOKEN") or "").strip()
    if not config["OIS_API_TOKEN"] and not OISClient.has_url_key(config["OIS_PRODUCTS_URL"]):
        missing.append("OIS_API_TOKEN")
    if missing:
        parser.error("Faltan variables de entorno: " + ", ".join(missing))
    try:
        shopify = ShopifyClient(
            (env.get("SHOPIFY_SHOP") or "w7hsns-n1").strip(),
            config["SHOPIFY_CLIENT_ID"],
            config["SHOPIFY_CLIENT_SECRET"],
        )
        items = OISClient(config["OIS_PRODUCTS_URL"], config["OIS_API_TOKEN"]).fetch_catalog()
        return sync(shopify, items, apply=args.apply, selected_sku=args.sku)
    except Exception as exc:
        # Upstream transport errors can include the OIS URL and its query token.
        if isinstance(exc, requests.RequestException):
            print("Error al consultar OIS.", file=sys.stderr)
        else:
            message = str(exc)
            for key in ("OIS_API_TOKEN", "SHOPIFY_CLIENT_SECRET"):
                if config[key]:
                    message = message.replace(config[key], "[redactado]")
            print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
