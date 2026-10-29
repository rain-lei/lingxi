"use strict";

// Learning state stays in the local service, isolated by the selected device.
// User-written strings are always inserted with textContent, never HTML.
(() => {
  const byId = (id) => document.getElementById(id);
  const bridge = () => window.LingXiCompanion;
  const ui = Object.fromEntries([
    "todayTasks", "taskPendingCount", "todayStudyMinutes", "weekStudyMinutes", "completedTaskCount",
    "nextReminderText", "learningGoalText", "greetingName", "homeWeeklyChart", "studyWeeklyChart",
    "recentStudyList", "reminderList", "studyTaskList", "studyRecordList", "learningError",
    "learningProfileForm", "profileNickname", "profileFocusMinutes", "profileLearningGoal", "profileInterests",
    "profileReplyStyle", "profileEncouragement", "profileReminderSound", "profileSaveStatus", "saveLearningProfile",
    "profileError", "notificationPermission", "notificationStatus", "taskDialog", "taskForm", "taskDialogTitle",
    "taskId", "taskTitle", "taskSubject", "taskPriority", "taskDueAt", "taskRemindAt", "taskFormError", "saveTask",
    "recordDialog", "recordForm", "recordSubject", "recordMinutes", "recordNote", "recordFormError", "saveRecord",
    "focusSubject", "focusMinutes", "startFocus", "endFocus", "focusHint"
  ].map((id) => [id, byId(id)]));
  let currentDevice = "", revision = 0, activeRequest = null, snapshot = null;
  let taskFilter = "pending", profileDirty = false, profileSaving = false;
  let notified = new Set(), focusSignature = "", notificationEnabled = false, soundContext;

  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = String(content);
    return element;
  }
  function text(element, value) { if (element) element.textContent = String(value); }
  function error(element, message = "") { if (element) { text(element, message); element.hidden = !message; } }
  function message(value) { bridge()?.toast(value); }
  function current() { return bridge()?.getDeviceId() || ""; }
  function isReady() { return Boolean(bridge()?.getReady()); }
  function endpoint(path) { return `/api/companion/learning${path}`; }
  const dateFormatter = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
  const dayFormatter = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "numeric", day: "numeric" });
  function formatDate(value) {
    if (!value) return "";
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? dateFormatter.format(date) : "";
  }
  function localDateTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return "";
    const pad = (part) => String(part).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }
  function isoDate(value) {
    if (!value) return null;
    const parsed = new Date(value);
    if (!Number.isFinite(parsed.getTime())) throw new Error("请填写有效的日期和时间。");
    return parsed.toISOString();
  }
  function emptyState(title, description, action, label) {
    const wrap = node("div", "task-empty");
    wrap.append(node("span", "empty-state-icon", "✦"), node("strong", "", title), node("p", "", description));
    if (action) {
      const button = node("button", "text-button", label); button.type = "button";
      button.addEventListener("click", action); wrap.append(button);
    }
    return wrap;
  }
  function notificationKey() { return `lingxi-notifications:${currentDevice}`; }
  function readNotificationPreference() {
    try { notificationEnabled = localStorage.getItem(notificationKey()) === "true"; } catch { notificationEnabled = false; }
    updateNotificationStatus();
  }
  function updateNotificationStatus() {
    if (!("Notification" in window)) {
      text(ui.notificationStatus, "当前浏览器不支持系统通知，网页内提醒仍可使用。");
      if (ui.notificationPermission) ui.notificationPermission.disabled = true;
      return;
    }
    if (Notification.permission === "denied") {
      text(ui.notificationStatus, "系统通知已被浏览器关闭。需要时可在地址栏权限设置中开启。");
      text(ui.notificationPermission, "通知权限已关闭");
      if (ui.notificationPermission) ui.notificationPermission.disabled = true;
      return;
    }
    const enabled = notificationEnabled && Notification.permission === "granted";
    text(ui.notificationStatus, enabled ? "已开启此设备的系统通知。请保持网页和本机服务运行。" : "网页提醒已可用；系统通知由你决定是否开启。");
    text(ui.notificationPermission, enabled ? "关闭系统通知" : "开启系统通知");
  }
  function warmSound() {
    if (!snapshot?.profile?.reminder_sound) return;
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) { soundContext ||= new AudioContext(); soundContext.resume().catch(() => {}); }
    } catch { /* Browser sound permission is optional. */ }
  }
  function playReminderSound() {
    if (!snapshot?.profile?.reminder_sound || !soundContext || soundContext.state !== "running") return;
    try {
      const oscillator = soundContext.createOscillator(), gain = soundContext.createGain();
      oscillator.type = "sine"; oscillator.frequency.value = 660;
      gain.gain.setValueAtTime(0, soundContext.currentTime);
      gain.gain.linearRampToValueAtTime(.07, soundContext.currentTime + .025);
      gain.gain.exponentialRampToValueAtTime(.001, soundContext.currentTime + .5);
      oscillator.connect(gain); gain.connect(soundContext.destination);
      oscillator.start(); oscillator.stop(soundContext.currentTime + .52);
      oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
    } catch { /* The visible reminder remains available if sound is unavailable. */ }
  }
  function notify(reminders) {
    for (const item of reminders) {
      const key = `${item.id}:${item.remind_at}`;
      if (notified.has(key)) continue;
      notified.add(key);
      message(`到提醒时间了：${item.title}`);
      playReminderSound();
      if (notificationEnabled && "Notification" in window && Notification.permission === "granted") {
        try {
          const notice = new Notification("灵犀 · 一件约好的小事", { body: item.title, tag: `lingxi-${currentDevice}-${key}`, icon: "/favicon.svg" });
          notice.onclick = () => { window.focus(); window.LingXiNavigate?.("study"); notice.close(); };
        } catch { /* Some mobile browsers only support service-worker notifications. */ }
      }
    }
  }
  function renderReminders(items) {
    if (ui.reminderList) {
      ui.reminderList.replaceChildren();
      ui.reminderList.hidden = items.length === 0;
      for (const item of items) {
        const card = node("div", "reminder-card"); card.setAttribute("role", "status");
        card.append(node("span", "reminder-icon", "◷"));
        const copy = node("div", "reminder-copy"); copy.append(node("strong", "", item.title), node("small", "", `约好的时间 · ${formatDate(item.remind_at)}`));
        const acknowledge = node("button", "reminder-dismiss", "知道啦"); acknowledge.type = "button";
        acknowledge.setAttribute("aria-label", `知道啦：${item.title}`);
        acknowledge.addEventListener("click", async () => {
          acknowledge.disabled = true;
          try { await mutate("/reminder/ack", { id: item.id }); }
          catch (problem) { message(problem.message); acknowledge.disabled = false; }
        });
        card.append(copy, acknowledge); ui.reminderList.append(card);
      }
    }
    notify(items);
  }
  function taskMeta(task) {
    const meta = node("div", "task-meta");
    if (task.confirmation_required) meta.append(node('span', 'task-pill', '待确认 · 提醒未启用'));
    if (task.subject) meta.append(node("span", "task-subject", task.subject));
    if (task.priority === "high") meta.append(node("span", "task-pill is-high", "优先"));
    if (task.priority === "low") meta.append(node("span", "task-pill is-low", "慢慢来"));
    if (task.due_at) {
      const overdue = task.status !== "completed" && new Date(task.due_at).getTime() < Date.now();
      meta.append(node("span", overdue ? "task-due is-overdue" : "task-due", `${overdue ? "已到期 · " : ""}${formatDate(task.due_at)}`));
    }
    if (task.remind_at && task.status !== "completed") meta.append(node("span", "task-reminder", `◷ ${formatDate(task.remind_at)}`));
    return meta;
  }
  function taskRow(task, compact = false) {
    const row = node("article", `study-task${compact ? " is-compact" : ""}${task.status === "completed" ? " is-completed" : ""}`);
    const check = node("button", "task-check", task.status === "completed" ? "✓" : "");
    check.type = "button"; check.setAttribute("aria-label", `${task.status === "completed" ? "重新打开" : "完成"}计划：${task.title}`);
    check.setAttribute("aria-pressed", String(task.status === "completed"));
    check.addEventListener("click", async () => {
      check.disabled = true;
      try { await mutate("/task/update", { id: task.id, status: task.status === "completed" ? "pending" : "completed" }); }
      catch (problem) { message(problem.message); check.disabled = false; }
    });
    const copy = node("div", "task-copy"); copy.append(node("strong", "", task.title), taskMeta(task));
    row.append(check, copy);
    if (task.confirmation_required) {
      const confirm = node('button', 'text-button', '确认任务');
      confirm.type = 'button';
      confirm.onclick = async () => {
        confirm.disabled = true;
        try { await mutate('/task/update', { id: task.id, status: 'pending' }); }
        catch (problem) { message(problem.message); confirm.disabled = false; }
      };
      row.append(confirm);
    }
    if (!compact) {
      const actions = node("div", "task-actions");
      const edit = node("button", "text-button", "编辑"); edit.type = "button"; edit.addEventListener("click", () => openTask(task));
      const remove = node("button", "text-button delete-button", "删除"); remove.type = "button";
      remove.setAttribute("aria-label", `删除计划：${task.title}`);
      remove.addEventListener("click", async () => {
        remove.disabled = true;
        try { await mutate("/task/delete", { id: task.id }); message("这件计划已移除。"); }
        catch (problem) { message(problem.message); remove.disabled = false; }
      });
      actions.append(edit, remove); row.append(actions);
    }
    return row;
  }
  function sortedTasks(items) {
    const priority = { high: 0, normal: 1, low: 2 };
    return [...items].sort((a, b) => {
      const aTime = a.due_at ? new Date(a.due_at).getTime() : Infinity;
      const bTime = b.due_at ? new Date(b.due_at).getTime() : Infinity;
      return (aTime - bTime) || (priority[a.priority] - priority[b.priority]) || b.id - a.id;
    });
  }
  function renderTasks(items) {
    const pending = sortedTasks(items.filter((item) => item.status === "pending"));
    document.querySelectorAll("[data-task-count]").forEach((element) => { element.textContent = String(items.filter((item) => item.status === element.dataset.taskCount).length); });
    document.querySelectorAll("[data-task-filter]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.taskFilter === taskFilter)));
    if (ui.todayTasks) {
      ui.todayTasks.replaceChildren();
      for (const item of pending.slice(0, 4)) ui.todayTasks.append(taskRow(item, true));
      if (!pending.length) ui.todayTasks.append(emptyState("给今天留一个小目标", "不用排满，从一件愿意开始的事就好。", () => openTask(), "＋ 写下第一件事"));
    }
    if (ui.studyTaskList) {
      ui.studyTaskList.replaceChildren();
      const selected = taskFilter === "all" ? sortedTasks(items) : taskFilter === "pending" ? pending : items.filter((item) => item.status === "completed").sort((a, b) => b.id - a.id);
      for (const item of selected) ui.studyTaskList.append(taskRow(item));
      if (!selected.length) ui.studyTaskList.append(emptyState(taskFilter === "completed" ? "第一份小成就，等你点亮" : "把脑海里的计划，放到这里", taskFilter === "completed" ? "完成计划后，在前面的圆圈打个勾，就会留下记录。" : "清楚地写下一件事，比一口气想完所有事情更容易开始。", taskFilter === "completed" ? null : () => openTask(), "＋ 新建学习计划"));
    }
    const upcoming = items.filter((item) => item.status === "pending" && item.remind_at).sort((a, b) => Date.parse(a.remind_at) - Date.parse(b.remind_at))[0];
    text(ui.nextReminderText, upcoming ? `${Date.parse(upcoming.remind_at) <= Date.now() ? "待查看提醒" : "下次提醒"} · ${formatDate(upcoming.remind_at)} ${upcoming.title}` : "还没有约好的提醒，给计划加一个时间吧。");
  }
  function renderChart(element, days) {
    if (!element) return;
    element.replaceChildren();
    const maximum = Math.max(30, ...days.map((day) => Number(day.minutes) || 0));
    element.setAttribute("aria-label", `最近七天学习时长：${days.map((day) => `${day.date} ${day.minutes}分钟`).join("，")}`);
    for (const day of days) {
      const wrapper = node("div", "chart-day");
      const value = Math.max(0, Number(day.minutes) || 0);
      wrapper.append(node("span", "chart-value", value));
      const track = node("div", "chart-track"), bar = node("span", `chart-bar${value ? "" : " is-empty"}`);
      bar.style.height = value ? `${Math.max(7, value / maximum * 100)}%` : "3px";
      track.append(bar); wrapper.append(track);
      const parts = String(day.date || "").split("-");
      wrapper.append(node("span", "chart-label", parts.length === 3 ? `${Number(parts[1])}/${Number(parts[2])}` : day.date));
      element.append(wrapper);
    }
  }
  function recordRow(record, compact = false) {
    const row = node("article", `study-record${compact ? " is-compact" : ""}`);
    row.append(node("span", "record-icon", record.source === "focus" ? "◷" : "✎"));
    const copy = node("div", "record-copy"); copy.append(node("strong", "", record.subject || "一段认真学习"));
    const date = new Date(record.created_at);
    const label = Number.isFinite(date.getTime()) ? dayFormatter.format(date) : "";
    copy.append(node("span", "record-meta", `${record.duration_minutes} 分钟 · ${label}${record.source === "focus" ? " · 专注计时" : " · 手动记录"}`));
    if (!compact && record.note) copy.append(node("p", "record-note", record.note));
    row.append(copy);
    if (!compact) {
      const remove = node("button", "text-button delete-button", "删除"); remove.type = "button";
      remove.setAttribute("aria-label", `删除学习记录：${record.subject}`);
      remove.addEventListener("click", async () => {
        remove.disabled = true;
        try { await mutate("/record/delete", { id: record.id }); message("学习记录已删除，统计已更新。"); }
        catch (problem) { message(problem.message); remove.disabled = false; }
      });
      row.append(remove);
    }
    return row;
  }
  function renderRecords(items) {
    const records = [...items].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id);
    for (const [element, compact] of [[ui.studyRecordList, false], [ui.recentStudyList, true]]) {
      if (!element) continue;
      element.replaceChildren();
      for (const record of records.slice(0, compact ? 3 : 100)) element.append(recordRow(record, compact));
      if (!records.length) element.append(emptyState(compact ? "第一段足迹，从今天开始" : "那些认真投入的时间，会在这里留下来", compact ? "开启一次专注，或记录刚刚学会的东西。" : "完成专注计时会自动记录，也可以补记一次阅读、练习或项目工作。", () => openRecord(), "＋ 留下学习记录"));
    }
  }
  function ensureOption(select, value, suffix = " 分钟") {
    if (!select) return;
    if (![...select.options].some((option) => option.value === String(value))) select.add(new Option(`${value}${suffix}`, String(value)));
    select.value = String(value);
  }
  function renderProfile(profile) {
    text(ui.greetingName, profile.nickname || "朋友");
    text(ui.learningGoalText, profile.learning_goal || "从一件小事开始，今天也有自己的节奏。");
    if (!profileDirty && !profileSaving) {
      for (const [id, key] of [["profileNickname", "nickname"], ["profileLearningGoal", "learning_goal"], ["profileInterests", "interests"], ["profileReplyStyle", "reply_style"], ["profileEncouragement", "encouragement"]]) if (ui[id]) ui[id].value = profile[key] || "";
      ensureOption(ui.profileFocusMinutes, profile.focus_minutes || 25);
      if (ui.profileReminderSound) ui.profileReminderSound.checked = Boolean(profile.reminder_sound);
      text(ui.profileSaveStatus, "已保存，之后的聊天会参考这些偏好。");
    }
    if (ui.focusMinutes && !snapshot?.focus?.active && ui.focusMinutes.dataset.userChanged !== "true") ensureOption(ui.focusMinutes, profile.focus_minutes || 25);
  }
  function render(data) {
    snapshot = data;
    const stats = data.stats || {};
    text(ui.taskPendingCount, stats.pending_tasks || 0);
    text(ui.todayStudyMinutes, stats.today_minutes || 0);
    text(ui.weekStudyMinutes, stats.week_minutes || 0);
    text(ui.completedTaskCount, stats.completed_tasks || 0);
    document.querySelectorAll("[data-learning-stat]").forEach((element) => { element.textContent = String(stats[element.dataset.learningStat] || 0); });
    renderTasks(Array.isArray(data.tasks) ? data.tasks : []);
    renderRecords(Array.isArray(data.records) ? data.records : []);
    renderChart(ui.homeWeeklyChart, stats.week_days || []);
    renderChart(ui.studyWeeklyChart, stats.week_days || []);
    renderProfile(data.profile || {});
    renderReminders(Array.isArray(data.reminders) ? data.reminders : []);
    if (ui.focusMinutes) {
      ui.focusMinutes.disabled = Boolean(data.focus?.active);
      if (data.focus?.active) ensureOption(ui.focusMinutes, Math.round(data.focus.duration_seconds / 60));
    }
    if (ui.focusSubject) ui.focusSubject.disabled = Boolean(data.focus?.active);
    if (data.focus?.active && ui.focusSubject && document.activeElement !== ui.focusSubject) ui.focusSubject.value = data.focus.subject || data.focus.topic || "";
    error(ui.learningError);
    window.dispatchEvent(new CustomEvent("lingxi:learning", { detail: { deviceId: currentDevice, data } }));
  }
  function resetDevice() {
    if (currentDevice === current()) return false;
    currentDevice = current(); revision++; activeRequest = null; snapshot = null; notified = new Set(); profileDirty = false; focusSignature = "";
    ui.taskDialog?.close(); ui.recordDialog?.close();
    ui.learningProfileForm?.reset();
    text(ui.greetingName, "朋友");
    text(ui.learningGoalText, "正在取来属于你的学习目标…");
    text(ui.nextReminderText, "正在同步提醒…");
    for (const element of [ui.taskPendingCount, ui.todayStudyMinutes, ui.weekStudyMinutes, ui.completedTaskCount]) text(element, "—");
    document.querySelectorAll("[data-learning-stat],[data-task-count]").forEach((element) => { element.textContent = "—"; });
    for (const element of [ui.studyRecordList, ui.recentStudyList]) if (element) element.replaceChildren(node("p", "loading-state", "正在取来你的学习足迹…"));
    ui.homeWeeklyChart?.replaceChildren(); ui.studyWeeklyChart?.replaceChildren();
    if (ui.reminderList) { ui.reminderList.replaceChildren(); ui.reminderList.hidden = true; }
    if (ui.focusSubject) ui.focusSubject.value = "";
    if (ui.focusSubject) ui.focusSubject.disabled = false;
    if (ui.focusMinutes) ui.focusMinutes.disabled = false;
    text(ui.profileSaveStatus, "正在读取你的偏好…");
    if (ui.todayTasks) ui.todayTasks.replaceChildren(node("p", "loading-state", "正在取来你的计划…"));
    if (ui.studyTaskList) ui.studyTaskList.replaceChildren(node("p", "loading-state", "正在读取学习计划…"));
    if (ui.focusMinutes) delete ui.focusMinutes.dataset.userChanged;
    readNotificationPreference();
    return true;
  }
  async function refresh() {
    if (!isReady()) return;
    resetDevice();
    if (activeRequest) return activeRequest;
    const device = currentDevice, ticket = revision;
    const request = bridge().getJSON(`${endpoint("")}?device_id=${encodeURIComponent(device)}`).then((data) => {
      if (device !== current() || ticket !== revision) return;
      render(data);
    }).catch((problem) => {
      if (device !== current() || ticket !== revision) return;
      error(ui.learningError, problem.message);
      text(ui.profileSaveStatus, "暂未同步，请确认本机服务运行后重试。");
      if (!snapshot && ui.todayTasks) ui.todayTasks.replaceChildren(emptyState("学习计划暂未连接", "已保存的数据仍留在本机。服务恢复后会自动重新读取。", () => refresh(), "重新读取 ↗"));
    }).finally(() => { if (activeRequest === request) activeRequest = null; });
    activeRequest = request;
    return request;
  }
  async function mutate(path, payload) {
    if (!isReady()) throw new Error("请先等待本机服务连接完成。");
    resetDevice();
    const device = currentDevice, ticket = ++revision;
    const response = await bridge().postJSON(endpoint(path), { device_id: device, ...payload });
    const data = await response.json();
    if (device === current() && ticket === revision) render(data);
    return data;
  }
  function openTask(task = null) {
    if (!ui.taskDialog || !ui.taskForm) return;
    if (!isReady()) return message("请先等待本机服务连接完成。");
    ui.taskForm.reset(); error(ui.taskFormError);
    ui.taskId.value = task?.id || ""; ui.taskTitle.value = task?.title || ""; ui.taskSubject.value = task?.subject || "";
    ui.taskPriority.value = task?.priority || "normal"; ui.taskDueAt.value = localDateTime(task?.due_at); ui.taskRemindAt.value = localDateTime(task?.remind_at);
    text(ui.taskDialogTitle, task ? "调整这件小计划" : "记下一件要做的事");
    ui.taskDialog.showModal(); ui.taskTitle.focus(); warmSound();
  }
  function openRecord() {
    if (!ui.recordDialog || !ui.recordForm) return;
    if (!isReady()) return message("请先等待本机服务连接完成。");
    ui.recordForm.reset(); error(ui.recordFormError);
    if (ui.recordMinutes) ui.recordMinutes.value = snapshot?.profile?.focus_minutes || 25;
    ui.recordDialog.showModal(); ui.recordSubject.focus();
  }
  document.querySelectorAll("[data-open-task],[data-action=new-task]").forEach((button) => button.addEventListener("click", () => openTask()));
  document.querySelectorAll("[data-open-record],[data-action=new-record]").forEach((button) => button.addEventListener("click", openRecord));
  document.querySelectorAll("[data-close-task]").forEach((button) => button.addEventListener("click", () => ui.taskDialog?.close()));
  document.querySelectorAll("[data-close-record]").forEach((button) => button.addEventListener("click", () => ui.recordDialog?.close()));
  document.querySelectorAll("[data-task-filter]").forEach((button) => button.addEventListener("click", () => { taskFilter = button.dataset.taskFilter; if (snapshot) renderTasks(snapshot.tasks || []); }));
  ui.taskForm?.addEventListener("submit", async (event) => {
    event.preventDefault(); if (ui.saveTask.disabled) return;
    ui.saveTask.disabled = true; error(ui.taskFormError);
    const device = current();
    try {
      const title = ui.taskTitle.value.trim();
      if (!title) throw new Error("先写下这件事的内容吧。");
      const payload = { title, subject: ui.taskSubject.value.trim(), priority: ui.taskPriority.value, due_at: isoDate(ui.taskDueAt.value), remind_at: isoDate(ui.taskRemindAt.value) };
      const id = Number(ui.taskId.value);
      if (id) payload.id = id;
      await mutate(id ? "/task/update" : "/task/create", payload);
      if (device === current()) { ui.taskDialog.close(); message(id ? "计划已更新。" : "记下了，一件一件来就好。"); }
    } catch (problem) { if (device === current()) error(ui.taskFormError, problem.message); }
    finally { ui.saveTask.disabled = false; }
  });
  ui.recordForm?.addEventListener("submit", async (event) => {
    event.preventDefault(); if (ui.saveRecord.disabled) return;
    ui.saveRecord.disabled = true; error(ui.recordFormError); const device = current();
    try {
      const subject = ui.recordSubject.value.trim(), minutes = Number(ui.recordMinutes.value);
      if (!subject) throw new Error("给这段学习起个名字吧。");
      if (!Number.isInteger(minutes) || minutes < 1 || minutes > 720) throw new Error("学习时长请填写 1–720 之间的整数分钟。");
      await mutate("/record/create", { subject, duration_minutes: minutes, note: ui.recordNote.value.trim() });
      if (device === current()) { ui.recordDialog.close(); message("这段认真投入的时间，已经记下了。"); }
    } catch (problem) { if (device === current()) error(ui.recordFormError, problem.message); }
    finally { ui.saveRecord.disabled = false; }
  });
  ui.learningProfileForm?.addEventListener("input", () => { profileDirty = true; text(ui.profileSaveStatus, "有新的偏好，记得保存。"); });
  ui.learningProfileForm?.addEventListener("change", () => { profileDirty = true; text(ui.profileSaveStatus, "有新的偏好，记得保存。"); });
  ui.learningProfileForm?.addEventListener("submit", async (event) => {
    event.preventDefault(); if (profileSaving) return;
    profileSaving = true; ui.saveLearningProfile.disabled = true; error(ui.profileError); text(ui.profileSaveStatus, "正在认真记住你的偏好…");
    const profileControls = [...ui.learningProfileForm.querySelectorAll("input,select,textarea")];
    profileControls.forEach((control) => { control.disabled = true; });
    const device = current();
    try {
      const profile = { nickname: ui.profileNickname.value.trim(), learning_goal: ui.profileLearningGoal.value.trim(), interests: ui.profileInterests.value.trim(), reply_style: ui.profileReplyStyle.value, encouragement: ui.profileEncouragement.value, focus_minutes: Number(ui.profileFocusMinutes.value), reminder_sound: ui.profileReminderSound.checked };
      await mutate("/profile", { profile });
      if (device === current()) { profileDirty = false; text(ui.profileSaveStatus, "已保存，之后的聊天会参考这些偏好。"); if (ui.focusMinutes) { delete ui.focusMinutes.dataset.userChanged; if (!snapshot?.focus?.active) ensureOption(ui.focusMinutes, profile.focus_minutes); } message("偏好已保存，下一次对话就会用上。"); warmSound(); }
    } catch (problem) { if (device === current()) { error(ui.profileError, problem.message); text(ui.profileSaveStatus, "还没有保存，请重试。"); } }
    finally { profileSaving = false; ui.saveLearningProfile.disabled = false; profileControls.forEach((control) => { control.disabled = false; }); }
  });
  ui.notificationPermission?.addEventListener("click", async () => {
    if (!("Notification" in window)) return;
    warmSound();
    if (notificationEnabled && Notification.permission === "granted") notificationEnabled = false;
    else {
      const permission = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
      notificationEnabled = permission === "granted";
    }
    try { localStorage.setItem(notificationKey(), String(notificationEnabled)); } catch { /* This page can still show reminders. */ }
    updateNotificationStatus();
  });
  ui.focusMinutes?.addEventListener("change", () => { ui.focusMinutes.dataset.userChanged = "true"; });
  ui.startFocus?.addEventListener("click", async () => {
    if (ui.startFocus.disabled) return;
    const device = current();
    ui.startFocus.disabled = true;
    try {
      const data = await mutate("/focus/start", { subject: ui.focusSubject?.value.trim() || "一段专注学习", minutes: Number(ui.focusMinutes?.value || snapshot?.profile?.focus_minutes || 25) });
      if (device !== current()) return;
      bridge()?.applyExperience(data); await bridge()?.reloadExperience();
      if (device === current()) { message(data.action?.message || "专注开始了，我陪你把这一小步走完。"); warmSound(); }
    } catch (problem) { if (device === current()) message(problem.message); }
    finally { ui.startFocus.disabled = false; }
  });
  ui.endFocus?.addEventListener("click", async () => {
    if (ui.endFocus.disabled) return;
    const device = current();
    ui.endFocus.disabled = true;
    try { const data = await mutate("/focus/stop", {}); if (device !== current()) return; bridge()?.applyExperience(data); await bridge()?.reloadExperience(); if (device === current()) message(data.action?.message || "这段专注结束了，学习记录已更新。"); }
    catch (problem) { if (device === current()) message(problem.message); }
    finally { ui.endFocus.disabled = false; }
  });
  window.addEventListener("lingxi:ready", refresh);
  window.addEventListener("lingxi:device-changing", resetDevice);
  window.addEventListener("lingxi:refresh-learning", refresh);
  let syncTimer;
  window.addEventListener('lingxi:data-changed', () => {
    clearTimeout(syncTimer);
    syncTimer = setTimeout(refresh, 120);
  });
  window.addEventListener("lingxi:experience", (event) => {
    const focus = event.detail?.focus || event.detail?.experience?.focus;
    const signature = focus ? `${focus.active}:${focus.started_at}:${focus.ends_at}` : "none";
    if (signature !== focusSignature) { focusSignature = signature; refresh(); }
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  document.addEventListener("pointerdown", warmSound, { once: true });
  setInterval(() => { if (!document.hidden || notificationEnabled) refresh(); }, 10000);
  window.addEventListener("pagehide", () => { soundContext?.close().catch(() => {}); });
  updateNotificationStatus();
  if (isReady()) refresh();
})();
