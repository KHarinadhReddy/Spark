const base = import.meta.env.VITE_API_BASE || "";
const TOKEN_KEY = "spark.ownerToken";

export function getOwnerToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setOwnerToken(token) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // private mode — the token only lives for this page load
  }
}

function headers(extra = {}) {
  const token = getOwnerToken();
  return {
    ...extra,
    ...(token ? { "x-spark-token": token } : {}),
  };
}

async function parse(response) {
  const type = response.headers.get("content-type") || "";
  const body = type.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const detail =
      body && typeof body === "object" ? body.detail || body.message : body;
    const error = new Error(detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return body;
}

export const api = {
  get(path) {
    return fetch(base + path, { headers: headers() }).then(parse);
  },
  post(path, payload) {
    return fetch(base + path, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: payload === undefined ? undefined : JSON.stringify(payload),
    }).then(parse);
  },
  put(path, payload) {
    return fetch(base + path, {
      method: "PUT",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    }).then(parse);
  },
  delete(path) {
    return fetch(base + path, {
      method: "DELETE",
      headers: headers(),
    }).then(parse);
  },
  async tts(text, language) {
    const response = await fetch(base + "/api/voice/tts", {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text, language }),
    });
    if (!response.ok) throw new Error("TTS unavailable");
    return response.blob();
  },
  async stt(blob, language = "") {
    const query = language ? `?language=${encodeURIComponent(language)}` : "";
    const response = await fetch(base + `/api/voice/stt${query}`, {
      method: "POST",
      headers: headers({ "Content-Type": blob.type || "audio/webm" }),
      body: blob,
    });
    return parse(response);
  },
  async *streamChat(payload) {
    const token = getOwnerToken();
    const response = await fetch(base + "/api/chat/stream", {
      method: "POST",
      headers: {
        ...(token ? { "x-spark-token": token } : {}),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const type = response.headers.get("content-type") || "";
      const body = type.includes("application/json") ? await response.json() : await response.text();
      const detail = body && typeof body === "object" ? body.detail || body.message : body;
      throw new Error(detail || `Stream failed (${response.status})`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalReply = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";
      for (const raw of events) {
        const line = (raw || "").trim();
        if (!line.startsWith("data: ")) continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (data.text) yield data.text;
          if (data.reply) finalReply = data.reply;
        } catch {
          // ignore malformed keep-alive chunks
        }
      }
    }
    if (finalReply) yield finalReply;
  },
};
