const DEMO_DEVICE_KEY = "lingxi-browser-device-id";

const els = {
  badge: document.querySelector("#demoServerBadge"),
  form: document.querySelector("#demoForm"),
  input: document.querySelector("#demoMessageInput"),
  send: document.querySelector("#demoSendButton"),
  cancel: document.querySelector("#demoCancelButton"),
  sample: document.querySelector("#sampleButton"),
  imageButton: document.querySelector("#demoImageButton"),
  imageInput: document.querySelector("#demoImageInput"),
  imagePreview: document.querySelector("#demoImagePreview"),
  imagePreviewImage: document.querySelector("#demoImagePreviewImage"),
  imagePreviewName: document.querySelector("#demoImagePreviewName"),
  removeImage: document.querySelector("#demoRemoveImageButton"),
  model: document.querySelector("#demoModelLabel"),
  response: document.querySelector("#demoResponse"),
  result: document.querySelector("#demoTaskResult"),
  taskTitle: document.querySelector("#demoTaskTitle"),
  taskStatus: document.querySelector("#demoTaskStatus"),
  taskMeta: document.querySelector("#demoTaskMeta"),
  taskChecklist: document.querySelector("#demoTaskChecklist"),
  confirmTask: document.querySelector("#demoConfirmTaskButton"),
  latency: document.querySelector("#demoLatency"),
  trace: document.querySelector("#demoTrace"),
  outputState: document.querySelector("#demoOutputState"),
  toast: document.querySelector("#demoToast"),
};

const state = {
  busy: false,
  image: null,
  deviceId: getDeviceId(),
  outputText: "",
  task: null,
  controller: null,
  timer: null,
  abortReason: null,
};
const taskStatusLabels = { pending: "待确认", confirmed: "已确认", completed: "已完成", cancelled: "已取消" };
const samplePrompt = "下周三18:30主楼302有未来实验室公开讲座，请整理成任务卡，并提前一小时提醒我报名。";
const DEMO_INTERACTION_TIMEOUT_MS = 45_000;

function getDeviceId() {
  let existing = null;
  try { existing = window.localStorage.getItem(DEMO_DEVICE_KEY); } catch (error) {}
  if (/^web-[A-Za-z0-9-]{8,60}$/.test(existing || "")) return existing;
  const random = window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  const id = `web-${random}`;
  try { window.localStorage.setItem(DEMO_DEVICE_KEY, id); } catch (error) {}
  return id;
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => els.toast.classList.remove("show"), 2600);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `请求失败：${response.status}`);
  return payload;
}

function setServerStatus(status, label) {
  els.badge.classList.remove("connected", "error");
  if (status) els.badge.classList.add(status);
  els.badge.querySelector("span").textContent = label;
}

function setStep(name, status = "active") {
  const order = ["recognize", "plan", "remember"];
  const current = order.indexOf(name);
  document.querySelectorAll(".demo-step").forEach((step) => {
    const index = order.indexOf(step.dataset.demoStep);
    step.classList.toggle("active", index === current);
    step.classList.toggle("done", current >= 0 && index < current);
  });
  if (status === "done") document.querySelector(`[data-demo-step="${name}"]`)?.classList.add("done");
}

function renderResponse(text = "") {
  if (!text) {
    els.response.innerHTML = '<div class="response-placeholder"><span class="placeholder-orb">灵</span><p>灵犀正在组织任务…<br /><em>先识别关键信息，再给出可执行下一步。</em></p></div>';
    return;
  }
  els.response.innerHTML = "";
  const label = document.createElement("span");
  label.className = "response-label";
  label.textContent = "灵犀建议";
  const body = document.createElement("p");
  body.textContent = text;
  els.response.append(label, body);
}

function showTaskResult(task, event = null) {
  if (!task) return;
  state.task = task;
  els.result.hidden = false;
  els.taskStatus.textContent = taskStatusLabels[task.status] || task.status;
  els.taskTitle.textContent = task.title;
  const formatTime = (value) => {
    const date = new Date(value || "");
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("zh-CN", {
      month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
    });
  };
  const reminderSource = task.reminder_source === "memory" ? " · 按记忆偏好" : "";
  const meta = [
    task.schedule_text,
    task.remind_at
      ? `提醒 ${formatTime(task.remind_at)}${reminderSource}`
      : "",
    task.location,
    task.source === "image" ? "图片识别" : "文字输入",
  ].filter(Boolean);
  els.taskMeta.textContent = meta.join(" · ") || task.summary || "任务已由服务器保存";
  els.taskChecklist.replaceChildren();
  (task.checklist || []).forEach((item) => {
    const row = document.createElement("li");
    row.textContent = item;
    els.taskChecklist.append(row);
  });
  els.taskChecklist.hidden = !els.taskChecklist.children.length;
  els.confirmTask.hidden = task.status !== "pending";
  els.confirmTask.disabled = false;
  els.latency.textContent = event?.latency_ms ? `${event.latency_ms} ms` : "已保存";
}

async function confirmCurrentTask() {
  if (!state.task || state.task.status !== "pending") return;
  els.confirmTask.disabled = true;
  try {
    const result = await fetchJson("/api/tasks/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: state.deviceId, task_id: state.task.id, status: "confirmed" }),
    });
    showTaskResult(result.task);
    showToast("任务已确认，可在控制台继续管理");
  } catch (error) {
    els.confirmTask.disabled = false;
    showToast(error.message);
  }
}

function clearImage() {
  state.image = null;
  els.imageInput.value = "";
  els.imagePreview.hidden = true;
  els.imagePreviewImage.removeAttribute("src");
  els.imagePreviewName.textContent = "";
}

function handleImage(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!/^image\/(jpeg|png|gif|webp)$/.test(file.type) || file.size > 8 * 1024 * 1024) {
    clearImage();
    showToast("请选择 8 MB 以内的 JPG、PNG、GIF 或 WebP 图片");
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    state.image = { dataUrl: String(reader.result || ""), name: file.name };
    els.imagePreviewImage.src = state.image.dataUrl;
    els.imagePreviewName.textContent = file.name;
    els.imagePreview.hidden = false;
  };
  reader.readAsDataURL(file);
}

function setBusy(busy) {
  state.busy = busy;
  els.send.disabled = busy;
  els.sample.disabled = busy;
  els.imageButton.disabled = busy;
  document.querySelectorAll(".demo-input-suggestions button").forEach((button) => { button.disabled = busy; });
  els.cancel.hidden = !state.controller;
}

function beginRequest() {
  const controller = new AbortController();
  state.controller = controller;
  state.abortReason = null;
  state.timer = window.setTimeout(() => {
    state.abortReason = "timeout";
    controller.abort("timeout");
  }, DEMO_INTERACTION_TIMEOUT_MS);
  return controller;
}

function finishRequest(controller) {
  if (state.timer) window.clearTimeout(state.timer);
  if (state.controller === controller) state.controller = null;
  state.timer = null;
}

function cancelRequest() {
  if (!state.controller) return;
  state.abortReason = "user";
  state.controller.abort("user");
}

async function runInteraction() {
  const input = els.input.value.trim();
  if ((!input && !state.image) || state.busy) return;
  const requestText = input || "请分析这张校园图片，并整理成一个可执行任务。";
  state.outputText = "";
  state.task = null;
  els.result.hidden = true;
  els.outputState.textContent = "RUNNING";
  els.trace.textContent = "任务已接收 · 正在生成执行计划";
  setStep("recognize");
  renderResponse();
  const controller = beginRequest();
  setBusy(true);
  try {
    const response = await fetch("/api/interactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: state.deviceId, text: requestText, mode: "assistant", offline: false, ...(state.image ? { image_data_url: state.image.dataUrl } : {}) }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.error || `请求失败：${response.status}`);
    }
    const reader = response.body?.getReader();
    if (!reader) throw new Error("浏览器不支持流式响应");
    const decoder = new TextDecoder();
    let buffer = "";
    let completed = null;
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines.filter(Boolean)) completed = handleEvent(JSON.parse(line), requestText) || completed;
      if (done) break;
    }
    if (buffer.trim()) completed = handleEvent(JSON.parse(buffer), requestText) || completed;
    if (completed && state.task) showTaskResult(state.task, completed);
  } catch (error) {
    if (controller.signal.aborted) {
      const timedOut = state.abortReason === "timeout";
      els.outputState.textContent = timedOut ? "TIMEOUT" : "CANCELLED";
      els.trace.textContent = timedOut ? "等待超时 · 已恢复可操作状态" : "已停止本次请求 · 可立即重试";
      renderResponse(state.outputText || (timedOut ? "等待超过 45 秒，已停止请求。请稍后重试。" : "已停止本次请求。你可以调整任务后重试。"));
      showToast(timedOut ? "等待超时，已恢复可操作状态" : "已停止本次请求");
    } else {
      els.outputState.textContent = "OFFLINE";
      els.trace.textContent = "链路异常 · 请进入控制台查看诊断";
      renderResponse(`暂时无法连接灵犀服务：${error.message}`);
      setServerStatus("error", "服务未连接");
    }
  } finally {
    finishRequest(controller);
    setBusy(false);
    clearImage();
    if (els.outputState.textContent === "RUNNING") els.outputState.textContent = "DONE";
  }
}

function handleEvent(event, input) {
  if (event.type === "state") {
    els.outputState.textContent = String(event.state || "RUNNING").toUpperCase();
    if (event.state === "thinking") { setStep("plan"); els.trace.textContent = event.label || "正在生成执行计划"; }
    if (event.state === "speaking") { setStep("remember"); els.trace.textContent = event.label || "正在准备反馈记忆"; }
    return null;
  }
  if (event.type === "delta") {
    state.outputText += event.text || "";
    renderResponse(state.outputText);
    return null;
  }
  if (event.type === "plan") {
    setStep("plan");
    els.trace.textContent = (event.steps || []).join(" → ") || "执行计划已生成";
    return null;
  }
  if (event.type === "tool") {
    els.trace.textContent = event.name === "task.create"
      ? `task.create · 任务已持久化 · ${event.latency_ms || 0} ms`
      : `${event.name || "agent.tool"} · ${event.hits || 0} 条记忆命中`;
    return null;
  }
  if (event.type === "task") {
    state.task = event.task;
    showTaskResult(event.task);
    els.trace.textContent = `task.create · #${event.task.id} · 等待用户确认`;
    return null;
  }
  if (event.type === "memory_recall") {
    setStep("remember");
    els.trace.textContent = `反馈记忆检索 · ${event.count || 0} 条命中`;
    return null;
  }
  if (event.type === "provider") {
    els.model.textContent = event.model || "Step 3.7 Flash";
    return null;
  }
  if (event.type === "complete") {
    setStep("remember", "done");
    els.trace.textContent = `任务完成 · ${event.provider || "灵犀"} · ${event.latency_ms || "—"} ms`;
    els.outputState.textContent = "DONE";
    return event;
  }
  return null;
}

async function loadStatus() {
  try {
    const [health, capabilities] = await Promise.all([fetchJson("/api/health"), fetchJson("/api/capabilities")]);
    setServerStatus("connected", capabilities.enabled ? "Step 3.7 已连接" : "灵犀服务已连接");
    els.model.textContent = capabilities.models?.chat || "Step 3.7 Flash";
  } catch (error) {
    setServerStatus("error", "服务未连接");
    els.model.textContent = "本地兜底模式";
  }
}

els.form.addEventListener("submit", (event) => { event.preventDefault(); runInteraction(); });
els.sample.addEventListener("click", () => { els.input.value = samplePrompt; els.input.focus(); runInteraction(); });
els.imageButton.addEventListener("click", () => els.imageInput.click());
els.imageInput.addEventListener("change", handleImage);
els.removeImage.addEventListener("click", clearImage);
els.confirmTask.addEventListener("click", confirmCurrentTask);
els.cancel.addEventListener("click", cancelRequest);
document.querySelectorAll("[data-demo-prompt]").forEach((button) => button.addEventListener("click", () => { els.input.value = button.dataset.demoPrompt || ""; els.input.focus(); }));
loadStatus();
