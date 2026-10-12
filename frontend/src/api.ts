const BASE_PATH = (window as unknown as { __BASE_PATH__?: string }).__BASE_PATH__ || "";

const API_BASE = (() => {
  if (import.meta.env?.VITE_API_URL) return import.meta.env.VITE_API_URL;
  return `${window.location.origin}${BASE_PATH}/api`;
})();

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
  });
  if (res.status === 401) {
    window.location.href = `${BASE_PATH}/login`;
    throw new Error("Unauthorized");
  }
  return res;
}

export { API_BASE, BASE_PATH };
