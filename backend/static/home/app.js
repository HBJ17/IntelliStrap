// IntelliStrap home screen: a calm, minimal pantry view for the person who owns the jars.
// Talks to the same /api/* endpoints as the technician dashboard (/admin).
(() => {
  "use strict";

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const rupees = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");

  const state = {
    tab: "jars", filter: "all",
    straps: null, list: null, orders: null, settings: null, items: [],
    openJar: null, jarMode: "view", online: true, threshold: 400, add: null,
  };

  /* ---------------------------------------------------------------- icons */
  const I = {
    check: '<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    alert: '<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    warn: '<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4m0 4h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/></svg>',
    clock: '<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    send: '<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>',
    x: '<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    off: '<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="1" y1="1" x2="23" y2="23"/><path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55M5 12.55a10.94 10.94 0 0 1 5.17-2.39M10.71 5.05A16 16 0 0 1 22.58 9M1.42 9a15.91 15.91 0 0 1 4.7-2.88M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01"/></svg>',
    jar: '<svg class="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h10a1 1 0 0 1 1 1v1a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M5 6h14a2 2 0 0 1 2 2v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V8a2 2 0 0 1 2-2Z"/><line x1="3" y1="13" x2="21" y2="13" stroke-width="2.5"/></svg>',
    jarNav: '<svg class="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="7" width="14" height="14" rx="3"/><path d="M8 3h8v4H8z"/><path d="M5 13h14"/></svg>',
    cart: '<svg class="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="20" r="1"/><circle cx="19" cy="20" r="1"/><path d="M1 2h3l2.6 11.6a2 2 0 0 0 2 1.6h9.8a2 2 0 0 0 2-1.6L22 6H5"/></svg>',
    doc: '<svg class="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z"/></svg>',
    plus: '<svg class="w-8 h-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    close: '<svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>',
    edit: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>',
    redo: '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>',
    wa: '<svg class="w-6 h-6" viewBox="0 0 24 24" fill="currentColor"><path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2.05 22l5.25-1.38a9.9 9.9 0 0 0 4.74 1.21c5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2Zm0 1.67a8.2 8.2 0 0 1 5.83 2.42 8.2 8.2 0 0 1 2.41 5.83c0 4.54-3.7 8.24-8.23 8.24-1.45 0-2.88-.38-4.13-1.12l-.3-.18-3.12.82.83-3.04-.2-.31a8.2 8.2 0 0 1-1.33-4.42c.01-4.54 3.7-8.24 8.25-8.24ZM9.03 7.82c-.19 0-.51.07-.78.36-.26.29-1.02 1-1.02 2.45s1.05 2.85 1.2 3.04c.15.2 2.06 3.15 5 4.42 2.44 1.05 2.94.83 3.48.78.54-.05 1.75-.72 2-1.43.25-.71.25-1.32.18-1.44-.07-.13-.26-.2-.55-.35-.29-.15-1.72-.86-1.99-.95-.26-.1-.45-.15-.64.15-.2.29-.75.95-.92 1.15-.17.19-.33.22-.62.07-.3-.15-1.23-.45-2.33-1.43-.85-.76-1.43-1.7-1.6-1.99-.16-.29-.02-.45.13-.6.13-.13.29-.34.45-.52.15-.19.2-.32.3-.52.1-.19.05-.36-.02-.51-.08-.14-.66-1.58-.9-2.16-.24-.56-.47-.48-.65-.49h-.57Z"/></svg>',
  };

  /* ------------------------------------------------------------- API layer */
  class ApiError extends Error { constructor(msg, status) { super(msg); this.status = status; } }

  const FRIENDLY = [
    [/no unclaimed strap/i, "We couldn't find that code. Check the 6 characters shown on your strap and try again."],
    [/wrong password/i, "That password isn't right. Please try again."],
    [/too many requests/i, "Too many tries. Please wait a minute and try again."],
  ];
  function friendly(status, data) {
    const d = data && data.detail;
    if (typeof d === "string") { for (const [re, msg] of FRIENDLY) if (re.test(d)) return msg; return d; }
    if (Array.isArray(d)) return "Please check what you typed. A number should look like +91 98765 43210.";
    return status >= 500 ? "Something went wrong on our side. Please try again." : "That didn't work. Please try again.";
  }

  async function api(method, path, body) {
    let res;
    try {
      res = await fetch(path, { method, cache: "no-store", headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    } catch (e) {
      setOnline(false);
      throw new ApiError("We can't reach your pantry right now. Check your connection.", 0);
    }
    setOnline(true);
    if (res.status === 401 && path !== "/api/login") { showLogin(); throw new ApiError("auth", 401); }
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) throw new ApiError(friendly(res.status, data), res.status);
    return data;
  }

  /* ----------------------------------------------------------------- toast */
  let toastTimer;
  function toast(msg, kind = "ok") {
    const t = $("#toast"); $("#toast-text").textContent = msg;
    const ic = $("#toast-icon");
    ic.textContent = kind === "ok" ? "✓" : "!";
    ic.style.background = kind === "ok" ? "#2E9E4F" : "#E5484D";
    t.classList.remove("translate-y-24", "opacity-0", "pointer-events-none");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add("translate-y-24", "opacity-0", "pointer-events-none"), 3600);
  }

  /* ------------------------------------------------------------ formatting */
  function dayLabel(iso) {
    if (!iso) return "";
    const d = new Date(iso), now = new Date();
    const start = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = Math.round((start(now) - start(d)) / 86400000);
    if (diff <= 0) return "Today";
    if (diff === 1) return "Yesterday";
    if (diff < 7) return diff + " days ago";
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  }
  function joinNames(names) {
    if (names.length <= 1) return names.join("");
    if (names.length === 2) return names.join(" and ");
    return names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
  }
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

  /* -------------------------------------------------------- jar status model */
  const TONE = {
    green: { c: "#2E9E4F", bg: "#E8F6EC" }, amber: { c: "#F59E0B", bg: "#FEF3C7" },
    red: { c: "#E5484D", bg: "#FEE2E2" }, grey: { c: "#9AA4B2", bg: "#F1F4F8" }, blue: { c: "#1F6FEB", bg: "#E7F0FD" },
  };
  function holdSeconds() {
    const s = state.settings; if (!s) return 20;
    return s.dev_hold_seconds != null ? s.dev_hold_seconds : (s.global && s.global.hold_seconds) || 20;
  }
  // The strap only knows OK / LOW. "Running low" is a jar that has just gone LOW and is still within the hold
  // time; "Refill needed" is one that stayed LOW and has joined (or is about to join) the shopping list.
  function statusOf(s) {
    const gap = s.gap == null ? null : Number(s.gap);
    const fullFill = gap == null ? 85 : 60 + clamp((gap - 40) / 60, 0, 1) * 40;
    const lowFill = gap == null ? 15 : 8 + clamp(gap, 0, 40) / 40 * 20;
    const lowAge = s.state_since ? (Date.now() - new Date(s.state_since).getTime()) / 1000 : 1e9;
    const lastKnown = s.state === "LOW" ? lowFill : s.state === "OK" ? fullFill : 0;
    switch (s.status) {
      case "OK": return { key: "full", label: "Full", tone: "green", icon: I.check, fill: fullFill, note: "Well stocked" };
      case "LOW":
        return lowAge >= holdSeconds()
          ? { key: "refill", label: "Refill needed", tone: "red", icon: I.alert, fill: lowFill, note: "On your shopping list" }
          : { key: "low", label: "Running low", tone: "amber", icon: I.warn, fill: lowFill, note: "Checking… not on your list yet" };
      case "OFFLINE": return { key: "offline", label: "Not connected", tone: "grey", icon: I.off, fill: lastKnown, note: "Check power and Wi-Fi" };
      default: return { key: "unknown", label: "Getting ready", tone: "grey", icon: I.clock, fill: 0, note: "Waiting for the strap" };
    }
  }
  const jarName = (s) => s.display_name || (s.item && s.item.name) || "My jar";

  function jarVisual(fill, color, big = true) {
    const w = big ? "w-28 h-36" : "w-20 h-28", lid = big ? "h-3 inset-x-3" : "h-2.5 inset-x-2", band = big ? "h-6" : "h-4", dot = big ? "w-2.5 h-2.5" : "w-1.5 h-1.5";
    return `<div class="relative ${w} bg-[#F7F9FC] border-[3px] border-[#17212B] rounded-20 overflow-hidden flex flex-col justify-end shadow-inner" aria-hidden="true">
      <div class="absolute top-0 ${lid} bg-[#17212B] rounded-b-md"></div>
      <div class="absolute top-1/2 -translate-y-1/2 inset-x-0 ${band} bg-[#1F6FEB] flex items-center justify-center z-10 shadow-sm"><div class="${dot} rounded-full bg-white"></div></div>
      <div class="jar-fill w-full" style="height:${Math.round(fill)}%;background:${color}"><div class="h-1.5 w-full" style="background:${color}"></div></div>
    </div>`;
  }
  const chip = (tone, icon, text) => `<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-black" style="background:${TONE[tone].bg};color:${TONE[tone].c}">${icon}<span>${esc(text)}</span></span>`;

  /* ------------------------------------------------------------------ tabs */
  const TABS = [
    { id: "jars", label: "My Jars", icon: I.jarNav },
    { id: "list", label: "Shopping List", icon: I.cart },
    { id: "orders", label: "Orders", icon: I.doc },
  ];
  function tabBadge(id) {
    const straps = state.straps || [], orders = state.orders || [], rows = state.list ? state.list.rows : [];
    if (id === "jars" && straps.some((s) => statusOf(s).key === "refill")) return { dot: "#E5484D", title: "Jars need refilling" };
    if (id === "list" && rows.length) return { count: rows.length };
    if (id === "orders" && orders.some((o) => o.status === "awaiting_owner")) return { dot: "#F59E0B", title: "An order is waiting for your reply" };
    return null;
  }
  function renderTabs() {
    const top = TABS.map((t) => {
      const on = state.tab === t.id, b = tabBadge(t.id);
      const badge = b ? (b.count != null ? `<span class="px-2 py-0.5 text-xs font-black rounded-full bg-[#E7F0FD] text-[#1F6FEB]">${b.count}</span>` : `<span class="w-2 h-2 rounded-full" style="background:${b.dot}" title="${esc(b.title)}"></span>`) : "";
      return `<button type="button" data-tab="${t.id}" aria-current="${on}" class="flex-1 min-h-[48px] py-2.5 px-3 rounded-20 text-base font-extrabold flex items-center justify-center gap-2 transition ${on ? "bg-white text-[#1F6FEB] shadow-sm" : "text-[#5B6776] hover:text-[#17212B]"}">${t.icon.replace("w-6 h-6", "w-5 h-5")}<span>${t.label}</span>${badge}</button>`;
    }).join("");
    $("#top-tabs").innerHTML = top;
    $("#bottom-tabs").innerHTML = TABS.map((t) => {
      const on = state.tab === t.id, b = tabBadge(t.id);
      const badge = b ? (b.count != null ? `<span class="absolute -top-1 -right-3 min-w-[20px] h-5 px-1.5 rounded-full bg-[#1F6FEB] text-white text-[11px] font-black flex items-center justify-center">${b.count}</span>` : `<span class="absolute -top-0.5 -right-2 w-2.5 h-2.5 rounded-full border-2 border-white" style="background:${b.dot}"></span>`) : "";
      return `<button type="button" data-tab="${t.id}" aria-current="${on}" class="min-h-[60px] pt-2 pb-1.5 flex flex-col items-center justify-center gap-0.5 text-[11px] font-extrabold ${on ? "text-[#1F6FEB]" : "text-[#5B6776]"}"><span class="relative">${t.icon}${badge}</span><span>${t.label}</span></button>`;
    }).join("");
  }
  function switchTab(id, push = true) {
    if (!TABS.some((t) => t.id === id)) id = "jars";
    state.tab = id;
    $$("[data-section]").forEach((el) => el.classList.toggle("hidden", el.dataset.section !== id));
    if (push && location.hash !== "#" + id) history.replaceState(null, "", "#" + id);
    renderTabs(); window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /* ---------------------------------------------------------------- header */
  function renderHeader() {
    const straps = state.straps || [];
    const connected = straps.filter((s) => s.status === "OK" || s.status === "LOW").length;
    const badge = $("#conn-badge");
    let tone = "grey", text = "No jars yet";
    if (straps.length) {
      if (connected === straps.length) { tone = "green"; text = straps.length === 1 ? "Jar connected" : "All jars connected"; }
      else if (connected === 0) { tone = "grey"; text = "Jars not connected"; }
      else { tone = "amber"; text = `${connected} of ${straps.length} jars connected`; }
    }
    badge.style.background = TONE[tone].bg; badge.style.color = TONE[tone].c;
    badge.innerHTML = `<span class="w-2 h-2 rounded-full" style="background:${TONE[tone].c}"></span><span>${text}</span>`;
    const banner = $("#offline-banner");
    banner.classList.toggle("hidden", state.online);
    banner.textContent = "We can't reach your pantry right now. We'll keep trying and show the latest information we have.";
  }
  function setOnline(v) { if (state.online !== v) { state.online = v; renderHeader(); } }

  /* --------------------------------------------------------------- My Jars */
  function skeletonCards(n = 3) {
    return `<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">${Array.from({ length: n }, () => '<div class="h-72 rounded-20 skeleton"></div>').join("")}</div>`;
  }
  function renderJars() {
    const el = $("#tab-jars");
    if (!state.straps) { el.innerHTML = '<div class="h-28 rounded-20 skeleton"></div>' + skeletonCards(); return; }
    const straps = state.straps, st = straps.map((s) => ({ s, x: statusOf(s) }));
    const refill = st.filter((a) => a.x.key === "refill"), low = st.filter((a) => a.x.key === "low");
    const ok = st.filter((a) => a.x.key === "full"), off = st.filter((a) => a.x.key === "offline" || a.x.key === "unknown");
    const listCount = state.list ? state.list.rows.length : 0;

    let head, sub;
    if (!straps.length) { head = "Let's add your first jar"; sub = "Wrap a strap around a jar, then tap “Add a jar”."; }
    else if (refill.length) { const n = refill.map((a) => jarName(a.s)); head = `${joinNames(n)} ${n.length > 1 ? "need" : "needs"} refilling`; sub = low.length ? `${joinNames(low.map((a) => jarName(a.s)))} ${low.length > 1 ? "are" : "is"} running low too.` : "We've added " + (n.length > 1 ? "them" : "it") + " to your shopping list."; }
    else if (low.length) { const n = low.map((a) => jarName(a.s)); head = `${joinNames(n)} ${n.length > 1 ? "are" : "is"} running low`; sub = "If it stays low, we'll add it to your shopping list."; }
    else if (ok.length && off.length) { head = "Your connected jars are stocked"; sub = `${off.length} jar${off.length > 1 ? "s are" : " is"} not connected. Check the power and Wi-Fi.`; }
    else if (ok.length) { head = "All jars are stocked"; sub = "Nothing to buy right now. Enjoy your cooking!"; }
    else if (st.every((a) => a.x.key === "offline")) { head = st.length > 1 ? "Your jars aren't connected" : "Your jar isn't connected"; sub = "Check that the strap has power and is on your Wi-Fi."; }
    else { head = "Getting your jars ready"; sub = "They'll show up here as soon as they connect."; }

    const filters = [
      { id: "all", label: `All (${st.length})` },
      { id: "need", label: `Needs refill (${refill.length + low.length})` },
      { id: "ok", label: `Stock OK (${ok.length})` },
    ].concat(off.length ? [{ id: "off", label: `Not connected (${off.length})` }] : []);
    if (!filters.some((f) => f.id === state.filter)) state.filter = "all";
    const match = (a) => state.filter === "all" || (state.filter === "need" && (a.x.key === "refill" || a.x.key === "low")) || (state.filter === "ok" && a.x.key === "full") || (state.filter === "off" && (a.x.key === "offline" || a.x.key === "unknown"));

    const cards = st.filter(match).map(({ s, x }) => {
      const t = TONE[x.tone];
      return `<article role="button" tabindex="0" data-jar="${esc(s.device_id)}" aria-label="${esc(jarName(s))}: ${x.label}. Open details" class="group bg-white rounded-20 p-5 border-2 border-[#E7F0FD] hover:border-[#1F6FEB] transition-all cursor-pointer shadow-card flex flex-col justify-between min-h-[18rem] fade-in">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0"><h3 class="text-2xl font-black truncate group-hover:text-[#1F6FEB] transition">${esc(jarName(s))}</h3>
            <p class="text-sm font-semibold text-[#5B6776] truncate">${esc(s.item ? s.item.name : "No contents set")}</p></div>
          ${chip(x.tone, x.icon, x.label)}
        </div>
        <div class="my-auto py-2 flex items-center justify-center">${jarVisual(x.fill, t.c)}</div>
        <div class="flex items-center justify-between gap-2 text-xs font-bold text-[#5B6776] border-t border-[#F1F4F8] pt-3">
          <span class="truncate">${esc(x.note)}</span><span class="text-[#1F6FEB] whitespace-nowrap">Details &rarr;</span>
        </div></article>`;
    }).join("");

    el.innerHTML = `
      <div class="bg-white rounded-20 p-5 sm:p-6 border border-[#E7F0FD] shadow-card flex flex-col sm:flex-row sm:items-center justify-between gap-4 fade-in">
        <div class="space-y-1 min-w-0"><h2 class="text-2xl sm:text-3xl font-extrabold tracking-tight">${esc(head)}</h2>
          <p class="text-sm font-medium text-[#5B6776]">${esc(sub)}</p></div>
        ${listCount ? `<button type="button" data-tab="list" class="self-start sm:self-center min-h-[48px] px-5 rounded-20 bg-[#E7F0FD] text-[#1F6FEB] font-extrabold hover:bg-[#1F6FEB] hover:text-white transition whitespace-nowrap">View ${listCount} list item${listCount > 1 ? "s" : ""} &rarr;</button>` : ""}
      </div>
      ${straps.length ? `<div class="flex items-center gap-2 overflow-x-auto no-scrollbar pb-1 text-sm font-bold" role="group" aria-label="Filter jars">${filters.map((f) => `<button type="button" data-filter="${f.id}" aria-pressed="${state.filter === f.id}" class="min-h-[44px] px-4 rounded-full whitespace-nowrap ${state.filter === f.id ? "bg-[#1F6FEB] text-white" : "bg-white text-[#5B6776] border border-[#E7F0FD] hover:bg-[#F1F4F8]"}">${esc(f.label)}</button>`).join("")}</div>` : ""}
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
        ${cards}
        <button type="button" data-add class="rounded-20 border-2 border-dashed border-[#1F6FEB] bg-[#E7F0FD]/60 hover:bg-[#E7F0FD] p-6 text-center transition flex flex-col items-center justify-center min-h-[${straps.length ? "18rem" : "14rem"}] gap-3 text-[#1F6FEB]">
          <span class="w-16 h-16 rounded-full bg-white shadow-card flex items-center justify-center">${I.plus}</span>
          <span><span class="block text-xl font-black">Add a jar</span><span class="block text-xs font-bold text-[#5B6776] mt-1">Wrap a strap around a jar and tap here</span></span>
        </button>
      </div>`;
  }

  /* -------------------------------------------------------- Shopping list */
  function renderList() {
    const el = $("#tab-list");
    if (!state.list) { el.innerHTML = '<div class="h-72 rounded-20 skeleton"></div>'; return; }
    const { rows, total_inr: total, threshold_inr: thr } = state.list, missing = state.list.missing_prices || [];
    const pct = thr ? clamp(Math.round(total / thr * 100), 0, 100) : 0;
    const waiting = (state.orders || []).find((o) => o.status === "awaiting_owner");
    const head = `<div class="flex items-center justify-between pb-4 border-b border-[#F1F4F8]"><div>
        <h2 class="text-2xl sm:text-3xl font-extrabold">Your shopping list</h2>
        <p class="text-sm font-semibold text-[#5B6776] mt-0.5">Added automatically when jars stay low</p></div>
        ${rows.length ? `<span class="whitespace-nowrap flex-shrink-0 ml-3 px-3.5 py-1.5 rounded-full text-xs font-black bg-[#E7F0FD] text-[#1F6FEB]">${rows.length} item${rows.length > 1 ? "s" : ""}</span>` : ""}</div>`;
    if (!rows.length) {
      el.innerHTML = `<div class="bg-white rounded-20 p-5 sm:p-7 border border-[#E7F0FD] shadow-card fade-in">${head}
        <div class="py-12 text-center flex flex-col items-center"><div class="w-20 h-20 rounded-full bg-[#E8F6EC] text-[#2E9E4F] flex items-center justify-center mb-3"><svg class="w-10 h-10" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg></div>
        <h3 class="text-2xl font-black">Nothing needed right now</h3>
        <p class="text-sm font-semibold text-[#5B6776] max-w-sm mt-1">${waiting ? "Your last list is waiting for your reply on WhatsApp." : "All your jars have plenty of stock. Relax and enjoy your cooking!"}</p></div></div>`;
      return;
    }
    const items = rows.map((r) => `<div class="py-4 flex items-center justify-between gap-3">
        <div class="flex items-center gap-3.5 min-w-0"><div class="w-12 h-12 rounded-16 bg-[#FEE2E2] text-[#E5484D] flex items-center justify-center flex-shrink-0">${I.jar}</div>
          <div class="min-w-0"><h4 class="text-lg font-extrabold truncate">${esc(r.item_name)}${r.qty > 1 ? ` <span class="text-[#5B6776]">× ${r.qty}</span>` : ""}</h4>
            <p class="text-xs font-semibold text-[#5B6776] truncate">${r.strap_name ? "From " + esc(r.strap_name) : "Added by you"}</p></div></div>
        <div class="flex items-center gap-2 flex-shrink-0">${r.needs_price ? '<span class="text-sm font-black text-[#F59E0B]">No price yet</span>' : `<span class="text-xl font-black">${rupees(r.line_total_inr)}</span>`}
          <button type="button" data-remove-row="${r.id}" class="w-11 h-11 rounded-full bg-[#F7F9FC] hover:bg-[#FEE2E2] hover:text-[#E5484D] text-[#9AA4B2] flex items-center justify-center transition" aria-label="Remove ${esc(r.item_name)} from the list" title="Remove">${I.close}</button></div></div>`).join("");
    el.innerHTML = `<div class="bg-white rounded-20 p-5 sm:p-7 border border-[#E7F0FD] shadow-card fade-in">${head}
      <div class="divide-y divide-[#F1F4F8] my-2">${items}</div>
      <div class="mt-4 pt-5 border-t border-[#E7F0FD] space-y-4">
        <div class="flex items-baseline justify-between"><span class="text-base font-bold text-[#5B6776]">List total</span>
          <div class="text-right"><span class="text-3xl sm:text-4xl font-black">${rupees(total)}</span><p class="text-xs font-semibold text-[#5B6776]">Auto-order at ${rupees(thr)}</p></div></div>
        <div class="space-y-1.5"><div class="w-full bg-[#F1F4F8] h-2.5 rounded-full overflow-hidden" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100" aria-label="Progress to automatic order"><div class="bg-[#1F6FEB] h-full rounded-full transition-all duration-500" style="width:${pct}%"></div></div>
          <div class="flex justify-between text-xs font-bold text-[#5B6776]"><span>${rupees(total)} saved up</span><span>${total >= thr ? "Ready to send" : rupees(thr - total) + " to auto-order"}</span></div></div>
        ${missing.length ? `<p class="text-sm font-bold text-[#B45309] bg-[#FEF3C7] rounded-16 p-3">Some items have no price yet. Open the jar and choose “Edit name and price” so the list can be sent.</p>` : ""}
        <div class="pt-1"><button type="button" id="send-list" class="w-full min-h-[56px] py-3.5 px-6 rounded-20 bg-[#1F6FEB] hover:bg-[#1858bd] active:scale-[0.99] text-white font-extrabold text-lg flex items-center justify-center gap-3 shadow-float transition">${I.wa}<span>Send to my WhatsApp</span></button>
          <p class="text-center text-xs font-semibold text-[#5B6776] mt-2.5">Sent automatically when the list reaches ${rupees(thr)}.</p></div>
      </div></div>`;
  }

  /* ---------------------------------------------------------------- Orders */
  function orderTone(o) {
    switch (o.status) {
      case "delivery_confirmed": return { tone: "green", label: "Shop confirmed", icon: I.check, steps: ["done", "done", "done"], note: "The shop will deliver it" };
      case "sent_to_shop": return { tone: "blue", label: "Sent to shop", icon: I.send, steps: ["done", "done", "todo"], note: "Waiting for the shop to answer" };
      case "confirmed": return { tone: "blue", label: "Sending to shop", icon: I.send, steps: ["done", "now", "todo"], note: "Sending now…" };
      case "awaiting_owner": return { tone: "amber", label: "Waiting for your reply", icon: I.clock, steps: ["done", "now", "todo"], note: "Open WhatsApp and tap “Place Order”" };
      case "shop_declined": return { tone: "red", label: "Shop can't deliver", icon: I.x, steps: ["done", "done", "fail"], note: "The items are back on your shopping list" };
      case "send_failed": return { tone: "red", label: "Couldn't send", icon: I.alert, steps: ["done", "fail", "todo"], note: "We'll keep your list safe. Try again." };
      case "cancelled": return { tone: "grey", label: "Not now", icon: I.x, steps: null, note: "" };
      default: return { tone: "grey", label: "Expired", icon: I.clock, steps: null, note: "" };
    }
  }
  function timeline(steps, tone, labels) {
    const c = TONE[tone].c;
    const dot = (st, n) => st === "done" ? `<span class="w-6 h-6 rounded-full text-white flex items-center justify-center text-xs font-bold" style="background:${c}">✓</span>`
      : st === "now" ? `<span class="w-6 h-6 rounded-full border-2 flex items-center justify-center text-xs font-black bg-white" style="border-color:${c};color:${c}">•</span>`
      : st === "fail" ? `<span class="w-6 h-6 rounded-full text-white flex items-center justify-center text-xs font-bold" style="background:${TONE.red.c}">✕</span>`
      : `<span class="w-6 h-6 rounded-full bg-[#F1F4F8] text-[#9AA4B2] flex items-center justify-center text-xs font-bold">${n}</span>`;
    const done = steps.filter((s) => s === "done").length;
    const width = steps[2] === "done" ? 100 : steps[1] === "done" ? 50 : steps[1] === "now" ? 25 : 0;
    return `<div class="relative flex items-center justify-between" aria-label="Order progress: ${labels.join(", ")}">
      <div class="absolute inset-x-4 top-3 h-1 bg-[#F1F4F8] rounded"><div class="h-full rounded" style="width:${width}%;background:${c}"></div></div>
      ${labels.map((l, i) => `<div class="flex flex-col items-center gap-1 z-10">${dot(steps[i], i + 1)}<span class="text-[11px] font-bold ${steps[i] === "todo" ? "text-[#9AA4B2]" : ""}" style="${steps[i] !== "todo" ? "color:" + (steps[i] === "fail" ? TONE.red.c : c) : ""}">${l}</span></div>`).join("")}</div>`;
  }
  function renderOrders() {
    const el = $("#tab-orders");
    if (!state.orders) { el.innerHTML = '<div class="h-40 rounded-20 skeleton"></div><div class="h-40 rounded-20 skeleton"></div>'; return; }
    const head = `<div><h2 class="text-2xl sm:text-3xl font-extrabold">Recent orders</h2><p class="text-sm font-semibold text-[#5B6776]">Your lists, sent to your local shop</p></div>`;
    if (!state.orders.length) {
      el.innerHTML = `${head}<div class="bg-white rounded-20 p-8 border border-[#E7F0FD] shadow-card text-center"><div class="w-16 h-16 mx-auto rounded-full bg-[#E7F0FD] text-[#1F6FEB] flex items-center justify-center mb-3">${I.doc}</div><h3 class="text-xl font-black">No orders yet</h3><p class="text-sm font-semibold text-[#5B6776] mt-1">When a jar stays low, your order shows up here.</p></div>`;
      return;
    }
    const cards = state.orders.slice(0, 15).map((o) => {
      const t = orderTone(o), items = o.items.map((i) => `${esc(i.name)} × ${i.qty}`).join(", ") || "Order #" + o.id;
      const compact = !t.steps;
      const actions = o.status === "send_failed" ? `<button type="button" data-order-retry="${o.id}" class="min-h-[44px] px-4 rounded-full bg-[#E7F0FD] text-[#1F6FEB] hover:bg-[#1F6FEB] hover:text-white transition font-black text-sm">Try again</button>` : "";
      const cancel = (o.status === "awaiting_owner" || o.status === "send_failed") ? `<button type="button" data-order-cancel="${o.id}" class="min-h-[44px] px-3 rounded-full text-[#5B6776] hover:text-[#E5484D] font-bold text-sm">Cancel order</button>` : "";
      const labels = o.status === "awaiting_owner" ? ["Listed", "Your reply", "Confirmed"] : ["Listed", "Sent", "Confirmed"];
      if (compact) return `<article class="bg-white rounded-20 p-4 sm:p-5 border border-[#F1F4F8] shadow-card opacity-80 flex items-center justify-between gap-3 fade-in">
          <div class="min-w-0"><h4 class="text-base font-extrabold truncate">${items}</h4><p class="text-xs font-semibold text-[#5B6776]">${esc(o.shop || "Your shop")} • ${dayLabel(o.created_at)}</p></div>${chip(t.tone, t.icon, t.label)}</article>`;
      return `<article class="bg-white rounded-20 p-5 sm:p-6 border shadow-card space-y-4 fade-in" style="border-color:${TONE[t.tone].bg}">
        <div class="flex flex-wrap items-start justify-between gap-3"><div class="min-w-0"><h3 class="text-xl font-extrabold">${items}</h3>
          <p class="text-xs font-semibold text-[#5B6776] mt-0.5">${esc(o.shop || "Your shop")} • ${dayLabel(o.created_at)}</p></div>${chip(t.tone, t.icon, t.label)}</div>
        ${timeline(t.steps, t.tone, labels)}
        <div class="flex flex-wrap items-center justify-between gap-2 pt-3 border-t border-[#F1F4F8]"><div><span class="font-extrabold">Total: ${rupees(o.total_inr)}</span>
          <p class="text-xs font-bold mt-0.5" style="color:${TONE[t.tone].c}">${esc(t.note)}</p></div><div class="flex items-center gap-1">${actions}${cancel}</div></div></article>`;
    }).join("");
    el.innerHTML = head + `<div class="space-y-4">${cards}</div>`;
  }

  /* ------------------------------------------------------------- Jar modal */
  const jarModal = $("#jar-modal"), jarCard = $("#jar-modal-card");
  function openModal(el) { el.classList.remove("hidden"); el.classList.add("flex"); document.body.style.overflow = "hidden"; }
  function closeModal(el) { el.classList.add("hidden"); el.classList.remove("flex"); if (!$$("#jar-modal.flex, #add-modal.flex").length && $("#settings-drawer").getAttribute("aria-hidden") !== "false") document.body.style.overflow = ""; }
  const strapById = (id) => (state.straps || []).find((s) => s.device_id === id);
  const closeBtn = (label) => `<button type="button" data-close class="w-11 h-11 rounded-full bg-[#F7F9FC] hover:bg-[#F1F4F8] text-[#5B6776] flex items-center justify-center transition flex-shrink-0" aria-label="${label}">${I.close}</button>`;
  const inputCls = "w-full min-h-[52px] px-4 rounded-16 bg-[#F7F9FC] border border-[#E7F0FD] focus:border-[#1F6FEB] focus:bg-white focus:outline-none text-base font-bold transition";

  function renderJarModal() {
    const s = strapById(state.openJar); if (!s) { closeModal(jarModal); return; }
    const x = statusOf(s), t = TONE[x.tone], it = s.item;
    if (state.jarMode === "edit") {
      jarCard.innerHTML = `<div class="flex items-start justify-between gap-3 mb-5"><h3 id="jar-modal-title" class="text-2xl font-black">Edit this jar</h3>${closeBtn("Close")}</div>
        <form id="edit-form" class="space-y-4" novalidate>
          <div><label class="block text-sm font-extrabold mb-1.5" for="e-name">Jar name</label><input id="e-name" class="${inputCls}" maxlength="80" value="${esc(s.display_name || "")}" required></div>
          <div><label class="block text-sm font-extrabold mb-1.5" for="e-label">What's inside?</label><input id="e-label" list="item-names" class="${inputCls}" maxlength="80" value="${esc(it ? it.name : "")}" placeholder="e.g. Toor dal"></div>
          <div><label class="block text-sm font-extrabold mb-1.5" for="e-price">Shop price (₹)</label><input id="e-price" inputmode="numeric" pattern="[0-9]*" class="${inputCls}" value="${it && it.price_inr != null ? it.price_inr : ""}" placeholder="e.g. 150"><p class="text-xs font-semibold text-[#5B6776] mt-1.5">This is what we add to your shopping list.</p></div>
          <p id="e-error" class="text-sm font-bold text-[#E5484D] min-h-[1.25rem]" role="alert"></p>
          <button type="submit" class="w-full min-h-[52px] rounded-20 bg-[#1F6FEB] hover:bg-[#1858bd] text-white font-extrabold text-base shadow-sm transition">Save</button>
          <button type="button" data-jar-mode="view" class="w-full min-h-[48px] rounded-20 text-[#5B6776] hover:bg-[#F1F4F8] font-bold text-sm transition">Cancel</button>
          <button type="button" data-remove-jar class="w-full min-h-[44px] rounded-20 text-[#9AA4B2] hover:text-[#E5484D] font-bold text-xs transition">Remove this jar</button>
        </form>`;
    } else if (state.jarMode === "recal-wait") {
      jarCard.innerHTML = `<div class="flex items-start justify-between gap-3 mb-4"><h3 id="jar-modal-title" class="text-2xl font-black">Set up ${esc(jarName(s))} again</h3>${closeBtn("Close")}</div>
        <div class="bg-[#F1F4F8] rounded-20 p-5 flex gap-4 items-center mb-5"><div class="flex-shrink-0">${jarVisual(x.fill, t.c, false)}</div>
          <p class="text-sm font-bold text-[#17212B]">Jar offline, will wait until online to recalibrate</p></div>
        <button type="button" data-jar-mode="view" class="w-full min-h-[52px] rounded-20 bg-[#1F6FEB] hover:bg-[#1858bd] text-white font-extrabold text-base shadow-sm transition">OK</button>`;
    } else if (state.jarMode === "recal") {
      jarCard.innerHTML = `<div class="flex items-start justify-between gap-3 mb-4"><h3 id="jar-modal-title" class="text-2xl font-black">Set up ${esc(jarName(s))} again</h3>${closeBtn("Close")}</div>
        <div class="bg-[#E7F0FD] rounded-20 p-5 flex gap-4 items-center mb-5"><div class="flex-shrink-0">${jarVisual(6, "#9AA4B2", false)}</div>
          <p class="text-sm font-bold text-[#17212B]">Please empty the jar and click next</p></div>
        <button type="button" data-recal-go class="w-full min-h-[52px] rounded-20 bg-[#1F6FEB] hover:bg-[#1858bd] text-white font-extrabold text-base shadow-sm transition mb-2">Next</button>
        <button type="button" data-jar-mode="view" class="w-full min-h-[48px] rounded-20 text-[#5B6776] hover:bg-[#F1F4F8] font-bold text-sm transition">Back</button>`;
    } else {
      jarCard.innerHTML = `<div class="flex items-start justify-between gap-3"><div class="space-y-1.5 min-w-0">${chip(x.tone, x.icon, x.label)}
          <h3 id="jar-modal-title" class="text-3xl font-black truncate">${esc(jarName(s))}</h3><p class="text-sm font-semibold text-[#5B6776]">${esc(it ? it.name : "No contents set yet")}</p></div>${closeBtn("Close")}</div>
        <div class="bg-[#F7F9FC] rounded-20 p-6 my-5 flex items-center justify-around gap-4">${jarVisual(x.fill, t.c, false)}
          <div class="space-y-3 text-left"><div><span class="text-xs font-bold text-[#5B6776] uppercase">Pack size</span><p class="text-lg font-black">${esc(it && (it.pack_size || it.unit) ? (it.pack_size || it.unit) : "—")}</p></div>
            <div><span class="text-xs font-bold text-[#5B6776] uppercase">Shop price</span><p class="text-lg font-black text-[#1F6FEB]">${it && it.price_inr != null ? rupees(it.price_inr) : "Not set"}</p></div></div></div>
        <p class="text-sm font-bold text-center text-[#5B6776] mb-5">${esc(x.note)}</p>
        <div class="space-y-2.5"><button type="button" data-jar-mode="edit" class="w-full min-h-[52px] rounded-20 bg-[#1F6FEB] hover:bg-[#1858bd] text-white font-extrabold text-base transition flex items-center justify-center gap-2 shadow-sm">${I.edit}<span>Edit name and price</span></button>
          <button type="button" data-jar-mode="recal" class="w-full min-h-[48px] rounded-20 text-[#5B6776] hover:text-[#17212B] hover:bg-[#F1F4F8] font-bold text-sm transition flex items-center justify-center gap-2">${I.redo}<span>Set up this jar again</span></button></div>`;
    }
  }
  function openJar(id) { state.openJar = id; state.jarMode = "view"; renderJarModal(); openModal(jarModal); }

  const numOrNull = (v) => { v = String(v || "").replace(/[^\d]/g, ""); return v === "" ? null : parseInt(v, 10); };

  async function saveEdit(form) {
    const err = $("#e-error", form), name = $("#e-name", form).value.trim(), label = $("#e-label", form).value.trim(), price = numOrNull($("#e-price", form).value);
    err.textContent = "";
    if (!name) { err.textContent = "Please give the jar a name."; return; }
    if (price != null && !label) { err.textContent = "Tell us what's inside before setting a price."; return; }
    const body = { display_name: name, label }; if (price != null) body.price_inr = price;
    const btn = $("button[type=submit]", form); btn.disabled = true;
    try { await api("PATCH", "/api/straps/" + encodeURIComponent(state.openJar), body); toast("Saved"); state.jarMode = "view"; await refresh(true); renderJarModal(); }
    catch (e) { if (e.message !== "auth") err.textContent = e.message; } finally { btn.disabled = false; }
  }

  /* ---------------------------------------------------------- Add a jar flow */
  const addModal = $("#add-modal"), addCard = $("#add-card");
  function dots(n) { return `<div class="flex items-center gap-1.5" aria-label="Step ${n} of 3">${[1, 2, 3].map((i) => `<span class="h-2 rounded-full transition-all ${i === n ? "w-6 bg-[#1F6FEB]" : "w-2 " + (i < n ? "bg-[#1F6FEB]/50" : "bg-[#E7F0FD]")}"></span>`).join("")}</div>`; }
  function openAdd() { state.add = { step: 1, code: "", name: "", label: "", price: "", error: "" }; renderAdd(); openModal(addModal); setTimeout(() => $("#a-code") && $("#a-code").focus(), 50); }
  function renderAdd() {
    const a = state.add; if (!a) return;
    const head = (title) => `<div class="flex items-start justify-between gap-3 mb-5"><div class="space-y-2"><h3 id="add-title" class="text-2xl font-black">${title}</h3>${dots(a.step)}</div>${closeBtn("Close")}</div>`;
    const err = `<p class="text-sm font-bold text-[#E5484D] min-h-[1.25rem]" role="alert">${esc(a.error)}</p>`;
    if (a.step === 1) addCard.innerHTML = head("Enter your strap's code") + `<form id="add-form" class="space-y-4" novalidate>
        <p class="text-sm font-semibold text-[#5B6776]">Switch on the strap. It shows a 6-character code when it first connects.</p>
        <input id="a-code" class="${inputCls} text-center text-3xl tracking-[0.3em] uppercase font-black" maxlength="6" autocomplete="off" autocapitalize="characters" spellcheck="false" value="${esc(a.code)}" placeholder="ABC123" aria-label="6-character strap code">${err}
        <button type="submit" class="w-full min-h-[52px] rounded-20 bg-[#1F6FEB] hover:bg-[#1858bd] text-white font-extrabold text-base transition">Next</button></form>`;
    else if (a.step === 2) addCard.innerHTML = head("What's in this jar?") + `<form id="add-form" class="space-y-4" novalidate>
        <div><label class="block text-sm font-extrabold mb-1.5" for="a-name">Jar name</label><input id="a-name" class="${inputCls}" maxlength="80" value="${esc(a.name)}" placeholder="e.g. Rice jar"></div>
        <div><label class="block text-sm font-extrabold mb-1.5" for="a-label">Contents</label><input id="a-label" list="item-names" class="${inputCls}" maxlength="80" value="${esc(a.label)}" placeholder="e.g. Rice"></div>
        <div><label class="block text-sm font-extrabold mb-1.5" for="a-price">Shop price (₹)</label><input id="a-price" inputmode="numeric" class="${inputCls}" value="${esc(a.price)}" placeholder="e.g. 60"></div>${err}
        <button type="submit" class="w-full min-h-[52px] rounded-20 bg-[#1F6FEB] hover:bg-[#1858bd] text-white font-extrabold text-base transition">Next</button>
        <button type="button" data-add-back class="w-full min-h-[48px] rounded-20 text-[#5B6776] hover:bg-[#F1F4F8] font-bold text-sm transition">Back</button></form>`;
    else addCard.innerHTML = head("Empty the jar, then press Done") + `<div class="space-y-4"><div class="bg-[#E7F0FD] rounded-20 p-5 flex gap-4 items-center"><div class="flex-shrink-0">${jarVisual(6, "#9AA4B2", false)}</div>
        <p class="text-sm font-bold">Fit the strap around the <b>empty</b> jar. It will learn what “empty” looks like, so it can tell when your <b>${esc(a.label || "food")}</b> runs low.</p></div>${err}
        <button type="button" data-add-done class="w-full min-h-[52px] rounded-20 bg-[#2E9E4F] hover:bg-[#25833f] text-white font-extrabold text-base transition">Done</button>
        <button type="button" data-add-back class="w-full min-h-[48px] rounded-20 text-[#5B6776] hover:bg-[#F1F4F8] font-bold text-sm transition">Back</button></div>`;
  }
  async function addSubmit() {
    const a = state.add; a.error = "";
    if (a.step === 1) {
      a.code = $("#a-code").value.trim().toUpperCase();
      if (a.code.length !== 6) { a.error = "The code has 6 characters. Please check it."; renderAdd(); return; }
      a.step = 2; renderAdd(); setTimeout(() => $("#a-name") && $("#a-name").focus(), 30);
    } else if (a.step === 2) {
      a.name = $("#a-name").value.trim(); a.label = $("#a-label").value.trim(); a.price = $("#a-price").value.trim();
      if (!a.name) { a.error = "Please give the jar a name."; renderAdd(); return; }
      if (!a.label) { a.error = "Tell us what's inside so we can order it."; renderAdd(); return; }
      a.step = 3; renderAdd();
    }
  }
  async function addDone(btn) {
    const a = state.add; btn.disabled = true; btn.textContent = "Setting up…";
    try {
      const body = { claim_code: a.code, display_name: a.name, label: a.label }; const p = numOrNull(a.price); if (p != null) body.price_inr = p;
      const strap = await api("POST", "/api/straps/claim", body);
      try { await api("POST", "/api/straps/" + encodeURIComponent(strap.device_id) + "/recalibrate"); } catch (e) { /* the strap also learns "empty" on its own at power-on */ }
      closeModal(addModal); state.add = null; toast("Jar added. It will appear in a moment."); await refresh(true); switchTab("jars");
    } catch (e) {
      if (e.message === "auth") return;
      a.error = e.message; a.step = e.status === 404 ? 1 : 3; renderAdd();
    }
  }

  /* -------------------------------------------------------------- Settings */
  const drawer = $("#settings-drawer"), overlay = $("#settings-overlay");
  function renderSettings() {
    const s = state.settings; if (!s) { drawer.innerHTML = '<div class="p-6"><div class="h-8 skeleton rounded mb-4"></div><div class="h-32 skeleton rounded"></div></div>'; return; }
    const shop = s.shop || { name: "", whatsapp_number: "", opted_in: false };
    drawer.innerHTML = `<form id="settings-form" class="flex flex-col h-full" novalidate>
      <div class="p-6 sm:p-7 space-y-6 overflow-y-auto flex-1">
        <div class="flex items-center justify-between pb-4 border-b border-[#F1F4F8]"><div><h3 class="text-2xl font-black">Settings</h3><p class="text-xs font-bold text-[#5B6776]">Simple WhatsApp ordering</p></div>${closeBtn("Close settings")}</div>
        <div class="space-y-2"><label class="block text-sm font-extrabold" for="s-owner">Your WhatsApp number</label><input id="s-owner" type="tel" class="${inputCls}" value="${esc(s.owner.whatsapp_number)}" placeholder="+91 98765 43210"><p class="text-xs font-semibold text-[#5B6776]">Your list and alerts are sent here.</p></div>
        <div class="space-y-3"><label class="block text-sm font-extrabold">Your shop</label>
          <div><label class="text-xs font-bold text-[#5B6776]" for="s-shop">Shop name</label><input id="s-shop" class="${inputCls} mt-1" value="${esc(shop.name)}" placeholder="e.g. Sharma General Store"></div>
          <div><label class="text-xs font-bold text-[#5B6776]" for="s-shopnum">Shop WhatsApp number</label><input id="s-shopnum" type="tel" class="${inputCls} mt-1" value="${esc(shop.whatsapp_number)}" placeholder="+91 98765 43210"></div>
          <label class="flex items-start gap-3 p-3 rounded-16 bg-[#F7F9FC] cursor-pointer"><input id="s-opt" type="checkbox" class="w-6 h-6 mt-0.5 accent-[#1F6FEB]" ${shop.opted_in ? "checked" : ""}><span class="text-sm font-bold">My shopkeeper agreed to receive orders on WhatsApp</span></label></div>
        <div class="space-y-3 bg-[#E7F0FD]/50 p-4 rounded-20 border border-[#E7F0FD]"><label class="block text-sm font-extrabold">Send my list when it reaches</label>
          <div class="flex items-center justify-between bg-white rounded-16 p-2 border border-[#E7F0FD]"><button type="button" data-step="-50" class="w-12 h-12 rounded-12 bg-[#F7F9FC] hover:bg-[#E7F0FD] text-[#1F6FEB] font-black text-2xl" aria-label="Decrease by 50 rupees">−</button>
            <div class="text-center"><span id="s-thr" class="text-2xl font-black">${rupees(state.threshold)}</span></div>
            <button type="button" data-step="50" class="w-12 h-12 rounded-12 bg-[#F7F9FC] hover:bg-[#E7F0FD] text-[#1F6FEB] font-black text-2xl" aria-label="Increase by 50 rupees">+</button></div></div>
        <p id="s-error" class="text-sm font-bold text-[#E5484D] min-h-[1.25rem]" role="alert"></p>
      </div>
      <div class="p-6 sm:p-7 pt-4 border-t border-[#F1F4F8] space-y-2 pb-safe"><button type="submit" class="w-full min-h-[52px] rounded-20 bg-[#1F6FEB] hover:bg-[#1858bd] text-white font-extrabold text-base transition shadow-md">Save settings</button>
        <div class="flex items-center justify-between"><button type="button" id="logout" class="min-h-[44px] px-2 text-sm font-bold text-[#5B6776] hover:text-[#17212B]">Sign out</button><a href="/admin" class="min-h-[44px] px-2 inline-flex items-center text-xs font-bold text-[#9AA4B2] hover:text-[#5B6776]">For technicians</a></div></div></form>`;
  }
  function openSettings() {
    if (state.settings) state.threshold = state.settings.owner.list_threshold_inr;
    renderSettings(); overlay.classList.remove("hidden"); drawer.classList.remove("translate-x-full"); drawer.setAttribute("aria-hidden", "false"); document.body.style.overflow = "hidden";
  }
  function closeSettings() { overlay.classList.add("hidden"); drawer.classList.add("translate-x-full"); drawer.setAttribute("aria-hidden", "true"); if (!$$("#jar-modal.flex, #add-modal.flex").length) document.body.style.overflow = ""; }
  const phone = (v) => { v = String(v || "").replace(/[\s\-()]/g, ""); if (/^\d{10}$/.test(v)) return "+91" + v; if (/^91\d{10}$/.test(v)) return "+" + v; return v; };
  async function saveSettings(form) {
    const err = $("#s-error", form); err.textContent = "";
    const owner = { whatsapp_number: phone($("#s-owner", form).value), list_threshold_inr: state.threshold };
    const shop = { name: $("#s-shop", form).value.trim() || undefined, whatsapp_number: phone($("#s-shopnum", form).value), opted_in: $("#s-opt", form).checked };
    try { state.settings = await api("PUT", "/api/settings", { owner, shop }); toast("Settings saved"); closeSettings(); await refresh(true); }
    catch (e) { if (e.message !== "auth") err.textContent = e.message; }
  }

  /* ------------------------------------------------------------ data loading */
  const sig = {};
  const changed = (k, v) => { const s = JSON.stringify(v); if (sig[k] === s) return false; sig[k] = s; return true; };
  let loading = false;
  async function refresh(force = false) {
    if (loading) return; loading = true;
    try {
      const [straps, list, orders, settings] = await Promise.all([api("GET", "/api/straps"), api("GET", "/api/list"), api("GET", "/api/orders?limit=20"), api("GET", "/api/settings")]);
      const c = [changed("straps", straps), changed("list", list), changed("orders", orders), changed("settings", settings)];
      state.straps = straps; state.list = list; state.orders = orders; state.settings = settings;
      if (!drawer.classList.contains("translate-x-full")) { /* don't disturb an open settings form */ } else if (c[3] || force) renderSettings();
      if (c[0] || c[1] || c[3] || force) renderJars();
      if (c[1] || c[2] || force) renderList();
      if (c[2] || c[0] || force) renderOrders();
      renderTabs(); renderHeader();
      if (jarModal.classList.contains("flex") && state.jarMode === "view" && c[0]) renderJarModal();
    } catch (e) { if (e.message !== "auth") renderHeader(); }
    finally { loading = false; }
  }
  async function loadItems() { try { state.items = await api("GET", "/api/items"); } catch (e) { /* optional */ } let dl = $("#item-names"); if (!dl) { dl = document.createElement("datalist"); dl.id = "item-names"; document.body.appendChild(dl); } dl.innerHTML = state.items.map((i) => `<option value="${esc(i.name)}">`).join(""); }

  /* ------------------------------------------------------------------ login */
  let timer;
  function showLogin() { clearInterval(timer); $("#app").classList.add("hidden"); $("#login").classList.remove("hidden"); setTimeout(() => $("#login-password").focus(), 30); }
  async function start() {
    $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
    switchTab((location.hash || "#jars").slice(1), false);
    renderTabs(); renderJars(); renderList(); renderOrders();
    await refresh(true); loadItems();
    clearInterval(timer); timer = setInterval(() => { if (!document.hidden) refresh(); }, 5000);
  }

  /* ------------------------------------------------------------ interactions */
  document.addEventListener("click", async (e) => {
    const t = e.target;
    const tab = t.closest("[data-tab]"); if (tab) return switchTab(tab.dataset.tab);
    const filt = t.closest("[data-filter]"); if (filt) { state.filter = filt.dataset.filter; return renderJars(); }
    if (t.closest("[data-add]")) return openAdd();
    const jar = t.closest("[data-jar]"); if (jar) return openJar(jar.dataset.jar);
    if (t.closest("#open-settings")) return openSettings();
    if (t === overlay) return closeSettings();
    if (t.closest("[data-close]")) { const m = t.closest("#jar-modal, #add-modal"); if (m) { closeModal(m); if (m === addModal) state.add = null; } else closeSettings(); return; }
    if (t === jarModal) return closeModal(jarModal);
    if (t === addModal) { closeModal(addModal); state.add = null; return; }
    const mode = t.closest("[data-jar-mode]"); if (mode) { state.jarMode = mode.dataset.jarMode; return renderJarModal(); }
    const step = t.closest("[data-step]"); if (step) { state.threshold = Math.max(50, state.threshold + parseInt(step.dataset.step, 10)); $("#s-thr").textContent = rupees(state.threshold); return; }
    if (t.closest("#logout")) { await api("POST", "/api/logout").catch(() => {}); closeSettings(); showLogin(); return; }
    if (t.closest("[data-add-back]")) { state.add.step -= 1; state.add.error = ""; return renderAdd(); }
    const done = t.closest("[data-add-done]"); if (done) return addDone(done);
    const go = t.closest("[data-recal-go]");
    if (go) {
      const cur = strapById(state.openJar), online = !!cur && (cur.status === "OK" || cur.status === "LOW");
      go.disabled = true;
      try {
        await api("POST", "/api/straps/" + encodeURIComponent(state.openJar) + "/recalibrate");  // the backend keeps it until the strap reports in
        if (online) { toast("Started. Keep the jar empty for a few minutes."); state.jarMode = "view"; }
        else state.jarMode = "recal-wait";
        renderJarModal();
      } catch (er) { if (er.message !== "auth") toast(er.message, "err"); go.disabled = false; }
      return;
    }
    if (t.closest("[data-remove-jar]")) {
      const b = t.closest("[data-remove-jar]");
      if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Tap again to remove this jar for good"; b.classList.add("text-[#E5484D]"); return; }
      try { await api("DELETE", "/api/straps/" + encodeURIComponent(state.openJar)); closeModal(jarModal); toast("Jar removed"); await refresh(true); } catch (er) { if (er.message !== "auth") toast(er.message, "err"); } return;
    }
    const rm = t.closest("[data-remove-row]");
    if (rm) { try { await api("DELETE", "/api/list/items/" + rm.dataset.removeRow); toast("Removed from your list"); await refresh(true); } catch (er) { if (er.message !== "auth") toast(er.message, "err"); } return; }
    const send = t.closest("#send-list");
    if (send) {
      send.disabled = true; const lbl = send.querySelector("span"); lbl.textContent = "Sending…";
      try { const o = await api("POST", "/api/list/send"); if (o.status === "send_failed") toast("We couldn't send it: " + (o.last_error || "please try again"), "err"); else { toast("Sent! Check your WhatsApp."); switchTab("orders"); } await refresh(true); }
      catch (er) { if (er.message !== "auth") toast(er.message, "err"); send.disabled = false; lbl.textContent = "Send to my WhatsApp"; }
      return;
    }
    const retry = t.closest("[data-order-retry]");
    if (retry) { retry.disabled = true; try { const o = await api("POST", "/api/orders/" + retry.dataset.orderRetry + "/retry"); toast(o.status === "send_failed" ? "Still couldn't send: " + (o.last_error || "") : "Sent!", o.status === "send_failed" ? "err" : "ok"); await refresh(true); } catch (er) { if (er.message !== "auth") toast(er.message, "err"); retry.disabled = false; } return; }
    const cancel = t.closest("[data-order-cancel]");
    if (cancel) { if (cancel.dataset.sure !== "1") { cancel.dataset.sure = "1"; cancel.textContent = "Tap again to cancel"; cancel.classList.add("text-[#E5484D]"); return; } try { await api("POST", "/api/orders/" + cancel.dataset.orderCancel + "/cancel"); toast("Order cancelled. The items are back on your list."); await refresh(true); } catch (er) { if (er.message !== "auth") toast(er.message, "err"); } return; }
  });

  document.addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    if (f.id === "login-form") {
      const err = $("#login-error"); err.textContent = "";
      api("POST", "/api/login", { password: $("#login-password").value }).then(() => { $("#login-password").value = ""; start(); }).catch((er) => { err.textContent = er.message; });
    } else if (f.id === "edit-form") saveEdit(f);
    else if (f.id === "add-form") addSubmit();
    else if (f.id === "settings-form") saveSettings(f);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { if (jarModal.classList.contains("flex")) closeModal(jarModal); else if (addModal.classList.contains("flex")) { closeModal(addModal); state.add = null; } else closeSettings(); }
    if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("[data-jar]")) { e.preventDefault(); openJar(e.target.dataset.jar); }
  });
  document.addEventListener("input", (e) => {
    if (e.target.id === "a-code") e.target.value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (e.target.id === "e-label" || e.target.id === "a-label") {  // known item: fill its usual price
      const it = state.items.find((i) => i.name.toLowerCase() === e.target.value.trim().toLowerCase());
      const price = $(e.target.id === "e-label" ? "#e-price" : "#a-price");
      if (it && it.price_inr != null && price && !price.value) price.value = it.price_inr;
    }
  });
  window.addEventListener("hashchange", () => switchTab((location.hash || "#jars").slice(1), false));
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("#app").classList.contains("hidden")) refresh(); });

  /* ------------------------------------------------------------------- boot */
  (async () => {
    try { const me = await fetch("/api/me", { cache: "no-store" }).then((r) => r.json()); me.authenticated ? start() : showLogin(); }
    catch (e) { showLogin(); }
  })();
})();
