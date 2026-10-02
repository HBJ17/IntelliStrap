"use strict";

const POLL_MS = 3000;
const GLOBAL_LABELS = {
  hold_minutes: "LOW hold time (min)",
  reminder_hours: "Owner reminder (h)",
  expiry_days: "List expiry (days)",
  offline_minutes: "Offline after (min)",
  refill_reminder_days: "Not-refilled reminder (days)",
  drift_throttle_minutes: "Drift log throttle (min)",
  event_retention_days: "Keep heartbeats (days)",
  fill_gap_full: "Gap shown as full",
};

const $ = (sel) => document.querySelector(sel);
const state = { view: "straps", items: [], straps: [], me: null };
const pollers = [];  // run after each view refresh

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
  if (s < 60) return `${Math.round(s)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function when(iso) {
  return iso ? new Date(iso).toLocaleString() : "";
}

function signal(rssi) {
  if (rssi == null) return "–";
  const q = rssi >= -60 ? "strong" : rssi >= -70 ? "good" : rssi >= -80 ? "weak" : "poor";
  return `${rssi} dBm (${q})`;
}

function renderLabelOptions() {
  // Suggestions for every free-text contents-label field.
  $("#label-options").innerHTML = state.items.map((i) => `<option value="${esc(i.name)}"></option>`).join("");
}

function editing(section) {
  // Don't re-render a view while the user is typing in it.
  return section.contains(document.activeElement) && document.activeElement !== document.body;
}

// --- login -------------------------------------------------------------------

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
  showLogin(true);
});

// --- views -------------------------------------------------------------------

const views = {};

views.straps = {
  async load() {
    state.straps = await api("GET", "/api/straps");
    const section = $("#view-straps");
    if (editing(section)) return;
    const grid = $("#strap-grid");
    if (!state.straps.length) {
      grid.innerHTML = `<div class="empty">No straps yet. <a href="#claim">Add one</a>.</div>`;
      return;
    }
    grid.innerHTML = state.straps.map((s) => {
      const fill = s.status === "OFFLINE" || s.status === "UNKNOWN" ? 0 : (s.fill_pct ?? 0);
      const label = s.status === "OFFLINE" ? "Offline" : s.status === "UNKNOWN" ? "Waiting" : s.status;
      return `
      <div class="card" data-id="${esc(s.device_id)}">
        <div class="card-head">
          <div>
            <div class="card-title">${esc(s.display_name || s.device_id)}</div>
            <div class="muted">${esc(s.item ? s.item.name : "No contents label")}${s.item && s.item.price_inr == null ? ` · <a class="pill warn" href="#settings">enter price</a>` : ""}</div>
          </div>
          <span class="pill ${esc(s.status)}">${esc(label)}</span>
        </div>
        <div class="bar ${esc(s.status)}"><div style="width:${fill}%"></div></div>
        <div class="muted">Last seen ${esc(ago(s.last_seen))} · Wi-Fi ${esc(signal(s.rssi))}</div>
        <div class="muted">${esc(s.device_id)}${s.pending_command ? ` · <span class="pill warn">${esc(s.pending_command)} queued</span>` : ""}</div>
        <div class="row" style="margin-top:10px">
          <input class="rename" value="${esc(s.display_name || "")}" maxlength="80" aria-label="Jar name" style="flex:1">
          <button class="small save-name">Rename</button>
        </div>
        <div class="row">
          <input class="label-input" list="label-options" value="${esc(s.item?.name || "")}" maxlength="80"
                 placeholder="Contents, e.g. Rice" aria-label="Contents label" style="flex:1">
          <input class="price-input price" type="number" min="0" value="${s.item?.price_inr ?? ""}"
                 placeholder="₹ price" aria-label="Price in rupees">
          <button class="small save-label">Save</button>
        </div>
        <div class="row">
          <button class="small danger delete-strap">Delete</button>
          <span class="spacer"></span>
          <button class="small recal">Recalibrate</button>
        </div>
      </div>`;
    }).join("");
  },
};

$("#strap-grid").addEventListener("click", async (e) => {
  const card = e.target.closest(".card");
  if (!card) return;
  const id = card.dataset.id;
  try {
    if (e.target.classList.contains("save-label")) {
      const label = card.querySelector(".label-input").value.trim();
      const price = readPrice(card.querySelector(".price-input"));
      if (label && price === null && !confirm(`Save "${label}" without a price? It won't count towards the ₹ threshold until you add one.`)) return;
      await api("PATCH", `/api/straps/${id}`, label ? { label, price_inr: price } : { label });
      e.target.blur();
      toast(!label ? "Label cleared" : price === null ? "Label saved (no price yet)" : `Label saved: ${label} ₹${price}`);
      state.items = await api("GET", "/api/items");
      renderLabelOptions();
    } else if (e.target.classList.contains("delete-strap")) {
      const name = card.querySelector(".card-title").textContent;
      if (!confirm(`Delete "${name}"? Its history is removed. If the strap is still switched on it shows a new claim code on its serial log, so you can add it again.`)) return;
      await api("DELETE", `/api/straps/${id}`);
      toast(`${name} deleted`);
    } else if (e.target.classList.contains("save-name")) {
      await api("PATCH", `/api/straps/${id}`, { display_name: card.querySelector(".rename").value });
      e.target.blur();
      toast("Renamed");
    } else if (e.target.classList.contains("recal")) {
      if (!confirm("Recalibrate this strap? Only do this with the jar EMPTY — the current reading becomes the new baseline.")) return;
      await api("POST", `/api/straps/${id}/recalibrate`);
      toast("Recalibration queued; the strap picks it up on its next report");
    } else {
      return;
    }
    await views.straps.load();
  } catch (err) {
    toast(err.message);
  }
});

function readPrice(input) {
  const v = input.value.trim();
  return v === "" ? null : Number(v);
}

// Typing a known label fills in its catalog price (still editable).
document.addEventListener("input", (e) => {
  if (!e.target.matches(".label-input, #claim-item")) return;
  const item = state.items.find((i) => i.name.toLowerCase() === e.target.value.trim().toLowerCase());
  const price = e.target.id === "claim-item" ? $("#claim-price") : e.target.parentElement.querySelector(".price-input");
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
    const current = select.value || state.straps[0]?.device_id || "";
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
    renderLabelOptions();
    $("#s-owner-name").value = s.owner.name;
    $("#s-owner-wa").value = s.owner.whatsapp_number;
    $("#s-threshold").value = s.owner.list_threshold_inr;
    $("#s-shop-name").value = s.shop?.name ?? "";
    $("#s-shop-wa").value = s.shop?.whatsapp_number ?? "";
    $("#s-shop-opt").value = String(s.shop?.opted_in ?? false);
    $("#s-global").innerHTML = Object.entries(GLOBAL_LABELS).map(([key, label]) => `
      <div><label for="g-${key}">${esc(label)}</label><input id="g-${key}" data-key="${key}" type="number" min="0" value="${esc(s.global[key])}"></div>`).join("");
    $("#s-mode").textContent = `Messaging: ${s.messaging_mode}${s.dev_hold_seconds ? ` · dev hold ${s.dev_hold_seconds}s` : ""}`;
    $("#catalog-body").innerHTML = items.map((i) => `
      <tr data-id="${i.id}">
        <td><input class="c-name" value="${esc(i.name)}"></td>
        <td><input class="c-unit" value="${esc(i.unit)}"></td>
        <td><input class="c-pack" value="${esc(i.pack_size)}"></td>
        <td><input class="c-price" type="number" min="0" value="${i.price_inr ?? ""}" placeholder="enter price"></td>
        <td class="row" style="flex-wrap:nowrap"><button class="small c-save">Save</button><button class="small danger c-del">Delete</button></td>
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
  if (!row) return;
  try {
    if (e.target.classList.contains("c-save")) {
      await api("PUT", `/api/items/${row.dataset.id}`, readItemRow(row, "c"));
      toast("Item saved");
    } else if (e.target.classList.contains("c-del")) {
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
  cancelled: "Not now",
  expired: "Expired",
  send_failed: "Unsent",
};

views.list = {
  async load() {
    const [list, orders, straps] = await Promise.all([
      api("GET", "/api/list"), api("GET", "/api/orders"), api("GET", "/api/straps"),
    ]);
    state.straps = straps;
    $("#list-total").textContent = `₹${list.total_inr}`;
    $("#list-threshold").textContent = `of ₹${list.threshold_inr} — the list is sent automatically at the threshold`;
    $("#list-bar").firstElementChild.style.width = `${Math.min(100, (list.total_inr / list.threshold_inr) * 100)}%`;
    $("#list-send").disabled = !list.rows.length || list.missing_prices.length > 0;
    $("#list-missing").innerHTML = list.missing_prices.map((m) =>
      `<a class="pill warn" href="#settings">Enter price: ${esc(m.name)}</a>`).join("");
    $("#list-body").innerHTML = list.rows.length ? list.rows.map((r) => `
      <tr data-id="${r.id}">
        <td>${esc(r.item_name)}</td>
        <td class="muted">${esc(r.strap_name || "manual")}</td>
        <td>${r.qty}</td>
        <td>${r.needs_price ? `<span class="pill warn">no price</span>` : `₹${r.line_total_inr}`}</td>
        <td class="muted">${esc(ago(r.added_at))}</td>
        <td><button class="small danger list-remove">Remove</button></td>
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
          <strong>#${o.id} · ₹${o.total_inr}</strong>
          <span class="pill status-${esc(o.status)}">${esc(ORDER_LABELS[o.status] || o.status)}</span>
          <span class="spacer"></span>
          <span class="muted">${esc(when(o.created_at))}</span>
        </div>
        <div class="muted">${esc(o.items.map((i) => `${i.name} ×${i.qty}`).join(", ") || "—")}${o.shop ? ` → ${esc(o.shop)}` : ""}</div>
        ${o.last_error ? `<div class="muted" style="color:var(--low)">${esc(o.last_error)}</div>` : ""}
        ${o.unsent || o.status === "awaiting_owner" ? `<div class="row">
          ${o.unsent ? `<button class="small primary order-retry">Retry send</button>` : ""}
          <button class="small order-cancel">Cancel order</button></div>` : ""}
      </div>`).join("") : `<div class="empty">No orders yet.</div>`;
  },
};

$("#list-body").addEventListener("click", async (e) => {
  if (!e.target.classList.contains("list-remove")) return;
  try {
    await api("DELETE", `/api/list/items/${e.target.closest("tr").dataset.id}`);
    await views.list.load();
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
  } catch (err) {
    toast(err.message);
  }
});

$("#orders").addEventListener("click", async (e) => {
  const order = e.target.closest(".order");
  if (!order) return;
  try {
    if (e.target.classList.contains("order-retry")) {
      const o = await api("POST", `/api/orders/${order.dataset.id}/retry`);
      toast(o.status === "send_failed" ? `Still unsent: ${o.last_error}` : "Sent");
    } else if (e.target.classList.contains("order-cancel")) {
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

// --- simulator panel -------------------------------------------------------------

const ROLE_LABELS = { owner_list: "To owner", shop_order: "To shop", text: "Text" };

async function pollSimulator() {
  if (state.me?.messaging_mode !== "simulator" || !$("#sim").open) return;
  if (!editing($("#sim"))) {
    $("#sim-strap").innerHTML = state.straps.map((s) =>
      `<option value="${esc(s.device_id)}">${esc(s.display_name || s.device_id)}</option>`).join("");
  }
  const { messages } = await api("GET", "/api/sim/messages");
  $("#sim-inbox").innerHTML = messages.length ? messages.map((m) => `
    <div class="bubble ${esc(m.role)}">
      <div class="meta">${esc(ROLE_LABELS[m.role] || m.role)} ${esc(m.to)} · ${esc(new Date(m.ts).toLocaleTimeString())}</div>
      <div class="msg">${esc(m.text)}</div>
      ${m.buttons.length ? `<div class="row">${m.buttons.map((b) =>
        `<button class="small" data-order="${m.order_id}" data-action="${b.payload.endsWith(":yes") ? "order" : "not_now"}">${esc(b.title)}</button>`).join("")}</div>` : ""}
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

// --- routing and polling -------------------------------------------------------

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
  state.items = await api("GET", "/api/items");
  renderLabelOptions();
  route();
}

window.addEventListener("hashchange", route);
setInterval(() => {
  if (document.visibilityState === "visible" && state.view !== "settings") refresh();
}, POLL_MS);
boot();
