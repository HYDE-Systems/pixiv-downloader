// ダッシュボードAPIクライアント。/api は nginx 経由でバックエンドへプロキシされる。
const BASE = "/api";

// FastAPIのエラー詳細(文字列 / 422の配列 / オブジェクト)を読める文字列に整形する。
function formatDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => {
      const where = Array.isArray(d.loc) ? d.loc.slice(1).join(".") : "";
      return where ? `${where}: ${d.msg}` : d.msg;
    }).join(" / ");
  }
  try { return JSON.stringify(detail); } catch (_) { return String(detail); }
}

async function req(path, options = {}) {
  const res = await fetch(BASE + path, {
    credentials: "same-origin", // セッションCookieを送る
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch (_) {}
    throw new Error(formatDetail(detail));
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  status: () => req("/status"),

  // ダッシュボードのログイン（Cookie）
  login: (token) => req("/login", { method: "POST", body: JSON.stringify({ token }) }),
  sessionLogout: () => req("/session/logout", { method: "POST" }),

  // 認証
  authBegin: () => req("/auth/begin", { method: "POST" }),
  authComplete: (state, code) => req("/auth/complete", { method: "POST", body: JSON.stringify({ state, code }) }),
  authToken: (refresh_token) => req("/auth/token", { method: "POST", body: JSON.stringify({ refresh_token }) }),
  logout: () => req("/auth/logout", { method: "POST" }),

  // 設定
  getSettings: () => req("/settings"),
  updateSettings: (patch) => req("/settings", { method: "PUT", body: JSON.stringify(patch) }),
  smbTest: () => req("/settings/smb-test", { method: "POST" }),
  rotateToken: () => req("/settings/rotate-token", { method: "POST" }),

  // 検索
  search: (word, page = 1) => req(`/search?word=${encodeURIComponent(word)}&page=${page}`),
  illust: (id) => req(`/illust/${id}`),

  // キュー
  queue: () => req("/queue"),
  enqueue: (items, token) => req("/queue", { method: "POST", headers: { "X-API-Token": token }, body: JSON.stringify({ items }) }),
  pause: () => req("/queue/pause", { method: "POST" }),
  resume: () => req("/queue/resume", { method: "POST" }),
  clear: () => req("/queue/clear", { method: "POST" }),
  retry: (id) => req(`/queue/retry/${id}`, { method: "POST" }),

  proxy: (url) => `${BASE}/proxy/image?url=${encodeURIComponent(url)}`,
};
