// Inject our real logic into the page context (so we can hook fetch/XHR/WebSocket)
(function inject() {
  const s = document.createElement("script");
  s.src = chrome.runtime.getURL("injected.js");
  s.type = "text/javascript";
  document.documentElement.appendChild(s);
  s.remove();
})();
