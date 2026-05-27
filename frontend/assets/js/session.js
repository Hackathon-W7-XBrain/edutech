const STORAGE_KEY = "sb_user";
const TOKEN_KEY = "sb_token";

export function getUserId() {
  return window.localStorage.getItem(STORAGE_KEY) || "";
}

export function setUserId(userId) {
  window.localStorage.setItem(STORAGE_KEY, userId);
}

export function clearUserId() {
  window.localStorage.removeItem(STORAGE_KEY);
}

export function getToken() {
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}
