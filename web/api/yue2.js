import { api } from "/scripts/api.js";

const PREFIX = "/yue2_prompt_writer";

async function request(path, options) {
  const response = await api.fetchApi(`${PREFIX}${path}`, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const error = payload?.error || {};
    const failure = new Error(error.message || `请求失败（HTTP ${response.status}）`);
    failure.code = error.code || `HTTP_${response.status}`;
    failure.details = error.details;
    throw failure;
  }
  return payload;
}

function post(path, body = {}) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const getHealth = () => request("/health");
export const getCatalog = () => request("/catalog");
export const getGuides = () => request("/guides");
export const getGuide = (guideId) => request(`/guide/${encodeURIComponent(guideId)}`);
export const plan = (payload) => post("/plan", payload);
export const analyzeLyrics = (lyrics, brief) => post("/lyrics/analyze", { lyrics, brief });
export const getModels = () => request("/models");
export const unloadModel = () => post("/model/unload");
export const diagnoseGguf = (refresh = false) => post("/runtime/gguf/diagnostics", { refresh });
export const testProvider = (provider) => post("/provider/test", { provider });
export const preview = (payload) => post("/preview", payload);
export const generate = (payload) => post("/generate", payload);
export const writeLyrics = (payload) => post("/lyrics", payload);
export const cancel = () => post("/cancel");
