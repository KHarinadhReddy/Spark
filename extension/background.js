// Spark Form Filler — service worker.
// All backend calls happen here so the popup never needs CORS exceptions.

const DEFAULTS = {
  backendUrl: "http://localhost:8000",
  token: "",
};

async function getSettings() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  return { ...DEFAULTS, ...stored };
}

async function apiFetch(path, options = {}) {
  const { backendUrl, token } = await getSettings();
  const base = (backendUrl || DEFAULTS.backendUrl).replace(/\/+$/, "");
  const response = await fetch(`${base}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "x-spark-token": token } : {}),
      ...(options.headers || {}),
    },
  });
  const type = response.headers.get("content-type") || "";
  const body = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = body && typeof body === "object" ? body.detail || body.message : body;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return body;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    try {
      if (message.type === "settings:get") {
        sendResponse({ ok: true, settings: await getSettings() });
        return;
      }
      if (message.type === "settings:set") {
        await chrome.storage.local.set({
          backendUrl: String(message.backendUrl || DEFAULTS.backendUrl).trim(),
          token: String(message.token || "").trim(),
        });
        sendResponse({ ok: true });
        return;
      }
      if (message.type === "api:health") {
        // /api/config is owner-protected, so this also verifies the token.
        sendResponse({ ok: true, data: await apiFetch("/api/config") });
        return;
      }
      if (message.type === "api:analyze") {
        sendResponse({
          ok: true,
          data: await apiFetch("/api/forms/analyze", {
            method: "POST",
            body: JSON.stringify(message.payload),
          }),
        });
        return;
      }
      if (message.type === "api:submit") {
        sendResponse({
          ok: true,
          data: await apiFetch("/api/forms/submit", {
            method: "POST",
            body: JSON.stringify({ ...message.payload, approved: true }),
          }),
        });
        return;
      }
      sendResponse({ ok: false, error: `Unknown message: ${message.type}` });
    } catch (error) {
      sendResponse({ ok: false, error: error.message || String(error) });
    }
  })();
  return true;
});
