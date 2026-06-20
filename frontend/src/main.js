import "./styles.css";
import { api } from "./api.js";

// ---------- 状態 ----------
const state = {
  view: "queue",
  status: null,
  settings: null,
  search: { word: "", results: [], hasNext: false, page: 1, loading: false, queued: new Set() },
  sse: null,
};

const NAV = [
  { id: "queue", label: "受信", en: "queue" },
  { id: "search", label: "検索", en: "search" },
  { id: "rss", label: "RSS", en: "feeds" },
  { id: "auth", label: "認証", en: "auth" },
  { id: "settings", label: "設定", en: "config" },
];

const app = document.getElementById("app");
const fmtBytes = (b) => {
  if (!b) return "0 B";
  const u = ["B", "KB", "MB", "GB"]; let i = 0; let n = b;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(n < 10 && i ? 1 : 0)} ${u[i]}`;
};
const esc = (s) => (s ?? "").toString().replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pad = (n) => String(n).padStart(3, "0");

// ---------- トースト ----------
function toast(msg, kind = "") {
  let wrap = document.querySelector(".toast-wrap");
  if (!wrap) { wrap = document.createElement("div"); wrap.className = "toast-wrap"; document.body.appendChild(wrap); }
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; setTimeout(() => el.remove(), 300); }, 3600);
}

// ---------- 初期化 ----------
async function boot() {
  try {
    state.status = await api.status();
  } catch (e) {
    app.innerHTML = `<div class="center-load">バックエンドに接続できません… ${esc(e.message)}</div>`;
    return;
  }
  if (!state.status.dashboard_authenticated) { renderLogin(); return; }
  if (!state.status.authenticated) state.view = "auth";
  render();
}

// ---------- ダッシュボードのログインゲート ----------
function renderLogin() {
  app.setAttribute("aria-busy", "false");
  app.innerHTML = `
    <div class="gate">
      <form class="gate-card" id="gate">
        <div class="mark"><span class="stamp">朱</span><span>PIXIV<br>DL STUDIO</span></div>
        <p class="hint">APIトークンでログインします。初回のトークンはサーバーのログに出力されています：<br>
          <code>docker compose logs backend | grep トークン</code></p>
        <div class="field"><label>APIトークン</label><input id="gate-token" type="password" placeholder="トークンを貼り付け" autocomplete="current-password" autofocus></div>
        <button class="btn primary" type="submit" style="width:100%">ログイン</button>
        <div class="msg" id="gate-msg"></div>
      </form>
    </div>`;
  app.querySelector("#gate").addEventListener("submit", async (e) => {
    e.preventDefault();
    const token = app.querySelector("#gate-token").value.trim();
    const msg = app.querySelector("#gate-msg");
    if (!token) return;
    try {
      await api.login(token);
      state.status = await api.status();
      if (!state.status.authenticated) state.view = "auth";
      render();
    } catch (err) {
      msg.className = "msg err"; msg.textContent = err.message || "ログインに失敗しました。";
    }
  });
}

// ---------- シェル描画 ----------
function render() {
  app.setAttribute("aria-busy", "false");
  app.innerHTML = `
    <div class="shell">
      ${railHTML()}
      <main class="main" id="main"></main>
    </div>`;
  app.querySelectorAll(".nav button").forEach((b) =>
    b.addEventListener("click", () => { switchView(b.dataset.view); }));
  const lock = app.querySelector("#lock");
  if (lock) lock.addEventListener("click", async () => {
    if (state.sse) { state.sse.close(); state.sse = null; }
    await api.sessionLogout();
    renderLogin();
  });
  renderView();
}

function railHTML() {
  const st = state.status || {};
  return `
    <aside class="rail">
      <div class="brand">
        <div class="mark"><span class="stamp">朱</span><span>PIXIV<br>DL STUDIO</span></div>
        <div class="sub">Darkroom · SMB</div>
      </div>
      <nav class="nav">
        ${NAV.map((n, i) => `
          <button data-view="${n.id}" class="${state.view === n.id ? "active" : ""}">
            <span class="idx">${pad(i + 1).slice(1)}</span><span>${n.label}</span><span class="en">${n.en}</span>
          </button>`).join("")}
      </nav>
      <div class="rail-foot">
        <div class="status-line"><span class="dot ${st.authenticated ? "ok" : "off"}"></span>pixiv ${st.authenticated ? (esc(st.pixiv_user) || "ログイン済") : "未ログイン"}</div>
        <div class="status-line"><span class="dot ${st.smb_configured ? "ok" : "off"}"></span>SMB ${st.smb_configured ? "設定済" : "未設定"}</div>
        <button class="btn ghost" id="lock" style="margin-top:10px;width:100%;padding:7px;font-size:10px">🔒 ロック</button>
      </div>
    </aside>`;
}

function switchView(v) {
  if (state.view === v) return;
  if (state.sse && v !== "queue") { state.sse.close(); state.sse = null; }
  state.view = v;
  app.querySelectorAll(".nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  renderView();
}

function renderView() {
  const main = document.getElementById("main");
  if (state.view === "queue") return renderQueue(main);
  if (state.view === "search") return renderSearch(main);
  if (state.view === "rss") return renderRss(main);
  if (state.view === "auth") return renderAuth(main);
  if (state.view === "settings") return renderSettings(main);
}

// ---------- 受信（キュー / フィルムストリップ）----------
function renderQueue(main) {
  main.innerHTML = `
    <div class="view-head">
      <div>
        <div class="eyebrow">contact sheet · 現像台</div>
        <h1>受信トレイ</h1>
        <p>取り込んだ作品はメモリ上で現像され、そのまま SMB へ転送されます。サーバーには何も残りません。</p>
      </div>
      <div class="btn-row">
        <button class="btn" id="q-pause">一時停止</button>
        <button class="btn ghost" id="q-clear">完了を消去</button>
      </div>
    </div>
    <div class="meters" id="meters"></div>
    <div class="strip" id="strip"></div>`;

  main.querySelector("#q-pause").addEventListener("click", async (e) => {
    const paused = e.target.textContent === "再開";
    if (paused) { await api.resume(); } else { await api.pause(); }
  });
  main.querySelector("#q-clear").addEventListener("click", async () => { await api.clear(); toast("完了済みを消去しました", "ok"); });

  startQueueStream();
}

function startQueueStream() {
  if (state.sse) state.sse.close();
  const es = new EventSource("/api/queue/stream");
  state.sse = es;
  es.onmessage = (ev) => { try { updateQueue(JSON.parse(ev.data)); } catch (_) {} };
  es.onerror = () => { /* ブラウザが自動再接続 */ };
}

const frameEls = new Map();
function updateQueue(data) {
  const meters = document.getElementById("meters");
  const strip = document.getElementById("strip");
  if (!meters || !strip) return;
  const s = data.stats || {};
  meters.innerHTML = `
    ${meterHTML(s.queued || 0, "待機", "")}
    ${meterHTML(s.downloading || 0, "現像中", "accent")}
    ${meterHTML(s.done || 0, "定着", "jade")}
    ${meterHTML(fmtBytes(s.bytes || 0), "SMB転送量", "")}`;

  const pauseBtn = document.getElementById("q-pause");
  if (pauseBtn) pauseBtn.textContent = data.paused ? "再開" : "一時停止";

  const items = data.items || [];
  if (!items.length) {
    strip.innerHTML = `<div class="empty"><div class="big">フィルム未装填</div>検索タブで作品を追加するか、Chrome拡張から一括投入してください。</div>`;
    frameEls.clear();
    return;
  }
  if (strip.querySelector(".empty")) strip.innerHTML = "";

  const seen = new Set();
  items.forEach((it, i) => {
    seen.add(it.id);
    let el = frameEls.get(it.id);
    if (!el) { el = document.createElement("div"); frameEls.set(it.id, el); strip.appendChild(el); }
    paintFrame(el, it, i);
  });
  // 消えた要素を除去
  for (const [id, el] of frameEls) {
    if (!seen.has(id)) { el.remove(); frameEls.delete(id); }
  }
  // 並び順を維持
  items.forEach((it) => strip.appendChild(frameEls.get(it.id)));
}

function meterHTML(n, k, cls) {
  return `<div class="meter ${cls}"><div class="n">${n}</div><div class="k">${k}</div></div>`;
}

function paintFrame(el, it, i) {
  if (it.kind === "note") {
    el.className = "frame is-note state-error";
    el.innerHTML = `<div class="perf"></div><div class="meta"><div class="title">${esc(it.title)}</div></div>`;
    return;
  }
  const pct = it.pages_total ? Math.round((it.pages_done / it.pages_total) * 100) : (it.state === "done" ? 100 : 0);
  const stateLabel = { queued: "待機", downloading: "現像", done: "定着", error: "失敗", resolving: "展開中" }[it.state] || it.state;
  el.className = `frame state-${it.state}`;
  el.innerHTML = `
    <div class="perf" data-no="${pad(i + 1)}"></div>
    <img class="thumb" alt="" src="${it.thumb_url ? api.proxy(it.thumb_url) : ""}" onerror="this.style.visibility='hidden'">
    <div class="meta">
      <div class="title">${esc(it.title)}</div>
      <div class="by">${it.artist ? esc(it.artist) : "—"} · <a href="https://www.pixiv.net/artworks/${it.illust_id}" target="_blank" rel="noopener">#${it.illust_id}</a></div>
      <div class="develop-bar"><i style="width:${pct}%"></i></div>
    </div>
    <div class="right">
      <span class="tag ${it.state}">${stateLabel}</span>
      <span class="sub">${it.pages_total ? `${it.pages_done}/${it.pages_total}p` : ""} ${it.bytes ? "· " + fmtBytes(it.bytes) : ""}</span>
      ${it.state === "error" ? `<button class="btn ghost" data-retry="${it.id}" style="padding:5px 10px;font-size:10px">再試行</button>` : ""}
    </div>`;
  const retry = el.querySelector("[data-retry]");
  if (retry) retry.addEventListener("click", async () => { await api.retry(it.id); toast("再試行キューに戻しました"); });
  const errTag = el.querySelector(".tag.error");
  if (errTag && it.error) errTag.title = it.error;
}

// ---------- 検索（コンタクトシート）----------
function renderSearch(main) {
  main.innerHTML = `
    <div class="view-head">
      <div>
        <div class="eyebrow">light table · 検索</div>
        <h1>作品を探す</h1>
        <p>タグ・キーワードで検索し、コンタクトシートから直接キューへ送ります。</p>
      </div>
    </div>
    <form class="searchbar" id="sform">
      <input id="sword" type="text" placeholder="タグ / キーワード（例：風景 オリジナル）" value="${esc(state.search.word)}" autocomplete="off">
      <button class="btn primary" type="submit">検索</button>
    </form>
    <div id="sheet"></div>`;

  main.querySelector("#sform").addEventListener("submit", (e) => {
    e.preventDefault();
    state.search.word = main.querySelector("#sword").value.trim();
    state.search.page = 1;
    doSearch(true);
  });
  if (state.search.results.length) paintSheet();
}

async function doSearch(reset) {
  if (!state.search.word) return;
  const sheet = document.getElementById("sheet");
  state.search.loading = true;
  if (reset) { state.search.results = []; sheet.innerHTML = `<div class="empty"><span class="spinner"></span> 検索中…</div>`; }
  try {
    const r = await api.search(state.search.word, state.search.page);
    state.search.results = reset ? r.illusts : state.search.results.concat(r.illusts);
    state.search.hasNext = r.has_next;
    paintSheet();
  } catch (e) {
    sheet.innerHTML = `<div class="empty"><div class="big">検索できません</div>${esc(e.message)}</div>`;
  } finally { state.search.loading = false; }
}

function paintSheet() {
  const sheet = document.getElementById("sheet");
  const items = state.search.results;
  if (!items.length) { sheet.innerHTML = `<div class="empty"><div class="big">該当なし</div>別のキーワードをお試しください。</div>`; return; }
  sheet.innerHTML = `
    <div class="sheet">
      ${items.map((it, i) => {
        const q = state.search.queued.has(it.illust_id);
        return `
        <div class="cell" data-id="${it.illust_id}" title="クリックで詳細">
          <span class="no">${pad(i + 1)}</span>
          <button class="add ${q ? "queued" : ""}" data-id="${it.illust_id}" data-title="${esc(it.title)}" title="キューに追加">${q ? "✓" : "+"}</button>
          ${it.page_count > 1 ? `<span class="pages">${it.page_count}p</span>` : ""}
          <img class="ph" loading="lazy" alt="" src="${api.proxy(it.thumb_url)}" onerror="this.style.visibility='hidden'">
          <div class="cap"><div class="t">${esc(it.title)}</div><div class="a">${esc(it.artist)}</div></div>
        </div>`;
      }).join("")}
    </div>
    ${state.search.hasNext ? `<div class="btn-row" style="justify-content:center;margin-top:22px"><button class="btn" id="more">さらに読み込む</button></div>` : ""}`;

  sheet.querySelectorAll(".add").forEach((b) => b.addEventListener("click", async (e) => {
    e.stopPropagation(); // セルのクリック(詳細表示)と分離
    await enqueueIllust(Number(b.dataset.id), b.dataset.title, b);
  }));
  // セルクリックで詳細ポップアップ
  sheet.querySelectorAll(".cell").forEach((cell) => cell.addEventListener("click", () => {
    openDetail(Number(cell.dataset.id));
  }));
  const more = sheet.querySelector("#more");
  if (more) more.addEventListener("click", () => { state.search.page++; doSearch(false); });
}

async function enqueueIllust(id, title, addBtn) {
  if (!Number.isInteger(id) || id <= 0) {
    toast("作品IDを取得できませんでした。", "err");
    return false;
  }
  if (!state.status.api_token) {
    toast("APIトークンが未取得です。ページを再読み込みしてください。", "err");
    return false;
  }
  try {
    await api.enqueue([{ illust_id: id, title: title || `#${id}` }], state.status.api_token);
    state.search.queued.add(id);
    if (addBtn) { addBtn.classList.add("queued"); addBtn.textContent = "✓"; }
    // シート上の同一作品ボタンも更新
    document.querySelectorAll(`.add[data-id="${id}"]`).forEach((b) => { b.classList.add("queued"); b.textContent = "✓"; });
    toast("キューに追加しました", "ok");
    return true;
  } catch (e) { toast("追加失敗: " + e.message, "err"); return false; }
}

// ---------- 詳細ポップアップ（ルーペ / ライトボックス）----------
function stripHtml(html) {
  return (html || "").replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "").trim();
}

async function openDetail(id) {
  let bg = document.querySelector(".modal-bg");
  if (bg) bg.remove();
  bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal"><div class="center-load" style="height:300px;grid-column:1/-1"><span class="spinner"></span> 読み込み中…</div></div>`;
  document.body.appendChild(bg);

  const close = () => { bg.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  bg.addEventListener("click", (e) => { if (e.target === bg) close(); });

  let d;
  try { d = await api.illust(id); }
  catch (e) { bg.querySelector(".modal").innerHTML = `<div class="empty" style="grid-column:1/-1"><div class="big">読み込めません</div>${esc(e.message)}</div>`; return; }

  const queued = state.search.queued.has(id);
  const previews = d.previews || [];
  bg.querySelector(".modal").innerHTML = `
    <button class="modal-close" aria-label="閉じる">✕</button>
    <div class="stage">
      <img class="big-img" alt="" src="${previews[0] ? api.proxy(previews[0]) : ""}">
      ${previews.length > 1 ? `<div class="thumbs">${previews.map((u, i) =>
        `<img data-i="${i}" class="${i === 0 ? "on" : ""}" src="${api.proxy(u)}" alt="">`).join("")}</div>` : ""}
    </div>
    <div class="info">
      <div class="eyebrow">${d.type === "ugoira" ? "うごイラ" : d.type === "manga" ? "マンガ" : "イラスト"} · ${d.page_count}p</div>
      <h2>${esc(d.title)}</h2>
      <a class="artist" href="https://www.pixiv.net/users/${d.artist_id}" target="_blank" rel="noopener">${esc(d.artist)}</a>
      <div class="stats">
        <span>👁 ${(d.total_view || 0).toLocaleString()}</span>
        <span>♥ ${(d.total_bookmarks || 0).toLocaleString()}</span>
        <span>${(d.create_date || "").slice(0, 10)}</span>
      </div>
      <div class="tags">${(d.tags || []).map((t) => `<span class="chip">#${esc(t)}</span>`).join("")}</div>
      ${d.caption ? `<p class="caption">${esc(stripHtml(d.caption))}</p>` : ""}
      <div class="modal-actions">
        <button class="btn primary" id="m-dl" ${queued ? "disabled" : ""}>${queued ? "追加済み ✓" : "ダウンロード"}</button>
        <a class="btn ghost" href="https://www.pixiv.net/artworks/${id}" target="_blank" rel="noopener">pixivで開く</a>
        <a class="btn ghost" href="${rssUrl(`user/${d.artist_id}`)}" target="_blank" rel="noopener" title="この作家の新着をRSSで購読">作家RSS</a>
      </div>
    </div>`;

  bg.querySelector(".modal-close").addEventListener("click", close);
  bg.querySelectorAll(".thumbs img").forEach((t) => t.addEventListener("click", () => {
    bg.querySelector(".big-img").src = api.proxy(previews[Number(t.dataset.i)]);
    bg.querySelectorAll(".thumbs img").forEach((x) => x.classList.remove("on"));
    t.classList.add("on");
  }));
  const dl = bg.querySelector("#m-dl");
  dl.addEventListener("click", async () => {
    dl.disabled = true;
    const ok = await enqueueIllust(id, d.title);
    dl.textContent = ok ? "追加済み ✓" : "ダウンロード";
    dl.disabled = ok;
  });
}

// ---------- RSS ----------
function rssUrl(path) {
  return `${location.origin}/api/rss/${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(state.status.api_token || "")}`;
}

function renderRss(main) {
  main.innerHTML = `
    <div class="view-head">
      <div>
        <div class="eyebrow">syndication · feeds</div>
        <h1>RSS フィード</h1>
        <p>pixivの新着をRSSリーダーで購読できます。URLにはAPIトークンが含まれます（取り扱いに注意）。</p>
      </div>
    </div>

    <div class="panel">
      <h2>フォロー新着</h2>
      <p class="hint">フォロー中ユーザーの新着作品フィード。</p>
      <div class="code-box" id="rss-follow">${esc(rssUrl("following"))}</div>
      <div class="btn-row" style="margin-top:12px">
        <button class="btn" data-copy="rss-follow">コピー</button>
        <a class="btn ghost" href="${rssUrl("following")}" target="_blank" rel="noopener">開く</a>
      </div>
    </div>

    <div class="panel">
      <h2>作家の新着</h2>
      <p class="hint">作家(ユーザー)IDを入力するとフィードURLを生成します。作品詳細の作者リンクのURL末尾の数字がIDです。</p>
      <div class="field"><label>ユーザーID</label><input id="rss-uid" type="text" placeholder="例: 19102577" inputmode="numeric"></div>
      <div class="code-box" id="rss-user">ユーザーIDを入力してください</div>
      <div class="btn-row" style="margin-top:12px">
        <button class="btn" data-copy="rss-user">コピー</button>
        <button class="btn ghost" id="rss-user-open">開く</button>
      </div>
    </div>

    <div class="panel">
      <h2>タグ / 検索の新着</h2>
      <p class="hint">タグやキーワードの検索結果フィード。</p>
      <div class="field"><label>キーワード</label><input id="rss-word" type="text" placeholder="例: オリジナル 風景"></div>
      <div class="code-box" id="rss-search">キーワードを入力してください</div>
      <div class="btn-row" style="margin-top:12px">
        <button class="btn" data-copy="rss-search">コピー</button>
        <button class="btn ghost" id="rss-search-open">開く</button>
      </div>
    </div>`;

  const uid = main.querySelector("#rss-uid");
  const word = main.querySelector("#rss-word");
  const userBox = main.querySelector("#rss-user");
  const searchBox = main.querySelector("#rss-search");
  uid.addEventListener("input", () => {
    userBox.textContent = uid.value.trim() ? rssUrl(`user/${encodeURIComponent(uid.value.trim())}`) : "ユーザーIDを入力してください";
  });
  word.addEventListener("input", () => {
    searchBox.textContent = word.value.trim() ? rssUrl(`search?word=${encodeURIComponent(word.value.trim())}`) : "キーワードを入力してください";
  });
  main.querySelector("#rss-user-open").addEventListener("click", () => {
    if (uid.value.trim()) window.open(rssUrl(`user/${encodeURIComponent(uid.value.trim())}`), "_blank", "noopener");
  });
  main.querySelector("#rss-search-open").addEventListener("click", () => {
    if (word.value.trim()) window.open(rssUrl(`search?word=${encodeURIComponent(word.value.trim())}`), "_blank", "noopener");
  });
  main.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", () => {
    const text = main.querySelector("#" + b.dataset.copy).textContent;
    if (text.startsWith("http")) { navigator.clipboard.writeText(text); toast("コピーしました", "ok"); }
    else { toast("先に入力してください", "err"); }
  }));
}

// ---------- 認証 ----------
function renderAuth(main) {
  const authed = state.status.authenticated;
  main.innerHTML = `
    <div class="view-head">
      <div>
        <div class="eyebrow">access · 認証</div>
        <h1>pixiv ログイン</h1>
        <p>refresh_token をダッシュボード内で取得します。トークンは暗号化して保存され、サーバーの平文には残りません。</p>
      </div>
    </div>
    ${authed ? `
    <div class="panel">
      <h2>ログイン済み</h2>
      <p class="hint">アカウント：<strong>${esc(state.status.pixiv_user) || "(名称不明)"}</strong></p>
      <button class="btn" id="logout">ログアウト</button>
    </div>` : ""}
    <div class="panel">
      <h2>方法A · ブラウザ認証（PKCE）</h2>
      <p class="hint">pixiv公式のログイン画面で認証し、リダイレクト先URLに含まれる <code>code</code> を貼り付けます。</p>
      <div class="steps">
        <div class="step"><div class="num"></div><div>
          <h3>ログインURLを生成</h3>
          <p>ボタンを押すと新しいタブでpixivのログイン画面が開きます。<strong>code は数十秒で失効</strong>するので、ログイン後は手早く次の手順へ。失敗したら下の同じリンクを開き直せば再取得できます。</p>
          <button class="btn primary" id="begin">ログインURLを開く</button>
          <p class="hint" id="login-link" style="margin-top:12px"></p>
        </div></div>
        <div class="step"><div class="num"></div><div>
          <h3>リダイレクトURLを貼り付け</h3>
          <p>ログインを完了すると「ページが見つかりません」等の画面に飛びます。そのとき<strong>ブラウザのアドレスバーに表示されているURL全体</strong>をコピーして、下に貼り付けてください。<code>code</code> は自動で抽出されます（コード単体の貼り付けも可）。</p>
          <div class="field"><label>リダイレクトURL または code</label><input id="code" type="text" placeholder="https://app-api.pixiv.net/.../callback?state=...&code=..."></div>
          <p class="hint" id="code-detect"></p>
        </div></div>
        <div class="step"><div class="num"></div><div>
          <h3>交換</h3>
          <p>code を refresh_token に交換して保存します。</p>
          <button class="btn primary" id="complete" disabled>refresh_tokenを取得</button>
        </div></div>
      </div>
    </div>
    <div class="panel">
      <h2>方法B · refresh_token を直接入力</h2>
      <p class="hint">既に refresh_token をお持ちの場合はこちら。</p>
      <div class="field"><label>refresh_token</label><input id="rt" type="password" placeholder="既存のトークンを貼り付け"></div>
      <button class="btn" id="rtsave">保存して検証</button>
    </div>`;

  let authState = null;
  const lo = main.querySelector("#logout");
  if (lo) lo.addEventListener("click", async () => { await api.logout(); state.status = await api.status(); render(); });

  main.querySelector("#begin").addEventListener("click", async () => {
    try {
      const r = await api.authBegin();
      authState = r.state;
      window.open(r.login_url, "_blank", "noopener");
      main.querySelector("#complete").disabled = false;
      // 同じURL(同じチャレンジ)を開き直して新しいcodeを取れるようリンクを残す
      main.querySelector("#login-link").innerHTML =
        `失効したら同じリンクを開き直す → <a href="${r.login_url}" target="_blank" rel="noopener" style="color:var(--vermilion)">ログインページを再度開く</a>`;
      toast("ログイン画面を開きました。codeを取得してください。");
    } catch (e) { toast(e.message, "err"); }
  });
  const extractCode = (raw) => {
    const m = (raw || "").match(/code=([^&\s]+)/);
    return (m ? m[1] : (raw || "")).trim();
  };
  const codeInput = main.querySelector("#code");
  const detect = main.querySelector("#code-detect");
  codeInput.addEventListener("input", () => {
    const code = extractCode(codeInput.value);
    detect.textContent = code ? `✓ codeを検出: ${code.slice(0, 10)}…` : "";
    detect.style.color = code ? "var(--jade)" : "";
  });
  main.querySelector("#complete").addEventListener("click", async () => {
    const code = extractCode(codeInput.value);
    if (!code || !authState) return toast("先にログインURLを開いてください。", "err");
    try {
      const r = await api.authComplete(authState, code);
      toast(`ログイン成功: ${r.pixiv_user || ""}`, "ok");
      state.status = await api.status(); render();
    } catch (e) { toast(e.message, "err"); }
  });
  main.querySelector("#rtsave").addEventListener("click", async () => {
    const rt = main.querySelector("#rt").value.trim();
    if (!rt) return;
    try {
      const r = await api.authToken(rt);
      toast(`ログイン成功: ${r.pixiv_user || ""}`, "ok");
      state.status = await api.status(); render();
    } catch (e) { toast(e.message, "err"); }
  });
}

// ---------- 設定 ----------
async function renderSettings(main) {
  main.innerHTML = `<div class="center-load"><span class="spinner"></span> 読み込み中…</div>`;
  state.settings = await api.getSettings();
  const s = state.settings;
  const smb = s.smb, dl = s.download;
  main.innerHTML = `
    <div class="view-head">
      <div>
        <div class="eyebrow">configuration · 設定</div>
        <h1>スタジオ設定</h1>
        <p>すべての設定はここで完結します。値は暗号化ボリュームに保存されます。</p>
      </div>
    </div>

    <div class="panel">
      <h2>SMB 保存先</h2>
      <p class="hint">ダウンロードした作品はすべてこの共有へ直接書き込まれます。</p>
      <div class="grid-2">
        <div class="field"><label>ホスト / IP</label><input id="smb_host" type="text" value="${esc(smb.host)}" placeholder="192.168.1.10"></div>
        <div class="field"><label>ポート</label><input id="smb_port" type="number" value="${smb.port}"></div>
        <div class="field"><label>共有名 (share)</label><input id="smb_share" type="text" value="${esc(smb.share)}" placeholder="media"></div>
        <div class="field"><label>保存ベースパス</label><input id="smb_base" type="text" value="${esc(smb.base_path)}" placeholder="pixiv"></div>
        <div class="field"><label>ユーザー名</label><input id="smb_user" type="text" value="${esc(smb.username)}"></div>
        <div class="field"><label>パスワード</label><input id="smb_pass" type="password" value="${smb.password ? "********" : ""}"></div>
        <div class="field"><label>ドメイン (任意)</label><input id="smb_domain" type="text" value="${esc(smb.domain)}"></div>
      </div>
      <div class="btn-row">
        <button class="btn primary" id="save_smb">保存</button>
        <button class="btn" id="test_smb">接続テスト</button>
      </div>
    </div>

    <div class="panel">
      <h2>ダウンロード</h2>
      <div class="field"><label>ファイル名テンプレート</label><input id="dl_tpl" type="text" value="${esc(dl.filename_template)}"></div>
      <p class="hint">使用可能：<code>{artist} {artist_id} {title} {illust_id} {page} {ext} {date}</code></p>
      <div class="grid-2">
        <div class="field"><label>同時ダウンロード数 (要再起動)</label><input id="dl_conc" type="number" min="1" max="6" value="${dl.concurrency}"></div>
      </div>
      <label class="check"><input type="checkbox" id="dl_zip" ${dl.zip_per_work ? "checked" : ""}> 作品ごとにZIP化（全ページ＋メタを1ファイルに）</label>
      <label class="check"><input type="checkbox" id="dl_meta" ${dl.save_metadata ? "checked" : ""}> メタデータ(JSON)を保存</label>
      <label class="check"><input type="checkbox" id="dl_ugo" ${dl.download_ugoira ? "checked" : ""}> うごイラ(zip)をダウンロード</label>
      <label class="check"><input type="checkbox" id="dl_skip" ${dl.skip_existing ? "checked" : ""}> 既存ファイルをスキップ</label>
      <div class="btn-row"><button class="btn primary" id="save_dl">保存</button></div>
    </div>

    <div class="panel">
      <h2>Chrome拡張 連携</h2>
      <p class="hint">拡張機能の設定にこのダッシュボードURLとAPIトークンを登録すると、複数タブを一括でキューへ送れます。</p>
      <div class="field"><label>API トークン</label><div class="code-box" id="apitok">${esc(state.status.api_token)}</div></div>
      <div class="btn-row">
        <button class="btn" id="copytok">コピー</button>
        <button class="btn ghost" id="rotate">再生成</button>
      </div>
    </div>`;

  const v = (id) => main.querySelector("#" + id).value;
  const c = (id) => main.querySelector("#" + id).checked;

  main.querySelector("#save_smb").addEventListener("click", async () => {
    const pass = v("smb_pass");
    const smbPatch = {
      host: v("smb_host"), port: Number(v("smb_port")) || 445, share: v("smb_share"),
      base_path: v("smb_base"), username: v("smb_user"), domain: v("smb_domain"),
    };
    if (pass !== "********") smbPatch.password = pass;
    try { await api.updateSettings({ smb: smbPatch }); state.status = await api.status(); toast("SMB設定を保存しました", "ok"); }
    catch (e) { toast(e.message, "err"); }
  });
  main.querySelector("#test_smb").addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "接続中…";
    try { await api.smbTest(); toast("SMB接続に成功しました", "ok"); }
    catch (err) { toast(err.message, "err"); }
    finally { e.target.disabled = false; e.target.textContent = "接続テスト"; }
  });
  main.querySelector("#save_dl").addEventListener("click", async () => {
    try {
      await api.updateSettings({ download: {
        filename_template: v("dl_tpl"), concurrency: Number(v("dl_conc")) || 2,
        save_metadata: c("dl_meta"), download_ugoira: c("dl_ugo"), skip_existing: c("dl_skip"),
        zip_per_work: c("dl_zip"),
      }});
      toast("ダウンロード設定を保存しました", "ok");
    } catch (e) { toast(e.message, "err"); }
  });
  main.querySelector("#copytok").addEventListener("click", () => {
    navigator.clipboard.writeText(state.status.api_token); toast("コピーしました", "ok");
  });
  main.querySelector("#rotate").addEventListener("click", async () => {
    const r = await api.rotateToken();
    state.status.api_token = r.api_token;
    main.querySelector("#apitok").textContent = r.api_token;
    toast("APIトークンを再生成しました（拡張機能の再設定が必要）", "ok");
  });
}

boot();
