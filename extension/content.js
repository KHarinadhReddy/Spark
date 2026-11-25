// Spark Form Filler — page-side extractor and filler.
// This script is only injected when you open the extension popup.

(() => {
  if (window.__sparkFormFillerLoaded) return;
  window.__sparkFormFillerLoaded = true;

  const SKIP_TYPES = new Set([
    "password",
    "hidden",
    "file",
    "submit",
    "button",
    "reset",
    "image",
  ]);

  const SENSITIVE = /(password|passcode|otp|one[- ]time|captcha|cvv|card number|debit|credit|pin\b|aadhaar|pan\b|bank account|ifsc|upi)/i;

  let lastForm = null;

  function isVisible(element) {
    if (!element || element.disabled || element.readOnly) return false;
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) {
      return false;
    }
    return Boolean(element.getClientRects().length);
  }

  function textOf(element) {
    return (element?.innerText || element?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function labelFor(element) {
    const id = element.getAttribute("id");
    if (id) {
      const explicit = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (explicit) return textOf(explicit);
    }
    const wrapping = element.closest("label");
    if (wrapping) return textOf(wrapping);
    const labelledBy = element.getAttribute("aria-labelledby");
    if (labelledBy) {
      const parts = labelledBy
        .split(/\s+/)
        .map((token) => textOf(document.getElementById(token)))
        .filter(Boolean);
      if (parts.length) return parts.join(" ");
    }
    return (
      element.getAttribute("aria-label") ||
      element.getAttribute("placeholder") ||
      element.getAttribute("title") ||
      ""
    ).trim();
  }

  function uniqueSelector(element) {
    const id = element.getAttribute("id");
    if (id && document.querySelectorAll(`#${CSS.escape(id)}`).length === 1) {
      return `#${CSS.escape(id)}`;
    }
    const name = element.getAttribute("name");
    if (name) {
      const matches = document.querySelectorAll(
        `${element.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`,
      );
      if (matches.length === 1) return `${element.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;
    }
    const parts = [];
    let node = element;
    while (node && node.nodeType === 1 && node !== document.body) {
      let part = node.tagName.toLowerCase();
      const siblings = Array.from(node.parentElement?.children || []).filter(
        (sibling) => sibling.tagName === node.tagName,
      );
      if (siblings.length > 1) {
        part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      if (node.id && document.querySelectorAll(`#${CSS.escape(node.id)}`).length === 1) {
        parts.unshift(`#${CSS.escape(node.id)}`);
        break;
      }
      node = node.parentElement;
    }
    return parts.join(" > ");
  }

  function optionsOf(element) {
    if (element.tagName.toLowerCase() !== "select") return [];
    return Array.from(element.options)
      .map((option) => textOf(option))
      .filter(Boolean)
      .slice(0, 50);
  }

  function scan() {
    const candidates = Array.from(
      document.querySelectorAll("input, textarea, select"),
    ).filter((element) => {
      const type = (element.getAttribute("type") || element.tagName).toLowerCase();
      if (SKIP_TYPES.has(type)) return false;
      if (element.closest("[aria-hidden='true']")) return false;
      return isVisible(element);
    });

    const fields = candidates.slice(0, 120).map((element, index) => {
      const type = (element.getAttribute("type") || element.tagName).toLowerCase();
      return {
        index,
        name: (element.getAttribute("name") || "").slice(0, 200),
        id: (element.getAttribute("id") || "").slice(0, 200),
        label: labelFor(element).slice(0, 240),
        aria_label: (element.getAttribute("aria-label") || "").slice(0, 240),
        placeholder: (element.getAttribute("placeholder") || "").slice(0, 240),
        type,
        required: Boolean(element.required) || element.getAttribute("aria-required") === "true",
        options: optionsOf(element),
        selector: uniqueSelector(element),
      };
    });

    return {
      url: location.href,
      title: document.title,
      fields,
    };
  }

  function nativeSet(element, value) {
    const proto =
      element.tagName.toLowerCase() === "textarea"
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor && descriptor.set) descriptor.set.call(element, value);
    else element.value = value;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function setSelect(element, value) {
    const wanted = String(value).trim().toLowerCase();
    const option = Array.from(element.options).find(
      (item) =>
        (item.value || "").trim().toLowerCase() === wanted ||
        textOf(item).toLowerCase() === wanted,
    );
    if (!option) return false;
    element.value = option.value;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.dispatchEvent(new Event("blur", { bubbles: true }));
    return true;
  }

  function setChoice(element, value) {
    const wanted = String(value).trim().toLowerCase();
    if (["", "false", "no", "0", "off"].includes(wanted)) {
      element.checked = false;
    } else if (element.type === "radio") {
      const group = element.name
        ? Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(element.name)}"]`))
        : [element];
      const option = group.find(
        (item) =>
          (item.value || "").trim().toLowerCase() === wanted ||
          textOf(item).toLowerCase() === wanted,
      );
      (option || element).checked = true;
    } else {
      element.checked = true;
    }
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fill(values) {
    let filled = 0;
    const errors = [];
    const touchedForms = [];
    for (const item of values || []) {
      if (!item || !item.selector) continue;
      const value = String(item.value ?? "");
      if (!value) continue;
      let element;
      try {
        element = document.querySelector(item.selector);
      } catch {
        element = null;
      }
      if (!element) {
        errors.push(`Missing field: ${item.label || item.selector}`);
        continue;
      }
      const type = (element.getAttribute("type") || element.tagName).toLowerCase();
      const label = item.label || labelFor(element);
      if (SKIP_TYPES.has(type) || SENSITIVE.test(`${label} ${element.name} ${element.id}`)) {
        errors.push(`Skipped sensitive field: ${label || element.name || type}`);
        continue;
      }
      try {
        if (type === "checkbox" || type === "radio") {
          setChoice(element, value);
        } else if (type === "select" || element.tagName.toLowerCase() === "select") {
          if (!setSelect(element, value)) {
            errors.push(`No matching option for ${label || element.name}`);
            continue;
          }
        } else {
          nativeSet(element, value);
        }
        filled += 1;
        const form = element.closest("form");
        if (form && !touchedForms.includes(form)) touchedForms.push(form);
      } catch (error) {
        errors.push(`Could not fill ${label || element.name}: ${error.message}`);
      }
    }
    lastForm = touchedForms[0] || document.querySelector("form");
    return { filled, errors };
  }

  function submitForm() {
    const form = lastForm || document.querySelector("form");
    if (!form) {
      const button = Array.from(
        document.querySelectorAll("button, input[type='submit']"),
      ).find((element) => /submit|send|apply|register|save/i.test(textOf(element) || element.value || ""));
      if (button) {
        button.click();
        return { ok: true, method: "button" };
      }
      return { ok: false, error: "No form or submit button found" };
    }
    if (typeof form.requestSubmit === "function") {
      form.requestSubmit();
      return { ok: true, method: "requestSubmit" };
    }
    form.submit();
    return { ok: true, method: "submit" };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "spark:scan") {
      sendResponse({ ok: true, data: scan() });
      return true;
    }
    if (message?.type === "spark:fill") {
      sendResponse({ ok: true, data: fill(message.values) });
      return true;
    }
    if (message?.type === "spark:submit") {
      // Respond before submitting: navigation can tear the page down immediately.
      sendResponse({ ok: true, data: { url: location.href, title: document.title } });
      setTimeout(() => {
        try {
          submitForm();
        } catch {
          // the page navigated; nothing else to do
        }
      }, 50);
      return true;
    }
    return false;
  });
})();
