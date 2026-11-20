import customtkinter as ctk
from tkinter import messagebox
from tinydb import TinyDB
import os
import sys
import threading
import logging
import queue

from ois_client import OISClient
from shopify_sync import LOCATION, ShopifyClient, apply_preview, preview, read_connector_env

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACTIVE_COLOR  = "#3B8ED0"
INACTIVE_COLOR = "#4A4A4A"
DONE_COLOR    = "#2FA84F"
TEXT_ACTIVE   = "#FFFFFF"
TEXT_INACTIVE = "#888888"

# ── Ruta base: funciona tanto en desarrollo como dentro del .exe ────────
# Cuando PyInstaller empaqueta el .exe, sys.frozen = True y los archivos
# temporales van a sys._MEIPASS. La DB se guarda JUNTO al .exe (no en temp).
if getattr(sys, "frozen", False):
    # Corriendo como .exe empaquetado → guardar la DB al lado del ejecutable
    _APP_DIR = os.path.dirname(sys.executable)
else:
    # Corriendo como script Python normal
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(_APP_DIR, "data.json")
db = TinyDB(DB_PATH)
tbl_settings   = db.table("settings")
tbl_programming = db.table("programming")


# ─────────────────────────────────────────────
# LOG HANDLER → cola thread-safe → CTkTextbox
# ─────────────────────────────────────────────
# Colores por nivel en el textbox (tag names)
LOG_COLORS = {
    "DEBUG"   : "#6B7280",   # gris
    "INFO"    : "#60A5FA",   # azul claro
    "WARNING" : "#FBBF24",   # amarillo
    "ERROR"   : "#F87171",   # rojo claro
    "CRITICAL": "#EF4444",   # rojo fuerte
}

class UILogHandler(logging.Handler):
    """
    Handler de logging que encola registros y los escribe
    en un CTkTextbox usando .after() para respetar el hilo de Tkinter.
    """
    def __init__(self, textbox: ctk.CTkTextbox, root: ctk.CTk):
        super().__init__()
        self._textbox = textbox
        self._root    = root
        self._queue   = queue.Queue()
        self.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(message)s",
            datefmt="%H:%M:%S",
        ))
        self._schedule_flush()

    def emit(self, record: logging.LogRecord):
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            pass

    def _schedule_flush(self):
        """Vacía la cola cada 100 ms desde el hilo principal de Tkinter."""
        self._flush()
        try:
            self._root.after(100, self._schedule_flush)
        except Exception:
            pass   # ventana cerrada

    def _flush(self):
        try:
            while True:
                record = self._queue.get_nowait()
                self._write(record)
        except queue.Empty:
            pass

    def _write(self, record: logging.LogRecord):
        msg  = self.format(record) + "\n"
        level = record.levelname
        color = LOG_COLORS.get(level, "#FFFFFF")

        self._textbox.configure(state="normal")
        self._textbox.insert("end", msg, level)
        self._textbox.tag_config(level, foreground=color)
        self._textbox.configure(state="disabled")
        self._textbox.see("end")


# ─────────────────────────────────────────────
# STEPPER
# ─────────────────────────────────────────────
class StepperWidget(ctk.CTkFrame):
    LABELS = ["Sincronizar", "Programming", "Settings"]

    def __init__(self, master, total_steps=3, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.total_steps = total_steps
        self.current_step = 0
        self._build()

    def _build(self):
        self.circles = []
        self.labels  = []

        for i in range(self.total_steps):
            col = i * 2

            circle = ctk.CTkLabel(
                self,
                text=str(i + 1),
                width=36, height=36,
                corner_radius=18,
                fg_color=INACTIVE_COLOR,
                text_color=TEXT_INACTIVE,
                font=ctk.CTkFont(size=14, weight="bold"),
            )
            circle.grid(row=0, column=col, padx=0, pady=(0, 4))
            self.circles.append(circle)

            label = ctk.CTkLabel(
                self,
                text=self.LABELS[i],
                font=ctk.CTkFont(size=11),
                text_color=TEXT_INACTIVE,
            )
            label.grid(row=1, column=col, padx=0)
            self.labels.append(label)

            if i < self.total_steps - 1:
                line = ctk.CTkFrame(self, width=80, height=2, fg_color=INACTIVE_COLOR)
                line.grid(row=0, column=col + 1, padx=4, sticky="ew")
                setattr(self, f"line_{i}", line)

        self.grid_columnconfigure(list(range(self.total_steps * 2 - 1)), weight=1)
        self._refresh()

    def _refresh(self):
        for i in range(self.total_steps):
            if i < self.current_step:
                self.circles[i].configure(fg_color=DONE_COLOR, text_color=TEXT_ACTIVE, text="✓")
                self.labels[i].configure(text_color=DONE_COLOR)
                if i < self.total_steps - 1:
                    getattr(self, f"line_{i}").configure(fg_color=DONE_COLOR)
            elif i == self.current_step:
                self.circles[i].configure(fg_color=ACTIVE_COLOR, text_color=TEXT_ACTIVE, text=str(i + 1))
                self.labels[i].configure(text_color=TEXT_ACTIVE)
                if i < self.total_steps - 1:
                    getattr(self, f"line_{i}").configure(fg_color=INACTIVE_COLOR)
            else:
                self.circles[i].configure(fg_color=INACTIVE_COLOR, text_color=TEXT_INACTIVE, text=str(i + 1))
                self.labels[i].configure(text_color=TEXT_INACTIVE)
                if i < self.total_steps - 1:
                    getattr(self, f"line_{i}").configure(fg_color=INACTIVE_COLOR)

    def set_step(self, step: int):
        self.current_step = step
        self._refresh()


# ─────────────────────────────────────────────
# STEP 1 — SINCRONIZAR
# ─────────────────────────────────────────────
class SyncFrame(ctk.CTkFrame):
    def __init__(self, master, app_root: ctk.CTk, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._app_root = app_root
        self._ui_handler: UILogHandler | None = None
        self._shopify_plan = None
        self._preview_revision = 0
        self._shopify_results = queue.Queue()
        self._busy = False
        self._build()
        self._setup_log_handler()

    # ── construcción de la UI ─────────────────────────────────────────
    def _build(self):
        # Layout: título + opciones arriba, log panel abajo (expandible)
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Título
        ctk.CTkLabel(
            self,
            text="Sincronización",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, pady=(10, 16))

        # Opciones de modo
        options_frame = ctk.CTkFrame(self, fg_color="#1E1E2E", corner_radius=12)
        options_frame.grid(row=1, column=0, sticky="ew", padx=40, pady=(0, 14))

        ctk.CTkLabel(
            options_frame, text=f"Shopify · {LOCATION}",
        ).pack(anchor="w", padx=20, pady=10)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=40, pady=(0, 12))
        self.sync_btn = ctk.CTkButton(
            actions,
            text="Previsualizar cambios",
            height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            corner_radius=10,
            command=self._preview_shopify,
        )
        self.sync_btn.pack(side="left", fill="x", expand=True)
        self.apply_btn = ctk.CTkButton(
            actions, text="Aplicar cambios", height=44, state="disabled",
            command=self._apply_shopify,
        )
        self.apply_btn.pack(side="left", padx=(10, 0))

        # ── Panel de logs ─────────────────────────────────────────────
        log_card = ctk.CTkFrame(self, fg_color="#1E1E2E", corner_radius=12)
        log_card.grid(row=3, column=0, sticky="nsew", padx=40, pady=(0, 12))
        log_card.grid_rowconfigure(1, weight=1)
        log_card.grid_columnconfigure(0, weight=1)

        # Header del panel de logs
        log_header = ctk.CTkFrame(log_card, fg_color="transparent")
        log_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 4))
        log_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            log_header,
            text="Registro de actividad",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#888888",
        ).grid(row=0, column=0, sticky="w")

        # Botón limpiar logs
        ctk.CTkButton(
            log_header,
            text="Limpiar",
            width=64,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#2A2A3A",
            hover_color="#3A3A4E",
            corner_radius=6,
            command=self._clear_logs,
        ).grid(row=0, column=1, sticky="e")

        # Textbox de logs (scroll integrado de CTkTextbox)
        self.log_textbox = ctk.CTkTextbox(
            log_card,
            font=ctk.CTkFont(family="Courier", size=11),
            fg_color="#0D0D1A",
            text_color="#D1D5DB",
            border_width=0,
            corner_radius=8,
            wrap="word",
            state="disabled",
        )
        self.log_textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def _setup_log_handler(self):
        """Conecta el logger del módulo ois_connector con el textbox."""
        ois_log = logging.getLogger("ois_connector")
        self._ui_handler = UILogHandler(self.log_textbox, self._app_root)
        self._ui_handler.setLevel(logging.DEBUG)
        # Evitar duplicar el handler si el frame se reconstruye
        ois_log.handlers = [
            h for h in ois_log.handlers
            if not isinstance(h, UILogHandler)
        ]
        ois_log.addHandler(self._ui_handler)

    def _clear_logs(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def _append_log(self, msg: str, color: str = "#60A5FA"):
        """Escribe un mensaje de estado directo (no via logger)."""
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", msg + "\n", "status")
        self.log_textbox.tag_config("status", foreground=color)
        self.log_textbox.configure(state="disabled")
        self.log_textbox.see("end")

    # ── persistencia ──────────────────────────────────────────────────
    def invalidate_preview(self):
        self._preview_revision += 1
        self._shopify_plan = None
        self.apply_btn.configure(state="disabled")

    def _preview_shopify(self):
        if self._busy:
            return
        self.invalidate_preview()
        self._clear_logs()
        rows = tbl_settings.all()
        cfg = rows[-1] if rows else {}
        env = read_connector_env()
        url = (env.get("OIS_PRODUCTS_URL") or cfg.get("OIS Products URL") or "").strip()
        token = (env.get("OIS_API_TOKEN") or cfg.get("Token / API Key") or "").strip()
        shop = (env.get("SHOPIFY_SHOP") or cfg.get("Shopify shop") or "w7hsns-n1").strip()
        client_id = (env.get("SHOPIFY_CLIENT_ID") or cfg.get("Shopify Client ID") or "").strip()
        secret = (env.get("SHOPIFY_CLIENT_SECRET") or "").strip()
        if not all((url, client_id, secret)) or not (token or OISClient.has_url_key(url)):
            self._append_log(
                "Completa la URL de OIS con ?key= o su token por separado, el Client ID y SHOPIFY_CLIENT_SECRET.",
                "#F87171",
            )
            return
        try:
            shopify = ShopifyClient(shop.strip(), client_id, secret)
        except ValueError as exc:
            self._append_log(str(exc), "#F87171")
            return
        ois = OISClient(url, token)

        def load_preview():
            try:
                items = ois.fetch_catalog()
            except RuntimeError:
                raise
            except Exception:
                raise RuntimeError("No se pudo consultar el catálogo de OIS.") from None
            groups = items.get("ResultItemGroups")
            group_count = len(groups) if isinstance(groups, list) else None
            return shopify, len(items["ResultItems"]), group_count, preview(shopify, items)

        revision = self._preview_revision

        def show_if_current(result):
            if revision == self._preview_revision:
                self._show_shopify_preview(result)
            else:
                self._append_log("La configuración cambió. Genera una nueva vista previa.", "#FBBF24")

        self._start_shopify(load_preview, show_if_current)

    def _show_shopify_preview(self, result):
        shopify, received, group_count, (location, rows, errors) = result
        changes = [row for row in rows if row["action"] != "unchanged"]
        self._append_log(
            f"{LOCATION} · {received} productos recibidos de OIS · "
            f"{len(changes)} con cambios · {len(rows) - len(changes)} sin cambios · "
            f"{received - len(rows)} omitidos",
        )
        if group_count is None:
            self._append_log("OIS no devolvió una lista en ResultItemGroups.")
        else:
            self._append_log(f"{group_count} grupos recibidos de OIS (ResultItemGroups).")
        for row in changes:
            variant = row["variant"]
            if variant is None:
                detail = (
                    f"Crear y publicar · Caja: {row['price']}, stock {row['available']} · "
                    f"Unidad: {row['unit_price']}, stock {row['available']}"
                )
            else:
                item = variant["inventoryItem"]
                level = item["inventoryLevel"]
                previous = level["quantities"][0]["quantity"] if level else "sin asignar"
                detail = (
                    f"Precio {variant['price']} → {row['price']} · "
                    f"stock {previous} → {row['available']}"
                )
                if row["unit_variant"]:
                    unit_level = row["unit_variant"]["inventoryItem"]["inventoryLevel"]
                    unit_stock = unit_level["quantities"][0]["quantity"] if unit_level else "sin asignar"
                    detail += f" · stock Unidad {unit_stock} → {row['available']}"
                    detail += f" · precio Unidad {row['unit_variant']['price']} → {row['unit_price']}"
                if row["publish"]:
                    detail += " · publicar en Online Store"
                if not item["tracked"]:
                    detail += " · activar seguimiento de inventario"
            self._append_log(f"{row['sku']} · {detail}")
        for error in errors:
            self._append_log(error, "#F87171")
        if changes:
            self._shopify_plan = shopify, location, changes
            self.apply_btn.configure(state="normal")

    def _apply_shopify(self):
        if self._busy or self._shopify_plan is None:
            return
        shopify, location, changes = self._shopify_plan
        if not messagebox.askyesno(
            "Sincronizar Shopify",
            f"¿Aplicar {len(changes)} cambios en Shopify? El stock se actualizará en {LOCATION}.",
            parent=self._app_root,
        ):
            return
        self.invalidate_preview()
        self._start_shopify(
            lambda: apply_preview(shopify, location, changes), self._show_shopify_result,
        )

    def _show_shopify_result(self, result):
        applied, errors = result
        self._append_log(f"{len(applied)} SKU sincronizados · {len(errors)} errores.", DONE_COLOR)
        for error in errors:
            self._append_log(error, "#F87171")

    def _start_shopify(self, operation, on_success):
        self._busy = True
        self.sync_btn.configure(state="disabled", text="Procesando…")
        self.apply_btn.configure(state="disabled")

        def worker():
            try:
                self._shopify_results.put((operation(), None))
            except Exception as exc:
                self._shopify_results.put((None, str(exc)))

        def poll():
            try:
                result, error = self._shopify_results.get_nowait()
            except queue.Empty:
                self.after(80, poll)
                return
            self._busy = False
            self.sync_btn.configure(state="normal", text="Previsualizar cambios")
            if error is not None:
                self._append_log(error, "#F87171")
            else:
                on_success(result)

        threading.Thread(target=worker, daemon=True).start()
        self.after(80, poll)

# ─────────────────────────────────────────────
# STEP 2 — PROGRAMMING
# ─────────────────────────────────────────────
class ProgrammingFrame(ctk.CTkFrame):
    DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._build()
        self._load()

    def _build(self):
        ctk.CTkLabel(
            self,
            text="Programación",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(pady=(10, 20))

        days_card = ctk.CTkFrame(self, fg_color="#1E1E2E", corner_radius=12)
        days_card.pack(fill="x", padx=40, pady=(0, 16))

        ctk.CTkLabel(
            days_card,
            text="Días de ejecución:",
            font=ctk.CTkFont(size=13),
            text_color="#AAAAAA",
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=20, pady=(14, 8))

        self.day_vars = {}
        for idx, day in enumerate(self.DAYS):
            var = ctk.BooleanVar(value=False)
            self.day_vars[day] = var
            row = 1 + idx // 4
            col = idx % 4
            ctk.CTkCheckBox(
                days_card,
                text=day,
                variable=var,
                font=ctk.CTkFont(size=12),
                checkbox_width=18,
                checkbox_height=18,
            ).grid(row=row, column=col, padx=(20, 8), pady=6, sticky="w")

        days_card.grid_columnconfigure([0, 1, 2, 3], weight=1)

        time_card = ctk.CTkFrame(self, fg_color="#1E1E2E", corner_radius=12)
        time_card.pack(fill="x", padx=40, pady=(0, 20))

        ctk.CTkLabel(
            time_card,
            text="Hora de ejecución (HH:MM):",
            font=ctk.CTkFont(size=13),
            text_color="#AAAAAA",
        ).pack(anchor="w", padx=20, pady=(14, 6))

        self.time_entry = ctk.CTkEntry(
            time_card,
            placeholder_text="08:00",
            width=120,
            height=36,
            font=ctk.CTkFont(size=14),
            justify="center",
        )
        self.time_entry.pack(anchor="w", padx=20, pady=(0, 14))

        ctk.CTkButton(
            self,
            text="Guardar Programación",
            height=44,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            command=self._on_save,
        ).pack(padx=40, fill="x")

        self.status_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#888888",
        )
        self.status_label.pack(pady=(10, 0))

    def _load(self):
        rows = tbl_programming.all()
        if rows:
            data = rows[-1]
            for day, var in self.day_vars.items():
                var.set(data.get("days", {}).get(day, False))
            saved_time = data.get("time", "")
            if saved_time:
                self.time_entry.delete(0, "end")
                self.time_entry.insert(0, saved_time)

    def _on_save(self):
        selected_days = {d: v.get() for d, v in self.day_vars.items()}
        time_val = self.time_entry.get().strip()

        active = [d for d, v in selected_days.items() if v]
        if not active:
            self.status_label.configure(text="⚠  Selecciona al menos un día", text_color="#E5A50A")
            return
        if not time_val:
            self.status_label.configure(text="⚠  Ingresa una hora", text_color="#E5A50A")
            return

        tbl_programming.truncate()
        tbl_programming.insert({"days": selected_days, "time": time_val})

        self.status_label.configure(
            text=f"✓  Guardado: {', '.join(active)} a las {time_val}",
            text_color=DONE_COLOR,
        )


# ─────────────────────────────────────────────
# STEP 3 — SETTINGS (con scroll)
# ─────────────────────────────────────────────
class SettingsFrame(ctk.CTkFrame):
    FIELDS = [
        ("OIS Products URL",        "https://ois.ejemplo.com/products", False),
        ("Token / API Key",         "••••••••••••••••",                 True),
        ("Shopify shop",            "w7hsns-n1",                        False),
        ("Shopify Client ID",       "Client ID de Shopify",             False),
    ]

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build()
        self._load()

    def _build(self):
        title = ctk.CTkLabel(
            self,
            text="Configuración",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        title.grid(row=0, column=0, pady=(10, 6), sticky="n")

        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="#13131F",
            scrollbar_button_color="#2A2A3A",
            scrollbar_button_hover_color="#3A3A4E",
        )
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.grid_rowconfigure(1, weight=1)

        card = ctk.CTkFrame(self.scroll, fg_color="#1E1E2E", corner_radius=12)
        card.pack(fill="x", padx=40, pady=(10, 12))
        card.grid_columnconfigure(0, weight=1)

        self.entries = {}
        for i, (label_text, placeholder, is_secret) in enumerate(self.FIELDS):
            ctk.CTkLabel(
                card,
                text=label_text,
                font=ctk.CTkFont(size=13),
                text_color="#AAAAAA",
            ).grid(row=i * 2, column=0, sticky="w", padx=20, pady=(16 if i == 0 else 10, 4))

            entry = ctk.CTkEntry(
                card,
                placeholder_text=placeholder,
                height=38,
                font=ctk.CTkFont(size=13),
                show="•" if is_secret else "",
            )
            entry.grid(row=i * 2 + 1, column=0, sticky="ew", padx=20, pady=(0, 2))
            self.entries[label_text] = entry

        ctk.CTkFrame(card, height=16, fg_color="transparent").grid(
            row=len(self.FIELDS) * 2, column=0
        )

        ctk.CTkButton(
            self.scroll,
            text="Guardar Configuración",
            height=44,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            command=self._on_save,
        ).pack(padx=40, fill="x", pady=(4, 6))

        ctk.CTkLabel(self.scroll, text="Puedes configurar Shopify y OIS en .env.").pack()

        self.status_label = ctk.CTkLabel(
            self.scroll,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#888888",
        )
        self.status_label.pack(pady=(2, 16))

    def _load(self):
        rows = tbl_settings.all()
        if rows:
            data = rows[-1]
            for label_text, entry in self.entries.items():
                saved_val = data.get(label_text, "")
                if saved_val:
                    entry.delete(0, "end")
                    entry.insert(0, saved_val)

    def _on_save(self):
        data = {k: e.get().strip() for k, e in self.entries.items()}
        env = read_connector_env()
        url = (env.get("OIS_PRODUCTS_URL") or data["OIS Products URL"]).strip()
        token = (env.get("OIS_API_TOKEN") or data["Token / API Key"]).strip()
        empty = []
        if not url:
            empty.append("OIS Products URL")
        elif not token and not OISClient.has_url_key(url):
            empty.append("Token / API Key")
        if empty:
            self.status_label.configure(
                text=f"⚠  Completa: {', '.join(empty)}",
                text_color="#E5A50A",
            )
            return
        tbl_settings.truncate()
        tbl_settings.insert(data)
        self.winfo_toplevel().frames[0].invalidate_preview()
        self.status_label.configure(text="✓  Configuración guardada", text_color=DONE_COLOR)


# ─────────────────────────────────────────────
# APP PRINCIPAL
# ─────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("OIS Connector")
        self.geometry("700x600")
        self.resizable(False, False)
        self.current_step = 0

        self._build_layout()
        self._show_step(0)

    def _build_layout(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ── header con stepper ──────────────────────────────────────────
        header = ctk.CTkFrame(self, corner_radius=0, fg_color="#161622", height=90)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)

        self.stepper = StepperWidget(header, total_steps=3)
        self.stepper.grid(row=0, column=0, pady=22, padx=60, sticky="ew")

        # ── área de contenido ───────────────────────────────────────────
        self.content_area = ctk.CTkFrame(self, fg_color="#13131F", corner_radius=0)
        self.content_area.grid(row=1, column=0, sticky="nsew")
        self.content_area.grid_rowconfigure(0, weight=1)
        self.content_area.grid_columnconfigure(0, weight=1)

        self.frames = [
            SyncFrame(self.content_area, app_root=self),   # ← pasa root para .after()
            ProgrammingFrame(self.content_area),
            SettingsFrame(self.content_area),
        ]
        for frame in self.frames:
            frame.grid(row=0, column=0, sticky="nsew")

        # ── barra de navegación ─────────────────────────────────────────
        nav_bar = ctk.CTkFrame(self, corner_radius=0, fg_color="#161622", height=60)
        nav_bar.grid(row=2, column=0, sticky="ew")
        nav_bar.grid_propagate(False)
        nav_bar.grid_columnconfigure(1, weight=1)

        self.btn_prev = ctk.CTkButton(
            nav_bar,
            text="← Anterior",
            width=130, height=38,
            font=ctk.CTkFont(size=13),
            fg_color="#2A2A3A",
            hover_color="#3A3A4E",
            corner_radius=8,
            command=self._prev_step,
        )
        self.btn_prev.grid(row=0, column=0, padx=(20, 0), pady=11)

        self.btn_next = ctk.CTkButton(
            nav_bar,
            text="Siguiente →",
            width=130, height=38,
            font=ctk.CTkFont(size=13),
            corner_radius=8,
            command=self._next_step,
        )
        self.btn_next.grid(row=0, column=2, padx=(0, 20), pady=11)

    def _show_step(self, step: int):
        self.current_step = step
        self.stepper.set_step(step)
        self.frames[step].tkraise()

        self.btn_prev.configure(state="normal" if step > 0 else "disabled")
        if step == 2:
            self.btn_next.configure(text="Finalizar", command=self._finish)
        else:
            self.btn_next.configure(text="Siguiente →", command=self._next_step)

    def _next_step(self):
        if self.current_step < 2:
            self._show_step(self.current_step + 1)

    def _prev_step(self):
        if self.current_step > 0:
            self._show_step(self.current_step - 1)

    def _finish(self):
        messagebox.showinfo("OIS Connector", "¡Configuración completada!\nDatos guardados en data.json")
