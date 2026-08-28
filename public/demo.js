const DEMO_DEVICE_KEY = "lingxi-browser-device-id";

const els = {
  badge: document.querySelector("#demoServerBadge"),
  form: document.querySelector("#demoForm"),
  input: document.querySelector("#demoMessageInput"),
  send: document.querySelector("#demoSendButton"),
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
  latency: document.querySelector("#demoLatency"),
  trace: document.querySelector("#demoTrace"),
  outputState: document.querySelector("#demoOutputState"),
  toast: document.querySelector("#demoToast"),
};

const state = { busy: false, image: null, deviceId: getDeviceId(), outputText: "" };
const samplePrompt = "请把这张校园活动海报整理成任务卡：告诉我时间、地点，并提前一小时提醒。";

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

function inferTitle(input, output) {
  if (/海报|讲座|活动|报名/.test(input)) return "校园活动 · 已整理为待确认任务";
  if (/复习|学习|作业|计划/.test(input)) return "学习计划 · 今晚两小时";
  if (/翻译|通知|英文|日文/.test(input)) return "校园通知 · 重点已提取";
  return (output || input).split(/[。！？\n]/)[0].slice(0, 28) || "灵犀任务 · 待确认";
}

function showTaskResult(input, output, event) {
  els.result.hidden = false;
  els.taskStatus.textContent = "待确认";
  els.taskTitle.textContent = inferTitle(input, output);
  els.taskMeta.textContent = state.image ? "图片已分析 · 可前往控制台继续编辑提醒和清单" : "任务已生成 · 可前往控制台查看完整执行链路";
  els.latency.textContent = event?.latency_ms ? `${event.latency_ms} ms` : "已完成";
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
}

async function runInteraction() {
  const input = els.input.value.trim();
  if ((!input && !state.image) || state.busy) return;
  const requestText = input || "请分析这张校园图片，并整理成一个可执行任务。";
  setBusy(true);
  state.outputText = "";
  els.result.hidden = true;
  els.outputState.textContent = "RUNNING";
  els.trace.textContent = "任务已接收 · 正在生成执行计划";
  setStep("recognize");
  renderResponse();
  try {
    const response = await fetch("/api/interactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: state.deviceId, text: requestText, mode: "assistant", offline: false, ...(state.image ? { image_data_url: state.image.dataUrl } : {}) }),
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
    if (completed) showTaskResult(requestText, state.outputText, completed);
  } catch (error) {
    els.outputState.textContent = "OFFLINE";
    els.trace.textContent = "链路异常 · 请进入控制台查看诊断";
    renderResponse(`暂时无法连接灵犀服务：${error.message}`);
    setServerStatus("error", "服务未连接");
  } finally {
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
    els.trace.textContent = `${event.name || "agent.tool"} · ${event.hits || 0} 条记忆命中`;
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
document.querySelectorAll("[data-demo-prompt]").forEach((button) => button.addEventListener("click", () => { els.input.value = button.dataset.demoPrompt || ""; els.input.focus(); }));
loadStatus();
