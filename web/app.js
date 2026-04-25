/* ═══════════════════════════════════════════════════
   ДУРАК — Telegram Mini App
   ═══════════════════════════════════════════════════ */

const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready(); tg.expand();
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  tg.setHeaderColor?.(dark ? '#111111' : '#ffffff');
  tg.setBackgroundColor?.(dark ? '#111111' : '#ffffff');
}

// Block direct browser access (no Telegram initData)
const _isLocalhost = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
if (!tg?.initData && !_isLocalhost) {
  document.body.innerHTML = `
    <div style="
      position:fixed;inset:0;display:flex;flex-direction:column;
      align-items:center;justify-content:center;
      background:#111;color:#fff;font-family:sans-serif;
      text-align:center;padding:32px;gap:16px;
    ">
      <div style="font-size:48px">🃏</div>
      <div style="font-size:20px;font-weight:700">Дурак</div>
      <div style="font-size:15px;opacity:0.7;max-width:280px;line-height:1.5">
        Игра доступна только через Telegram.<br>Откройте приложение в клиенте Telegram.
      </div>
    </div>`;
  throw new Error('no initData');
}

const SUIT_GLYPH  = { S: '♠', C: '♣', H: '♡', D: '♢' };
const SUIT_FILLED = { S: '♠', C: '♣', H: '♥', D: '♦' };
const RED_SUITS   = new Set(['H', 'D']);
const RANK_VALUE  = { '6':0,'7':1,'8':2,'9':3,'10':4,'J':5,'Q':6,'K':7,'A':8 };
const RANK_VALUE_52 = { '2':0,'3':1,'4':2,'5':3,'6':4,'7':5,'8':6,'9':7,'10':8,'J':9,'Q':10,'K':11,'A':12 };
function rankValues() { return state?.deck_size === 52 ? RANK_VALUE_52 : RANK_VALUE; }

const $  = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));

const ACTION_LABEL = { done: 'БИТО', take: 'БЕРУ — подкидывай!', transfer: 'ПЕРЕВОД' };
const ACTION_DELAY = { done: 750, take: 850 };

/* ── App state ──────────────────────────────────── */
let ws            = null;
let state         = null;
let selected      = null;
let prevTable     = new Set();
let prevDefended  = new Set(); // attacks whose defend card is already rendered
let prevHand      = new Set();
let prevAction    = null;
let lastWaiting   = null;
let resultApplied    = false;
let resultHadPayouts = false;
let discardCount      = 0;
let takeAnimTriggered = false;
let endSoundPlayed = false;
let freshCardsList = [];

/* ── Ready check ─────────────────────────────────── */
let rcInterval  = null;
let rcSeconds   = 10;
let rcReady     = false;

/* ── Profile (server-authoritative) ─────────────── */
let myCoins     = null;
let myCardSkin  = 'classic';
let myTableSkin = 'default';
let myName      = '';
let myAvatar    = null;
let myId        = null;
let myStats     = { games: 0, wins: 0, losses: 0, draws: 0, streak: 0, best_streak: 0 };
let myRank      = { title: 'Рядовой', pogon: { type: 'blank' } };

/* ── Shop state ─────────────────────────────────── */
let shopData              = null;
let shopActiveTab         = 'cards';
let myEquippedCustomPackId = null;

/* ── Emoji pack state ────────────────────────────── */
let activeEmojis = ['👍', '😂', '🤡', '🔥', '😤', '🫡'];

function updateEmojiBar(emojis, imgUrls) {
  const bar = $('#emoji-bar');
  if (!bar) return;
  bar.innerHTML = '';
  if (imgUrls && imgUrls.length) {
    activeEmojis = imgUrls;
    imgUrls.forEach(url => {
      const btn = document.createElement('button');
      btn.className = 'emoji-btn img-emoji';
      btn.dataset.emoji = url;
      const img = document.createElement('img');
      img.src = url;
      img.className = 'emoji-img';
      btn.appendChild(img);
      bar.appendChild(btn);
    });
  } else if (emojis && emojis.length) {
    activeEmojis = emojis;
    emojis.forEach(e => {
      const btn = document.createElement('button');
      btn.className = 'emoji-btn';
      btn.dataset.emoji = e;
      btn.textContent = e;
      bar.appendChild(btn);
    });
  }
}

/* ── Create game settings ────────────────────────── */
let createSettings = { bet: 100, max_players: 2, deck_size: 36, mode: 'perevodnoy' };

/* ── Timer ──────────────────────────────────────── */
let timerInterval = null;
let timerSeconds  = 0;

/* ── Drag ───────────────────────────────────────── */
let drag = null;
const DRAG_THRESH = 7;

/* ── Flash / emoji cooldown ──────────────────────── */
let flashTimer = null;
let emojiCooldown = false;

/* ── Pending state timeout ───────────────────────── */
let pendingStateTimeout = null;

/* ── Profile popup ───────────────────────────────── */
let pendingProfileTarget = null;

/* ── Ефрейтор easter egg ─────────────────────────── */
let efrGamesData = null; // { games, next_min }
let efrTooltipEl = null;

function showEfrTooltip() {
  if (efrTooltipEl) { efrTooltipEl.remove(); efrTooltipEl = null; return; }
  const badge = $('#efr-badge');
  if (!badge) return;
  const rect = badge.getBoundingClientRect();
  const el = document.createElement('div');
  el.className = 'efr-tooltip';
  const left = Math.min(rect.left, window.innerWidth - 220);
  el.style.left = left + 'px';
  el.style.top  = (rect.bottom + 6) + 'px';
  const gamesLeft = efrGamesData ? (efrGamesData.next_min - efrGamesData.games) : '?';
  el.innerHTML = `<strong>⚠ Ефрейтор</strong>«лучше дочь шлюха,<br>чем сын ефрейтор»`;
  document.body.appendChild(el);
  efrTooltipEl = el;
}

/* ── Pending quick action after leave ────────────── */
let pendingQuickAction = null;

/* ══════════════════════════════════════════════════
   SOUND ENGINE  (Web Audio API, всё синтезировано)
   ══════════════════════════════════════════════════ */
const sfx = (() => {
  let ctx = null;
  function ac() {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
    return ctx;
  }
  function go(fn) { try { fn(ac()); } catch (_) {} }

  return {
    cardPlay() {
      go(c => {
        const len  = Math.floor(c.sampleRate * 0.055);
        const buf  = c.createBuffer(1, len, c.sampleRate);
        const data = buf.getChannelData(0);
        for (let i = 0; i < len; i++)
          data[i] = (Math.random() * 2 - 1) * Math.exp(-i / (len * 0.25));
        const src = c.createBufferSource();
        const hp  = c.createBiquadFilter();
        const gn  = c.createGain();
        hp.type = 'highpass'; hp.frequency.value = 900;
        src.buffer = buf;
        src.connect(hp); hp.connect(gn); gn.connect(c.destination);
        gn.gain.setValueAtTime(0.55, c.currentTime);
        src.start(c.currentTime);
        const o = c.createOscillator(), og = c.createGain();
        o.connect(og); og.connect(c.destination);
        o.type = 'sine';
        o.frequency.setValueAtTime(160, c.currentTime);
        o.frequency.exponentialRampToValueAtTime(55, c.currentTime + 0.07);
        og.gain.setValueAtTime(0.18, c.currentTime);
        og.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.08);
        o.start(c.currentTime); o.stop(c.currentTime + 0.09);
      });
    },
    cardDefend() {
      go(c => {
        const len  = Math.floor(c.sampleRate * 0.05);
        const buf  = c.createBuffer(1, len, c.sampleRate);
        const data = buf.getChannelData(0);
        for (let i = 0; i < len; i++)
          data[i] = (Math.random() * 2 - 1) * Math.exp(-i / (len * 0.3));
        const src = c.createBufferSource();
        const bp  = c.createBiquadFilter();
        const gn  = c.createGain();
        bp.type = 'bandpass'; bp.frequency.value = 700; bp.Q.value = 1.2;
        src.buffer = buf;
        src.connect(bp); bp.connect(gn); gn.connect(c.destination);
        gn.gain.setValueAtTime(0.45, c.currentTime);
        src.start(c.currentTime);
        const o = c.createOscillator(), og = c.createGain();
        o.connect(og); og.connect(c.destination);
        o.type = 'sine';
        o.frequency.setValueAtTime(120, c.currentTime);
        o.frequency.exponentialRampToValueAtTime(45, c.currentTime + 0.08);
        og.gain.setValueAtTime(0.14, c.currentTime);
        og.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.09);
        o.start(c.currentTime); o.stop(c.currentTime + 0.1);
      });
    },
    done() {
      go(c => {
        [0, 0.05, 0.1].forEach((delay, i) => {
          const o = c.createOscillator(), g = c.createGain();
          o.connect(g); g.connect(c.destination);
          const t = c.currentTime + delay;
          o.type = 'sine';
          o.frequency.setValueAtTime(580 - i * 55, t);
          o.frequency.exponentialRampToValueAtTime(180, t + 0.13);
          g.gain.setValueAtTime(0.14, t);
          g.gain.exponentialRampToValueAtTime(0.001, t + 0.15);
          o.start(t); o.stop(t + 0.16);
        });
      });
    },
    take() {
      go(c => {
        const o = c.createOscillator(), g = c.createGain();
        o.connect(g); g.connect(c.destination);
        o.type = 'sine';
        o.frequency.setValueAtTime(220, c.currentTime);
        o.frequency.exponentialRampToValueAtTime(75, c.currentTime + 0.22);
        g.gain.setValueAtTime(0.38, c.currentTime);
        g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.25);
        o.start(c.currentTime); o.stop(c.currentTime + 0.26);
      });
    },
    deal() {
      go(c => {
        const len  = Math.floor(c.sampleRate * 0.03);
        const buf  = c.createBuffer(1, len, c.sampleRate);
        const data = buf.getChannelData(0);
        for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / len);
        const src = c.createBufferSource();
        const flt = c.createBiquadFilter();
        const g   = c.createGain();
        flt.type = 'bandpass'; flt.frequency.value = 2200; flt.Q.value = 1.8;
        src.buffer = buf;
        src.connect(flt); flt.connect(g); g.connect(c.destination);
        g.gain.setValueAtTime(0.32, c.currentTime);
        g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.05);
        src.start(c.currentTime);
      });
    },
    win() {
      go(c => {
        [523, 659, 784, 1047].forEach((f, i) => {
          const o = c.createOscillator(), g = c.createGain();
          o.connect(g); g.connect(c.destination);
          const t = c.currentTime + i * 0.13;
          o.type = 'sine'; o.frequency.setValueAtTime(f, t);
          g.gain.setValueAtTime(0, t);
          g.gain.linearRampToValueAtTime(0.22, t + 0.03);
          g.gain.exponentialRampToValueAtTime(0.001, t + 0.28);
          o.start(t); o.stop(t + 0.29);
        });
      });
    },
    lose() {
      go(c => {
        [400, 330, 280, 210].forEach((f, i) => {
          const o = c.createOscillator(), g = c.createGain();
          o.connect(g); g.connect(c.destination);
          const t = c.currentTime + i * 0.15;
          o.type = 'sawtooth'; o.frequency.setValueAtTime(f, t);
          g.gain.setValueAtTime(0, t);
          g.gain.linearRampToValueAtTime(0.1, t + 0.04);
          g.gain.exponentialRampToValueAtTime(0.001, t + 0.3);
          o.start(t); o.stop(t + 0.31);
        });
      });
    },
    tick() {
      go(c => {
        const o = c.createOscillator(), g = c.createGain();
        o.connect(g); g.connect(c.destination);
        o.type = 'square'; o.frequency.setValueAtTime(1400, c.currentTime);
        g.gain.setValueAtTime(0.07, c.currentTime);
        g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + 0.04);
        o.start(c.currentTime); o.stop(c.currentTime + 0.05);
      });
    },
  };
})();

/* ═══════════════════════════════════════════════════
   AVATAR
   ═══════════════════════════════════════════════════ */
function applyAvatar(el, av) {
  if (!el || !av) return;
  if (av.url) {
    el.style.background = av.color;
    el.style.backgroundImage = `url(${av.url})`;
    el.style.backgroundSize = 'cover';
    el.style.backgroundPosition = 'center';
    el.textContent = '';
  } else {
    el.style.background = av.color;
    el.style.backgroundImage = '';
    el.textContent = av.initials;
  }
}

/* ═══════════════════════════════════════════════════
   ПОГОНЫ
   ═══════════════════════════════════════════════════ */
function buildPogon(pogon, large) {
  const el = document.createElement('div');
  el.className = 'pogon' + (large ? ' lg' : '');
  const type = pogon?.type || 'blank';

  if (type === 'stripes') {
    const n = pogon.n || 1;
    const inner = document.createElement('div');
    inner.style.cssText = 'display:flex;align-items:center;justify-content:center;height:100%;gap:3px;position:relative;z-index:1;padding:0 5px;';
    for (let i = 0; i < n; i++) {
      const s = document.createElement('div');
      s.className = 'pogon-stripe';
      inner.appendChild(s);
    }
    el.appendChild(inner);
  } else if (type === 'bar') {
    const bar = document.createElement('div');
    bar.className = 'pogon-bar';
    el.appendChild(bar);
  } else if (type === 'stars') {
    const line = document.createElement('div');
    line.className = 'pogon-line';
    el.appendChild(line);
    const wrap = document.createElement('div');
    wrap.className = 'pogon-stars';
    const n = pogon.n || 1;
    const sz = pogon.size || 'md';
    if (n === 4) {
      wrap.style.flexWrap = 'wrap';
      wrap.style.width = '100%';
      wrap.style.justifyContent = 'center';
      wrap.style.gap = '1px';
    }
    for (let i = 0; i < n; i++) {
      const star = document.createElement('span');
      star.className = `pogon-star ${sz}`;
      star.textContent = '★';
      wrap.appendChild(star);
    }
    el.appendChild(wrap);
  } else if (type === 'general') {
    el.classList.add('pogon-general');
    const wrap = document.createElement('div');
    wrap.className = 'pogon-stars';
    const star = document.createElement('span');
    star.className = 'pogon-star xl';
    star.textContent = '★';
    wrap.appendChild(star);
    el.appendChild(wrap);
  } else if (type === 'marshal') {
    el.classList.add('pogon-marshal');
    const wrap = document.createElement('div');
    wrap.className = 'pogon-stars';
    const star = document.createElement('span');
    star.className = 'pogon-star xl';
    star.style.color = '#ffd700';
    star.textContent = '✦';
    wrap.appendChild(star);
    el.appendChild(wrap);
  }

  return el;
}

/* ═══════════════════════════════════════════════════
   SKINS
   ═══════════════════════════════════════════════════ */
const SKIN_CLASSES = [
  'skin-card-classic','skin-card-dots','skin-card-cross','skin-card-waves','skin-card-dark',
  'skin-table-default','skin-table-green','skin-table-navy','skin-table-wood','skin-table-marble',
];
function applySkins(cardSkin, tableSkin) {
  const g = $('#game');
  if (!g) return;
  SKIN_CLASSES.forEach(c => g.classList.remove(c));
  if (cardSkin  && cardSkin  !== 'classic')  g.classList.add(`skin-card-${cardSkin}`);
  if (tableSkin && tableSkin !== 'default')  g.classList.add(`skin-table-${tableSkin}`);
}

/* ═══════════════════════════════════════════════════
   COINS DISPLAY
   ═══════════════════════════════════════════════════ */
function refreshCoins() {
  if (myCoins === null) return;
  const fmt = `⬡ ${myCoins.toLocaleString('ru')}`;
  const l = $('#lobby-coins'); if (l) l.textContent = fmt;
  const g = $('#game-coins');  if (g) g.textContent = fmt;
  const s = $('#shop-coins');  if (s) s.textContent = fmt;
}

/* ═══════════════════════════════════════════════════
   TIMER
   ═══════════════════════════════════════════════════ */
function startTimer(seconds) {
  clearInterval(timerInterval);
  timerSeconds = Math.round(seconds ?? 30);
  tickTimer();
  timerInterval = setInterval(() => {
    timerSeconds = Math.max(0, timerSeconds - 1);
    tickTimer();
    if (timerSeconds === 0) { clearInterval(timerInterval); autoAct(); }
  }, 1000);
}
function stopTimer() {
  clearInterval(timerInterval); timerInterval = null;
  const p = $('#timer-pill');
  if (p) { p.classList.add('hidden'); p.classList.remove('urgent'); }
}
function tickTimer() {
  if (!state || state.phase !== 'playing') { stopTimer(); return; }
  const myTurn = state.attacker === state.you || state.defender === state.you;
  const p = $('#timer-pill');
  if (!p) return;
  if (!myTurn) { p.classList.add('hidden'); return; }
  p.classList.remove('hidden');
  p.textContent = timerSeconds;
  p.classList.toggle('urgent', timerSeconds <= 10);
  if (timerSeconds > 0 && timerSeconds <= 10) sfx.tick();
}
function autoAct() {
  if (!state || state.phase !== 'playing') return;
  if (state.can_done) { send({ type: 'done' }); return; }
  if (state.can_take) { selected = null; send({ type: 'take' }); return; }
  if (state.can_pass) { send({ type: 'pass' }); return; }
  if (state.attacker === state.you) {
    const c = state.your_hand.find(x => isPlayable(x));
    if (c) send({ type: 'attack', card: c });
  }
}

/* ═══════════════════════════════════════════════════
   READY CHECK
   ═══════════════════════════════════════════════════ */
function renderReadyCheck(msg) {
  show('ready-check');
  rcReady = msg.you_ready || false;
  rcSeconds = 10;

  const row = $('#rc-players-row');
  row.innerHTML = '';
  const players = msg.players || [];
  players.forEach(pl => {
    const wrap = document.createElement('div');
    wrap.className = 'rc-player' + (pl.is_me ? ' me' : '');

    const card = document.createElement('div');
    card.className = 'rc-player-card' + (pl.ready ? ' ready' : '');
    card.dataset.pid = pl.is_me ? 'me' : pl.name;

    const avatarWrap = document.createElement('div');
    avatarWrap.className = 'avatar-container';
    const avatarEl = document.createElement('div');
    avatarEl.className = 'avatar md';
    applyAvatar(avatarEl, pl.avatar || (pl.is_me ? (myAvatar || { color: '#888', initials: '?' }) : null));
    avatarWrap.appendChild(avatarEl);

    const badge = document.createElement('span');
    badge.className = 'rc-badge';
    badge.textContent = pl.ready ? '✓' : '';
    badge.style.color = pl.ready ? 'var(--fg)' : 'transparent';

    const name = document.createElement('span');
    name.className = 'rc-name';
    name.textContent = pl.is_me ? (pl.name || 'вы') : (pl.name || '—');

    const label = document.createElement('span');
    label.className = 'rc-ready-label';
    label.textContent = 'ГОТОВ';

    card.appendChild(avatarWrap);
    card.appendChild(badge);
    card.appendChild(name);
    card.appendChild(label);
    wrap.appendChild(card);
    row.appendChild(wrap);
  });

  renderRoomInfoChips('rc-info', msg);

  const btn = $('#rc-ready-btn');
  btn.textContent = rcReady ? 'Ожидаем...' : 'Готов!';
  btn.disabled = rcReady;

  startRcTimer();
}

function startRcTimer() {
  stopRcTimer();
  tickRcTimer();
  rcInterval = setInterval(() => {
    rcSeconds = Math.max(0, rcSeconds - 1);
    tickRcTimer();
    if (rcSeconds === 0) {
      stopRcTimer();
      if (!rcReady) send({ type: 'cancel' });
    }
  }, 1000);
}

function stopRcTimer() {
  clearInterval(rcInterval); rcInterval = null;
}

function tickRcTimer() {
  const numEl  = $('#rc-timer');
  const ringEl = $('#rc-ring');
  if (!numEl || !ringEl) return;
  const CIRC = 150.8;
  numEl.textContent = rcSeconds;
  ringEl.style.strokeDashoffset = (CIRC * (1 - rcSeconds / 10)).toFixed(2);
  const urgent = rcSeconds <= 3;
  numEl.classList.toggle('urgent', urgent);
  ringEl.classList.toggle('urgent', urgent);
  if (urgent && rcSeconds > 0) sfx.tick();
}

$('#rc-ready-btn')?.addEventListener('click', () => {
  if (rcReady) return;
  rcReady = true;
  const btn = $('#rc-ready-btn');
  btn.textContent = 'Ожидаем...';
  btn.disabled = true;
  const meCard = $('#rc-players-row .rc-player.me .rc-player-card');
  if (meCard) {
    meCard.classList.add('ready');
    const badge = meCard.querySelector('.rc-badge');
    if (badge) { badge.textContent = '✓'; badge.style.color = 'var(--fg)'; }
  }
  send({ type: 'ready' });
});

$('#ready-check')?.addEventListener('click', e => {
  if (e.target.closest('[data-act]')?.dataset.act === 'rc-cancel') {
    stopRcTimer();
    send({ type: 'leave' });
  }
});

/* ═══════════════════════════════════════════════════
   ACTION FLASH
   ═══════════════════════════════════════════════════ */
function showFlash(text, durationMs = 1100) {
  const el = $('#action-flash');
  if (!el) return;
  el.textContent = text;
  el.classList.remove('hidden', 'show');
  void el.offsetWidth;
  el.classList.add('show');
  el.classList.remove('hidden');
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => el.classList.add('hidden'), durationMs);
}
function maybeFlash(newState) {
  const la = newState.last_action;
  if (!la) return;
  if (prevAction && la.type === prevAction.type && la.by === prevAction.by) return;
  const label = ACTION_LABEL[la.type];
  if (!label) return;
  const isMe = la.by === newState.you;
  let name;
  if (isMe) {
    name = 'ВЫ';
  } else {
    const opp = (newState.opponents || []).find(o => o.id === la.by);
    name = (opp?.name || newState.opponent_name || 'СОПЕРНИК').toUpperCase();
  }
  showFlash(`${name}: ${label}`);
}

/* ═══════════════════════════════════════════════════
   EMOJI REACTIONS
   ═══════════════════════════════════════════════════ */
function showAvatarEmoji(wrapId, emoji) {
  const wrap = $(`#${wrapId}`);
  if (!wrap) return;
  const el = document.createElement('span');
  el.className = 'emoji-float-item';
  if (emoji.startsWith('/static/packs/')) {
    const img = document.createElement('img');
    img.src = emoji;
    img.className = 'emoji-img float-img';
    el.appendChild(img);
  } else {
    el.textContent = emoji;
  }
  wrap.innerHTML = '';
  wrap.appendChild(el);
  setTimeout(() => { if (wrap.contains(el)) wrap.removeChild(el); }, 1900);
}

$('#recall-btn')?.addEventListener('click', () => {
  if (!state?.can_recall) return;
  if (myCoins < 1000) { showToast('Недостаточно монет: нужно 1000 ⬡'); return; }
  send({ type: 'recall' });
});

$('#emoji-bar')?.addEventListener('click', e => {
  const btn = e.target.closest('.emoji-btn');
  if (!btn || emojiCooldown) return;
  const emoji = btn.dataset.emoji;
  send({ type: 'emoji', emoji });
  showAvatarEmoji('my-emoji-wrap', emoji);
  btn.classList.remove('sent');
  void btn.offsetWidth;
  btn.classList.add('sent');
  emojiCooldown = true;
  setTimeout(() => { emojiCooldown = false; }, 1200);
});

/* ═══════════════════════════════════════════════════
   SCREENS
   ═══════════════════════════════════════════════════ */
const ALL_SCREENS = ['lobby', 'waiting', 'ready-check', 'game', 'shop', 'friends', 'friend-profile', 'achievements', 'admin-panel', 'pack-creator'];

function show(id) {
  ALL_SCREENS.forEach(s => {
    const el = $(`#${s}`);
    if (el) el.classList.toggle('hidden', s !== id);
  });
  if (id !== 'game') stopTimer();
  if (id !== 'ready-check') stopRcTimer();
}

let toastTimer = null;
function toast(text) {
  const el = $('#toast');
  el.textContent = text;
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 2400);
}

function showConfirm(message, onYes) {
  const overlay = document.createElement('div');
  overlay.className = 'confirm-overlay';
  overlay.innerHTML = `
    <div class="confirm-box">
      <div class="confirm-msg">${message}</div>
      <div class="confirm-btns">
        <button class="confirm-no">Отмена</button>
        <button class="confirm-yes">Удалить</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('.confirm-yes').addEventListener('click', () => { overlay.remove(); onYes(); });
  overlay.querySelector('.confirm-no').addEventListener('click', () => overlay.remove());
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}

function showDailyBonus(coins) {
  const el = document.createElement('div');
  el.className = 'daily-bonus-popup';
  el.innerHTML = `<span class="db-icon">🎁</span><div class="db-text"><b>Ежедневный бонус</b><br>+50 ⬡ начислено</div>`;
  document.body.appendChild(el);
  setTimeout(() => el.classList.add('db-show'), 30);
  setTimeout(() => { el.classList.remove('db-show'); setTimeout(() => el.remove(), 400); }, 3200);
}

/* ═══════════════════════════════════════════════════
   LOBBY TABS
   ═══════════════════════════════════════════════════ */
let currentLbMode = 'players-games';
let currentRoomType = 'open';

function switchRoomType(type) {
  currentRoomType = type;
  $$('.rooms-sub-btn').forEach(b => b.classList.toggle('active', b.dataset.roomtype === type));
  $('#rooms-open-panel')?.classList.toggle('hidden', type !== 'open');
  $('#rooms-private-panel')?.classList.toggle('hidden', type !== 'private');
  send({ type: type === 'open' ? 'room_list' : 'room_list' });
  loadRoomList();
}

function switchLobbyTab(tab) {
  $$('.tab-panel').forEach(p => p.classList.add('hidden'));
  $(`#tab-${tab}`)?.classList.remove('hidden');
  $$('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  if (tab === 'rooms') {
    loadRoomList();
  } else {
    send({ type: 'room_list_unwatch' });
  }
  if (tab === 'leaderboard') {
    loadLeaderboardMode(currentLbMode);
  }
  if (tab === 'clan') {
    send({ type: 'clan_get' });
  }
}

function loadLeaderboardMode(mode) {
  currentLbMode = mode;
  $$('.lb-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.lbmode === mode));
  $('#leaderboard-list').innerHTML = '<div class="lb-loading">Загрузка…</div>';
  if (mode === 'clans-games') {
    send({ type: 'clan_leaderboard_get', sort: 'games' });
  } else if (mode === 'clans-coins') {
    send({ type: 'clan_leaderboard_get', sort: 'coins' });
  } else {
    send({ type: 'leaderboard_get', sort: mode === 'players-coins' ? 'coins' : 'games' });
  }
}

$('#lobby-nav')?.addEventListener('click', e => {
  const btn = e.target.closest('.nav-btn');
  if (!btn) return;
  switchLobbyTab(btn.dataset.tab);
});

document.querySelector('.lb-mode-tabs')?.addEventListener('click', e => {
  const btn = e.target.closest('.lb-mode-btn');
  if (!btn) return;
  loadLeaderboardMode(btn.dataset.lbmode);
});

document.querySelector('.rooms-sub-toggle')?.addEventListener('click', e => {
  const btn = e.target.closest('.rooms-sub-btn');
  if (!btn) return;
  switchRoomType(btn.dataset.roomtype);
});

document.querySelector('[data-act="refresh-rooms"]')?.addEventListener('click', () => loadRoomList());

/* ═══════════════════════════════════════════════════
   ROOM LIST
   ═══════════════════════════════════════════════════ */
function loadRoomList() {
  send({ type: 'room_list' });
}

const ROOM_SUITS = ['♠', '♣', '♥', '♦'];
function renderRoomList(type, rooms) {
  const listEl = $(`#${type}-rooms-list`);
  if (!listEl) return;
  if (!rooms.length) { listEl.innerHTML = '<div class="rooms-empty">Нет игр</div>'; return; }
  listEl.innerHTML = '';
  rooms.forEach((room, i) => {
    const item = document.createElement('div');
    item.className = 'room-item';
    const modeLabel = room.mode === 'perevodnoy' ? 'перев.' : 'подкид.';
    const suit = ROOM_SUITS[i % 4];
    item.innerHTML = `
      <div class="room-suit">${suit}</div>
      <div class="room-body">
        <div class="room-host">${room.host_name}</div>
        <div class="room-meta">${room.current_players}/${room.max_players} игр. · ${room.deck_size}к · ${modeLabel}</div>
      </div>
      <div class="room-bet">${room.bet} ⬡</div>
      <button class="btn sm primary room-join-btn">Войти</button>
    `;
    item.querySelector('.room-join-btn').addEventListener('click', () => {
      send({ type: 'join_open', code: room.code });
    });
    listEl.appendChild(item);
  });
}

/* ═══════════════════════════════════════════════════
   ACHIEVEMENTS
   ═══════════════════════════════════════════════════ */
const ACHIEVEMENT_DEFS = {
  "first_win":    { name: "Первая победа",    desc: "Выиграть первую игру",       icon: "🏆" },
  "rookie":       { name: "Новичок",          desc: "Сыграть 10 игр",             icon: "🃏" },
  "experienced":  { name: "Опытный",          desc: "Сыграть 50 игр",             icon: "⚔️" },
  "veteran":      { name: "Ветеран",          desc: "Сыграть 200 игр",            icon: "🎖️" },
  "lucky":        { name: "Везунчик",         desc: "Выиграть 3 игры подряд",     icon: "🍀" },
  "rich":         { name: "Богач",            desc: "Накопить 50 000 ⬡",          icon: "💰" },
  "loser_10":     { name: "Дурак-рекордсмен", desc: "Проиграть 10 игр",           icon: "🤡" },
  "comeback":     { name: "Возвращение",      desc: "Победить после 3 поражений", icon: "💪" },
  "streak_5":     { name: "Серия побед",      desc: "Выиграть 5 игр подряд",      icon: "🔥" },
  "streak_10":    { name: "Легенда серии",    desc: "Выиграть 10 игр подряд",     icon: "⚡" },
  "centurion":    { name: "Сотник",           desc: "Сыграть 100 игр",            icon: "💯" },
  "thousander":   { name: "Тысячник",         desc: "Сыграть 1000 игр",           icon: "🌟" },
  "sharp":        { name: "Мастер",           desc: "50% побед в 30+ играх",      icon: "🎯" },
  "collector":    { name: "Коллекционер",     desc: "Купить 3 скина",             icon: "🎨" },
  "general_rank": { name: "До генерала",      desc: "Достичь звания Генерал",     icon: "⭐" },
};

function renderAchievements(unlocked) {
  const list = $('#achievements-list');
  if (!list) return;
  list.innerHTML = '';
  const unlockedSet = new Set(unlocked);
  const total = Object.keys(ACHIEVEMENT_DEFS).length;
  const prog = $('#ach-progress');
  if (prog) prog.textContent = `${unlocked.length}/${total}`;

  const ids = Object.keys(ACHIEVEMENT_DEFS);
  ids.sort((a, b) => (unlockedSet.has(b) ? 1 : 0) - (unlockedSet.has(a) ? 1 : 0));

  const suits = ['♠','♣','♥','♦'];
  ids.forEach((id, i) => {
    const def = ACHIEVEMENT_DEFS[id];
    if (!def) return;
    const item = document.createElement('div');
    const isUnlocked = unlockedSet.has(id);
    item.className = 'ach-item' + (isUnlocked ? '' : ' locked');
    item.setAttribute('data-suit', suits[i % 4]);
    item.innerHTML = `
      <div class="ach-icon">${def.icon}</div>
      <div class="ach-name">${def.name}</div>
      <div class="ach-desc">${def.desc}</div>
    `;
    list.appendChild(item);
  });
}

/* ═══════════════════════════════════════════════════
   LEADERBOARD
   ═══════════════════════════════════════════════════ */
function lbAvatar(url, name, large) {
  const initial = (name || '?')[0].toUpperCase();
  const el = document.createElement(url ? 'img' : 'div');
  const lgCls = large ? ' lb-avatar-lg' : '';
  el.className = 'lb-avatar' + lgCls + (url ? '' : ' lb-avatar-ph');
  if (url) {
    el.src = url;
    el.addEventListener('error', () => {
      const ph = document.createElement('div');
      ph.className = 'lb-avatar' + lgCls + ' lb-avatar-ph';
      ph.textContent = initial;
      el.replaceWith(ph);
    });
  } else {
    el.textContent = initial;
  }
  return el;
}

const LB_PODIUM = ['gold', 'silver', 'bronze'];

function renderLeaderboard(rows, yourId, sort) {
  const list = $('#leaderboard-list');
  if (!list) return;
  const showCoins = sort === 'coins';
  const sub = $('#lb-updated');
  if (sub) sub.textContent = `${rows.length} игроков`;

  if (!rows.length) {
    list.innerHTML = '<div class="lb-empty">Пока никого нет. Сыграй первую партию!</div>';
    return;
  }

  list.innerHTML = '';
  let yourPos = -1;

  rows.forEach((r, i) => {
    const isYou = r.id === yourId;
    if (isYou) yourPos = i + 1;

    const isTop3 = i < 3;
    const podium = LB_PODIUM[i] || null;
    const winPct = r.games > 0 ? Math.round(r.wins / r.games * 100) : 0;

    const row = document.createElement('div');
    const classes = ['lb-row'];
    if (isTop3) classes.push('lb-row-top', `lb-row-${podium}`);
    if (isYou)  classes.push('lb-row-you');
    row.className = classes.join(' ');
    row.style.cursor = 'pointer';

    const statVal = showCoins
      ? `${(r.coins || 0).toLocaleString()} ⬡`
      : `${r.games} игр`;
    const statSub = showCoins ? '' : `${winPct}%`;

    const posBadge = isTop3
      ? `<span class="lb-pos-badge ${podium}">${i + 1}</span>`
      : `<span class="lb-pos">${i + 1}</span>`;

    const rankChip = r.rank_title
      ? `<span class="lb-rank-chip">${r.rank_title}</span>`
      : '';

    const winBar = !showCoins
      ? `<div class="lb-win-bar"><div class="lb-win-bar-fill" style="width:${winPct}%"></div></div>`
      : '';

    row.innerHTML = `
      ${posBadge}
      <div class="lb-info">
        <span class="lb-name">${r.name || ''}${isYou ? ' <span class="lb-you-tag">вы</span>' : ''}</span>
        ${rankChip}
        ${winBar}
      </div>
      <div class="lb-stat">
        <span class="lb-stat-main">${statVal}</span>
        ${statSub ? `<span class="lb-stat-sub">${statSub} побед</span>` : ''}
      </div>
    `;

    row.insertBefore(lbAvatar(r.avatar_url, r.name, isTop3), row.children[1]);

    row.addEventListener('click', () => {
      pendingProfileTarget = { name: r.name || '', avatar: r.avatar_url || null };
      send({ type: 'profile_get', target_id: r.id });
    });
    list.appendChild(row);
  });

  if (yourPos > 0 && yourPos > 10) {
    const notice = document.createElement('div');
    notice.className = 'lb-your-pos';
    notice.textContent = `Ваша позиция: #${yourPos}`;
    list.appendChild(notice);
  }
}

function renderClanLeaderboard(rows, sort) {
  const list = $('#leaderboard-list');
  if (!list) return;
  const showCoins = sort === 'coins';
  const sub = $('#lb-updated');
  if (sub) sub.textContent = `${rows.length} кланов`;

  if (!rows.length) {
    list.innerHTML = '<div class="lb-empty">Нет кланов. Создайте первый!</div>';
    return;
  }

  list.innerHTML = '';
  rows.forEach((r, i) => {
    const isTop3 = i < 3;
    const podium = LB_PODIUM[i] || null;
    const row = document.createElement('div');
    const classes = ['lb-row'];
    if (isTop3) classes.push('lb-row-top', `lb-row-${podium}`);
    row.className = classes.join(' ');

    const statVal = showCoins
      ? `${(r.total_coins || 0).toLocaleString()} ⬡`
      : `${r.total_games} игр`;

    const posBadge = isTop3
      ? `<span class="lb-pos-badge ${podium}">${i + 1}</span>`
      : `<span class="lb-pos">${i + 1}</span>`;

    row.innerHTML = `
      ${posBadge}
      <div class="lb-avatar lb-avatar-ph lb-clan-ph" style="font-size:${isTop3?'18px':'16px'}">🛡</div>
      <div class="lb-info">
        <span class="lb-name">${r.name}</span>
        <span class="lb-rank-chip">${r.username ? '@' + r.username + ' · ' : ''}${r.member_count} участн.</span>
      </div>
      <div class="lb-stat">
        <span class="lb-stat-main">${statVal}</span>
      </div>
    `;
    list.appendChild(row);
  });
}

/* ═══════════════════════════════════════════════════
   PACK CREATOR
   ═══════════════════════════════════════════════════ */
const CREATOR_SLOTS = 6;
let creatorImages = new Array(CREATOR_SLOTS).fill(null); // {dataUrl, file}
let creatorPrice  = 500;
let creatorSupply = 0;

function initCreatorSlots() {
  creatorImages = new Array(CREATOR_SLOTS).fill(null);
  const wrap = $('#creator-slots');
  if (!wrap) return;
  wrap.innerHTML = '';
  for (let i = 0; i < CREATOR_SLOTS; i++) {
    const slot = document.createElement('div');
    slot.className = 'creator-slot empty';
    slot.dataset.idx = i;
    slot.innerHTML = `<span class="slot-plus">+</span>`;
    slot.addEventListener('click', () => triggerSlotUpload(i));
    wrap.appendChild(slot);
  }
}

function triggerSlotUpload(idx) {
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.accept = 'image/png,image/jpeg,image/webp,image/gif';
  inp.onchange = async () => {
    const file = inp.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { toast('Файл слишком большой (макс 5МБ)'); return; }
    const raw = await readFileAsDataUrl(file);
    const cropped = await openCropEditor(raw);
    if (!cropped) return;
    creatorImages[idx] = { dataUrl: cropped, name: file.name };
    updateSlotUI(idx, cropped);
    updateCreatorPreview();
  };
  inp.click();
}

function readFileAsDataUrl(file) {
  return new Promise(resolve => {
    const r = new FileReader();
    r.onload = e => resolve(e.target.result);
    r.readAsDataURL(file);
  });
}

/* ═══════════════════════════════════════════════════
   CROP EDITOR
   ═══════════════════════════════════════════════════ */
let _cropResolve = null;
const _crop = {
  img: null, x: 0, y: 0, scale: 1,
  dragging: false, lastX: 0, lastY: 0,
  pinching: false, lastDist: 0,
};

function _cropRender() {
  const canvas = $('#crop-canvas');
  if (!canvas || !_crop.img) return;
  const wrap = $('#crop-wrap');
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  canvas.width  = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, w, h);
  const dw = _crop.img.naturalWidth  * _crop.scale;
  const dh = _crop.img.naturalHeight * _crop.scale;
  ctx.drawImage(_crop.img, _crop.x, _crop.y, dw, dh);
  _cropUpdatePreview();
}

function _cropUpdatePreview() {
  const canvas = $('#crop-canvas');
  const prev   = $('#crop-preview-img');
  if (!canvas || !prev) return;
  const wrap = $('#crop-wrap');
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  const pad = w * 0.15;
  const bx = pad, by = pad, bw = w - pad * 2, bh = h - pad * 2;
  const off = document.createElement('canvas');
  off.width = bw; off.height = bh;
  off.getContext('2d').drawImage(canvas, bx, by, bw, bh, 0, 0, bw, bh);
  prev.src = off.toDataURL('image/webp', 0.9);
}

function _cropExport() {
  const canvas = $('#crop-canvas');
  const wrap   = $('#crop-wrap');
  if (!canvas || !wrap) return null;
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  const pad = w * 0.15;
  const bx = pad, by = pad, bw = w - pad * 2, bh = h - pad * 2;
  const EXPORT = 200;
  const off = document.createElement('canvas');
  off.width = EXPORT; off.height = EXPORT;
  off.getContext('2d').drawImage(canvas, bx, by, bw, bh, 0, 0, EXPORT, EXPORT);
  return off.toDataURL('image/webp', 0.92);
}

function openCropEditor(srcDataUrl) {
  return new Promise(resolve => {
    _cropResolve = resolve;
    const modal = $('#crop-modal');
    modal.classList.remove('hidden');

    const img = new Image();
    img.onload = () => {
      _crop.img = img;
      const wrap = $('#crop-wrap');
      const w = wrap.clientWidth || 280;
      const h = wrap.clientHeight || 280;
      const pad = w * 0.15;
      const bw = w - pad * 2;
      const scale = Math.max(bw / img.naturalWidth, bw / img.naturalHeight);
      _crop.scale = scale;
      _crop.x = (w - img.naturalWidth  * scale) / 2;
      _crop.y = (h - img.naturalHeight * scale) / 2;
      _cropRender();
    };
    img.onerror = () => {
      closeCropEditor();
      if (_cropResolve) { _cropResolve(null); _cropResolve = null; }
      toast('Формат файла не поддерживается. Используй PNG, JPG или WebP.');
    };
    img.src = srcDataUrl;
  });
}

function closeCropEditor() {
  $('#crop-modal').classList.add('hidden');
  _crop.img = null;
}

$('#crop-confirm-btn')?.addEventListener('click', () => {
  const dataUrl = _cropExport();
  closeCropEditor();
  if (_cropResolve) { _cropResolve(dataUrl); _cropResolve = null; }
});

$('#crop-cancel-btn')?.addEventListener('click', () => {
  closeCropEditor();
  if (_cropResolve) { _cropResolve(null); _cropResolve = null; }
});

/* Mouse drag */
$('#crop-wrap')?.addEventListener('mousedown', e => {
  _crop.dragging = true; _crop.lastX = e.clientX; _crop.lastY = e.clientY;
});
window.addEventListener('mousemove', e => {
  if (!_crop.dragging) return;
  _crop.x += e.clientX - _crop.lastX;
  _crop.y += e.clientY - _crop.lastY;
  _crop.lastX = e.clientX; _crop.lastY = e.clientY;
  _cropRender();
});
window.addEventListener('mouseup', () => { _crop.dragging = false; });

/* Wheel zoom */
$('#crop-wrap')?.addEventListener('wheel', e => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  const wrap = $('#crop-wrap');
  const cx = wrap.clientWidth / 2, cy = wrap.clientHeight / 2;
  _crop.x = cx - (cx - _crop.x) * factor;
  _crop.y = cy - (cy - _crop.y) * factor;
  _crop.scale *= factor;
  _cropRender();
}, { passive: false });

/* Touch drag & pinch */
$('#crop-wrap')?.addEventListener('touchstart', e => {
  e.preventDefault();
  if (e.touches.length === 1) {
    _crop.dragging = true; _crop.pinching = false;
    _crop.lastX = e.touches[0].clientX; _crop.lastY = e.touches[0].clientY;
  } else if (e.touches.length === 2) {
    _crop.pinching = true; _crop.dragging = false;
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    _crop.lastDist = Math.hypot(dx, dy);
  }
}, { passive: false });

$('#crop-wrap')?.addEventListener('touchmove', e => {
  e.preventDefault();
  if (_crop.dragging && e.touches.length === 1) {
    _crop.x += e.touches[0].clientX - _crop.lastX;
    _crop.y += e.touches[0].clientY - _crop.lastY;
    _crop.lastX = e.touches[0].clientX; _crop.lastY = e.touches[0].clientY;
    _cropRender();
  } else if (_crop.pinching && e.touches.length === 2) {
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    const dist = Math.hypot(dx, dy);
    const factor = dist / _crop.lastDist;
    const wrap = $('#crop-wrap');
    const cx = wrap.clientWidth / 2, cy = wrap.clientHeight / 2;
    _crop.x = cx - (cx - _crop.x) * factor;
    _crop.y = cy - (cy - _crop.y) * factor;
    _crop.scale *= factor;
    _crop.lastDist = dist;
    _cropRender();
  }
}, { passive: false });

$('#crop-wrap')?.addEventListener('touchend', e => {
  if (e.touches.length === 0) { _crop.dragging = false; _crop.pinching = false; }
  else if (e.touches.length === 1) {
    _crop.pinching = false; _crop.dragging = true;
    _crop.lastX = e.touches[0].clientX; _crop.lastY = e.touches[0].clientY;
  }
}, { passive: false });

function updateSlotUI(idx, dataUrl) {
  const slot = $(`#creator-slots .creator-slot[data-idx="${idx}"]`);
  if (!slot) return;
  slot.classList.remove('empty');
  slot.classList.add('filled');
  slot.innerHTML = `
    <img src="${dataUrl}" class="slot-img">
    <button class="slot-remove" data-idx="${idx}">✕</button>
  `;
  slot.querySelector('.slot-remove').addEventListener('click', e => {
    e.stopPropagation();
    creatorImages[idx] = null;
    slot.classList.remove('filled');
    slot.classList.add('empty');
    slot.innerHTML = `<span class="slot-plus">+</span>`;
    updateCreatorPreview();
  });
}

function updateCreatorPreview() {
  const preview = $('#creator-preview');
  if (!preview) return;
  preview.innerHTML = '';
  creatorImages.forEach(img => {
    if (!img) return;
    const btn = document.createElement('button');
    btn.className = 'emoji-btn img-emoji';
    const im = document.createElement('img');
    im.src = img.dataUrl;
    im.className = 'emoji-img';
    btn.appendChild(im);
    preview.appendChild(btn);
  });
}

$$('#creator-price-opts .seg-btn')?.forEach(b =>
  b?.addEventListener('click', () => {
    $$('#creator-price-opts .seg-btn').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    creatorPrice = parseInt(b.dataset.val);
  })
);

$$('#creator-supply-opts .seg-btn')?.forEach(b =>
  b?.addEventListener('click', () => {
    $$('#creator-supply-opts .seg-btn').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    creatorSupply = parseInt(b.dataset.val);
  })
);

$('#creator-submit-btn')?.addEventListener('click', async () => {
  const name = ($('#creator-name')?.value || '').trim();
  if (!name) { toast('Введи название пака'); return; }
  const images = creatorImages.filter(Boolean);
  if (images.length < 3) { toast('Добавь минимум 3 картинки'); return; }

  const btn = $('#creator-submit-btn');
  btn.disabled = true;
  btn.textContent = 'Загружаю…';

  send({
    type: 'pack_submit',
    name,
    price: creatorPrice,
    supply: creatorSupply,
    images: images.map(i => i.dataUrl),
  });
});

$('#pack-creator')?.addEventListener('click', e => {
  if (e.target.closest('[data-act="creator-back"]')) {
    show('shop');
    if (shopData) renderShop(shopData);
  }
});

function openPackCreator() {
  initCreatorSlots();
  creatorPrice = 500;
  creatorSupply = 0;
  $$('#creator-price-opts .seg-btn').forEach((b, i) => b.classList.toggle('active', i === 0));
  $$('#creator-supply-opts .seg-btn').forEach((b, i) => b.classList.toggle('active', i === 0));
  if ($('#creator-name')) $('#creator-name').value = '';
  const status = $('#creator-status');
  if (status) status.classList.add('hidden');
  const btn = $('#creator-submit-btn');
  if (btn) { btn.disabled = false; btn.textContent = 'Отправить на модерацию →'; }
  updateCreatorPreview();
  show('pack-creator');
}

/* ── Marketplace ─────────────────────────────────── */
function renderMarket(packs, owned, yourId, equippedPackId) {
  const body = $('#shop-body');
  if (!body) return;
  body.innerHTML = '';

  const header = document.createElement('div');
  header.className = 'market-header';
  header.innerHTML = `
    <span class="market-title">Паки от игроков</span>
    <button class="btn sm ghost" id="market-create-btn">+ Создать пак</button>
  `;
  header.querySelector('#market-create-btn').addEventListener('click', openPackCreator);
  body.appendChild(header);

  const myPacksBtn = document.createElement('button');
  myPacksBtn.className = 'btn ghost full market-mypacks-btn';
  myPacksBtn.textContent = 'Мои паки →';
  myPacksBtn.addEventListener('click', () => { send({ type: 'my_packs' }); });
  body.appendChild(myPacksBtn);

  if (!packs.length) {
    const empty = document.createElement('div');
    empty.className = 'market-empty';
    empty.textContent = 'Паков пока нет. Создай первый!';
    body.appendChild(empty);
    return;
  }

  const list = document.createElement('div');
  list.className = 'market-list';

  packs.forEach(pack => {
    const isOwned   = owned.includes(pack.id) || pack.creator_id === yourId;
    const isCreator = pack.creator_id === yourId;
    const limited   = pack.supply > 0;
    const soldOut   = limited && pack.sold >= pack.supply;
    const remaining = limited ? pack.supply - pack.sold : null;

    const card = document.createElement('div');
    card.className = 'market-card' + (soldOut ? ' sold-out' : '');

    const imgs = document.createElement('div');
    imgs.className = 'market-pack-imgs';
    for (let i = 0; i < 6; i++) {
      const img = document.createElement('img');
      img.src = `/static/packs/${pack.id}/${i}.webp`;
      img.className = 'market-pack-img';
      img.onerror = () => img.remove();
      imgs.appendChild(img);
    }

    const info = document.createElement('div');
    info.className = 'market-card-info';

    const top = document.createElement('div');
    top.className = 'market-card-top';
    top.innerHTML = `
      <span class="market-pack-name">${pack.name}</span>
      ${limited ? `<span class="market-limited-badge">${soldOut ? 'Распродан' : `Осталось ${remaining}`}</span>` : ''}
    `;

    const meta = document.createElement('div');
    meta.className = 'market-card-meta';
    meta.innerHTML = `
      <span class="market-creator">от ${pack.creator_name}</span>
      <span class="market-sold">${pack.sold} продаж</span>
    `;

    const isEquipped = pack.id === equippedPackId;
    const btn = document.createElement('button');
    if (isEquipped) {
      btn.className = 'shop-item-btn equipped';
      btn.textContent = 'Надето';
    } else if (isCreator) {
      btn.className = 'shop-item-btn primary';
      btn.textContent = 'Надеть (мой)';
      btn.addEventListener('click', () => send({ type: 'pack_equip', pack_id: pack.id }));
    } else if (isOwned) {
      btn.className = 'shop-item-btn primary';
      btn.textContent = 'Надеть';
      btn.addEventListener('click', () => send({ type: 'pack_equip', pack_id: pack.id }));
    } else if (soldOut) {
      btn.className = 'shop-item-btn';
      btn.disabled = true;
      btn.textContent = 'Распродан';
    } else {
      btn.className = 'shop-item-btn primary';
      btn.textContent = `${pack.price} ⬡ Купить`;
      btn.addEventListener('click', () => send({ type: 'pack_buy', pack_id: pack.id }));
    }

    info.append(top, meta, btn);
    card.append(imgs, info);
    list.appendChild(card);
  });

  body.appendChild(list);
}

/* ── My packs screen ─────────────────────────────── */
function renderMyPacks(packs, owned, equippedPackId) {
  const body = $('#shop-body');
  if (!body) return;
  body.innerHTML = '';

  const header = document.createElement('div');
  header.className = 'market-header';
  header.innerHTML = `<span class="market-title">Мои паки</span>`;
  body.appendChild(header);

  const createBtn = document.createElement('button');
  createBtn.className = 'btn primary full';
  createBtn.textContent = '+ Создать новый пак';
  createBtn.addEventListener('click', openPackCreator);
  body.appendChild(createBtn);

  if (!packs.length) {
    const empty = document.createElement('div');
    empty.className = 'market-empty';
    empty.textContent = 'Ты ещё не создавал паков.';
    body.appendChild(empty);
    return;
  }

  const STATUS_LABEL = { pending: '⏳ На модерации', approved: '✓ Одобрен', rejected: '✗ Отклонён' };
  const list = document.createElement('div');
  list.className = 'market-list';

  packs.forEach(pack => {
    const card = document.createElement('div');
    card.className = 'market-card my-pack-card';

    const imgs = document.createElement('div');
    imgs.className = 'market-pack-imgs';
    for (let i = 0; i < 6; i++) {
      const img = document.createElement('img');
      img.src = `/static/packs/${pack.id}/${i}.webp`;
      img.className = 'market-pack-img';
      img.onerror = () => img.remove();
      imgs.appendChild(img);
    }

    const info = document.createElement('div');
    info.className = 'market-card-info';
    info.innerHTML = `
      <div class="market-card-top">
        <span class="market-pack-name">${pack.name}</span>
        <span class="mpack-status status-${pack.status}">${STATUS_LABEL[pack.status] || pack.status}</span>
      </div>
      <div class="market-card-meta">
        <span>${pack.price} ⬡ · ${pack.sold} продаж</span>
        <span class="market-earnings">Заработано: ${Math.round(pack.sold * pack.price * 0.7)} ⬡</span>
      </div>
    `;
    if (pack.status === 'approved') {
      const equipBtn = document.createElement('button');
      if (pack.id === equippedPackId) {
        equipBtn.className = 'shop-item-btn equipped';
        equipBtn.textContent = 'Надето';
      } else {
        equipBtn.className = 'shop-item-btn primary';
        equipBtn.textContent = 'Надеть';
        equipBtn.addEventListener('click', () => send({ type: 'pack_equip', pack_id: pack.id }));
      }
      info.appendChild(equipBtn);
    }

    card.append(imgs, info);
    list.appendChild(card);
  });

  body.appendChild(list);
}

/* ═══════════════════════════════════════════════════
   FRIENDS
   ═══════════════════════════════════════════════════ */
let friendsData = [];

function formatOnline(ts) {
  if (!ts) return 'не заходил(а)';
  const d = new Date(ts + (ts.endsWith('Z') ? '' : 'Z'));
  const now = Date.now();
  const diff = Math.floor((now - d.getTime()) / 1000);
  if (diff < 60) return 'только что';
  if (diff < 3600) return `${Math.floor(diff/60)} мин. назад`;
  if (diff < 86400) return `${Math.floor(diff/3600)} ч. назад`;
  return `${Math.floor(diff/86400)} д. назад`;
}

function renderFriends(friends, incoming = []) {
  friendsData = friends;

  // Incoming requests block
  const incomingEl = $('#friends-incoming');
  if (incomingEl) {
    if (incoming.length) {
      incomingEl.classList.remove('hidden');
      incomingEl.innerHTML = `<div class="incoming-title">Заявки в друзья (${incoming.length})</div>`;
      for (const r of incoming) {
        const item = document.createElement('div');
        item.className = 'incoming-item';
        const av = document.createElement('div');
        av.className = 'avatar sm';
        if (r.avatar_url) { av.style.backgroundImage = `url(${r.avatar_url})`; av.style.backgroundSize = 'cover'; }
        else { av.textContent = (r.name || '?')[0].toUpperCase(); av.style.background = '#888'; }
        const nameEl = document.createElement('span');
        nameEl.className = 'incoming-name';
        nameEl.textContent = r.name || r.username || r.from_id;
        const actions = document.createElement('div');
        actions.className = 'incoming-actions';
        const acceptBtn = document.createElement('button');
        acceptBtn.className = 'btn sm primary';
        acceptBtn.textContent = '✓ Принять';
        acceptBtn.dataset.acceptFriendId = r.from_id;
        const declineBtn = document.createElement('button');
        declineBtn.className = 'btn sm ghost';
        declineBtn.textContent = '✕';
        declineBtn.dataset.declineFriendId = r.from_id;
        actions.appendChild(acceptBtn);
        actions.appendChild(declineBtn);
        item.appendChild(av);
        item.appendChild(nameEl);
        item.appendChild(actions);
        incomingEl.appendChild(item);
      }
    } else {
      incomingEl.classList.add('hidden');
      incomingEl.innerHTML = '';
    }
  }

  const list = $('#friends-list');
  if (!list) return;
  const accepted = friends.filter(f => f.status === 'accepted');
  if (!accepted.length) { list.innerHTML = '<div class="rooms-empty">Нет друзей</div>'; return; }
  list.innerHTML = '';
  for (const f of accepted) {
    const item = document.createElement('div');
    item.className = 'friend-item';
    item.dataset.friendId = f.friend_id;

    const isOnline = f.last_online && (Date.now()/1000 - f.last_online < 300);

    const avWrap = document.createElement('div');
    avWrap.className = 'friend-avatar';
    const av = document.createElement('div');
    av.className = 'avatar sm';
    applyAvatar(av, f.avatar);
    const dot = document.createElement('div');
    dot.className = 'friend-online-dot' + (isOnline ? '' : ' offline');
    avWrap.appendChild(av);
    avWrap.appendChild(dot);

    const info = document.createElement('div');
    info.className = 'friend-info';
    info.innerHTML = `<div class="friend-name">${f.name || f.friend_id}</div><span class="friend-status">${formatOnline(f.last_online)}</span>`;

    const removeBtn = document.createElement('button');
    removeBtn.className = 'btn sm ghost friend-remove-btn';
    removeBtn.textContent = '✕';
    removeBtn.dataset.removeFriendId = f.friend_id;

    item.appendChild(avWrap);
    item.appendChild(info);
    item.appendChild(removeBtn);
    list.appendChild(item);
  }
}

function openFriendProfile(f) {
  show('friend-profile');
  $('#fp-title').textContent = f.name || '—';
  $('#fp-name').textContent  = f.name || '—';
  $('#fp-remove-btn').dataset.removeFriendId = f.friend_id;

  const av = $('#fp-avatar');
  if (f.avatar_url) {
    av.style.backgroundImage = `url(${f.avatar_url})`;
    av.style.backgroundSize = 'cover';
    av.textContent = '';
  } else {
    av.style.backgroundImage = '';
    av.style.background = '#888';
    av.textContent = (f.name || '?')[0].toUpperCase();
  }

  // Online
  $('#fp-online').textContent = f.last_online ? `Был(а) в сети: ${formatOnline(f.last_online)}` : '';

  // Link
  const botName = lastWaiting?.bot_username || 'gatgames_bot';
  const linkUsername = f.username || f.friend_id;
  const link = `https://t.me/${botName}?startapp=${encodeURIComponent(linkUsername)}`;
  $('#fp-link').textContent = link;
  $('#fp-copy-link').onclick = () => {
    navigator.clipboard?.writeText(link).then(() => toast('Ссылка скопирована'));
  };

  // Request full profile data
  pendingFriendProfileId = f.friend_id;
  send({ type: 'profile_get', target_id: f.friend_id });
}

let pendingFriendProfileId = null;

/* ── User search autocomplete ─────────────────────── */
let searchDebounce = null;
function renderUserSearchDrop(users) {
  const drop = $('#friend-search-drop');
  if (!drop) return;
  if (!users.length) { drop.classList.add('hidden'); drop.innerHTML = ''; return; }
  drop.innerHTML = '';
  drop.classList.remove('hidden');
  for (const u of users) {
    const item = document.createElement('div');
    item.className = 'friend-search-item';
    const av = document.createElement('div');
    av.className = 'avatar sm';
    av.style.flexShrink = '0';
    if (u.avatar_url) { av.style.backgroundImage = `url(${u.avatar_url})`; av.style.backgroundSize = 'cover'; }
    else { av.textContent = (u.name || '?')[0].toUpperCase(); av.style.background = '#888'; }
    const txt = document.createElement('div');
    txt.innerHTML = `<div class="friend-search-name">${u.name}</div>${u.username ? `<div class="friend-search-user">@${u.username}</div>` : ''}`;
    item.appendChild(av);
    item.appendChild(txt);
    item.addEventListener('click', () => {
      const inp = $('#friend-username');
      if (inp) inp.value = u.username || u.name;
      drop.classList.add('hidden');
      drop.innerHTML = '';
    });
    drop.appendChild(item);
  }
}

// Input handler for friend search
$('#friend-username')?.addEventListener('input', e => {
  const q = e.target.value.trim().replace(/^@/, '');
  clearTimeout(searchDebounce);
  if (q.length < 1) {
    const drop = $('#friend-search-drop');
    if (drop) { drop.classList.add('hidden'); drop.innerHTML = ''; }
    return;
  }
  searchDebounce = setTimeout(() => send({ type: 'user_search', query: q }), 250);
});

$('#friend-username')?.addEventListener('blur', () => {
  setTimeout(() => {
    const drop = $('#friend-search-drop');
    if (drop) { drop.classList.add('hidden'); }
  }, 200);
});

/* ═══════════════════════════════════════════════════
   ADMIN PANEL
   ═══════════════════════════════════════════════════ */
function renderAdminPacks(packs) {
  let wrap = $('#admin-packs-list');
  if (!wrap) return;
  wrap.innerHTML = '';
  if (!packs.length) {
    wrap.textContent = 'Нет паков на модерации.';
    return;
  }
  packs.forEach(pack => {
    const row = document.createElement('div');
    row.className = 'admin-pack-row';
    const imgs = document.createElement('div');
    imgs.className = 'market-pack-imgs';
    for (let i = 0; i < 6; i++) {
      const img = document.createElement('img');
      img.src = `/static/packs/${pack.id}/${i}.webp`;
      img.className = 'market-pack-img';
      img.onerror = () => img.remove();
      imgs.appendChild(img);
    }
    const info = document.createElement('div');
    info.innerHTML = `<b>${pack.name}</b> · от ${pack.creator_name} · ${pack.price}⬡`;
    const btnOk  = document.createElement('button');
    btnOk.className = 'btn sm primary'; btnOk.textContent = '✓ Одобрить';
    btnOk.addEventListener('click', () => send({ type: 'pack_approve', pack_id: pack.id }));
    const btnNo  = document.createElement('button');
    btnNo.className = 'btn sm ghost'; btnNo.textContent = '✗ Откл.';
    btnNo.addEventListener('click', () => send({ type: 'pack_reject', pack_id: pack.id }));
    row.append(imgs, info, btnOk, btnNo);
    wrap.appendChild(row);
  });
}

function renderAdminPanel(msg) {
  show('admin-panel');
  const { stats = {}, rank = {}, coins = 0 } = msg;
  // Fill inputs with current values
  const coinsInput = $('#admin-coins');
  const gamesInput = $('#admin-games');
  const winsInput  = $('#admin-wins');
  if (coinsInput) coinsInput.value = coins;
  if (gamesInput) gamesInput.value = stats.games || 0;
  if (winsInput)  winsInput.value  = stats.wins  || 0;

  // Preview
  const pogonEl = $('#admin-pogon-preview');
  if (pogonEl) { pogonEl.innerHTML = ''; pogonEl.appendChild(buildPogon(rank.pogon, true)); }
  const rankEl = $('#admin-rank-preview');
  if (rankEl) rankEl.textContent = rank.title || 'Рядовой';
  const statsEl = $('#admin-stats-preview');
  if (statsEl) statsEl.textContent = `${stats.games||0} игр · ${stats.wins||0} побед · ${coins} ⬡`;
}

/* ═══════════════════════════════════════════════════
   PROFILE POPUP
   ═══════════════════════════════════════════════════ */
function openProfilePopup(name, avatar, stats, rank, rankProgress) {
  const popup = $('#profile-popup');
  if (!popup) return;
  const avatarEl = $('#popup-avatar');
  if (avatarEl) {
    // Always reset first so previous profile's avatar doesn't bleed through
    avatarEl.style.backgroundImage = '';
    avatarEl.style.background = '#888';
    avatarEl.textContent = (name || '?')[0].toUpperCase();
    if (avatar) {
      if (typeof avatar === 'string') {
        // Leaderboard provides plain URL strings, not avatar objects
        avatarEl.style.backgroundImage = `url(${avatar})`;
        avatarEl.style.backgroundSize = 'cover';
        avatarEl.style.backgroundPosition = 'center';
        avatarEl.textContent = '';
      } else {
        applyAvatar(avatarEl, avatar);
      }
    }
  }
  $('#popup-name').textContent = name || '—';
  const pogonEl = $('#popup-pogon');
  if (pogonEl) {
    pogonEl.innerHTML = '';
    pogonEl.appendChild(buildPogon(rank?.pogon, true));
  }
  $('#popup-rank-title').textContent = rank?.title || 'Рядовой';

  // Ефрейтор easter egg в попапе
  const popupEfrBadge = $('#popup-efr-badge');
  if (popupEfrBadge) {
    const isEfr = rank?.id === 'ефрейтор';
    popupEfrBadge.classList.toggle('hidden', !isEfr);
  }

  if (stats) {
    $('#popup-games').textContent = stats.games;
    $('#popup-wins').textContent = stats.wins;
    const wr = stats.games > 0 ? Math.round(stats.wins / stats.games * 100) + '%' : '—';
    $('#popup-winrate').textContent = wr;
    $('#popup-streak').textContent = Math.abs(stats.streak || 0);
  }
  const barEl  = $('#popup-rank-bar');
  const nextEl = $('#popup-rank-next');
  if (barEl) barEl.style.width = rankProgress ? Math.round((rankProgress.progress || 0) * 100) + '%' : '0%';
  if (nextEl) nextEl.textContent = rankProgress
    ? (rankProgress.next ? `до ${rankProgress.next.title}: ${rankProgress.next.min_games - (rankProgress.games || 0)} игр` : 'максимальный ранг')
    : '';
  popup.classList.remove('hidden');
}

$('#profile-popup-close')?.addEventListener('click', () => {
  $('#profile-popup')?.classList.add('hidden');
});
$('#profile-popup')?.addEventListener('click', e => {
  if (e.target === $('#profile-popup')) $('#profile-popup').classList.add('hidden');
});
$('#popup-efr-badge')?.addEventListener('click', e => {
  e.stopPropagation();
  showEfrTooltip();
});

/* ═══════════════════════════════════════════════════
   WEBSOCKET
   ═══════════════════════════════════════════════════ */
function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  // Include uid so nginx can route this connection to a consistent worker
  const uid = tg?.initDataUnsafe?.user?.id
    || myId
    || Number(localStorage.getItem('dev_id') || 0);
  ws = new WebSocket(`${proto}//${location.host}/ws?uid=${uid}`);
  ws.onopen = () => {
    const initData   = tg?.initData || '';
    const startParam = tg?.initDataUnsafe?.start_param
      || new URLSearchParams(location.search).get('tgWebAppStartParam');
    const payload = { type: 'hello', initData, start_param: startParam };
    if (!initData) {
      const devId = Number(localStorage.getItem('dev_id') || Math.floor(Math.random() * 1e9));
      localStorage.setItem('dev_id', String(devId));
      payload.dev_id   = devId;
      payload.dev_name = localStorage.getItem('dev_name') || ('Игрок' + (devId % 1000));
    }
    ws.send(JSON.stringify(payload));
  };
  ws.onmessage = e => dispatch(JSON.parse(e.data));
  ws.onclose   = () => { toast('связь потеряна'); setTimeout(connect, 1500); };
}
function send(obj) { if (ws?.readyState === 1) ws.send(JSON.stringify(obj)); }

/* ── Dispatch ───────────────────────────────────── */
function dispatch(msg) {
  if (msg.type === 'error')   { toast(msg.message); return; }
  if (msg.type === 'toast')   { toast(msg.message); return; }
  if (msg.type === 'daily_bonus') { showDailyBonus(msg.coins); return; }
  if (msg.type === 'emoji') {
    const wrapId = msg.from ? `opp-emoji-wrap-${msg.from}` : 'opp-emoji-wrap-0';
    showAvatarEmoji(wrapId, msg.emoji);
    return;
  }

  if (msg.type === 'invite_friends_list') {
    renderInviteFriendsList(msg.friends, msg.bet);
    return;
  }

  if (msg.type === 'avatar_update') {
    myAvatar = msg.avatar;
    applyAvatar($('#lobby-avatar'), myAvatar);
    return;
  }

  if (msg.type === 'match_found') {
    // Server found a match on another worker — reconnect so the new worker picks us up
    toast('Найден соперник!');
    if (ws) { ws.onclose = null; ws.close(); }
    setTimeout(connect, 300);
    return;
  }

  if (msg.type === 'server_restart') {
    toast(msg.msg || 'Сервер перезагружается…');
    if (ws) { ws.onclose = null; ws.close(); }
    // Reconnect after a short delay; server will be back momentarily
    setTimeout(connect, 3000);
    return;
  }

  if (msg.type === 'lobby') {
    if (pendingStateTimeout) { clearTimeout(pendingStateTimeout); pendingStateTimeout = null; }
    state = null; selected = null; prevAction = null;
    resultApplied = false; resultHadPayouts = false; discardCount = 0; endSoundPlayed = false; rcReady = false;
    if (msg.id)      myId      = msg.id;
    if (msg.coins !== undefined) myCoins = msg.coins;
    if (msg.card_skin)  myCardSkin  = msg.card_skin;
    if (msg.table_skin) myTableSkin = msg.table_skin;
    if (msg.name)   myName   = msg.name;
    if (msg.avatar) myAvatar = msg.avatar;
    if (msg.emoji_imgs?.length) updateEmojiBar([], msg.emoji_imgs);
    else if (msg.emojis) updateEmojiBar(msg.emojis);
    if (msg.is_admin) {
      let btn = $('#admin-lobby-btn');
      if (!btn) {
        btn = document.createElement('button');
        btn.id = 'admin-lobby-btn';
        btn.className = 'btn sm ghost admin-lobby-btn';
        btn.dataset.act = 'show-admin';
        btn.textContent = '⚙ Admin';
        const header = $('#tab-profile .profile-header');
        if (header) header.appendChild(btn);
      }
    }
    // Don't navigate away from non-game screens on reconnect (e.g. pack-creator on OPPO drops WS when file picker opens)
    const safeScreens = ['pack-creator', 'shop', 'friends', 'friend-profile', 'achievements', 'admin-panel'];
    const onSafeScreen = safeScreens.some(s => !$(`#${s}`)?.classList.contains('hidden'));
    if (!onSafeScreen) show('lobby');
    refreshCoins();
    updateLobbyProfile();
    send({ type: 'profile_get' });
    if (pendingQuickAction) {
      const act = pendingQuickAction; pendingQuickAction = null;
      setTimeout(() => send({ type: act }), 60);
    }
    return;
  }

  if (msg.type === 'profile_data') {
    // Use server-provided target_id to reliably distinguish own profile from others'
    const isMe = myId ? (msg.target_id === myId) : (pendingProfileTarget === null);

    if (isMe) {
      // Only update MY profile data
      myStats = msg.stats || myStats;
      myRank  = msg.rank  || myRank;

      $('#stat-games').textContent = myStats.games;
      $('#stat-wins').textContent  = myStats.wins;
      $('#stat-winrate').textContent = myStats.games > 0
        ? Math.round(myStats.wins / myStats.games * 100) + '%' : '0%';
      $('#stat-streak').textContent = Math.abs(myStats.streak || 0);

      const pogonWrap = $('#lobby-pogon');
      if (pogonWrap) { pogonWrap.innerHTML = ''; pogonWrap.appendChild(buildPogon(myRank.pogon)); }
      const rankTitle = $('#lobby-rank-title');
      if (rankTitle) rankTitle.textContent = myRank.title;

      // Ефрейтор easter egg (only in my profile)
      const efrBadge = $('#efr-badge');
      if (efrBadge) {
        const isEfr = myRank.id === 'ефрейтор';
        efrBadge.classList.toggle('hidden', !isEfr);
        if (isEfr && msg.rank_progress) {
          efrGamesData = { games: msg.rank_progress.games, next_min: msg.rank_progress.next?.min_games ?? 15 };
        }
      }
    }

    if (pendingFriendProfileId !== null) {
      // Fill friend profile screen with rank data
      const pogonEl = $('#fp-pogon');
      if (pogonEl && msg.rank?.pogon) {
        pogonEl.innerHTML = '';
        pogonEl.appendChild(buildPogon(msg.rank.pogon, true));
      }
      if (msg.rank) $('#fp-rank').textContent = msg.rank.title || 'Рядовой';
      const fpStats = $('#fp-stats');
      if (fpStats && msg.stats) {
        const s = msg.stats;
        const wr = s.games > 0 ? Math.round(s.wins / s.games * 100) : 0;
        fpStats.innerHTML = `
          <div class="fp-stat"><span class="fp-stat-val">${s.games}</span><span class="fp-stat-lbl">игр</span></div>
          <div class="fp-stat"><span class="fp-stat-val">${s.wins}</span><span class="fp-stat-lbl">побед</span></div>
          <div class="fp-stat"><span class="fp-stat-val">${wr}%</span><span class="fp-stat-lbl">w/r</span></div>
          <div class="fp-stat"><span class="fp-stat-val">${Math.abs(s.streak||0)}</span><span class="fp-stat-lbl">серия</span></div>
        `;
      }
      const fpBar = $('#fp-rank-bar');
      if (fpBar && msg.rank_progress) {
        fpBar.style.width = (msg.rank_progress.progress * 100).toFixed(1) + '%';
        fpBar.style.height = '100%';
        fpBar.style.background = 'var(--fg)';
      }
      if (msg.rank_progress?.next) {
        $('#fp-rank-next').textContent = `→ ${msg.rank_progress.next.title} (${msg.rank_progress.next.min_games} игр)`;
      }
      pendingFriendProfileId = null;
    } else if (pendingProfileTarget !== null) {
      openProfilePopup(
        pendingProfileTarget.name,
        pendingProfileTarget.avatar,
        msg.stats,
        msg.rank,
        msg.rank_progress,
      );
      pendingProfileTarget = null;
    }
    return;
  }

  if (msg.type === 'room_list') {
    renderRoomList('open', msg.open || []);
    renderRoomList('private', msg.private || []);
    return;
  }

  if (msg.type === 'achievements_data') {
    renderAchievements(msg.unlocked || []);
    show('achievements');
    return;
  }

  if (msg.type === 'leaderboard_data') {
    renderLeaderboard(msg.rows || [], msg.your_id, msg.sort || 'games');
    return;
  }

  if (msg.type === 'clan_leaderboard_data') {
    renderClanLeaderboard(msg.rows || [], msg.sort || 'games');
    return;
  }

  if (msg.type === 'clan_data') {
    renderClanTab(msg.clan);
    return;
  }

  if (msg.type === 'pack_market_data') {
    renderMarket(msg.packs || [], msg.owned || [], msg.your_id, myEquippedCustomPackId);
    return;
  }

  if (msg.type === 'my_packs_data') {
    renderMyPacks(msg.packs || [], msg.owned || [], myEquippedCustomPackId);
    return;
  }

  if (msg.type === 'pack_submitted') {
    toast(msg.message || 'Пак отправлен на модерацию!');
    show('shop');
    if (shopData) renderShop(shopData);
    return;
  }

  if (msg.type === 'pack_bought') {
    myCoins = msg.coins;
    refreshCoins();
    toast('Пак куплен! Теперь можно надеть.');
    send({ type: 'pack_market' });
    return;
  }

  if (msg.type === 'pack_equipped') {
    myEquippedCustomPackId = msg.pack_id;
    updateEmojiBar([], msg.img_urls);
    if (shopData) shopData.emoji_pack = '';
    toast('Пак надет!');
    return;
  }

  if (msg.type === 'packs_pending') {
    renderAdminPacks(msg.packs || []);
    return;
  }

  if (msg.type === 'friend_list') {
    renderFriends(msg.friends || [], msg.incoming || []);
    show('friends');
    return;
  }

  if (msg.type === 'user_search_result') {
    renderUserSearchDrop(msg.users || []);
    return;
  }

  if (msg.type === 'waiting')     { renderWaiting(msg); return; }
  if (msg.type === 'ready_check') { renderReadyCheck(msg); return; }
  if (msg.type === 'state')   { handleStateMsg(msg); return; }

  if (msg.type === 'admin_data') { renderAdminPanel(msg); return; }

  if (msg.type === 'open_friend_profile') {
    // Opened via deep link to a profile
    openFriendProfile({
      friend_id: msg.id,
      name: msg.name,
      username: msg.username,
      avatar_url: msg.avatar?.url || null,
      last_online: null,
      status: 'accepted',
    });
    // Also fill rank/stats immediately
    pendingFriendProfileId = msg.id;
    // Build synthetic profile_data
    dispatch({ type: 'profile_data', stats: msg.stats, rank: msg.rank, rank_progress: msg.rank_progress });
    return;
  }

  if (msg.type === 'player_disconnected') { showDisconnectOverlay(msg); return; }
  if (msg.type === 'player_reconnected')  { hideDisconnectOverlay(msg.pid); return; }
  if (msg.type === 'player_forfeited')    { showForfeitEnd(msg); return; }

  if (msg.type === 'shop') {
    shopData = msg;
    myCoins = msg.coins;
    if (msg.card_skin)  myCardSkin  = msg.card_skin;
    if (msg.table_skin) myTableSkin = msg.table_skin;
    if (msg.user_pack) {
      myEquippedCustomPackId = msg.user_pack;
    } else if (msg.emoji_pack) {
      myEquippedCustomPackId = null;
    }
    if (msg.emoji_pack && msg.catalog?.emoji_packs) {
      const pack = msg.catalog.emoji_packs.find(p => p.skin_id === msg.emoji_pack);
      if (pack?.emojis) updateEmojiBar(pack.emojis);
    }
    renderShop(msg);
    return;
  }

  if (msg.type === 'emoji_pack_updated') {
    updateEmojiBar(msg.emojis);
    return;
  }
}

function handleStateMsg(msg) {
  const newState    = msg.state;
  const la          = newState.last_action;
  const isNewAction = la && !(prevAction && la.type === prevAction.type && la.by === prevAction.by);
  const delay       = isNewAction ? (ACTION_DELAY[la.type] ?? 0) : 0;

  if (isNewAction) maybeFlash(newState);

  if (pendingStateTimeout) { clearTimeout(pendingStateTimeout); pendingStateTimeout = null; }
  if (delay > 0) {
    pendingStateTimeout = setTimeout(() => { pendingStateTimeout = null; applyState(msg); }, delay);
  } else {
    applyState(msg);
  }
}

function applyState(msg) {
  // Cancel any active drag to prevent stale card sends (race with timer/auto-act)
  if (drag) {
    if (drag.clone) drag.clone.remove();
    if (drag.el) drag.el.style.opacity = '';
    clearDropHighlights();
    drag = null;
  }

  const oldTablePairs   = state?.table ?? [];
  const oldPrevTable    = new Set(oldTablePairs.map(p => p.attack));
  const oldPrevDefended = new Set(oldTablePairs.filter(p => p.defend).map(p => p.attack));
  const oldPrevHand     = new Set(state?.your_hand ?? []);
  // All cards that were on the table (attack + defend) — to avoid animating them as deck cards
  const allOldTableCards = new Set([
    ...(state?.table?.map(p => p.attack) ?? []),
    ...(state?.table?.filter(p => p.defend)?.map(p => p.defend) ?? []),
  ]);
  const prevAttacker       = state?.attacker;
  const prevDefender       = state?.defender;
  const prevDefendingTakes = state?.defending_takes ?? false;
  prevTable    = oldPrevTable;
  prevDefended = oldPrevDefended;
  prevHand     = oldPrevHand;
  prevAction   = state?.last_action ?? null;
  state      = msg.state;

  freshCardsList = state.your_hand.filter(c => !oldPrevHand.has(c));
  // Only animate cards that actually came from the deck (not taken from table)
  const freshDeckCards = freshCardsList.filter(c => !allOldTableCards.has(c));

  if (state.attacker === state.opponent) {
    state.table.filter(p => !oldPrevTable.has(p.attack))
      .forEach((_, i) => setTimeout(() => sfx.cardPlay(), i * 90));
  }
  if (state.defender === state.opponent) {
    state.table.filter(p => p.defend && !oldPrevDefended.has(p.attack))
      .forEach((_, i) => setTimeout(() => sfx.cardDefend(), i * 90));
  }
  freshDeckCards.forEach((_, i) => setTimeout(() => sfx.deal(), i * 85));
  selected   = null;

  if (state.you_coins !== undefined) myCoins = state.you_coins;
  if (state.you_card_skin)  myCardSkin  = state.you_card_skin;
  if (state.you_table_skin) myTableSkin = state.you_table_skin;
  if (state.you_avatar) myAvatar = state.you_avatar;
  if (state.you_name)   myName   = state.you_name;
  if (state.you_rank)   myRank   = state.you_rank;
  if (state.you_emoji_imgs?.length) updateEmojiBar([], state.you_emoji_imgs);
  else if (state.you_emojis?.length) updateEmojiBar(state.you_emojis);

  if (state.phase === 'playing') {
    const isFirstState = prevAttacker === undefined;
    const turnChanged  = prevAttacker !== state.attacker || prevDefender !== state.defender;
    const tableChanged = state.table.some(p => !oldPrevTable.has(p.attack)) ||
                         state.table.some(p => p.defend && !oldPrevDefended.has(p.attack));
    if (isFirstState)        startTimer(state.timer_remaining ?? 30);
    else if (turnChanged || tableChanged) startTimer(30);
  } else {
    stopTimer();
  }

  const isRecall     = state.last_action?.type === 'recall';
  const tableCleared = oldPrevTable.size > 0 && state.table.length === 0;
  const tableShrunk  = isRecall && oldPrevTable.size > state.table.length;

  if (isRecall && (tableCleared || tableShrunk)) {
    // Animate recalled cards flying back to hand
    const newAttacks = new Set(state.table.map(p => p.attack));
    const recalledEls = [];
    oldTablePairs.forEach(pair => {
      if (!newAttacks.has(pair.attack)) {
        const pairEl = $(`[data-attack="${pair.attack}"]`);
        if (pairEl) pairEl.querySelectorAll('.atk-card, .def-card').forEach(el => recalledEls.push(el));
      }
    });
    if (recalledEls.length) {
      const destEl = $('#hand');
      const destRect = (destEl || document.body).getBoundingClientRect();
      _flyCards(recalledEls, destRect, {
        dur: 240, stagger: 30,
        endTransform: i => `scale(0.65) rotate(${(i % 3 - 1) * 7}deg)`,
      });
    }
  } else if (tableCleared) {
    if (!prevDefendingTakes) animateDone();
    else if (!takeAnimTriggered) animateTake(prevDefender);
  }
  takeAnimTriggered = false;

  renderGame();
  if (freshDeckCards.length > 0) animateDeal(freshDeckCards);
}

/* ── Waiting ────────────────────────────────────── */
function renderWaiting(msg) {
  lastWaiting = msg;
  if (msg.you) {
    if (msg.you.coins !== undefined) myCoins = msg.you.coins;
    if (msg.you.avatar) myAvatar = msg.you.avatar;
    if (msg.you.name)   myName   = msg.you.name;
  }
  show('waiting');
  $('#code-box').classList.remove('hidden');
  $('#room-code').textContent   = msg.code;
  $('#waiting-sub').textContent = msg.private ? 'ждём друга по коду' : 'открытая — ждём игроков…';
  $('#invite-list-wrap').classList.add('hidden');
  $('#invite-list-wrap').innerHTML = '';
  renderRoomInfoChips('waiting-info', msg);
}

function renderRoomInfoChips(elId, msg) {
  const el = $(`#${elId}`);
  if (!el) return;
  const modeLabel = { perevodnoy: 'Переводной', podkidnoy: 'Подкидной' }[msg.mode] || msg.mode || '';
  const chips = [
    msg.bet != null ? `${msg.bet} ⬡` : null,
    modeLabel || null,
    msg.deck_size ? `${msg.deck_size} карт` : null,
    msg.max_players ? `${msg.current_players || 1}/${msg.max_players} игр.` : null,
  ].filter(Boolean);
  el.innerHTML = chips.map(c => `<span class="room-info-chip">${c}</span>`).join('');
}

function renderInviteFriendsList(friends, bet) {
  const wrap = $('#invite-list-wrap');
  if (!wrap) return;
  wrap.innerHTML = '';
  if (!friends.length) {
    wrap.innerHTML = '<div class="rooms-empty">Нет друзей для приглашения</div>';
    wrap.classList.remove('hidden');
    return;
  }
  for (const f of friends) {
    const row = document.createElement('div');
    row.className = 'invite-friend-row';
    const nameEl = document.createElement('span');
    nameEl.className = 'invite-friend-name';
    nameEl.textContent = f.name || `#${f.friend_id}`;
    const btn = document.createElement('button');
    btn.className = 'btn sm primary invite-friend-btn';
    btn.textContent = 'Пригласить';
    btn.addEventListener('click', () => {
      btn.disabled = true;
      btn.textContent = '✓ Отправлено';
      send({ type: 'invite_friend', friend_id: f.friend_id });
    });
    row.appendChild(nameEl);
    row.appendChild(btn);
    wrap.appendChild(row);
  }
  wrap.classList.remove('hidden');
}

/* ── Lobby profile ──────────────────────────────── */
function updateLobbyProfile() {
  const nameEl = $('#lobby-name');
  const avatarEl = $('#lobby-avatar');
  if (nameEl && myName) nameEl.textContent = myName;
  if (avatarEl && myAvatar) applyAvatar(avatarEl, myAvatar);
  refreshCoins();
}

/* ── Lobby ──────────────────────────────────────── */
$('#lobby').addEventListener('click', e => {
  // Bot count selector
  const botCnt = e.target.closest('[data-bots]');
  if (botCnt) {
    document.querySelectorAll('.bot-cnt').forEach(b => b.classList.remove('active'));
    botCnt.classList.add('active');
    return;
  }

  const act = e.target.closest('[data-act]')?.dataset.act;
  if (!act) return;

  if (act === 'quick') {
    resultApplied = false; resultHadPayouts = false;
    send({ type: 'quick' });
    show('waiting');
    $('#waiting-sub').textContent = 'ищем комнату…';
    $('#code-box').classList.add('hidden');
    $('#waiting-info').innerHTML = '';
  }
  if (act === 'vs_bot')  {
    resultApplied = false; resultHadPayouts = false;
    const numBots = parseInt(document.querySelector('.bot-cnt.active')?.dataset.bots || '1', 10);
    send({ type: 'vs_bot', num_bots: numBots });
  }
  if (act === 'shop')    { send({ type: 'shop_open' }); }
  if (act === 'show-friends') { send({ type: 'friend_list' }); }
  if (act === 'show-achievements') { send({ type: 'achievements_get' }); }
  if (act === 'show-admin') { send({ type: 'admin_get' }); }
  if (act === 'refresh-open') loadRoomList();
  if (act === 'refresh-private') loadRoomList();
  if (act === 'join-go') {
    const c = $('#join-code')?.value.trim();
    if (c) { resultApplied = false; resultHadPayouts = false; send({ type: 'join', code: c }); }
  }
});

$('#join-code')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    const c = e.target.value.trim();
    if (c) { resultApplied = false; resultHadPayouts = false; send({ type: 'join', code: c }); }
  }
});

/* ── Create game ─────────────────────────────────── */
$('#bet-options')?.addEventListener('click', e => {
  const btn = e.target.closest('.bet-opt');
  if (!btn) return;
  $$('.bet-opt').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  createSettings.bet = Number(btn.dataset.val);
});

$('#players-opts')?.addEventListener('click', e => {
  const btn = e.target.closest('.seg-btn');
  if (!btn) return;
  $$('#players-opts .seg-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  createSettings.max_players = Number(btn.dataset.val);
});

$('#deck-opts')?.addEventListener('click', e => {
  const btn = e.target.closest('.seg-btn');
  if (!btn) return;
  $$('#deck-opts .seg-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  createSettings.deck_size = Number(btn.dataset.val);
});

$('#mode-opts')?.addEventListener('click', e => {
  const btn = e.target.closest('.seg-btn');
  if (!btn) return;
  $$('#mode-opts .seg-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  createSettings.mode = btn.dataset.val;
});

$('#create-game-btn')?.addEventListener('click', () => {
  resultApplied = false; resultHadPayouts = false;
  send({
    type: 'create_game',
    bet: createSettings.bet,
    max_players: createSettings.max_players,
    deck_size: createSettings.deck_size,
    mode: createSettings.mode,
    password: '',
    private: true,
  });
});

$('#create-open-btn')?.addEventListener('click', () => {
  resultApplied = false; resultHadPayouts = false;
  send({
    type: 'create_game',
    bet: createSettings.bet,
    max_players: createSettings.max_players,
    deck_size: createSettings.deck_size,
    mode: createSettings.mode,
    password: '',
    private: false,
  });
});

/* ── Friends screen ─────────────────────────────── */
$('#friends')?.addEventListener('click', e => {
  // Accept incoming request
  const acceptId = e.target.closest('[data-accept-friend-id]')?.dataset.acceptFriendId;
  if (acceptId) {
    send({ type: 'friend_accept', from_id: parseInt(acceptId, 10) });
    return;
  }
  // Decline incoming request
  const declineId = e.target.closest('[data-decline-friend-id]')?.dataset.declineFriendId;
  if (declineId) {
    send({ type: 'friend_decline', from_id: parseInt(declineId, 10) });
    return;
  }
  // Remove button
  const removeFriendId = e.target.closest('[data-remove-friend-id]')?.dataset.removeFriendId;
  if (removeFriendId) {
    showConfirm('Удалить из друзей?', () => send({ type: 'friend_remove', friend_id: parseInt(removeFriendId, 10) }));
    return;
  }

  // Click on friend row → open profile
  const friendItem = e.target.closest('.friend-item');
  if (friendItem && !e.target.closest('[data-act]')) {
    const fid = parseInt(friendItem.dataset.friendId, 10);
    const f = friendsData.find(x => x.friend_id === fid);
    if (f && f.status === 'accepted') openFriendProfile(f);
    return;
  }

  const act = e.target.closest('[data-act]')?.dataset.act;
  if (!act) return;
  if (act === 'back') show('lobby');
  if (act === 'friend-add-show') {
    const row = $('#friend-add-row');
    if (row) row.classList.toggle('hidden');
    $('#friend-username')?.focus();
  }
  if (act === 'friend-send') {
    const username = $('#friend-username')?.value.trim();
    if (username) send({ type: 'friend_add', username });
  }
});

/* ── Friend Profile screen ──────────────────────── */
$('#friend-profile')?.addEventListener('click', e => {
  const removeFriendId = e.target.closest('[data-remove-friend-id]')?.dataset.removeFriendId;
  if (removeFriendId) {
    showConfirm('Удалить из друзей?', () => {
      send({ type: 'friend_remove', friend_id: parseInt(removeFriendId, 10) });
      show('friends');
    });
    return;
  }
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (act === 'fp-back') show('friends');
});

/* ── Achievements screen ────────────────────────── */
$('#achievements')?.addEventListener('click', e => {
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (act === 'back') { show('lobby'); return; }
  const item = e.target.closest('.ach-item');
  if (item) {
    const wasExpanded = item.classList.contains('expanded');
    document.querySelectorAll('.ach-item.expanded').forEach(el => el.classList.remove('expanded'));
    if (!wasExpanded) item.classList.add('expanded');
  }
});

$('#admin-panel')?.addEventListener('click', e => {
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (act === 'back') show('lobby');
  const adminSet = e.target.closest('[data-admin-set]')?.dataset.adminSet;
  if (adminSet) {
    const inputMap = { coins: '#admin-coins', games: '#admin-games', wins: '#admin-wins' };
    const val = $(inputMap[adminSet])?.value;
    if (val !== undefined && val !== '') send({ type: 'admin_set', field: adminSet, value: parseInt(val, 10) });
  }
});

$('#waiting').addEventListener('click', async e => {
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (!act) return;
  if (act === 'cancel') send({ type: 'cancel' });
  if (act === 'share') {
    const code    = $('#room-code').textContent;
    const botName = lastWaiting?.bot_username;
    const link    = botName
      ? `https://t.me/${botName}?startapp=r_${encodeURIComponent(code)}`
      : `${location.origin}?join=${code}`;
    try { await navigator.clipboard.writeText(link); toast('ссылка скопирована'); } catch { toast(link); }
  }
  if (act === 'invite-friends') {
    send({ type: 'get_friends_for_invite' });
  }
});

/* ── Avatar clicks → profile popup ─────────────── */
$('#efr-badge')?.addEventListener('click', e => {
  e.stopPropagation();
  showEfrTooltip();
});
document.addEventListener('click', () => {
  if (efrTooltipEl) { efrTooltipEl.remove(); efrTooltipEl = null; }
});

$('#me-avatar')?.addEventListener('click', () => {
  pendingProfileTarget = { name: myName, avatar: myAvatar };
  send({ type: 'profile_get' });
});

$('#lobby-avatar-wrap')?.addEventListener('click', () => {
  pendingProfileTarget = { name: myName, avatar: myAvatar };
  send({ type: 'profile_get' });
});

/* ═══════════════════════════════════════════════════
   RENDER GAME
   ═══════════════════════════════════════════════════ */
function renderGame() {
  show('game');
  refreshCoins();
  applySkins(myCardSkin, myTableSkin);

  const { phase, attacker, you } = state;
  const isAtk = attacker === you;

  applyAvatar($('#me-avatar'), state.you_avatar || myAvatar);
  renderOpponents();
  renderDeck();
  renderTable();
  const isDef = state.defender === you;
  $('#me-turn-dot').className = 'turn-dot' + (isAtk ? ' attacking' : isDef ? ' defending' : '');
  // My vote ring
  const meVoteRing = $('#me-vote-ring');
  if (meVoteRing) {
    const passed = state.passed_players || [];
    const iFinished = !state.your_hand?.length && state.deck_count === 0;
    const votingActive = state.table?.length > 0 && (
      state.defending_takes || state.table.every(p => p.defend !== null)
    );
    const isMeEligible = you !== state.defender;
    if (iFinished && isMeEligible) {
      meVoteRing.className = 'vote-ring voted';
    } else if (votingActive && isMeEligible) {
      meVoteRing.className = 'vote-ring ' + (passed.includes(you) ? 'voted' : 'pending');
    } else {
      meVoteRing.className = '';
    }
  }
  $('#me-name').textContent   = state.you_name || 'вы';
  // Show my rank mini badge
  const myRankMiniEl = $('#me-rank-mini');
  if (myRankMiniEl && myRank?.pogon) {
    myRankMiniEl.innerHTML = '';
    myRankMiniEl.appendChild(buildPogon(myRank.pogon));
  }
  renderHand();

  const hint = $('#defend-hint');
  hint.textContent = (state.defender === you && phase === 'playing' && selected)
    ? 'нажмите на карту соперника' : '';

  // Recall button
  const recallBtn = $('#recall-btn');
  if (recallBtn) {
    const canRecall = state.can_recall && (myCoins >= 1000);
    recallBtn.classList.toggle('hidden', !state.can_recall);
    recallBtn.disabled = !canRecall;
    recallBtn.classList.toggle('recall-broke', state.can_recall && myCoins < 1000);
  }

  renderActionBar();
  renderEndOverlay();
}

function renderOpponents() {
  const zone = $('#opponents-zone');
  zone.innerHTML = '';

  const opps = state.opponents || [{
    id: state.opponent,
    name: state.opponent_name || '—',
    avatar: state.opp_avatar,
    card_skin: state.opp_card_skin || 'classic',
    card_count: state.opponent_count,
    is_attacker: state.attacker === state.opponent,
    is_defender: state.defender === state.opponent,
    eliminated: false,
  }];

  opps.forEach(opp => {
    const eliminated = !!opp.eliminated;
    const row = document.createElement('div');
    row.className = 'opponent' + (eliminated ? ' eliminated' : '');

    const avatarWrap = document.createElement('div');
    avatarWrap.className = 'avatar-container';
    const avatarEl = document.createElement('div');
    avatarEl.className = 'avatar sm';
    applyAvatar(avatarEl, opp.avatar);
    avatarEl.style.cursor = 'pointer';
    avatarEl.addEventListener('click', () => {
      if (opp.id < 0) {
        const BOT_PROFILES = {
          '-1': { games: 7,  wins: 3,  rank: { id: 'ефрейтор',   title: 'Ефрейтор',   pogon: { type: 'stripes', n: 1 } } },
          '-2': { games: 15, wins: 8,  rank: { id: 'мл_сержант', title: 'Мл. сержант', pogon: { type: 'stripes', n: 2 } } },
          '-3': { games: 30, wins: 18, rank: { id: 'сержант',    title: 'Сержант',     pogon: { type: 'stars',   n: 1, size: 'sm' } } },
        };
        const bp = BOT_PROFILES[String(opp.id)] || BOT_PROFILES['-1'];
        openProfilePopup(
          opp.name,
          opp.avatar,
          { games: bp.games, wins: bp.wins, losses: bp.games - bp.wins, draws: 0, streak: 1, best_streak: 3 },
          bp.rank,
          null,
        );
        return;
      }
      pendingProfileTarget = { name: opp.name, avatar: opp.avatar };
      send({ type: 'profile_get', target_id: opp.id });
    });
    const emojiWrap = document.createElement('div');
    emojiWrap.className = 'avatar-emoji-wrap down';
    emojiWrap.id = `opp-emoji-wrap-${opp.id}`;
    // Vote ring: visible when all-defended or take-declared and player must vote
    const voteRing = document.createElement('div');
    const passed = state.passed_players || [];
    const votingActive = state.table?.length > 0 && (
      state.defending_takes ||
      state.table.every(p => p.defend !== null)
    );
    const isEligible = !opp.eliminated && opp.id !== state.defender;
    const oppFinished = opp.card_count === 0 && state.deck_count === 0;
    if (oppFinished && isEligible) {
      voteRing.className = 'vote-ring voted';
    } else if (votingActive && isEligible) {
      voteRing.className = 'vote-ring ' + (passed.includes(opp.id) ? 'voted' : 'pending');
    }
    avatarWrap.appendChild(avatarEl);
    avatarWrap.appendChild(emojiWrap);
    avatarWrap.appendChild(voteRing);

    const label = document.createElement('div');
    label.className = 'player-label';
    if (eliminated) {
      const doneSpan = document.createElement('span');
      doneSpan.className = 'elim-badge';
      doneSpan.textContent = opp.finish_pos === 1 ? '🥇' : '✓';
      label.appendChild(doneSpan);
    } else {
      const dot = document.createElement('span');
      dot.className = 'turn-dot' + (opp.is_attacker ? ' attacking' : (opp.is_defender ? ' defending' : ''));
      label.appendChild(dot);
    }
    const nameSpan = document.createElement('span');
    nameSpan.textContent = opp.name;
    label.appendChild(nameSpan);
    if (opp.pogon) {
      const mini = document.createElement('span');
      mini.className = 'opp-rank-mini';
      mini.appendChild(buildPogon(opp.pogon));
      label.appendChild(mini);
    }

    const cardsEl = document.createElement('div');
    cardsEl.className = 'opp-cards';
    if (!eliminated) {
      const n = Math.min(opp.card_count || 0, 14);
      for (let i = 0; i < n; i++) {
        const b = document.createElement('div');
        b.className = `card-back-sm opp-skin-${opp.card_skin}`;
        if (i > 0) b.style.marginLeft = '-5px';
        cardsEl.appendChild(b);
      }
    }

    const countEl = document.createElement('span');
    countEl.className = 'opp-count';
    countEl.textContent = !eliminated && (opp.card_count || 0) > 0 ? `×${opp.card_count}` : '';

    row.appendChild(avatarWrap);
    row.appendChild(label);
    row.appendChild(cardsEl);
    row.appendChild(countEl);
    zone.appendChild(row);
  });
}

function renderDeck() {
  const trumpEl     = $('#trump-display');
  const trumpSuitEl = $('#trump-suit-only');
  const pileEl      = $('#deck-pile');

  if (state.trump_card) {
    const r = rankOf(state.trump_card), s = suitOf(state.trump_card);
    trumpEl.className = 'trump-card-area' + (RED_SUITS.has(s) ? ' red' : '');
    trumpEl.innerHTML = `
      <div class="t-top"><span class="t-rank">${r}</span><span class="t-suit">${SUIT_GLYPH[s]}</span></div>
      <div class="t-suit-center">${SUIT_FILLED[s]}</div>
      <div class="t-bot"><span class="t-rank">${r}</span><span class="t-suit">${SUIT_GLYPH[s]}</span></div>`;
    trumpEl.classList.remove('hidden');
    trumpSuitEl.classList.add('hidden');
  } else if (state.trump) {
    trumpEl.classList.add('hidden');
    trumpSuitEl.className   = 'trump-suit-only' + (RED_SUITS.has(state.trump) ? ' red' : '');
    trumpSuitEl.textContent = SUIT_FILLED[state.trump];
    trumpSuitEl.classList.remove('hidden');
  } else {
    trumpEl.classList.add('hidden');
    trumpSuitEl.classList.add('hidden');
  }

  $('#pile-count').textContent = state.deck_count;
  pileEl.classList.toggle('empty', state.deck_count === 0);
  pileEl.style.display = (state.deck_count === 0 && !state.trump_card) ? 'none' : '';
}

function renderTable() {
  const t = $('#table');
  t.innerHTML = '';
  const { you, defender, attacker, phase } = state;
  const isDef = defender === you && phase === 'playing';
  const isAtk = attacker === you && phase === 'playing';
  t.classList.toggle('drop-zone', isAtk);

  for (const pair of state.table) {
    const wrap = document.createElement('div');
    wrap.className = 'pair';
    wrap.dataset.attack = pair.attack;

    const ac = buildCard(pair.attack, { mini: true });
    ac.classList.add('atk-card');
    ac.dataset.card = pair.attack;
    if (!prevTable.has(pair.attack)) ac.classList.add('table-in');
    if (!pair.defend) {
      ac.classList.add('needs-defend');
      if (isDef) {
        ac.dataset.dropTarget = '1';
        if (selected && canBeat(pair.attack, selected)) ac.classList.add('tap-target');
      }
    }
    wrap.appendChild(ac);

    if (pair.defend) {
      const dc = buildCard(pair.defend, { mini: true });
      dc.classList.add('def-card');
      if (!prevDefended.has(pair.attack)) dc.classList.add('defend-in');
      wrap.appendChild(dc);
    }
    t.appendChild(wrap);
  }

  if (isDef && state.can_transfer) {
    const slot = document.createElement('div');
    slot.className = 'pair transfer-slot';
    slot.id = 'transfer-slot';
    const inner = document.createElement('div');
    inner.className = 'transfer-slot-inner' + (selected && isTransferable(selected) ? ' tap-ready' : '');
    inner.innerHTML = '<span class="transfer-arrow">↩</span>';
    slot.appendChild(inner);
    t.appendChild(slot);
  }
}

function renderHand() {
  const h = $('#hand');
  h.innerHTML = '';
  const sorted = [...state.your_hand].sort(sortCards);
  const n = sorted.length;
  if (n === 0) return;

  const CARD_W = 56, CARD_H = 80, SIDE_PAD = 10;
  const handW = (h.clientWidth || (window.innerWidth - 16)) - SIDE_PAD * 2;
  const rawStep = n > 1 ? Math.floor((handW - CARD_W) / (n - 1)) : 0;
  const step    = Math.max(11, Math.min(CARD_W + 4, rawStep));
  const totalW  = (n - 1) * step + CARD_W;
  const startX  = SIDE_PAD + Math.max(0, Math.round((handW - totalW) / 2));
  const maxAngle = n > 1 ? Math.min(14, n * 1.8) : 0;

  sorted.forEach((c, i) => {
    const t     = n > 1 ? i / (n - 1) : 0.5;
    const angle = n > 1 ? -maxAngle + t * 2 * maxAngle : 0;
    const x     = startX + i * step;

    const el = buildCard(c, {});
    el.dataset.card = c;
    el.style.setProperty('--fan-angle', angle + 'deg');
    el.style.left   = x + 'px';
    el.style.width  = CARD_W + 'px';
    el.style.height = CARD_H + 'px';
    el.style.zIndex = i + 1;

    if (freshCardsList.includes(c)) el.dataset.fresh = '1';

    const playable = isPlayable(c);
    el.classList.add(playable ? 'playable' : 'greyed');

    if (selected === c) {
      el.style.transform  = `rotate(${angle}deg) translateY(-16px) scale(1.06)`;
      el.style.boxShadow  = '0 8px 24px rgba(0,0,0,0.22)';
      el.style.zIndex     = 20;
    }

    el.addEventListener('pointerdown', ev => {
      ev.preventDefault();
      if (!playable) return;
      beginDragOrTap(ev, c, el);
    });
    h.appendChild(el);
  });
}

function renderActionBar() {
  const bar = $('#action-bar');
  bar.innerHTML = '';
  if (state.phase !== 'playing') return;

  if (state.can_done) {
    const b = document.createElement('button');
    b.className = 'btn primary'; b.textContent = 'Бито';
    b.addEventListener('click', () => send({ type: 'done' }));
    bar.appendChild(b);
  }
  if (state.can_take) {
    const b = document.createElement('button');
    b.className = 'btn primary'; b.textContent = 'Беру';
    b.addEventListener('click', () => { setTimeout(() => { selected = null; send({ type: 'take' }); }, 0); });
    bar.appendChild(b);
  }
  if (state.can_pass && !state.can_done) {
    const b = document.createElement('button');
    b.className = state.defending_takes ? 'btn primary' : 'btn';
    b.textContent = state.defending_takes ? 'Пас (не бросаю)' : 'Пас';
    b.addEventListener('click', () => send({ type: 'pass' }));
    bar.appendChild(b);
  }

  // Speed-up: player already finished, bots still playing
  const iFinished = (state.finish_order || []).includes(state.you);
  if (iFinished && bar.children.length === 0) {
    if (!$('#speed-up-btn')) {
      const sb = document.createElement('button');
      sb.id = 'speed-up-btn';
      sb.className = 'btn primary speed-up-btn';
      sb.textContent = '⏩ Ускорить';
      sb.addEventListener('click', () => { send({ type: 'speed_up' }); sb.disabled = true; sb.textContent = '⏩ Ускорено'; });
      bar.appendChild(sb);
    }
    return;
  }

  // Surrender only when no other action available
  if (bar.children.length === 0) {
    const sb = document.createElement('button');
    sb.className = 'btn ghost surrender-btn';
    sb.textContent = 'Сдаться';
    sb.addEventListener('click', () => {
      if (confirm('Сдаться и потерять ставку?')) send({ type: 'surrender' });
    });
    bar.appendChild(sb);
  }
}

/* ── Disconnect overlay ────────────────────────────── */
let dcTimerInterval = null;
const dcOverlayPids = new Set();

function showDisconnectOverlay(msg) {
  dcOverlayPids.add(msg.pid);
  const overlay = $('#disconnect-overlay');
  const avatarEl = $('#dc-avatar');
  const nameEl   = $('#dc-name');
  const timerEl  = $('#dc-timer');
  const ringEl   = $('#dc-ring');

  // Set avatar
  const av = msg.avatar || {};
  if (av.url) {
    avatarEl.style.backgroundImage = `url(${av.url})`;
    avatarEl.textContent = '';
  } else {
    avatarEl.style.backgroundImage = '';
    avatarEl.style.background = av.color || '#555';
    avatarEl.textContent = av.initials || '?';
  }
  nameEl.textContent = msg.name || '—';

  // Timer countdown
  const total = msg.timeout || 30;
  const circumference = 150.8;
  let remaining = total;
  timerEl.textContent = remaining;
  ringEl.style.strokeDashoffset = 0;

  if (dcTimerInterval) clearInterval(dcTimerInterval);
  dcTimerInterval = setInterval(() => {
    remaining--;
    timerEl.textContent = Math.max(0, remaining);
    const pct = 1 - remaining / total;
    ringEl.style.strokeDashoffset = circumference * pct;
    if (remaining <= 0) {
      clearInterval(dcTimerInterval);
      dcTimerInterval = null;
    }
  }, 1000);

  overlay.classList.remove('hidden');
}

function hideDisconnectOverlay(pid) {
  dcOverlayPids.delete(pid);
  if (dcOverlayPids.size === 0) {
    if (dcTimerInterval) { clearInterval(dcTimerInterval); dcTimerInterval = null; }
    $('#disconnect-overlay').classList.add('hidden');
  }
}

function showForfeitEnd(msg) {
  if (dcTimerInterval) { clearInterval(dcTimerInterval); dcTimerInterval = null; }
  $('#disconnect-overlay').classList.add('hidden');
  dcOverlayPids.clear();

  if (resultApplied) return;
  resultApplied = true;
  const coins = msg.split_coins || 0;
  $('#end-overlay').classList.remove('hidden');
  $('#end-emoji').textContent = '🏳️';
  $('#end-title').textContent = 'СДАЛСЯ';
  $('#end-sub').textContent   = `${msg.name} покинул игру`;
  $('#end-coins').textContent = coins > 0 ? `+${coins} ⬡` : '';
  $('#end-coins').className   = coins > 0 ? 'end-coins win' : 'end-coins';
  if (!endSoundPlayed) { endSoundPlayed = true; sfx.win(); }
}

function renderEndOverlay() {
  if (state.phase !== 'finished') { $('#end-overlay').classList.add('hidden'); return; }
  const hasPayouts = !!(state.payouts && Object.keys(state.payouts).length > 0);
  // Skip if already rendered with same payout state; re-render once if payouts just arrived
  if (resultApplied && hasPayouts === resultHadPayouts) return;
  resultApplied    = true;
  resultHadPayouts = hasPayouts;
  $('#end-overlay').classList.remove('hidden');

  const rematchBtn = $('#rematch-btn');
  if (rematchBtn) rematchBtn.classList.toggle('hidden', !!state.vs_bot);

  const { winner, loser, you, winner_name, loser_name, finish_order } = state;
  const won = winner === you;
  const isLoser = loser === you;
  const draw = loser === null && winner === null;
  const bet = state.bet || 100;
  const winAmt = Math.round(bet * 0.9);

  if (!endSoundPlayed) {
    endSoundPlayed = true;
    if (!draw) { if (won) sfx.win(); else sfx.lose(); }
  }

  const isMulti = state.opponents && state.opponents.length > 1;
  const payouts = state.payouts || {};
  const myDelta = payouts[you] ?? (won ? winAmt : isLoser ? -bet : 0);

  // Render placement list for multiplayer
  const resultsEl = $('#end-results');
  if (resultsEl) {
    resultsEl.innerHTML = '';
    if (isMulti && (finish_order || loser !== null)) {
      const allOpps = state.opponents || [];
      const ordered = [...(finish_order || [])];
      if (loser !== null && !ordered.includes(loser)) ordered.push(loser);
      ordered.forEach((pid, i) => {
        const isYou = pid === you;
        const opp = allOpps.find(o => o.id === pid);
        const name = isYou ? (state.you_name || 'Вы') : (opp?.name || String(pid));
        const isLast = pid === loser;
        const medal = i === 0 ? '🥇' : isLast ? '🤡' : ['🥈','🥉'][i-1] || '✓';
        const delta = payouts[pid];
        const coinsStr = delta !== undefined
          ? (delta > 0 ? `+${delta}` : String(delta)) + ' ⬡'
          : '';
        const row = document.createElement('div');
        row.className = 'end-place-row' + (isYou ? ' end-place-you' : '') + (isLast ? ' end-place-last' : '');
        row.innerHTML = `<span class="end-place-medal">${medal}</span>`
          + `<span class="end-place-name">${name}</span>`
          + (coinsStr ? `<span class="end-place-coins ${delta > 0 ? 'win' : 'loss'}">${coinsStr}</span>` : '');
        resultsEl.appendChild(row);
      });
    }
  }

  if (draw) {
    $('#end-emoji').textContent = '';
    $('#end-title').textContent = 'НИЧЬЯ';
    $('#end-sub').textContent   = 'колода пуста';
    $('#end-coins').textContent = '';
    $('#end-coins').className   = 'end-coins';
  } else if (won) {
    $('#end-emoji').textContent = '🏆';
    $('#end-title').textContent = 'ПОБЕДА';
    const loserLabel = loser_name && loser_name !== (state.you_name || '') ? loser_name : 'соперник';
    $('#end-sub').textContent   = isMulti ? '' : `дурак: ${loserLabel}`;
    $('#end-coins').textContent = `+${myDelta} ⬡`;
    $('#end-coins').className   = 'end-coins win';
    launchConfetti();
  } else if (isLoser) {
    $('#end-emoji').textContent = '🤡';
    $('#end-title').textContent = 'ДУРАК';
    $('#end-sub').textContent   = isMulti ? '' : 'в этот раз — вы';
    $('#end-coins').textContent = `−${bet} ⬡`;
    $('#end-coins').className   = 'end-coins loss';
  } else {
    // Multiplayer: finished but not winner and not loser
    const place = (finish_order || []).indexOf(you) + 1;
    const medals = ['', '🥇', '🥈', '🥉'];
    $('#end-emoji').textContent = medals[place] || '✓';
    $('#end-title').textContent = 'ВЫШЕЛ';
    $('#end-sub').textContent   = place ? `${place}-е место` : '';
    $('#end-coins').textContent = myDelta > 0 ? `+${myDelta} ⬡` : myDelta < 0 ? `−${Math.abs(myDelta)} ⬡` : '';
    $('#end-coins').className   = 'end-coins' + (myDelta > 0 ? ' win' : myDelta < 0 ? ' loss' : '');
    if (myDelta > 0) launchConfetti();
  }
}

function launchConfetti() {
  const canvas = document.getElementById('confetti-canvas');
  if (!canvas) return;
  canvas.width  = canvas.offsetWidth;
  canvas.height = canvas.offsetHeight;
  const ctx = canvas.getContext('2d');
  const pieces = Array.from({ length: 80 }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * -canvas.height,
    r: Math.random() * 5 + 3,
    d: Math.random() * 3 + 1,
    color: ['#FFD700','#FF6B6B','#4ECDC4','#45B7D1','#96CEB4','#FFEAA7'][Math.floor(Math.random()*6)],
    tilt: Math.random() * 10 - 5,
    ts: Math.random() * 0.1,
  }));
  let frame = 0;
  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    pieces.forEach(p => {
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.color;
      ctx.fill();
      p.y += p.d;
      p.x += Math.sin(frame * p.ts + p.tilt) * 0.8;
      if (p.y > canvas.height) { p.y = -10; p.x = Math.random() * canvas.width; }
    });
    frame++;
    if (frame < 180) requestAnimationFrame(draw);
    else ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
  draw();
}

/* ═══════════════════════════════════════════════════
   SHOP
   ═══════════════════════════════════════════════════ */
function renderShop(data) {
  show('shop');
  myCoins = data.coins;
  refreshCoins();

  const body = $('#shop-body');
  body.innerHTML = '';

  if (shopActiveTab === 'emojis') {
    renderEmojiPackShop(data, body);
    return;
  }

  if (shopActiveTab === 'market') {
    send({ type: 'pack_market' });
    body.innerHTML = '<div class="lb-loading">Загрузка маркетплейса…</div>';
    return;
  }

  const catalog = shopActiveTab === 'cards' ? data.catalog.card_skins : data.catalog.table_skins;

  const grid = document.createElement('div');
  grid.className = 'shop-grid';

  for (const item of catalog) {
    const owned   = data.owned.includes(item.id);
    const active  = item.kind === 'card' ? item.skin_id === data.card_skin : item.skin_id === data.table_skin;
    const free    = item.price === 0;

    const el = document.createElement('div');
    el.className = 'shop-item' + (active ? ' active-skin' : owned ? ' owned' : '');

    const preview = document.createElement('div');
    preview.className = `skin-preview ${item.kind}-${item.skin_id}`;

    const nameEl = document.createElement('div');
    nameEl.className = 'shop-item-name';
    nameEl.textContent = item.name;

    const priceEl = document.createElement('div');
    priceEl.className = 'shop-item-price';
    priceEl.textContent = free ? 'бесплатно' : `${item.price} ⬡`;

    const btnRow = document.createElement('div');
    btnRow.className = 'shop-btn-row';

    if (active) {
      const btn = document.createElement('button');
      btn.className = 'shop-item-btn equipped';
      btn.textContent = 'Надето';
      btnRow.appendChild(btn);
    } else if (owned) {
      const btn = document.createElement('button');
      btn.className = 'shop-item-btn primary';
      btn.textContent = 'Надеть';
      btn.addEventListener('click', () => send({ type: 'equip', cosmetic_id: item.id }));
      btnRow.appendChild(btn);
    } else {
      const btn = document.createElement('button');
      btn.className = 'shop-item-btn primary';
      btn.textContent = free ? 'Взять' : `${item.price} ⬡`;
      if (!free && data.coins < item.price) btn.disabled = true;
      btn.addEventListener('click', () => send({ type: 'buy', cosmetic_id: item.id }));
      btnRow.appendChild(btn);
    }

    el.append(preview, nameEl, priceEl, btnRow);
    grid.appendChild(el);
  }

  body.appendChild(grid);
}

function renderEmojiPackShop(data, body) {
  const packs = data.catalog.emoji_packs || [];
  const activePack = data.user_pack ? null : (data.emoji_pack || 'classic');

  const grid = document.createElement('div');
  grid.className = 'shop-grid';

  for (const item of packs) {
    const owned  = data.owned.includes(item.id);
    const active = item.skin_id === activePack;
    const free   = item.price === 0;

    const el = document.createElement('div');
    el.className = 'shop-item' + (active ? ' active-skin' : owned ? ' owned' : '');

    const preview = document.createElement('div');
    preview.className = 'emoji-pack-preview';
    (item.emojis || []).forEach(e => {
      const s = document.createElement('span');
      s.className = 'ep-emoji';
      s.textContent = e;
      preview.appendChild(s);
    });

    const nameEl = document.createElement('div');
    nameEl.className = 'shop-item-name';
    nameEl.textContent = item.name;

    const priceEl = document.createElement('div');
    priceEl.className = 'shop-item-price';
    priceEl.textContent = free ? 'бесплатно' : `${item.price} ⬡`;

    const btnRow = document.createElement('div');
    btnRow.className = 'shop-btn-row';

    const btn = document.createElement('button');
    if (active) {
      btn.className = 'shop-item-btn equipped';
      btn.textContent = 'Надето';
    } else if (owned || free) {
      btn.className = 'shop-item-btn primary';
      btn.textContent = 'Надеть';
      btn.addEventListener('click', () => send({ type: 'equip', cosmetic_id: item.id }));
    } else {
      btn.className = 'shop-item-btn primary';
      btn.textContent = free ? 'Взять' : `${item.price} ⬡`;
      if (!free && data.coins < item.price) btn.disabled = true;
      btn.addEventListener('click', () => send({ type: 'buy', cosmetic_id: item.id }));
    }
    btnRow.appendChild(btn);

    el.append(preview, nameEl, priceEl, btnRow);
    grid.appendChild(el);
  }

  body.appendChild(grid);
}

$$('.shop-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    $$('.shop-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const t = tab.dataset.tab;
    shopActiveTab = t === 'cards' ? 'cards' : t === 'market' ? 'market' : 'emojis';
    if (shopData) renderShop(shopData);
  });
});

$('#shop').addEventListener('click', e => {
  if (e.target.closest('[data-act]')?.dataset.act === 'shop-back') {
    show('lobby');
    updateLobbyProfile();
  }
});

/* ═══════════════════════════════════════════════════
   DRAG & DROP
   ═══════════════════════════════════════════════════ */
function beginDragOrTap(e, card, el) {
  drag = { card, el, startX: e.clientX, startY: e.clientY, active: false, clone: null };
  el.setPointerCapture(e.pointerId);
}

document.addEventListener('pointermove', e => {
  if (!drag) return;
  const dx = e.clientX - drag.startX, dy = e.clientY - drag.startY;
  if (!drag.active && Math.sqrt(dx * dx + dy * dy) > DRAG_THRESH) activateDrag(e);
  if (!drag.active) return;
  drag.clone.style.left = (e.clientX - drag.offsetX) + 'px';
  drag.clone.style.top  = (e.clientY - drag.offsetY) + 'px';
  highlightDropTarget(e.clientX, e.clientY);
});

document.addEventListener('pointerup', e => {
  if (!drag) return;
  if (drag.active) {
    drag.clone.remove();
    const target = resolveDropTarget(e.clientX, e.clientY);
    if (target) commitDrop(drag.card, target);
    else if (drag.el) drag.el.style.opacity = '';
    clearDropHighlights();
  } else {
    handleTap(drag.card);
  }
  drag = null;
});

document.addEventListener('pointercancel', () => {
  if (drag?.clone) drag.clone.remove();
  if (drag?.el)   drag.el.style.opacity = '';
  clearDropHighlights();
  drag = null;
});

function activateDrag(e) {
  drag.active = true;
  const rect   = drag.el.getBoundingClientRect();
  drag.offsetX = e.clientX - rect.left;
  drag.offsetY = e.clientY - rect.top;
  const clone  = drag.el.cloneNode(true);
  clone.classList.remove('deal-in', 'selected', 'greyed');
  clone.style.cssText = `
    position:fixed; z-index:1000; pointer-events:none;
    width:${rect.width}px; height:${rect.height}px;
    left:${rect.left}px; top:${rect.top}px;
    transform: scale(1.12) rotate(2deg);
    box-shadow: 0 16px 44px rgba(0,0,0,0.3);
    transition: none;
  `;
  document.body.appendChild(clone);
  drag.clone = clone;
  drag.el.style.opacity = '0.3';
}

function handleTap(card) {
  if (!state || state.phase !== 'playing') return;
  const { you, attacker, defender } = state;
  if (attacker === you || state.can_throw) {
    sfx.cardPlay();
    send({ type: 'attack', card });
  } else if (defender === you) {
    selected = selected === card ? null : card;
    renderGame();
  }
}

function highlightDropTarget(x, y) {
  clearDropHighlights();
  const target = resolveDropTarget(x, y);
  if (!target) return;
  if (target.type === 'attack')   $('#table').classList.add('drop-hover');
  else if (target.type === 'defend')
    $$('.atk-card').find(e => e.dataset.card === target.attack)?.classList.add('drop-hover');
  else if (target.type === 'transfer')
    $('#transfer-slot')?.classList.add('drop-hover');
}
function clearDropHighlights() { $$('.drop-hover').forEach(el => el.classList.remove('drop-hover')); }

function resolveDropTarget(x, y) {
  if (!state || state.phase !== 'playing') return null;
  const { you, attacker, defender } = state;
  const els = document.elementsFromPoint(x, y);
  if (attacker === you || state.can_throw) {
    const hit = els.find(el => el.classList.contains('pair') || el.id === 'table' || el.classList.contains('middle'));
    if (hit) return { type: 'attack' };
  }
  if (defender === you) {
    const card = drag?.card || selected;
    const atkEl = els.find(el => el.classList.contains('atk-card') && el.dataset.dropTarget);
    if (atkEl && card && canBeat(atkEl.dataset.card, card))
      return { type: 'defend', attack: atkEl.dataset.card };
    if (card && isTransferable(card)) {
      const hit = els.find(el => el.id === 'transfer-slot' || el.closest?.('#transfer-slot'));
      if (hit) return { type: 'transfer' };
    }
  }
  return null;
}

function commitDrop(card, target) {
  if (drag?.el) drag.el.style.opacity = '';
  if (target.type === 'attack')      { sfx.cardPlay();   send({ type: 'attack', card }); }
  else if (target.type === 'defend') { sfx.cardDefend(); send({ type: 'defend', attack: target.attack, card }); }
  else if (target.type === 'transfer') { sfx.cardPlay(); selected = null; send({ type: 'transfer', card }); }
}

$('#table').addEventListener('click', e => {
  if (!state || state.phase !== 'playing') return;
  if (state.defender !== state.you || !selected) return;

  if (e.target.closest('#transfer-slot')) {
    if (isTransferable(selected)) {
      const card = selected; selected = null;
      sfx.cardPlay();
      send({ type: 'transfer', card });
    }
    return;
  }

  const atkEl = e.target.closest('.atk-card');
  if (!atkEl || !atkEl.dataset.dropTarget) return;
  if (canBeat(atkEl.dataset.card, selected)) {
    sfx.cardDefend();
    send({ type: 'defend', attack: atkEl.dataset.card, card: selected });
    selected = null;
  }
});

/* ═══════════════════════════════════════════════════
   ANIMATIONS
   ═══════════════════════════════════════════════════ */
function animateDeal(cards) {
  const deckEl = $('#deck-pile');
  const handEl = $('#hand');
  if (!handEl) return;
  const deckRect = deckEl ? deckEl.getBoundingClientRect() : null;

  cards.forEach((c, i) => {
    setTimeout(() => {
      const cardEl = handEl.querySelector(`[data-card="${c}"]`);
      if (!cardEl) return;
      const cardRect = cardEl.getBoundingClientRect();
      if (cardRect.width === 0) return;

      cardEl.style.opacity = '0';

      const clone = document.createElement('div');
      const from  = deckRect || { left: 0, top: 0, width: cardRect.width, height: cardRect.height };
      const cs    = getComputedStyle(cardEl);
      clone.style.cssText = `
        position:fixed; z-index:998; pointer-events:none;
        left:${from.left}px; top:${from.top}px;
        width:${from.width}px; height:${from.height}px;
        background:var(--bg); border:1.5px solid var(--fg);
        transition:none;
      `;
      clone.innerHTML = `<div style="position:absolute;inset:4px;
        background:repeating-linear-gradient(45deg,var(--pattern-clr) 0 0.7px,transparent 0.7px 3px);
        opacity:var(--pattern-op);"></div>`;
      document.body.appendChild(clone);

      requestAnimationFrame(() => requestAnimationFrame(() => {
        clone.style.transition = 'left 190ms ease-out,top 190ms ease-out,width 190ms ease-out,height 190ms ease-out,transform 190ms ease-out';
        clone.style.left      = cardRect.left + 'px';
        clone.style.top       = cardRect.top  + 'px';
        clone.style.width     = cardRect.width  + 'px';
        clone.style.height    = cardRect.height + 'px';
        clone.style.transform = cs.transform;
        setTimeout(() => {
          clone.remove();
          if (cardEl) cardEl.style.opacity = '';
        }, 210);
      }));
    }, i * 90);
  });
}

function _flyCards(cards, destRect, opts = {}) {
  cards.forEach((el, i) => {
    const rect  = el.getBoundingClientRect();
    const tx    = getComputedStyle(el).transform;
    const clone = el.cloneNode(true);
    clone.classList.remove('deal-in', 'table-in', 'defend-in', 'done-fly', 'taking',
                           'needs-defend', 'tap-target', 'drop-hover', 'atk-pulse');
    clone.style.cssText      = '';
    clone.style.position     = 'fixed';
    clone.style.zIndex       = '998';
    clone.style.pointerEvents = 'none';
    clone.style.left         = rect.left   + 'px';
    clone.style.top          = rect.top    + 'px';
    clone.style.width        = rect.width  + 'px';
    clone.style.height       = rect.height + 'px';
    clone.style.transform    = tx;
    clone.style.transformOrigin = 'center center';
    clone.style.animation    = 'none';
    clone.style.transition   = 'none';
    document.body.appendChild(clone);
    el.style.opacity = '0';

    const delay = i * (opts.stagger ?? 45);
    setTimeout(() => {
      const cx = destRect.left + (destRect.width  - rect.width)  / 2;
      const cy = destRect.top  + (destRect.height - rect.height) / 2;
      clone.style.transition = `left ${opts.dur ?? 300}ms ease, top ${opts.dur ?? 300}ms ease, transform ${opts.dur ?? 300}ms ease, opacity 180ms ${(opts.dur ?? 300) - 120}ms`;
      clone.style.left      = cx + 'px';
      clone.style.top       = cy + 'px';
      clone.style.transform = opts.endTransform?.(i) ?? `rotate(${(i % 3 - 1) * 6}deg) scale(0.8)`;
      clone.style.opacity   = '0';
      setTimeout(() => clone.remove(), (opts.dur ?? 300) + 220);
    }, delay);
  });
}

function animateTake(defenderPid) {
  sfx.take();
  const cards = Array.from($$('.atk-card, .def-card'));
  if (!cards.length) return;

  let destEl = defenderPid === state.you
    ? $('#hand')
    : ($(`#opp-emoji-wrap-${defenderPid}`) || $('#opponents-zone'));
  if (!destEl) destEl = $('#opponents-zone');

  const destRect = destEl.getBoundingClientRect();
  _flyCards(cards, destRect, {
    dur: 260, stagger: 35,
    endTransform: i => `scale(0.55) rotate(${(i % 5 - 2) * 9}deg)`,
  });
}

function animateDone() {
  sfx.done();
  const pileEl = $('#discard-pile');
  if (!pileEl) return;
  const destRect = pileEl.getBoundingClientRect();
  const cards = Array.from($$('.atk-card, .def-card'));
  discardCount += cards.length;

  _flyCards(cards, destRect, {
    dur: 300, stagger: 50,
    endTransform: i => `rotate(${(i % 3 - 1) * 6}deg) scale(0.85)`,
  });

  setTimeout(updateDiscardPile, cards.length * 50 + 350);
}

function updateDiscardPile() {
  const el      = $('#discard-pile');
  const countEl = $('#discard-count');
  if (!el || !countEl) return;
  el.classList.toggle('has-cards', discardCount > 0);
  countEl.textContent = discardCount > 0 ? String(discardCount) : '';
}

/* ═══════════════════════════════════════════════════
   GAME LOGIC
   ═══════════════════════════════════════════════════ */
function rankOf(c) { return c.slice(0, -1); }
function suitOf(c) { return c.slice(-1); }

function canBeat(attack, defend) {
  const rv = rankValues();
  const ar = rankOf(attack), as = suitOf(attack);
  const dr = rankOf(defend),  ds = suitOf(defend);
  if (as === ds) return rv[dr] > rv[ar];
  if (ds === state.trump && as !== state.trump) return true;
  return false;
}

function isTransferable(c) {
  if (!state?.can_transfer) return false;
  const ranks = new Set(state.table.map(p => rankOf(p.attack)));
  return ranks.has(rankOf(c));
}

function isPlayable(c) {
  const { phase, you, attacker, defender, table, opponent_count, defending_takes } = state;
  if (phase !== 'playing') return false;

  const isAttacker = attacker === you;
  // Attacker can always act; co-attacker (right neighbor) only when can_throw is set
  const canThrow = isAttacker || state.can_throw;

  if (canThrow) {
    if (table.length === 0) return isAttacker; // only main attacker opens
    if (table.length >= 6) return false;
    const ranks = new Set();
    for (const p of table) { ranks.add(rankOf(p.attack)); if (p.defend) ranks.add(rankOf(p.defend)); }
    if (!ranks.has(rankOf(c))) return false;
    if (!defending_takes) {
      const defCount = state.opponents?.find(o => o.id === defender)?.card_count ?? opponent_count ?? 0;
      if (table.filter(p => !p.defend).length >= defCount) return false;
    }
    return true;
  }
  if (defender === you) {
    if (defending_takes) return false;
    if (table.some(p => !p.defend && canBeat(p.attack, c))) return true;
    if (isTransferable(c)) return true;
  }
  return false;
}

function sortCards(a, b) {
  const rv = rankValues();
  const sa = suitOf(a), sb = suitOf(b);
  if (sa !== sb) {
    if (sa === state?.trump) return 1;
    if (sb === state?.trump) return -1;
    return sa.localeCompare(sb);
  }
  return rv[rankOf(a)] - rv[rankOf(b)];
}

function buildCard(c, { mini = false } = {}) {
  const r = rankOf(c), s = suitOf(c);
  const isRed = RED_SUITS.has(s), isTrump = s === state?.trump;
  const el = document.createElement('div');
  el.className = ['card', mini && 'mini', isTrump && 'trump', isRed && 'red'].filter(Boolean).join(' ');
  const top = document.createElement('div');
  top.className = 'cr';
  top.innerHTML = `<span class="rank">${r}</span><span class="suit">${SUIT_GLYPH[s]}</span>`;
  const center = document.createElement('div');
  center.className = 'suit-center'; center.textContent = SUIT_FILLED[s];
  const bot = document.createElement('div');
  bot.className = 'cr flip';
  bot.innerHTML = `<span class="rank">${r}</span><span class="suit">${SUIT_GLYPH[s]}</span>`;
  el.append(top, center, bot);
  return el;
}

/* ── End overlay button ─────────────────────────── */
$('#end-overlay').addEventListener('click', e => {
  const act = e.target.closest('[data-act]')?.dataset.act;
  if (act === 'again') { send({ type: 'leave' }); return; }
  if (act === 'rematch') {
    resultApplied = false; resultHadPayouts = false;
    endSoundPlayed = false;
    $('#end-overlay').classList.add('hidden');
    send({ type: 'rematch' });
    return;
  }
  if (act === 'restart-quick') {
    resultApplied = false; resultHadPayouts = false;
    pendingQuickAction = 'quick';
    send({ type: 'leave' });
    return;
  }
  if (act === 'restart-bot') {
    resultApplied = false; resultHadPayouts = false;
    pendingQuickAction = 'vs_bot';
    send({ type: 'leave' });
    return;
  }
});

/* ═══════════════════════════════════════════════════
   CLAN
   ═══════════════════════════════════════════════════ */
function renderClanTab(clan) {
  const noClan = $('#clan-no-clan');
  const clanInfo = $('#clan-info');
  if (!noClan || !clanInfo) return;

  // reset forms
  $('#clan-create-form')?.classList.add('hidden');
  $('#clan-join-form')?.classList.add('hidden');

  if (!clan) {
    noClan.classList.remove('hidden');
    clanInfo.classList.add('hidden');
    return;
  }

  noClan.classList.add('hidden');
  clanInfo.classList.remove('hidden');

  $('#clan-info-name').textContent = clan.name;
  $('#clan-info-username').textContent = clan.username ? '@' + clan.username : '';
  const descEl = $('#clan-info-desc');
  if (descEl) {
    descEl.textContent = clan.description || '';
    descEl.style.display = clan.description ? '' : 'none';
  }
  $('#clan-info-members').textContent = clan.member_count || 0;
  $('#clan-info-games').textContent = (clan.total_games || 0).toLocaleString();
  $('#clan-info-coins').textContent = (clan.total_coins || 0).toLocaleString();

  const avatarEl = $('#clan-info-avatar');
  if (avatarEl) avatarEl.textContent = (clan.name || '?')[0].toUpperCase();

  const roleEl = $('#clan-info-role');
  if (roleEl) {
    roleEl.textContent = clan.role === 'owner' ? '👑 Владелец' : '· Участник';
    roleEl.className = 'clan-role-badge' + (clan.role === 'owner' ? ' owner' : '');
  }

  const mlist = $('#clan-members-list');
  mlist.innerHTML = '';
  (clan.members || []).forEach(m => {
    const el = document.createElement('div');
    el.className = 'clan-member-row' + (m.role === 'owner' ? ' owner' : '') + (m.id === myId ? ' me' : '');

    const avDiv = document.createElement('div');
    avDiv.className = 'clan-member-avatar clan-member-avatar-ph';
    if (m.avatar_url) {
      const img = document.createElement('img');
      img.src = m.avatar_url;
      img.className = 'clan-member-avatar';
      img.style.cssText = 'width:36px;height:36px;border-radius:50%;object-fit:cover;flex-shrink:0';
      img.onerror = () => img.replaceWith(avDiv);
      el.appendChild(img);
    } else {
      avDiv.textContent = (m.name || '?')[0].toUpperCase();
      el.appendChild(avDiv);
    }

    const info = document.createElement('div');
    info.className = 'clan-member-info';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'clan-member-name';
    nameSpan.textContent = (m.name || '?') + (m.role === 'owner' ? ' 👑' : '');

    const statsSpan = document.createElement('span');
    statsSpan.className = 'clan-member-stats';
    const winPct = m.games > 0 ? Math.round(m.wins / m.games * 100) : 0;
    statsSpan.textContent = `${m.games} игр · ${winPct}% побед`;

    info.appendChild(nameSpan);
    info.appendChild(statsSpan);
    el.appendChild(info);
    mlist.appendChild(el);
  });
}

$('#clan-create-btn')?.addEventListener('click', () => {
  $('#clan-create-form')?.classList.remove('hidden');
  $('#clan-join-form')?.classList.add('hidden');
});
$('#clan-create-cancel')?.addEventListener('click', () => {
  $('#clan-create-form')?.classList.add('hidden');
});
$('#clan-create-submit')?.addEventListener('click', () => {
  const name = $('#clan-create-name')?.value.trim();
  const username = $('#clan-create-username')?.value.trim();
  const description = $('#clan-create-desc')?.value.trim();
  if (!name) { toast('Укажи название клана'); return; }
  if (!username) { toast('Укажи юзернейм клана'); return; }
  send({ type: 'clan_create', name, username, description });
});

$('#clan-join-btn')?.addEventListener('click', () => {
  $('#clan-join-form')?.classList.remove('hidden');
  $('#clan-create-form')?.classList.add('hidden');
});
$('#clan-join-cancel')?.addEventListener('click', () => {
  $('#clan-join-form')?.classList.add('hidden');
});
$('#clan-join-submit')?.addEventListener('click', () => {
  const username = $('#clan-join-username')?.value.trim().replace(/^@/, '');
  if (!username) return;
  send({ type: 'clan_join', username });
});

$('#clan-leave-btn')?.addEventListener('click', () => {
  if (confirm('Покинуть клан?')) send({ type: 'clan_leave' });
});

/* ── Theme toggle ───────────────────────────────── */
(function initTheme() {
  const saved = localStorage.getItem('theme');
  const btn = $('#theme-toggle');
  function applyTheme(t) {
    document.body.classList.remove('theme-dark', 'theme-light');
    if (t === 'dark')  { document.body.classList.add('theme-dark');  if (btn) btn.textContent = '🌙'; }
    if (t === 'light') { document.body.classList.add('theme-light'); if (btn) btn.textContent = '☀️'; }
    if (!t)            { if (btn) btn.textContent = window.matchMedia('(prefers-color-scheme: dark)').matches ? '🌙' : '☀️'; }
    const isDark = t === 'dark' || (!t && window.matchMedia('(prefers-color-scheme: dark)').matches);
    tg?.setHeaderColor?.(isDark ? '#111111' : '#ffffff');
    tg?.setBackgroundColor?.(isDark ? '#111111' : '#ffffff');
  }
  applyTheme(saved || null);
  btn?.addEventListener('click', () => {
    const isDark = document.body.classList.contains('theme-dark') ||
      (!document.body.classList.contains('theme-light') && window.matchMedia('(prefers-color-scheme: dark)').matches);
    const next = isDark ? 'light' : 'dark';
    localStorage.setItem('theme', next);
    applyTheme(next);
  });
})();

/* ── Surrender CSS ───────────────────────────────── */

/* ── Init ───────────────────────────────────────── */
updateEmojiBar(activeEmojis);
connect();
