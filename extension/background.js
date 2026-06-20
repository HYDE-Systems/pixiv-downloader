// Pixiv Download Studio 連携 — バックグラウンド(Service Worker)
// pixivのURLを解析し、ダッシュボードのキューAPIへ投入する中枢。

const PIXIV_HOSTS = ["pixiv.net", "www.pixiv.net"];

// URL から投入アイテム({illust_id} または {user_id})を抽出する。
function parsePixivUrl(rawUrl) {
  let u;
  try { u = new URL(rawUrl); } catch (_) { return null; }
  if (!PIXIV_HOSTS.includes(u.hostname)) return null;

  // /artworks/12345  (/en/artworks/...)
  let m = u.pathname.match(/\/artworks\/(\d+)/);
  if (m) return { illust_id: Number(m[1]), source_url: rawUrl };

  // /users/12345  (/en/users/...)
  m = u.pathname.match(/\/users\/(\d+)/);
  if (m) return { user_id: Number(m[1]), source_url: rawUrl };

  // 旧形式 member_illust.php?illust_id=12345
  const illustId = u.searchParams.get("illust_id");
  if (illustId) return { illust_id: Number(illustId), source_url: rawUrl };

  // 旧形式 member.php?id=123 / member_illust.php?id=123
  if (/member(_illust)?\.php/.test(u.pathname)) {
    const id = u.searchParams.get("id");
    if (id) return { user_id: Number(id), source_url: rawUrl };
  }
  return null;
}

async function getConfig() {
  const { dashboardUrl, apiToken } = await chrome.storage.sync.get(["dashboardUrl", "apiToken"]);
  return { dashboardUrl: (dashboardUrl || "").replace(/\/+$/, ""), apiToken: apiToken || "" };
}

async function enqueue(items) {
  const { dashboardUrl, apiToken } = await getConfig();
  if (!dashboardUrl || !apiToken) {
    throw new Error("拡張機能の設定でダッシュボードURLとAPIトークンを入力してください。");
  }
  const res = await fetch(`${dashboardUrl}/api/queue`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Token": apiToken },
    body: JSON.stringify({ items }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

// 開いている全タブから対応URLを収集する。
async function collectOpenTabs() {
  const tabs = await chrome.tabs.query({});
  const items = [];
  const seen = new Set();
  for (const tab of tabs) {
    const parsed = parsePixivUrl(tab.url || "");
    if (!parsed) continue;
    const key = parsed.illust_id ? `i${parsed.illust_id}` : `u${parsed.user_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    parsed.title = tab.title;
    items.push(parsed);
  }
  return items;
}

function notify(title, message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message,
  });
}

// --- メッセージ受信(ポップアップから) ---
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === "collect") {
        sendResponse({ ok: true, items: await collectOpenTabs() });
      } else if (msg.type === "enqueue") {
        const r = await enqueue(msg.items);
        sendResponse({ ok: true, accepted: r.accepted });
      }
    } catch (e) {
      sendResponse({ ok: false, error: e.message });
    }
  })();
  return true; // 非同期レスポンス
});

// --- コンテキストメニュー ---
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "pds-add-link",
    title: "Pixivキューに追加",
    contexts: ["link", "page"],
    documentUrlPatterns: ["*://*.pixiv.net/*"],
    targetUrlPatterns: ["*://*.pixiv.net/*"],
  });
  chrome.contextMenus.create({
    id: "pds-add-all",
    title: "開いているPixivタブを一括追加",
    contexts: ["page"],
    documentUrlPatterns: ["*://*.pixiv.net/*"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    if (info.menuItemId === "pds-add-link") {
      const parsed = parsePixivUrl(info.linkUrl || info.pageUrl || tab.url);
      if (!parsed) return notify("追加できません", "対応するpixivのURLではありません。");
      const r = await enqueue([parsed]);
      notify("キューに追加", `${r.accepted}件を追加しました。`);
    } else if (info.menuItemId === "pds-add-all") {
      const items = await collectOpenTabs();
      if (!items.length) return notify("対象なし", "開いているタブに対応URLがありません。");
      const r = await enqueue(items);
      notify("一括追加完了", `${r.accepted}件をキューに追加しました。`);
    }
  } catch (e) {
    notify("エラー", e.message);
  }
});
