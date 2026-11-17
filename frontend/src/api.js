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
};
