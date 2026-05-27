import { getUserId, getToken } from "./session.js";

export function escapeHtml(value = "") {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function showToast(message, type = "") {
  const stack = document.getElementById("toast-stack");
  if (!stack) {
    return;
  }
  const node = document.createElement("div");
  node.className = `toast ${type}`.trim();
  node.textContent = message;
  stack.appendChild(node);
  window.setTimeout(() => node.remove(), 3200);
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const userId = getUserId();
  const token = getToken();
  if (userId) {
    headers.set("X-User-Id", userId);
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const baseUrl = window.API_BASE_URL || "";
  const fullPath = baseUrl + path;
  const response = await fetch(fullPath, { ...options, headers });
  const raw = await response.text();
  let body = raw;
  try {
    body = JSON.parse(raw);
  } catch {}
  if (!response.ok) {
    const detail = typeof body === "object" && body && "detail" in body ? body.detail : "Request failed";
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent("studybot:unauthorized", { detail: { path, detail } }));
    }
    throw new Error(detail);
  }
  return body;
}
