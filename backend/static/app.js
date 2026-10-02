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

function itemOptions(selectedId, includeNone = true) {
  const opts = includeNone ? [`<option value="">— no label —</option>`] : [];
  for (const item of state.items) {
    const price = item.price_inr == null ? "no price" : `₹${item.price_inr}`;
    opts.push(`<option value="${item.id}" ${item.id === selectedId ? "selected" : ""}>${esc(item.name)} (${price})</option>`);
  }
  return opts.join("");
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
      grid.innerHTML = `<div class="empty">No straps yet. <a href="#claim">Claim one</a>.</div>`;
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
            <div class="muted">${esc(s.item ? s.item.name : "No contents label")}</div>
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
          <select class="item-select" aria-label="Contents" style="flex:1">${itemOptions(s.item?.id)}</select>
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
    if (e.target.classList.contains("save-name")) {
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

$("#strap-grid").addEventListener("change", async (e) => {
  if (!e.target.classList.contains("item-select")) return;
  const id = e.target.closest(".card").dataset.id;
  const value = e.target.value ? Number(e.target.value) : null;
  try {
    await api("PATCH", `/api/straps/${id}`, { item_id: value });
    e.target.blur();
    toast("Contents label updated");
    await views.straps.load();
  } catch (err) {
    toast(err.message);
  }
});

views.claim = {
  async load() {
    if (!editing($("#view-claim"))) $("#claim-item").innerHTML = itemOptions(null);
  },
};

$("#claim-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const item = $("#claim-item").value;
    await api("POST", "/api/straps/claim", {
      claim_code: $("#claim-code").value.trim().toUpperCase(),
      display_name: $("#claim-name").value.trim(),
      item_id: item ? Number(item) : null,
    });
    e.target.reset();
    toast("Strap claimed");
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

const pollers = [];

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
  state.items = await api("GET", "/api/items");
  route();
}

window.addEventListener("hashchange", route);
setInterval(() => {
  if (document.visibilityState === "visible" && state.view !== "settings") refresh();
}, POLL_MS);
boot();
