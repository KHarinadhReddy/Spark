// Spark Form Filler — popup controller.

const $ = (id) => document.getElementById(id);

const state = {
  tab: null,
  scan: null,
  analysis: null,
  filled: 0,
  submitted: false,
};

const SKIP = new Set(["password", "hidden", "file", "submit", "button", "reset", "image"]);
const SENSITIVE = /(password|passcode|otp|one[- ]time|captcha|cvv|card number|debit|credit|pin\b|aadhaar|pan\b|bank account|ifsc|upi)/i;

function background(type, payload = {}) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type, ...payload }, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response || { ok: false, error: "No response from the extension worker" });
    });
  });
}

function setStatus(text, tone = "") {
  const node = $("status");
  node.textContent = text;
  node.className = `status ${tone}`.trim();
}

function setError(text) {
  const node = $("error");
  node.textContent = text || "";
  node.hidden = !text;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab || null;
}

async function ensureContent(tabId) {
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    return true;
  } catch (error) {
    setError(`This page cannot be read by the extension: ${error.message}`);
    return false;
  }
}

function sendTab(tabId, message) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response || { ok: false, error: "The page did not respond" });
    });
  });
}

async function scanPage() {
  const tab = state.tab;
  if (!tab?.id) throw new Error("No active tab");
  if (/^(chrome|edge|about|devtools):/i.test(tab.url || "")) {
    throw new Error("Open a normal website first — browser pages cannot be filled.");
  }
  if (!(await ensureContent(tab.id))) throw new Error("The page could not be read.");
  const response = await sendTab(tab.id, { type: "spark:scan" });
  if (!response.ok) throw new Error(response.error || "Scan failed");
  return response.data;
}

function isManual(field) {
  return (
    SKIP.has(String(field.type || "").toLowerCase()) ||
    SENSITIVE.test(`${field.label || ""} ${field.name || ""}`)
  );
}

function editorFor(field, index) {
  const type = String(field.type || "text").toLowerCase();
  if (type === "select" && Array.isArray(field.options) && field.options.length) {
    const select = document.createElement("select");
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "— choose —";
    select.append(blank);
    field.options.forEach((option) => {
      const node = document.createElement("option");
      node.value = option;
      node.textContent = option;
      select.append(node);
    });
    select.value = field.value || "";
    select.dataset.index = String(index);
    return select;
  }
  if (type === "checkbox" || type === "radio") {
    const row = document.createElement("label");
    row.className = "check-row";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.index = String(index);
    input.checked = /^(yes|true|1|on|checked)$/i.test(String(field.value || ""));
    row.append(input, document.createTextNode(field.label || "Yes"));
    return row;
  }
  if (type === "textarea") {
    const textarea = document.createElement("textarea");
    textarea.rows = 3;
    textarea.value = field.value || "";
    textarea.dataset.index = String(index);
    return textarea;
  }
  const input = document.createElement("input");
  input.type = "text";
  input.value = field.value || "";
  input.dataset.index = String(index);
  input.placeholder = field.placeholder || "";
  return input;
}

function renderFields() {
  const container = $("fields");
  container.innerHTML = "";
  const fields = state.analysis?.fields || [];
  let count = 0;
  fields.forEach((field, index) => {
    const manual = isManual(field);
    if (!manual) count += 1;
    const card = document.createElement("div");
    card.className = `field ${manual ? "manual" : ""}`;

    const label = document.createElement("label");
    label.className = "field-label";
    const title = document.createElement("span");
    title.textContent = field.label || field.name || `Field ${index + 1}`;
    const kind = document.createElement("em");
    kind.textContent = manual ? "manual" : field.type || "text";
    label.append(title, kind);

    if (manual) {
      const note = document.createElement("span");
      note.className = "manual-note";
      note.textContent =
        field.type === "file"
          ? "Upload this yourself — Spark never attaches files."
          : "Sensitive field — Spark never fills this.";
      card.append(label, note);
    } else {
      const editor = editorFor(field, index);
      editor.id = `field-${index}`;
      card.append(label, editor);
      if (field.reason) {
        const reason = document.createElement("span");
        reason.className = "reason";
        reason.textContent = field.filled
          ? field.reason
          : "No saved profile value — add one here or in Spark Settings.";
        card.append(reason);
      }
    }
    container.append(card);
  });

  $("field-count").textContent = `${count} fillable`;
  $("gate").hidden = count === 0;
  if (count === 0) {
    setStatus("No fillable fields were found on this page.", "warn");
  }
}

function collectValues() {
  const fields = state.analysis?.fields || [];
  const values = [];
  const missing = [];
  fields.forEach((field, index) => {
    if (isManual(field)) return;
    const editor = $(`field-${index}`);
    if (!editor) return;
    let value;
    if (editor.type === "checkbox") value = editor.checked ? "yes" : "";
    else value = editor.value;
    value = String(value ?? "").trim();
    if (!value) return;
    if (!field.selector) {
      missing.push(field.label || field.name || `Field ${index + 1}`);
      return;
    }
    values.push({
      selector: field.selector,
      label: field.label || field.name || "",
      type: field.type || "text",
      value,
    });
  });
  return { values, missing };
}

async function analyze() {
  setError("");
  state.filled = 0;
  state.submitted = false;
  $("submit").disabled = true;
  $("reviewed").checked = false;
  $("fields").innerHTML = "";
  $("gate").hidden = true;
  setStatus("Reading the form…");

  try {
    state.tab = await activeTab();
    if (!state.tab) throw new Error("No active tab");
    const scan = await scanPage();
    state.scan = scan;
    $("page-title").textContent = scan.title || "Untitled page";
    $("page-url").textContent = scan.url || "";
    setStatus(`Found ${scan.fields.length} fields. Matching them to your Spark profile…`);

    const response = await background("api:analyze", {
      payload: { url: scan.url, title: scan.title, fields: scan.fields },
    });
    if (!response.ok) {
      throw new Error(
        `${response.error}. Check the backend URL and access password under Settings.`,
      );
    }
    state.analysis = response.data;
    $("engine").textContent = response.data.filled
      ? `${response.data.filled} matched`
      : "No matches yet";
    renderFields();
    if (response.data.filled) {
      setStatus(
        `Spark matched ${response.data.filled} of ${response.data.total} fields. Review them below.`,
        "good",
      );
    } else {
      setStatus(
        "No profile values matched. Fill fields here or add your profile in Spark Settings.",
        "warn",
      );
    }
  } catch (error) {
    setError(error.message || String(error));
    setStatus("Could not analyze this page.");
  }
}

async function fillForm() {
  setError("");
  const { values, missing } = collectValues();
  if (values.length === 0) {
    setError("No values to fill. Add at least one field value above.");
    return;
  }
  if (missing.length) {
    setError(`Some fields have no page selector: ${missing.join(", ")}`);
    return;
  }
  const response = await sendTab(state.tab.id, { type: "spark:fill", values });
  if (!response.ok) {
    setError(response.error || "Filling failed.");
    return;
  }
  state.filled = response.data.filled;
  $("fill-note").textContent = response.data.errors?.length
    ? `Filled ${response.data.filled}. ${response.data.errors.join(" ")}`
    : `Filled ${response.data.filled} fields. Check the page, then tick the approval box.`;
  setStatus(
    `Filled ${response.data.filled} fields. Nothing is submitted until you approve.`,
    "good",
  );
  updateSubmitState();
}

function updateSubmitState() {
  const reviewed = $("reviewed").checked;
  $("submit").disabled = !(reviewed && state.filled > 0 && !state.submitted);
}

async function submitForm() {
  if (!$("reviewed").checked) {
    setError("Tick the approval box after reviewing the page.");
    return;
  }
  if (!state.filled) {
    setError("Fill the form first, review it, then submit.");
    return;
  }
  $("submit").disabled = true;
  $("fill").disabled = true;
  const response = await sendTab(state.tab.id, { type: "spark:submit" });
  if (!response.ok) {
    setError(response.error || "The page could not be submitted.");
    $("fill").disabled = false;
    updateSubmitState();
    return;
  }
  state.submitted = true;
  const log = await background("api:submit", {
    payload: {
      url: response.data.url,
      title: response.data.title,
      field_count: state.filled,
      detail: { source: "chrome-extension", fields: state.filled },
    },
  });
  if (log.ok) {
    setStatus("Submitted and recorded in Spark's form audit.", "good");
    $("fill-note").textContent = "Submission approved by you and logged.";
  } else {
    setStatus("Submitted. The Spark audit log could not be reached.", "warn");
    setError(log.error || "");
  }
}

async function loadSettings() {
  const response = await background("settings:get");
  if (response.ok) {
    $("backend-url").value = response.settings.backendUrl || "";
    $("backend-token").value = response.settings.token || "";
  }
}

async function saveSettings() {
  const response = await background("settings:set", {
    backendUrl: $("backend-url").value.trim(),
    token: $("backend-token").value.trim(),
  });
  $("settings-status").textContent = response.ok ? "Saved." : response.error || "Could not save.";
  if (response.ok) analyze();
}

async function testBackend() {
  $("settings-status").textContent = "Testing…";
  const response = await background("api:health");
  $("settings-status").textContent = response.ok
    ? `Connected · ${response.data.mode} mode`
    : `Failed: ${response.error}`;
}

$("rescan").addEventListener("click", analyze);
$("fill").addEventListener("click", fillForm);
$("submit").addEventListener("click", submitForm);
$("reviewed").addEventListener("change", updateSubmitState);
$("save-settings").addEventListener("click", saveSettings);
$("test-backend").addEventListener("click", testBackend);

(async () => {
  await loadSettings();
  await analyze();
})();
