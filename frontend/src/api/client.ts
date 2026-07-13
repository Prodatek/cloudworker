import createClient from "openapi-fetch";
import type { paths } from "./generated/schema";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const TOKEN_STORAGE_KEY = "cloudworker.token";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

export const api = createClient<paths>({ baseUrl: API_BASE_URL });

// Injects the current token (API key or JWT — the backend's get_current_user accepts
// either through the same header) on every request, read fresh each time so a
// login/logout during the session takes effect immediately.
api.use({
  onRequest({ request }) {
    const token = getStoredToken();
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    return request;
  },
});
