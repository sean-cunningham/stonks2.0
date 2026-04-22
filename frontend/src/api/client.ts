const DEFAULT_API_BASE = "http://127.0.0.1:8000";
export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE;

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    const msg = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${msg}`);
  }

  return (await res.json()) as T;
}
