# gui_chatbot.py — offline, clean rendering (no external links)
from __future__ import annotations

import os
import re
from typing import List, Tuple
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QLineEdit, QPushButton
)
from PySide6.QtGui import QKeySequence, QShortcut

from rag_index import LocalRAG
from config_qt import TIER_LIMITS, DEFAULT_TRIAL_EMAIL  # for accurate bin caps

# ----------------------------
# Quick knowledge snippets
# ----------------------------
HELP_SNIPPETS = {
    "bin assignments": (
        "Bin Assignments:\n"
        "- Type a username and qty, click Add Bidder (or Ctrl+B).\n"
        "- Auto-capture pulls winners from the Bridge when ON.\n"
        "- 'Bins Used' shows usage vs. your tier limit.\n"
        "Try: /bins, /top, or 'how do I auto capture' "
    ),
    "auto capture": (
        "Auto Capture:\n"
        "- Toggle with the status bar checkbox or Ctrl+Shift+K.\n"
        "- Bridge must be ON (Ctrl+Shift+J)."
    ),
    "annotate labels": (
        "Annotate Labels:\n"
        "- Go to Annotate tab.\n"
        "- Pick your Whatnot PDF, adjust X/Y offset, click Annotate.\n"
        "Offsets are in inches (default X=0.40, Y=5.40)."
    ),
    "promo code": (
        "Promo Codes:\n"
        "- Press Ctrl+Alt+D to open 'Enter Promo Code'."
    ),
    "giveaway": (
        "Giveaway:\n"
        "- Use 'Start Giveaway' in the main UI.\n"
        "- Customize text in Settings → Messages."
    ),
}

# ----------------------------
# Commands / intents
# ----------------------------
INTENTS = [
    (r"^\s*/bins\s*$", "intent_bins"),
    (r"^\s*/top\s*$", "intent_top"),
    (r"^\s*/sticky\s*$", "intent_sticky"),
    (r"^\s*/bridge\s+(on|off)\s*$", "intent_bridge_toggle"),
    (r"^\s*/mode\s+(auto|manual)\s*$", "intent_mode"),
    (r"^\s*/status\s*$", "intent_status"),
    (r"^\s*/promo\s*$", "intent_promo"),
    (r"^\s*/help\s*$", "intent_help"),
    (r"^\s*/find\s+(.+)$", "intent_find"),  # force search
]

# ----------------------------
# Sanitizers / formatters
# ----------------------------
_STYLE_BLOCK_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_SCRIPT_BLOCK_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_LONG_INDENT_BLOCK_RE = re.compile(r"(?:^|\n)(?:\s{4,}.*\n){3,}")  # large indented dumps
_WS_LINES_RE = re.compile(r"[ \t]{2,}")
_EMPTY_LINES_RE = re.compile(r"\n{3,}")

def _sanitize(raw: str) -> str:
    """Strip CSS/JS/HTML and heavy code blobs, normalize whitespace."""
    if not raw:
        return ""
    s = _STYLE_BLOCK_RE.sub("", raw)
    s = _SCRIPT_BLOCK_RE.sub("", s)
    s = _CODE_FENCE_RE.sub("", s)
    s = _LONG_INDENT_BLOCK_RE.sub("\n", s)
    if "<" in s and ">" in s:
        s = _TAG_RE.sub("", s)
    s = s.replace("\r", "")
    s = _WS_LINES_RE.sub(" ", s)
    s = _EMPTY_LINES_RE.sub("\n\n", s)
    # clip very long lines
    lines = []
    for line in s.split("\n"):
        line = line.strip()
        if len(line) > 800:
            line = line[:800] + "…"
        if line:
            lines.append(line)
    return "\n".join(lines).strip()

def _first_n_lines(text: str, n: int = 8) -> str:
    out: List[str] = []
    for i, line in enumerate(text.splitlines()):
        if i >= n:
            out.append("…")
            break
        out.append(line)
    return "\n".join(out)

def _html_escape(s: str) -> str:
    return (s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
              .replace("\n","<br>"))

def _lead_for_query(q: str, *, tier: str, bins_used: int | None = None, bins_cap: int | None = None) -> str:
    ql = q.lower().strip()
    if any(w in ql for w in ("install", "installer", "setup")):
        return "Install SwiftSale, launch it, enter your email, and your install ID will sync automatically."
    if any(w in ql for w in ("promo", "code", "unlock")):
        return "Press Ctrl+Alt+D to open **Enter Promo Code**, paste your code, and your tier updates instantly."
    if "bin" in ql:
        if bins_used is not None and bins_cap is not None:
            return f"Bin usage: {bins_used}/{bins_cap} on the **{tier}** tier. Use Add Bidder or Auto-capture during the show."
        return f"Use Add Bidder or Auto-capture; SwiftSale assigns bins automatically on the **{tier}** tier."
    if any(w in ql for w in ("auto capture", "autocapture", "bridge")):
        return "Turn the Bridge ON (Ctrl+Shift+J) and set mode to Auto (Ctrl+Shift+K) to capture winners automatically."
    if any(w in ql for w in ("annotate", "label", "labels")):
        return "Open the Annotate tab, pick your Whatnot PDF, adjust X/Y offsets, then click Annotate."
    return "Here’s the most relevant info from the built-in guide:"

# ----------------------------
# Dialog
# ----------------------------
class AssistantDialog(QDialog):
    """
    In-app helper with local RAG over your guide.html (no network/links).
    Commands:
      /bins, /top, /sticky, /bridge on|off, /mode auto|manual, /status, /promo, /help, /find <query>
    Natural questions auto-search the local guide.
    """
    def __init__(self, host, parent=None, guide_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("SwiftSale Assistant")
        self.setModal(False)
        self.resize(640, 560)
        self.host = host

        # UI
        vbox = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setStyleSheet(
            "QTextBrowser{background:#101214;color:#eaeef3;border:1px solid #202225;"
            "border-radius:8px;padding:10px;}"
        )
        self.view.append("<b>Ask anything about SwiftSale. I’ll keep answers concise and show short matches below.</b><br>")

        hbox = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask a question or type /help, /find annotate labels …")
        self.send_btn = QPushButton("Send")
        self.send_btn.setDefault(True)
        hbox.addWidget(self.input)
        hbox.addWidget(self.send_btn)

        vbox.addWidget(self.view)
        vbox.addLayout(hbox)

        self.send_btn.clicked.connect(self._on_send)
        self.input.returnPressed.connect(self._on_send)
        QShortcut(QKeySequence("Ctrl+I"), self, lambda: self.input.setFocus())

        # Build local RAG
        self.rag = LocalRAG()
        if guide_path and os.path.exists(guide_path):
            # Larger chunks are nicer since we’re not linking out
            self.rag.add_file(guide_path, title="SwiftSale Guide", url=None, max_chars=900)
        # Seed helpful snippets
        for title, text in [
            ("Bin Assignments", HELP_SNIPPETS["bin assignments"]),
            ("Auto Capture", HELP_SNIPPETS["auto capture"]),
            ("Annotate Labels", HELP_SNIPPETS["annotate labels"]),
            ("Promo Codes", HELP_SNIPPETS["promo code"]),
            ("Giveaway", HELP_SNIPPETS["giveaway"]),
        ]:
            self.rag.add_snippet(title, text, url=None)
        self.rag.build()

    # ---- UX helpers ---------------------------------------------------------
    def _say(self, role: str, msg: str):
        label = "You" if role == "user" else "Answer"
        self.view.append(f"<p><b>{label}:</b><br>{_html_escape(msg)}</p>")

    def _render_results(self, chunks: List):
        if not chunks:
            self._say("bot", "No results found in the local guide.")
            return

        cards = []
        for i, ch in enumerate(chunks, start=1):
            clean = _sanitize(ch.text)
            preview = _first_n_lines(clean, 8)
            title = f"{ch.title} — Match {i}"
            cards.append(
                "<div style='margin:10px 0;padding:12px;"
                "border:1px solid #2a2d31;border-radius:8px;background:#181a1f;'>"
                f"<div style='font-weight:600;margin-bottom:8px;color:#f5f6f7;'>{_html_escape(title)}</div>"
                f"<div style='white-space:pre-wrap;color:#d3d7de;line-height:1.4;'>{_html_escape(preview)}</div>"
                "</div>"
            )
        self.view.insertHtml("<br>".join(cards))
        self.view.insertHtml("<br>")

    # ---- Send ---------------------------------------------------------------
    def _on_send(self):
        text = (self.input.text() or "").strip()
        if not text:
            return
        self._say("user", text)
        self.input.clear()

        # Commands first
        for pattern, handler_name in INTENTS:
            m = re.match(pattern, text, flags=re.I)
            if m:
                try:
                    getattr(self, handler_name)(*m.groups())
                except Exception as e:
                    self._say("bot", f"Error: {e}")
                return

        # Default: search and summarise
        return self.intent_find(text)

    # ---- Commands -----------------------------------------------------------
    def intent_help(self):
        self._say("bot",
                  "Commands:\n"
                  "/bins — show bin usage\n"
                  "/top — show top buyers\n"
                  "/sticky — apply sticky winner\n"
                  "/bridge on|off — toggle bridge power\n"
                  "/mode auto|manual — set capture mode\n"
                  "/status — bridge + tier status\n"
                  "/promo — open 'Enter Promo Code' dialog\n"
                  "/find <query> — search the built-in guide\n")

    def intent_bins(self):
        try:
            bins_used = self.host.bidder_manager.count_total_bins_assigned()
            tier = getattr(self.host, "tier", "Starter")
            max_bins = TIER_LIMITS.get(tier, {}).get("bins", 20)
        except Exception:
            bins_used, max_bins, tier = 0, 20, "Starter"
        self._say("bot", f"Bins used: {bins_used}/{max_bins} (Tier: {tier})")

    def intent_top(self):
        try:
            tops = self.host.bidder_manager.get_top_buyers() or []
            if not tops:
                return self._say("bot", "No top buyers yet.")
            self._say("bot", "Top buyers: " + ", ".join(f"{n} ({c})" for n, c in tops))
        except Exception as e:
            self._say("bot", f"Failed to get top buyers: {e}")

    def intent_sticky(self):
        try:
            code = self.host.bidder_manager.apply_sticky_to_username()
            if code:
                self.host.refresh_bin_usage_display()
                self.host.update_latest_bidder_display()
                self._say("bot", f"Applied sticky → Bin {code}")
            else:
                self._say("bot", "No sticky winner available.")
        except Exception as e:
            self._say("bot", f"Sticky failed: {e}")

    def intent_bridge_toggle(self, onoff: str):
        try:
            want = onoff.lower() == "on"
            if bool(self.host.bridge_enabled) == want:
                return self._say("bot", f"Bridge already {'ON' if want else 'OFF'}.")
            self.host.toggle_bridge_enabled()
            self._say("bot", f"Bridge now {'ENABLED' if self.host.bridge_enabled else 'DISABLED'}.")
        except Exception as e:
            self._say("bot", f"Bridge toggle failed: {e}")

    def intent_mode(self, mode: str):
        try:
            want = mode.lower()
            if want not in ("auto", "manual"):
                return self._say("bot", "Mode must be 'auto' or 'manual'.")
            if self.host.bridge_mode.lower() != want:
                self.host.toggle_bridge_mode()
            self._say("bot", f"Capture mode: {self.host.bridge_mode.upper()}")
        except Exception as e:
            self._say("bot", f"Mode change failed: {e}")

    def intent_status(self):
        try:
            tier = getattr(self.host, "tier", "Starter")
            bridge = f"{'ON' if self.host.bridge_enabled else 'OFF'} ({self.host.bridge_mode})"
            install_id = getattr(self.host, "install_id", "unknown")
            self._say("bot", f"Tier: {tier}\nInstall ID: {install_id}\nBridge: {bridge}")
        except Exception as e:
            self._say("bot", f"Status error: {e}")

    def intent_promo(self):
        try:
            if hasattr(self.host, "open_dev_code_dialog"):
                self.host.open_dev_code_dialog()
                self._say("bot", "Opened 'Enter Promo Code' dialog.")
            else:
                self._say("bot", "Promo dialog not available in this build.")
        except Exception as e:
            self._say("bot", f"Promo dialog failed: {e}")

    def intent_find(self, query: str):
        """Search guide, show a concise lead + clean matches."""
        try:
            # Prepare lead
            try:
                tier = getattr(self.host, "tier", "Starter")
                bins_used = self.host.bidder_manager.count_total_bins_assigned()
                bins_cap = TIER_LIMITS.get(tier, {}).get("bins", 20)
            except Exception:
                tier, bins_used, bins_cap = "Starter", None, None

            lead = _lead_for_query(query, tier=tier, bins_used=bins_used, bins_cap=bins_cap)
            self._say("bot", lead)

            # Search local guide
            results = self.rag.search(query, top_k=3)
            # Sanitize and render concise matches
            self._render_results(results)
        except Exception as e:
            self._say("bot", f"Search error: {e}")
