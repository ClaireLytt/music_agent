"""Static front-end assets for the Gradio app: the global JS (Blocks
head) and the stylesheet. Split out of ui.py — plain string constants,
no imports."""

_HEAD_JS = """
<script>
// 🕵️ 考据页 AI 助手：默认收起，右上角 💬 按需展开
(function() {
  function panel() { return document.getElementById('ll-lore-chat'); }
  function hidden() {
    const p = panel();
    return !!(p && p.classList.contains('ll-lc-hidden'));
  }
  function refreshTip(btn) {
    const tip = btn.querySelector('.ll-sb-tip');
    if (tip) tip.textContent = hidden() ? '展开 AI 助手' : '收起 AI 助手';
  }
  const t = setInterval(() => {
    const p = panel();
    if (!p) return;
    clearInterval(t);
    let shown = '';
    try { shown = localStorage.getItem('ll_lore_chat') || ''; } catch (e) {}
    if (shown !== '1') p.classList.add('ll-lc-hidden');   // 默认隐藏
    const btn = document.createElement('button');
    btn.id = 'll-lore-chat-btn';
    btn.innerHTML = '💬<span class="ll-sb-tip"></span>';
    btn.addEventListener('click', () => {
      p.classList.toggle('ll-lc-hidden');
      try {
        localStorage.setItem('ll_lore_chat', hidden() ? '0' : '1');
      } catch (e) {}
      refreshTip(btn);
    });
    document.body.appendChild(btn);
    refreshTip(btn);
    setInterval(() => {   // 只在考据子页签可见时显示按钮
      const main = document.getElementById('ll-lore-main');
      btn.style.display = (main && main.offsetParent !== null) ? '' : 'none';
    }, 400);
  }, 400);
})();
// 🎵 歌单侧栏收起/展开（仿 Claude 网页版：左上角图标 + 黑色气泡提示 +
// Ctrl+B 快捷键，偏好记入 localStorage）
(function() {
  function sidebar() { return document.getElementById('ll-sidebar'); }
  function hidden() {
    const sb = sidebar();
    return !!(sb && sb.classList.contains('ll-sb-hidden'));
  }
  function refreshTip(btn) {
    const tip = btn.querySelector('.ll-sb-tip');
    if (tip) tip.innerHTML = (hidden() ? '显示歌单' : '隐藏歌单')
      + ' <kbd>Ctrl+B</kbd>';
  }
  function toggle(btn) {
    const sb = sidebar();
    if (!sb) return;
    sb.classList.toggle('ll-sb-hidden');
    try {
      localStorage.setItem('ll_sidebar', hidden() ? '0' : '1');
    } catch (err) {}
    refreshTip(btn);
  }
  const t = setInterval(() => {
    const sb = sidebar();
    if (!sb) return;
    clearInterval(t);
    try {   // 记忆：上次收起则保持收起
      if (localStorage.getItem('ll_sidebar') === '0')
        sb.classList.add('ll-sb-hidden');
    } catch (err) {}
    const btn = document.createElement('button');
    btn.id = 'll-sb-btn';
    btn.innerHTML = '◧<span class="ll-sb-tip"></span>';
    btn.addEventListener('click', () => toggle(btn));
    document.body.appendChild(btn);
    refreshTip(btn);
    // 只在播放解读页显示切换按钮（歌单只在那页）
    setInterval(() => {
      const lc = document.getElementById('lyrics-container');
      btn.style.display = (lc && lc.offsetParent !== null) ? '' : 'none';
    }, 400);
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'b' || e.key === 'B')) {
        e.preventDefault();
        toggle(btn);
      }
    });
  }, 400);
})();
// 🎮 竞猜/拼图：Enter 两段式——未出结果时 Enter=提交，出结果后 Enter=下一题
(function() {
  const GAMES = [
    {res: 'll-quiz-result', submit: '提交答案', next: '开始 / 下一题'},
    {res: 'll-blank-result', submit: '🧩 拼好了', next: '🧩 来一题'},
  ];
  function visibleBtn(text) {
    for (const b of document.querySelectorAll('button'))
      if (b.offsetParent !== null && b.textContent.includes(text)) return b;
    return null;
  }
  function activeGame() {
    for (const g of GAMES) {
      const res = document.getElementById(g.res);
      if (res && res.offsetParent !== null) return g;
    }
    return null;
  }
  document.addEventListener('keydown', (e) => {
    if (e.isComposing) return;
    const tag = (e.target.tagName || '').toLowerCase();
    const type = (e.target.type || '').toLowerCase();
    // 文本输入框里的按键不抢（打字练习/聊天各有自己的行为）
    if (tag === 'textarea'
        || (tag === 'input' && type !== 'radio' && type !== 'checkbox'))
      return;
    const g = activeGame();
    if (!g) return;
    // 1-4 选第 N 个选项
    if (/^[1-4]$/.test(e.key)) {
      const opts = [...document.querySelectorAll('input[type=radio]')]
        .filter((i) => i.offsetParent !== null
                       && i.closest('.tabitem'));
      const idx = Number(e.key) - 1;
      if (opts[idx]) { e.preventDefault(); opts[idx].click(); }
      return;
    }
    if (e.key !== 'Enter') return;
    const answered = /[✅❌]/.test(
      document.getElementById(g.res).textContent);
    const btn = visibleBtn(answered ? g.next : g.submit);
    if (btn) { e.preventDefault(); btn.click(); }
  });
})();
window.llz = function() {   // body CSS zoom 校正系数
  return parseFloat(getComputedStyle(document.body).zoom) || 1;
};
window.llSend = function(id, value) {  // 写隐藏 gradio 通道并通知后端
  const box = document.querySelector('#' + id + ' textarea, #' + id + ' input');
  if (!box) return false;
  box.value = value;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  return true;
};
// force Gradio's light theme so the UI is always white regardless of the
// OS dark-mode setting (Gradio otherwise follows prefers-color-scheme)
(function() {
  try {
    const u = new URL(window.location);
    if (u.searchParams.get('__theme') !== 'light') {
      u.searchParams.set('__theme', 'light');
      window.location.replace(u);
    }
  } catch (e) {}
})();
// keep the selected song visible inside the capped song list (only when
// the selection changes — never fight the user's own scrolling)
(function() {
  let lastSel = null;
  setInterval(() => {
    const c = document.querySelector('#ll-songs input[type=radio]:checked');
    if (!c || c.value === lastSel) return;
    const first = lastSel === null;
    lastSel = c.value;
    const label = c.closest('label');
    if (label) label.scrollIntoView({ block: 'nearest' });
    // song changed -> drop the stale picked-line index so a later
    // favorite/ask doesn't act on the previous song's line
    if (!first) {
      const lp = document.querySelector('#ll-line-pick textarea, #ll-line-pick input');
      if (lp && lp.value) { lp.value = ''; lp.dispatchEvent(new Event('input', { bubbles: true })); }
    }
    // evidence-card jump: once the cited song's lyrics are up, scroll to
    // the cited line and flash it
    const pend = window.__llPendingLine;
    if (pend != null && pend >= 0) {
      let tries = 0;
      // the OLD song's lyrics may still be mounted when the radio flips —
      // only flash once the rendered title matches the newly checked radio
      // (covers both orders: render-before-watcher and watcher-before-render)
      const want = c.value;
      const t = setInterval(() => {
        const titleEl = document.querySelector('.song-title-display');
        const title = titleEl ? titleEl.textContent.trim() : '';
        const ready = title && (want === title
                                || want.indexOf(title + ' — ') === 0);
        if (!ready) { if (++tries > 40) clearInterval(t); return; }
        const el = document.querySelector(
          '#lyrics-scroll .lyric-line[data-index="' + pend + '"]');
        if (el) {
          clearInterval(t);
          el.scrollIntoView({ block: 'center' });
          el.classList.add('cite-flash');
          // probes/tests: survives the node being re-rendered mid-flash
          window.__llCiteFlashAt = Date.now();
          setTimeout(() => el.classList.remove('cite-flash'), 2600);
        } else if (++tries > 40) clearInterval(t);
      }, 250);
      window.__llPendingLine = null;
    }
  }, 800);
})();
// mini translator: double-click an English word inside the lyrics ->
// popover anchored at the selection with the offline dictionary meaning,
// an optional AI in-context explanation and a ⭐ wordbook button
(function() {
  // 多卡并存：每张弹卡用 dataset.q 认领自己的后端结果，互不干扰
  let lastSpoken = '';  // the data.q already auto-pronounced
  // pronunciation à la qwerty-learner: youdao dictvoice, client-side only
  const voiceUrl = (w) =>
    'https://dict.youdao.com/dictvoice?audio=' + encodeURIComponent(w)
    + '&type=2';
  function sayWord(w) {
    if (w) new Audio(voiceUrl(w)).play().catch(() => {});
  }
  function closeAll() {
    document.querySelectorAll('.ll-dict-pop').forEach((p) => p.remove());
  }
  function wireClose(pop) {
    const x = pop.querySelector('.dict-close');
    if (x) x.addEventListener('click', (e) => {
      e.stopPropagation();
      pop.remove();
    });
  }
  // 弹卡可拖动：按住卡片空白处（按钮除外）移动
  function makeDraggable(pop) {
    let sx = 0, sy = 0, px = 0, py = 0, moved = false;
    pop.addEventListener('pointerdown', (e) => {
      // 按钮/✕ 不作为拖动起点（pointer capture 会吞掉它们的 click）
      if (e.target.closest('button, .dict-close')) return;
      sx = e.clientX; sy = e.clientY; moved = false;
      const r = pop.getBoundingClientRect();
      const z = window.llz();
      px = r.left / z; py = r.top / z;
      pop.setPointerCapture(e.pointerId);
      const onMove = (ev) => {
        const z2 = window.llz();
        const dx = (ev.clientX - sx) / z2, dy = (ev.clientY - sy) / z2;
        if (!moved && Math.abs(dx) + Math.abs(dy) < 4) return;
        moved = true;
        pop.style.left = Math.max(0, px + dx) + 'px';
        pop.style.top = Math.max(0, py + dy) + 'px';
      };
      const onUp = (ev) => {
        pop.releasePointerCapture(e.pointerId);
        pop.removeEventListener('pointermove', onMove);
        pop.removeEventListener('pointerup', onUp);
      };
      pop.addEventListener('pointermove', onMove);
      pop.addEventListener('pointerup', onUp);
    });
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAll();
  });
  function lookupSelection(e) {
    const sel = window.getSelection();
    // \u6b4c\u8bcd\u884c\u4ece\u300c\u9009\u533a\u300d\u53cd\u63a8\uff0c\u800c\u4e0d\u662f\u9f20\u6807\u677e\u5f00\u7684\u4f4d\u7f6e\u2014\u2014\u62d6\u51fa\u884c\u5916\u677e\u624b\u4e5f\u80fd\u67e5
    let anchor = sel && sel.anchorNode;
    if (anchor && anchor.nodeType === 3) anchor = anchor.parentElement;
    const lineEl = (anchor && anchor.closest
                    && anchor.closest('.lyric-line'))
      || (e.target.closest && e.target.closest('.lyric-line'));
    if (!lineEl) return;
    const raw = (sel ? sel.toString() : '').trim().replace(/\\s+/g, ' ');
    // \u5355\u8bcd\uff0c\u6216\u62d6\u9009 2-16 \u4e2a\u8bcd\u7684\u8bcd\u7ec4\u3002\u62d6\u5230\u884c\u5c3e\u65f6\u9009\u533a\u5e38\u5e26\u4e0a
    // \u540c\u884c\u7684\u4e2d\u6587\u7ffb\u8bd1\uff0c\u6240\u4ee5\u4ece\u5f00\u5934\u300c\u63d0\u53d6\u300d\u82f1\u6587\u8bcd\u7ec4\u800c\u4e0d\u662f\u6574\u4f53\u5339\u914d
    const m = raw.match(/^[A-Za-z][A-Za-z'\u2019-]{1,31}(?: [A-Za-z][A-Za-z'\u2019,.-]{0,31}){0,15}/);
    if (!m) return;
    const word = m[0].replace(/[,.-]+$/, '');
    const pops = document.querySelectorAll('.ll-dict-pop');
    if (pops.length >= 4) pops[0].remove();   // 最多同屏 4 张，顶掉最旧的
    const line = (lineEl.querySelector('.lyric-text') || lineEl).textContent.trim();
    const titleEl = document.querySelector('.song-title-display');
    const song = titleEl ? titleEl.textContent.trim() : '';
    const pop = document.createElement('div');
    pop.className = 'll-dict-pop';
    pop.dataset.word = word;
    pop.dataset.line = line;
    pop.dataset.song = song;
    pop.innerHTML = '<div class="dict-word">' + word
      + ' <span class="dict-close" title="关闭">✕</span></div>'
      + '<div class="dict-body">⏳ 查询中…</div>';
    wireClose(pop);
    let rect = lineEl.getBoundingClientRect();
    try {
      const r = sel.getRangeAt(0).getBoundingClientRect();
      if (r && r.width) rect = r;
    } catch (err) {}
    const z0 = window.llz();
    pop.style.left = Math.min(rect.left / z0,
                              window.innerWidth / z0 - 300) + 'px';
    pop.style.top = Math.min(rect.bottom / z0 + 6,
                             window.innerHeight / z0 - 160) + 'px';
    document.body.appendChild(pop);
    makeDraggable(pop);
    pop.dataset.q = word + '\\t' + line + '\\t' + song + '\\t' + Date.now();
    window.llSend('ll-dict-pick', pop.dataset.q);
  }
  document.addEventListener('dblclick', lookupSelection);
  document.addEventListener('mouseup', (e) => {
    // 拖选词组：选区含空格才走这里（单词仍由 dblclick 负责）。
    // 稍等一拍让浏览器先敲定选区，再按选区反推歌词行
    setTimeout(() => {
      const sel = window.getSelection();
      const s = (sel ? sel.toString() : '').trim();
      if (s.includes(' ')) lookupSelection(e);
    }, 10);
  });
  function render(pop, data) {
    if (!pop) return;
    const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
    let html = '<div class="dict-word">' + esc(data.word);
    if (data.phonetic) html += ' <span class="dict-phon">/' + esc(data.phonetic) + '/</span>';
    html += ' <button class="dict-btn dict-say" data-dict-say '
          + 'title="重播发音">🔊</button>'
          + ' <span class="dict-close" title="关闭">✕</span></div>';
    if (data.found) {
      html += '<div class="dict-body">'
        + esc(data.translation).split('\\n').join('<br>') + '</div>';
    } else {
      html += '<div class="dict-body dict-miss">本地词典没有这个词'
        + '，试试 ✨ AI 解释。</div>';
    }
    if (data.ai) html += '<div class="dict-ai">✨ ' + esc(data.ai) + '</div>';
    html += '<div class="dict-actions">';
    if (data.canFav) html += '<button class="dict-btn" data-dict-fav>⭐ 收藏单词</button>';
    if (!data.ai) html += '<button class="dict-btn" data-dict-ai>✨ AI 语境解释</button>';
    html += '</div>';
    pop.innerHTML = html;
    wireClose(pop);
    const favBtn = pop.querySelector('[data-dict-fav]');
    if (favBtn) favBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      window.llSend('ll-wb-act', 'add:' + pop.dataset.word + '\\t'
                  + pop.dataset.line + '\\t' + pop.dataset.song
                  + '\\t' + Date.now());
      favBtn.textContent = '✓ 已收藏';
      favBtn.disabled = true;
    });
    const sayBtn = pop.querySelector('[data-dict-say]');
    if (sayBtn) sayBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      sayWord(pop.dataset.word);
    });
    // auto-pronounce once per lookup (the AI reply re-renders the same q)
    if (data.q !== lastSpoken) {
      lastSpoken = data.q;
      sayWord(data.word);
    }
    const aiBtn = pop.querySelector('[data-dict-ai]');
    if (aiBtn) aiBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      aiBtn.textContent = '✨ 生成中…';
      aiBtn.disabled = true;
      pop.dataset.q = pop.dataset.word + '\\t' + pop.dataset.line + '\\t'
                      + pop.dataset.song + '\\t' + Date.now();
      window.llSend('ll-dict-ai', pop.dataset.q);
    });
  }
  let lastSeen = '';
  setInterval(() => {
    // 卡在「查询中」的卡片重发查询：共享输出通道上，快速连查时
    // 前一个结果可能被后一个覆盖而没被轮询看到（查询是本地词典，重发零成本）
    for (const p of document.querySelectorAll('.ll-dict-pop')) {
      if (!p.querySelector('.dict-actions')
          && Date.now() - Number(p.dataset.q.split('\\t').pop()) > 3000
          && Number(p.dataset.retries || 0) < 3) {
        p.dataset.retries = Number(p.dataset.retries || 0) + 1;
        p.dataset.q = p.dataset.word + '\\t' + p.dataset.line + '\\t'
                      + p.dataset.song + '\\t' + Date.now();
        window.llSend('ll-dict-pick', p.dataset.q);
      }
    }
    const box = document.querySelector('#ll-dict-out textarea, #ll-dict-out input');
    if (!box || !box.value || box.value === lastSeen) return;
    lastSeen = box.value;
    let data;
    try { data = JSON.parse(box.value); } catch (err) { return; }
    // 把结果路由给认领这个 q 的那张卡；没有就是已关闭/过期
    for (const p of document.querySelectorAll('.ll-dict-pop'))
      if (p.dataset.q === data.q) { render(p, data); return; }
  }, 300);
})();
// ⌨️ 单词练习: qwerty-learner-style keystroke loop. The backend renders a
// .ll-type-card (data-word/data-mp3/data-nonce); this block owns typing:
// correct letters color up, one wrong key resets the whole word, completion
// reports through the ll-review-done channel.
(() => {
  let nonce = null, pos = 0, mistakes = 0, t0 = 0, done = false;
  let peeks = 0, sawPlain = false;  // 盲打统计：Tab 偷看次数 / 是否露过字母
  const card = () => document.querySelector('.ll-type-card');
  const chars = (c) => c.querySelectorAll('.tp-ch');
  function reset(c) {
    pos = 0;
    chars(c).forEach((el) => el.classList.remove('ok'));
  }
  function play(c) {
    if (c.dataset.mp3) new Audio(c.dataset.mp3).play().catch(() => {});
  }
  // ── 会话统计（qwerty-learner 式）：时间/输入数/WPM/正确数/正确率 ──
  // 公式同 qwerty-learner：输入数 = 对 + 错按键；正确率 = 对/输入数；
  // WPM = 完成单词数 / 秒 × 60。暂停时计时与计数全部冻结；
  // 切出歌曲寻词页签 = 本轮结束（清零）。
  let dsRun = false, dsTime = 0, dsOk = 0, dsBad = 0, dsWords = 0;
  const dsPanel = () => document.getElementById('ll-drill-stats');
  function dsSet(id, v) {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  }
  function dsPaint() {
    const mm = String(Math.floor(dsTime / 60)).padStart(2, '0');
    const ss = String(dsTime % 60).padStart(2, '0');
    const sum = dsOk + dsBad;
    dsSet('ll-ds-time', mm + ':' + ss);
    dsSet('ll-ds-input', String(sum));
    dsSet('ll-ds-wpm',
          String(dsTime ? Math.round((dsWords / dsTime) * 60) : 0));
    dsSet('ll-ds-correct', String(dsOk));
    dsSet('ll-ds-acc',
          Math.round((dsOk / (sum === 0 ? 1 : sum)) * 100) + '%');
    const btn = document.getElementById('ll-ds-pause');
    if (btn) btn.textContent = dsRun ? '⏸ 暂停' : '▶ 开始';
  }
  function dsSetRun(run) {
    dsRun = run;
    dsPaint();
    if (run) {
      const c = card();
      const inp = c && c.querySelector('.ll-type-input');
      if (inp) inp.focus();
    }
  }
  function dsEnd() {  // 退出寻词页 = 本轮结束
    dsRun = false;
    dsTime = dsOk = dsBad = dsWords = 0;
    dsPaint();
  }
  setInterval(() => {
    const p = dsPanel();
    if (!p) return;
    if (p.offsetParent === null) {         // 不在寻词页签
      if (dsRun || dsTime > 0) dsEnd();
      return;
    }
    // 悬停快捷键气泡：给 Gradio 的开始按钮补 data-ds-tip
    for (const b of document.querySelectorAll('button'))
      if (b.textContent.includes('开始 / 换一词') && !b.dataset.dsTip)
        b.dataset.dsTip = '开始 / 换一词；Space 暂停/继续';
    if (dsRun) { dsTime += 1; dsPaint(); }
  }, 1000);
  document.addEventListener('click', (e) => {
    if (!e.target.closest) return;
    if (e.target.closest('#ll-ds-pause')) { dsSetRun(!dsRun); return; }
    const b = e.target.closest('button');
    if (b && b.textContent.includes('开始 / 换一词')) dsSetRun(true);
  }, true);
  // Space = 开始/暂停（仅寻词页；焦点在打字框外也生效，capture 挡住
  // 全局的音频空格快捷键）
  document.addEventListener('keydown', (e) => {
    if (e.code !== 'Space') return;
    const p = dsPanel();
    if (!p || p.offsetParent === null) return;
    if (e.target.classList
        && e.target.classList.contains('ll-type-input')) return;  // 打字框内走下方逻辑
    const tag = (e.target.tagName || '').toLowerCase();
    const type = (e.target.type || '').toLowerCase();
    if (tag === 'textarea' || (tag === 'input'
        && !['radio', 'checkbox', 'button', 'range'].includes(type))) return;
    e.preventDefault();
    e.stopPropagation();
    dsSetRun(!dsRun);
  }, true);
  // 开始/暂停按钮钉在例句卡（没有例句则单词卡）下方右对齐
  // （卡片在 review_html 里随词重渲染，Gradio 组件不能搬进去，
  // 所以 fixed 定位跟随；没卡片时回归文档流）
  function placeStartRow() {
    const row = document.getElementById('ll-review-startrow');
    if (!row) return;
    const c = card();
    const stats = dsPanel();
    // 有卡片锚例句卡（无例句锚单词卡）下方；无卡片锚统计条右上方
    const anchor = (c && c.offsetParent !== null)
      ? (document.querySelector('.ll-example-card') || c)
      : (stats && stats.offsetParent !== null ? stats : null);
    if (!anchor) {
      row.style.position = ''; row.style.left = ''; row.style.top = '';
      return;
    }
    // 自校正定位：先量当前视口位置，与目标差多少就把样式挪多少——
    // 对 body/容器任意层级的 CSS zoom 都免疫（坐标系不用猜）
    const r = anchor.getBoundingClientRect();
    row.style.position = 'fixed';
    const cur = row.getBoundingClientRect();
    const wantX = r.right - cur.width;
    const wantY = anchor === stats ? r.top - cur.height - 8 : r.bottom + 10;
    const px = parseFloat(row.style.left) || 0;
    const py = parseFloat(row.style.top) || 0;
    if (Math.abs(wantX - cur.left) > 1)
      row.style.left = (px + wantX - cur.left) + 'px';
    if (Math.abs(wantY - cur.top) > 1)
      row.style.top = (py + wantY - cur.top) + 'px';
  }
  ['scroll', 'resize'].forEach((evt) =>
    window.addEventListener(evt, placeStartRow, { passive: true }));
  setInterval(placeStartRow, 300);
  // 一键导出：后端把文件挂上隐藏的 DownloadButton 并往 ll-dl-tick 写
  // "json|anki \t ts"，这里看到新 tick 就代点对应按钮触发浏览器下载，
  // 用户不用再点第二个下载按钮
  let dlTickSeen = '';
  setInterval(() => {
    const box = document.querySelector('#ll-dl-tick textarea, #ll-dl-tick input');
    if (!box || !box.value || box.value === dlTickSeen) return;
    dlTickSeen = box.value;
    const kind = box.value.split('\\t')[0];
    const btn = document.getElementById(
      kind === 'anki' ? 'll-dl-anki' : 'll-dl-json');
    if (btn) btn.click();
  }, 400);
  setInterval(() => {
    const c = card();
    if (!c || c.dataset.nonce === nonce) return;
    nonce = c.dataset.nonce;
    mistakes = 0; t0 = Date.now(); done = false;
    peeks = 0; sawPlain = false;
    reset(c);
    // only grab focus while the practice tab is actually visible
    if (c.offsetParent !== null) {
      const inp = c.querySelector('.ll-type-input');
      if (inp) inp.focus();
      play(c);
    }
    try {  // 卡片默认盲打（服务端烘焙）；记忆为"显示"时才摘除
      if (localStorage.getItem('ll_tp_blind') === '0')
        c.classList.remove('tp-blind');
    } catch (err) {}
  }, 300);
  // focus on pointerdown AND click — belt and braces against focus races
  ['pointerdown', 'click'].forEach((evt) =>
    document.addEventListener(evt, (e) => {
      const c = e.target.closest('.ll-type-card');
      if (!c) return;
      if (evt === 'click' && e.target.closest('[data-ll-say]')) {
        play(c);
        return;
      }
      if (evt === 'click' && e.target.closest('[data-tp-eye]')) {
        const blind = c.classList.toggle('tp-blind');
        try { localStorage.setItem('ll_tp_blind', blind ? '1' : '0'); }
        catch (err) {}
        // 焦点回输入框——否则切换后按键落在按钮上，显示模式下"打不了字"
        const inp2 = c.querySelector('.ll-type-input');
        if (inp2) inp2.focus();
        return;
      }
      const inp = c.querySelector('.ll-type-input');
      if (inp) inp.focus();
    }, true));
  document.addEventListener('keydown', (e) => {
    if (!e.target.classList || !e.target.classList.contains('ll-type-input'))
      return;
    const c = card();
    if (!c) return;
    if (e.key === 'Enter') {       // 跳过 / 打完后继续，都走换一词
      e.preventDefault();
      for (const b of document.querySelectorAll('button'))
        if (b.textContent.includes('开始 / 换一词')) { b.click(); break; }
      return;
    }
    if (done) {                    // 已完成：除 Enter 外不再吃按键
      if (e.key === ' ') e.preventDefault();  // 别让空格滚动页面
      return;
    }
    if (e.isComposing || e.keyCode === 229) {   // CJK IME is active
      c.classList.add('tp-ime');
      e.preventDefault();
      return;
    }
    c.classList.remove('tp-ime');
    if (e.key === 'Tab') {                      // 盲打模式偷看一眼（0.2 秒）
      e.preventDefault();
      if (c.classList.contains('tp-blind')) {
        peeks += 1;
        c.classList.remove('tp-blind');
        const n = c.dataset.nonce;
        setTimeout(() => {
          const cc = card();
          if (cc && cc.dataset.nonce === n) cc.classList.add('tp-blind');
        }, 200);
      }
      return;
    }
    if (e.key === ' ') {
      // 词组里该敲空格且会话进行中 → 当作输入；否则 Space = 开始/暂停
      const expectSpace = !done && c.dataset.word[pos] === ' ';
      if (!dsRun || !expectSpace) {
        e.preventDefault();
        dsSetRun(!dsRun);
        return;
      }
    }
    if (e.key.length !== 1) return;             // let F5/etc through
    e.preventDefault();                          // space must not scroll
    if (!dsRun) {
      // 未开始：首键自动开计时；暂停中：不吃按键
      if (dsTime === 0 && dsOk + dsBad === 0) dsSetRun(true);
      else return;
    }
    const want = c.dataset.word;
    if (!c.classList.contains('tp-blind')) sawPlain = true;  // 本次露过字母
    const spans = chars(c);
    if (e.key.toLowerCase() === want[pos]) {
      dsOk += 1;
      spans[pos].classList.add('ok');
      pos += 1;
      if (pos >= want.length) {
        done = true;
        dsWords += 1;
        c.classList.add('tp-done');
        window.llSend('ll-review-done',
                    want + '\\t' + mistakes + '\\t' + (Date.now() - t0)
                    + '\\t' + (sawPlain ? 0 : 1) + '\\t' + peeks
                    + '\\t' + Date.now());
      }
    } else {
      dsBad += 1;
      mistakes += 1;                             // wrong key: retype it all
      reset(c);
      c.classList.remove('tp-shake');
      void c.offsetWidth;                        // restart the animation
      c.classList.add('tp-shake');
    }
    dsPaint();
  }, true);
})();
// per-song ⋯ menu: the selected row grows a ⋯ button; expanding it
// offers 🗑️ delete (native confirm, then the ll-del-song channel).
// Admin-only: the role-gating block below strips it for viewers.
(function() {
  let menuOpenedAt = 0;
  function closeMenus() {
    document.querySelectorAll('.ll-dots-menu').forEach((m) => m.remove());
  }
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.ll-dots') && !e.target.closest('.ll-dots-menu'))
      closeMenus();
  }, true);
  // the menu is viewport-fixed: close it only when its anchor moves,
  // i.e. the scrolled container holds the dots button (page/song list).
  // An unrelated panel must NOT close it: during playback the lyric sync
  // smooth-scrolls its own container continuously.
  document.addEventListener('scroll', (e) => {
    if (!document.querySelector('.ll-dots-menu')) return;
    // scroll events arrive async: one pending from just before the click
    // (inertia / scroll-into-view) lands right after the menu opens
    if (performance.now() - menuOpenedAt < 200) return;
    const btn = document.querySelector('.ll-dots');
    const t = e.target === document ? document.documentElement : e.target;
    if (!btn || !t || t.nodeType !== 1 || t.contains(btn)) closeMenus();
  }, true);
  setInterval(() => {
    const delBox = document.querySelector('#ll-del-song textarea, #ll-del-song input');
    if (!delBox) return;  // public build: no delete at all
    const roleBox = document.querySelector('#ll-role textarea, #ll-role input');
    if (roleBox && roleBox.value && roleBox.value !== 'admin') return;
    const checked = document.querySelector('#ll-songs input[type=radio]:checked');
    document.querySelectorAll('.ll-dots').forEach((b) => {
      const lab = b.closest('label');
      if (!checked || !lab || !lab.contains(checked)) {
        b.remove();
        closeMenus();
      }
    });
    if (!checked) return;
    const label = checked.closest('label');
    if (!label || label.querySelector('.ll-dots')) return;
    const btn = document.createElement('span');
    btn.className = 'll-dots';
    btn.textContent = '⋯';
    btn.title = '更多操作';
    // keep focus off the row's radio input: label activation would focus
    // it and the browser scrolls it into view inside #ll-songs, and that
    // scroll closes the menu we are about to open
    btn.addEventListener('mousedown', (e) => {
      e.preventDefault();
      e.stopPropagation();
    });
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (document.querySelector('.ll-dots-menu')) { closeMenus(); return; }
      const menu = document.createElement('div');
      menu.className = 'll-dots-menu';
      // viewport-fixed and mounted on <body>: inside the row the dots
      // span's transform would hijack the fixed containing block and the
      // list's overflow would clip the menu out of sight
      const r = btn.getBoundingClientRect();
      const z = window.llz();
      menu.style.top = (r.bottom / z + 4) + 'px';
      menu.style.left = Math.max(8, r.right / z - 150) + 'px';
      const del = document.createElement('button');
      del.type = 'button';
      del.textContent = '🗑️ 删除这首歌';
      del.addEventListener('click', (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        closeMenus();
        const cur = document.querySelector('#ll-songs input[type=radio]:checked');
        if (!cur) return;
        if (!window.confirm('确定永久删除《' + cur.value + '》？\\n'
                            + '（连同歌词/批注/音频目录，不可恢复）')) return;
        window.llSend('ll-del-song', cur.value + '\\t' + Date.now());
      });
      menu.appendChild(del);
      document.body.appendChild(menu);
      menuOpenedAt = performance.now();
    });
    label.appendChild(btn);
  }, 800);
})();
// role gating: the backend writes the login role into #ll-role; for
// non-admins the management tabs are hidden. UI-level gating only.
(function() {
  function applyRole() {
    const box = document.querySelector('#ll-role textarea, #ll-role input');
    if (!box || !box.value || box.value === 'admin') return;
    document.querySelectorAll('button[role="tab"]').forEach((btn) => {
      const t = btn.textContent || '';
      if (t.includes('添加歌曲') || t.includes('⚙️ 设置'))
        btn.style.display = 'none';
    });
    // refresh + per-song ⋯ menu are admin-only too
    const rb = document.querySelector('#ll-refresh-btn');
    if (rb) rb.style.display = 'none';
    document.querySelectorAll('.ll-dots, .ll-dots-menu')
        .forEach((el) => el.remove());
  }
  setInterval(applyRole, 1500);
})();
// stale-page guard: after a server restart, an already-open page keeps a dead
// session and every click silently does nothing — detect the restart via the
// per-launch app_id and reload automatically
(function() {
  let appId = null;
  setInterval(async () => {
    try {
      const r = await fetch('config', { cache: 'no-store' });
      if (!r.ok) return;
      const c = await r.json();
      const id = String(c.app_id || '');
      if (!id) return;
      if (appId === null) appId = id;
      else if (id !== appId) window.location.reload();
    } catch (e) {}
  }, 4000);
})();
(function() {
  let userScrolling = false, scrollTimeout = null, lastActive = -2;

  function getAudio() { return document.getElementById('ll-audio'); }
  // preview clips start mid-song: lyric-time = audio-time + offset
  function getOffset(audio) { return parseFloat(audio.dataset.offset || '0'); }

  function fmt(t) {
    const s = Math.max(0, Math.floor(t));
    return String(Math.floor(s / 60)).padStart(2, '0') + ':' +
           String(s % 60).padStart(2, '0');
  }



  function sync() {
    const audio = getAudio();
    const lines = document.querySelectorAll('#lyrics-scroll .lyric-line');
    if (audio && lines.length) {
      const ms = audio.currentTime * 1000 + getOffset(audio);
      let idx = -1;
      for (let i = lines.length - 1; i >= 0; i--) {
        if (ms >= parseFloat(lines[i].dataset.ts || '0')) { idx = i; break; }
      }
      if (idx !== lastActive) {
        lines.forEach((el, i) => {
          el.classList.toggle('played', i < idx);
          el.classList.toggle('active', i === idx);
          if (i !== idx) {
            const s = el.querySelector('.lyric-text');
            if (s && s.style.backgroundImage) s.style.backgroundImage = '';
          }
        });
        if (idx >= 0 && !userScrolling) {
          // scroll ONLY the lyrics container — scrollIntoView also scrolls the
          // page itself, hijacking clicks on other controls (e.g. search box)
          const c = document.getElementById('lyrics-container');
          const el = lines[idx];
          if (c && el) {
            c.scrollTo({
              top: el.offsetTop - c.clientHeight / 2 + el.offsetHeight / 2,
              behavior: 'smooth',
            });
          }
        }
        lastActive = idx;
      }
      // karaoke sweep on the active line: estimated per-line progress
      // (linear between this line's timestamp and the next one's)
      if (idx >= 0 && !audio.paused) {
        const el = lines[idx];
        const t0 = parseFloat(el.dataset.ts || '0');
        const next = lines[idx + 1];
        const t1 = next ? parseFloat(next.dataset.ts || '0')
                        : (audio.duration || 0) * 1000 + getOffset(audio);
        const p = Math.min(100, Math.max(0, 100 * (ms - t0) / Math.max(t1 - t0, 1)));
        const s = el.querySelector('.lyric-text');
        if (s) {
          s.style.backgroundImage =
            'linear-gradient(90deg, var(--accent) ' + p.toFixed(1) +
            '%, var(--karaoke-rest) ' + p.toFixed(1) + '%)';
        }
      }
    }
    requestAnimationFrame(sync);
  }
  requestAnimationFrame(sync);

  // whole-song echo map: backend writes JSON into #ll-echo-map, we decorate
  // matching lyric lines with a 🥚 marker (idempotent; re-applies after any
  // lyrics re-render, skips maps that belong to a different song)
  setInterval(() => {
    const box = document.querySelector('#ll-echo-map textarea, #ll-echo-map input');
    if (!box || !box.value) return;
    let data;
    try { data = JSON.parse(box.value); } catch (e) { return; }
    const lines = document.querySelectorAll('#lyrics-scroll .lyric-line');
    if (!lines.length) return;
    const title = document.querySelector('.song-title-display');
    if (!title || title.textContent.trim() !== data.song) return;
    const want = new Map((data.lines || []).map(o => [o.i, o]));
    lines.forEach(el => {
      const has = el.querySelector('.echo-mark');
      const o = want.get(parseInt(el.dataset.index));
      if (o && !has) {
        const m = document.createElement('span');
        m.className = 'echo-mark';
        m.title = '彩蛋：与《' + o.song + '》有呼应（相似度 ' + o.sim +
                  '），点击这行查看详情';
        m.textContent = '🥚';
        el.appendChild(m);
      } else if (!o && has) has.remove();
    });
  }, 600);

  // 🎚 offset live preview: backend writes {offset} into #ll-offset-set,
  // we apply it straight onto the audio element — karaoke reads
  // data-offset every frame, so the lyrics shift immediately
  let lastOffsetMsg = null;
  setInterval(() => {
    const box = document.querySelector('#ll-offset-set textarea, #ll-offset-set input');
    if (!box || !box.value || box.value === lastOffsetMsg) return;
    const first = lastOffsetMsg === null;
    lastOffsetMsg = box.value;
    if (first) return;  // page-load leftover
    let data;
    try { data = JSON.parse(box.value); } catch (e) { return; }
    const a = getAudio();
    if (a) a.dataset.offset = String(data.offset || 0);
  }, 300);

  // MCP play-command relay: the backend timer mirrors the command file into
  // #ll-mcp-play; when its value changes, switch happens server-side (radio
  // update) — here we wait for the target song to render, then play (+seek).
  let lastMcp = null;
  setInterval(() => {
    const box = document.querySelector('#ll-mcp-play textarea, #ll-mcp-play input');
    if (!box || !box.value || box.value === lastMcp) return;
    const first = lastMcp === null;
    lastMcp = box.value;
    if (first) return;  // page-load leftover — never replay
    let data;
    try { data = JSON.parse(box.value); } catch (e) { return; }
    if (data.cmd !== 'play') return;
    if (data.line != null) window.__llPendingLine = data.line;
    let tries = 0;
    const t = setInterval(() => {
      const title = document.querySelector('.song-title-display');
      const a = getAudio();
      if (a && title && title.textContent.trim() === data.title) {
        clearInterval(t);
        if (data.line != null) {
          const el = document.querySelector(
            '#lyrics-scroll .lyric-line[data-index="' + data.line + '"]');
          if (el && el.dataset.ts)
            a.currentTime = Math.max(0, (parseFloat(el.dataset.ts) - getOffset(a)) / 1000);
        }
        a.play().catch(() => {});  // autoplay policy may block — harmless
      } else if (++tries > 30) clearInterval(t);
    }, 300);
  }, 700);

  // player-tool buttons + click-to-backend channels (capture phase so a
  // delete click doesn't also trigger the note's data-seek)
  document.addEventListener('click', function(e) {
    if (!e.target.closest) return;
    const audio = getAudio();
    const del = e.target.closest('[data-del-note]');
    if (del) {
      e.stopPropagation();
      window.llSend('ll-note-del', del.dataset.delNote + ':' +
                   (del.dataset.delTs || '') + '\\t' + Date.now());
      return;
    }
    // 📺 B 站视频: collapse/expand (the iframe is always rendered now)
    const vt = e.target.closest('[data-video-toggle]');
    if (vt) {
      const frame = document.querySelector('.bv-frame');
      if (frame) {
        const show = frame.style.display === 'none';
        frame.style.display = show ? '' : 'none';
        const a = getAudio();
        if (a && show) a.pause();
      }
      return;
    }
    // 🎬 MV 彩蛋 ⏱ 锚点: switch to the song on the play tab (backend) and
    // seek its video iframe to the stamp (here, via a bounded retry loop)
    // ✨ per-line annotation: the button is the consent gate — a native
    // confirm makes the single LLM call explicit before anything is spent
    const ga = e.target.closest('[data-gen-ann]');
    if (ga) {
      if (!confirm('将调用 1 次 LLM 为这句歌词生成 AI 批注，继续？')) return;
      ga.textContent = '✨ 生成中…';
      ga.disabled = true;
      window.llSend('ll-gen-ann', ga.dataset.genAnn + '\\t' + Date.now());
      return;
    }
    const tj = e.target.closest('[data-tp-jump]');
    if (tj) {
      // 打字卡出处歌词 -> 切到播放页并闪烁那一句；挂一个返回按钮
      for (const b of document.querySelectorAll('button[role="tab"]'))
        if (b.textContent.includes('播放解读')) { b.click(); break; }
      window.__llPendingLine = parseInt(tj.dataset.tpLine || '-1', 10);
      window.llSend('ll-cite-jump',
                   tj.dataset.tpJump + '\\t' + tj.dataset.tpLine
                   + '\\t' + Date.now());
      if (!document.getElementById('ll-back-typing')) {
        const back = document.createElement('button');
        back.id = 'll-back-typing';
        back.textContent = '↩ 回到打字练习';
        // 歌词区会随切歌整体重渲染，所以按钮挂在 body 上、
        // 用定时器把它钉在歌词容器右上角（歌词不可见时隐藏）
        const anchor = setInterval(() => {
          if (!back.isConnected) { clearInterval(anchor); return; }
          const lc = document.getElementById('lyrics-container');
          if (!lc || lc.offsetParent === null) {
            back.style.display = 'none';
            return;
          }
          const r = lc.getBoundingClientRect();
          const z = window.llz();
          back.style.display = 'block';
          back.style.left = (r.right / z - back.offsetWidth - 12) + 'px';
          back.style.top = (r.top / z + 10) + 'px';
        }, 300);
        back.addEventListener('click', () => {
          for (const b of document.querySelectorAll('button[role="tab"]'))
            if (b.textContent.includes('歌曲寻词')) { b.click(); break; }
          back.remove();
          setTimeout(() => {   // 回来直接能打字/按 Enter，无需先点卡片
            const inp = document.querySelector('.ll-type-input');
            if (inp) inp.focus();
          }, 400);
        });
        document.body.appendChild(back);
      }
      return;
    }
    const bvu = e.target.closest('[data-bvid-unbind]');
    if (bvu) {
      if (!confirm('删除这首歌的视频绑定？（之后可重新搜索或手填）')) return;
      window.llSend('ll-bvid-act', 'unbind	' + Date.now());
      return;
    }
    const bvs = e.target.closest('[data-bvid-search]');
    if (bvs) {
      window.llSend('ll-bvid-act', 'search\\t' + Date.now());
      return;
    }
    const bvp = e.target.closest('[data-bvid-pick]');
    if (bvp) {
      window.llSend('ll-bvid-act',
                   'pick\\t' + bvp.dataset.bvidPick + '\\t' + Date.now());
      return;
    }
    const fav = e.target.closest('[data-fav]');
    if (fav) {
      window.llSend('ll-fav-act', fav.dataset.fav + '\\t' + Date.now());
      return;
    }
    const wn = e.target.closest('[data-wb-note]');
    if (wn) {
      const txt = prompt('给「' + wn.dataset.wbNote
                         + '」写一句我的笔记（清空 = 删除笔记）',
                         wn.dataset.note || '');
      if (txt === null) return;
      window.llSend('ll-wb-act', 'note:' + wn.dataset.wbNote + '\\t'
                   + txt.replace(/[\\t\\n]/g, ' ') + '\\t' + Date.now());
      return;
    }
    const wb = e.target.closest('[data-wb]');
    if (wb) {
      window.llSend('ll-wb-act', wb.dataset.wb + '\\t' + Date.now());
      return;
    }
    const cite = e.target.closest('[data-cite-label]');
    if (cite) {
      // 从考据页/竞猜结果跳转时顺带切回播放页
      if (cite.closest('.lore-page') || cite.classList.contains('cite-go-play'))
        for (const b of document.querySelectorAll('button[role="tab"]'))
          if (b.textContent.includes('播放解读')) { b.click(); break; }
      const lineNo = parseInt(cite.dataset.citeLine || '-1', 10);
      const cur = document.querySelector('#ll-songs input[type=radio]:checked');
      if (cur && cur.value === cite.dataset.citeLabel) {
        // already on the cited song: flash in place (no re-render happens,
        // so the song-switch watcher would never consume a pending line)
        const el = document.querySelector(
          '#lyrics-scroll .lyric-line[data-index="' + lineNo + '"]');
        if (el) {
          el.scrollIntoView({ block: 'center' });
          el.classList.add('cite-flash');
          window.__llCiteFlashAt = Date.now();
          setTimeout(() => el.classList.remove('cite-flash'), 2600);
        }
        return;
      }
      // remember the cited line; the song-switch watcher scrolls to it
      // once the lyrics re-render
      window.__llPendingLine = lineNo;
      window.llSend('ll-cite-jump',
                   cite.dataset.citeLabel + '\\t' + cite.dataset.citeLine
                   + '\\t' + Date.now());
      return;
    }
  }, true);

  // current playback position → hidden channel (used by 听歌笔记)
  setInterval(() => {
    const a = getAudio();
    const box = document.querySelector('#ll-cur-time textarea, #ll-cur-time input');
    if (!box) return;
    // no audio on this song: reset instead of keeping the previous song's
    // position (a note added here would inherit that stale timestamp)
    const v = a ? a.currentTime.toFixed(2) : '0';
    if (box.value !== v) {
      box.value = v;
      box.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }, 700);

  // keep the AI chat scrolled to the bottom while streaming (only when near bottom)
  setInterval(() => {
    const c = document.getElementById('chat-scroll');
    if (!c) return;
    if (c.scrollHeight - c.scrollTop - c.clientHeight < 140) c.scrollTop = c.scrollHeight;
  }, 400);

  document.addEventListener('wheel', function(e) {
    if (e.target.closest && e.target.closest('#lyrics-container')) {
      userScrolling = true;
      clearTimeout(scrollTimeout);
      scrollTimeout = setTimeout(() => { userScrolling = false; }, 5000);
    }
  }, { passive: true });

  // focus assist on pointerdown (fires before click; more reliable when
  // some other handler swallows the click): pressing anywhere on the
  // search field focuses its input
  document.addEventListener('pointerdown', function(e) {
    if (!e.target.closest) return;
    const sw = e.target.closest('#ll-search');
    if (sw) {
      const inp = sw.querySelector('textarea, input');
      if (inp) setTimeout(() => inp.focus(), 0);
    }
  }, true);

  document.addEventListener('click', function(e) {
    if (!e.target.closest) return;
    if (e.target.closest('#ll-search')) return;

    const audio = getAudio();

    // 彩蛋总览 entry: jump to (and select) the referenced lyric line
    const ov = e.target.closest('[data-goto-line]');
    if (ov) {
      const line = document.querySelector(
        '#lyrics-scroll .lyric-line[data-index="' + ov.dataset.gotoLine + '"]');
      if (line) {
        const c = document.getElementById('lyrics-container');
        if (c) {
          c.scrollTo({
            top: line.offsetTop - c.clientHeight / 2 + line.offsetHeight / 2,
            behavior: 'smooth',
          });
        }
        line.click();
      }
      return;
    }

    const seekEl = e.target.closest('[data-seek]');
    if (seekEl && audio) {
      audio.currentTime = Math.max(0,
        (parseFloat(seekEl.dataset.seek) - getOffset(audio)) / 1000);
      audio.play().catch(() => {});
      return;
    }

    const line = e.target.closest('#lyrics-scroll .lyric-line');
    if (line) {
      document.querySelectorAll('.lyric-line.picked').forEach(el => el.classList.remove('picked'));
      line.classList.add('picked');
      // tell the backend which line is selected (feeds the AI assistant panel)
      window.llSend('ll-line-pick', line.dataset.index);
      if (audio && line.dataset.ts) {
        audio.currentTime = Math.max(0,
          (parseFloat(line.dataset.ts) - getOffset(audio)) / 1000);
        audio.play().catch(() => {});
      }
    }
  });

  document.addEventListener('keydown', function(e) {
    // only text-entry elements swallow the shortcuts — radios/checkboxes
    // (e.g. the song list, where focus lands after picking a song) must not,
    // or space/arrows stop working right after the most common action
    const t = e.target;
    const tag = (t.tagName || '').toLowerCase();
    const type = (t.type || '').toLowerCase();
    if (tag === 'textarea' || tag === 'select' || t.isContentEditable) return;
    if (tag === 'input' &&
        !['radio', 'checkbox', 'button', 'range'].includes(type)) return;
    const audio = getAudio();
    if (!audio) return;
    if (e.code === 'Space') {
      e.preventDefault();
      audio.paused ? audio.play().catch(() => {}) : audio.pause();
    } else if (e.key === 'ArrowLeft') {
      audio.currentTime = Math.max(0, audio.currentTime - 5);
    } else if (e.key === 'ArrowRight') {
      audio.currentTime = Math.min(audio.duration || 1e9, audio.currentTime + 5);
    }
  });
})();
// 🧭 新手指引：首次进入自动播放；左下角 ❓ 随时重开。
// 纯前端分步高亮（backdrop 阴影圈出目标元素 + 气泡说明）。
(function() {
  const STEPS = [
    { sel: '#ll-songs',
      text: '🎵 这里是歌曲列表：点歌名切歌，支持筛选和排序；每首歌的 ⋯ 菜单可删除。' },
    { sel: '#lyrics-container',
      text: '📖 听不懂的歌词：<b>单击</b>那一句，右侧 AI 用中文把它讲懂；'
            + '<b>双击英文单词</b>弹词义卡 → ⭐ 收藏生词（带真例句）。' },
    { sel: 'button[role="tab"]',
      text: '🗂 收藏的生词去 <b>🔤 歌曲寻词</b> 盲打练会（可导出 Anki）；'
            + '🎮 互动里有歌迷考据和竞猜，➕ 添加歌曲自动配歌词和 MV，'
            + '⚙️ 设置填 API Key。' },
    { sel: null,
      text: '✅ 就这些！随时点<b>左下角 ❓</b> 重新打开本指引。祝听歌愉快～' },
  ];
  let idx = 0, box = null, ring = null;
  function stop() {
    if (box) box.remove();
    if (ring) ring.remove();
    box = ring = null;
    try { localStorage.setItem('ll_onboard', '1'); } catch (err) {}
  }
  function show(i) {
    idx = i;
    const s = STEPS[i];
    if (!ring) {
      ring = document.createElement('div');
      ring.className = 'll-tour-ring';
      document.body.appendChild(ring);
    }
    const el = s.sel ? document.querySelector(s.sel) : null;
    if (el && el.offsetParent !== null) {
      const r = el.getBoundingClientRect();
      const z = window.llz();
      ring.style.display = 'block';
      ring.style.left = (r.left / z - 6) + 'px';
      ring.style.top = (r.top / z - 6) + 'px';
      ring.style.width = (r.width / z + 12) + 'px';
      ring.style.height = (r.height / z + 12) + 'px';
    } else {
      ring.style.display = 'block';
      ring.style.left = '50%'; ring.style.top = '40%';
      ring.style.width = '0px'; ring.style.height = '0px';
    }
    if (!box) {
      box = document.createElement('div');
      box.className = 'll-onboard-box';
      document.body.appendChild(box);
    }
    box.innerHTML = '<div class="ob-text">' + s.text + '</div>'
      + '<div class="ob-nav"><span class="ob-dots">'
      + STEPS.map((_, k) => k === i ? '●' : '○').join(' ') + '</span>'
      + (i > 0 ? '<button class="ob-btn" data-ob="prev">上一步</button>' : '')
      + (i < STEPS.length - 1
         ? '<button class="ob-btn ob-main" data-ob="next">下一步</button>'
           + '<button class="ob-btn" data-ob="skip">跳过</button>'
         : '<button class="ob-btn ob-main" data-ob="skip">完成</button>')
      + '</div>';
    // 气泡固定在屏幕下方居中，避免遮住被圈出的元素
    box.querySelectorAll('[data-ob]').forEach((b) =>
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        const act = b.dataset.ob;
        if (act === 'next') show(idx + 1);
        else if (act === 'prev') show(idx - 1);
        else stop();
      }));
  }
  function start() { stop(); show(0); }
  // ❓ 重开按钮 + 首次自动播放
  const t = setInterval(() => {
    if (!document.querySelector('#ll-songs')) return;
    clearInterval(t);
    const btn = document.createElement('button');
    btn.id = 'll-onboard-btn';
    btn.title = '新手指引';
    btn.textContent = '❓';
    btn.addEventListener('click', start);
    document.body.appendChild(btn);
    let seen = '1';
    try { seen = localStorage.getItem('ll_onboard') || ''; } catch (err) {}
    if (!seen) setTimeout(start, 800);
  }, 400);
})();
</script>
"""

# ── CSS ───────────────────────────────────────────────────

_CSS = """\
/* 整体默认缩放 75%（等效浏览器 75% 缩放，用户定的默认密度） */
body { zoom: 0.75; }
:root {
  /* 青瓷 Celadon theme (Morandi): grey-teal, muted, porcelain-calm.
     Measured from prototypes/recolor.html th-celadon on 2026-10-06. */
  --bg-primary: #ffffff;
  --bg-page: linear-gradient(160deg, #eef3f2 0%, #ecf1f1 48%, #f1f4f2 100%);
  --bg-secondary: #eff3f1;
  --bg-card: #eff3f1;
  --bg-card-hover: #e2ebe8;
  --text-primary: #35433f;
  --text-secondary: #76867f;
  --text-played: #a5b3ac;
  --accent: #6f948f;
  --accent-2: #8fb0aa; /* light stop of the celadon gradient */
  --accent-grad: linear-gradient(90deg, #8fb0aa, #6f948f);
  --accent-soft: rgba(111, 148, 143, 0.12);
  --accent-glow: rgba(111, 148, 143, 0.18);
  --pink: #527672;     /* selected-lyric "hot" color (celadon deep) */
  --pink-soft: #e9f0ee;
  --border: #dbe5e1;
  --card-shadow: 0 8px 28px rgba(111, 148, 143, 0.16);
  --karaoke-rest: #5d6f6a; /* un-sung part of the active karaoke line */
  --lyric-dim: #a5b3ac; /* upcoming lyric lines */
}

/* NOTE: Gradio's CSS reserializer destroys `background: var()` SHORTHANDS in
   some rules (expands to empty longhands) — use background-image/-color
   longhands whenever the value is a var(). */
body, .gradio-container {
  background-color: #eef3f2 !important;
  background-image: var(--bg-page) !important;
  background-attachment: fixed !important;
}
/* 全宽布局：歌单贴屏幕最左，不留大白边 */
.gradio-container { max-width: 100% !important;
  padding-left: 14px !important; padding-right: 14px !important;
  padding-bottom: 150px !important; /* 整页底部留 ~3 行滚动余量 */ }

/* hide gradio footer (Runs / API / Gradio links) */
footer, .gradio-container footer { display: none !important; }

/* song list & catalog: one song per line, never side by side */
#ll-songs .wrap, #ll-songs [data-testid="radio"], #ll-songs fieldset,
#ll-catalog .wrap, #ll-catalog [data-testid="radio"],
#ll-catalog [data-testid="checkbox-group"], #ll-catalog fieldset {
  display: flex !important;
  flex-direction: column !important;
  align-items: stretch !important;
  gap: 4px !important;
}
#ll-songs label, #ll-catalog label { width: 100%;
  border-radius: 14px !important; border: none !important;
  background: var(--bg-card) !important;
  box-shadow: none !important;
  transition: background 0.15s ease, transform 0.15s ease-out;
}
/* 歌单行：隐藏 radio 圆点,整行(label)点击,选中靠高亮表达。
   opacity 而非 display:none —— 保住可访问树/Playwright 的 radio 角色 */
#ll-songs input[type="radio"] {
  position: absolute; opacity: 0;
  width: 1px; height: 1px; margin: 0;
}
#ll-songs label { padding-left: 14px !important; }
#ll-songs label.selected, #ll-catalog label.selected {
  background: var(--accent-grad) !important;
}
#ll-songs label.selected *, #ll-catalog label.selected * {
  color: #ffffff !important;
}
/* per-song ⋯ menu (selected row only) */
#ll-songs label { position: relative; }
.ll-dots {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  padding: 0 7px; border-radius: 7px; cursor: pointer;
  color: var(--text-secondary); font-weight: 700; line-height: 1.6;
}
.ll-dots:hover { background: var(--bg-card-hover); color: var(--text-primary); }
.ll-dots-menu {
  position: fixed; z-index: 1000; padding: 4px; min-width: 130px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 10px; box-shadow: 0 8px 24px rgba(15, 23, 42, .14);
}
.ll-dots-menu button {
  all: unset; display: block; padding: 6px 12px; border-radius: 7px;
  cursor: pointer; font-size: .88em; white-space: nowrap;
  color: var(--text-primary);
}
.ll-dots-menu button:hover { background: rgba(220, 38, 38, .09); color: #dc2626; }
#ll-songs {
  max-height: 44vh; overflow-y: auto;
  scrollbar-width: thin; scrollbar-color: var(--border) transparent;
}
#ll-song-filter { margin-bottom: 6px; }
#ll-catalog { max-height: 46vh; overflow-y: auto; }

/* white theme: every field on white with clearly visible text + caret */
.gradio-container input:not([type="checkbox"]):not([type="radio"]),
.gradio-container textarea,
.gradio-container select {
  background: #ffffff !important;
  color: var(--text-primary) !important;
  caret-color: var(--accent) !important;
  border: 1px solid var(--border) !important;
  border-radius: 12px !important;
}
.gradio-container input:focus, .gradio-container textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 2px var(--accent-soft) !important;
}
.gradio-container input::placeholder, .gradio-container textarea::placeholder {
  color: var(--text-secondary) !important; opacity: 0.6;
}

.app-header { text-align: center; padding: 16px 0 4px; }
.app-header h1 { font-size: 26px; margin: 0; font-weight: 800;
  background-image: var(--accent-grad);
  -webkit-background-clip: text; background-clip: text;
  color: transparent; -webkit-text-fill-color: transparent; }
.app-header p { color: var(--text-secondary); margin: 4px 0 0; font-size: 14px; }

/* ── Chip tab navigation: grey pills, selected = solid blue ── */
.gradio-container .tab-nav, .gradio-container div[role="tablist"] {
  justify-content: center; gap: 12px; border-bottom: none !important;
  padding-bottom: 2px; margin-bottom: 14px; flex-wrap: wrap;
}
.gradio-container .tab-nav button, .gradio-container button[role="tab"] {
  font-size: 15px !important; font-weight: 700 !important;
  padding: 8px 18px !important; border-radius: 500px !important;
  color: var(--text-secondary) !important;
  background: rgba(255, 255, 255, 0.75) !important;
  border: none !important;
  box-shadow: 0 1px 3px rgba(43, 36, 64, 0.08);
  transition: background 0.2s ease, color 0.2s ease, transform 0.15s ease-out;
}
.gradio-container .tab-nav button:hover, .gradio-container button[role="tab"]:hover {
  color: var(--text-primary) !important; background: #ffffff !important;
  transform: translateY(-2px);
}
.gradio-container .tab-nav button.selected,
.gradio-container button[role="tab"][aria-selected="true"] {
  color: #ffffff !important; background: var(--text-primary) !important;
  transform: none;
}

/* ── Pill buttons, blue on white ── */
.gradio-container button.primary {
  background: var(--accent-grad) !important; color: #ffffff !important;
  border: none !important; border-radius: 500px !important;
  font-weight: 700 !important;
  box-shadow: 0 2px 10px rgba(129, 140, 248, 0.35) !important;
  transition: filter 0.15s ease, transform 0.15s ease;
}
.gradio-container button.primary:hover {
  filter: brightness(1.06); transform: scale(1.03);
}
.gradio-container button.primary:active { transform: scale(0.98); }
.gradio-container button.secondary {
  background: #ffffff !important; color: var(--text-primary) !important;
  border: 1px solid var(--border) !important; border-radius: 500px !important;
  font-weight: 600 !important; box-shadow: none !important;
  transition: border-color 0.15s ease, color 0.15s ease, transform 0.15s ease;
}
.gradio-container button.secondary:hover {
  border-color: #c7cbfa !important; color: var(--accent) !important;
  background: #ffffff !important; transform: scale(1.03);
}

.ll-hidden { display: none !important; }

/* ── three main panels as separate white rounded cards ──
   geometry strictly transferred from prototypes/recolor.html (th-celadon):
   grid 240px | 1fr | 320px, gap 18px, max-width 1240px centered,
   side cards pad 20px, middle card pad 26px, radius 22px */
#ll-play-row {
  display: grid !important;
  /* 2026-10-06 用户手绘:侧栏 300 / 右栏 420 贴两侧,
     中栏限宽 ~1080px(红框)居中,两边留白 */
  grid-template-columns: 420px minmax(0, 1300px) 420px !important;
  justify-content: space-between !important;
  gap: 15px !important;
  max-width: 88% !important;
  margin: 0 auto !important;
  padding: 0 26px;
  align-items: flex-start;
}
#ll-play-row > * { width: auto !important; min-width: 0 !important; }
/* 三栏各自限高在视口内、内部滚动;页面整体滚动条保持不动。
   body 有 zoom:0.75,100vh 的 CSS 高度只渲染出 75% —— 用 133.33vh
   补偿;260px ≈ 顶部标题+tab 条(CSS px) */
#ll-play-row > .ll-card {
  max-height: calc(133.33vh - 260px);
  min-height: 0;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.ll-card {
  background-color: #ffffff !important;
  border-radius: 22px !important;
  padding: 20px !important;
  box-shadow: var(--card-shadow) !important;
}
#ll-play-row > .ll-card:nth-child(2) { padding: 26px !important; }
/* blocks inside a card stay flat so the card reads as one surface */
.ll-card .block, .ll-card .form {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

.side-panel-title {
  font-size: 12px; font-weight: 700; color: var(--text-primary);
  padding: 4px 2px 6px; border-bottom: 2px solid var(--accent-soft); margin-bottom: 8px;
}

/* Song header: gradient cover tile + big title (pop_design.png) */
.song-header {
  display: flex; align-items: center; gap: 16px;
  padding: 6px 4px 14px; margin-bottom: 8px;
}
.song-cover {
  width: 72px; height: 72px; border-radius: 20px; flex: none;
  background-image: var(--accent-grad);
  display: flex; align-items: center; justify-content: center;
  font-size: 28px; color: #ffffff;
}
.song-title-display { margin: 0; font-size: 26px; font-weight: 800; color: var(--text-primary); }
.song-meta-display { margin: 4px 0 0; font-size: 13px; color: var(--text-secondary); }

/* native audio bar: blend into the white card as a rounded chip */
.gradio-container audio {
  width: 100%; height: 40px; border-radius: 999px;
  background-color: var(--bg-card);
}
.gradio-container audio::-webkit-media-controls-enclosure {
  border-radius: 999px; background-color: var(--bg-card);
  margin-bottom: 10px;
}

/* compact audio-upload dropzone — the default is a huge empty drop area */
#ll-audio-up .wrap {
  min-height: 0 !important; padding: 10px 8px !important; font-size: 12.5px;
}
#ll-audio-up .wrap .icon-wrap, #ll-audio-up .wrap svg { display: none; }
#ll-audio-up .wrap .or { margin: 0 4px; }

.no-audio-hint {
  padding: 10px 16px; margin: 8px 0; border-radius: 8px; font-size: 13px;
  background: var(--bg-card); border: 1px dashed var(--border);
  color: var(--text-secondary);
}
.preview-hint {
  margin-top: 4px; font-size: 11px; color: var(--text-secondary);
}
.echo-mark {
  margin-left: 6px; font-size: 12px; opacity: 0.7; user-select: none;
}
.lyric-line:hover .echo-mark { opacity: 1; }

.lyrics-hint { text-align: center; color: var(--text-secondary); font-size: 12px; padding: 6px 0; opacity: 0.7; }

/* Lyrics */
#lyrics-container {
  position: relative; /* anchors .lyric-line offsetTop for container-scoped scroll */
  max-height: 66vh; overflow-y: auto; padding: 8px 12px;
  scroll-behavior: smooth; scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
#lyrics-container::-webkit-scrollbar { width: 6px; }
#lyrics-container::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
#lyrics-scroll { display: flex; flex-direction: column; gap: 2px; }

.lyric-line {
  padding: 10px 14px; border-radius: 14px; cursor: pointer;
  margin-bottom: 20px; /* 行间距(用户定) */
  transition: all 0.25s ease; border-left: 3px solid transparent;
}
.lyric-line:hover { background: var(--bg-card); }
.lyric-line.picked { background: var(--pink-soft); border-left-color: var(--pink); }
.lyric-line.picked .lyric-text { color: var(--pink); }
.lyric-line.played .lyric-text { color: var(--text-played); }
.lyric-line.active { background: var(--accent-glow); border-left-color: var(--accent); transform: scale(1.02); }
.lyric-line.active .lyric-text { color: var(--text-primary); font-weight: 700; font-size: 24px; }
/* karaoke sweep: JS drives a gradient over the active line's text; the
   estimated progress paints sung characters accent-blue */
@supports (-webkit-background-clip: text) or (background-clip: text) {
  .lyric-line.active .lyric-text[style*="background-image"] {
    -webkit-background-clip: text; background-clip: text;
    color: transparent; -webkit-text-fill-color: transparent;
  }
}
.lyric-text {
  font-size: 21px; font-weight: 500; color: var(--lyric-dim);
  letter-spacing: -0.01em; transition: all 0.25s ease; line-height: 1.5;
}

/* Search */
#ll-search { position: relative; z-index: 5; }
#ll-search textarea, #ll-search input {
  pointer-events: auto !important; cursor: text;
}
.search-mode-tag { font-size: 11px; color: var(--text-secondary); margin-bottom: 6px; }
.search-hit {
  padding: 8px 12px; background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 8px; margin-bottom: 6px;
}
.search-hit.seekable { cursor: pointer; }
.search-hit.seekable:hover { border-color: var(--accent); }
.search-line { font-size: 13px; color: var(--text-primary); font-style: italic; }
.search-meta { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.search-none { color: var(--text-secondary); font-size: 13px; padding: 8px; }

/* AI assistant chat */
.chat-topic {
  font-size: 13px; color: var(--accent); padding: 8px 12px;
  background: var(--accent-soft); border-radius: 8px; margin-bottom: 8px;
}
.chat-topic.dim { color: var(--text-secondary); background: var(--bg-card); }
.chat-empty { color: var(--text-secondary); font-size: 13px; padding: 10px; line-height: 1.7; }
#chat-scroll {
  max-height: 56vh; overflow-y: auto; display: flex; flex-direction: column;
  gap: 8px; padding: 4px 2px; scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.chat-bubble {
  padding: 10px 14px; border-radius: 12px; font-size: 13px;
  line-height: 1.7; max-width: 94%;
}
.chat-bubble b { display: block; font-size: 12px; margin-bottom: 4px; color: var(--accent); }
.chat-bubble p { margin: 0; color: var(--text-primary); white-space: pre-wrap; }
.chat-bubble.ai { background: rgba(9,105,218,0.06); border: 1px solid rgba(9,105,218,0.22); align-self: flex-start; }
.chat-bubble.user { background: var(--bg-card); border: 1px solid var(--border); align-self: flex-end; }
.chat-bubble.streaming { border-style: dashed; opacity: 0.92; }
/* debate personas get their own tints */
.chat-bubble.critic { background: rgba(130,80,223,0.07); border-color: rgba(130,80,223,0.30); }
.chat-bubble.critic b { color: #8250df; }
.chat-bubble.fan { background: rgba(191,57,137,0.07); border-color: rgba(191,57,137,0.30); }
.chat-bubble.fan b { color: #bf3989; }

/* whole-song AI intro */
.song-intro {
  font-size: 13px; line-height: 1.8; color: var(--text-primary);
  padding: 10px 12px; background: var(--bg-card); border-radius: 10px;
  white-space: pre-wrap;
}

.add-status { font-size: 14px; line-height: 1.8; }

/* Easter-egg intertextuality tracker */
.echo-list { display: flex; flex-direction: column; gap: 6px; }
.echo-card {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--bg-card);
}
.echo-line { font-size: 13px; font-style: italic; color: var(--text-primary); }
.echo-meta { font-size: 11px; color: var(--text-secondary); margin-top: 3px; }
.echo-explain { font-size: 13px; line-height: 1.7; }

/* player tools */
.ptool {
  font-size: 12px; padding: 3px 10px; border-radius: 14px; cursor: pointer;
  background: var(--bg-card); border: 1px solid var(--border);
  color: var(--text-primary);
  margin-top: 8px;
}
.ptool:hover { border-color: var(--accent); color: var(--accent); }

/* listening notes */
.note-list { display: flex; flex-direction: column; gap: 5px; max-height: 32vh; overflow-y: auto; }
.note-item {
  display: flex; gap: 8px; align-items: baseline; cursor: pointer;
  padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-card); font-size: 15px;
}
.note-item:hover { border-color: var(--accent); }
.note-ts { color: var(--accent); font-size: 12px; white-space: nowrap; }
.note-text { flex: 1; color: var(--text-primary); }
.note-del { color: var(--text-secondary); padding: 0 4px; }
.note-del:hover { color: #cf222e; }

/* daily quote card */
.daily-card {
  background: linear-gradient(135deg, rgba(9,105,218,0.07), rgba(130,80,223,0.07));
  border: 1px solid var(--border); border-radius: 14px; padding: 16px 20px;
}
.daily-label { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.daily-line { font-size: 19px; font-weight: 700; color: var(--text-primary); font-style: italic; }
.daily-meta { font-size: 13px; color: var(--accent); margin: 6px 0 8px; }
.daily-insight { font-size: 13px; color: var(--text-secondary); line-height: 1.7; }

/* word cloud */
.cloud-hint { font-size: 12px; color: var(--text-secondary); margin: 4px 0 8px; }
.word-cloud {
  display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: baseline;
  padding: 10px 4px;
}
.cloud-word { color: var(--accent); cursor: pointer; line-height: 1.1; }
.cloud-word:hover { text-decoration: underline; }

/* emotion map */
.emo-axis { stroke: var(--border); stroke-dasharray: 4 4; }
.emo-axis-label { font-size: 12px; fill: var(--text-secondary); }
.emo-node { cursor: pointer; }
.emo-node circle { stroke: #ffffff; stroke-width: 1.5; }
.emo-node:hover circle { stroke: var(--accent); stroke-width: 2.5; }
.emo-label { font-size: 11px; fill: var(--text-secondary); }
.emo-label.emo-hidden { display: none; }
.emo-node:hover .emo-label.emo-hidden {
  display: block; font-weight: 700; fill: var(--text-primary);
  paint-order: stroke; stroke: var(--bg-primary); stroke-width: 3px;
}

/* side-panel icon dock: icon-only tab nav on TOP, content expands below */
.ll-icon-dock { display: flex; flex-direction: column; }
.ll-icon-dock > .tab-nav, .ll-icon-dock > div[role="tablist"] {
  justify-content: center; gap: 4px;
  border-top: none !important;
  border-bottom: 1px solid var(--border) !important;
  padding: 2px 0 8px; margin: 0 0 10px;
  position: relative; z-index: 3; background: var(--bg-primary);
  flex-wrap: wrap !important; /* 320px 窄卡里 6 个图标必须全可见,不许折叠进 ⋯ */
}
.ll-icon-dock > .tabitem, .ll-icon-dock > div[role="tabpanel"] {
  overflow: visible; padding-bottom: 6px;
}
/* Gradio 的 JS 溢出逻辑会在重渲染时把部分图标 tab 收进 ⋯ 下拉
   (probe 随即找不到 ⚙️)。六个图标缩窄后本就放得下——强制全部可见,
   并永久隐藏 ⋯ 溢出菜单。!important 压得过 JS 写的行内样式 */
.ll-icon-dock .tab-container button[role="tab"] {
  display: flex !important; visibility: visible !important;
}
.ll-icon-dock .overflow-menu { display: none !important; }
.ll-icon-dock > .tab-nav button, .ll-icon-dock button[role="tab"] {
  font-size: 16px !important; font-weight: 400 !important;
  /* 320px 窄卡里 6 个图标 tab 必须全可见(6×~30px < ~200px 容器),
     否则 Gradio 的 JS 溢出逻辑会把 ⚙️/📝 折进 ⋯ 下拉,probe 找不到 */
  padding: 5px 7px !important; border-radius: 10px !important;
  border-bottom: none !important; background: transparent !important;
  line-height: 1 !important;
}
.ll-icon-dock > .tab-nav button:hover,
.ll-icon-dock button[role="tab"]:hover {
  background: var(--bg-card-hover) !important;
}
.ll-icon-dock > .tab-nav button.selected,
.ll-icon-dock button[role="tab"][aria-selected="true"] {
  background: var(--accent-soft) !important;
  border-bottom: none !important;
}

/* archaeology report (母题考古) */
.arch-report {
  padding: 14px 16px; border-radius: 12px; background: var(--bg-card);
  border: 1px solid var(--border); font-size: 13px; line-height: 1.7;
}
.arch-head { font-size: 15px; font-weight: 700; margin-bottom: 6px; }
.arch-overview { color: var(--text-primary); margin-bottom: 10px; }
.arch-motif {
  margin: 12px 0 0; padding: 10px 12px; border-radius: 10px;
  background: var(--bg-secondary); border: 1px solid var(--border);
}
.arch-word { font-weight: 700; font-size: 14px; }
.arch-n { font-weight: 400; font-size: 12px; color: var(--text-secondary); margin-left: 8px; }
.arch-arc { margin: 4px 0 8px; color: var(--text-primary); }
.arch-hit { margin: 3px 0; font-size: 12.5px; }
.arch-hit.ev-ok[data-cite-label] { cursor: pointer; border-radius: 8px; padding: 2px 4px; }
.arch-hit.ev-ok[data-cite-label]:hover { background: var(--bg-card-hover); }
.arch-hit .ev-src { display: inline; padding-left: 6px; font-size: 12px; color: var(--text-secondary); }
.arch-foot { margin-top: 12px; font-size: 11.5px; color: var(--text-secondary); }

/* annotation coverage line (曲库洞察) */
.cov-line {
  margin-bottom: 10px; padding: 8px 12px; border-radius: 10px;
  background: var(--bg-secondary); border: 1px solid var(--border);
  font-size: 12.5px; color: var(--text-secondary);
}
.cov-line b { color: var(--text-primary); }

/* 🎧 tour commentary card */

/* evidence card (可追溯证据) */
.ev-card {
  margin-top: 8px; padding: 12px 14px; border-radius: 12px;
  background: var(--bg-card); border: 1px solid var(--border);
  font-size: 13px; line-height: 1.7;
}
.ev-conclusion { font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
.ev-sec-title {
  font-size: 12px; font-weight: 700; color: var(--text-secondary);
  margin: 10px 0 4px; display: flex; justify-content: space-between;
}
.ev-conf { font-weight: 400; }
.ev-quote { margin: 4px 0; padding-left: 4px; }
.ev-quote.ev-ok[data-cite-label] { cursor: pointer; border-radius: 8px; }
.ev-quote.ev-ok[data-cite-label]:hover { background: var(--bg-card-hover); }
.ev-quote .ev-mark { margin-right: 4px; }
.ev-quote .ev-src { display: block; font-size: 12px; color: var(--text-secondary); padding-left: 22px; }
.ev-quote.ev-bad .ev-text { color: var(--text-secondary); text-decoration: line-through; }
.ev-fact { font-size: 12.5px; color: var(--text-secondary); margin: 3px 0; }
.ev-spec { font-size: 12.5px; color: var(--text-secondary); margin: 3px 0; padding-left: 4px; border-left: 2px solid var(--border); }
.mv-link.ev-ok[data-cite-label] { cursor: pointer; }
.mv-link.ev-ok[data-cite-label]:hover { text-decoration: underline; }
.mv-link.ev-bad { color: var(--text-secondary); }
@keyframes ll-cite-flash {
  0%, 15% { background: var(--accent); color: #fff;
            box-shadow: 0 0 0 3px var(--accent); }
  70% { background: var(--accent-soft); color: inherit;
        box-shadow: 0 0 0 2px var(--accent); }
  100% { background: transparent; box-shadow: none; }
}
.lyric-line.cite-flash { animation: ll-cite-flash 4s ease-out;
  border-radius: 8px; }
.lyric-line.cite-flash .lyric-text { color: inherit; }

/* mini translator popover + wordbook */
.ll-dict-pop {
  position: fixed; z-index: 1200; width: 290px; padding: 12px 14px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: 0 10px 30px rgba(15, 23, 42, .18);
  font-size: .9em; line-height: 1.55;
  cursor: move; user-select: none; touch-action: none;
}
.ll-dict-pop .dict-word { font-weight: 700; margin-bottom: 4px; }
.ll-dict-pop .dict-close { float: right; cursor: pointer; padding: 0 4px;
  color: var(--text-secondary); font-weight: 400; }
.ll-dict-pop .dict-close:hover { color: var(--text-primary); }
.ll-dict-pop .dict-phon { color: var(--text-secondary); font-weight: 400; }
.ll-dict-pop .dict-body { color: var(--text-primary); max-height: 150px; overflow-y: auto; }
.ll-dict-pop .dict-miss { color: var(--text-secondary); }
.ll-dict-pop .dict-ai {
  margin-top: 8px; padding: 8px 10px; border-radius: 8px;
  background: var(--accent-soft); color: var(--text-primary);
}
.ll-dict-pop .dict-actions { margin-top: 10px; display: flex; gap: 8px; }
.ll-dict-pop .dict-say { padding: 0 6px; }
.ll-dict-pop .dict-btn {
  all: unset; cursor: pointer; padding: 5px 10px; border-radius: 8px;
  background: var(--bg-card-hover); font-size: .92em;
}
.ll-dict-pop .dict-btn:hover { background: var(--accent-soft); }
.ll-dict-pop .dict-btn[disabled] { opacity: .6; cursor: default; }
.wb-list { display: flex; flex-direction: column; gap: 8px;
  max-height: 48vh; overflow-y: auto; overflow-x: hidden;
  scrollbar-width: thin; }
.wb-item {
  position: relative; padding: 8px 26px 8px 10px; border-radius: 10px;
  background: var(--bg-card); border: 1px solid var(--border);
}
.wb-item .wb-word { font-weight: 700; font-size: 1.5em; }
.wb-item .wb-phon { color: var(--text-secondary); font-weight: 400; font-size: .9em; }
.wb-item .wb-meaning { font-size: 1.05em; color: var(--text-primary); }
.wb-item .wb-src { font-size: 1em; color: var(--text-secondary); margin-top: 2px; }
.wb-item .wb-ai { font-size: .85em; color: var(--text-primary); margin-top: 4px;
  padding: 6px 8px; background: var(--accent-soft); border-radius: 8px;
  line-height: 1.5; }
.lyric-line .lyric-trans { font-size: 14px; font-weight: 400;
  color: var(--text-played); margin-top: 3px; line-height: 1.5; }
/* 歌单侧栏收起（仿 Claude） */
#ll-sidebar.ll-sb-hidden { display: none !important; }
#ll-sb-btn {
  position: fixed; z-index: 1270; left: 10px; top: 10px;
  width: 34px; height: 34px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--border); background: var(--bg-card);
  color: var(--text-secondary); font-size: 16px; line-height: 1; }
#ll-sb-btn:hover { color: var(--text-primary);
  background: var(--bg-card-hover); }
#ll-sb-btn .ll-sb-tip {
  display: none; position: absolute; left: 0; top: 40px;
  white-space: nowrap; padding: 7px 10px; border-radius: 8px;
  background: #1f2328; color: #fff; font-size: 12.5px;
  box-shadow: 0 6px 20px rgba(15, 23, 42, .3); }
#ll-sb-btn:hover .ll-sb-tip { display: block; }
#ll-sb-btn .ll-sb-tip kbd {
  margin-left: 8px; padding: 1px 6px; border-radius: 4px;
  background: #3a3f45; color: #c8cdd3; font-family: inherit;
  font-size: 11.5px; }
#ll-review-stats { text-align: right; }
#ll-review-hint { text-align: center; }
/* 歌曲寻词整页与互动同级放大 */
.tabitem:has(#ll-review-hint) { zoom: 1.25; }
/* 添加歌曲：整块居中 + 同级放大 */
.tabitem:has(#ll-add-head) { zoom: 1.25; }
.tabitem:has(#ll-add-head) > * { max-width: 980px; margin-left: auto;
  margin-right: auto; text-align: center; }
/* 练习范围：窄、贴提示行 */
#ll-review-group { max-width: 280px; margin-left: 24%; margin-right: auto; }
/* 去掉下拉旁拉通整行的灰底容器 */
.form:has(> #ll-review-group) { background: transparent; border: none;
  box-shadow: none; }
/* ⋯ 面板：竖排窄浮层，展开时覆盖在页面上，不挤压单词卡片 */
#ll-review-topright { position: relative; }
#ll-review-more { position: absolute; right: 0; top: 34px;
  width: 400px; z-index: 60; background: var(--bg-card);
  border: 1px solid var(--border); border-radius: 12px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, .15);
  /* 常驻滚动条：面板高出视口时（尤其还没出单词卡、页面本身很矮）
     也能拖动看到底部按钮；底部留白加大拖动余量 */
  max-height: calc(100vh - 230px); overflow-y: scroll;
  padding-bottom: 48px; }
#ll-review-more .label-wrap { justify-content: flex-end; }
/* 上传框压扁 */
#ll-import-file { min-height: 0 !important; }
#ll-import-file .wrap, #ll-import-file [data-testid="dropzone"],
#ll-import-file .upload-container, #ll-import-file .center {
  min-height: 90px !important; }
#ll-import-file { max-height: 130px; overflow: hidden; }
/* 一键导出：下载锚点由 JS 代点，永远不显示 */
#ll-dl-json, #ll-dl-anki { display: none !important; }
/* 开始/暂停按钮：无卡片时贴统计条右缘（776 = 统计条 720 + 内边距）；
   出卡后由 JS（placeStartRow）fixed 定位钉在例句卡下方 */
#ll-review-startrow { max-width: 778px; margin: 6px auto 0;
  display: flex; justify-content: flex-end; gap: 8px;
  width: auto; z-index: 10; }
#ll-review-startrow button { flex: 0 0 auto; }
#ll-review-startrow > * { flex: 0 0 auto !important;
  width: auto !important; min-width: 0 !important; }
/* 🎮 竞猜/拼图：整块居中 + 放大（互动页空间大、原字号太小） */
#ll-quiz-wrap, #ll-blank-wrap { max-width: 860px; margin: 0 auto;
  text-align: center; zoom: 1.3; }
/* 🕵️ 考据：选歌下拉居中收窄，正文整体放大 */
.tabitem:has(#ll-lore-main) { zoom: 1.15; }
/* 生成按钮与选歌下拉等宽居中 */
#ll-lore-gen { max-width: 560px; margin: 8px auto 0; display: block; }
/* 考据 AI 助手默认收起，💬 图标按需展开 */
#ll-lore-chat.ll-lc-hidden { display: none !important; }
#ll-lore-chat-btn {
  position: fixed; z-index: 1270; right: 14px; top: 10px;
  width: 34px; height: 34px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--border); background: var(--bg-card);
  color: var(--text-secondary); font-size: 16px; line-height: 1; }
#ll-lore-chat-btn:hover { color: var(--text-primary);
  background: var(--bg-card-hover); }
#ll-lore-chat-btn .ll-sb-tip {
  display: none; position: absolute; right: 0; top: 40px;
  white-space: nowrap; padding: 7px 10px; border-radius: 8px;
  background: #1f2328; color: #fff; font-size: 12.5px;
  box-shadow: 0 6px 20px rgba(15, 23, 42, .3); }
#ll-lore-chat-btn:hover .ll-sb-tip { display: block; }
#ll-lore-main .chat-empty { text-align: center; }
#ll-lore-song { max-width: 560px; margin: 0 auto; }
.form:has(> #ll-lore-song) { background: transparent; border: none;
  box-shadow: none; max-width: 580px; margin: 0 auto; }
#ll-quiz-wrap fieldset, #ll-blank-wrap fieldset {
  justify-content: center; }
#ll-quiz-wrap .quiz-line, #ll-blank-wrap .quiz-line {
  text-align: center; }
/* 🧭 新手指引 */
.ll-tour-ring {
  position: fixed; z-index: 1290; pointer-events: none; border-radius: 12px;
  border: 2px solid var(--accent);
  box-shadow: 0 0 0 9999px rgba(15, 23, 42, .45);
  transition: all .3s ease; }
.ll-onboard-box {
  position: fixed; z-index: 1300; left: 50%; bottom: 60px;
  transform: translateX(-50%); width: min(460px, 92vw);
  padding: 14px 16px; border-radius: 14px; background: var(--bg-card);
  border: 1px solid var(--border);
  box-shadow: 0 10px 30px rgba(15, 23, 42, .25);
  font-size: 13.5px; line-height: 1.7; }
.ll-onboard-box .ob-nav { margin-top: 10px; display: flex; gap: 8px;
  align-items: center; }
.ll-onboard-box .ob-dots { margin-right: auto;
  color: var(--text-secondary); letter-spacing: 2px; }
.ll-onboard-box .ob-btn { padding: 4px 12px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--bg-card);
  cursor: pointer; font-size: 12.5px; color: var(--text-primary); }
.ll-onboard-box .ob-btn.ob-main { background: var(--accent); color: #fff;
  border-color: var(--accent); }
#ll-onboard-btn {
  position: fixed; z-index: 1280; left: 14px; bottom: 14px;
  width: 34px; height: 34px; border-radius: 50%; cursor: pointer;
  border: 1px solid var(--border); background: var(--bg-card);
  color: var(--text-secondary); font-size: 15px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, .15); }
#ll-onboard-btn:hover { color: var(--accent); border-color: var(--accent); }
/* 🕵️ 歌迷考据 */
.lore-page { max-width: 760px; margin: 0 auto; text-align: center; }
.lore-head { font-size: 18px; font-weight: 800; margin: 8px 0; }
.lore-hook { padding: 12px 16px; border-left: 4px solid var(--accent);
  background: var(--accent-soft); border-radius: 0 10px 10px 0;
  font-size: 15px; font-weight: 600; margin-bottom: 14px; }
.lore-sec { font-weight: 700; margin: 16px 0 8px; }
.lore-clue { padding: 12px 14px; border: 1px solid var(--border);
  border-radius: 12px; background: var(--bg-card); margin-bottom: 10px;
  line-height: 1.75; }
.lore-badge { display: inline-block; font-size: 11px; font-weight: 700;
  padding: 2px 8px; border-radius: 999px; margin-bottom: 6px; }
.lore-badge.lore-official { background: #dafbe1; color: #116329; }
.lore-badge.lore-parallel { background: var(--accent-soft);
  color: var(--accent); }
.lore-badge.lore-theory { background: #fff1e5; color: #953800; }
.lore-clue-title { font-weight: 700; margin: 2px 0 4px; }
.lore-clue-body { color: var(--text-primary); }
.lore-quote { margin-top: 8px; padding: 8px 12px; border-radius: 8px;
  background: var(--bg-main); font-style: italic; }
.lore-quote.ev-ok { cursor: pointer; }
.lore-quote.ev-ok:hover { background: var(--bg-card-hover); }
.lore-quote-src { font-style: normal; font-size: 12px; margin-left: 8px;
  color: var(--text-secondary); }
.lore-theory-note { margin-top: 6px; font-size: 11.5px;
  color: var(--text-secondary); }
.lore-caveat { margin-top: 8px; font-size: 12px;
  color: var(--text-secondary); }
.lore-disclaim { margin-top: 14px; font-size: 11.5px;
  color: var(--text-secondary); border-top: 1px dashed var(--border);
  padding-top: 8px; }
/* 点句批注卡 */
.ann-card { padding: 12px 14px; border: 1px solid var(--border);
  border-radius: 12px; background: var(--bg-card); margin-bottom: 10px;
  font-size: 13px; line-height: 1.6; }
.ann-card .ann-summary { font-weight: 700; color: var(--text-primary);
  margin-bottom: 6px; }
.ann-card .ann-row { color: var(--text-primary); margin-top: 4px; }
.ann-card .ann-row b { color: var(--text-secondary); font-weight: 600;
  margin-right: 2px; }
.ann-card .ann-rel { color: var(--text-secondary); }
.ann-card.ann-empty { color: var(--text-secondary); display: flex;
  align-items: center; gap: 10px; flex-wrap: wrap; }
/* 📺 B 站视频模式 */
.bv-frame { position: relative; width: 100%; padding-top: 56.25%;
  margin-top: 10px; border-radius: 12px; overflow: hidden;
  border: 1px solid var(--border); background: var(--bg-card); }
.bv-frame iframe { position: absolute; inset: 0; width: 100%; height: 100%; }
.bv-note { font-size: .85em; color: var(--text-secondary); margin-top: 6px; }
.bv-bind { margin-top: 8px; display: flex; align-items: center; gap: 8px; }
.bv-bind-hint { font-size: .8em; color: var(--text-secondary); }
.bv-cand { padding: 10px 14px; border: 1px solid var(--border);
  border-radius: 12px; background: var(--bg-card); margin-top: 6px;
  cursor: pointer; }
.bv-cand:hover { border-color: var(--accent); }
.bv-cand b { font-size: 14px; color: var(--text-primary); }
.bv-cand-meta { display: block; font-size: 12px;
  color: var(--text-secondary); margin-top: 2px; }
/* ⌨️ 单词练习 */
.ll-type-card { padding: 18px 20px; border: 1px solid var(--border);
  border-radius: 14px; background: var(--bg-card); cursor: text;
  max-width: 720px; margin: 0 auto; text-align: center; }
.ll-type-card .tp-word { font-size: 34px; font-weight: 800;
  letter-spacing: 3px; color: var(--karaoke-rest); margin-bottom: 10px; }
.ll-type-card .tp-ch.ok { color: var(--accent); }
.ll-type-card .ll-type-input { position: absolute; opacity: 0;
  width: 1px; height: 1px; border: 0; padding: 0; }
.ll-type-card .wb-meaning, .ll-type-card .wb-src, .ll-type-card .wb-ai {
  margin-top: 8px; font-size: 1.3em; line-height: 1.7; }
.ll-type-card .tp-ime-hint { display: none; color: #cf222e;
  font-size: .85em; margin-top: 4px; }
.ll-type-card.tp-ime .tp-ime-hint { display: block; }
.ll-type-card .tp-donehint { display: none; color: var(--accent);
  font-weight: 700; font-size: 1.1em; margin-top: 8px; }
.ll-type-card.tp-done .tp-donehint { display: block; }
.ll-type-card .tp-ch.tp-space { min-width: .55em;
  display: inline-block; }
.ll-type-card .tp-wline-word { background: var(--accent-soft);
  border-radius: 4px; padding: 0 2px; }
.ll-type-card .wb-src[data-tp-jump] { cursor: pointer; }
.ll-type-card .wb-src[data-tp-jump]:hover { color: var(--accent); }
.ll-example-card { padding: 14px 20px; border: 1px solid var(--border);
  border-radius: 14px; background: var(--bg-card); max-width: 720px;
  margin: 10px auto 0; text-align: center; }
.ll-example-card .wb-example { margin-top: 6px; font-size: 1.15em;
  line-height: 1.7; color: var(--text-secondary); }
/* 盲打时例句卡里的目标词同样遮住（跟随主卡的 tp-blind 状态） */
.ll-type-card.tp-blind + .ll-example-card .tp-wline-word {
  background: var(--text-secondary); color: transparent;
  border-radius: 4px; }
#ll-back-typing {
  position: fixed; z-index: 1280;
  padding: 8px 16px; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--accent); background: var(--bg-card);
  color: var(--accent); font-size: 13px; font-weight: 600;
  box-shadow: 0 4px 14px rgba(15, 23, 42, .15); }
#ll-back-typing:hover { background: var(--accent); color: #fff; }
.ll-type-card.tp-blind .tp-ch { color: transparent;
  border-bottom: 2px solid var(--karaoke-rest); }
.ll-type-card.tp-blind .tp-ch.ok { color: var(--accent);
  border-bottom-color: var(--accent); }
.ll-type-card.tp-blind .tp-wline-word { background: var(--text-secondary);
  color: transparent; border-radius: 4px; }
.ll-type-card.tp-shake { animation: tp-shake .25s; }
@keyframes tp-shake {
  25% { transform: translateX(-5px); } 75% { transform: translateX(5px); }
}
.wb-item .wb-jump { cursor: pointer; }
.wb-item .wb-jump:hover { color: var(--accent); text-decoration: underline; }
.fav-item[data-cite-label] { cursor: pointer; }
.wb-item .wb-del {
  position: absolute; right: 8px; top: 8px; cursor: pointer;
  color: var(--text-secondary); padding: 0 4px; border-radius: 6px;
}
.wb-item .wb-del:hover { color: #dc2626; background: var(--bg-card-hover); }
.wb-item .wb-note-btn {
  position: absolute; right: 32px; top: 8px; cursor: pointer;
  padding: 0 4px; border-radius: 6px; font-size: 15px;
}
.wb-item .wb-note-btn:hover { background: var(--bg-card-hover); }
.wb-item .wb-note { font-size: .9em; color: var(--accent);
  margin-top: 4px; }

/* lyric favorites */
.fav-list { display: flex; flex-direction: column; gap: 6px;
  max-height: 40vh; overflow-y: auto; scrollbar-width: thin; }
.fav-item { padding: 8px 12px; border: 1px solid var(--border);
  border-radius: 10px; background: var(--bg-card); cursor: pointer; }
.fav-item:hover { border-color: var(--accent); }
.fav-line { font-size: 20px; font-style: italic; color: var(--text-primary); }
.fav-song { font-size: 17px; color: var(--text-secondary); margin-top: 3px; }
.fav-del { float: right; color: var(--text-secondary); padding: 0 4px; }
.fav-del:hover { color: #cf222e; }

/* UI probe report table */
.probe-table { border-collapse: collapse; font-size: 12.5px; width: 100%; }
.probe-table th, .probe-table td {
  border: 1px solid var(--border); padding: 4px 8px; text-align: left;
}
.probe-table th { background: var(--bg-card); }
.probe-detail { color: #cf222e; }

/* quiz */
.quiz-line {
  font-size: 18px; font-weight: 700; font-style: italic;
  color: var(--text-primary); padding: 14px 18px;
  background: var(--bg-card); border-radius: 12px;
}
.quiz-meta { font-size: 12px; color: var(--text-secondary); margin-top: 6px; }
.quiz-hint { font-size: 12.5px; color: var(--text-secondary);
  text-align: center; margin: 2px auto 0; }

/* 右栏 AI 助手整栏：内置竖向滚动条；任何情况下不出横向条。
   flex-wrap 必须锁死 nowrap —— Gradio 列默认可换行，内容一超过
   max-height 整个图标坞会被挤到右边、再被 overflow-x 裁掉 */
.ll-card:has(#ll-side-dock) {
  max-height: 86vh; overflow-y: auto; overflow-x: hidden;
  scrollbar-width: thin; flex-wrap: nowrap !important;
}

/* 📺 关联 B 站视频：保存按钮下的跳转链接（按钮样式） */
.bv-goto {
  display: block; text-align: center; padding: 5px 10px;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-card); color: var(--text-primary);
  font-size: 13px; text-decoration: none;
}
.bv-goto:hover { border-color: var(--accent); color: var(--accent); }

/* ⚙️ 设置：📊 API 用量整页居中；🔑 API 设置居中窄框（仿添加歌曲页） */
.tabitem:has(#ll-usage-head) { text-align: center; }
.tabitem:has(#ll-usage-head) table { margin-left: auto; margin-right: auto; }
#ll-apiset { max-width: 620px; margin: 0 auto; }

/* ⌨️ 歌曲寻词：qwerty-learner 式统计条 + 暂停按钮 + 快捷键气泡 */
#ll-drill-stats {
  display: flex; justify-content: center; gap: 40px;
  max-width: 720px; margin: 18px auto 0; padding: 24px 28px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 14px;
}
#ll-drill-stats .ds-tile { text-align: center; min-width: 76px; }
#ll-drill-stats .ds-num {
  font-size: 22px; font-weight: 700; color: var(--text-primary);
  padding-bottom: 6px; border-bottom: 1px solid var(--border);
}
#ll-drill-stats .ds-label {
  font-size: 12px; color: var(--text-secondary); margin-top: 6px;
}
#ll-ds-pause {
  font-size: 13px; padding: 5px 14px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--border); background: var(--bg-card);
  color: var(--text-primary);
}
#ll-ds-pause:hover { border-color: var(--accent); color: var(--accent); }
[data-ds-tip] { position: relative; }
[data-ds-tip]:hover::after {
  content: attr(data-ds-tip); position: absolute;
  bottom: calc(100% + 7px); left: 50%; transform: translateX(-50%);
  white-space: nowrap; background: var(--text-primary);
  color: var(--bg-card); font-size: 12px; padding: 4px 9px;
  border-radius: 6px; z-index: 1300; pointer-events: none;
}

/* ── Card hover ──
   clickable cards lift & brighten; static info cards only brighten
   (no lift = no false affordance); list rows brighten like tracklist rows.
   (.uni-* / .egg-pair live in other CSS constants but share this sheet.) */
.search-hit, .note-item, .egg-pair,
.echo-card, .uni-char-card, .uni-event, .quiz-line {
  transition: transform 0.2s ease, background 0.2s ease,
    border-color 0.2s ease;
}
.search-hit.seekable:hover, .note-item:hover,
.egg-pair:hover {
  transform: translateY(-3px);
  background: var(--bg-card-hover);
}
.echo-card:hover, .uni-char-card:hover, .uni-event:hover,
.quiz-line:hover {
  background: var(--bg-card-hover);
}
#ll-songs label:hover, #ll-catalog label:hover {
  background: var(--bg-card-hover) !important;
}

/* ── 📊 数据分析：全屏页 + 竖向年历热力图（仿 qwerty-learner）──── */
.hm-overlay {
  position: fixed; inset: 0; z-index: 2000; overflow-y: auto;
  background-color: #eef3f2; padding: 28px 16px 60px;
}
.hm-sheet { max-width: 880px; margin: 0 auto; text-align: center; }
.hm-page-title { font-size: 20px; font-weight: 700;
  color: var(--text-primary); margin-bottom: 18px; position: relative; }
.hm-close { position: absolute; right: 0; top: 0; cursor: pointer;
  color: var(--text-secondary); font-size: 18px; padding: 0 6px; }
.hm-close:hover { color: var(--text-primary); }
/* ❓ 口径说明：✕ 右侧的小按钮，点开浮出说明卡 */
.hm-help { position: absolute; right: -54px; top: -4px; }
.hm-help summary { list-style: none; cursor: pointer; font-size: 15px;
  padding: 3px 8px; border: 1px solid var(--border); border-radius: 9px;
  background-color: var(--bg-card); }
.hm-help summary::-webkit-details-marker { display: none; }
.hm-help[open] summary, .hm-help summary:hover {
  background-color: var(--bg-card-hover); }
.hm-help-pop { position: absolute; right: 0; top: 36px; z-index: 20;
  width: 320px; padding: 14px 16px; text-align: center;
  font-size: 12.5px; font-weight: 400; line-height: 1.7;
  color: var(--text-primary); background-color: var(--bg-card);
  border: 1px solid var(--border); border-radius: 12px;
  box-shadow: var(--card-shadow); }
.hm-help-pop b { color: var(--accent); }
.hm-nums { display: flex; gap: 26px; justify-content: center;
  align-items: flex-start; margin-bottom: 20px;
  color: var(--text-secondary); font-size: 13px; }
.hm-stat summary { cursor: pointer; list-style: none; padding: 6px 14px;
  border: 1px solid var(--border); border-radius: 10px;
  background-color: var(--bg-card); }
.hm-stat summary::-webkit-details-marker { display: none; }
.hm-stat[open] summary, .hm-stat summary:hover {
  background-color: var(--bg-card-hover); }
.hm-stat b { color: var(--accent); font-size: 17px; margin-right: 3px; }
.hm-words { max-width: 230px; max-height: 240px; overflow-y: auto;
  margin-top: 6px; padding: 8px; display: flex; flex-wrap: wrap; gap: 5px;
  justify-content: center; border: 1px solid var(--border);
  border-radius: 10px; background-color: var(--bg-card); }
.hm-chip { padding: 2px 8px; border-radius: 8px; font-size: 12px;
  background-color: var(--accent-soft); color: var(--text-primary); }
.hm-chip-none { color: var(--text-secondary); font-size: 12px; }
.hm-wk-box { max-width: 340px; display: block; }
.hm-wk { width: 100%; border-collapse: collapse; font-size: 12px;
  color: var(--text-primary); }
.hm-wk th { font-weight: 600; color: var(--text-secondary);
  padding: 3px 8px; border-bottom: 1px solid var(--border); }
.hm-wk td { padding: 3px 8px; text-align: center; }
.hm-wk .hm-wk-w { text-align: left; font-weight: 500; }
.hm-wk tr:nth-child(even) { background-color: var(--accent-soft); }
.hm-th-sort { cursor: pointer; user-select: none; white-space: nowrap; }
.hm-th-sort:hover { color: var(--accent); }
.hm-sort { font-size: 11px; color: var(--accent); }
.hm-charts { display: flex; flex-direction: column; gap: 34px;
  align-items: center; }
.hm-chart { display: inline-block; }
.hm-title { font-size: 15px; font-weight: 600; color: var(--text-primary);
  margin-bottom: 4px; }
.hm-grid { display: flex; gap: 3px; justify-content: center;
  padding-top: 16px; }
.hm-week { display: flex; flex-direction: column; gap: 3px;
  position: relative; }
.hm-week[data-m]:not([data-m=""])::before {
  content: attr(data-m); position: absolute; top: -15px; left: 0;
  font-size: 10px; color: var(--text-secondary); white-space: nowrap;
}
.hm-wd { display: flex; flex-direction: column; gap: 3px;
  margin-right: 4px; }
.hm-wd i { width: 13px; height: 12px; font-size: 9px; font-style: normal;
  color: var(--text-secondary); line-height: 12px; }
.hm-c { width: 12px; height: 12px; border-radius: 3px; display: block;
  background-color: var(--border); }
.hm-c.l1 { background-color: color-mix(in srgb, var(--accent) 30%, #fff); }
.hm-c.l2 { background-color: color-mix(in srgb, var(--accent) 55%, #fff); }
.hm-c.l3 { background-color: color-mix(in srgb, var(--accent) 80%, #fff); }
.hm-c.l4 { background-color: var(--pink); }
.hm-empty { padding: 40px 0; color: var(--text-secondary); font-size: 14px; }
"""


