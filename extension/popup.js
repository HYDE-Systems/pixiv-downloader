// ポップアップ：開いている対応タブを集計し、一括でキューへ送る。
let items = [];

const $ = (id) => document.getElementById(id);

function send(type, payload = {}) {
  return new Promise((resolve) => chrome.runtime.sendMessage({ type, ...payload }, resolve));
}

function renderList() {
  $("count").textContent = items.length;
  $("send").disabled = items.length === 0;
  const list = $("list");
  if (!items.length) {
    list.innerHTML = `<div class="empty">pixivの作品・作家ページを開いてください。</div>`;
    return;
  }
  list.innerHTML = items.map((it) => {
    const isUser = !!it.user_id;
    const id = isUser ? it.user_id : it.illust_id;
    return `<div class="row">
      <span class="k ${isUser ? "u" : ""}">${isUser ? "作家" : "作品"}</span>
      <span class="t">${(it.title || id).replace(/[<>&]/g, "")}</span>
    </div>`;
  }).join("");
}

async function scan() {
  const r = await send("collect");
  items = (r && r.items) || [];
  renderList();
}

$("refresh").addEventListener("click", scan);
$("opts").addEventListener("click", (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); });

$("send").addEventListener("click", async () => {
  const msg = $("msg");
  $("send").disabled = true;
  msg.className = "msg"; msg.textContent = "送信中…";
  const r = await send("enqueue", { items });
  if (r && r.ok) {
    msg.className = "msg ok";
    msg.textContent = `${r.accepted}件をキューに追加しました。`;
  } else {
    msg.className = "msg err";
    msg.textContent = (r && r.error) || "送信に失敗しました。";
    $("send").disabled = false;
  }
});

scan();
