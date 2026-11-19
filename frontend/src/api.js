const BASE = "/api";
export class ApiError extends Error {
  constructor(message, status, fieldErrors = {}) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}
async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(BASE + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new ApiError("Cannot reach the server. Is the backend running on port 8000?", 0);
  }
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = typeof body.detail === "string" ? body.detail : "Something went wrong.";
    throw new ApiError(msg, res.status, body.errors || {});
  }
  return body;
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
};