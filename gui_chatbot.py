# gui_chatbot.py — offline, no external links
from __future__ import annotations

import os
import re
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QLineEdit, QPushButton
)
from PySide6.QtGui import QKeySequence, QShortcut

from rag_index import LocalRAG
from config_qt import TIER_LIMITS  # for accurate bin caps

HELP_SNIPPETS = {
    "bin assignments": (
        "Bin Assignments:\n"
        "- Type a username and qty, click Add Bidder (or Ctrl+B).\n"
        "- Use Auto-capture to pull winners from the Bridge.\n"
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
            "border-radius:8px;padding:10px;}")
        self.view.append(self._hello())

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
    def _hello(self) -> str:
        return (
            "<b>Hi! Ask anything about SwiftSale. I answer from the built-in guide.</b><br>"
       )

    def _say(self, role: str, msg: str):
        label = "You" if role == "user" else "Assistant"
        self.view.append(f"<p><b>{label}:</b><br>{self._escape(msg)}</p>")

    def _escape(self, s: str) -> str:
        return (s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                  .replace("\n","<br>"))

    def _render_results(self, chunks):
        if not chunks:
            self._say("bot", "No results found in the local guide.")
            return

        html_parts = []
        for i, ch in enumerate(chunks, start=1):
            text = ch.text.strip()
            if len(text) > 900:
                text = text[:900].rstrip() + "…"

            # NOTE: No escaping — we trust our local guide/snippets
            html_parts.append(f"""
                <div style="margin:10px 0;padding:12px;
                            border:1px solid #2a2d31;
                            border-radius:8px;
                            background-color:#181a1f;">
                    <div style="font-weight:600;margin-bottom:8px;
                                color:#f5f6f7;">
                        {ch.title} — Match {i}
                    </div>
                    <div style="white-space:pre-wrap;color:#d3d7de;
                                line-height:1.4;">
                        {text}
                    </div>
                </div>
            """)

        self.view.insertHtml("<br>".join(html_parts))
        self.view.insertHtml("<br>")  # extra spacing after results

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

        # Default: just search the guide
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
            max_bins = TIER_LIMITS.get(self.host.tier, {}).get("bins", 20)
        except Exception:
            bins_used, max_bins = 0, 20
        self._say("bot", f"Bins used: {bins_used}/{max_bins} (Tier: {self.host.tier})")

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
            bridge = f"{'ON' if self.host.bridge_enabled else 'OFF'} ({self.host.bridge_mode})"
            self._say("bot", f"Tier: {self.host.tier}\nInstall ID: {self.host.install_id}\nBridge: {bridge}")
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
        try:
            results = self.rag.search(query, top_k=3)
            self._render_results(results)
        except Exception as e:
            self._say("bot", f"Search error: {e}")
