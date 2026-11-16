/* Interfaz gráfica del Sistema de Gestión de Facturas de Proveedores.
 *
 * JavaScript puro (sin librerías). Cada pantalla pide sus datos a la API
 * con fetch() y dibuja el resultado en la página:
 *
 *   Resumen      GET /reports/summary, GET /reports/supplier-balance
 *   Proveedores  GET/POST /suppliers, PUT/DELETE /suppliers/<id>
 *   Facturas     GET /invoices, GET /invoices/<id>,
 *                POST /invoices/<id>/payments, POST /invoices/mark-overdue
 *   Productos    GET /products (búsqueda y paginación), GET /categories
 *   Reportes     GET /reports/supplier-balance, /reports/expenses,
 *                /reports/department-expenses
 */

// ---------------------------------------------------------------- Ayudas
const $ = (selector, root = document) => root.querySelector(selector);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

const moneyFormat = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const money = (n) => moneyFormat.format(Number(n || 0));
const numberFormat = new Intl.NumberFormat("en-US");

function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

function today() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const STATUS = { Pending: "Pendiente", Paid: "Pagada", Overdue: "Vencida" };
const METHODS = { Cash: "Efectivo", "Bank transfer": "Transferencia bancaria", Card: "Tarjeta", Check: "Cheque" };
const badge = (status) => `<span class="badge ${esc(status)}">${esc(STATUS[status] || status)}</span>`;

// Mensajes claros para los errores más comunes que devuelve la API
function friendly(error) {
  const detail = error.detail || "";
  if (detail.includes("uq_supplier_tax_id")) return "Ya existe un proveedor con ese RUC.";
  if (detail.includes("fk_invoice_supplier")) return "No se puede eliminar: el proveedor tiene facturas registradas.";
  if (detail.includes("ck_payment_amount_positive")) return "El monto del pago debe ser mayor que cero.";
  return error.message;
}

async function api(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (networkError) {
    setApiStatus(false);
    throw new Error("No se pudo conectar con la API. ¿Está encendida?");
  }
  let data = null;
  try { data = await response.json(); } catch (e) { /* respuesta sin JSON */ }
  setApiStatus(true);
  if (!response.ok) {
    const error = new Error((data && data.error) || `Error ${response.status}`);
    error.detail = data && data.detail;
    error.status = response.status;
    throw error;
  }
  return { data, total: Number(response.headers.get("X-Total-Count") || 0) };
}

function setApiStatus(ok) {
  const box = $("#api-status");
  box.classList.toggle("ok", ok);
  box.classList.toggle("bad", !ok);
  $("#api-status-text").textContent = ok ? "Conectado a la API" : "Sin conexión con la API";
}

function toast(message, type = "") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function openModal(title, html, { narrow = false } = {}) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = html;
  $(".modal").classList.toggle("narrow", narrow);
  $("#modal-backdrop").hidden = false;
  const first = $("#modal-body input, #modal-body select, #modal-body button");
  if (first) first.focus();
}

function closeModal() {
  $("#modal-backdrop").hidden = true;
  $("#modal-body").innerHTML = "";
}

$("#modal-close").addEventListener("click", closeModal);
$("#modal-backdrop").addEventListener("click", (e) => { if (e.target.id === "modal-backdrop") closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

function debounce(fn, ms = 300) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

function pager(page, pages, total, label) {
  return `<div class="pager">
      <span>${numberFormat.format(total)} ${label} · página ${page} de ${pages}</span>
      <span class="btns">
        <button class="btn small" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>Anterior</button>
        <button class="btn small" data-page="${page + 1}" ${page >= pages ? "disabled" : ""}>Siguiente</button>
      </span>
    </div>`;
}

// ---------------------------------------------------------------- Resumen
async function viewResumen(content) {
  const [{ data: s }, { data: balances }] = await Promise.all([
    api("/reports/summary"), api("/reports/supplier-balance"),
  ]);
  const top = balances.filter((b) => b.pending_balance > 0)
    .sort((a, b) => b.pending_balance - a.pending_balance).slice(0, 8);
  const max = top.length ? top[0].pending_balance : 1;
  const statusRows = ["Pending", "Overdue", "Paid"].map((st) => {
    const row = s.invoices_by_status[st] || { invoice_count: 0, total_amount: 0 };
    return `<tr><td>${badge(st)}</td><td class="num">${row.invoice_count}</td>
            <td class="num">${money(row.total_amount)}</td></tr>`;
  }).join("");

  content.innerHTML = `
    <div class="stats">
      <div class="stat"><div class="stat-label">Proveedores</div>
        <div class="stat-value">${numberFormat.format(s.suppliers)}</div>
        <div class="stat-note">registrados</div></div>
      <div class="stat"><div class="stat-label">Productos en catálogo</div>
        <div class="stat-value">${numberFormat.format(s.products)}</div>
        <div class="stat-note">${s.categories} categorías</div></div>
      <div class="stat"><div class="stat-label">Facturas</div>
        <div class="stat-value">${numberFormat.format(s.invoices)}</div>
        <div class="stat-note">${money(s.total_invoiced)} facturado</div></div>
      <div class="stat"><div class="stat-label">Saldo pendiente</div>
        <div class="stat-value">${money(s.pending_balance)}</div>
        <div class="stat-note">${money(s.total_paid)} pagado en ${s.payments} pagos</div></div>
    </div>
    <div class="two-col">
      <div class="card">
        <h2>Facturas por estado</h2>
        <table>
          <thead><tr><th>Estado</th><th class="num">Facturas</th><th class="num">Monto</th></tr></thead>
          <tbody>${statusRows}</tbody>
          <tfoot><tr><td>Total</td><td class="num">${s.invoices}</td><td class="num">${money(s.total_invoiced)}</td></tr></tfoot>
        </table>
      </div>
      <div class="card">
        <h2>Proveedores con mayor saldo pendiente</h2>
        <table>
          <thead><tr><th>Proveedor</th><th></th><th class="num">Saldo</th></tr></thead>
          <tbody>${top.map((b) => `<tr>
              <td>${esc(b.company_name)}</td>
              <td style="width:30%"><div class="bar"><span style="width:${(b.pending_balance / max * 100).toFixed(1)}%"></span></div></td>
              <td class="num">${money(b.pending_balance)}</td></tr>`).join("")
            || '<tr><td colspan="3" class="empty">No hay saldos pendientes.</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
}

// ---------------------------------------------------------------- Proveedores
async function viewProveedores(content, actions) {
  actions.innerHTML = '<button class="btn primary" id="new-supplier">Nuevo proveedor</button>';
  content.innerHTML = `
    <div class="card">
      <div class="toolbar">
        <div class="field grow"><label for="supplier-q">Buscar por razón social o RUC</label>
          <input id="supplier-q" type="search" placeholder="Ej.: IMPORTADORA o 1790…"></div>
      </div>
      <div class="table-wrap" id="supplier-table"></div>
    </div>`;

  async function load() {
    const q = $("#supplier-q").value.trim();
    const { data, total } = await api("/suppliers" + (q ? `?q=${encodeURIComponent(q)}` : ""));
    $("#supplier-table").innerHTML = `
      <table>
        <thead><tr><th>Razón social</th><th>RUC / RIMPE</th><th>Teléfono</th><th>Correo</th><th></th></tr></thead>
        <tbody>${data.map((s) => `<tr>
            <td>${esc(s.company_name)}</td><td>${esc(s.tax_id)}</td>
            <td>${esc(s.phone || "—")}</td><td>${esc(s.email || "—")}</td>
            <td class="actions">
              <button class="btn small" data-edit="${s.supplier_id}">Editar</button>
              <button class="btn small danger" data-delete="${s.supplier_id}">Eliminar</button>
            </td></tr>`).join("")
          || '<tr><td colspan="5" class="empty">No se encontraron proveedores.</td></tr>'}</tbody>
      </table>
      <div class="pager"><span>${total} proveedores</span></div>`;
    $("#supplier-table").querySelectorAll("[data-edit]").forEach((b) =>
      b.addEventListener("click", () => form(data.find((s) => s.supplier_id == b.dataset.edit))));
    $("#supplier-table").querySelectorAll("[data-delete]").forEach((b) =>
      b.addEventListener("click", () => confirmDelete(data.find((s) => s.supplier_id == b.dataset.delete))));
  }

  function form(supplier) {
    const s = supplier || {};
    openModal(supplier ? "Editar proveedor" : "Nuevo proveedor", `
      <form id="supplier-form" novalidate>
        <div class="form-grid">
          <div class="field full"><label for="f-name">Razón social *</label>
            <input id="f-name" maxlength="150" value="${esc(s.company_name)}"></div>
          <div class="field"><label for="f-tax">RUC / RIMPE *</label>
            <input id="f-tax" maxlength="20" inputmode="numeric" value="${esc(s.tax_id)}"></div>
          <div class="field"><label for="f-phone">Teléfono</label>
            <input id="f-phone" maxlength="20" value="${esc(s.phone)}"></div>
          <div class="field full"><label for="f-email">Correo de contacto</label>
            <input id="f-email" type="email" maxlength="120" value="${esc(s.email)}"></div>
        </div>
        <div id="supplier-error"></div>
        <div class="form-actions">
          <button type="button" class="btn" id="cancel">Cancelar</button>
          <button type="submit" class="btn primary">Guardar</button>
        </div>
      </form>`, { narrow: true });
    $("#cancel").addEventListener("click", closeModal);
    $("#supplier-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = {
        company_name: $("#f-name").value.trim(),
        tax_id: $("#f-tax").value.trim(),
        phone: $("#f-phone").value.trim() || null,
        email: $("#f-email").value.trim() || null,
      };
      if (!body.company_name || !body.tax_id) {
        $("#supplier-error").innerHTML = '<div class="form-error">La razón social y el RUC son obligatorios.</div>';
        return;
      }
      try {
        if (supplier) await api(`/suppliers/${supplier.supplier_id}`, { method: "PUT", body });
        else await api("/suppliers", { method: "POST", body });
        closeModal();
        toast(supplier ? "Proveedor actualizado." : "Proveedor registrado.", "success");
        load();
      } catch (error) {
        $("#supplier-error").innerHTML = `<div class="form-error">${esc(friendly(error))}</div>`;
      }
    });
  }

  function confirmDelete(supplier) {
    openModal("Eliminar proveedor", `
      <p>¿Eliminar a <strong>${esc(supplier.company_name)}</strong> (RUC ${esc(supplier.tax_id)})?</p>
      <p class="hint">Solo se puede eliminar un proveedor que no tenga facturas registradas.</p>
      <div id="delete-error"></div>
      <div class="form-actions">
        <button class="btn" id="cancel">Cancelar</button>
        <button class="btn danger" id="confirm">Eliminar</button>
      </div>`, { narrow: true });
    $("#cancel").addEventListener("click", closeModal);
    $("#confirm").addEventListener("click", async () => {
      try {
        await api(`/suppliers/${supplier.supplier_id}`, { method: "DELETE" });
        closeModal();
        toast("Proveedor eliminado.", "success");
        load();
      } catch (error) {
        $("#delete-error").innerHTML = `<div class="form-error">${esc(friendly(error))}</div>`;
      }
    });
  }

  $("#new-supplier").addEventListener("click", () => form(null));
  $("#supplier-q").addEventListener("input", debounce(load));
  await load();
}

// ---------------------------------------------------------------- Facturas
async function viewFacturas(content, actions) {
  actions.innerHTML = '<button class="btn" id="mark-overdue">Marcar vencidas</button>';
  const [{ data: suppliers }, { data: methods }, { data: users }] = await Promise.all([
    api("/suppliers"), api("/payment-methods"), api("/users"),
  ]);
  content.innerHTML = `
    <div class="card">
      <div class="toolbar">
        <div class="field grow"><label for="i-supplier">Proveedor</label>
          <select id="i-supplier"><option value="">Todos</option>
            ${suppliers.map((s) => `<option value="${s.supplier_id}">${esc(s.company_name)}</option>`).join("")}
          </select></div>
        <div class="field"><label for="i-status">Estado</label>
          <select id="i-status"><option value="">Todos</option>
            ${Object.entries(STATUS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}
          </select></div>
        <div class="field"><label for="i-from">Emitida desde</label><input id="i-from" type="date"></div>
        <div class="field"><label for="i-to">Hasta</label><input id="i-to" type="date"></div>
        <button class="btn" id="i-clear">Limpiar</button>
      </div>
      <div class="table-wrap" id="invoice-table"></div>
    </div>`;

  const PER_PAGE = 12;
  let rows = [];
  let page = 1;

  function draw() {
    const pages = Math.max(1, Math.ceil(rows.length / PER_PAGE));
    page = Math.min(page, pages);
    const slice = rows.slice((page - 1) * PER_PAGE, page * PER_PAGE);
    $("#invoice-table").innerHTML = `
      <table>
        <thead><tr><th>N.º de factura</th><th>Proveedor</th><th>Emisión</th><th>Vence</th>
          <th class="num">Total</th><th>Estado</th><th></th></tr></thead>
        <tbody>${slice.map((i) => `<tr>
            <td>${esc(i.invoice_number)}</td><td>${esc(i.supplier_name)}</td>
            <td>${fmtDate(i.issue_date)}</td><td>${fmtDate(i.due_date)}</td>
            <td class="num">${money(i.total_amount)}</td><td>${badge(i.payment_status)}</td>
            <td class="actions"><button class="btn small" data-view="${i.invoice_id}">Ver</button></td></tr>`).join("")
          || '<tr><td colspan="7" class="empty">No hay facturas con esos filtros.</td></tr>'}</tbody>
      </table>
      ${pager(page, pages, rows.length, "facturas")}`;
    $("#invoice-table").querySelectorAll("[data-view]").forEach((b) =>
      b.addEventListener("click", () => detail(b.dataset.view)));
    $("#invoice-table").querySelectorAll("[data-page]").forEach((b) =>
      b.addEventListener("click", () => { page = Number(b.dataset.page); draw(); }));
  }

  async function load() {
    const params = new URLSearchParams();
    if ($("#i-supplier").value) params.set("supplier_id", $("#i-supplier").value);
    if ($("#i-status").value) params.set("status", $("#i-status").value);
    if ($("#i-from").value) params.set("date_from", $("#i-from").value);
    if ($("#i-to").value) params.set("date_to", $("#i-to").value);
    const { data } = await api("/invoices?" + params.toString());
    rows = data.slice().reverse();          // las más recientes primero
    draw();
  }

  async function detail(id) {
    const { data: inv } = await api(`/invoices/${id}`);
    openModal(`Factura ${inv.invoice_number}`, `
      <div class="kv">
        <div><span>Proveedor</span><strong>${esc(inv.supplier_name)}</strong></div>
        <div><span>Departamento</span><strong>${esc(inv.department_name)}</strong></div>
        <div><span>Estado</span>${badge(inv.payment_status)}</div>
        <div><span>Fecha de emisión</span><strong>${fmtDate(inv.issue_date)}</strong></div>
        <div><span>Fecha de vencimiento</span><strong>${fmtDate(inv.due_date)}</strong></div>
        <div><span>Total</span><strong>${money(inv.total_amount)}</strong></div>
      </div>
      <div class="section-title">Detalle</div>
      <table>
        <thead><tr><th>Producto</th><th class="num">Cant.</th><th class="num">P. unitario</th>
          <th class="num">IVA</th><th class="num">Total línea</th></tr></thead>
        <tbody>${inv.details.map((d) => `<tr><td>${esc(d.product_name)}</td>
            <td class="num">${d.quantity}</td><td class="num">${money(d.unit_price)}</td>
            <td class="num">${d.rate_percent}%</td><td class="num">${money(d.line_total)}</td></tr>`).join("")
          || '<tr><td colspan="5" class="empty">Sin líneas de detalle.</td></tr>'}</tbody>
      </table>
      <div class="totals">
        <div><span>Subtotal</span><strong>${money(inv.subtotal)}</strong></div>
        <div><span>IVA</span><strong>${money(inv.vat)}</strong></div>
        <div><span>Total</span><strong>${money(inv.total_amount)}</strong></div>
      </div>
      <div class="section-title">Pagos</div>
      <table>
        <thead><tr><th>Fecha</th><th>Método</th><th class="num">Monto</th></tr></thead>
        <tbody>${inv.payments.map((p) => `<tr><td>${fmtDate(p.payment_date)}</td>
            <td>${esc(METHODS[p.method_name] || p.method_name)}</td>
            <td class="num">${money(p.amount_paid)}</td></tr>`).join("")
          || '<tr><td colspan="3" class="empty">Todavía no hay pagos.</td></tr>'}</tbody>
      </table>
      <div class="totals">
        <div><span>Pagado</span><strong>${money(inv.total_paid)}</strong></div>
        <div><span>Saldo pendiente</span><strong>${money(inv.pending_balance)}</strong></div>
      </div>
      ${inv.pending_balance > 0 ? `
      <form class="pay-form" id="pay-form" novalidate>
        <div class="section-title" style="margin-top:0">Registrar pago</div>
        <div class="toolbar">
          <div class="field"><label for="p-amount">Monto</label>
            <input id="p-amount" type="number" step="0.01" min="0.01" value="${inv.pending_balance.toFixed(2)}"></div>
          <div class="field"><label for="p-date">Fecha</label>
            <input id="p-date" type="date" value="${today()}"></div>
          <div class="field"><label for="p-method">Método</label>
            <select id="p-method">${methods.map((m) =>
              `<option value="${m.payment_method_id}">${esc(METHODS[m.method_name] || m.method_name)}</option>`).join("")}</select></div>
          <div class="field grow"><label for="p-user">Registrado por</label>
            <select id="p-user">${users.map((u) =>
              `<option value="${u.app_user_id}">${esc(u.full_name)}</option>`).join("")}</select></div>
          <button type="submit" class="btn primary">Registrar pago</button>
        </div>
        <div id="pay-error"></div>
      </form>` : ""}`);
    const form = $("#pay-form");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const { data } = await api(`/invoices/${id}/payments`, {
            method: "POST",
            body: {
              amount_paid: $("#p-amount").value,
              payment_date: $("#p-date").value,
              payment_method_id: Number($("#p-method").value),
              app_user_id: Number($("#p-user").value),
            },
          });
          toast(data.invoice.payment_status === "Paid"
            ? "Pago registrado. La factura quedó pagada."
            : "Pago parcial registrado.", "success");
          await load();
          detail(id);
        } catch (error) {
          $("#pay-error").innerHTML = `<div class="form-error">${esc(friendly(error))}</div>`;
        }
      });
    }
  }

  ["#i-supplier", "#i-status", "#i-from", "#i-to"].forEach((sel) =>
    $(sel).addEventListener("change", () => { page = 1; load(); }));
  $("#i-clear").addEventListener("click", () => {
    ["#i-supplier", "#i-status", "#i-from", "#i-to"].forEach((sel) => { $(sel).value = ""; });
    page = 1;
    load();
  });
  $("#mark-overdue").addEventListener("click", async () => {
    const { data } = await api("/invoices/mark-overdue", { method: "POST" });
    toast(`${data.marked_overdue} facturas marcadas como vencidas (${data.total_overdue} vencidas en total).`, "success");
    load();
  });
  await load();
}

// ---------------------------------------------------------------- Productos
async function viewProductos(content) {
  const { data: categories } = await api("/categories");
  content.innerHTML = `
    <div class="card">
      <div class="toolbar">
        <div class="field grow"><label for="p-q">Buscar producto</label>
          <input id="p-q" type="search" placeholder="Ej.: FILTRO ACEITE, PASTILLA, BANDA…"></div>
        <div class="field"><label for="p-cat">Categoría</label>
          <select id="p-cat"><option value="">Todas</option>
            ${categories.map((c) => `<option value="${c.category_id}">${esc(c.category_name)}</option>`).join("")}
          </select></div>
      </div>
      <div class="table-wrap" id="product-table"></div>
    </div>`;

  const PER_PAGE = 15;
  let page = 1;

  async function load() {
    const params = new URLSearchParams({ limit: PER_PAGE, offset: (page - 1) * PER_PAGE });
    if ($("#p-q").value.trim()) params.set("q", $("#p-q").value.trim());
    if ($("#p-cat").value) params.set("category_id", $("#p-cat").value);
    const { data, total } = await api("/products?" + params.toString());
    const pages = Math.max(1, Math.ceil(total / PER_PAGE));
    $("#product-table").innerHTML = `
      <table>
        <thead><tr><th>Producto</th><th>Categoría</th><th>Unidad</th></tr></thead>
        <tbody>${data.map((p) => `<tr><td>${esc(p.product_name)}</td>
            <td>${esc(p.category_name)}</td><td>${esc(p.unit_of_measure)}</td></tr>`).join("")
          || '<tr><td colspan="3" class="empty">No se encontraron productos.</td></tr>'}</tbody>
      </table>
      ${pager(page, pages, total, "productos")}`;
    $("#product-table").querySelectorAll("[data-page]").forEach((b) =>
      b.addEventListener("click", () => { page = Number(b.dataset.page); load(); }));
  }

  $("#p-q").addEventListener("input", debounce(() => { page = 1; load(); }));
  $("#p-cat").addEventListener("change", () => { page = 1; load(); });
  await load();
}

// ---------------------------------------------------------------- Reportes
async function viewReportes(content) {
  content.innerHTML = `
    <div class="card">
      <div class="tabs">
        <button class="tab active" data-tab="saldo">Saldo por proveedor</button>
        <button class="tab" data-tab="periodo">Gasto e IVA por período</button>
        <button class="tab" data-tab="departamento">Gasto por departamento</button>
      </div>
      <div id="report"></div>
    </div>`;
  const year = new Date().getFullYear();
  const period = { from: `${year}-01-01`, to: today() };

  const periodToolbar = () => `
    <div class="toolbar">
      <div class="field"><label for="r-from">Desde</label><input id="r-from" type="date" value="${period.from}"></div>
      <div class="field"><label for="r-to">Hasta</label><input id="r-to" type="date" value="${period.to}"></div>
      <button class="btn primary" id="r-run">Generar</button>
    </div>
    <div id="r-result"></div>`;

  const tabs = {
    async saldo(box) {
      const { data } = await api("/reports/supplier-balance");
      const sum = (key) => data.reduce((total, r) => total + r[key], 0);
      box.innerHTML = `
        <p class="hint" style="margin-top:0">Total facturado menos total pagado de cada proveedor (FR-13).</p>
        <div class="table-wrap"><table>
          <thead><tr><th>Proveedor</th><th>RUC</th><th class="num">Facturado</th>
            <th class="num">Pagado</th><th class="num">Saldo pendiente</th></tr></thead>
          <tbody>${data.map((r) => `<tr><td>${esc(r.company_name)}</td><td>${esc(r.tax_id)}</td>
              <td class="num">${money(r.total_invoiced)}</td><td class="num">${money(r.total_paid)}</td>
              <td class="num">${money(r.pending_balance)}</td></tr>`).join("")}</tbody>
          <tfoot><tr><td colspan="2">Total</td><td class="num">${money(sum("total_invoiced"))}</td>
            <td class="num">${money(sum("total_paid"))}</td><td class="num">${money(sum("pending_balance"))}</td></tr></tfoot>
        </table></div>`;
    },
    async periodo(box) {
      box.innerHTML = periodToolbar();
      const run = async () => {
        period.from = $("#r-from").value; period.to = $("#r-to").value;
        const { data } = await api(`/reports/expenses?date_from=${period.from}&date_to=${period.to}`);
        $("#r-result").innerHTML = `
          <div class="stats" style="margin-bottom:0">
            <div class="stat"><div class="stat-label">Facturas del período</div><div class="stat-value">${data.invoice_count}</div></div>
            <div class="stat"><div class="stat-label">Subtotal</div><div class="stat-value">${money(data.total_subtotal)}</div></div>
            <div class="stat"><div class="stat-label">IVA</div><div class="stat-value">${money(data.total_vat)}</div></div>
            <div class="stat"><div class="stat-label">Gasto total</div><div class="stat-value">${money(data.total_expense)}</div></div>
          </div>`;
      };
      $("#r-run").addEventListener("click", () => run().catch((e) => toast(friendly(e), "error")));
      await run();
    },
    async departamento(box) {
      box.innerHTML = periodToolbar();
      const run = async () => {
        period.from = $("#r-from").value; period.to = $("#r-to").value;
        const { data } = await api(`/reports/department-expenses?date_from=${period.from}&date_to=${period.to}`);
        $("#r-result").innerHTML = `
          <div class="table-wrap"><table>
            <thead><tr><th>Departamento</th><th class="num">Facturas</th><th class="num">Subtotal</th>
              <th class="num">IVA</th><th class="num">Total</th></tr></thead>
            <tbody>${data.map((r) => `<tr><td>${esc(r.department_name)}</td><td class="num">${r.invoice_count}</td>
                <td class="num">${money(r.subtotal)}</td><td class="num">${money(r.vat)}</td>
                <td class="num">${money(r.total_amount)}</td></tr>`).join("")
              || '<tr><td colspan="5" class="empty">No hay facturas en ese período.</td></tr>'}</tbody>
          </table></div>`;
      };
      $("#r-run").addEventListener("click", () => run().catch((e) => toast(friendly(e), "error")));
      await run();
    },
  };

  async function show(name) {
    content.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    try { await tabs[name]($("#report")); } catch (error) { toast(friendly(error), "error"); }
  }
  content.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => show(t.dataset.tab)));
  await show("saldo");
}

// ---------------------------------------------------------------- Navegación
const VIEWS = {
  resumen: ["Resumen", viewResumen],
  proveedores: ["Proveedores", viewProveedores],
  facturas: ["Facturas", viewFacturas],
  productos: ["Catálogo de productos", viewProductos],
  reportes: ["Reportes", viewReportes],
};

async function route() {
  const name = location.hash.replace("#/", "") || "resumen";
  const [title, render] = VIEWS[name] || VIEWS.resumen;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === name));
  $("#view-title").textContent = title;
  $("#view-actions").innerHTML = "";
  const content = $("#content");
  content.innerHTML = '<div class="card empty">Cargando…</div>';
  try {
    await render(content, $("#view-actions"));
  } catch (error) {
    content.innerHTML = `<div class="card"><div class="form-error" style="margin:0">${esc(friendly(error))}</div></div>`;
  }
}

window.addEventListener("hashchange", route);
route();
