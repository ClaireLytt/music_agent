"""Static front-end assets for the Gradio app: the global JS (Blocks
head) and the stylesheet. Split out of ui.py — plain string constants,
no imports."""

_HEAD_JS = """
<script src="https://cdnjs.cloudflare.com/ajax/libs/wavesurfer.js/7.8.6/wavesurfer.min.js" defer></script>
<script>
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
      const t = setInterval(() => {
        const el = document.querySelector(
          '#lyrics-scroll .lyric-line[data-index="' + pend + '"]');
        if (el) {
          clearInterval(t);
          el.scrollIntoView({ block: 'center' });
          el.classList.add('cite-flash');
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
  let lastQuery = '';
  let saved = null;  // {word, line, song} of the open popover
  function closePop() {
    document.querySelectorAll('.ll-dict-pop').forEach((p) => p.remove());
  }
  function sendChannel(id, value) {
    const box = document.querySelector('#' + id + ' textarea, #' + id + ' input');
    if (!box) return false;
    box.value = value;
    box.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  }
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.ll-dict-pop')) closePop();
  }, true);
  document.addEventListener('dblclick', (e) => {
    const lineEl = e.target.closest('.lyric-line');
    if (!lineEl) return;
    const sel = window.getSelection();
    const word = (sel ? sel.toString() : '').trim();
    if (!/^[A-Za-z][A-Za-z'\u2019-]{1,31}$/.test(word)) return;
    closePop();
    const line = (lineEl.querySelector('.lyric-text') || lineEl).textContent.trim();
    const titleEl = document.querySelector('.song-title-display');
    const song = titleEl ? titleEl.textContent.trim() : '';
    saved = { word: word, line: line, song: song };
    const pop = document.createElement('div');
    pop.className = 'll-dict-pop';
    pop.innerHTML = '<div class="dict-body">⏳ 查询中…</div>';
    let rect = lineEl.getBoundingClientRect();
    try {
      const r = sel.getRangeAt(0).getBoundingClientRect();
      if (r && r.width) rect = r;
    } catch (err) {}
    pop.style.left = Math.min(rect.left, window.innerWidth - 300) + 'px';
    pop.style.top = Math.min(rect.bottom + 6, window.innerHeight - 160) + 'px';
    document.body.appendChild(pop);
    lastQuery = word + '\\t' + line + '\\t' + song + '\\t' + Date.now();
    sendChannel('ll-dict-pick', lastQuery);
  });
  function render(data) {
    const pop = document.querySelector('.ll-dict-pop');
    if (!pop || !saved) return;
    const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
    let html = '<div class="dict-word">' + esc(data.word);
    if (data.phonetic) html += ' <span class="dict-phon">/' + esc(data.phonetic) + '/</span>';
    html += '</div>';
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
    const favBtn = pop.querySelector('[data-dict-fav]');
    if (favBtn) favBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      sendChannel('ll-wb-act', 'add:' + saved.word + '\\t' + saved.line
                  + '\\t' + saved.song + '\\t' + Date.now());
      favBtn.textContent = '✓ 已收藏';
      favBtn.disabled = true;
    });
    const aiBtn = pop.querySelector('[data-dict-ai]');
    if (aiBtn) aiBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      aiBtn.textContent = '✨ 生成中…';
      aiBtn.disabled = true;
      lastQuery = saved.word + '\\t' + saved.line + '\\t' + saved.song
                  + '\\t' + Date.now();
      sendChannel('ll-dict-ai', lastQuery);
    });
  }
  let lastSeen = '';
  setInterval(() => {
    const box = document.querySelector('#ll-dict-out textarea, #ll-dict-out input');
    if (!box || !box.value || box.value === lastSeen) return;
    lastSeen = box.value;
    let data;
    try { data = JSON.parse(box.value); } catch (err) { return; }
    if (data.q !== lastQuery) return;  // stale result for a previous word
    render(data);
  }, 300);
})();
// ⌨️ 单词练习: qwerty-learner-style keystroke loop. The backend renders a
// .ll-type-card (data-word/data-mp3/data-nonce); this block owns typing:
// correct letters color up, one wrong key resets the whole word, completion
// reports through the ll-review-done channel.
(() => {
  function sendChannel(id, value) {
    const box = document.querySelector('#' + id + ' textarea, #' + id + ' input');
    if (!box) return;
    box.value = value;
    box.dispatchEvent(new Event('input', { bubbles: true }));
  }
  let nonce = null, pos = 0, mistakes = 0, t0 = 0, done = false;
  const card = () => document.querySelector('.ll-type-card');
  const chars = (c) => c.querySelectorAll('.tp-ch');
  function reset(c) {
    pos = 0;
    chars(c).forEach((el) => el.classList.remove('ok'));
  }
  function play(c) {
    if (c.dataset.mp3) new Audio(c.dataset.mp3).play().catch(() => {});
  }
  setInterval(() => {
    const c = card();
    if (!c || c.dataset.nonce === nonce) return;
    nonce = c.dataset.nonce;
    mistakes = 0; t0 = Date.now(); done = false;
    reset(c);
    // only grab focus while the practice tab is actually visible
    if (c.offsetParent !== null) {
      const inp = c.querySelector('.ll-type-input');
      if (inp) inp.focus();
      play(c);
    }
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
      const inp = c.querySelector('.ll-type-input');
      if (inp) inp.focus();
    }, true));
  document.addEventListener('keydown', (e) => {
    if (!e.target.classList || !e.target.classList.contains('ll-type-input'))
      return;
    const c = card();
    if (!c || done) return;
    if (e.isComposing || e.keyCode === 229) {   // CJK IME is active
      c.classList.add('tp-ime');
      e.preventDefault();
      return;
    }
    c.classList.remove('tp-ime');
    if (e.key.length !== 1) return;             // let Tab/F5/etc through
    e.preventDefault();                          // space must not scroll
    const want = c.dataset.word;
    const spans = chars(c);
    if (e.key.toLowerCase() === want[pos]) {
      spans[pos].classList.add('ok');
      pos += 1;
      if (pos >= want.length) {
        done = true;
        sendChannel('ll-review-done',
                    want + '\\t' + mistakes + '\\t' + (Date.now() - t0)
                    + '\\t' + Date.now());
      }
    } else {
      mistakes += 1;                             // wrong key: retype it all
      reset(c);
      c.classList.remove('tp-shake');
      void c.offsetWidth;                        // restart the animation
      c.classList.add('tp-shake');
    }
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
      menu.style.top = (r.bottom + 4) + 'px';
      menu.style.left = Math.max(8, r.right - 150) + 'px';
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
        delBox.value = cur.value + '\\t' + Date.now();
        delBox.dispatchEvent(new Event('input', { bubbles: true }));
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
  // player tools state (survives per-song re-renders of the audio block)
  let abStart = null, abEnd = null;
  let radioOn = false, rhymeOn = false, radioPending = false;
  let tourOn = false;
  let lastAudioEl = null;

  function getAudio() { return document.getElementById('ll-audio'); }
  // preview clips start mid-song: lyric-time = audio-time + offset
  function getOffset(audio) { return parseFloat(audio.dataset.offset || '0'); }

  function fmt(t) {
    const s = Math.max(0, Math.floor(t));
    return String(Math.floor(s / 60)).padStart(2, '0') + ':' +
           String(s % 60).padStart(2, '0');
  }

  // write into a hidden gradio textbox channel and notify the backend
  function writeChannel(id, value) {
    const box = document.querySelector('#' + id + ' textarea, #' + id + ' input');
    if (!box) return;
    box.value = value;
    box.dispatchEvent(new Event('input', { bubbles: true }));
  }

  // 🎧 导览: commentary card for the line that just became active
  function maybeTourCard(idx) {
    if (!tourOn) return;
    const box = document.querySelector('#ll-echo-map textarea, #ll-echo-map input');
    if (!box || !box.value) return;
    let data;
    try { data = JSON.parse(box.value); } catch (e) { return; }
    const title = document.querySelector('.song-title-display');
    if (!title || title.textContent.trim() !== data.song) return;
    document.querySelectorAll('.ll-tour-card').forEach((c) => c.remove());
    const o = (data.lines || []).find((l) => l.i === idx);
    if (!o) return;
    const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
    const card = document.createElement('div');
    card.className = 'll-tour-card';
    let html = '<div class="tour-head">🎧 AI 导览</div>';
    if (o.note) html += '<div class="tour-note">📝 ' + esc(o.note) + '</div>';
    html += '<div class="tour-echo">🥚 这句呼应《' + esc(o.song) + '》';
    if (o.target) html += '：“' + esc(o.target) + '”';
    html += '</div><div class="tour-hint">点击卡片关闭 · 详情见右侧 🥚 面板</div>';
    card.innerHTML = html;
    card.addEventListener('click', () => {
      card.remove();
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      restoreDuck();
    });
    document.body.appendChild(card);
    setTimeout(() => { if (card.isConnected) card.remove(); }, 9000);
    speakTour(o);
  }

  // DJ voice via the browser's own TTS — zero backend, works offline;
  // silently absent when the platform ships no voices
  function restoreDuck() {
    const a = getAudio();
    if (a && a.dataset.llBaseVol) {
      a.volume = parseFloat(a.dataset.llBaseVol);
      delete a.dataset.llBaseVol;
    }
  }

  function speakTour(o) {
    try {
      const synth = window.speechSynthesis;
      if (!synth) return;
      // cancel() does NOT reliably fire the old utterance's 'end' event,
      // so restore from the stored base volume before ducking again
      synth.cancel();
      restoreDuck();
      let text = '';
      if (o.note) text += o.note + '。';
      text += '这句呼应了《' + o.song + '》';
      if (o.target) text += '里的：' + o.target;
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'zh-CN';
      u.rate = 1.15;
      const a = getAudio();
      if (a && !a.paused) {
        a.dataset.llBaseVol = String(a.volume);
        a.volume = Math.max(0.15, a.volume * 0.3);
        u.addEventListener('end', restoreDuck);
        u.addEventListener('error', restoreDuck);
      }
      synth.speak(u);
    } catch (err) {}
  }

  function applyRhyme() {
    const c = document.getElementById('lyrics-container');
    if (c) c.classList.toggle('rhyme-on', rhymeOn);
  }

  // waveform: wavesurfer (CDN) drawing on top of the native audio element;
  // silently absent when the CDN is unreachable
  function initWave(a) {
    const holder = document.getElementById('ll-wave');
    if (!holder) return;
    if (!window.WaveSurfer) {
      // the deferred CDN script may not have loaded yet on first render —
      // retry for a while (still this song's audio element) before giving up
      holder.style.display = 'none';
      a._llWaveTries = (a._llWaveTries || 0) + 1;
      if (a._llWaveTries <= 20)
        setTimeout(() => { if (getAudio() === a) initWave(a); }, 500);
      return;
    }
    try {
      if (window._llWave) { window._llWave.destroy(); window._llWave = null; }
      holder.style.display = 'block';
      window._llWave = WaveSurfer.create({
        container: holder, media: a, height: 54,
        waveColor: '#c9d4df', progressColor: '#0969da',
        cursorColor: '#0969da', barWidth: 2, barGap: 1, barRadius: 1,
      });
    } catch (err) { holder.style.display = 'none'; }
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
        if (idx >= 0 && idx !== undefined) maybeTourCard(idx);
        lastActive = idx;
      }
      // A-B loop: jump back to A whenever playback passes B
      if (abStart !== null && abEnd !== null && !audio.paused
          && audio.currentTime >= abEnd) {
        audio.currentTime = abStart;
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

  // new-song watcher: the audio block is re-rendered per song, so restore
  // toggle states, rebuild the waveform, reset the A-B loop, and (in radio
  // mode) play the spoken intro before the song itself
  setInterval(() => {
    const a = getAudio();
    if (!a || a === lastAudioEl) return;
    lastAudioEl = a;
    abStart = abEnd = null;
    const r = document.getElementById('ll-radio-toggle');
    if (r) r.checked = radioOn;
    const y = document.getElementById('ll-rhyme-toggle');
    if (y) y.checked = rhymeOn;
    const tg = document.getElementById('ll-tour-toggle');
    if (tg) tg.checked = tourOn;
    applyRhyme();
    initWave(a);
    if (radioPending) {
      radioPending = false;
      const intro = a.dataset.intro;
      if (radioOn && intro) {
        const voice = new Audio(intro);
        voice.addEventListener('ended', () => a.play().catch(() => {}));
        // a broken intro file fires 'error', never 'ended' — don't stall
        voice.addEventListener('error', () => a.play().catch(() => {}));
        voice.play().catch(() => { a.play().catch(() => {}); });
      } else if (radioOn) {
        a.play().catch(() => {});
      }
    }
  }, 500);

  // radio mode: when the song ends, advance to the next one in the list
  document.addEventListener('ended', function(e) {
    if (!e.target || e.target.id !== 'll-audio' || !radioOn) return;
    const inputs = Array.from(
      document.querySelectorAll('#ll-songs input[type=radio]'));
    if (!inputs.length) return;
    const i = inputs.findIndex(x => x.checked);
    radioPending = true;
    inputs[(i + 1) % inputs.length].click();
  }, true);  // 'ended' does not bubble — capture it

  // toggle listeners (delegated: the checkboxes are re-rendered per song)
  document.addEventListener('change', function(e) {
    if (!e.target) return;
    if (e.target.id === 'll-radio-toggle') radioOn = e.target.checked;
    if (e.target.id === 'll-tour-toggle') {
      tourOn = e.target.checked;
      if (!tourOn) {
        document.querySelectorAll('.ll-tour-card').forEach((c) => c.remove());
        if (window.speechSynthesis) window.speechSynthesis.cancel();
        restoreDuck();
      }
    }
    if (e.target.id === 'll-rhyme-toggle') {
      rhymeOn = e.target.checked;
      applyRhyme();
    }
  }, true);

  // player-tool buttons + click-to-backend channels (capture phase so a
  // delete click doesn't also trigger the note's data-seek)
  document.addEventListener('click', function(e) {
    if (!e.target.closest) return;
    const audio = getAudio();
    if (e.target.closest('#ll-ab-a') && audio) {
      abStart = audio.currentTime; abEnd = null;
      e.target.closest('#ll-ab-a').textContent = '🅰 ' + fmt(abStart);
      const b = document.getElementById('ll-ab-b');
      if (b) b.textContent = '🅱 循环';
      const c = document.getElementById('ll-ab-clear');
      if (c) c.style.display = 'none';
      return;
    }
    if (e.target.closest('#ll-ab-b') && audio) {
      if (abStart === null || audio.currentTime <= abStart + 0.3) return;
      abEnd = audio.currentTime;
      e.target.closest('#ll-ab-b').textContent = '🅱 ' + fmt(abEnd);
      const c = document.getElementById('ll-ab-clear');
      if (c) c.style.display = '';
      return;
    }
    if (e.target.closest('#ll-ab-clear')) {
      abStart = abEnd = null;
      const a2 = document.getElementById('ll-ab-a');
      if (a2) a2.textContent = '🅰 起点';
      const b2 = document.getElementById('ll-ab-b');
      if (b2) b2.textContent = '🅱 循环';
      e.target.closest('#ll-ab-clear').style.display = 'none';
      return;
    }
    const del = e.target.closest('[data-del-note]');
    if (del) {
      e.stopPropagation();
      writeChannel('ll-note-del', del.dataset.delNote + ':' +
                   (del.dataset.delTs || '') + '\\t' + Date.now());
      return;
    }
    const word = e.target.closest('.cloud-word');
    if (word) {
      writeChannel('ll-word-pick', word.dataset.word + '\\t' + Date.now());
      return;
    }
    const emo = e.target.closest('[data-emo-pick]');
    if (emo) {
      writeChannel('ll-emo-pick', emo.dataset.emoPick + '\\t' + Date.now());
      return;
    }
    const ov = e.target.closest('[data-ov-pick]');
    if (ov) {
      writeChannel('ll-ov-pick', ov.dataset.ovPick + '\\t' + Date.now());
      return;
    }
    // 📺 B 站视频模式: toggle shows the frame and lazily sets the iframe
    // src on first use, so song switches never hit bilibili by themselves
    const vt = e.target.closest('[data-video-toggle]');
    if (vt) {
      const frame = document.querySelector('.bv-frame');
      if (frame) {
        const ifr = frame.querySelector('iframe');
        if (ifr && !ifr.src) ifr.src = frame.dataset.embed;
        const show = frame.style.display === 'none';
        frame.style.display = show ? '' : 'none';
        const a = getAudio();
        if (a && show) a.pause();
      }
      return;
    }
    const bvs = e.target.closest('[data-bvid-search]');
    if (bvs) {
      writeChannel('ll-bvid-act', 'search\\t' + Date.now());
      return;
    }
    const bvp = e.target.closest('[data-bvid-pick]');
    if (bvp) {
      writeChannel('ll-bvid-act',
                   'pick\\t' + bvp.dataset.bvidPick + '\\t' + Date.now());
      return;
    }
    const fav = e.target.closest('[data-fav]');
    if (fav) {
      writeChannel('ll-fav-act', fav.dataset.fav + '\\t' + Date.now());
      return;
    }
    const wb = e.target.closest('[data-wb]');
    if (wb) {
      writeChannel('ll-wb-act', wb.dataset.wb + '\\t' + Date.now());
      return;
    }
    const cite = e.target.closest('[data-cite-label]');
    if (cite) {
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
          setTimeout(() => el.classList.remove('cite-flash'), 2600);
        }
        return;
      }
      // remember the cited line; the song-switch watcher scrolls to it
      // once the lyrics re-render
      window.__llPendingLine = lineNo;
      writeChannel('ll-cite-jump',
                   cite.dataset.citeLabel + '\\t' + cite.dataset.citeLine
                   + '\\t' + Date.now());
      return;
    }
    if (e.target.closest('details.egg-more')) return;  // expand, not pick
    const fp = e.target.closest('[data-focus-pick]');
    if (fp) {
      writeChannel('ll-focus-pick', fp.dataset.focusPick + '\\t' + Date.now());
    }
  }, true);

  // 彩蛋地图 network view: hovering a song dims unrelated edges and nodes
  // so its connections stand out (focus view has no data-ega edges, so
  // the toggles below never fire there)
  document.addEventListener('mouseover', (e) => {
    const svg = e.target.closest('.egg-svg');
    if (!svg || !svg.querySelector('.egg-edge[data-ega]')) return;
    const g = e.target.closest('[data-focus-pick]');
    const song = g ? g.dataset.focusPick : null;
    const keep = new Set(song ? [song] : []);
    svg.querySelectorAll('.egg-edge[data-ega]').forEach(p => {
      const on = !song || p.dataset.ega === song || p.dataset.egb === song;
      p.classList.toggle('egg-dim', !on);
      p.classList.toggle('egg-lit', !!song && on);
      if (song && on) { keep.add(p.dataset.ega); keep.add(p.dataset.egb); }
    });
    svg.querySelectorAll('[data-focus-pick]').forEach(nd => {
      nd.classList.toggle('egg-dim', !!song && !keep.has(nd.dataset.focusPick));
    });
  }, true);
  document.addEventListener('mouseout', (e) => {
    const svg = e.target.closest('.egg-svg');
    if (!svg || svg.contains(e.relatedTarget)) return;
    svg.querySelectorAll('.egg-dim, .egg-lit').forEach(
      el => el.classList.remove('egg-dim', 'egg-lit'));
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
      const pick = document.querySelector('#ll-line-pick textarea, #ll-line-pick input');
      if (pick) {
        pick.value = line.dataset.index;
        pick.dispatchEvent(new Event('input', { bubbles: true }));
      }
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
</script>
"""

# ── CSS ───────────────────────────────────────────────────

_CSS = """\
:root {
  --bg-primary: #ffffff;
  --bg-secondary: #f6f8fa;
  --bg-card: #f6f8fa;
  --bg-card-hover: #eaeef2;
  --text-primary: #1f2328;
  --text-secondary: #656d76;
  --text-played: #a9b1ba;
  --accent: #0969da;
  --accent-soft: rgba(9, 105, 218, 0.08);
  --accent-glow: rgba(9, 105, 218, 0.15);
  --border: #d0d7de;
  --karaoke-rest: #57606a; /* un-sung part of the active karaoke line */
  --lyric-dim: rgba(31, 35, 40, 0.52); /* upcoming lyric lines */
}

body, .gradio-container { background: var(--bg-primary) !important; }

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
#ll-songs label, #ll-catalog label { width: 100%; }
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
  border-radius: 8px !important;
}
.gradio-container input:focus, .gradio-container textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 2px var(--accent-soft) !important;
}
.gradio-container input::placeholder, .gradio-container textarea::placeholder {
  color: var(--text-secondary) !important; opacity: 0.6;
}

.app-header { text-align: center; padding: 16px 0 4px; }
.app-header h1 { color: var(--accent); font-size: 26px; margin: 0; font-weight: 700; }
.app-header p { color: var(--text-secondary); margin: 4px 0 0; font-size: 14px; }

/* ── Chip tab navigation: grey pills, selected = solid blue ── */
.gradio-container .tab-nav, .gradio-container div[role="tablist"] {
  justify-content: center; gap: 8px; border-bottom: none !important;
  padding-bottom: 2px; margin-bottom: 14px; flex-wrap: wrap;
}
.gradio-container .tab-nav button, .gradio-container button[role="tab"] {
  font-size: 15px !important; font-weight: 700 !important;
  padding: 8px 18px !important; border-radius: 500px !important;
  color: var(--text-secondary) !important;
  background: var(--bg-card-hover) !important;
  border: none !important;
  transition: background 0.2s ease, color 0.2s ease;
}
.gradio-container .tab-nav button:hover, .gradio-container button[role="tab"]:hover {
  color: var(--text-primary) !important; background: #dfe5eb !important;
}
.gradio-container .tab-nav button.selected,
.gradio-container button[role="tab"][aria-selected="true"] {
  color: #ffffff !important; background: var(--accent) !important;
}

/* ── Pill buttons, blue on white ── */
.gradio-container button.primary {
  background: var(--accent) !important; color: #ffffff !important;
  border: none !important; border-radius: 500px !important;
  font-weight: 700 !important; box-shadow: none !important;
  transition: background 0.15s ease, transform 0.15s ease;
}
.gradio-container button.primary:hover {
  background: #0a5ac1 !important; transform: scale(1.03);
}
.gradio-container button.primary:active { transform: scale(0.98); }
.gradio-container button.secondary {
  background: #ffffff !important; color: var(--text-primary) !important;
  border: 1px solid var(--border) !important; border-radius: 500px !important;
  font-weight: 600 !important; box-shadow: none !important;
  transition: border-color 0.15s ease, color 0.15s ease, transform 0.15s ease;
}
.gradio-container button.secondary:hover {
  border-color: var(--accent) !important; color: var(--accent) !important;
  transform: scale(1.03);
}

.ll-hidden { display: none !important; }

.side-panel-title {
  font-size: 15px; font-weight: 700; color: var(--text-primary);
  padding: 4px 2px 6px; border-bottom: 2px solid var(--accent-soft); margin-bottom: 8px;
}

/* Song header */
.song-header {
  display: flex; align-items: center; gap: 14px;
  padding: 12px 20px; border-bottom: 1px solid var(--border); margin-bottom: 8px;
}
.song-title-display { margin: 0; font-size: 22px; font-weight: 700; color: var(--text-primary); }
.song-meta-display { margin: 2px 0 0; font-size: 13px; color: var(--text-secondary); }

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
  padding: 8px 16px; border-radius: 8px; cursor: pointer;
  transition: all 0.25s ease; border-left: 3px solid transparent;
}
.lyric-line:hover { background: var(--bg-card-hover); }
.lyric-line.picked { background: var(--accent-soft); border-left-color: var(--accent); }
.lyric-line.played .lyric-text { color: var(--text-played); }
.lyric-line.active { background: var(--accent-glow); border-left-color: var(--accent); transform: scale(1.02); }
.lyric-line.active .lyric-text { color: var(--text-primary); font-weight: 800; font-size: 19px; }
/* karaoke sweep: JS drives a gradient over the active line's text; the
   estimated progress paints sung characters accent-blue */
@supports (-webkit-background-clip: text) or (background-clip: text) {
  .lyric-line.active .lyric-text[style*="background-image"] {
    -webkit-background-clip: text; background-clip: text;
    color: transparent; -webkit-text-fill-color: transparent;
  }
}
.lyric-text {
  font-size: 17px; font-weight: 700; color: var(--lyric-dim);
  letter-spacing: -0.01em; transition: all 0.25s ease; line-height: 1.6;
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

/* player tools (chorus / A-B loop / toggles) */
#ll-wave { width: 100%; min-height: 0; }
.player-tools {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  padding: 6px 2px 0;
}
.ptool {
  font-size: 12px; padding: 3px 10px; border-radius: 14px; cursor: pointer;
  background: var(--bg-card); border: 1px solid var(--border);
  color: var(--text-primary);
}
.ptool:hover { border-color: var(--accent); color: var(--accent); }
.ptool-toggle {
  font-size: 12px; color: var(--text-secondary); cursor: pointer;
  display: inline-flex; align-items: center; gap: 4px;
}

/* end-rhyme dots: hidden until the 🎯 韵脚 toggle adds .rhyme-on */
.rhyme-mark {
  display: none; width: 9px; height: 9px; border-radius: 50%;
  margin-left: 8px; vertical-align: middle;
}
#lyrics-container.rhyme-on .rhyme-mark { display: inline-block; }

/* listening notes */
.note-list { display: flex; flex-direction: column; gap: 5px; max-height: 32vh; overflow-y: auto; }
.note-item {
  display: flex; gap: 8px; align-items: baseline; cursor: pointer;
  padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-card); font-size: 13px;
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
  justify-content: center; gap: 6px;
  border-top: none !important;
  border-bottom: 1px solid var(--border) !important;
  padding: 2px 0 8px; margin: 0 0 10px;
  position: relative; z-index: 3; background: var(--bg-primary);
}
.ll-icon-dock > .tabitem, .ll-icon-dock > div[role="tabpanel"] {
  overflow: visible; padding-bottom: 6px;
}
.ll-icon-dock > .tab-nav button, .ll-icon-dock button[role="tab"] {
  font-size: 18px !important; font-weight: 400 !important;
  padding: 6px 12px !important; border-radius: 10px !important;
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
.ll-tour-card {
  position: fixed; right: 18px; bottom: 18px; z-index: 1100; width: 300px;
  padding: 12px 14px; border-radius: 12px; cursor: pointer;
  background: var(--bg-card); border: 1px solid var(--border);
  box-shadow: 0 10px 30px rgba(15, 23, 42, .18);
  font-size: 12.5px; line-height: 1.65;
  animation: ll-tour-in .35s ease-out;
}
@keyframes ll-tour-in {
  from { transform: translateY(14px); opacity: 0; }
  to { transform: none; opacity: 1; }
}
.ll-tour-card .tour-head { font-weight: 700; margin-bottom: 4px; }
.ll-tour-card .tour-note { color: var(--text-primary); margin-bottom: 4px; }
.ll-tour-card .tour-echo { color: var(--text-primary); }
.ll-tour-card .tour-hint { margin-top: 6px; font-size: 11px; color: var(--text-secondary); }

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
  0%, 60% { background: var(--accent-soft); }
  100% { background: transparent; }
}
.lyric-line.cite-flash { animation: ll-cite-flash 2.5s ease-out; border-radius: 8px; }

/* mini translator popover + wordbook */
.ll-dict-pop {
  position: fixed; z-index: 1200; width: 290px; padding: 12px 14px;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: 0 10px 30px rgba(15, 23, 42, .18);
  font-size: .9em; line-height: 1.55;
}
.ll-dict-pop .dict-word { font-weight: 700; margin-bottom: 4px; }
.ll-dict-pop .dict-phon { color: var(--text-secondary); font-weight: 400; }
.ll-dict-pop .dict-body { color: var(--text-primary); max-height: 150px; overflow-y: auto; }
.ll-dict-pop .dict-miss { color: var(--text-secondary); }
.ll-dict-pop .dict-ai {
  margin-top: 8px; padding: 8px 10px; border-radius: 8px;
  background: var(--accent-soft); color: var(--text-primary);
}
.ll-dict-pop .dict-actions { margin-top: 10px; display: flex; gap: 8px; }
.ll-dict-pop .dict-btn {
  all: unset; cursor: pointer; padding: 5px 10px; border-radius: 8px;
  background: var(--bg-card-hover); font-size: .92em;
}
.ll-dict-pop .dict-btn:hover { background: var(--accent-soft); }
.ll-dict-pop .dict-btn[disabled] { opacity: .6; cursor: default; }
.wb-list { display: flex; flex-direction: column; gap: 8px; }
.wb-item {
  position: relative; padding: 8px 26px 8px 10px; border-radius: 10px;
  background: var(--bg-card); border: 1px solid var(--border);
}
.wb-item .wb-word { font-weight: 700; }
.wb-item .wb-phon { color: var(--text-secondary); font-weight: 400; font-size: .9em; }
.wb-item .wb-meaning { font-size: .9em; color: var(--text-primary); }
.wb-item .wb-src { font-size: .85em; color: var(--text-secondary); margin-top: 2px; }
.wb-item .wb-ai { font-size: .85em; color: var(--text-primary); margin-top: 4px;
  padding: 6px 8px; background: var(--accent-soft); border-radius: 8px;
  line-height: 1.5; }
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
  border-radius: 14px; background: var(--bg-card); cursor: text; }
.ll-type-card .tp-word { font-size: 34px; font-weight: 800;
  letter-spacing: 3px; color: var(--karaoke-rest); margin-bottom: 10px; }
.ll-type-card .tp-ch.ok { color: var(--accent); }
.ll-type-card .ll-type-input { position: absolute; opacity: 0;
  width: 1px; height: 1px; border: 0; padding: 0; }
.ll-type-card .wb-meaning, .ll-type-card .wb-src, .ll-type-card .wb-ai {
  margin-top: 6px; }
.ll-type-card .tp-ime-hint { display: none; color: #cf222e;
  font-size: .85em; margin-top: 4px; }
.ll-type-card.tp-ime .tp-ime-hint { display: block; }
.ll-type-card .tp-blurhint { font-size: .8em; color: var(--text-secondary);
  margin-top: 10px; }
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

/* lyric favorites */
.fav-list { display: flex; flex-direction: column; gap: 6px;
  max-height: 40vh; overflow-y: auto; scrollbar-width: thin; }
.fav-item { padding: 8px 12px; border: 1px solid var(--border);
  border-radius: 10px; background: var(--bg-card); cursor: pointer; }
.fav-item:hover { border-color: var(--accent); }
.fav-line { font-size: 13px; font-style: italic; color: var(--text-primary); }
.fav-song { font-size: 12px; color: var(--text-secondary); margin-top: 3px; }
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

/* whole-song easter-egg overview (🗺️ 本歌彩蛋总览) */
.echo-ov-head { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.echo-ov-list { max-height: 40vh; overflow-y: auto; scrollbar-width: thin; }
.echo-ov-item {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--bg-card); margin-bottom: 6px; cursor: pointer;
  transition: border-color 0.15s ease;
}
.echo-ov-item:hover { border-color: var(--accent); }
.echo-ov-src { font-size: 13px; font-style: italic; color: var(--text-primary); }
.echo-ov-dst { font-size: 12px; color: var(--text-secondary); margin-top: 3px; }
.echo-ov-sim { margin-left: 6px; font-size: 11px; color: var(--accent); }

/* ── Card hover ──
   clickable cards lift & brighten; static info cards only brighten
   (no lift = no false affordance); list rows brighten like tracklist rows.
   (.uni-* / .egg-pair live in other CSS constants but share this sheet.) */
.search-hit, .echo-ov-item, .note-item, .egg-pair,
.echo-card, .uni-char-card, .uni-event, .quiz-line {
  transition: transform 0.2s ease, background 0.2s ease,
    border-color 0.2s ease;
}
.search-hit.seekable:hover, .echo-ov-item:hover, .note-item:hover,
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
"""


