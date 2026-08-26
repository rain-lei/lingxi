const DEVICE_ID = "demo-pendant-01";

const modeLabels = {
  assistant: "问答",
  companion: "陪伴",
  translate: "翻译",
};

const stateLabels = {
  idle: "待机",
  listening: "正在倾听",
  thinking: "思考中",
  speaking: "正在回应",
  offline: "网络不可用",
};

const rateLabels = {
  slow: "慢",
  normal: "正常",
  fast: "快",
};

const rateValues = {
  slow: 0.82,
  normal: 1,
  fast: 1.18,
};

const elements = {
  serverBadge: document.querySelector("#serverBadge"),
  deviceStage: document.querySelector("#deviceStage"),
  oledMode: document.querySelector("#oledMode"),
  oledText: document.querySelector("#oledText"),
  oledStatus: document.querySelector("#oledStatus"),
  talkButton: document.querySelector("#talkButton"),
  holdTip: document.querySelector("#holdTip"),
  conversation: document.querySelector("#conversation"),
  composer: document.querySelector("#composer"),
  messageInput: document.querySelector("#messageInput"),
  imageButton: document.querySelector("#imageButton"),
  imageInput: document.querySelector("#imageInput"),
  imagePreview: document.querySelector("#imagePreview"),
  imagePreviewImage: document.querySelector("#imagePreviewImage"),
  imagePreviewName: document.querySelector("#imagePreviewName"),
  removeImageButton: document.querySelector("#removeImageButton"),
  sendButton: document.querySelector("#sendButton"),
  offlineToggle: document.querySelector("#offlineToggle"),
  profileName: document.querySelector("#profileName"),
  profileRate: document.querySelector("#profileRate"),
  memoryNote: document.querySelector("#memoryNote"),
  latencyMetric: document.querySelector("#latencyMetric"),
  providerMetric: document.querySelector("#providerMetric"),
  sessionMetric: document.querySelector("#sessionMetric"),
  eventLog: document.querySelector("#eventLog"),
  resetButton: document.querySelector("#resetButton"),
  guideDialog: document.querySelector("#guideDialog"),
  showGuideButton: document.querySelector("#showGuideButton"),
  toast: document.querySelector("#toast"),
};

const app = {
  mode: "assistant",
  busy: false,
  profile: {
    preferred_name: "朋友",
    speech_rate: "normal",
  },
  recognition: null,
  recognizing: false,
  transcript: "",
  ttsActive: false,
  capabilities: { enabled: false, provider: "mock", chat: false, asr: false, tts: false, vision: false },
  pendingImage: null,
  audioCapture: null,
  captureStarting: false,
  stopCaptureRequested: false,
  audioPlayer: null,
  audioUrl: null,
};

function setServerStatus(status, label) {
  elements.serverBadge.classList.remove("connected", "error");
  if (status) elements.serverBadge.classList.add(status);
  elements.serverBadge.querySelector("span").textContent = label;
}

function setDeviceState(state, label = stateLabels[state] || state) {
  elements.deviceStage.dataset.state = state;
  elements.oledStatus.textContent = `● ${label}`;
  elements.sessionMetric.textContent = stateLabels[state] || label;
  document.querySelectorAll(".state-item").forEach((item) => item.classList.remove("active"));

  const pipelineState = state === "idle" || state === "offline" ? null : state;
  if (pipelineState) {
    document.querySelector(`[data-pipeline="${pipelineState}"]`)?.classList.add("active");
  }
}

function setMode(mode) {
  if (!modeLabels[mode]) return;
  app.mode = mode;
  document.querySelectorAll(".mode-option").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  elements.oledMode.textContent = `LINGXI / ${modeLabels[mode]}`;
  addLog("MODE", `切换至${modeLabels[mode]}模式`);
}

function updateProfile(profile, message = "") {
  if (!profile) return;
  app.profile = profile;
  elements.profileName.textContent = profile.preferred_name || "朋友";
  elements.profileRate.textContent = rateLabels[profile.speech_rate] || "正常";
  if (message) {
    elements.memoryNote.textContent = message;
    document.querySelector('[data-pipeline="memory"]')?.classList.add("active");
  }
}

function addMessage(role, text = "", options = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;
  if (options.streaming) wrapper.classList.add("streaming");
  if (options.offline) wrapper.classList.add("offline");

  if (role !== "user") {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = "灵";
    wrapper.append(avatar);
  }

  const body = document.createElement("div");
  const label = document.createElement("span");
  label.className = "message-role";
  label.textContent = role === "user" ? "你" : "灵犀";
  const content = document.createElement("p");
  content.textContent = text;
  body.append(label, content);
  if (options.imageDataUrl) {
    const image = document.createElement("img");
    image.className = "message-image";
    image.src = options.imageDataUrl;
    image.alt = "用户发送的图片";
    body.append(image);
  }
  wrapper.append(body);
  elements.conversation.append(wrapper);
  scrollConversation();
  return { wrapper, content };
}

function scrollConversation() {
  requestAnimationFrame(() => {
    elements.conversation.scrollTop = elements.conversation.scrollHeight;
  });
}

function addLog(code, message) {
  const entry = document.createElement("span");
  const time = document.createElement("time");
  time.textContent = code;
  entry.append(time, document.createTextNode(message));
  elements.eventLog.prepend(entry);
  while (elements.eventLog.children.length > 4) {
    elements.eventLog.lastElementChild.remove();
  }
}

let toastTimer = null;
function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("show");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => elements.toast.classList.remove("show"), 2600);
}

function resizeInput() {
  elements.messageInput.style.height = "auto";
  elements.messageInput.style.height = `${Math.min(elements.messageInput.scrollHeight, 104)}px`;
}

function clearImageSelection() {
  app.pendingImage = null;
  elements.imageInput.value = "";
  elements.imagePreview.hidden = true;
  elements.imagePreviewImage.removeAttribute("src");
  elements.imagePreviewName.textContent = "";
}

function handleImageSelection(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!/^image\/(jpeg|png|gif|webp)$/.test(file.type)) {
    clearImageSelection();
    showToast("请选择 JPG、PNG、GIF 或 WebP 图片");
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    clearImageSelection();
    showToast("图片不能超过 8 MB");
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    const dataUrl = String(reader.result || "");
    app.pendingImage = { dataUrl, name: file.name };
    elements.imagePreviewImage.src = dataUrl;
    elements.imagePreviewName.textContent = file.name;
    elements.imagePreview.hidden = false;
    addLog("VISION", "图片已准备，发送后由视觉模型分析");
  };
  reader.onerror = () => showToast("图片读取失败，请重试");
  reader.readAsDataURL(file);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `请求失败：${response.status}`);
  return payload;
}

async function loadInitialData() {
  try {
    await fetchJson("/api/health");
    setServerStatus("connected", "本地服务已连接");

    const [capabilities, profile, history] = await Promise.all([
      fetchJson("/api/capabilities"),
      fetchJson(`/api/profile?device_id=${encodeURIComponent(DEVICE_ID)}`),
      fetchJson(`/api/history?device_id=${encodeURIComponent(DEVICE_ID)}`),
    ]);
    app.capabilities = capabilities;
    if (capabilities.enabled) {
      setServerStatus("connected", "Step 3.7 已连接");
      elements.providerMetric.textContent = capabilities.models?.chat || "Step 3.7 Flash";
      elements.holdTip.textContent = "按住说话 · 阶跃 ASR";
      addLog("AI", `${capabilities.models?.chat || "Step 3.7 Flash"} 已就绪`);
    } else {
      elements.providerMetric.textContent = "Mock + 浏览器";
    }
    updateProfile(profile);
    history.items.forEach((item) => {
      addMessage("user", item.user_text);
      addMessage("assistant", item.assistant_text, { offline: item.status === "offline" });
    });
    if (history.items.length) addLog("MEM", `恢复 ${history.items.length} 轮历史会话`);
  } catch (error) {
    setServerStatus("error", "本地服务未连接");
    showToast(error.message);
  }
}

function setBusy(busy) {
  app.busy = busy;
  elements.sendButton.disabled = busy;
  elements.imageButton.disabled = busy;
  document.querySelectorAll(".suggestions button").forEach((button) => {
    button.disabled = busy;
  });
}

async function sendInteraction(text) {
  const cleanText = text.trim();
  const image = app.pendingImage;
  if ((!cleanText && !image) || app.busy) return;

  setBusy(true);
  stopSpeech();
  elements.messageInput.value = "";
  resizeInput();
  addMessage("user", cleanText || "请分析这张图片", image ? { imageDataUrl: image.dataUrl } : {});
  clearImageSelection();
  const assistant = addMessage("assistant", "", { streaming: true });
  let responseText = "";
  let completed = false;

  elements.oledText.textContent = cleanText;
  setDeviceState("listening", "收到输入");
  addLog("INPUT", `${cleanText.length} 字符`);

  try {
    const response = await fetch("/api/interactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        device_id: DEVICE_ID,
        text: cleanText,
        mode: app.mode,
        offline: elements.offlineToggle.checked,
        ...(image ? { image_data_url: image.dataUrl } : {}),
      }),
    });

    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.error || `请求失败：${response.status}`);
    }
    if (!response.body) throw new Error("浏览器不支持流式响应");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      lines.filter(Boolean).forEach((line) => {
        handleStreamEvent(JSON.parse(line), assistant, (delta) => {
          responseText += delta;
          assistant.content.textContent = responseText;
          elements.oledText.textContent = responseText;
          scrollConversation();
        });
      });
      if (done) break;
    }

    if (buffer.trim()) {
      handleStreamEvent(JSON.parse(buffer), assistant, (delta) => {
        responseText += delta;
        assistant.content.textContent = responseText;
        elements.oledText.textContent = responseText;
      });
    }
    completed = true;
  } catch (error) {
    assistant.wrapper.classList.add("offline");
    assistant.content.textContent = `连接失败：${error.message}`;
    assistant.wrapper.classList.remove("streaming");
    elements.oledText.textContent = "服务连接失败";
    setDeviceState("offline", "服务连接失败");
    setServerStatus("error", "本地服务异常");
    addLog("ERROR", error.message);
  } finally {
    assistant.wrapper.classList.remove("streaming");
    setBusy(false);
    if (!completed && elements.deviceStage.dataset.state !== "offline") {
      setDeviceState("idle");
    }
  }
}

function handleStreamEvent(event, assistant, appendDelta) {
  if (event.type === "state") {
    if (event.state === "idle" && app.ttsActive) return;
    setDeviceState(event.state, event.label);
    addLog("STATE", event.label);
    if (event.state === "offline") assistant.wrapper.classList.add("offline");
    return;
  }

  if (event.type === "delta") {
    appendDelta(event.text);
    return;
  }

  if (event.type === "memory") {
    updateProfile(event.profile, `已写入：${event.changes.join(" · ")}`);
    addLog("MEM", event.changes.join(" / "));
    return;
  }

  if (event.type === "provider") {
    const isStepFun = event.provider === "stepfun";
    const model = event.model || "Step 3.7 Flash";
    elements.providerMetric.textContent = isStepFun ? model : "本地 Mock";
    addLog("AI", event.label || (isStepFun ? "阶跃模型开始生成" : "已切换本地兜底"));
    return;
  }

  if (event.type === "complete") {
    assistant.wrapper.classList.remove("streaming");
    elements.latencyMetric.textContent = `${event.latency_ms} ms`;
    updateProfile(event.profile);
    if (event.provider === "stepfun") elements.providerMetric.textContent = event.model || "Step 3.7 Flash";
    if (event.provider === "mock") elements.providerMetric.textContent = "本地 Mock";
    addLog(event.offline ? "FALLBACK" : "DONE", `${event.latency_ms} ms`);
    if (!event.offline) speakResponse(event.text);
    return;
  }
}

function stopSpeech() {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  if (app.audioPlayer) {
    app.audioPlayer.pause();
    app.audioPlayer.src = "";
    app.audioPlayer = null;
  }
  if (app.audioUrl) {
    URL.revokeObjectURL(app.audioUrl);
    app.audioUrl = null;
  }
  app.ttsActive = false;
}

async function speakResponse(text) {
  if (app.capabilities.tts && text) {
    app.ttsActive = true;
    setDeviceState("speaking", "阶跃语音合成");
    try {
      const response = await fetch("/api/audio/speech", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          mode: app.mode,
          speech_rate: app.profile.speech_rate,
        }),
      });
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.error || `TTS 请求失败：${response.status}`);
      }
      const blob = await response.blob();
      const audioUrl = URL.createObjectURL(blob);
      const audio = new Audio(audioUrl);
      app.audioUrl = audioUrl;
      app.audioPlayer = audio;
      audio.onended = finishAudioPlayback;
      audio.onerror = () => {
        finishAudioPlayback();
        speakWithBrowser(text);
      };
      await audio.play();
      addLog("TTS", "StepAudio 2.5 音频开始播放");
      return;
    } catch (error) {
      addLog("TTS", `阶跃播报失败，使用浏览器兜底`);
      stopSpeech();
    }
  }
  speakWithBrowser(text);
}

function finishAudioPlayback() {
  if (app.audioUrl) URL.revokeObjectURL(app.audioUrl);
  app.audioUrl = null;
  app.audioPlayer = null;
  app.ttsActive = false;
  setDeviceState("idle");
}

function speakWithBrowser(text) {
  if (!("speechSynthesis" in window) || !text) {
    setDeviceState("idle");
    return;
  }

  stopSpeech();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = app.mode === "translate" && /^[\x00-\x7F\s.,!?'-]+$/.test(text) ? "en-US" : "zh-CN";
  utterance.rate = rateValues[app.profile.speech_rate] || 1;
  utterance.pitch = 1.04;
  utterance.onstart = () => {
    app.ttsActive = true;
    setDeviceState("speaking", "语音播报");
  };
  utterance.onend = () => {
    app.ttsActive = false;
    setDeviceState("idle");
  };
  utterance.onerror = () => {
    app.ttsActive = false;
    setDeviceState("idle");
  };
  window.speechSynthesis.speak(utterance);
}

function startVoiceInput(event) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (app.capabilities.asr && navigator.mediaDevices?.getUserMedia && AudioContextClass) {
    startStepFunCapture(event, AudioContextClass);
    return;
  }
  startRecognition(event);
}

function stopVoiceInput(event) {
  if (app.audioCapture || app.captureStarting) {
    stopStepFunCapture(event);
    return;
  }
  stopRecognition(event);
}

async function startStepFunCapture(event, AudioContextClass) {
  if (app.busy || app.audioCapture || app.captureStarting) return;
  event?.preventDefault();
  app.captureStarting = true;
  app.stopCaptureRequested = false;
  stopSpeech();

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    const context = new AudioContextClass();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    const chunks = [];
    processor.onaudioprocess = (audioEvent) => {
      chunks.push(new Float32Array(audioEvent.inputBuffer.getChannelData(0)));
    };
    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(context.destination);

    app.audioCapture = {
      stream,
      context,
      source,
      processor,
      silentGain,
      chunks,
      sampleRate: context.sampleRate,
      startedAt: performance.now(),
    };
    app.captureStarting = false;
    elements.talkButton.classList.add("active");
    elements.oledText.textContent = "";
    setDeviceState("listening", "阶跃 ASR 录音中");
    addLog("ASR", `PCM ${context.sampleRate}Hz 采集中`);

    if (app.stopCaptureRequested) stopStepFunCapture();
  } catch (error) {
    app.captureStarting = false;
    app.audioCapture = null;
    elements.talkButton.classList.remove("active");
    setDeviceState("idle");
    showToast("无法使用麦克风，请检查浏览器权限");
    addLog("ASR", "麦克风权限不可用");
  }
}

async function stopStepFunCapture(event) {
  event?.preventDefault();
  if (app.captureStarting) {
    app.stopCaptureRequested = true;
    return;
  }
  const capture = app.audioCapture;
  if (!capture) return;
  app.audioCapture = null;
  elements.talkButton.classList.remove("active");
  capture.processor.onaudioprocess = null;
  capture.source.disconnect();
  capture.processor.disconnect();
  capture.silentGain.disconnect();
  capture.stream.getTracks().forEach((track) => track.stop());
  await capture.context.close();

  const duration = (performance.now() - capture.startedAt) / 1000;
  if (duration < 0.25 || !capture.chunks.length) {
    setDeviceState("idle");
    showToast("按住时间太短，请再试一次");
    return;
  }

  const merged = mergeFloat32(capture.chunks);
  const downsampled = downsampleAudio(merged, capture.sampleRate, 16000);
  const pcm16 = floatToPcm16(downsampled);
  const audioBase64 = bytesToBase64(new Uint8Array(pcm16.buffer));
  setDeviceState("thinking", "阶跃语音识别中");
  setBusy(true);

  try {
    const result = await fetchJson("/api/audio/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio_base64: audioBase64, language: "zh" }),
    });
    elements.messageInput.value = result.text;
    elements.oledText.textContent = result.text;
    resizeInput();
    addLog("ASR", `StepAudio 识别 ${result.text.length} 字符`);
    setBusy(false);
    await sendInteraction(result.text);
  } catch (error) {
    setBusy(false);
    setDeviceState("idle");
    showToast(error.message);
    addLog("ASR", "阶跃语音识别失败");
  }
}

function mergeFloat32(chunks) {
  const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(length);
  let offset = 0;
  chunks.forEach((chunk) => {
    merged.set(chunk, offset);
    offset += chunk.length;
  });
  return merged;
}

function downsampleAudio(input, inputRate, outputRate) {
  if (inputRate === outputRate) return input;
  const ratio = inputRate / outputRate;
  const outputLength = Math.round(input.length / ratio);
  const output = new Float32Array(outputLength);
  let inputOffset = 0;
  for (let outputOffset = 0; outputOffset < outputLength; outputOffset += 1) {
    const nextInputOffset = Math.min(input.length, Math.round((outputOffset + 1) * ratio));
    let total = 0;
    let count = 0;
    for (; inputOffset < nextInputOffset; inputOffset += 1) {
      total += input[inputOffset];
      count += 1;
    }
    output[outputOffset] = count ? total / count : 0;
  }
  return output;
}

function floatToPcm16(samples) {
  const output = new Int16Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return window.btoa(binary);
}

function setupRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    elements.holdTip.textContent = "当前浏览器不支持语音 · 可使用文字输入";
    return;
  }

  const recognition = new Recognition();
  recognition.lang = "zh-CN";
  recognition.interimResults = true;
  recognition.continuous = false;

  recognition.onstart = () => {
    app.recognizing = true;
    app.transcript = "";
    elements.talkButton.classList.add("active");
    elements.oledText.textContent = "";
    setDeviceState("listening", "我在听");
    addLog("MIC", "浏览器麦克风已启动");
  };

  recognition.onresult = (event) => {
    let fullText = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      fullText += event.results[index][0].transcript;
    }
    app.transcript = fullText.trim();
    elements.oledText.textContent = app.transcript || "我在听…";
    elements.messageInput.value = app.transcript;
    resizeInput();
  };

  recognition.onerror = (event) => {
    app.recognizing = false;
    elements.talkButton.classList.remove("active");
    setDeviceState("idle");
    const message = event.error === "not-allowed" ? "请允许浏览器使用麦克风" : `语音识别失败：${event.error}`;
    showToast(message);
    addLog("MIC", message);
  };

  recognition.onend = () => {
    app.recognizing = false;
    elements.talkButton.classList.remove("active");
    const transcript = app.transcript.trim();
    if (transcript && !app.busy) sendInteraction(transcript);
    else if (!app.busy) setDeviceState("idle");
  };

  app.recognition = recognition;
}

function startRecognition(event) {
  if (app.busy || app.recognizing) return;
  event?.preventDefault();
  if (!app.recognition) {
    showToast("当前浏览器不支持语音识别，请在右侧输入文字");
    elements.messageInput.focus();
    return;
  }
  try {
    app.recognition.start();
  } catch (error) {
    showToast("麦克风正在准备，请稍后再试");
  }
}

function stopRecognition(event) {
  event?.preventDefault();
  if (!app.recognition || !app.recognizing) return;
  app.recognition.stop();
}

async function resetDemo() {
  const confirmed = window.confirm("清空本机 demo 的记忆和会话记录？");
  if (!confirmed) return;
  try {
    const payload = await fetchJson("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: DEVICE_ID }),
    });
    updateProfile(payload.profile, "记忆已清空。再次对话时会重新建立用户画像。");
    elements.conversation.querySelectorAll(".message:not(.welcome-message)").forEach((message) => message.remove());
    elements.latencyMetric.textContent = "—";
    addLog("RESET", "本地记忆已清空");
    showToast("Demo 数据已清空");
  } catch (error) {
    showToast(error.message);
  }
}

document.querySelectorAll(".mode-option").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});

document.querySelectorAll(".suggestions button").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.modeTarget) setMode(button.dataset.modeTarget);
    sendInteraction(button.dataset.prompt || "");
  });
});

elements.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  sendInteraction(elements.messageInput.value);
});

elements.imageButton.addEventListener("click", () => elements.imageInput.click());
elements.imageInput.addEventListener("change", handleImageSelection);
elements.removeImageButton.addEventListener("click", clearImageSelection);

elements.messageInput.addEventListener("input", resizeInput);
elements.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.composer.requestSubmit();
  }
});

elements.talkButton.addEventListener("pointerdown", startVoiceInput);
elements.talkButton.addEventListener("pointerup", stopVoiceInput);
elements.talkButton.addEventListener("pointercancel", stopVoiceInput);
elements.talkButton.addEventListener("pointerleave", stopVoiceInput);
elements.talkButton.addEventListener("keydown", (event) => {
  if (event.code === "Space" && !event.repeat) startVoiceInput(event);
});
elements.talkButton.addEventListener("keyup", (event) => {
  if (event.code === "Space") stopVoiceInput(event);
});

elements.offlineToggle.addEventListener("change", () => {
  const active = elements.offlineToggle.checked;
  showToast(active ? "下一条消息将模拟断网" : "已恢复在线链路");
  addLog("NET", active ? "断网演练已开启" : "在线链路已恢复");
});

elements.resetButton.addEventListener("click", resetDemo);
elements.showGuideButton.addEventListener("click", () => elements.guideDialog.showModal());

window.addEventListener("beforeunload", stopSpeech);

setDeviceState("idle");
setupRecognition();
loadInitialData();
