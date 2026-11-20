const $ = (id) => document.getElementById(id);
let planId = null;
let changed = 0;
let polling = false;
const labels = {create_and_publish: "Crear y publicar", update: "Actualizar", publish: "Publicar", unchanged: "Sin cambios"};
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": document.querySelector('meta[name="csrf"]').content},
    body: JSON.stringify(data)
  });
  if (response.status === 401) { window.location.assign("/login"); throw new Error("Inicia sesión para continuar."); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "No se pudo completar la operación.");
  return result;
}
function busy(active) {
  $("preview").disabled = active;
  $("apply").disabled = active || !planId || !changed;
  for (const element of $("config").elements) element.disabled = active;
}
function errors(messages) {
  $("errors").replaceChildren(...messages.map(message => {
    const p = document.createElement("p"); p.textContent = message; return p;
  }));
}
function cell(row, value) { const td = document.createElement("td"); td.textContent = value; row.append(td); return td; }
function priceCell(row, before, after) {
  const td = cell(row, "");
  if (before != null && String(before) !== String(after)) {
    const span = document.createElement("span"); span.className = "old"; span.textContent = before; td.append(span);
  }
  td.append(document.createTextNode(after ?? "—"));
}
function showPreview(result) {
  planId = result.plan_id; changed = result.rows.filter(row => row.action !== "unchanged").length;
  $("received").textContent = result.received; $("groups").textContent = result.groups;
  $("changed").textContent = changed; $("other").textContent = `${result.unchanged} / ${result.omitted}`;
  $("rows").replaceChildren();
  for (const item of result.rows) {
    const row = document.createElement("tr");
    const title = cell(row, item.title || item.sku); const sku = document.createElement("small"); sku.textContent = item.sku; title.append(sku);
    for (const image of item.images || []) {
      const img = document.createElement("img");
      img.src = "/api/images/" + image.id; img.alt = item.title || item.sku;
      img.className = "product-image"; img.loading = "lazy"; title.append(img);
    }
    const action = cell(row, ""); const badge = document.createElement("span"); badge.className = "badge";
    badge.textContent = labels[item.action] || item.action; action.append(badge);
    if (item.publish && item.action === "update") action.append(document.createTextNode(" · Online Store"));
    priceCell(row, item.variant?.price, item.price); priceCell(row, item.unit_variant?.price, item.unit_price);
    const quantities = item.variant?.inventoryItem?.inventoryLevel?.quantities;
    priceCell(row, quantities?.[0]?.quantity, item.available);
    const unitQuantities = item.unit_variant?.inventoryItem?.inventoryLevel?.quantities;
    priceCell(row, unitQuantities?.[0]?.quantity, item.unit_variant || !item.variant ? item.available : "—");
    $("rows").append(row);
  }
  if (!result.rows.length) { const row = document.createElement("tr"); const td = cell(row, "OIS no devolvió productos utilizables."); td.colSpan = 6; $("rows").append(row); }
  errors(result.errors); $("status").textContent = "Vista previa lista. Revisa los cambios antes de aplicarlos.";
}
async function poll() {
  if (polling) return;
  polling = true;
  busy(true);
  try {
    while (true) {
      const job = await api("/api/job");
      if (job.status !== "running") {
        if (job.status === "error") throw new Error(job.error);
        if (job.status === "done") {
          if (job.operation === "preview") showPreview(job.result);
          else {
            planId = null;
            errors(job.result.errors);
            $("status").textContent = `${job.result.applied} productos sincronizados · ${job.result.images_uploaded || 0} imágenes enviadas · ${job.result.errors.length} errores. Genera otra vista previa para actualizar el estado.`;
          }
        }
        break;
      }
      $("status").textContent = ["preview", "images-preview"].includes(job.operation) ? "Consultando OIS y Shopify…" : "Aplicando cambios en Shopify…";
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  } catch (error) { planId = null; errors([error.message]); $("status").textContent = "La operación requiere atención."; }
  finally { polling = false; busy(false); }
}
async function start(operation, data = {}) {
  busy(true); errors([]);
  try { await api("/api/" + operation, data); await poll(); }
  catch (error) { errors([error.message]); busy(false); }
}
$("preview").onclick = () => { planId = null; start("preview"); };
$("apply").onclick = () => {
  $("confirm-text").textContent = `Se aplicarán cambios a ${changed} productos. Se enviarán también sus imágenes. El inventario se sincronizará en Shop location y los productos indicados se publicarán en Online Store.`;
  $("confirm").showModal();
};
$("cancel").onclick = () => $("confirm").close();
$("confirm-apply").onclick = () => { $("confirm").close(); const id = planId; planId = null; start("apply", {plan_id: id}); };
$("config").onsubmit = async (event) => {
  event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); busy(true);
  try {
    const result = await api("/api/config", data); planId = null;
    $("saved").textContent = result.overridden.length ? "Guardado. Variables de terminal con prioridad: " + result.overridden.join(", ") : "Configuración guardada.";
    for (const key of ["SHOPIFY_CLIENT_SECRET", "OIS_PRODUCTS_URL", "OIS_API_TOKEN", "OIS_IMAGES_URL"]) $("config").elements[key].value = "";
    await loadConfig();
  } catch(error) { errors([error.message]); }
  finally { busy(false); }
};
async function loadConfig() {
  const result = await api("/api/config");
  for (const [key,value] of Object.entries(result.values)) $("config").elements[key].value = value;
  for (const [key,configured] of Object.entries(result.configured)) {
    if (!Object.hasOwn(result.values, key)) $("config").elements[key].placeholder = configured ? "Configurado · dejar vacío para conservar" : "Pendiente de configurar";
  }
}
(async () => { try { await loadConfig(); await poll(); } catch(error) { errors([error.message]); } })();
