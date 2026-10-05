"use strict";

const POLL_MS = 3000;
const GLOBAL_LABELS = {
  hold_seconds: "LOW hold time (sec)",
  reminder_hours: "Owner reminder (h)",
  expiry_days: "List expiry (days)",
  offline_minutes: "Offline after (min)",
  refill_reminder_days: "Not-refilled reminder (days)",
  drift_throttle_minutes: "Drift log throttle (min)",
  event_retention_days: "Keep heartbeats (days)",
};

const $ = (sel) => document.querySelector(sel);
const state = {
  view: "straps", items: [], straps: [], list: null, orders: [], settings: null, me: null,
  filter: "all", editing: new Set(), historyFor: null,
};
const pollers = [];  // run after each view refresh

// --- icons (Material Symbols Rounded, same set as the design) ----------------------
const ICON_NAMES = {
  sensors: "sensors", grid: "kitchen", cart: "shopping_basket", plus: "add_circle", history: "history",
  settings: "settings", logout: "logout", wifi: "wifi", target: "tune", trash: "delete", edit: "edit",
  message: "chat", send: "send", alert: "warning", check: "check_circle", clock: "schedule",
  down: "arrow_downward", up: "arrow_upward", box: "inventory_2", chevron: "expand_less", activity: "monitor_heart",
};

function icon(name) {
  return `<span class="ic material-symbols-rounded" aria-hidden="true">${ICON_NAMES[name] || ""}</span>`;
}

function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    el.outerHTML = icon(el.dataset.icon);
  });
}

// --- helpers -----------------------------------------------------------------------
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 2600);
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401 && path !== "/api/login") {
    showLogin(true);
    throw new Error("login required");
  }
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : res.statusText);
  }
  return data;
}

function ago(iso) {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function when(iso) {
  return iso ? new Date(iso).toLocaleString() : "";
}

function signal(rssi) {
  if (rssi == null) return "Wi-Fi –";
  return `Wi-Fi ${rssi >= -60 ? "Strong" : rssi >= -70 ? "Good" : rssi >= -80 ? "Weak" : "Poor"}`;
}

function renderLabelOptions() {
  // Suggestions for every free-text contents-label field.
  $("#label-options").innerHTML = state.items.map((i) => `<option value="${esc(i.name)}"></option>`).join("");
}

function editing(section) {
  // Don't re-render a view while the user is typing in it.
  return section.contains(document.activeElement) && document.activeElement !== document.body;
}

function readPrice(input) {
  const v = input.value.trim();
  return v === "" ? null : Number(v);
}

// --- login -------------------------------------------------------------------------
function showLogin(show) {
  $("#login").classList.toggle("hidden", !show);
  if (show) $("#login-password").focus();
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("POST", "/api/login", { password: $("#login-password").value });
    $("#login-password").value = "";
    $("#login-error").textContent = "";
    showLogin(false);
    await boot();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

$("#logout").addEventListener("click", async () => {
  await api("POST", "/api/logout");
  state.me = null;
  showLogin(true);
});

// --- chrome: top bar capsule, sidebar node card, list badge -----------------------------
function counts(straps) {
  const c = { total: straps.length, OK: 0, LOW: 0, OFFLINE: 0, UNKNOWN: 0 };
  straps.forEach((s) => { c[s.status] = (c[s.status] || 0) + 1; });
  c.online = c.OK + c.LOW;
  return c;
}

function renderChrome() {
  const c = counts(state.straps);
  const capsule = $("#live-capsule");
  const healthy = c.total === 0 || c.OFFLINE + c.UNKNOWN === 0;
  capsule.classList.toggle("warn", !healthy);
  $("#live-text").textContent = c.total ? `Live • ${c.online}/${c.total} straps online` : "Live • no straps yet";
  $("#node-online").textContent = `${c.online}/${c.total} online`;
  $("#node-low").textContent = c.LOW ? `${c.LOW} LOW` : "";
  $("#node-dot").style.background = healthy ? "var(--ok)" : "var(--warn)";
  const mode = state.me?.messaging_mode || "";
  $("#mode-chip").textContent = mode.replace("twilio_", "twilio ");
  $("#node-sub").textContent = `Messaging: ${mode.replace("_", " ")}`;
  const n = state.list?.rows.length || 0;
  const badge = $("#nav-list-badge");
  badge.textContent = `${n} ITEM${n === 1 ? "" : "S"}`;
  badge.classList.toggle("hidden", n === 0);
  if (state.settings) {
    const g = state.settings.global;
    const hold = state.settings.dev_hold_seconds ? `${state.settings.dev_hold_seconds}s (dev)` : `${g.hold_seconds}s`;
    $("#side-timings").textContent = `LOW hold ${hold} · Offline after ${g.offline_minutes} min · Threshold ₹${state.settings.owner.list_threshold_inr}`;
  }
}

async function pollChrome() {
  if (state.view !== "straps" && state.view !== "list") {
    const [straps, list] = await Promise.all([api("GET", "/api/straps"), api("GET", "/api/list")]);
    state.straps = straps;
    state.list = list;
  }
  renderChrome();
}
pollers.push(pollChrome);

// --- views ---------------------------------------------------------------------------
const views = {};

const STATUS_TEXT = { OK: "Stock OK", LOW: "LOW", OFFLINE: "Offline", UNKNOWN: "Waiting" };

function metricsHTML() {
  const c = counts(state.straps);
  const list = state.list || { rows: [], total_inr: 0, threshold_inr: 0, missing_prices: [] };
  const open = state.orders.filter((o) => o.status === "awaiting_owner").length;
  const unsent = state.orders.filter((o) => o.unsent).length;
  const last = state.orders[0];
  const pct = list.threshold_inr ? Math.min(100, Math.round((list.total_inr / list.threshold_inr) * 100)) : 0;
  return `
    <div class="metric">
      <div class="top"><span class="label">Active straps</span>${icon("sensors")}</div>
      <div class="value"><span class="num">${c.online}</span><span class="sub">/ ${c.total} online</span></div>
      <div class="foot"><span class="t-ok">● ${c.OK} reporting OK</span><span>${c.OFFLINE + c.UNKNOWN} offline / waiting</span></div>
    </div>
    <div class="metric">
      <div class="top"><span class="label">Stock health</span>${icon("activity")}</div>
      <div class="value"><span class="num">${c.LOW}</span><span class="label ${c.LOW ? "t-low" : "t-ok"}">${c.LOW ? "Jars LOW" : "All jars stocked"}</span></div>
      <div class="foot"><div class="split3"><span class="b-ok">${c.OK} OK</span><span class="b-low">${c.LOW} LOW</span><span class="b-warn">${c.OFFLINE + c.UNKNOWN} Off</span></div></div>
    </div>
    <div class="metric">
      <div class="top"><span class="label">Shopping list</span>${icon("cart")}</div>
      <div class="value"><span class="num">₹${list.total_inr}</span><span class="sub">/ ₹${list.threshold_inr}</span></div>
      <div class="foot"><span>${list.rows.length} item${list.rows.length === 1 ? "" : "s"} · ${pct}% of threshold</span>
        ${list.missing_prices.length ? `<span class="t-warn">${list.missing_prices.length} need price</span>` : ""}</div>
    </div>
    <div class="metric">
      <div class="top"><span class="label">WhatsApp orders</span>${icon("send")}</div>
      <div class="value"><span class="num">${open}</span><span class="sub">awaiting reply</span></div>
      <div class="foot"><span>${last ? `Last: #${last.id} ${esc(ORDER_LABELS[last.status] || last.status)}` : "No orders yet"}</span>
        ${unsent ? `<span class="t-low">${unsent} unsent</span>` : ""}</div>
    </div>`;
}

function bannerFor(s, listed) {
  if (listed) return { cls: "b-warn", ic: "cart", text: `On shopping list${listed.line_total_inr != null ? ` · ₹${listed.line_total_inr}` : ""}`, right: ago(listed.added_at) };
  if (s.status === "LOW") return { cls: "b-low", ic: "clock", text: "LOW · joins list after hold", right: `since ${ago(s.state_since)}` };
  if (s.status === "OFFLINE") return { cls: "b-warn", ic: "alert", text: "No report: check power / Wi-Fi", right: ago(s.last_seen) };
  if (s.status === "UNKNOWN") return { cls: "", ic: "clock", text: "Waiting for first report", right: "" };
  return { cls: "b-ok", ic: "check", text: "Stock OK", right: s.state_since ? `since ${ago(s.state_since)}` : "" };
}

function jarCardHTML(s, listedByStrap) {
  // The drawing only shows the state (full or low); no measured level is shown.
  const fill = s.status === "OK" ? 85 : s.status === "LOW" ? 15 : 0;
  const listed = listedByStrap.get(s.device_id);
  const b = bannerFor(s, listed);
  const price = s.item ? (s.item.price_inr == null ? `<a class="warn-chip" href="#settings">${icon("alert")}enter price</a>` : `₹${s.item.price_inr}${s.item.pack_size ? ` / ${esc(s.item.pack_size)}` : ""}`) : "";
  const open = state.editing.has(s.device_id);
  return `
  <article class="jar-card st-${esc(s.status)}" data-id="${esc(s.device_id)}">
    <div class="jar-head">
      <div style="min-width:0">
        <div class="row"><span class="jar-id">#${esc(s.device_id)}</span>
          <span class="status-chip st-chip-${esc(s.status)}">${esc(STATUS_TEXT[s.status] || s.status)}</span></div>
        <h3 class="card-title">${esc(s.display_name || s.device_id)}</h3>
        <p class="muted mono" style="margin:0">Contents: ${s.item ? esc(s.item.name) : "no label"} ${price ? `• ${price}` : ""}</p>
      </div>
      <div class="jar ${esc(s.status)}"><div class="fill" style="height:${fill}%"></div><div class="base"></div><div class="lid"></div></div>
    </div>
    <div class="readouts">
      <div class="wide"><span>Last report: ${esc(ago(s.last_seen))}</span><span>${s.pending_command ? `<b class="t-warn">${esc(s.pending_command)} queued</b>` : "No pending command"}</span></div>
    </div>
    <div class="banner ${b.cls}"><span>${icon(b.ic)}${esc(b.text)}</span><span class="muted">${esc(b.right)}</span></div>
    <div class="telemetry">
      <span>${icon("wifi")}${esc(signal(s.rssi))}</span>
    </div>
    ${open ? `
    <div class="edit-panel">
      <label>Jar name</label>
      <input class="rename" value="${esc(s.display_name || "")}" maxlength="80">
      <div class="edit-grid">
        <div><label>Contents label</label>
          <input class="label-input" list="label-options" value="${esc(s.item?.name || "")}" maxlength="80" placeholder="e.g. Rice"></div>
        <div><label>Price (₹)</label>
          <input class="price-input" type="number" min="0" value="${s.item?.price_inr ?? ""}" placeholder="60"></div>
      </div>
      <div class="row" style="margin-top:10px">
        <button class="btn sm primary save-edit">${icon("check")}Save</button>
        <button class="btn sm cancel-edit">Cancel</button>
      </div>
    </div>` : ""}
    <footer class="jar-actions">
      <button class="btn sm show-history" title="History" aria-label="History">${icon("history")}</button>
      <button class="btn sm toggle-edit">${icon("edit")}Edit</button>
      <button class="btn sm danger delete-strap" title="Delete strap" aria-label="Delete strap">${icon("trash")}</button>
      <span class="spacer"></span>
      <button class="btn sm primary recal">${icon("target")}Recalibrate</button>
    </footer>
  </article>`;
}

function streamHTML(events) {
  if (!events.length) return `<div class="empty">No events yet. State changes and recalibrations appear here live.</div>`;
  return events.map((e) => {
    const ic = e.kind === "low" ? "down" : e.kind === "ok" ? "up" : "target";
    const cls = e.kind === "low" ? "low" : e.kind === "ok" ? "ok" : "";
    const color = e.kind === "low" ? "t-low" : e.kind === "ok" ? "t-ok" : "";
    return `
    <div class="log ${cls}">
      <div class="head"><span class="${color}">${icon(ic)}${esc(e.strap_name)}: ${esc(e.text)}</span><span class="muted">${esc(ago(e.ts))}</span></div>
    </div>`;
  }).join("");
}

views.straps = {
  async load() {
    const [straps, list, orders, events] = await Promise.all([
      api("GET", "/api/straps"), api("GET", "/api/list"), api("GET", "/api/orders?limit=10"),
      api("GET", "/api/events/recent?limit=20"),
    ]);
    Object.assign(state, { straps, list, orders });
    // Forget edit panels for straps that no longer exist.
    state.editing.forEach((id) => { if (!straps.some((s) => s.device_id === id)) state.editing.delete(id); });

    $("#metrics").innerHTML = metricsHTML();
    $("#stream").innerHTML = streamHTML(events);

    const grid = $("#strap-grid");
    if (editing(grid) || state.editing.size) return;  // keep edit panels and typed text intact
    const shown = straps.filter((s) => state.filter === "all"
      || (state.filter === "OFFLINE" ? (s.status === "OFFLINE" || s.status === "UNKNOWN") : s.status === state.filter));
    $("#strap-count").textContent = `Showing ${shown.length} of ${straps.length}`;
    if (!straps.length) {
      grid.innerHTML = `<div class="empty panel" style="grid-column:1/-1">No straps yet. <a href="#claim">Add one</a>.</div>`;
      return;
    }
    if (!shown.length) {
      grid.innerHTML = `<div class="empty panel" style="grid-column:1/-1">No straps match this filter.</div>`;
      return;
    }
    const listedByStrap = new Map(list.rows.filter((r) => r.strap_id).map((r) => [r.strap_id, r]));
    grid.innerHTML = shown.map((s) => jarCardHTML(s, listedByStrap)).join("");
  },
};

$("#strap-filter").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-filter]");
  if (!btn) return;
  state.filter = btn.dataset.filter;
  document.querySelectorAll("#strap-filter button").forEach((b) => b.classList.toggle("on", b === btn));
  views.straps.load().catch((err) => toast(err.message));
});

$("#strap-grid").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  const card = e.target.closest(".jar-card");
  if (!btn || !card) return;
  const id = card.dataset.id;
  const name = card.querySelector(".card-title").textContent;
  try {
    if (btn.classList.contains("toggle-edit") || btn.classList.contains("cancel-edit")) {
      if (state.editing.has(id)) state.editing.delete(id); else state.editing.add(id);
      btn.blur();
      // Re-render just this card.
      const s = state.straps.find((x) => x.device_id === id);
      const listedByStrap = new Map((state.list?.rows || []).filter((r) => r.strap_id).map((r) => [r.strap_id, r]));
      card.outerHTML = jarCardHTML(s, listedByStrap);
      return;
    }
    if (btn.classList.contains("save-edit")) {
      const display = card.querySelector(".rename").value.trim();
      const label = card.querySelector(".label-input").value.trim();
      const price = readPrice(card.querySelector(".price-input"));
      if (!display) throw new Error("Jar name cannot be empty");
      if (label && price === null && !confirm(`Save "${label}" without a price? It won't count towards the ₹ threshold until you add one.`)) return;
      await api("PATCH", `/api/straps/${id}`, label ? { display_name: display, label, price_inr: price } : { display_name: display, label });
      state.editing.delete(id);
      toast(!label ? "Saved (no contents label)" : price === null ? "Saved (no price yet)" : `Saved: ${label} ₹${price}`);
      state.items = await api("GET", "/api/items");
      renderLabelOptions();
    } else if (btn.classList.contains("delete-strap")) {
      if (!confirm(`Delete "${name}"? Its history is removed. If the strap is still switched on it shows a new claim code on its serial log, so you can add it again.`)) return;
      await api("DELETE", `/api/straps/${id}`);
      state.editing.delete(id);
      toast(`${name} deleted`);
    } else if (btn.classList.contains("recal")) {
      if (!confirm("Recalibrate this strap? Only do this with the jar EMPTY. The current reading becomes the new baseline.")) return;
      await api("POST", `/api/straps/${id}/recalibrate`);
      toast("Recalibration queued; the strap picks it up on its next report");
    } else if (btn.classList.contains("show-history")) {
      state.historyFor = id;
      location.hash = "#history";
      return;
    } else {
      return;
    }
    document.activeElement.blur();
    await views.straps.load();
    renderChrome();
  } catch (err) {
    toast(err.message);
  }
});

// Typing a known label fills in its catalog price (still editable).
document.addEventListener("input", (e) => {
  if (!e.target.matches(".label-input, #claim-item")) return;
  const item = state.items.find((i) => i.name.toLowerCase() === e.target.value.trim().toLowerCase());
  const price = e.target.id === "claim-item" ? $("#claim-price") : e.target.closest(".edit-panel")?.querySelector(".price-input");
  if (item && price) price.value = item.price_inr ?? "";
});

views.claim = {
  async load() {
    state.items = await api("GET", "/api/items");
    renderLabelOptions();
  },
};

$("#claim-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("POST", "/api/straps/claim", {
      claim_code: $("#claim-code").value.trim().toUpperCase(),
      display_name: $("#claim-name").value.trim(),
      label: $("#claim-item").value.trim(),
      price_inr: $("#claim-item").value.trim() ? readPrice($("#claim-price")) : null,
    });
    state.items = await api("GET", "/api/items");
    renderLabelOptions();
    e.target.reset();
    toast("Strap added");
    location.hash = "#straps";
  } catch (err) {
    toast(err.message);
  }
});

views.history = {
  async load() {
    state.straps = await api("GET", "/api/straps");
    const select = $("#history-strap");
    const current = state.historyFor || select.value || state.straps[0]?.device_id || "";
    state.historyFor = null;
    select.innerHTML = state.straps.map((s) =>
      `<option value="${esc(s.device_id)}" ${s.device_id === current ? "selected" : ""}>${esc(s.display_name || s.device_id)}</option>`).join("");
    if (!current) {
      $("#history-list").innerHTML = `<li class="empty">No straps yet.</li>`;
      return;
    }
    const data = await api("GET", `/api/history/${encodeURIComponent(current)}`);
    $("#history-list").innerHTML = data.entries.length ? data.entries.map((e) => `
      <li><span class="dot ${esc(e.kind)}"></span><span class="when">${esc(when(e.ts))}</span><span>${esc(e.text)}</span></li>`).join("")
      : `<li class="empty">Nothing logged yet.</li>`;
  },
};

$("#history-strap").addEventListener("change", () => views.history.load().catch((e) => toast(e.message)));

views.settings = {
  async load() {
    if (editing($("#view-settings"))) return;
    const [s, items] = await Promise.all([api("GET", "/api/settings"), api("GET", "/api/items")]);
    state.items = items;
    state.settings = s;
    renderLabelOptions();
    $("#s-owner-name").value = s.owner.name;
    $("#s-owner-wa").value = s.owner.whatsapp_number;
    $("#s-threshold").value = s.owner.list_threshold_inr;
    $("#s-shop-name").value = s.shop?.name ?? "";
    $("#s-shop-wa").value = s.shop?.whatsapp_number ?? "";
    $("#s-shop-opt").value = String(s.shop?.opted_in ?? false);
    $("#s-global").innerHTML = Object.entries(GLOBAL_LABELS).map(([key, label]) => `
      <div><label for="g-${key}">${esc(label)}</label><input id="g-${key}" data-key="${key}" type="number" min="0" value="${esc(s.global[key])}"></div>`).join("");
    $("#s-mode").textContent = `Messaging mode: ${s.messaging_mode}${s.dev_hold_seconds ? ` · dev hold ${s.dev_hold_seconds}s` : ""}`;
    $("#catalog-body").innerHTML = items.map((i) => `
      <tr data-id="${i.id}">
        <td><input class="c-name" value="${esc(i.name)}"></td>
        <td><input class="c-unit" value="${esc(i.unit)}"></td>
        <td><input class="c-pack" value="${esc(i.pack_size)}"></td>
        <td><input class="c-price" type="number" min="0" value="${i.price_inr ?? ""}" placeholder="enter price"></td>
        <td class="nowrap"><button class="btn sm c-save">Save</button><button class="btn sm danger c-del">Delete</button></td>
      </tr>`).join("");
  },
};

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const global = {};
  document.querySelectorAll("#s-global input").forEach((el) => { global[el.dataset.key] = Number(el.value); });
  try {
    await api("PUT", "/api/settings", {
      owner: {
        name: $("#s-owner-name").value.trim() || null,
        whatsapp_number: $("#s-owner-wa").value.trim(),
        list_threshold_inr: Number($("#s-threshold").value),
      },
      shop: {
        name: $("#s-shop-name").value.trim() || null,
        whatsapp_number: $("#s-shop-wa").value.trim(),
        opted_in: $("#s-shop-opt").value === "true",
      },
      global,
    });
    document.activeElement.blur();
    toast("Settings saved");
    await views.settings.load();
    renderChrome();
  } catch (err) {
    toast(err.message);
  }
});

function readItemRow(row, prefix) {
  const price = row.querySelector(`.${prefix}-price`).value;
  return {
    name: row.querySelector(`.${prefix}-name`).value.trim(),
    unit: row.querySelector(`.${prefix}-unit`).value.trim(),
    pack_size: row.querySelector(`.${prefix}-pack`).value.trim(),
    price_inr: price === "" ? null : Number(price),
  };
}

$("#catalog-body").addEventListener("click", async (e) => {
  const row = e.target.closest("tr");
  const btn = e.target.closest("button");
  if (!row || !btn) return;
  try {
    if (btn.classList.contains("c-save")) {
      await api("PUT", `/api/items/${row.dataset.id}`, readItemRow(row, "c"));
      toast("Item saved");
    } else if (btn.classList.contains("c-del")) {
      if (!confirm("Delete this item from the catalog?")) return;
      await api("DELETE", `/api/items/${row.dataset.id}`);
      toast("Item deleted");
    } else {
      return;
    }
    document.activeElement.blur();
    await views.settings.load();
  } catch (err) {
    toast(err.message);
  }
});

$("#new-item-add").addEventListener("click", async (e) => {
  e.preventDefault();
  const price = $("#new-item-price").value;
  try {
    await api("POST", "/api/items", {
      name: $("#new-item-name").value.trim(),
      unit: $("#new-item-unit").value.trim(),
      pack_size: $("#new-item-pack").value.trim(),
      price_inr: price === "" ? null : Number(price),
    });
    ["#new-item-name", "#new-item-unit", "#new-item-pack", "#new-item-price"].forEach((s) => { $(s).value = ""; });
    document.activeElement.blur();
    toast("Item added");
    await views.settings.load();
  } catch (err) {
    toast(err.message);
  }
});

const ORDER_LABELS = {
  awaiting_owner: "Waiting for owner",
  confirmed: "Sending to shop",
  sent_to_shop: "Sent to shop",
  delivery_confirmed: "Shop confirmed",
  shop_declined: "Shop can't deliver",
  cancelled: "Not now",
  expired: "Expired",
  send_failed: "Unsent",
};

views.list = {
  async load() {
    const [list, orders, straps] = await Promise.all([
      api("GET", "/api/list"), api("GET", "/api/orders"), api("GET", "/api/straps"),
    ]);
    Object.assign(state, { list, orders, straps });
    const pct = list.threshold_inr ? Math.min(100, (list.total_inr / list.threshold_inr) * 100) : 0;
    $("#list-total").textContent = `₹${list.total_inr}`;
    $("#list-threshold").textContent = `/ ₹${list.threshold_inr} threshold · ${Math.round(pct)}%`;
    $("#list-bar").firstElementChild.style.width = `${pct}%`;
    $("#list-bar").classList.toggle("done", pct >= 100);
    $("#list-send").disabled = !list.rows.length || list.missing_prices.length > 0;
    $("#list-missing").innerHTML = list.missing_prices.map((m) =>
      `<a class="warn-chip" href="#settings">${icon("alert")}Enter price: ${esc(m.name)}</a>`).join("");
    $("#list-body").innerHTML = list.rows.length ? list.rows.map((r) => `
      <tr data-id="${r.id}">
        <td><b>${esc(r.item_name)}</b></td>
        <td class="mono muted">${esc(r.strap_name || "manual")}</td>
        <td class="mono">×${r.qty}</td>
        <td class="mono">${r.needs_price ? `<span class="warn-chip">no price</span>` : `₹${r.line_total_inr}`}</td>
        <td class="mono muted">${esc(ago(r.added_at))}</td>
        <td class="nowrap" style="text-align:right"><button class="btn sm danger list-remove">${icon("trash")}Remove</button></td>
      </tr>`).join("") : `<tr><td colspan="6" class="empty">Nothing on the list. Jars that stay LOW are added automatically.</td></tr>`;

    if (!editing($("#list-add-select").parentElement)) {
      const listed = new Set(list.rows.map((r) => r.strap_id));
      $("#list-add-select").innerHTML =
        `<optgroup label="From a jar">${straps.filter((s) => s.item && !listed.has(s.device_id)).map((s) =>
          `<option value="strap:${esc(s.device_id)}">${esc(s.display_name || s.device_id)} (${esc(s.item.name)})</option>`).join("")}</optgroup>` +
        `<optgroup label="Catalog item">${state.items.map((i) =>
          `<option value="item:${i.id}">${esc(i.name)}</option>`).join("")}</optgroup>`;
    }

    $("#orders").innerHTML = orders.length ? orders.map((o) => `
      <div class="order" data-id="${o.id}">
        <div class="row">
          <span class="jar-id">#${o.id}</span>
          <b class="mono">₹${o.total_inr}</b>
          <span class="status-chip os-${esc(o.status)}">${esc(ORDER_LABELS[o.status] || o.status)}</span>
          <span class="spacer"></span>
          <span class="muted mono">${esc(when(o.created_at))}</span>
        </div>
        <div class="muted mono">${esc(o.items.map((i) => `${i.name} ×${i.qty}`).join(", ") || "—")}${o.shop ? ` → ${esc(o.shop)}` : ""}</div>
        ${o.last_error ? `<div class="mono t-low" style="font-size:11px">${esc(o.last_error)}</div>` : ""}
        ${o.unsent || o.status === "awaiting_owner" ? `<div class="row">
          ${o.unsent ? `<button class="btn sm primary order-retry">${icon("send")}Retry send</button>` : ""}
          <button class="btn sm order-cancel">Cancel order</button></div>` : ""}
      </div>`).join("") : `<div class="empty">No orders yet.</div>`;
  },
};

$("#list-body").addEventListener("click", async (e) => {
  const btn = e.target.closest(".list-remove");
  if (!btn) return;
  try {
    await api("DELETE", `/api/list/items/${btn.closest("tr").dataset.id}`);
    await views.list.load();
    renderChrome();
  } catch (err) {
    toast(err.message);
  }
});

$("#list-add").addEventListener("click", async () => {
  const [kind, id] = $("#list-add-select").value.split(":");
  if (!id) return;
  try {
    await api("POST", "/api/list/items", kind === "strap" ? { strap_id: id } : { item_id: Number(id) });
    document.activeElement.blur();
    await views.list.load();
    renderChrome();
  } catch (err) {
    toast(err.message);
  }
});

$("#list-send").addEventListener("click", async () => {
  if (!confirm("Send the list to your WhatsApp now?")) return;
  try {
    const order = await api("POST", "/api/list/send");
    toast(order.status === "send_failed" ? `Not sent: ${order.last_error}` : "List sent to your WhatsApp");
    await views.list.load();
    renderChrome();
  } catch (err) {
    toast(err.message);
  }
});

$("#orders").addEventListener("click", async (e) => {
  const order = e.target.closest(".order");
  const btn = e.target.closest("button");
  if (!order || !btn) return;
  try {
    if (btn.classList.contains("order-retry")) {
      const o = await api("POST", `/api/orders/${order.dataset.id}/retry`);
      toast(o.status === "send_failed" ? `Still unsent: ${o.last_error}` : "Sent");
    } else if (btn.classList.contains("order-cancel")) {
      if (!confirm("Cancel this order? Its items go back on the list.")) return;
      await api("POST", `/api/orders/${order.dataset.id}/cancel`);
    } else {
      return;
    }
    await views.list.load();
  } catch (err) {
    toast(err.message);
  }
});

// --- simulator panel -------------------------------------------------------------------
const ROLE_LABELS = { owner_list: "To owner", shop_order: "To shop", text: "Text" };

async function pollSimulator() {
  if (state.me?.messaging_mode !== "simulator" || !$("#sim").open) return;
  if (!editing($("#sim"))) {
    const current = $("#sim-strap").value;
    $("#sim-strap").innerHTML = state.straps.map((s) =>
      `<option value="${esc(s.device_id)}" ${s.device_id === current ? "selected" : ""}>${esc(s.display_name || s.device_id)}</option>`).join("");
  }
  const { messages } = await api("GET", "/api/sim/messages");
  $("#sim-inbox").innerHTML = messages.length ? messages.map((m) => `
    <div class="bubble ${esc(m.role)}">
      <div class="meta">${esc(ROLE_LABELS[m.role] || m.role)} ${esc(m.to)} · ${esc(new Date(m.ts).toLocaleTimeString())}</div>
      <div class="msg">${esc(m.text)}</div>
      ${m.buttons.length ? `<div class="row">${m.buttons.map((b) =>
        `<button class="btn sm ${b.payload.endsWith(":yes") ? "primary" : ""}" data-order="${m.order_id}" data-action="${b.payload.endsWith(":yes") ? "order" : "not_now"}">${esc(b.title)}</button>`).join("")}</div>` : ""}
    </div>`).join("") : `<div class="empty">No messages yet.</div>`;
}
pollers.push(pollSimulator);

$("#sim").addEventListener("toggle", () => {
  if ($("#sim").open) api("GET", "/api/straps").then((s) => { state.straps = s; return pollSimulator(); }).catch(() => {});
});

$("#sim-inbox").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-order]");
  if (!btn) return;
  try {
    const { outcome } = await api("POST", "/api/sim/reply", { order_id: Number(btn.dataset.order), action: btn.dataset.action });
    toast(`Owner tapped ${btn.textContent}: ${outcome.replace(/_/g, " ")}`);
    await refresh();
  } catch (err) {
    toast(err.message);
  }
});

document.querySelectorAll("[data-sim-state]").forEach((btn) => btn.addEventListener("click", async () => {
  const stateValue = btn.dataset.simState;
  try {
    await api("POST", "/api/sim/event", {
      device_id: $("#sim-strap").value,
      type: "state_change",
      payload: { state: stateValue, gap: stateValue === "LOW" ? 8 : 35 },
    });
    toast(`Strap reported ${stateValue}`);
    await refresh();
  } catch (err) {
    toast(err.message);
  }
}));

$("#sim-ff").addEventListener("click", async () => {
  try {
    const { added } = await api("POST", "/api/sim/fast-forward");
    toast(`${added} jar(s) added to the list`);
    await refresh();
  } catch (err) {
    toast(err.message);
  }
});

$("#sim-clear").addEventListener("click", async () => {
  await api("DELETE", "/api/sim/messages");
  await pollSimulator();
});

// --- routing and polling -----------------------------------------------------------------
function route() {
  const view = (location.hash || "#straps").slice(1);
  state.view = views[view] ? view : "straps";
  document.querySelectorAll("main > section[data-view]").forEach((s) => {
    s.classList.toggle("hidden", s.dataset.view !== state.view);
  });
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === state.view));
  refresh();
}

async function refresh() {
  if (!state.me?.authenticated) return;
  try {
    await views[state.view].load();
    for (const poll of pollers) await poll();
  } catch (err) {
    if (err.message !== "login required") console.warn(err);
  }
}

async function boot() {
  state.me = await api("GET", "/api/me");
  if (!state.me.authenticated) {
    showLogin(true);
    return;
  }
  document.body.dataset.mode = state.me.messaging_mode;
  $("#sim").classList.toggle("hidden", state.me.messaging_mode !== "simulator");
  const [items, settings] = await Promise.all([api("GET", "/api/items"), api("GET", "/api/settings")]);
  state.items = items;
  state.settings = settings;
  renderLabelOptions();
  route();
}

hydrateIcons();
window.addEventListener("hashchange", route);
setInterval(() => {
  if (document.visibilityState === "visible" && state.view !== "settings" && state.me?.authenticated) refresh();
}, POLL_MS);
boot();
