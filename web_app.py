"""Browser interface for the OIS Shopify connector. Run with python web_app.py."""
from datetime import timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import threading
import time
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor

from dotenv import set_key
from flask import Flask, jsonify, render_template, request, session, redirect, url_for, send_file

from werkzeug.security import generate_password_hash, check_password_hash

from product_images import prepare_images, upload_image

from ois_client import OISClient
from shopify_sync import ShopifyClient, apply_preview, preview, read_connector_env

ROOT = Path(__file__).resolve().parent
FIELDS = {
    "SHOPIFY_SHOP": "Shopify shop",
    "SHOPIFY_CLIENT_ID": "Shopify Client ID",
    "SHOPIFY_CLIENT_SECRET": None,
    "OIS_PRODUCTS_URL": "OIS Products URL",
    "OIS_API_TOKEN": "Token / API Key",
    "OIS_IMAGES_URL": None,
}
SECRET_FIELDS = {"SHOPIFY_CLIENT_SECRET", "OIS_API_TOKEN", "OIS_PRODUCTS_URL", "OIS_IMAGES_URL"}


def configuration():
    env = read_connector_env()
    saved = {}
    path = ROOT / "data.json"
    if path.exists():
        saved = list(json.loads(path.read_text()).get("settings", {}).values())
        saved = saved[-1] if saved else {}
    return {
        key: (env.get(key) or saved.get(label, "") or
              ("w7hsns-n1" if key == "SHOPIFY_SHOP" else "")).strip()
        for key, label in FIELDS.items()
    }


def create_app():
    app = Flask(__name__, template_folder="web_ui", static_folder="web_ui", static_url_path="/assets")
    env = read_connector_env()
    username = env.get("ADMIN_USERNAME", "")
    password = env.get("ADMIN_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("Configura ADMIN_USERNAME y ADMIN_PASSWORD en .env o en el hosting.")
    password_hash = generate_password_hash(password)
    auth_version = sha256((username + "\0" + password).encode()).hexdigest()
    session_secret = env.get("SESSION_SECRET", "").strip()
    if env.get("RENDER") and not session_secret:
        raise RuntimeError(
            "Configura SESSION_SECRET en Environment de Render con un valor aleatorio estable."
        )
    app.secret_key = session_secret or secrets.token_bytes(32)
    allowed_hosts = {"127.0.0.1", "localhost"}
    allowed_hosts.update(host.strip() for host in env.get("ALLOWED_HOSTS", "").split(",") if host.strip())
    if env.get("RENDER_EXTERNAL_HOSTNAME"):
        allowed_hosts.add(env["RENDER_EXTERNAL_HOSTNAME"])
    app.config.update(
        SESSION_COOKIE_SECURE=bool(env.get("RENDER")),
        SESSION_COOKIE_NAME="ois_shopify_session",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    login_attempts = []
    login_lock = threading.Lock()
    app.config.update(MAX_CONTENT_LENGTH=32768, SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_HTTPONLY=True)
    executor = ThreadPoolExecutor(max_workers=1)
    lock = threading.Lock()
    state = {"job": None, "plan": None, "images": None}
    image_files = TemporaryDirectory(prefix="ois-images-")
    app.extensions["image_files"] = image_files

    def safe_error(exc, config):
        if isinstance(exc, (RuntimeError, ValueError)):
            message = str(exc)
            for key in SECRET_FIELDS:
                if config.get(key):
                    message = message.replace(config[key], "[oculto]")
            return message[:2000]
        return "Falló la conexión. Genera otra vista previa para revisar el estado actual."

    @app.before_request
    def protect():
        if request.host.split(":")[0] not in allowed_hosts:
            return jsonify(error="Host no permitido."), 403
        if request.endpoint == "static" or request.path == "/health":
            return
        if request.endpoint != "login" and session.get("auth_version") != auth_version:
            if request.path.startswith("/api/"):
                return jsonify(error="Inicia sesión para continuar."), 401
            return redirect(url_for("login"))
        session.setdefault("csrf", secrets.token_hex(32))
        if request.method == "POST":
            if not secrets.compare_digest(
                request.headers.get("X-CSRF-Token") or request.form.get("csrf", ""), session["csrf"]
            ):
                if request.endpoint == "login":
                    session.clear()
                    session["csrf"] = secrets.token_hex(32)
                    return render_template(
                        "login.html", csrf=session["csrf"],
                        error="La sesión del formulario venció. Ingresa tus credenciales otra vez.",
                    ), 403
                return jsonify(error="La sesión del formulario venció. Recarga la página."), 403

    @app.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; form-action 'self'"
        return response

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        status = 200
        if request.method == "POST":
            with login_lock:
                now = time.monotonic()
                login_attempts[:] = [stamp for stamp in login_attempts if now - stamp < 60]
                if len(login_attempts) >= 5:
                    error = "Espera un minuto antes de volver a intentar."
                    status = 429
                else:
                    login_attempts.append(now)
                    valid_password = check_password_hash(password_hash, request.form.get("password", ""))
                    valid_user = secrets.compare_digest(request.form.get("username", "").encode(), username.encode())
                    if valid_password and valid_user:
                        session.clear()
                        session.permanent = True
                        session["auth_version"] = auth_version
                        session["csrf"] = secrets.token_hex(32)
                        login_attempts.clear()
                        return redirect(url_for("index"))
                    error = "Usuario o contraseña incorrectos."
                    status = 401
        return render_template("login.html", csrf=session["csrf"], error=error), status

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def index():
        session.setdefault("csrf", secrets.token_hex(32))
        return render_template("index.html", csrf=session["csrf"])

    @app.get("/api/config")
    def get_config():
        config = configuration()
        return jsonify(
            values={key: value for key, value in config.items() if key not in SECRET_FIELDS},
            configured={key: bool(value) for key, value in config.items()},
        )

    @app.post("/api/config")
    def save_config():
        values = request.get_json() or {}
        if any(key not in FIELDS or not isinstance(value, str) for key, value in values.items()):
            return jsonify(error="Configuración inválida."), 400
        with lock:
            if state["job"] and state["job"]["status"] == "running":
                return jsonify(error="Espera a que termine la operación."), 409
            path = ROOT / ".env"
            path.touch(mode=0o600, exist_ok=True)
            os.chmod(path, 0o600)
            for key, value in values.items():
                # Blank secret inputs keep the server's existing value.
                if key in SECRET_FIELDS and not value.strip():
                    continue
                set_key(path, key, value.strip())
            state["plan"] = None
        overridden = [key for key in values if key in os.environ]
        return jsonify(saved=True, overridden=overridden)

    def run_job(job, operation, config, plan):
        try:
            if operation == "preview":
                if not all(config[key] for key in ("SHOPIFY_SHOP", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET", "OIS_PRODUCTS_URL")):
                    raise ValueError("Completa las credenciales de Shopify y la URL de OIS.")
                if not config["OIS_API_TOKEN"] and not OISClient.has_url_key(config["OIS_PRODUCTS_URL"]):
                    raise ValueError("Configura el token de OIS o inclúyelo en la URL.")
                client = ShopifyClient(config["SHOPIFY_SHOP"], config["SHOPIFY_CLIENT_ID"], config["SHOPIFY_CLIENT_SECRET"])
                try:
                    catalog = OISClient(config["OIS_PRODUCTS_URL"], config["OIS_API_TOKEN"]).fetch_catalog()
                except Exception:
                    raise RuntimeError("No se pudo consultar OIS. Revisa la URL y el token.") from None
                location, rows, errors = preview(client, catalog)
                image_rows = []
                if config["OIS_IMAGES_URL"]:
                    for path in Path(image_files.name).iterdir():
                        path.unlink()
                    image_rows, image_errors = prepare_images(client, config, image_files.name, catalog)
                    errors.extend(image_errors)
                for row in rows:
                    matching = [image for image in image_rows if image["sku"] == row["sku"]]
                    row["images"] = [
                        {"id": image["id"], "status": image["status"]} for image in matching
                    ]
                    if row["action"] == "unchanged" and any(image["status"] == "upload" for image in matching):
                        row["action"] = "update"
                plan_id = secrets.token_hex(16)
                result = {
                    "received": len(catalog["ResultItems"]),
                    "groups": len(catalog.get("ResultItemGroups") or []),
                    "unchanged": sum(row["action"] == "unchanged" for row in rows),
                    "omitted": len(catalog["ResultItems"]) - len(rows),
                    "rows": rows,
                    "errors": errors,
                    "plan_id": plan_id,
                }
                with lock:
                    state["images"] = {"rows": image_rows}
                    state["plan"] = {
                        "id": plan_id, "client": client, "location": location,
                        "rows": [row for row in rows if row["action"] != "unchanged"],
                        "config": config, "expires": time.monotonic() + 1800,
                        "images": image_rows,
                    }
            else:
                applied, errors = apply_preview(plan["client"], plan["location"], plan["rows"])
                products = {row["sku"]: row["product_id"] for row in applied}
                uploaded = 0
                for image in plan["images"]:
                    if image["status"] != "upload" or image["sku"] not in products:
                        continue
                    try:
                        uploaded += int(upload_image(
                            plan["client"], {**image, "product_id": products[image["sku"]]},
                        ))
                    except Exception as exc:
                        errors.append(f"{image['sku']}: {safe_error(exc, config)}")
                result = {"applied": len(applied), "images_uploaded": uploaded, "errors": errors}
            # Serialize through Flask only after the job has finished.
            with lock:
                job.update(status="done", result=result)
        except Exception as exc:
            with lock:
                job.update(status="error", error=safe_error(exc, config))

    @app.post("/api/<operation>")
    def start(operation):
        if operation not in {"preview", "apply"}:
            return jsonify(error="Operación desconocida."), 404
        with lock:
            if state["job"] and state["job"]["status"] == "running":
                return jsonify(error="Ya hay una operación en curso."), 409
            config = configuration()
            plan = state["plan"]
            if operation == "apply":
                data = request.get_json() or {}
                if not plan or data.get("plan_id") != plan["id"]:
                    return jsonify(error="Genera una nueva vista previa."), 409
                if plan["config"] != config or time.monotonic() > plan["expires"]:
                    state["plan"] = None
                    return jsonify(error="La vista previa venció o cambió la configuración."), 409
            state["plan"] = None
            job = {"id": secrets.token_hex(16), "status": "running", "operation": operation}
            state["job"] = job
            executor.submit(run_job, job, operation, config, plan)
            return jsonify(job), 202

    @app.get("/api/images/<image_id>")
    def image_file(image_id):
        with lock:
            images = state["images"]
            row = next((row for row in images["rows"] if row["id"] == image_id), None) if images else None
            if row is None:
                return jsonify(error="Consulta las imágenes nuevamente."), 404
            return send_file(
                row["path"], mimetype=row["mime"],
                as_attachment=request.args.get("download") == "1", download_name=row["filename"],
            )

    @app.get("/api/job")
    def job_status():
        with lock:
            return jsonify(state["job"] or {"status": "idle"})

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8080, debug=False, threaded=True)
