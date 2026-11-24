const base = import.meta.env.VITE_API_BASE || "";

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
    return fetch(base + path).then(parse);
  },
  post(path, payload) {
    return fetch(base + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    }).then(parse);
  },
  async tts(text, language) {
    const response = await fetch(base + "/api/voice/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language }),
    });
    if (!response.ok) throw new Error("TTS unavailable");
    return response.blob();
  },
  async stt(blob) {
    const response = await fetch(base + "/api/voice/stt", {
      method: "POST",
      headers: { "Content-Type": blob.type || "audio/webm" },
      body: blob,
    });
    return parse(response);
  },
};
