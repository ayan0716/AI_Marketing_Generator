// API client. Phase 5: timeouts, one automatic retry for reads, cached static lists, friendly messages
// for rate limits / server errors / offline, and the server's request id so a failure can be found in the logs.
const BASE = "/api";
const READ_TIMEOUT_MS = 30_000;
const WRITE_TIMEOUT_MS = 240_000; // AI generation (text + images) can legitimately take a while
const STATIC_TTL_MS = 10 * 60_000;
const STATIC_PATHS = new Set(["/options", "/content/platforms", "/creatives/formats", "/agent/assets", "/agent/safeguards"]);

export class ApiError extends Error {
  constructor(message, status, fieldErrors = {}, extra = {}) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
    this.requestId = extra.requestId || null;
    this.retryAfter = extra.retryAfter || null;
  }
}

const staticCache = new Map(); // path -> { at, data }
const inflight = new Map(); // GET path -> Promise (identical simultaneous reads share one request)

function friendly(status, detail, retryAfter, requestId) {
  if (typeof detail === "string" && detail && status < 500) return detail; // the server's message is already readable
  const ref = requestId ? ` (reference ${requestId})` : "";
  if (status === 429) return `You are sending requests too quickly. Please wait ${retryAfter || 30}s and try again.`;
  if (status === 413) return "That file is too large. Please use a smaller image.";
  if (status === 502 || status === 503 || status === 504)
    return (typeof detail === "string" && detail ? detail : "The AI service is busy or unavailable. Please try again in a moment.") + ref;
  if (status >= 500) return `Something went wrong on our side. Please try again${ref}.`;
  return typeof detail === "string" && detail ? detail : "Something went wrong.";
}

async function once(path, options, timeoutMs) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(BASE + path, { headers: { "Content-Type": "application/json" }, signal: ctrl.signal, ...options });
  } catch (e) {
    if (e?.name === "AbortError")
      throw new ApiError("The request took too long and was stopped. The AI may be busy, please try again.", 0);
    throw new ApiError(
      import.meta.env?.DEV
        ? "Cannot reach the server. Is the backend running on port 8000?"
        : "Cannot reach the server. Check your internet connection and try again.",
      0
    );
  } finally {
    clearTimeout(timer);
  }
}

async function request(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const isRead = method === "GET";

  if (isRead && STATIC_PATHS.has(path)) {
    const hit = staticCache.get(path);
    if (hit && Date.now() - hit.at < STATIC_TTL_MS) return hit.data; // no request at all
  }
  if (isRead && inflight.has(path)) return inflight.get(path);

  const run = async () => {
    let res;
    try {
      res = await once(path, options, isRead ? READ_TIMEOUT_MS : WRITE_TIMEOUT_MS);
    } catch (e) {
      if (!isRead || e.status !== 0) throw e;
      await new Promise((r) => setTimeout(r, 800));
      res = await once(path, options, READ_TIMEOUT_MS); // reads are safe to retry once; writes are never retried
    }
    if (isRead && [502, 503, 504].includes(res.status)) {
      await new Promise((r) => setTimeout(r, 800));
      res = await once(path, options, READ_TIMEOUT_MS);
    }
    const requestId = res.headers.get("X-Request-ID");
    if (res.status === 204) return null;
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const retryAfter = Number(res.headers.get("Retry-After")) || null;
      throw new ApiError(friendly(res.status, body.detail, retryAfter, body.request_id || requestId), res.status, body.errors || {}, {
        requestId: body.request_id || requestId,
        retryAfter,
      });
    }
    if (isRead && STATIC_PATHS.has(path)) staticCache.set(path, { at: Date.now(), data: body });
    return body;
  };

  if (!isRead) return run();
  const p = run().finally(() => inflight.delete(path));
  inflight.set(path, p);
  return p;
}

export const api = {
  health: () => request("/health"),
  llmTest: () => request("/llm/test"),
  options: () => request("/options"),
  createStrategy: (payload) => request("/strategies", { method: "POST", body: JSON.stringify(payload) }),
  listCampaigns: () => request("/campaigns"),
  getCampaign: (id) => request(`/campaigns/${id}`),
  deleteCampaign: (id) => request(`/campaigns/${id}`, { method: "DELETE" }),
  // ---- Phase 2: platform content ----
  platforms: () => request("/content/platforms"),
  listContent: (id) => request(`/campaigns/${id}/content`),
  generateContent: (id, platforms, variations) =>
    request(`/campaigns/${id}/content`, { method: "POST", body: JSON.stringify({ platforms, variations }) }),
  regenerate: (id, platform, body) =>
    request(`/campaigns/${id}/content/${platform}/regenerate`, { method: "POST", body: JSON.stringify(body) }),
  selectVariation: (id, platform, index) =>
    request(`/campaigns/${id}/content/${platform}/select`, { method: "PUT", body: JSON.stringify({ index }) }),
  // ---- Phase 3: AI image creatives ----
  creativeFormats: () => request("/creatives/formats"),
  listCreatives: (id) => request(`/campaigns/${id}/creatives`),
  generateCreatives: (id, formats, concepts, useProduct) =>
    request(`/campaigns/${id}/creatives`, { method: "POST", body: JSON.stringify({ formats, concepts, use_product_image: useProduct }) }),
  reviseCreative: (id, fmt, cid, body) =>
    request(`/campaigns/${id}/creatives/${fmt}/${cid}/regenerate`, { method: "POST", body: JSON.stringify(body) }),
  retryCreative: (id, fmt, cid) => request(`/campaigns/${id}/creatives/${fmt}/${cid}/retry`, { method: "POST" }),
  selectCreative: (id, fmt, cid) =>
    request(`/campaigns/${id}/creatives/${fmt}/select`, { method: "PUT", body: JSON.stringify({ concept_id: cid }) }),
  useVersion: (id, fmt, cid, vid) =>
    request(`/campaigns/${id}/creatives/${fmt}/${cid}/version`, { method: "PUT", body: JSON.stringify({ version_id: vid }) }),
  getProductImage: (id) => request(`/campaigns/${id}/product-image`),
  uploadProductImage: (id, dataUrl) =>
    request(`/campaigns/${id}/product-image`, { method: "PUT", body: JSON.stringify({ data_url: dataUrl }) }),
  deleteProductImage: (id) => request(`/campaigns/${id}/product-image`, { method: "DELETE" }),
  // ---- Phase 4: campaign agent ----
  agentAssets: () => request("/agent/assets"),
  agentSafeguards: () => request("/agent/safeguards"),
  agentHistory: (q) => request(`/agent/history${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  agentRun: (payload) => request("/agent/runs", { method: "POST", body: JSON.stringify(payload) }),
  agentGetRun: (id) => request(`/agent/runs/${id}`),
  agentContinue: (id, assets) => request(`/agent/runs/${id}/continue`, { method: "POST", body: JSON.stringify({ assets }) }),
  agentCancel: (id) => request(`/agent/runs/${id}/cancel`, { method: "POST" }),
  agentWorkspace: (id) => request(`/agent/campaigns/${id}/workspace`),
  agentRegenerate: (id, body) => request(`/agent/campaigns/${id}/regenerate`, { method: "POST", body: JSON.stringify(body) }),
  agentApprovals: (id, approvals) => request(`/agent/campaigns/${id}/approvals`, { method: "PUT", body: JSON.stringify({ approvals }) }),
  agentExport: (id, body) => request(`/agent/campaigns/${id}/export`, { method: "POST", body: JSON.stringify(body) }),
};