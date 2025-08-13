(() => {
  // ===========================
  // CONFIG — set these once
  // ===========================
  // You can override without rebuilding by setting in DevTools console:
  //   localStorage.setItem('swiftsale_api_base','http://127.0.0.1:10000')
  //   localStorage.setItem('swiftsale_bridge_secret','YOUR_SECRET')
  const API_BASE = localStorage.getItem('swiftsale_api_base') || "http://127.0.0.1:10000";
  const BRIDGE_SECRET = localStorage.getItem('swiftsale_bridge_secret') || "<PUT_YOUR_BRIDGE_SECRET_HERE>";
  const SOURCE = "chrome_ext";
  const DEDUP_TTL_MS = 5000;

  if (!BRIDGE_SECRET || BRIDGE_SECRET.includes("PUT_YOUR")) {
    console.warn("[SwiftSale] Set your bridge secret: localStorage.setItem('swiftsale_bridge_secret','YOUR_SECRET')");
  }

  // ===========================
  // Utils
  // ===========================
  const recent = new Map(); // key -> ts
  function dedup(username, lotId) {
    const key = `${username}|${lotId || ""}`;
    const now = Date.now();
    for (const [k, ts] of recent) if (now - ts > DEDUP_TTL_MS) recent.delete(k);
    if (recent.has(key)) return true;
    recent.set(key, now);
    return false;
  }

  const HANDLE_RE = /@[A-Za-z0-9_.-]{2,30}/;
  function extractHandle(s) {
    if (typeof s !== "string") return null;
    const m = s.match(HANDLE_RE);
    return m ? m[0] : null;
  }
  function scanObjectForHandle(obj) {
    try { return extractHandle(JSON.stringify(obj)); } catch { return null; }
  }

  async function postWinner(payload) {
    // payload: { username, lot_id?, confidence?, ts? }
    if (!payload || !payload.username || !payload.username.startsWith("@")) return;
    if (dedup(payload.username, payload.lot_id)) return;

    const body = JSON.stringify({
      username: payload.username,
      lot_id: payload.lot_id ?? null,
      source: SOURCE,
      confidence: typeof payload.confidence === "number" ? payload.confidence : 0.95,
      ts: payload.ts || Date.now()
    });

    try {
      const res = await fetch(`${API_BASE}/won`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Bridge-Secret": BRIDGE_SECRET
        },
        body
      });
      if (!res.ok) {
        const txt = await res.text().catch(()=>"");
        console.warn("[SwiftSale] /won failed", res.status, txt);
      }
    } catch (e) {
      console.warn("[SwiftSale] /won network error", e);
    }
  }

  function normalizeHandle(h) {
    if (!h) return null;
    return h.startsWith("@") ? h : `@${h}`;
  }

  // ===========================
  // Capture Strategy A: fetch()
  // ===========================
  (function hookFetch() {
    const origFetch = window.fetch;
    window.fetch = async (...args) => {
      const resp = await origFetch(...args);
      try {
        const clone = resp.clone();
        const ct = (clone.headers.get("content-type") || "").toLowerCase();
        if (ct.includes("application/json")) {
          clone.json().then(json => {
            const uname =
              json?.winner?.username ||
              json?.buyer?.username ||
              scanObjectForHandle(json);

            const lotId = json?.auction_id || json?.lot_id || json?.item_id || null;
            const handle = normalizeHandle(uname);
            if (handle) postWinner({ username: handle, lot_id: lotId, confidence: 0.98 });
          }).catch(()=>{});
        }
      } catch {}
      return resp;
    };
  })();

  // ===========================
  // Capture Strategy B: XHR
  // ===========================
  (function hookXHR() {
    const XHR = window.XMLHttpRequest;
    const open = XHR.prototype.open;
    const send = XHR.prototype.send;

    XHR.prototype.open = function(...a) {
      this._sw_url = a[1];
      return open.apply(this, a);
    };

    XHR.prototype.send = function(...a) {
      this.addEventListener("load", function() {
        try {
          const ct = (this.getResponseHeader("content-type") || "").toLowerCase();
          if (ct.includes("application/json") && this.responseText) {
            const j = JSON.parse(this.responseText);
            const uname =
              j?.winner?.username ||
              j?.buyer?.username ||
              scanObjectForHandle(j);
            const lotId = j?.auction_id || j?.lot_id || j?.item_id || null;
            const handle = normalizeHandle(uname);
            if (handle) postWinner({ username: handle, lot_id: lotId, confidence: 0.98 });
          }
        } catch {}
      });
      return send.apply(this, a);
    };
  })();

  // ===========================
  // Capture Strategy C: WebSocket
  // ===========================
  (function hookWebSocket() {
    const OrigWS = window.WebSocket;
    function WrappedWS(url, protocols) {
      const ws = protocols ? new OrigWS(url, protocols) : new OrigWS(url);
      try {
        ws.addEventListener("message", (ev) => {
          const data = ev?.data;
          if (!data) return;
          // Try JSON parse then fallback to plain text scan
          try {
            const parsed = typeof data === "string" ? JSON.parse(data) : null;
            if (parsed) {
              const uname =
                parsed?.winner?.username ||
                parsed?.buyer?.username ||
                scanObjectForHandle(parsed);
              const lotId = parsed?.auction_id || parsed?.lot_id || parsed?.item_id || null;
              const handle = normalizeHandle(uname);
              if (handle) postWinner({ username: handle, lot_id: lotId, confidence: 0.99 });
              return;
            }
          } catch {}
          if (typeof data === "string") {
            const handle = extractHandle(data);
            if (handle) postWinner({ username: handle, confidence: 0.9 });
          }
        });
      } catch {}
      return ws;
    }
    WrappedWS.prototype = OrigWS.prototype;
    Object.defineProperty(WrappedWS, 'CONNECTING', { get: () => OrigWS.CONNECTING });
    Object.defineProperty(WrappedWS, 'OPEN',       { get: () => OrigWS.OPEN });
    Object.defineProperty(WrappedWS, 'CLOSING',    { get: () => OrigWS.CLOSING });
    Object.defineProperty(WrappedWS, 'CLOSED',     { get: () => OrigWS.CLOSED });
    window.WebSocket = WrappedWS;
  })();

  // ===========================
  // Capture Strategy D: DOM fallback
  // ===========================
  (function observeDOM() {
    const obs = new MutationObserver((muts) => {
      for (const m of muts) for (const node of m.addedNodes || []) {
        try {
          const txt = node?.textContent || "";
          if (!txt) continue;
          if (/Winner|won|Purchased by|High bidder|Buyer/i.test(txt)) {
            const handle = extractHandle(txt);
            if (handle) {
              // try closest lot id from attributes if present
              let lotId = null;
              if (node.nodeType === 1) {
                const el = /** @type {HTMLElement} */(node);
                lotId = el.getAttribute?.("data-auction-id") || el.getAttribute?.("data-lot-id");
              }
              postWinner({ username: handle, lot_id: lotId, confidence: 0.9 });
            }
          }
        } catch {}
      }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true });
  })();

  // ===========================
  // Manual fallback: Shift+W
  // ===========================
  window.addEventListener("keydown", (e) => {
    if (e.shiftKey && e.key.toLowerCase() === "w") {
      e.preventDefault();
      const sel = (window.getSelection()?.toString() || "").trim();
      let handle = extractHandle(sel);
      if (!handle) {
        const input = prompt("Send winner to SwiftSale (enter @username):", "@");
        if (!input) return;
        handle = input.startsWith("@") ? input : "@"+input;
      }
      postWinner({ username: handle, confidence: 0.7 });
    }
  });

  console.log("[SwiftSale] Winner capturer loaded (fetch/XHR/WebSocket/DOM).");
})();
