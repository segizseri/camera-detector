/*
 * Camera Detector AI Box — общий слой интерфейса.
 *
 * Глобальный объект window.UI: тема, боковое меню, toast, модальные окна,
 * обёртка над fetch, форматирование дат и чисел, реестр типов событий
 * (каталог детекторов из detector-catalog.js) и HLS-плеер для live-просмотра.
 * Скрипты страниц подключаются после этого файла и используют только UI.*.
 */
(function () {
  'use strict';

  const ICON_SPRITE = '/static/icons.svg';
  const doc = document;

  /* ------------------------------------------------------------ Утилиты */

  const storage = {
    get(key) {
      try { return window.localStorage.getItem(key); } catch (_) { return null; }
    },
    set(key, value) {
      try { window.localStorage.setItem(key, value); } catch (_) { /* приватный режим */ }
    },
  };

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function icon(name, cls = '') {
    return `<svg class="icon ${cls}" aria-hidden="true" focusable="false"><use href="${ICON_SPRITE}#i-${name}"></use></svg>`;
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function plural(n, forms) {
    const abs = Math.abs(n) % 100;
    const last = abs % 10;
    if (abs > 10 && abs < 20) return forms[2];
    if (last > 1 && last < 5) return forms[1];
    if (last === 1) return forms[0];
    return forms[2];
  }

  function debounce(fn, ms = 250) {
    let timer = null;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  /* -------------------------------------------------------- Форматирование */

  // Сервер хранит время в UTC без зоны (datetime.utcnow()); без «Z» браузер
  // принял бы его за местное и сдвинул бы время на величину часового пояса.
  function parseDate(value) {
    if (!value) return null;
    if (value instanceof Date) return value;
    if (typeof value === 'number') return new Date(value < 1e12 ? value * 1000 : value);
    const text = String(value);
    const hasZone = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(text);
    const date = new Date(hasZone || !text.includes('T') ? text : `${text}Z`);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  const dtf = {
    dateTime: new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }),
    dateTimeYear: new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }),
    full: new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    date: new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }),
    time: new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    clock: new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }),
  };
  const rtf = new Intl.RelativeTimeFormat('ru', { numeric: 'auto' });
  const nf = new Intl.NumberFormat('ru-RU');

  const fmt = {
    dateTime(value) {
      const d = parseDate(value);
      if (!d) return '—';
      return (d.getFullYear() === new Date().getFullYear() ? dtf.dateTime : dtf.dateTimeYear).format(d);
    },
    full(value) {
      const d = parseDate(value);
      return d ? dtf.full.format(d) : '—';
    },
    date(value) {
      const d = parseDate(value);
      return d ? dtf.date.format(d) : '—';
    },
    time(value) {
      const d = parseDate(value);
      return d ? dtf.time.format(d) : '—';
    },
    clock(value) {
      const d = parseDate(value);
      return d ? dtf.clock.format(d) : '—';
    },
    relative(value) {
      const d = parseDate(value);
      if (!d) return '—';
      const diff = (d.getTime() - Date.now()) / 1000;
      const abs = Math.abs(diff);
      if (abs < 45) return 'только что';
      if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
      if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
      if (abs < 86400 * 7) return rtf.format(Math.round(diff / 86400), 'day');
      return fmt.dateTime(d);
    },
    duration(seconds) {
      const total = Math.max(0, Math.floor(Number(seconds) || 0));
      const h = Math.floor(total / 3600);
      const m = Math.floor((total % 3600) / 60);
      const s = total % 60;
      return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
    },
    number(value) {
      return nf.format(Number(value) || 0);
    },
    percent(value, digits = 0) {
      const n = Number(value);
      if (!Number.isFinite(n)) return '—';
      return `${(n * 100).toFixed(digits).replace('.', ',')}%`;
    },
    bytes(value) {
      let n = Number(value) || 0;
      const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
      let i = 0;
      while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
      return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1).replace('.', ',')} ${units[i]}`;
    },
    isoDate(date) {
      const d = date instanceof Date ? date : new Date();
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    },
  };

  /* ----------------------------------------------------------------- API */

  class ApiError extends Error {
    constructor(message, status, data) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.data = data;
    }
  }

  function detailMessage(detail) {
    if (!detail) return '';
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail.map((item) => (item && item.msg ? item.msg : String(item))).join('; ');
    }
    return String(detail);
  }

  // fetch с JSON по умолчанию и понятной ошибкой: { json } — тело запроса.
  async function api(url, options = {}) {
    const opts = { ...options, headers: { ...(options.headers || {}) } };
    if (opts.json !== undefined) {
      opts.body = JSON.stringify(opts.json);
      opts.headers['Content-Type'] = 'application/json';
      delete opts.json;
    }
    let response;
    try {
      response = await fetch(url, opts);
    } catch (_) {
      throw new ApiError('Нет связи с сервером. Проверьте сеть и повторите попытку.', 0);
    }
    const text = await response.text();
    let data = null;
    if (text) {
      try { data = JSON.parse(text); } catch (_) { data = text; }
    }
    if (!response.ok) {
      const detail = data && typeof data === 'object' ? detailMessage(data.detail || data.message || data.error) : '';
      throw new ApiError(detail || `Сервер ответил ошибкой (HTTP ${response.status}).`, response.status, data);
    }
    return data;
  }

  /* --------------------------------------------------------------- Тема */

  const theme = {
    get() {
      return doc.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
    },
    set(value) {
      const next = value === 'light' ? 'light' : 'dark';
      // Без переходов на время смены темы, иначе кнопки и поля «догоняют» фон.
      doc.documentElement.classList.add('theme-switching');
      doc.documentElement.dataset.theme = next;
      requestAnimationFrame(() => requestAnimationFrame(() => doc.documentElement.classList.remove('theme-switching')));
      storage.set('ui.theme', next);
      syncThemeControls();
      doc.dispatchEvent(new CustomEvent('ui:themechange', { detail: next }));
    },
    toggle() {
      theme.set(theme.get() === 'dark' ? 'light' : 'dark');
    },
  };

  function syncThemeControls() {
    const dark = theme.get() === 'dark';
    doc.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      const label = dark ? 'Включить светлую тему' : 'Включить тёмную тему';
      button.setAttribute('aria-label', label);
      button.title = label;
      button.innerHTML = icon(dark ? 'sun' : 'moon');
    });
    doc.querySelectorAll('[data-theme-choice]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme.get()));
    });
  }

  /* ------------------------------------------------------- Боковое меню */

  function initSidebar() {
    const sidebar = doc.getElementById('app-sidebar');
    const scrim = doc.getElementById('app-scrim');
    const openButton = doc.querySelector('[data-sidebar-open]');
    if (!sidebar || !scrim) return;
    const desktop = window.matchMedia('(min-width: 1024px)');

    function setOpen(open) {
      sidebar.dataset.open = String(open);
      scrim.hidden = !open;
      if (openButton) openButton.setAttribute('aria-expanded', String(open));
      if (desktop.matches) return;
      sidebar.toggleAttribute('inert', !open);
      doc.body.style.overflow = open ? 'hidden' : '';
      if (open) {
        const current = sidebar.querySelector('[aria-current="page"]') || sidebar.querySelector('a, button');
        current?.focus();
      } else if (openButton && sidebar.contains(doc.activeElement)) {
        openButton.focus();
      }
    }

    function sync() {
      if (desktop.matches) {
        sidebar.removeAttribute('inert');
        sidebar.dataset.open = 'false';
        scrim.hidden = true;
        doc.body.style.overflow = '';
      } else if (sidebar.dataset.open !== 'true') {
        sidebar.setAttribute('inert', '');
      }
    }

    openButton?.addEventListener('click', () => setOpen(true));
    doc.querySelectorAll('[data-sidebar-close]').forEach((el) => el.addEventListener('click', () => setOpen(false)));
    scrim.addEventListener('click', () => setOpen(false));
    doc.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && sidebar.dataset.open === 'true') setOpen(false);
    });
    desktop.addEventListener('change', sync);
    sync();
  }

  /* -------------------------------------------------------------- Toast */

  const TOAST_ICONS = { success: 'check-circle', error: 'alert-circle', warning: 'alert-triangle', info: 'info' };

  function toast(message, options = {}) {
    const region = doc.getElementById('toast-region');
    if (!region) return null;
    const type = options.type || 'success';
    const el = doc.createElement('div');
    el.className = `toast toast-${type}`;
    el.setAttribute('role', type === 'error' ? 'alert' : 'status');
    el.innerHTML = `
      ${icon(TOAST_ICONS[type] || 'info')}
      <div class="min-w-0 flex-1">
        ${options.title ? `<div class="toast-title">${escapeHtml(options.title)}</div>` : ''}
        <div class="${options.title ? 'toast-message' : 'toast-title font-medium'}">${escapeHtml(message)}</div>
      </div>
      <button type="button" class="btn btn-ghost btn-xs btn-icon -mr-1 -mt-0.5" aria-label="Закрыть уведомление">${icon('x', 'icon-sm')}</button>`;
    let timer = null;
    const remove = () => {
      clearTimeout(timer);
      el.dataset.leaving = 'true';
      setTimeout(() => el.remove(), 180);
    };
    const arm = () => {
      clearTimeout(timer);
      timer = setTimeout(remove, options.timeout ?? (type === 'error' ? 8000 : 4500));
    };
    el.querySelector('button').addEventListener('click', remove);
    el.addEventListener('mouseenter', () => clearTimeout(timer));
    el.addEventListener('mouseleave', arm);
    el.addEventListener('focusin', () => clearTimeout(timer));
    el.addEventListener('focusout', arm);
    region.appendChild(el);
    while (region.children.length > 4) region.firstElementChild.remove();
    arm();
    return { close: remove };
  }

  /* ----------------------------------------------------- Модальные окна */

  function openDialog(dialog) {
    if (typeof dialog === 'string') dialog = doc.getElementById(dialog);
    if (dialog && !dialog.open) dialog.showModal();
    return dialog;
  }

  function closeDialog(dialog, value) {
    if (typeof dialog === 'string') dialog = doc.getElementById(dialog);
    if (dialog?.open) dialog.close(value);
  }

  // Клик по подложке закрывает окно; кнопки [data-dialog-close] закрывают ближайшее.
  doc.addEventListener('click', (event) => {
    const closer = event.target.closest('[data-dialog-close]');
    if (closer) {
      closer.closest('dialog')?.close();
      return;
    }
    const dialog = event.target;
    if (dialog instanceof HTMLDialogElement && dialog.classList.contains('modal') && dialog.open) {
      const rect = dialog.getBoundingClientRect();
      const inside = event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
      if (!inside) dialog.close();
    }
  });

  // Подтверждение действия вместо window.confirm(). Возвращает Promise<boolean>.
  function confirmAction(options = {}) {
    const dialog = doc.getElementById('confirm-dialog');
    if (!dialog) return Promise.resolve(window.confirm(options.message || 'Подтвердите действие'));
    const danger = options.danger !== false;
    dialog.querySelector('[data-confirm-title]').textContent = options.title || 'Подтвердите действие';
    dialog.querySelector('[data-confirm-message]').textContent = options.message || '';
    const iconBox = dialog.querySelector('[data-confirm-icon]');
    iconBox.className = `modal-icon ${danger ? 'bg-critical-soft text-critical-fg' : 'bg-primary-soft text-primary-text'}`;
    iconBox.innerHTML = icon(options.icon || (danger ? 'alert-triangle' : 'info'));
    const ok = dialog.querySelector('[data-confirm-ok]');
    ok.textContent = options.confirmText || (danger ? 'Удалить' : 'Подтвердить');
    ok.className = `btn ${danger ? 'btn-danger' : 'btn-primary'}`;
    dialog.querySelector('[data-confirm-cancel]').textContent = options.cancelText || 'Отмена';
    dialog.returnValue = '';
    return new Promise((resolve) => {
      dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true });
      dialog.showModal();
      (danger ? dialog.querySelector('[data-confirm-cancel]') : ok).focus();
    });
  }

  /* ---------------------------------------------- Кнопки, пустые состояния */

  function setBusy(button, busy, text) {
    if (!button) return;
    if (busy) {
      if (button.getAttribute('aria-busy') === 'true') return;
      button.dataset.idleHtml = button.innerHTML;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.innerHTML = `<span class="spinner" aria-hidden="true"></span>${text ? `<span>${escapeHtml(text)}</span>` : '<span class="sr-only">Загрузка</span>'}`;
    } else {
      if (button.dataset.idleHtml !== undefined) button.innerHTML = button.dataset.idleHtml;
      delete button.dataset.idleHtml;
      button.disabled = false;
      button.removeAttribute('aria-busy');
    }
  }

  function emptyState({ iconName = 'inbox', title = 'Пока пусто', text = '', action = '' } = {}) {
    return `<div class="empty">
      <div class="empty-icon">${icon(iconName, 'icon-lg')}</div>
      <div class="empty-title">${escapeHtml(title)}</div>
      ${text ? `<p class="empty-text">${escapeHtml(text)}</p>` : ''}
      ${action ? `<div class="mt-2">${action}</div>` : ''}
    </div>`;
  }

  function errorState(message, retryLabel = 'Повторить') {
    return `<div class="empty" role="alert">
      <div class="empty-icon text-critical-fg">${icon('alert-circle', 'icon-lg')}</div>
      <div class="empty-title">Не удалось загрузить данные</div>
      <p class="empty-text">${escapeHtml(message)}</p>
      <button type="button" class="btn btn-secondary btn-sm mt-2" data-retry>${icon('refresh', 'icon-sm')}${escapeHtml(retryLabel)}</button>
    </div>`;
  }

  /* ------------------------------------------------- Типы событий и статусы */

  const SEVERITY = {
    critical: { label: 'Критично', badge: 'badge-critical', text: 'sev-critical' },
    high: { label: 'Высокая', badge: 'badge-high', text: 'sev-high' },
    medium: { label: 'Средняя', badge: 'badge-medium', text: 'sev-medium' },
    info: { label: 'Инфо', badge: 'badge-info', text: 'sev-info' },
    system: { label: 'Система', badge: 'badge-system', text: 'sev-system' },
  };

  // Оформление детекторов каталога: иконка и серьёзность события.
  const DETECTOR_STYLE = {
    fight: { icon: 'swords', severity: 'critical' },
    bullying: { icon: 'shield-alert', severity: 'high' },
    cash_theft: { icon: 'banknote', severity: 'high' },
    shelf_theft: { icon: 'shopping-bag', severity: 'high' },
    eating: { icon: 'utensils', severity: 'medium' },
  };

  const MATURITY = {
    concept: { label: 'Концепт', badge: 'badge-outline', hint: 'Контракт объявлен, работает упрощённый прототип на позах' },
    prototype: { label: 'Прототип', badge: 'badge-medium', hint: 'Реализация есть, качество на реальных данных не измерено' },
    beta: { label: 'Бета', badge: 'badge-info', hint: 'Качество измерено на реальных данных' },
    stable: { label: 'Стабильный', badge: 'badge-success', hint: 'Готов к промышленной эксплуатации' },
  };

  const catalog = (window.DETECTOR_CATALOG && window.DETECTOR_CATALOG.detectors) || [];
  const detectors = catalog.map((d) => ({ ...d, ...(DETECTOR_STYLE[d.id] || { icon: 'target', severity: 'medium' }) }));

  const EVENT_TYPES = {};
  detectors.forEach((d) => {
    EVENT_TYPES[d.legacy_event_type] = { type: d.legacy_event_type, label: d.title, icon: d.icon, severity: d.severity, detector: d.id, group: 'detector' };
  });
  EVENT_TYPES.person_detected = { type: 'person_detected', label: 'Человек в кадре', icon: 'user', severity: 'info', group: 'other' };
  EVENT_TYPES.camera_offline = { type: 'camera_offline', label: 'Камера недоступна', icon: 'video-off', severity: 'system', group: 'system' };

  function eventMeta(type) {
    return EVENT_TYPES[type] || { type, label: type || 'Событие', icon: 'bell', severity: 'system', group: 'other' };
  }

  function eventBadge(type, options = {}) {
    const meta = eventMeta(type);
    return `<span class="badge ${options.size || ''} ${SEVERITY[meta.severity].badge}">${icon(meta.icon)}${escapeHtml(meta.label)}</span>`;
  }

  const CAMERA_STATUS = {
    online: { label: 'Онлайн', badge: 'badge-success', dot: 'sev-success', live: true },
    offline: { label: 'Офлайн', badge: 'badge-system', dot: 'sev-system' },
    error: { label: 'Ошибка', badge: 'badge-critical', dot: 'sev-critical' },
    checking: { label: 'Проверка…', badge: 'badge-info', dot: 'sev-info' },
  };

  function cameraStatus(status) {
    return CAMERA_STATUS[status] || CAMERA_STATUS.offline;
  }

  function cameraStatusBadge(status, options = {}) {
    const meta = cameraStatus(status);
    const cls = options.overlay ? 'badge-overlay' : meta.badge;
    return `<span class="badge ${cls}"><span class="dot ${meta.dot} ${meta.live ? 'dot-live' : ''}"></span>${escapeHtml(meta.label)}</span>`;
  }

  function activeDetectors(camera) {
    return detectors.filter((d) => camera && camera[d.legacy_flag]);
  }

  /* --------------------------------------------------------- Live-плеер */

  // HLS-поток камеры: POST trigger-hls → hls.js (или нативный HLS в Safari),
  // keepalive раз в 30 с, stop-hls при остановке и уходе со страницы.
  class LivePlayer {
    constructor(video, cameraId, { onState } = {}) {
      this.video = video;
      this.cameraId = cameraId;
      this.onState = onState || (() => {});
      this.hls = null;
      this.keepalive = null;
      this.state = 'idle';
      this.session = 0;
      this.mediaRecoveries = 0;
    }

    setState(state, detail) {
      this.state = state;
      this.onState(state, detail);
    }

    async start() {
      this.stop({ silent: true, keepServer: true });
      const session = ++this.session;
      this.mediaRecoveries = 0;
      LivePlayer.active.add(this);
      this.setState('connecting');
      let data;
      try {
        data = await api(`/api/cameras/${encodeURIComponent(this.cameraId)}/trigger-hls`, { method: 'POST' });
      } catch (error) {
        if (session === this.session) this.fail(error.message);
        return;
      }
      if (session !== this.session) return;
      this.keepalive = setInterval(() => {
        fetch(`/api/cameras/${encodeURIComponent(this.cameraId)}/hls-keepalive`, { method: 'POST', keepalive: true }).catch(() => {});
      }, 30000);
      // ffmpeg пишет первый сегмент через 2–4 с после старта; уже запущенный поток
      // подключаем сразу. Если манифест ещё не готов, hls.js повторит запрос.
      if (data.status !== 'running') await sleep(4000);
      if (session !== this.session) return;
      this.attach(data.hls_url, session);
    }

    attach(url, session) {
      const video = this.video;
      video.muted = true;
      video.playsInline = true;
      if (window.Hls && window.Hls.isSupported()) {
        const retry = { maxNumRetry: 8, retryDelayMs: 1000, maxRetryDelayMs: 3000, shouldRetry: (cfg, count) => count < (cfg ? cfg.maxNumRetry : 0) };
        const hls = new window.Hls({
          maxBufferLength: 5,
          maxMaxBufferLength: 10,
          liveSyncDurationCount: 2,
          manifestLoadPolicy: {
            default: {
              maxTimeToFirstByteMs: 10000,
              maxLoadTimeMs: 20000,
              timeoutRetry: { maxNumRetry: 2, retryDelayMs: 0, maxRetryDelayMs: 0 },
              errorRetry: retry,
            },
          },
        });
        this.hls = hls;
        hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
          if (session !== this.session) return;
          video.play().catch(() => {});
        });
        hls.on(window.Hls.Events.FRAG_BUFFERED, () => {
          if (session === this.session && this.state !== 'playing') this.setState('playing');
        });
        hls.on(window.Hls.Events.ERROR, (_event, data) => {
          if (!data.fatal || session !== this.session) return;
          if (data.type === window.Hls.ErrorTypes.MEDIA_ERROR && this.mediaRecoveries < 2) {
            this.mediaRecoveries += 1;
            hls.recoverMediaError();
            return;
          }
          this.fail(data.type === window.Hls.ErrorTypes.NETWORK_ERROR ? 'Поток не отвечает. Проверьте RTSP-подключение камеры.' : 'Не удалось воспроизвести поток.');
        });
        hls.loadSource(url);
        hls.attachMedia(video);
      } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = url;
        video.addEventListener('loadeddata', () => {
          if (session === this.session) this.setState('playing');
        }, { once: true });
        video.addEventListener('error', () => {
          if (session === this.session) this.fail('Не удалось воспроизвести поток.');
        }, { once: true });
        video.play().catch(() => {});
      } else {
        this.fail('Браузер не поддерживает HLS-видео.');
      }
    }

    fail(message) {
      this.teardown();
      this.setState('error', message);
    }

    teardown() {
      clearInterval(this.keepalive);
      this.keepalive = null;
      if (this.hls) {
        this.hls.destroy();
        this.hls = null;
      }
      if (this.video.getAttribute('src')) {
        this.video.removeAttribute('src');
        this.video.load();
      }
    }

    stop({ silent = false, keepServer = false } = {}) {
      const wasActive = LivePlayer.active.has(this);
      this.session += 1;
      this.teardown();
      LivePlayer.active.delete(this);
      if (wasActive && !keepServer) {
        fetch(`/api/cameras/${encodeURIComponent(this.cameraId)}/stop-hls`, { method: 'POST', keepalive: true }).catch(() => {});
      }
      if (!silent) this.setState('idle');
    }
  }
  LivePlayer.active = new Set();

  window.addEventListener('pagehide', () => {
    LivePlayer.active.forEach((player) => {
      const url = `/api/cameras/${encodeURIComponent(player.cameraId)}/stop-hls`;
      clearInterval(player.keepalive);
      if (navigator.sendBeacon) navigator.sendBeacon(url, new Blob([]));
      else fetch(url, { method: 'POST', keepalive: true }).catch(() => {});
    });
    LivePlayer.active.clear();
  });

  /* ------------------------------------------------- Карточка события */

  const snapshotUrl = (path) => (path ? `/media/snapshots/${encodeURI(String(path).split('/').pop())}` : null);
  const clipUrl = (path) => (path ? `/media/clips/${encodeURI(String(path).split('/').pop())}` : null);

  function eventIsTest(event) {
    if (!event || !event.meta_json) return false;
    try { return Boolean(JSON.parse(event.meta_json).is_test); } catch (_) { return false; }
  }

  let eventDialog = null;
  let eventDialogState = { list: [], index: 0, cameraName: () => '' };

  function ensureEventDialog() {
    if (eventDialog) return eventDialog;
    eventDialog = doc.createElement('dialog');
    eventDialog.className = 'modal modal-lg';
    eventDialog.id = 'event-dialog';
    eventDialog.setAttribute('aria-labelledby', 'event-dialog-title');
    doc.body.appendChild(eventDialog);
    eventDialog.addEventListener('keydown', (e) => {
      if (e.target.closest('video')) return;
      if (e.key === 'ArrowRight') { e.preventDefault(); stepEvent(1); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); stepEvent(-1); }
    });
    eventDialog.addEventListener('close', () => {
      eventDialog.querySelectorAll('video').forEach((v) => v.pause());
    });
    eventDialog.addEventListener('click', (e) => {
      const nav = e.target.closest('[data-event-step]');
      if (nav) stepEvent(Number(nav.dataset.eventStep));
      const tab = e.target.closest('[data-media-tab]');
      if (tab) showMediaTab(tab.dataset.mediaTab);
    });
    return eventDialog;
  }

  function showMediaTab(name) {
    eventDialog.querySelectorAll('[data-media-tab]').forEach((tab) => tab.setAttribute('aria-selected', String(tab.dataset.mediaTab === name)));
    eventDialog.querySelectorAll('[data-media-panel]').forEach((panel) => { panel.hidden = panel.dataset.mediaPanel !== name; });
    eventDialog.querySelectorAll('[data-media-panel] video').forEach((v) => { if (name !== 'clip') v.pause(); });
  }

  function stepEvent(delta) {
    const { list, index } = eventDialogState;
    const next = index + delta;
    if (next < 0 || next >= list.length) return;
    eventDialogState.index = next;
    renderEventDialog();
  }

  function renderEventDialog() {
    const { list, index, cameraName } = eventDialogState;
    const event = list[index];
    const meta = eventMeta(event.event_type);
    const snap = snapshotUrl(event.snapshot_path);
    const clip = clipUrl(event.clip_path);
    const camera = cameraName(event.camera_id, event) || event.camera_id || '—';
    const isTest = eventIsTest(event);
    const tabs = snap && clip
      ? `<div class="seg" role="tablist" aria-label="Материалы события">
          <button type="button" role="tab" data-media-tab="snapshot" aria-selected="true">${icon('image', 'icon-sm')}Снимок</button>
          <button type="button" role="tab" data-media-tab="clip" aria-selected="false">${icon('film', 'icon-sm')}Клип</button>
        </div>`
      : '';
    const snapshotPanel = snap
      ? `<div data-media-panel="snapshot" class="media-frame rounded-lg border border-line"><img src="${snap}" alt="Снимок события «${escapeHtml(meta.label)}», камера ${escapeHtml(camera)}"></div>`
      : '';
    const clipPanel = clip
      ? `<div data-media-panel="clip" class="space-y-2" ${snap ? 'hidden' : ''}>
          <div class="media-frame rounded-lg border border-line"><video controls preload="none" src="${clip}"></video></div>
          <p class="hint" data-clip-error hidden>Браузер не может воспроизвести этот клип. Скачайте файл и откройте его в видеоплеере.</p>
        </div>`
      : '';
    const noMedia = !snap && !clip
      ? `<div class="media-frame media-grid-bg rounded-lg border border-line"><div class="media-overlay">${icon('image', 'icon-xl')}<span>Снимка для этого события нет</span></div></div>`
      : '';
    eventDialog.innerHTML = `
      <div class="modal-header">
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            ${eventBadge(event.event_type, { size: 'badge-lg' })}
            ${isTest ? '<span class="badge badge-outline">Тестовое событие</span>' : ''}
          </div>
          <h2 id="event-dialog-title" class="modal-title mt-2">${escapeHtml(meta.label)} · ${escapeHtml(camera)}</h2>
          <p class="text-sm text-muted mt-0.5">${escapeHtml(fmt.full(event.timestamp))} · ${escapeHtml(fmt.relative(event.timestamp))}</p>
        </div>
        <button type="button" class="btn btn-ghost btn-icon" data-dialog-close aria-label="Закрыть">${icon('x')}</button>
      </div>
      <div class="modal-body space-y-4">
        ${tabs}
        ${snapshotPanel}${clipPanel}${noMedia}
        <dl class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
          <div><dt class="hint">Уверенность</dt><dd class="font-semibold text-fg num">${event.confidence != null ? fmt.percent(event.confidence, 1) : '—'}</dd></div>
          <div><dt class="hint">Серьёзность</dt><dd class="font-semibold text-fg">${SEVERITY[meta.severity].label}</dd></div>
          <div><dt class="hint">Камера</dt><dd class="font-semibold text-fg truncate">${event.camera_id ? `<a class="link" href="/cameras/${encodeURIComponent(event.camera_id)}">${escapeHtml(camera)}</a>` : escapeHtml(camera)}</dd></div>
          <div><dt class="hint">ID события</dt><dd class="mono text-fg truncate" title="${escapeHtml(event.id)}">${escapeHtml(String(event.id || '').slice(0, 8))}</dd></div>
        </dl>
      </div>
      <div class="modal-footer justify-between">
        <div class="flex items-center gap-2">
          ${list.length > 1 ? `
            <button type="button" class="btn btn-secondary btn-sm btn-icon" data-event-step="-1" aria-label="Предыдущее событие" ${index === 0 ? 'disabled' : ''}>${icon('chevron-left', 'icon-sm')}</button>
            <span class="text-xs text-subtle num">${index + 1} из ${list.length}</span>
            <button type="button" class="btn btn-secondary btn-sm btn-icon" data-event-step="1" aria-label="Следующее событие" ${index >= list.length - 1 ? 'disabled' : ''}>${icon('chevron-right', 'icon-sm')}</button>` : ''}
        </div>
        <div class="flex flex-wrap gap-2">
          ${snap ? `<a class="btn btn-secondary btn-sm" href="${snap}" target="_blank" rel="noopener">${icon('external', 'icon-sm')}Снимок в новой вкладке</a>` : ''}
          ${clip ? `<a class="btn btn-secondary btn-sm" href="${clip}" download>${icon('download', 'icon-sm')}Скачать клип</a>` : ''}
          <button type="button" class="btn btn-primary btn-sm" data-dialog-close>Закрыть</button>
        </div>
      </div>`;
    const video = eventDialog.querySelector('[data-media-panel="clip"] video');
    video?.addEventListener('error', () => {
      const note = eventDialog.querySelector('[data-clip-error]');
      if (note) note.hidden = false;
    });
  }

  function openEvent(list, index = 0, options = {}) {
    ensureEventDialog();
    eventDialogState = { list, index, cameraName: options.cameraName || (() => '') };
    renderEventDialog();
    if (!eventDialog.open) eventDialog.showModal();
  }

  // Просмотр изображения во весь экран (снимки посетителей, проверки детекций)
  function openImage(src, alt = '') {
    let dialog = doc.getElementById('image-dialog');
    if (!dialog) {
      dialog = doc.createElement('dialog');
      dialog.id = 'image-dialog';
      dialog.className = 'modal modal-lg';
      dialog.setAttribute('aria-label', 'Просмотр снимка');
      doc.body.appendChild(dialog);
    }
    dialog.innerHTML = `
      <div class="modal-header"><h2 class="modal-title">${escapeHtml(alt || 'Снимок')}</h2>
        <button type="button" class="btn btn-ghost btn-icon" data-dialog-close aria-label="Закрыть">${icon('x')}</button></div>
      <div class="modal-body"><div class="media-frame rounded-lg border border-line"><img src="${escapeHtml(src)}" alt="${escapeHtml(alt)}"></div></div>
      <div class="modal-footer"><a class="btn btn-secondary btn-sm" href="${escapeHtml(src)}" target="_blank" rel="noopener">${icon('external', 'icon-sm')}Открыть в новой вкладке</a>
        <button type="button" class="btn btn-primary btn-sm" data-dialog-close>Закрыть</button></div>`;
    dialog.showModal();
  }

  /* ---------------------------------------------------- Общие данные */

  let camerasPromise = null;
  function cameras({ refresh = false } = {}) {
    if (!camerasPromise || refresh) {
      camerasPromise = api('/api/cameras/').catch((error) => {
        camerasPromise = null;
        throw error;
      });
    }
    return camerasPromise;
  }

  // Периодическое обновление, которое ставится на паузу во фоновой вкладке.
  function poll(fn, intervalMs) {
    let timer = null;
    const tick = async () => {
      if (!doc.hidden) {
        try { await fn(); } catch (_) { /* ошибка уже показана на странице */ }
      }
      timer = setTimeout(tick, intervalMs);
    };
    timer = setTimeout(tick, intervalMs);
    doc.addEventListener('visibilitychange', () => {
      if (!doc.hidden) {
        clearTimeout(timer);
        tick();
      }
    });
    return () => clearTimeout(timer);
  }

  /* ------------------------------------------------- Шапка: связь и часы */

  function initTopbar() {
    const clock = doc.getElementById('topbar-clock');
    const status = doc.getElementById('topbar-status');
    const tickClock = () => { if (clock) clock.textContent = fmt.clock(new Date()); };
    tickClock();
    setInterval(tickClock, 15000);
    if (!status) return;
    const check = async () => {
      try {
        const response = await fetch('/health', { cache: 'no-store' });
        if (!response.ok) throw new Error();
        status.className = 'badge badge-success hidden sm:inline-flex';
        status.innerHTML = '<span class="dot sev-success"></span>Сервер на связи';
      } catch (_) {
        status.className = 'badge badge-critical inline-flex';
        status.innerHTML = '<span class="dot sev-critical"></span>Нет связи с сервером';
      }
    };
    check();
    poll(check, 30000);
  }

  /* --------------------------------------------------------------- Старт */

  doc.addEventListener('click', (event) => {
    if (event.target.closest('[data-theme-toggle]')) theme.toggle();
    const choice = event.target.closest('[data-theme-choice]');
    if (choice) theme.set(choice.dataset.themeChoice);
  });

  function init() {
    syncThemeControls();
    initSidebar();
    initTopbar();
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init);
  else init();

  window.UI = {
    api,
    ApiError,
    escapeHtml,
    icon,
    sleep,
    plural,
    debounce,
    parseDate,
    fmt,
    storage,
    theme,
    toast,
    openDialog,
    closeDialog,
    confirm: confirmAction,
    setBusy,
    emptyState,
    errorState,
    SEVERITY,
    MATURITY,
    detectors,
    EVENT_TYPES,
    eventMeta,
    eventBadge,
    cameraStatus,
    cameraStatusBadge,
    activeDetectors,
    LivePlayer,
    snapshotUrl,
    clipUrl,
    eventIsTest,
    openEvent,
    openImage,
    cameras,
    poll,
  };
})();
