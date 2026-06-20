// 連携設定の保存と接続テスト。
const $ = (id) => document.getElementById(id);

chrome.storage.sync.get(["dashboardUrl", "apiToken"]).then(({ dashboardUrl, apiToken }) => {
  $("url").value = dashboardUrl || "";
  $("token").value = apiToken || "";
});

function setMsg(text, kind = "") { const m = $("msg"); m.className = "msg " + kind; m.textContent = text; }

$("save").addEventListener("click", async () => {
  const dashboardUrl = $("url").value.trim().replace(/\/+$/, "");
  const apiToken = $("token").value.trim();
  await chrome.storage.sync.set({ dashboardUrl, apiToken });
  setMsg("保存しました。", "ok");
});

$("test").addEventListener("click", async () => {
  const url = $("url").value.trim().replace(/\/+$/, "");
  const token = $("token").value.trim();
  if (!url) return setMsg("URLを入力してください。", "err");
  setMsg("接続中…");
  try {
    const res = await fetch(`${url}/api/status`, { headers: token ? { "X-API-Token": token } : {} });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const s = await res.json();
    if (!s.dashboard_authenticated) {
      setMsg("接続OK・トークン未認証：APIトークンを確認してください。", "err");
      return;
    }
    setMsg(`接続成功：pixiv ${s.authenticated ? "ログイン済" : "未ログイン"} / SMB ${s.smb_configured ? "設定済" : "未設定"}`, "ok");
  } catch (e) {
    setMsg("接続失敗：" + e.message, "err");
  }
});
