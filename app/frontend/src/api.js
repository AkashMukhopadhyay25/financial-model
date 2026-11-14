// Thin client for the FastAPI backend. Every page response carries its own SQL evidence.
const cache = new Map();

async function request(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* empty body */
  }
  if (!res.ok) throw new Error((body && (body.error || body.detail)) || `${res.status} ${res.statusText}`);
  return body;
}

export function get(path, { fresh = false } = {}) {
  if (!fresh && cache.has(path)) return cache.get(path);
  const p = request(path).catch((e) => {
    cache.delete(path);
    throw e;
  });
  cache.set(path, p);
  return p;
}

export function post(path, data) {
  return request(path, { method: "POST", body: JSON.stringify(data) });
}

export function invalidate(prefix) {
  for (const k of [...cache.keys()]) if (k.startsWith(prefix)) cache.delete(k);
}

export const askGenie = (question, conversation_id) => post("/api/genie/ask", { question, conversation_id });

export const flagReview = (body) =>
  post("/api/review-requests", body).then((r) => {
    invalidate("/api/early-warning");
    invalidate("/api/overview");
    return r;
  });
