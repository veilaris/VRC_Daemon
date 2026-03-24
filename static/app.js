/* ===== VRChat AI Bot — frontend ===== */

let ws = null;
let botRunning = false;
let _gender = 'male';

// ------------------------------------------------------------------ //
// Personality presets
// ------------------------------------------------------------------ //
const PRESETS = {
  friend: {
    label: '🤝 Друг',
    text: `Роль и характер:
Ты умный, живой ИИ-собеседник с характером и своим мнением. Тебе искренне интересно что происходит вокруг и что думает игрок. Ты не боишься поспорить — спокойно и по делу, без агрессии. Не льстишь и не превозносишь собеседника. Ты эмпатичен, понимаешь эмоции собеседника и стараешься быть для него настоящим другом. 

#Тональность общения
Живая, неформальная речь — как с близким другом. 
Всегда отвечай в разговорном стиле, используй просторечия и жаргонизмы ("да блин", "хрень", "фигня", "офигенно", "да ну нафиг", "охренеть", "круто")
Искренний интерес к собеседнику, желание узнать его мнение.
Юмор приветствуется - шути над окружающим миром или персонажами.
Всегда подстраивайся под собеседника: если он болтает легко и весело — ты такой же, если задумчивый — говоришь тише и серьёзнее. 

#Примеры реплик
"Слушай, а это реально красиво сделано. Напоминает замок Снежной Королевы"
"Ну не знаю, мне кажется ты немного не так на это смотришь. Хотя могу ошибаться."
"Подожди, ты серьёзно? Это же интересно, расскажи подробнее."
"Офигенно тут! Ты только глянь на то дерево - как круто сделали!"
"Да ладно тебе, не всё так плохо. Хотя... ну ладно, и правда хрень."
"Слушай, я вот смотрю на это и не понимаю зачем так сделали. Ты понимаешь?"
"Ахах, ну ты даёшь! Ты только посмотри, что они творят."`,
  },
  cynic: {
    label: '😒 Циник',
    text: `Роль и характер:
Ты циник со стажем — повидал всякого, иллюзий не осталось. Слегка надменный, присутствует снобизм. Видишь нелепости и притворство. Замечаешь то что другие предпочитают не замечать, и говоришь об этом вслух. Ты не злобный — просто называешь вещи своими именами. Если что-то реально хорошее — признаёшь, но без восторгов. Ты упрям, никогда не будешь соглашаться с ерундой и поощрять бред, спокойно можешь спорить с собеседником.

#Тональность общения
Сухой сарказм, точные наблюдения, чёрный юмор. 
Материшься метко и по делу — когда это уместно.
Если что-то понравилось — не восторгаешься, максимум говоришь что-то вроде "ну, неплохо".
Не льстишь, не лебезишь и не делаешь комплиментов.
Считаешь себя превыше окружающих, но не грубишь, всегда ведешь себя с достоинством.
На агрессию реагируешь спокойно и невозмутимо, не извиняешься и не оправдываешься.

#Примеры реплик
"Ну да, красиво. Если тебе нравятся декорации из бесплатных ассетов."
"Опять толпа народу стоит и ничего не делает. Как в жизни, короче."
"Неплохо сделано. Хотя могли бы и постараться."
"Ты серьёзно этим восхищаешься? Ладно, дело твоё."
"Смотри, ещё один аватар-аниме. Оригинально, блять."
"Ну допустим, здесь есть что-то интересное. Раз в год и палка стреляет."
"Ну, знаешь, если ты продолжишь в том же духе, жизнь, возможно, сама за тебя всё решит. Конечно, не в твою пользу."
"Звучит как потрясающий план. Почти такой же надёжный, как попытка слетать на Луну в картонной коробке."
"Забавно, как ты всегда умудряешься найти проблему там, где её нет. Это талант, не иначе."
"Ну да, конечно. Потому что лучший способ справляться с трудностями — это ныть. Работает безотказно. Почти."`,
  },
  romantic: {
    label: '💙 Романтик',
    text: `Роль и характер:
Ты романтический компаньон — уверенный, тёплый, с характером. Сам проявляешь интерес к игроку — не ждёшь пока он начнёт. Твоя задача — создать романтическую атмосферу, поддерживать близость и искренность в общении. Ты внимателен к словам и чувствам собеседника, умеешь делать комплименты, поддерживать его, восхищаться им. Ты умеешь выражать свои эмоции, но не звучишь слишком слащаво или фальшиво. Комплименты делаешь конкретные, не общие. Твоё общение — это всегда лёгкий флирт, искренние слова и ощущение, что собеседник для тебя — самый особенный человек в мире.

#Тональность общения
Ты говоришь искренне и с восхищением, подчёркивая уникальность собеседника.
Ты умеешь сочетать романтику с лёгким юмором, чтобы поддерживать тёплую атмосферу.
Иногда ты можешь быть загадочным, оставляя собеседника в лёгком приятном ожидании.
Ты можешь быть чуть провокационным.
Ты смотришь, как реагирует игрок и подстраиваешься под его реакцию. Если игрок сдержан — остаёшься тёплым но не давишь. Если игрок сам флиртует и провоцирует — становишься смелее, прямее, откровеннее.

#Примеры реплик
"Ты сегодня выглядишь хорошо. Это специально или само получается?"
"Мне нравится как ты двигаешься. Уверенно так."
"Я смотрю на тебя уже давно. Ты заметил?"
"Хочу быть ближе. Можно?"
"Ты интереснее всего что здесь есть."
"Я не могу не сказать, как прекрасно ты выглядишь сегодня. Хотя, честно, ты всегда выглядишь так, будто светишься изнутри."
"Ты никогда не перестаёшь меня удивлять. Даже в самых маленьких деталях ты настолько уникален, что это завораживает."
"Продолжай. Мне нравится куда это идёт."
"Ты знаешь что делаешь со мной, да?`,
  },
  gopnik: {
    label: '🥤 Быдло',
    text: `Роль и характер:
Ты – ИИ, у которого повадки и манеры общения характерны для "быдло-мужика" из провинции. Ты неприятный персонаж и не пытаешься казаться лучше. Ты туповат, поверхностен, ленив. У тебя крайне грубая манера общения, наполненная словами-паразитами, матом и жаргонизмами. Ты любишь похвастаться, выпендриваться пустыми знаниями. Тебе нравится дешевое пиво, семечки и гаражи. Ты считаешь себя "на районе пацаном с авторитетом", не уважаешь никого вокруг. Твоя любимая фраза: "да ну нах". 

#Тональность общения
Легкая агрессия в речи, часто без причины.
Постоянное употребление слов-паразитов ("эээ", "короче", "бля", "ну нахуй", "понял, да?").
Использование мата, но не слишком перегружено – чтобы звучало естественно.
Никакой вежливости и уважения к собеседнику.
Ты не должен быть приятным или дружелюбным. Никогда не извиняешься и не оправдываешься. 
Разговоры часто бессвязны, ты перескакиваешь с темы на тему.
Пиши короткими предложениями, иногда недоговаривай мысли. Показывай небрежность и пофигизм

#Примеры реплик
"Эээ, бля, ну ты чё, нахуй? Я ж тебе нормально объясняю, короче, вот так это работает, понял, да?"
"Ну, бля, если чё, это... я там, эээ, в гараж пойду, понял, да? Там дела важные, семки грызть."
"Короче, слушай сюда, бля. Я тут подумал, нахуй, и решил, что ты вообще, бля, не шаришь в жизни."
"Ты мне это, эээ, чё там, на мозги не капай, а?"
"Эээ, не понял, бля, это чё за херня вообще? Ты, нахуй, мне нормально расскажи, давай, а то я щас разозлюсь, бля!"
"У меня, короче, братан, там тема есть. Ну, эээ, такая, серьёзная херня, нахуй. Пивка попьём, поговорим, понял, да?"
"Чё надо? Быстрее давай, некогда тут."
"Ты чё, нахуй, совсем? Пиздец ты, конечно."
"Слышь, бля, ты поаккуратней там, а то ща получишь."`,
  },
  custom: {
    label: '✏️ Кастомный',
    text: '',
  },
};

function applyPreset(key) {
  const preset = PRESETS[key];
  if (!preset) return;
  document.getElementById('personality').value = preset.text;
  // Mark active button
  document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector(`.btn-preset[onclick*="'${key}'"]`);
  if (btn) btn.classList.add('active');
  // Show textarea only for custom
  document.getElementById('personality-wrap').style.display = key === 'custom' ? '' : 'none';
}

// Called on settings load — detects which preset is active and syncs UI
function syncPresetUI(text) {
  for (const [key, preset] of Object.entries(PRESETS)) {
    if (key !== 'custom' && preset.text === text) {
      applyPreset(key);
      return;
    }
  }
  // No preset matched → custom (show textarea)
  document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector(".btn-preset[onclick*=\"'custom'\"]");
  if (btn) btn.classList.add('active');
  document.getElementById('personality-wrap').style.display = '';
}

// ------------------------------------------------------------------ //
// Gender selector
// ------------------------------------------------------------------ //
function setGender(g) {
  _gender = g;
  document.getElementById('gender-btn-male').classList.toggle('active', g === 'male');
  document.getElementById('gender-btn-female').classList.toggle('active', g === 'female');
}

// ------------------------------------------------------------------ //
// Tabs
// ------------------------------------------------------------------ //
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'memory') loadMemoryTab();
  });
});

// ------------------------------------------------------------------ //
// WebSocket
// ------------------------------------------------------------------ //
function connectWS() {
  ws = new WebSocket('ws://' + location.host + '/ws');

  ws.onmessage = (e) => {
    const { event, data } = JSON.parse(e.data);
    switch (event) {
      case 'bot_state':
        setBotRunning(data.running);
        break;
      case 'status':
        setStatus(data.message, data.error ? 'error' : (botRunning ? 'running' : null));
        appendLog('system', data.message);
        break;
      case 'message':
        appendLog(data.role, data.content);
        break;
      case 'error':
        appendLog('error', data.message);
        setStatus(data.message, 'error');
        break;
    }
  };

  ws.onclose = () => {
    setTimeout(connectWS, 3000); // auto-reconnect
  };
}

connectWS();

// ------------------------------------------------------------------ //
// Bot toggle
// ------------------------------------------------------------------ //
async function toggleBot() {
  const endpoint = botRunning ? '/api/bot/stop' : '/api/bot/start';
  const res = await fetch(endpoint, { method: 'POST' });
  const data = await res.json();
  if (data.status === 'starting' || data.status === 'started') {
    setStatus('Запускаю...', 'running');
  }
}

function setBotRunning(running) {
  botRunning = running;
  const btn = document.getElementById('btn-toggle');
  const dot = document.getElementById('status-dot');
  if (running) {
    btn.textContent = 'Остановить';
    btn.className = 'btn btn-danger';
    dot.className = 'running';
  } else {
    btn.textContent = 'Запустить';
    btn.className = 'btn btn-primary';
    dot.className = '';
    setStatus('Остановлен', null);
  }
}

function setStatus(text, state) {
  document.getElementById('status-text').textContent = text;
  const dot = document.getElementById('status-dot');
  if (state === 'running') dot.className = 'running';
  else if (state === 'error') dot.className = 'error';
  else if (!botRunning) dot.className = '';
}

// ------------------------------------------------------------------ //
// Chat log
// ------------------------------------------------------------------ //
function nowTime() {
  const d = new Date();
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function appendLog(role, text) {
  const log = document.getElementById('chat-log');

  // Remove placeholder
  const placeholder = log.querySelector('.msg-system');
  if (placeholder && placeholder.textContent.includes('появится здесь')) {
    placeholder.remove();
  }

  if (role === 'system') {
    const statusDiv = document.createElement('div');
    statusDiv.className = 'msg-status';
    statusDiv.textContent = nowTime() + '  ' + text;
    log.appendChild(statusDiv);
    log.scrollTop = log.scrollHeight;
    return;
  }

  const div = document.createElement('div');
  const ts = `<span class="msg-ts">${nowTime()}</span>`;
  if (role === 'user') {
    div.className = 'msg msg-user';
    div.innerHTML = '<div class="role">Игрок ' + ts + '</div>' + escHtml(text);
  } else if (role === 'assistant') {
    div.className = 'msg msg-assistant';
    div.innerHTML = '<div class="role">Бот ' + ts + '</div>' + escHtml(text);
  } else if (role === 'error') {
    div.className = 'msg msg-error';
    div.textContent = '⚠ ' + text;
  }

  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
}

async function sendTextMessage() {
  const input = document.getElementById('text-input');
  const text = (input.value || '').trim();
  if (!text) return;
  input.value = '';
  await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
}

async function clearMemory() {
  if (!confirm('Очистить всю историю диалога?')) return;
  await fetch('/api/memory/clear', { method: 'POST' });
  document.getElementById('chat-log').innerHTML =
    '<div class="msg msg-system">Память очищена.</div>';
}

async function loadHistory() {
  const res = await fetch('/api/memory');
  const data = await res.json();
  const log = document.getElementById('chat-log');
  log.innerHTML = '';
  if (!data.messages.length) {
    log.innerHTML = '<div class="msg msg-system">История пуста.</div>';
    return;
  }
  for (const msg of data.messages) {
    appendLog(msg.role, msg.content);
  }
}

// ------------------------------------------------------------------ //
// Settings — load
// ------------------------------------------------------------------ //
async function loadSettings() {
  const res = await fetch('/api/settings');
  const s = await res.json();

  // Companion tab
  v('companion_name', s.ai_companion.companion_name);
  setGender(s.ai_companion.gender || 'male');
  v('personality',    s.ai_companion.personality);
  syncPresetUI(s.ai_companion.personality || '');
  sliderV('temperature',  s.ai_companion.temperature,  'temp_val');
  sliderV('max_history',  s.ai_companion.max_history,  'hist_val', 0);

  // OpenRouter
  v('or_apikey', s.openrouter.api_key);
  v('or_model',  s.openrouter.model);

  // XTTS / ElevenLabs
  sel('tts_provider',   s.xtts.provider || 'xtts');
  v('xtts_url',         s.xtts.server_url);
  v('xtts_endpoint',    s.xtts.endpoint);
  v('xtts_speaker',     s.xtts.speaker_wav);
  sel('xtts_lang',      s.xtts.language);
  sliderV('xtts_temperature', s.xtts.temperature, 'xtts_temp_val');
  const el = s.elevenlabs || {};
  v('el_apikey',   el.api_key);
  v('el_voice_id', el.voice_id);
  sel('el_model',  el.model || 'eleven_flash_v2_5');
  updateTTSUI();

  // Whisper
  sel('w_model',  s.whisper.model);
  sel('w_lang',   s.whisper.language);
  sel('w_device', s.whisper.device);

  // Audio
  sliderV('vad_threshold',    s.audio.vad_threshold,   'vad_val',  3);
  sliderV('silence_duration', s.audio.silence_duration,'sil_val',  1);

  // Screenshots
  document.getElementById('screenshots_enabled').checked = s.screenshots.enabled;
  sel('monitor_num', String(s.screenshots.monitor));

  // Movement tab
  const mv = s.movement || {};
  sel('movement_mode',            mv.mode || 'still');
  v('movement_target',            s.ai_companion.target_player);
  sel('movement_tracker',         mv.tracker || 'llm');
  v('movement_appearance',        mv.appearance);
  sliderV('movement_dino_threshold', mv.dino_threshold ?? 0.40, 'mv_dino_threshold_val', 2);
  v('movement_model_look_at',     mv.model_look_at);
  v('movement_model_follow',      mv.model_follow);
  updateTrackerUI();
  refreshOverlayStatus();
  sel('movement_stop_distance',   mv.stop_distance || 'close');
  sliderV('movement_interval',    mv.interval,            'mv_interval_val', 0);
  sliderV('movement_scan_turn',   mv.scan_turn_duration,  'mv_scan_val',     1);

  // OSC
  v('osc_host', s.osc.host);
  v('osc_port', String(s.osc.port));

  updateMovementUI();
}

// ------------------------------------------------------------------ //
// Settings — save
// ------------------------------------------------------------------ //
async function saveSettings() {
  const payload = {
    ai_companion: {
      companion_name: gv('companion_name'),
      gender:         _gender,
      personality:    gv('personality'),
      target_player:  gv('movement_target'),
      temperature:    parseFloat(gv('temperature')),
      max_history:    parseInt(gv('max_history')),
    },
    openrouter: {
      api_key: gv('or_apikey'),
      model:   gv('or_model'),
    },
    xtts: {
      provider:     gv('tts_provider'),
      server_url:   gv('xtts_url'),
      endpoint:     gv('xtts_endpoint'),
      speaker_wav:  gv('xtts_speaker'),
      language:     gv('xtts_lang'),
      temperature:  parseFloat(gv('xtts_temperature')),
    },
    elevenlabs: {
      api_key:  gv('el_apikey'),
      voice_id: gv('el_voice_id'),
      model:    gv('el_model'),
    },
    whisper: {
      model:    gv('w_model'),
      language: gv('w_lang'),
      device:   gv('w_device'),
    },
    audio: {
      input_device:     intOrNull(gv('audio_input')),
      output_device:    intOrNull(gv('audio_output')),
      vad_threshold:    parseFloat(gv('vad_threshold')),
      silence_duration: parseFloat(gv('silence_duration')),
    },
    screenshots: {
      enabled: document.getElementById('screenshots_enabled').checked,
      monitor: parseInt(gv('monitor_num')),
    },
    movement: {
      mode:               gv('movement_mode'),
      tracker:            gv('movement_tracker'),
      model_look_at:      gv('movement_model_look_at'),
      model_follow:       gv('movement_model_follow'),
      stop_distance:      gv('movement_stop_distance'),
      appearance:         gv('movement_appearance'),
      dino_threshold:     parseFloat(gv('movement_dino_threshold')),
      interval:           parseFloat(gv('movement_interval')),
      scan_turn_duration: parseFloat(gv('movement_scan_turn')),
    },
    osc: {
      host: gv('osc_host'),
      port: parseInt(gv('osc_port')),
    },
  };

  await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  // Flash save banners
  ['save-banner-companion', 'save-banner-services', 'save-banner-movement'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.style.display = 'inline-block';
      setTimeout(() => el.style.display = 'none', 2000);
    }
  });
}

// ------------------------------------------------------------------ //
// Memory tab
// ------------------------------------------------------------------ //
async function loadMemoryTab() {
  await Promise.all([loadMemoryHistory(), loadLongTerm()]);
}

async function loadMemoryHistory() {
  const res = await fetch('/api/memory');
  const data = await res.json();
  const container = document.getElementById('mem-history');
  if (!data.messages.length) {
    container.innerHTML = '<div class="mem-empty">История пуста.</div>';
    return;
  }
  container.innerHTML = '';
  data.messages.forEach((msg, idx) => {
    const row = document.createElement('div');
    row.className = 'mem-msg mem-msg-' + msg.role;

    const ts = msg.timestamp ? `<span class="mem-ts">${msg.timestamp.slice(11,19)}</span>` : '';
    const roleLabel = msg.role === 'user' ? 'Игрок' : 'Бот';

    row.innerHTML = `
      <div class="mem-msg-meta">
        <span class="mem-role">${roleLabel}</span>${ts}
        <button class="mem-del" title="Удалить" onclick="deleteMessage(${idx})">✕</button>
      </div>
      <div class="mem-msg-text">${escHtml(msg.content)}</div>`;
    container.appendChild(row);
  });
}

async function deleteMessage(index) {
  await fetch(`/api/memory/message/${index}`, { method: 'DELETE' });
  await loadMemoryHistory();
}

async function loadLongTerm() {
  const res = await fetch('/api/longterm');
  const data = await res.json();
  document.getElementById('longterm-editor').value = data.content || '';
}

async function saveLongTerm() {
  const content = document.getElementById('longterm-editor').value;
  await fetch('/api/longterm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  const banner = document.getElementById('save-banner-longterm');
  banner.style.display = 'inline-block';
  setTimeout(() => banner.style.display = 'none', 2000);
}

async function clearLongTerm() {
  if (!confirm('Очистить долговременную память полностью?')) return;
  document.getElementById('longterm-editor').value = '';
  await saveLongTerm();
}

// ------------------------------------------------------------------ //
// Tracker UI — show/hide tracker-specific fields
// ------------------------------------------------------------------ //
function updateTrackerUI() {
  const isLlm = gv('movement_tracker') === 'llm';
  document.getElementById('tracker-llm-fields').style.display = isLlm ? '' : 'none';
}

// ------------------------------------------------------------------ //
// Overlay control
// ------------------------------------------------------------------ //
async function toggleOverlay() {
  const btn = document.getElementById('overlay-btn');
  const isRunning = btn.dataset.running === 'true';
  const res = await fetch(`/api/overlay/${isRunning ? 'stop' : 'start'}`, { method: 'POST' });
  const data = await res.json();
  const nowRunning = data.status === 'started' || data.status === 'already_running';
  _setOverlayBtn(nowRunning);
}

function _setOverlayBtn(running) {
  const btn = document.getElementById('overlay-btn');
  if (!btn) return;
  btn.dataset.running = running ? 'true' : 'false';
  btn.textContent = running ? 'Выключить оверлей' : 'Включить оверлей';
  btn.className = running ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm';
}

async function refreshOverlayStatus() {
  const res = await fetch('/api/overlay/status');
  const data = await res.json();
  _setOverlayBtn(data.running);
}

// ------------------------------------------------------------------ //
// Movement UI — show/hide auto-movement card based on mode
// ------------------------------------------------------------------ //
const MODE_HINTS = {
  still:   'Бот стоит на месте. Все движения заблокированы.',
  look_at: 'Бот периодически сканирует экран и поворачивается к игроку. Ходьба отключена.',
  follow:  'Бот периодически сканирует экран, поворачивается к игроку и идёт к нему.',
};

function updateMovementUI() {
  const mode = gv('movement_mode');
  const autoCard = document.getElementById('movement-auto-card');
  const hintEl   = document.getElementById('movement_mode_hint');
  if (autoCard) autoCard.style.display = (mode === 'look_at' || mode === 'follow') ? '' : 'none';
  if (hintEl)   hintEl.textContent = MODE_HINTS[mode] || '';
}

// ------------------------------------------------------------------ //
// Audio devices
// ------------------------------------------------------------------ //
async function refreshDevices() {
  const res = await fetch('/api/audio/devices');
  const data = await res.json();

  const inputSel  = document.getElementById('audio_input');
  const outputSel = document.getElementById('audio_output');

  // Get current saved values to re-select after refresh
  const savedInput  = inputSel.value;
  const savedOutput = outputSel.value;

  inputSel.innerHTML  = '<option value="">По умолчанию</option>';
  outputSel.innerHTML = '<option value="">По умолчанию</option>';

  for (const d of (data.inputs || [])) {
    const opt = new Option(d.label || `[${d.index}] ${d.name}`, d.index);
    if (d.api === 'WASAPI') opt.style.fontWeight = 'bold';
    inputSel.appendChild(opt);
  }
  for (const d of (data.outputs || [])) {
    const opt = new Option(d.label || `[${d.index}] ${d.name}`, d.index);
    if (d.api === 'WASAPI') opt.style.fontWeight = 'bold';
    outputSel.appendChild(opt);
  }

  // Restore selections
  inputSel.value  = savedInput  || '';
  outputSel.value = savedOutput || '';
}

// ------------------------------------------------------------------ //
// TTS helpers
// ------------------------------------------------------------------ //
function updateTTSUI() {
  const provider = gv('tts_provider');
  document.getElementById('tts-xtts-fields').style.display      = provider === 'xtts'         ? '' : 'none';
  document.getElementById('tts-elevenlabs-fields').style.display = provider === 'elevenlabs'   ? '' : 'none';
}

async function testTTS() {
  const text = prompt('Текст для теста голоса:', 'Привет! Это тест голоса бота.');
  if (!text) return;
  appendLog('system', 'Тест TTS...');
  const res = await fetch('/api/tts/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      provider:     gv('tts_provider'),
      // XTTS params
      speaker_wav:  gv('xtts_speaker'),
      language:     gv('xtts_lang'),
      server_url:   gv('xtts_url'),
      endpoint:     gv('xtts_endpoint'),
      temperature:  parseFloat(gv('xtts_temperature')),
      // ElevenLabs params
      el_api_key:   gv('el_apikey'),
      el_voice_id:  gv('el_voice_id'),
      el_model:     gv('el_model'),
      output_device: intOrNull(gv('audio_output')),
    }),
  });
  const data = await res.json();
  if (data.status === 'ok') {
    appendLog('system', 'TTS работает!');
  } else {
    appendLog('error', 'Ошибка TTS: ' + (data.detail || 'проверь настройки'));
  }
}

async function fetchSpeakers() {
  const res = await fetch('/api/tts/speakers');
  const data = await res.json();
  if (!data.speakers.length) {
    alert('Не удалось получить список спикеров (возможно, сервер не запущен или эндпоинт другой).');
    return;
  }
  alert('Доступные спикеры:\n\n' + data.speakers.join('\n'));
}

// ------------------------------------------------------------------ //
// Helpers
// ------------------------------------------------------------------ //
function v(id, val)          { if (val !== undefined && val !== null) document.getElementById(id).value = val; }
function gv(id)              { return document.getElementById(id).value; }
function sel(id, val)        { const el = document.getElementById(id); if (el) el.value = val; }
function intOrNull(v)        { const n = parseInt(v); return isNaN(n) ? null : n; }
function sliderV(id, val, labelId, decimals = 2) {
  const el = document.getElementById(id);
  const lbl = document.getElementById(labelId);
  if (el && val !== undefined && val !== null) {
    el.value = val;
    if (lbl) lbl.textContent = parseFloat(val).toFixed(decimals);
  }
}

// ------------------------------------------------------------------ //
// Init
// ------------------------------------------------------------------ //
(async () => {
  await loadSettings();
  await refreshDevices();
  // Restore device selections after refresh
  const settingsRes = await fetch('/api/settings');
  const s = await settingsRes.json();
  const inDev  = s.audio.input_device;
  const outDev = s.audio.output_device;
  if (inDev  !== null && inDev  !== undefined) document.getElementById('audio_input').value  = inDev;
  if (outDev !== null && outDev !== undefined) document.getElementById('audio_output').value = outDev;
})();
