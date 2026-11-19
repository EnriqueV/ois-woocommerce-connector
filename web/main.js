const APP_VERSION = "2026-05-01.1";
const STEP_LABELS = ["Sincronizar", "Programming", "Settings"];
const DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const SETTINGS_ACCESS_KEY = "Ois2026#";

let currentStep = 0;
let settingsUnlocked = false;

const views = [
  document.getElementById("view-sync"),
  document.getElementById("view-programming"),
  document.getElementById("view-settings"),
];

const stepperEl = document.getElementById("stepper");
const btnPrev = document.getElementById("btn-prev");
const btnNext = document.getElementById("btn-next");
const btnTestConnection = document.getElementById("btn-test-connection");
const btnSync = document.getElementById("btn-sync");
const btnCreateCategories = document.getElementById("btn-create-categories");
const btnClearLogs = document.getElementById("btn-clear-logs");
const logPanel = document.getElementById("log-panel");

const btnSaveProgramming = document.getElementById("btn-save-programming");
const programTime = document.getElementById("program-time");
const programmingStatus = document.getElementById("programming-status");
const daysGrid = document.getElementById("days-grid");

const btnSaveSettings = document.getElementById("btn-save-settings");
const settingsFields = document.getElementById("settings-fields");
const settingsStatus = document.getElementById("settings-status");
const settingsCard = document.getElementById("settings-card");
const settingsLockPanel = document.getElementById("settings-lock-panel");
const settingsAccessKey = document.getElementById("settings-access-key");
const btnUnlockSettings = document.getElementById("btn-unlock-settings");
const settingsLockStatus = document.getElementById("settings-lock-status");

const SETTINGS_FIELDS = [
  { key: "OIS Products URL", placeholder: "https://ois.ejemplo.com/products", secret: false },
  { key: "Image URL", placeholder: "https://www.oisimobile.com/OISWC/inventory.svc/Images", secret: false },
  { key: "DigitalOcean Spaces Endpoint", placeholder: "https://bucket.nyc3.digitaloceanspaces.com", secret: false },
  { key: "DigitalOcean Spaces Access Key", placeholder: "DOxxxxxxxxxxxxxxxxxx", secret: false },
  { key: "DigitalOcean Spaces Secret Key", placeholder: "••••••••••••••••", secret: true },
  { key: "DigitalOcean Spaces Directory", placeholder: "file_img", secret: false },
  { key: "Local Images Directory", placeholder: "/wp-content/uploads/2026/04", secret: false },
  { key: "Public Images Base URL", placeholder: "https://www.latinproductsdistribution.com/wp-content/uploads/2026/04", secret: false },
  { key: "Token / API Key", placeholder: "••••••••••••••••", secret: true },
  { key: "WordPress URL", placeholder: "https://mitienda.com", secret: false },
  { key: "WordPress Username", placeholder: "admin", secret: false },
  { key: "WordPress Application Password", placeholder: "xxxx xxxx xxxx xxxx xxxx xxxx", secret: true },
  { key: "WordPress Client Key", placeholder: "ck_xxxxxxxxxxxx", secret: false },
  { key: "WordPress Client Secret", placeholder: "cs_xxxxxxxxxxxx", secret: true },
];

init().catch((error) => {
  addLog("error", `Error de inicialización: ${error.message || error}`);
});

async function init() {
  renderStepper();
  renderProgrammingDays();
  renderSettingsFields();
  wireEvents();
  await loadStateFromApi();
  showStep(0);
  addLog("debug", `UI cargado. version=${APP_VERSION}`);
}

function wireEvents() {
  btnPrev.addEventListener("click", () => {
    if (currentStep > 0) showStep(currentStep - 1);
  });
  btnNext.addEventListener("click", () => {
    if (currentStep < 2) showStep(currentStep + 1);
    else alert("Configuración completada. Datos guardados en config.json.");
  });

  btnSaveProgramming.addEventListener("click", saveProgramming);
  btnSaveSettings.addEventListener("click", saveSettings);
  btnClearLogs.addEventListener("click", () => (logPanel.textContent = ""));
  btnTestConnection.addEventListener("click", onTestConnection);
  btnSync.addEventListener("click", onSync);
  btnCreateCategories.addEventListener("click", onCreateCategories);
  btnUnlockSettings.addEventListener("click", unlockSettings);
  settingsAccessKey.addEventListener("keydown", (event) => {
    if (event.key === "Enter") unlockSettings();
  });
}

function renderStepper() {
  stepperEl.innerHTML = "";
  for (let i = 0; i < STEP_LABELS.length; i += 1) {
    const circle = document.createElement("div");
    circle.id = `step-circle-${i}`;
    circle.className =
      "mx-auto flex h-9 w-9 items-center justify-center rounded-full text-sm font-bold";
    circle.textContent = String(i + 1);

    const label = document.createElement("p");
    label.id = `step-label-${i}`;
    label.className = "mt-1 text-center text-xs";
    label.textContent = STEP_LABELS[i];

    const item = document.createElement("div");
    item.append(circle, label);
    stepperEl.appendChild(item);

    if (i < STEP_LABELS.length - 1) {
      const line = document.createElement("div");
      line.id = `step-line-${i}`;
      line.className = "h-0.5 w-full rounded";
      stepperEl.appendChild(line);
    }
  }
}

function refreshStepper() {
  for (let i = 0; i < STEP_LABELS.length; i += 1) {
    const circle = document.getElementById(`step-circle-${i}`);
    const label = document.getElementById(`step-label-${i}`);
    if (i < currentStep) {
      circle.className =
        "mx-auto flex h-9 w-9 items-center justify-center rounded-full bg-emerald-600 text-sm font-bold text-white";
      circle.textContent = "✓";
      label.className = "mt-1 text-center text-xs text-emerald-500";
    } else if (i === currentStep) {
      circle.className =
        "mx-auto flex h-9 w-9 items-center justify-center rounded-full bg-sky-600 text-sm font-bold text-white";
      circle.textContent = String(i + 1);
      label.className = "mt-1 text-center text-xs text-white";
    } else {
      circle.className =
        "mx-auto flex h-9 w-9 items-center justify-center rounded-full bg-slate-700 text-sm font-bold text-slate-300";
      circle.textContent = String(i + 1);
      label.className = "mt-1 text-center text-xs text-slate-400";
    }
    if (i < STEP_LABELS.length - 1) {
      const line = document.getElementById(`step-line-${i}`);
      line.className = `h-0.5 w-full rounded ${i < currentStep ? "bg-emerald-600" : "bg-slate-700"}`;
    }
  }
}

function showStep(step) {
  currentStep = step;
  views.forEach((view, i) => {
    view.classList.toggle("hidden", i !== step);
  });
  btnPrev.disabled = step === 0;
  btnNext.textContent = step === 2 ? "Finalizar" : "Siguiente →";
  if (step === 2) {
    refreshSettingsLock();
    if (!settingsUnlocked) {
      settingsAccessKey.focus();
    }
  }
  refreshStepper();
}

function renderProgrammingDays() {
  daysGrid.innerHTML = "";
  DAYS.forEach((day) => {
    const label = document.createElement("label");
    label.className = "flex cursor-pointer items-center gap-2";
    label.innerHTML = `
      <input class="h-4 w-4 day-checkbox" type="checkbox" data-day="${day}" />
      <span>${day}</span>
    `;
    daysGrid.appendChild(label);
  });
}

function saveProgramming() {
  const days = {};
  DAYS.forEach((day) => {
    const checkbox = document.querySelector(`.day-checkbox[data-day="${day}"]`);
    days[day] = Boolean(checkbox?.checked);
  });
  const selected = Object.keys(days).filter((d) => days[d]);
  if (!selected.length) {
    setStatus(programmingStatus, "Selecciona al menos un día.", false);
    return;
  }
  if (!programTime.value) {
    setStatus(programmingStatus, "Ingresa una hora.", false);
    return;
  }
  apiPost("save_programming", {
    programming: { days, time: programTime.value },
  })
    .then(() => {
      setStatus(programmingStatus, `Guardado: ${selected.join(", ")} a las ${programTime.value}`, true);
    })
    .catch((error) => {
      setStatus(programmingStatus, `Error al guardar: ${error.message || error}`, false);
    });
}

function renderSettingsFields() {
  settingsFields.innerHTML = "";
  SETTINGS_FIELDS.forEach((f) => {
    const wrapper = document.createElement("div");
    wrapper.innerHTML = `
      <label class="mb-1 block text-sm text-slate-400">${f.key}</label>
      <input
        id="setting-${cssSafeId(f.key)}"
        type="${f.secret ? "password" : "text"}"
        placeholder="${f.placeholder}"
        disabled
        class="setting-input w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 outline-none ring-sky-500 focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60"
      />
    `;
    settingsFields.appendChild(wrapper);
  });
  refreshSettingsLock();
}

function saveSettings() {
  if (!settingsUnlocked) {
    setStatus(settingsStatus, "Ingresa la clave para modificar Settings.", false);
    refreshSettingsLock();
    return;
  }

  const data = {};
  SETTINGS_FIELDS.forEach((f) => {
    const input = document.getElementById(`setting-${cssSafeId(f.key)}`);
    data[f.key] = input?.value?.trim() ?? "";
  });
  const empty = Object.keys(data).filter((k) => !data[k]);
  if (empty.length) {
    setStatus(settingsStatus, `Completa: ${empty.join(", ")}`, false);
    return;
  }
  apiPost("save_settings", { settings: data })
    .then(() => {
      setStatus(settingsStatus, "Configuración guardada.", true);
    })
    .catch((error) => {
      setStatus(settingsStatus, `Error al guardar: ${error.message || error}`, false);
    });
}

function unlockSettings() {
  const typedKey = settingsAccessKey.value.trim();
  if (typedKey === SETTINGS_ACCESS_KEY) {
    settingsUnlocked = true;
    settingsAccessKey.value = "";
    settingsLockStatus.textContent = "";
    refreshSettingsLock();
    setStatus(settingsStatus, "Settings desbloqueado.", true);
    return;
  }

  settingsLockStatus.textContent = "Clave incorrecta.";
  settingsLockStatus.className = "mt-3 min-h-5 text-sm text-amber-400";
  settingsAccessKey.select();
}

function refreshSettingsLock() {
  const locked = !settingsUnlocked;
  document.querySelectorAll(".setting-input").forEach((input) => {
    input.disabled = locked;
  });
  btnSaveSettings.disabled = locked;
  btnSaveSettings.classList.toggle("opacity-60", locked);
  btnSaveSettings.classList.toggle("cursor-not-allowed", locked);
  settingsCard.classList.toggle("opacity-60", locked);
  settingsLockPanel.classList.toggle("hidden", !locked);
}

async function onSync() {
  clearLogs();
  const mode = "new";

  btnSync.disabled = true;
  btnSync.textContent = "Sincronizando...";

  try {
    await apiPost("save_sync_mode", { mode });
    addLog("info", "Iniciando sincronización...");

    const response = await apiPost("sync", { mode });
    if (response.message) {
      addLog("info", response.message);
    }

    if (response.summary) {
      const {
        ok,
        created,
        updated,
        skipped,
        errors,
        received,
        mapped,
        limit,
        products_with_images,
        images_assigned,
        target_store,
        retried_without_images,
        category_groups_found,
        products_with_categories,
        sync_tag_name,
        products_with_tags,
      } = response.summary;
      if (target_store) {
        addLog("info", `Tienda destino: ${target_store}`);
      }
      addLog("info", `OIS devolvió ${received} item(s). Límite=${limit}. Mapeados=${mapped}.`);
      addLog("info", `Imágenes asignadas: ${images_assigned || 0}. Productos con imagen: ${products_with_images || 0}.`);
      addLog("info", `Categorías enlazadas: ${category_groups_found || 0} grupo(s). Productos con categoría: ${products_with_categories || 0}.`);
      addLog("info", `Tag aplicado: ${sync_tag_name || "sincronizado by ois connector"} (${products_with_tags || 0} producto(s)).`);
      if (retried_without_images) {
        addLog("warning", `Productos reintentados sin imágenes: ${retried_without_images}`);
      }
      let summary = `${ok} producto(s) procesado(s): ${created || 0} creado(s), ${updated || 0} actualizado(s), ${skipped || 0} sin cambios`;
      if (errors) summary += ` | ${errors} con error`;
      addLog("success", summary);
    }

    if (Array.isArray(response.retried_without_images) && response.retried_without_images.length > 0) {
      response.retried_without_images.forEach((product) => {
        const name = product.name || "Sin nombre";
        const reason = product.reason || "Error de imagen";
        const id = product.id ?? "";
        addLog("warning", `Recuperado sin imágenes: ${name} | id=${id} | motivo=${reason}`);
      });
    }

    if (Array.isArray(response.created_products) && response.created_products.length > 0) {
      response.created_products.forEach((product) => {
        const id = product.id ?? "";
        const name = product.name || "Sin nombre";
        const status = product.status || "sin status";
        const permalink = product.permalink ? ` | ${product.permalink}` : "";
        addLog("debug", `Creado en WooCommerce ID=${id} | ${name} | status=${status}${permalink}`);
      });
    }

    if (Array.isArray(response.updated_products) && response.updated_products.length > 0) {
      response.updated_products.forEach((product) => {
        const id = product.id ?? "";
        const name = product.name || "Sin nombre";
        const status = product.status || "sin status";
        const permalink = product.permalink ? ` | ${product.permalink}` : "";
        addLog("debug", `Actualizado en WooCommerce ID=${id} | ${name} | status=${status}${permalink}`);
      });
    }

    if (Array.isArray(response.skipped_products) && response.skipped_products.length > 0) {
      response.skipped_products.forEach((product) => {
        const id = product.id ?? "";
        const name = product.name || "Sin nombre";
        const reason = product.reason || "sin cambios";
        addLog("debug", `Sin cambios ID=${id} | ${name} | ${reason}`);
      });
    }

    if (Array.isArray(response.error_details) && response.error_details.length > 0) {
      response.error_details.forEach((errorItem) => {
        const name = errorItem.name || "Sin nombre";
        const message = errorItem.message || "Error desconocido";
        addLog("warning", `Error producto ${name}: ${message}`);
      });
    }
  } catch (error) {
    addLog("error", String(error.message || error));
  } finally {
    btnSync.disabled = false;
    btnSync.textContent = "Sincronizar cambios";
  }
}

async function onTestConnection() {
  clearLogs();
  btnTestConnection.disabled = true;
  btnTestConnection.textContent = "Probando...";

  try {
    addLog("info", "Probando conexión con OIS...");
    const response = await apiGet("test_connection");

    if (response.message) {
      addLog(response.summary?.has_results ? "success" : "warning", response.message);
    }

    if (response.summary?.target_store) {
      addLog("info", `Tienda destino configurada: ${response.summary.target_store}`);
    }

    addLog("info", `Productos recibidos desde OIS: ${response.summary?.received ?? 0}`);

    if (Array.isArray(response.sample_products) && response.sample_products.length > 0) {
      response.sample_products.forEach((product) => {
        const itemId = product.cItemId ?? "";
        const name = product.name || "Sin nombre";
        const sku = product.sku || "sin sku";
        addLog("debug", `Muestra OIS cItemId=${itemId} | ${name} | sku=${sku}`);
      });
    }
  } catch (error) {
    addLog("error", String(error.message || error));
  } finally {
    btnTestConnection.disabled = false;
    btnTestConnection.textContent = "Probar conexión";
  }
}

async function onCreateCategories() {
  clearLogs();
  btnCreateCategories.disabled = true;
  btnCreateCategories.textContent = "Creando categorías...";

  try {
    addLog("warning", "Borrando categorías existentes de WooCommerce...");
    addLog("info", "Leyendo ResultItemGroups desde OIS...");

    const response = await apiPost("create_categories", {});
    if (response.message) {
      addLog("info", response.message);
    }

    const summary = response.summary || {};
    if (summary.target_store) {
      addLog("info", `Tienda destino: ${summary.target_store}`);
    }
    addLog("info", `OIS devolvió ${summary.received ?? 0} grupo(s). Categorías válidas=${summary.requested ?? 0}.`);
    addLog("success", `${summary.deleted ?? 0} categoría(s) borrada(s). ${summary.created ?? 0} categoría(s) creada(s).`);

    if (Array.isArray(response.created_categories) && response.created_categories.length > 0) {
      response.created_categories.forEach((category) => {
        const id = category.id ?? "";
        const name = category.name || "Sin nombre";
        addLog("debug", `Categoría creada ID=${id} | ${name}`);
      });
    }

    if (Array.isArray(response.delete_errors) && response.delete_errors.length > 0) {
      response.delete_errors.forEach((category) => {
        const id = category.id ?? "";
        const name = category.name || "Sin nombre";
        const message = category.message || "Error desconocido";
        addLog("warning", `No se pudo borrar categoría ID=${id} | ${name}: ${message}`);
      });
    }

    if (Array.isArray(response.create_errors) && response.create_errors.length > 0) {
      response.create_errors.forEach((category) => {
        const name = category.name || "Sin nombre";
        const message = category.message || "Error desconocido";
        addLog("warning", `No se pudo crear categoría ${name}: ${message}`);
      });
    }
  } catch (error) {
    addLog("error", String(error.message || error));
  } finally {
    btnCreateCategories.disabled = false;
    btnCreateCategories.textContent = "Crear categorías";
  }
}

function setStatus(el, text, ok) {
  el.textContent = text;
  el.className = `text-sm ${ok ? "text-emerald-500" : "text-amber-400"}`;
}

function addLog(level, message) {
  const now = new Date().toLocaleTimeString("es-MX", { hour12: false });
  const colorByLevel = {
    debug: "#94a3b8",
    info: "#60a5fa",
    warning: "#fbbf24",
    error: "#f87171",
    success: "#34d399",
  };
  const line = document.createElement("div");
  line.style.color = colorByLevel[level] || "#e2e8f0";
  line.textContent = `${now}  ${level.toUpperCase().padEnd(7, " ")}  ${message}`;
  logPanel.appendChild(line);
  logPanel.scrollTop = logPanel.scrollHeight;
}

function clearLogs() {
  logPanel.textContent = "";
}

function cssSafeId(input) {
  return input.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

async function loadStateFromApi() {
  const res = await apiGet("get_state");
  const state = res.data || {};

  const settings = state.settings || {};
  SETTINGS_FIELDS.forEach((f) => {
    const input = document.getElementById(`setting-${cssSafeId(f.key)}`);
    if (input && settings[f.key]) input.value = settings[f.key];
  });

  const programming = state.programming || {};
  DAYS.forEach((day) => {
    const checkbox = document.querySelector(`.day-checkbox[data-day="${day}"]`);
    if (checkbox) checkbox.checked = Boolean(programming.days?.[day]);
  });
  if (programming.time) programTime.value = programming.time;

}

async function apiGet(action) {
  const response = await fetch(`./api.php?action=${encodeURIComponent(action)}`, {
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Cache-Control": "no-cache",
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Error API (${response.status})`);
  }
  return data;
}

async function apiPost(action, payload) {
  const response = await fetch(`./api.php?action=${encodeURIComponent(action)}`, {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "Cache-Control": "no-cache",
    },
    body: JSON.stringify(payload || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Error API (${response.status})`);
  }
  return data;
}
