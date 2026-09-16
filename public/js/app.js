'use strict';

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const DEMO = { email: 'demo@punchlist.test', password: 'demo1234' };
  const MAX_HOLES = 30;

  const state = {
    user: null,
    tasks: [],
    stats: null,
    filters: { q: '', status: '', priority: '', sort: 'created' },
    editingId: null,
    justPunched: null,
  };

  /* ------------------------------------------------------------------ API */
  class ApiError extends Error {
    constructor(status, body) {
      super(body?.error?.message || `Request failed (${status})`);
      this.status = status;
      this.fields = body?.error?.fields || null;
    }
  }

  async function api(path, { method = 'GET', body } = {}) {
    const res = await fetch(`/api${path}`, {
      method,
      credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.status === 204) return null;
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const err = new ApiError(res.status, data);
      if (res.status === 401 && state.user && !path.startsWith('/auth/login')) {
        state.user = null;
        showAuth();
        toast(err.message, true);
      }
      throw err;
    }
    return data;
  }

  /* -------------------------------------------------------------- Helpers */
  function toast(message, isError = false) {
    const el = document.createElement('div');
    el.className = `toast${isError ? ' is-error' : ''}`;
    el.setAttribute('role', isError ? 'alert' : 'status');
    el.textContent = message;
    $('#toasts').append(el);
    setTimeout(() => el.remove(), isError ? 5000 : 2800);
  }

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? '' : v);
    }
    for (const c of [].concat(children)) if (c) node.append(c);
    return node;
  }

  const todayISO = () => new Date().toISOString().slice(0, 10);

  function formatDue(iso) {
    const today = todayISO();
    const diff = Math.round((Date.parse(iso) - Date.parse(today)) / 86400000);
    if (diff === 0) return 'Due today';
    if (diff === 1) return 'Due tomorrow';
    if (diff === -1) return 'Due yesterday';
    const label = new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
    return `Due ${label}`;
  }

  function setBusy(form, busy) {
    form.querySelectorAll('button').forEach((b) => { b.disabled = busy; });
  }

  function showFormErrors(form, err) {
    form.querySelectorAll('.field-error').forEach((n) => { n.textContent = ''; });
    form.querySelectorAll('[aria-invalid]').forEach((n) => n.removeAttribute('aria-invalid'));
    const banner = $('.form-error', form);

    if (err?.fields) {
      for (const [name, msg] of Object.entries(err.fields)) {
        const slot = form.querySelector(`.field-error[data-for="${name}"]`);
        const input = form.elements[name];
        if (slot) slot.textContent = msg;
        if (input) input.setAttribute('aria-invalid', 'true');
      }
      const first = form.querySelector('[aria-invalid="true"]');
      if (first) first.focus();
    }
    if (banner) {
      const hasFieldSlots = err?.fields && Object.keys(err.fields).every((n) => form.querySelector(`.field-error[data-for="${n}"]`));
      banner.hidden = !err || hasFieldSlots;
      banner.textContent = err ? err.message : '';
    } else if (err && !err.fields) {
      toast(err.message, true);
    }
  }

  const formData = (form) => Object.fromEntries(new FormData(form).entries());

  /* ---------------------------------------------------------------- Theme */
  function applyTheme(theme) {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
  }
  function currentTheme() {
    return document.documentElement.dataset.theme ||
      (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  }
  try { applyTheme(localStorage.getItem('pl-theme')); } catch { /* storage unavailable */ }

  /* ---------------------------------------------------------------- Views */
  function showAuth() {
    $('#boot').hidden = true;
    $('#app-view').hidden = true;
    $('#auth-view').hidden = false;
    document.title = 'Sign in – Punchlist';
  }

  async function showApp() {
    $('#boot').hidden = true;
    $('#auth-view').hidden = true;
    $('#app-view').hidden = false;
    $('#whoami').textContent = state.user.name;
    $('#whoami').title = state.user.email;
    document.title = 'Punchlist';
    await refresh();
  }

  function selectTab(which) {
    const login = which === 'login';
    $('#tab-login').setAttribute('aria-selected', String(login));
    $('#tab-register').setAttribute('aria-selected', String(!login));
    $('#login-form').hidden = !login;
    $('#register-form').hidden = login;
    $(login ? '#login-form input' : '#register-form input').focus();
  }

  /* ---------------------------------------------------------------- Data */
  async function refresh() {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(state.filters)) if (v) params.set(k, v);
    try {
      const [list, stats] = await Promise.all([
        api(`/tasks?${params}`),
        api('/tasks/stats'),
      ]);
      state.tasks = list.tasks;
      state.stats = stats.stats;
      render();
    } catch (err) {
      if (err.status !== 401) toast(err.message, true);
    }
  }

  /* -------------------------------------------------------------- Render */
  function renderSummary() {
    const s = state.stats;
    $('#done-count').textContent = s.done;
    $('#total-count').textContent = s.total;
    $('#stat-open').textContent = s.todo + s.in_progress;
    $('#stat-progress').textContent = s.in_progress;
    $('#stat-overdue').textContent = s.overdue;
    $('#stat-high').textContent = s.highOpen;
    $('#stat-overdue').parentElement.classList.toggle('has-value', s.overdue > 0);

    const strip = $('#punch-strip');
    strip.replaceChildren();
    const holes = Math.min(s.total, MAX_HOLES);
    const punched = s.total <= MAX_HOLES ? s.done : Math.round((s.done / s.total) * MAX_HOLES);
    for (let i = 0; i < holes; i++) {
      const isPunched = i < punched;
      const isNew = isPunched && state.justPunched && i === punched - 1;
      strip.append(el('span', { class: `hole${isPunched ? ' is-punched' : ''}${isNew ? ' just-punched' : ''}` }));
    }
    strip.setAttribute('aria-label', s.total
      ? `${s.done} of ${s.total} tasks done (${s.completionRate}%)`
      : 'No tasks yet');
  }

  function renderTask(t) {
    const done = t.status === 'done';
    const overdue = !done && t.dueDate && t.dueDate < todayISO();

    const tags = [];
    if (t.priority === 'high') tags.push(el('span', { class: 'tag tag-high', text: 'High priority' }));
    if (t.priority === 'low') tags.push(el('span', { class: 'tag', text: 'Low priority' }));
    if (t.status === 'in_progress') tags.push(el('span', { class: 'tag tag-progress', text: 'In progress' }));
    if (t.dueDate) {
      tags.push(el('span', {
        class: `tag${overdue ? ' tag-overdue' : ''}${done ? ' tag-done' : ''}`,
        text: overdue ? `Overdue, ${formatDue(t.dueDate).replace('Due ', 'was due ')}` : formatDue(t.dueDate),
      }));
    }

    const statusSelect = el('select', {
      'aria-label': `Status for ${t.title}`,
      onchange: (e) => updateTask(t.id, { status: e.target.value }),
    }, [
      el('option', { value: 'todo', text: 'To do', selected: t.status === 'todo' }),
      el('option', { value: 'in_progress', text: 'In progress', selected: t.status === 'in_progress' }),
      el('option', { value: 'done', text: 'Done', selected: done }),
    ]);

    return el('li', { class: `task${done ? ' is-done' : ''}`, 'data-id': t.id }, [
      el('button', {
        class: `punch-btn${state.justPunched === t.id ? ' just-punched' : ''}`,
        type: 'button',
        'aria-pressed': String(done),
        'aria-label': done ? `Mark "${t.title}" as not done` : `Mark "${t.title}" as done`,
        title: done ? 'Mark as not done' : 'Mark as done',
        onclick: () => updateTask(t.id, { status: done ? 'todo' : 'done' }),
      }),
      el('div', { class: 'task-main' }, [
        el('button', { class: 'task-title', type: 'button', text: t.title, onclick: () => openEditor(t.id) }),
        t.notes ? el('p', { class: 'task-notes', text: t.notes }) : null,
        tags.length ? el('div', { class: 'task-tags' }, tags) : null,
      ]),
      el('div', { class: 'task-side' }, [statusSelect]),
    ]);
  }

  function render() {
    renderSummary();
    const list = $('#task-list');
    list.replaceChildren(...state.tasks.map(renderTask));

    const filtered = Object.entries(state.filters).some(([k, v]) => k !== 'sort' && v);
    const empty = state.tasks.length === 0;
    $('#empty').hidden = !empty;
    if (empty) {
      $('#empty-title').textContent = filtered ? 'No tasks match these filters' : 'Nothing on the list';
      $('#empty-body').textContent = filtered
        ? 'Clear the search or pick a different status or priority.'
        : 'Add your first task with the form on this page.';
    }
    $('#list-meta').textContent = empty ? '' :
      `Showing ${state.tasks.length} ${state.tasks.length === 1 ? 'task' : 'tasks'}${filtered ? ' matching your filters' : ''}`;
    state.justPunched = null;
  }

  /* ------------------------------------------------------------- Actions */
  async function updateTask(id, patch) {
    try {
      const { task } = await api(`/tasks/${id}`, { method: 'PATCH', body: patch });
      if (patch.status === 'done') state.justPunched = task.id;
      await refresh();
      if (patch.status === 'done') toast('Punched off');
      else if (patch.status) toast(patch.status === 'todo' ? 'Moved back to to do' : 'Marked in progress');
      return task;
    } catch (err) {
      if (err.status !== 401) toast(err.message, true);
      throw err;
    }
  }

  function openEditor(id) {
    const task = state.tasks.find((t) => t.id === id);
    if (!task) return;
    state.editingId = id;
    const form = $('#edit-form');
    showFormErrors(form, null);
    form.elements.title.value = task.title;
    form.elements.notes.value = task.notes;
    form.elements.status.value = task.status;
    form.elements.priority.value = task.priority;
    form.elements.dueDate.value = task.dueDate || '';
    $('#edit-dialog').showModal();
    form.elements.title.focus();
  }

  function closeEditor() {
    $('#edit-dialog').close();
    state.editingId = null;
  }

  /* -------------------------------------------------------------- Wiring */
  function wire() {
    $('#tab-login').addEventListener('click', () => selectTab('login'));
    $('#tab-register').addEventListener('click', () => selectTab('register'));
    $('.tabs').addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        const next = $('#tab-login').getAttribute('aria-selected') === 'true' ? 'register' : 'login';
        selectTab(next);
        $(`#tab-${next}`).focus();
      }
    });

    async function login(credentials, form) {
      setBusy(form, true);
      try {
        const { user } = await api('/auth/login', { method: 'POST', body: credentials });
        state.user = user;
        form.reset();
        showFormErrors(form, null);
        await showApp();
        toast(`Signed in as ${user.name}`);
      } catch (err) {
        showFormErrors(form, err);
      } finally {
        setBusy(form, false);
      }
    }

    $('#login-form').addEventListener('submit', (e) => {
      e.preventDefault();
      login(formData(e.currentTarget), e.currentTarget);
    });
    $('#demo-login').addEventListener('click', () => login(DEMO, $('#login-form')));

    $('#register-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = e.currentTarget;
      setBusy(form, true);
      try {
        const { user } = await api('/auth/register', { method: 'POST', body: formData(form) });
        state.user = user;
        form.reset();
        showFormErrors(form, null);
        await showApp();
        toast('Account created');
      } catch (err) {
        showFormErrors(form, err);
      } finally {
        setBusy(form, false);
      }
    });

    $('#logout').addEventListener('click', async () => {
      await api('/auth/logout', { method: 'POST' }).catch(() => {});
      state.user = null;
      state.tasks = [];
      showAuth();
      selectTab('login');
      toast('Signed out');
    });

    $('#theme-toggle').addEventListener('click', () => {
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      try { localStorage.setItem('pl-theme', next); } catch { /* ignore */ }
    });

    $('#create-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = e.currentTarget;
      const data = formData(form);
      if (!data.dueDate) delete data.dueDate;
      setBusy(form, true);
      try {
        await api('/tasks', { method: 'POST', body: data });
        form.reset();
        showFormErrors(form, null);
        await refresh();
        toast('Task added');
        form.elements.title.focus();
      } catch (err) {
        showFormErrors(form, err);
      } finally {
        setBusy(form, false);
      }
    });

    let searchTimer;
    $('#filters').addEventListener('input', (e) => {
      const { name, value } = e.target;
      state.filters[name] = value.trim();
      clearTimeout(searchTimer);
      searchTimer = setTimeout(refresh, name === 'q' ? 250 : 0);
    });
    $('#filters').addEventListener('submit', (e) => e.preventDefault());

    $('#edit-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = e.currentTarget;
      const data = formData(form);
      data.dueDate = data.dueDate || null;
      setBusy(form, true);
      try {
        await api(`/tasks/${state.editingId}`, { method: 'PATCH', body: data });
        closeEditor();
        await refresh();
        toast('Changes saved');
      } catch (err) {
        showFormErrors(form, err);
      } finally {
        setBusy(form, false);
      }
    });
    $('#edit-cancel').addEventListener('click', closeEditor);
    $('#edit-delete').addEventListener('click', async () => {
      const task = state.tasks.find((t) => t.id === state.editingId);
      if (!task || !confirm(`Delete "${task.title}"? This can't be undone.`)) return;
      try {
        await api(`/tasks/${task.id}`, { method: 'DELETE' });
        closeEditor();
        await refresh();
        toast('Task deleted');
      } catch (err) {
        if (err.status !== 401) toast(err.message, true);
      }
    });
    $('#edit-dialog').addEventListener('close', () => { state.editingId = null; });
  }

  /* ---------------------------------------------------------------- Boot */
  async function boot() {
    wire();

    api('/health').then((h) => {
      if (h.storage === 'memory') {
        $('#env-note').textContent = 'This server keeps data in memory, so accounts and tasks reset when it restarts.';
      }
    }).catch(() => {});

    try {
      const { user } = await api('/auth/me');
      state.user = user;
      await showApp();
    } catch {
      showAuth();
    }
  }

  boot();
})();
