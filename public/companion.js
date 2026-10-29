"use strict";

// The page keeps paired-device credentials in the current tab session. All voices and saved preferences
// come from the local service; browser speech synthesis is never substituted.
const $ = (id) => document.getElementById(id);
const ui = Object.fromEntries([
  "connection", "connectionLabel", "setupBanner", "setupBannerTitle", "setupBannerText",
  "openSetup", "openSetupAdvanced", "setupDialog", "setupForm", "closeSetup", "setupStatus",
  "apiKey", "baseUrl", "setupDeviceToken", "setupError", "saveSetup", "preferencesForm",
  "voiceSelect", "voiceDescription", "saveStatus", "savePreferences", "settingsError",
  "deviceId", "deviceToken", "switchDevice", "stage", "petMood", "petImage", "petBadge", "petPlaceholder",
  "petName", "petLine", "avatarTag", "messages", "clearChat", "chatForm", "messageInput",
  "micButton", "sendButton", "inputHint", "chatError", "stopAudio", "voiceReply", "toast",
  "memoryCount", "memoryList", "focusClock", "focusHint", "startFocus", "endFocus",
  "breathOrb", "breathLabel", "breathHint", "startBreath", "replyTiming"
].map((id) => [id, $(id)]));

const AVATARS = {
  kangaroo: { name: "蓝蓝", image: "/assets/mascot-kangaroo-preview.png", tag: "大工小伙伴", alt: "蓝色袋鼠小伙伴" },
  robot: { name: "小犀", image: "/assets/mascot-robot-preview.png", tag: "灵感行动派", alt: "蓝色云朵机器人小犀" },
  cat: { name: "奶泡", image: "/assets/companion-cat.png", tag: "安静倾听派", alt: "戴淡紫围巾的奶白毛绒小猫奶泡" },
  otter: { name: "团团", image: "/assets/companion-otter.png", tag: "耐心学习派", alt: "抱蓝色书本的毛绒水獭团团" },
  sprout: { name: "芽芽", image: "/assets/companion-sprout.png", tag: "元气成长派", alt: "头顶双叶的薄荷绿毛绒小龙芽芽" }
};
const MOODS = {
  idle: ["等你说说话", "不用急，我在这里听你说。"],
  listening: ["正在认真听", "嗯嗯，你说，我在听。"],
  thinking: ["正在想怎么回应你", "让我好好想一想…"],
  speaking: ["正在回应你", "这是我想对你说的话。"]
};
const DEFAULTS = { avatar: "kangaroo", mode: "companion", voice: "", tone: "warm", language: "zh", persona: "friend", speech_rate: "normal" };
const state = { deviceId: LingxiIdentity.get(), settings: { ...DEFAULTS }, voices: [], dirty: false, ready: false, configured: false, setup: null, busy: false, recorder: null, audioContext: null, audioSource: null, loadRevision: 0, inputSeconds: 10 };
const streamAudio = { sources: new Set(), nextAt: 0, muted: false, generation: 0 };
let focusEndsAt = 0;
let breathStartedAt = 0;
let toastTimer;
let voiceFrame = 0, lastVoicePaint = 0, voiceEnergy = 0, listeningEnergy = 0;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
// Animation is optional artwork. It must never delay settings, audio or chat.
const petMotion = { catalog: null, requested: false, revision: 0, requestedKey: "", renderedKey: "", renderedAvatar: "", renderedKind: "", pending: null, failed: new Set(), celebrationUntil: 0, celebrationTimer: 0, preview: "", previewTimer: 0, ambientTimer: 0, ambientIndex: 0, paused: false, preloads: new Set() };
const PET_GESTURES = {
  greeting: "打个招呼", comfort: "一个抱抱", focus: "陪你学习",
  celebrate: "庆祝一下", stretch: "伸个懒腰", sleepy: "晚安时刻"
};
const TONE_STYLES = {
  warm: { name: "温柔安慰", hint: "柔软的圆体，把每句话说得温柔一点。" },
  calm: { name: "平静舒缓", hint: "沉静的书卷字形，留一点从容，慢慢说。" },
  cheerful: { name: "活泼元气", hint: "轻快的手写字形，装下今天的小雀跃。" },
  direct: { name: "清晰简洁", hint: "清楚利落的黑体，把重要的事情说清楚。" }
};

function petAssetURL(value, extensions) {
  if (typeof value !== "string" || !/^\/animations\/v[23]\//.test(value)) return null;
  try {
    const url = new URL(value, location.origin);
    if (url.origin !== location.origin || !/^\/animations\/v[23]\//.test(url.pathname) || url.search || url.hash || !extensions.some((extension) => url.pathname.toLowerCase().endsWith(extension))) return null;
    return url.pathname;
  } catch { return null; }
}
function clearPetCelebration() {
  clearTimeout(petMotion.celebrationTimer);
  petMotion.celebrationTimer = 0;
  petMotion.celebrationUntil = 0;
}
function clearPetPreview() {
  clearTimeout(petMotion.previewTimer);
  clearTimeout(petMotion.ambientTimer);
  petMotion.previewTimer = petMotion.ambientTimer = 0;
  petMotion.preview = "";
  delete ui.stage.dataset.preview;
  document.querySelectorAll("[data-pet-motion]").forEach((button) => button.setAttribute("aria-pressed", "false"));
  const status = $("motionPreviewStatus");
  if (status) status.textContent = "轻点动作，看看我的小表情";
  if ($("returnPetIdle")) $("returnPetIdle").hidden = true;
}
function scheduleAmbientGesture() {
  clearTimeout(petMotion.ambientTimer);
  if (reducedMotion.matches || petMotion.paused || document.hidden || state.busy || state.recorder || ui.stage.dataset.state !== "idle" || petMotion.preview || ui.stage.closest("[hidden]")) return;
  const avatar = ui.stage.dataset.avatar;
  const clips = petMotion.catalog?.get(avatar);
  const choices = focusEndsAt > Date.now() ? ["focus", "stretch"] : ["stretch", "greeting"];
  const available = choices.filter((id) => clips?.has(id));
  if (!available.length) return;
  petMotion.ambientTimer = setTimeout(() => {
    petMotion.ambientTimer = 0;
    if (state.busy || state.recorder || ui.stage.dataset.state !== "idle" || document.hidden || reducedMotion.matches || petMotion.paused || ui.stage.closest("[hidden]")) return;
    previewPetGesture(available[petMotion.ambientIndex++ % available.length], { ambient: true });
  }, 18000);
}
function previewPetGesture(id, { ambient = false } = {}) {
  if (state.busy || state.recorder || ui.stage.dataset.state !== "idle") {
    if (!ambient) toast("先听完这一句，等聊完再看看小动作。 ");
    return false;
  }
  const clip = petMotion.catalog?.get(ui.stage.dataset.avatar)?.get(id);
  if (!clip || petMotion.failed.has(clip.preview)) {
    if (!ambient) toast("这段新动作还在准备，先看看其他小表情吧。 ");
    return false;
  }
  clearPetCelebration();
  clearPetPreview();
  petMotion.preview = id;
  ui.stage.dataset.preview = id;
  const status = $("motionPreviewStatus");
  if (status) status.textContent = `${ambient ? "陪伴小动作" : "动作预览"} · ${PET_GESTURES[id] || clip.label || id}`;
  document.querySelectorAll("[data-pet-motion]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.petMotion === id)));
  if ($("returnPetIdle")) $("returnPetIdle").hidden = false;
  syncPetArtwork();
  return true;
}
function cancelPetImageRequest() {
  if (!petMotion.pending) return;
  petMotion.pending.onload = petMotion.pending.onerror = null;
  petMotion.pending.removeAttribute("src");
  petMotion.pending = null;
}
function currentPetArtwork() {
  const avatar = AVATARS[ui.stage.dataset.avatar] ? ui.stage.dataset.avatar : "kangaroo";
  const mood = MOODS[ui.stage.dataset.state] ? ui.stage.dataset.state : "idle";
  const clipId = mood === "idle" && !state.busy && petMotion.preview ? petMotion.preview : mood === "idle" && !state.busy && performance.now() < petMotion.celebrationUntil ? "celebrate" : mood;
  const clip = petMotion.catalog?.get(avatar)?.get(clipId);
  const still = reducedMotion.matches || petMotion.paused || document.hidden || Boolean(ui.stage.closest("[hidden]"));
  const kind = clip && !petMotion.failed.has(clip.preview) ? (still ? "poster" : "animated") : "fallback";
  const url = kind === "animated" ? clip.preview : kind === "poster" ? clip.poster : AVATARS[avatar].image;
  if (!url || petMotion.failed.has(url)) return { avatar, clipId, kind: "fallback", url: AVATARS[avatar].image };
  return { avatar, clipId, kind, url, badgeBaked: clip?.badgeBaked === true };
}
function syncPetArtwork() {
  const target = currentPetArtwork();
  const key = `${target.avatar}:${target.clipId}:${target.kind}:${target.url}`;
  if (petMotion.requestedKey === key) return;
  const revision = ++petMotion.revision;
  petMotion.requestedKey = key;
  cancelPetImageRequest();
  // Keep the previous complete frame on screen while the next clip loads and
  // decodes. Replacing one image atomically avoids blanks and double mascots.
  const image = new Image();
  image.id = "petImage";
  image.className = "pet-image";
  image.alt = AVATARS[target.avatar].alt;
  image.decoding = "async";
  image.draggable = false;
  petMotion.pending = image;
  const failed = () => {
    if (revision !== petMotion.revision) return;
    petMotion.failed.add(target.url);
    petMotion.pending = null;
    image.onload = image.onerror = null;
    image.removeAttribute("src");
    if (target.kind === "fallback") {
      // A working previous frame is preferable to an empty loading silhouette.
      if (!ui.petImage.naturalWidth) {
        ui.petImage.hidden = true;
        ui.petBadge.hidden = true;
        ui.petPlaceholder.hidden = false;
        ui.stage.dataset.petArt = "fallback";
      }
      return;
    }
    petMotion.requestedKey = "";
    syncPetArtwork();
  };
  image.onerror = failed;
  image.onload = async () => {
    if (revision !== petMotion.revision) { image.onload = image.onerror = null; image.removeAttribute("src"); return; }
    if (!image.naturalWidth) { failed(); return; }
    try { if (image.decode) await image.decode(); } catch { if (!image.naturalWidth) { failed(); return; } }
    if (revision !== petMotion.revision) { image.onload = image.onerror = null; image.removeAttribute("src"); return; }
    image.onload = null;
    petMotion.pending = null;
    const previous = ui.petImage;
    previous.replaceWith(image);
    ui.petImage = image;
    previous.onload = previous.onerror = null;
    previous.removeAttribute("src");
    petMotion.renderedKey = key;
    petMotion.renderedAvatar = target.avatar;
    petMotion.renderedKind = target.kind;
    ui.stage.dataset.petArt = target.kind;
    ui.stage.dataset.petBadgeBaked = String(target.avatar === "kangaroo" && target.kind !== "fallback" && target.badgeBaked === true);
    ui.petPlaceholder.hidden = true;
    ui.petBadge.hidden = target.avatar !== "kangaroo" || (target.kind !== "fallback" && target.badgeBaked === true);
    if (petMotion.preview && target.clipId === petMotion.preview) {
      clearTimeout(petMotion.previewTimer);
      const duration = petMotion.catalog?.get(target.avatar)?.get(target.clipId)?.duration || 3500;
      petMotion.previewTimer = setTimeout(() => { clearPetPreview(); syncPetArtwork(); }, duration);
    } else scheduleAmbientGesture();
  };
  image.src = target.url;
}
async function loadPetAnimations() {
  if (petMotion.requested) return;
  petMotion.requested = true;
  try {
    let manifest;
    for (const path of ["/animations/v3/manifest.json", "/animations/v2/manifest.json"]) {
      try {
        const response = await LingxiIdentity.fetch(path, { cache: "no-store", credentials: "same-origin", signal: AbortSignal.timeout(8000) });
        if (!response.ok) continue;
        const candidate = await response.json();
        if (candidate.schema_version !== 1 || candidate.ready === false || candidate.web_ready === false || !Array.isArray(candidate.avatars)) continue;
        manifest = candidate; break;
      } catch { /* A not-yet-published V3 pack must not hide the V2 companion. */ }
    }
    if (!manifest) return;
    const catalog = new Map();
    for (const avatar of manifest.avatars) {
      if (!AVATARS[avatar?.id] || !Array.isArray(avatar.clips)) continue;
      const clips = new Map();
      for (const clip of avatar.clips) {
        if (!clip || ![...Object.keys(MOODS), ...Object.keys(PET_GESTURES)].includes(clip.id)) continue;
        const preview = petAssetURL(clip.web_preview_url, [".webp", ".png"]);
        const poster = petAssetURL(clip.web_poster_url, [".webp", ".png"]);
        if (!preview || !poster) continue;
        const badgeBaked = clip.web_badge_baked === false ? false : clip.web_badge_baked === true || clip.badge_baked === true;
        clips.set(clip.id, { preview, poster, badgeBaked, label: clip.label, duration: Math.min(15000, Math.max(500, Number(clip.web_duration_ms || clip.duration_ms) || 2000)) });
      }
      if (clips.size) catalog.set(avatar.id, clips);
    }
    if (!catalog.size) return;
    petMotion.catalog = catalog;
    updateMotionDock();
    syncPetArtwork();
  } catch { /* The original static character remains available offline. */ }
}

function paintVoice(now) {
  if (!["listening", "speaking"].includes(ui.stage.dataset.state) || document.hidden) {
    voiceFrame = 0;
    return;
  }
  if (now - lastVoicePaint >= 65) {
    lastVoicePaint = now;
    let energy = listeningEnergy;
    if (ui.stage.dataset.state === "speaking" && state.playbackAnalyser) {
      state.playbackAnalyser.getByteTimeDomainData(state.waveSamples);
      let squares = 0;
      for (const value of state.waveSamples) squares += ((value - 128) / 128) ** 2;
      energy = Math.sqrt(squares / state.waveSamples.length);
    }
    voiceEnergy = voiceEnergy * .6 + Math.min(1, energy * 5) * .4;
    ui.stage.style.setProperty("--voice-level", voiceEnergy.toFixed(3));
    const bars = ui.stage.querySelectorAll(".audio-visualizer i");
    bars.forEach((bar, index) => {
      // A single measured envelope drives a fixed symmetric spatial profile.
      // No generated bars or synthetic 'microphone level' are presented.
      const center = 1 - Math.abs(index - (bars.length - 1) / 2) / Math.max(1, bars.length / 2);
      bar.style.height = `${4 + voiceEnergy * (10 + 26 * center)}px`;
    });
  }
  voiceFrame = requestAnimationFrame(paintVoice);
}

function resetVoiceVisual() {
  cancelAnimationFrame(voiceFrame);
  voiceFrame = 0;
  voiceEnergy = listeningEnergy = 0;
  ui.stage.style.setProperty("--voice-level", "0");
  ui.stage.querySelectorAll(".audio-visualizer i").forEach((bar) => { bar.style.height = "4px"; });
}

const petFrame = document.querySelector(".pet-frame");
if (petFrame) {
  petFrame.setAttribute("role", "button");
  petFrame.setAttribute("tabindex", "0");
  petFrame.setAttribute("aria-label", "摸摸小伙伴");
  function greetPet() {
    if (state.busy || state.recorder || ui.stage.dataset.state !== "idle" || document.hidden || reducedMotion.matches) return;
    const clips = petMotion.catalog?.get(ui.stage.dataset.avatar);
    const greeting = clips?.has("greeting") ? "greeting" : "celebrate";
    const clip = clips?.get(greeting);
    if (clip && !petMotion.failed.has(clip.preview)) {
      previewPetGesture(greeting);
      return;
    }
    // A still fallback is not an articulated gesture. Do not rotate the whole
    // cutout to imitate a greeting while the motion catalog is unavailable.
    toast("收到你的摸摸啦。动作素材加载完成后，我再向你挥挥手。");
  }
  petFrame.addEventListener("click", greetPet);
  petFrame.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); greetPet(); }
  });
  // The APNG owns the joint motion. Keep its canvas anchored to the floor;
  // pointer parallax would move the badge and torso as one flat rectangle.
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { resetVoiceVisual(); clearPetCelebration(); clearPetPreview(); }
  else if (["listening", "speaking"].includes(ui.stage.dataset.state) && !voiceFrame && !reducedMotion.matches) voiceFrame = requestAnimationFrame(paintVoice);
  syncPetArtwork();
});
function petMotionPreferenceChanged() {
  clearPetCelebration();
  clearPetPreview();
  if (reducedMotion.matches) {
    resetVoiceVisual();
  } else if (["listening", "speaking"].includes(ui.stage.dataset.state) && !document.hidden && !voiceFrame) voiceFrame = requestAnimationFrame(paintVoice);
  syncPetArtwork();
}
if (reducedMotion.addEventListener) reducedMotion.addEventListener("change", petMotionPreferenceChanged);
else if (reducedMotion.addListener) reducedMotion.addListener(petMotionPreferenceChanged);

function updateMotionDock() {
  const clips = petMotion.catalog?.get(ui.stage.dataset.avatar);
  document.querySelectorAll("[data-pet-motion]").forEach((button) => {
    const supported = Boolean(clips?.has(button.dataset.petMotion));
    button.disabled = state.busy || !supported;
    button.title = supported ? "只预览动作，不会发送对话" : "这段新动作正在准备";
    if (!button.hasAttribute("aria-pressed")) button.setAttribute("aria-pressed", "false");
  });
}
function prewarmPetClip(id) {
  if (reducedMotion.matches || petMotion.paused || document.hidden) return;
  const clip = petMotion.catalog?.get(ui.stage.dataset.avatar)?.get(id);
  if (!clip || petMotion.preloads.has(clip.preview)) return;
  // A browser-managed compressed prefetch avoids holding several decoded APNGs
  // in memory. The active complete image is still retained during a real swap.
  const preload = document.createElement("link");
  preload.rel = "prefetch";
  preload.as = "image";
  preload.href = clip.preview;
  document.head.append(preload);
  petMotion.preloads.add(clip.preview);
  while (petMotion.preloads.size > 12) {
    const first = petMotion.preloads.values().next().value;
    petMotion.preloads.delete(first);
    for (const node of document.head.querySelectorAll('link[rel="prefetch"]')) if (node.getAttribute("href") === first) node.remove();
  }
}
document.querySelectorAll("[data-pet-motion]").forEach((button) => {
  button.addEventListener("click", () => previewPetGesture(button.dataset.petMotion));
  button.addEventListener("pointerenter", () => prewarmPetClip(button.dataset.petMotion));
  button.addEventListener("focus", () => prewarmPetClip(button.dataset.petMotion));
});
$("returnPetIdle")?.addEventListener("click", () => { clearPetPreview(); syncPetArtwork(); });
$("pausePetMotion")?.addEventListener("click", () => {
  petMotion.paused = !petMotion.paused;
  clearPetPreview();
  $("pausePetMotion").setAttribute("aria-pressed", String(petMotion.paused));
  $("pausePetMotion").textContent = petMotion.paused ? "让伙伴动起来" : "静态欣赏";
  syncPetArtwork();
  if (!petMotion.paused && reducedMotion.matches) toast("已尊重系统的减少动态设置，继续使用静态画面。 ");
});
ui.messageInput.addEventListener("focus", () => { prewarmPetClip("thinking"); prewarmPetClip("speaking"); });
ui.micButton.addEventListener("pointerenter", () => prewarmPetClip("listening"));

function applyToneStyle(value) {
  const tone = TONE_STYLES[value] ? value : "warm";
  document.body.dataset.tone = tone;
  document.querySelectorAll("[data-tone-choice]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.toneChoice === tone)));
  if ($("toneStyleHint")) $("toneStyleHint").textContent = TONE_STYLES[tone].hint;
}
document.querySelectorAll("[data-tone-choice]").forEach((button) => button.addEventListener("click", () => {
  if (state.busy || state.recorder || !TONE_STYLES[button.dataset.toneChoice]) return;
  const tone = button.dataset.toneChoice;
  const field = ui.preferencesForm.elements.namedItem("tone");
  if (!field) return;
  field.value = tone;
  field.dispatchEvent(new Event("change", { bubbles: true }));
  toast(`已选择「${TONE_STYLES[tone].name}」。字体已预览，下次对话前会保存语气。`);
}));

function setShowcaseMode(enabled) {
  document.body.classList.toggle("is-showcase", enabled);
  const toggle = $("showcaseToggle");
  if (toggle) {
    toggle.setAttribute("aria-pressed", String(enabled));
    toggle.replaceChildren();
    const icon = document.createElement("span"); icon.textContent = enabled ? "↙" : "↗"; icon.setAttribute("aria-hidden", "true");
    toggle.append(icon, document.createTextNode(enabled ? "退出展示" : "现场展示"));
  }
  if ($("showcaseModeTag")) $("showcaseModeTag").hidden = !enabled;
  if (enabled && document.querySelector('[data-view="home"]')?.hidden) navigateCompanion("home");
  if (enabled) window.scrollTo({ top: 0, behavior: "instant" });
}
$("showcaseToggle")?.addEventListener("click", () => setShowcaseMode(!document.body.classList.contains("is-showcase")));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && document.body.classList.contains("is-showcase") && !document.querySelector("dialog[open]")) setShowcaseMode(false);
});

function validDevice(value) { return /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(value || ""); }
const queryDevice = new URLSearchParams(location.search).get("device_id");
ui.deviceId.value = validDevice(queryDevice) ? queryDevice : state.deviceId;
ui.deviceToken.value = LingxiIdentity.token();

function toast(message) {
  clearTimeout(toastTimer);
  ui.toast.textContent = message;
  ui.toast.hidden = false;
  toastTimer = setTimeout(() => { ui.toast.hidden = true; }, 3500);
}
function showError(element, message = "") { element.textContent = message; element.hidden = !message; }
function apiHeaders(extra = {}) {
  const headers = { ...extra };
  if (ui.deviceToken.value.trim()) headers["X-Device-Token"] = ui.deviceToken.value.trim();
  return headers;
}
async function responseError(response) {
  let detail = "";
  try {
    const data = await response.json();
    detail = typeof data.error === "string" ? data.error : data.error?.message || data.message || data.detail || "";
  } catch { /* Do not expose HTML error pages or service tracebacks. */ }
  if (response.status === 401 || response.status === 403) return new Error(detail || "访问被拒绝。请检查设备访问令牌，或在本机完成服务配置。");
  if (response.status === 404) return new Error("当前服务未提供陪伴接口，请重启更新后的灵犀服务。");
  if (response.status === 503) return new Error(detail || "语音服务还没有配置完成，请先连接服务。");
  return new Error(detail || `请求失败（HTTP ${response.status}），请检查本地服务和网络。`);
}
async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeout || 90000);
  try {
    const response = await LingxiIdentity.fetch(path, { ...options, headers: apiHeaders(options.headers), signal: controller.signal });
    if (!response.ok) throw await responseError(response);
    return response;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("这次请求等待太久了。请检查服务状态后重试。");
    if (error instanceof TypeError) throw new Error("无法连接本地服务。请确认灵犀服务正在运行，并刷新页面。");
    throw error;
  } finally { clearTimeout(timeout); }
}
async function getJSON(path) { return (await request(path, { timeout: 15000 })).json(); }
async function postJSON(path, payload) { return request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); }

function setMood(mood, line) {
  if (mood !== "idle") { clearPetCelebration(); clearPetPreview(); }
  ui.stage.dataset.state = mood;
  ui.petMood.textContent = MOODS[mood][0];
  ui.petLine.textContent = line || MOODS[mood][1];
  if (["listening", "speaking"].includes(mood) && !reducedMotion.matches) {
    if (!voiceFrame) voiceFrame = requestAnimationFrame(paintVoice);
  } else resetVoiceVisual();
  syncPetArtwork();
}
function showAvatar(value) {
  const avatar = AVATARS[value] || AVATARS.kangaroo;
  if (ui.stage.dataset.avatar !== value) { clearPetCelebration(); clearPetPreview(); }
  ui.stage.dataset.avatar = AVATARS[value] ? value : "kangaroo";
  syncPetArtwork();
  ui.petName.textContent = avatar.name;
  ui.avatarTag.textContent = avatar.tag;
  updateMotionDock();
  document.querySelectorAll("[data-character]").forEach((card) => {
    const selected = card.dataset.character === value;
    card.classList.toggle("is-selected", selected);
    const button = card.querySelector("[data-choose-avatar]");
    if (button) { button.setAttribute("aria-pressed", String(selected)); button.firstChild.textContent = selected ? "正在陪伴你 " : `邀请${AVATARS[card.dataset.character]?.name || "伙伴"}陪我 `; }
  });
}

function formSettings() {
  const data = new FormData(ui.preferencesForm);
  return Object.fromEntries(Object.keys(DEFAULTS).map((key) => [key, String(data.get(key) || DEFAULTS[key])]));
}
function populateSettings(settings) {
  state.settings = { ...DEFAULTS, ...settings };
  for (const [name, value] of Object.entries(state.settings)) {
    const field = ui.preferencesForm.elements.namedItem(name);
    if (field && typeof value === "string") field.value = value;
  }
  showAvatar(state.settings.avatar);
  applyToneStyle(state.settings.tone);
  updateVoiceDescription();
  markDirty(false);
}
function markDirty(dirty) {
  state.dirty = dirty;
  ui.saveStatus.textContent = dirty ? "有新的偏好待保存" : "已与服务同步";
  ui.saveStatus.dataset.dirty = String(dirty);
}
function updateVoiceDescription() {
  const voice = state.voices.find((item) => item.id === ui.voiceSelect.value);
  ui.voiceDescription.textContent = voice?.description || "保存后，后续对话将使用这个声音。";
}
function populateCatalog(catalog) {
  const source = catalog.voices || catalog.options?.voice || catalog.options?.voices || [];
  state.inputSeconds = Math.min(20, Math.max(1, Number(catalog.limits?.input_seconds) || 10));
  ui.inputHint.textContent = `录音最长 ${state.inputSeconds} 秒 · 声音将发送给已配置的语音服务`;
  state.voices = source.map((item) => typeof item === "string" ? { id: item, name: item } : ({ ...item, id: item.id || item.value, name: item.name || item.label || item.id || item.value })).filter((item) => item.id);
  ui.voiceSelect.replaceChildren();
  if (!state.voices.length) {
    const option = new Option("服务暂未提供可用声音", "");
    ui.voiceSelect.add(option);
    ui.voiceSelect.disabled = true;
    return;
  }
  for (const item of state.voices) ui.voiceSelect.add(new Option(item.name, item.id));
  ui.voiceSelect.disabled = false;
}

async function loadSettings() {
  const revision = ++state.loadRevision;
  ui.savePreferences.disabled = true;
  ui.saveStatus.textContent = "正在读取设备偏好…";
  showError(ui.settingsError);
  try {
    const data = await getJSON(`/api/companion/settings?device_id=${encodeURIComponent(state.deviceId)}`);
    if (revision !== state.loadRevision) return;
    populateSettings(data.settings || data);
    state.ready = true;
    window.dispatchEvent(new CustomEvent("lingxi:ready", { detail: { deviceId: state.deviceId } }));
    await loadExperience();
  } catch (error) {
    if (revision !== state.loadRevision) return;
    state.ready = false;
    ui.saveStatus.textContent = "暂未同步";
    showError(ui.settingsError, error.message);
  } finally { if (revision === state.loadRevision) ui.savePreferences.disabled = !state.ready; }
}
async function saveSettings({ quiet = false } = {}) {
  if (!state.ready) throw new Error("偏好还未载入，请检查服务后刷新页面。");
  const settings = formSettings();
  if (!settings.voice) throw new Error("请先选择一个服务支持的声音。");
  ui.savePreferences.disabled = true;
  ui.saveStatus.textContent = "正在保存…";
  showError(ui.settingsError);
  try {
    const response = await postJSON("/api/companion/settings", { device_id: state.deviceId, settings });
    const data = await response.json();
    populateSettings(data.settings || settings);
    if (!quiet) toast("偏好已保存，下次对话就用这个声音。 ");
  } catch (error) {
    ui.saveStatus.textContent = "未保存，请重试";
    showError(ui.settingsError, error.message);
    throw error;
  } finally { ui.savePreferences.disabled = state.busy || !state.ready; }
}
ui.preferencesForm.addEventListener("change", () => {
  markDirty(true);
  showAvatar(formSettings().avatar);
  applyToneStyle(formSettings().tone);
  updateVoiceDescription();
});
ui.preferencesForm.addEventListener("submit", (event) => { event.preventDefault(); saveSettings().catch(() => {}); });
ui.switchDevice.addEventListener("click", async () => {
  if (state.busy || state.recorder) return toast("等这次对话结束后，再切换设备。 ");
  const device = ui.deviceId.value.trim();
  if (!validDevice(device)) return showError(ui.settingsError, "设备编号请使用 1–64 位英文字母、数字、短横线、下划线、点或冒号。");
  try { await getJSON(`/api/companion/settings?device_id=${encodeURIComponent(device)}`); }
  catch (error) { return showError(ui.settingsError, error.message); }
  LingxiIdentity.select(device, ui.deviceToken.value.trim());
  state.deviceId = device;
  state.ready = false;
  focusEndsAt = 0;
  updateFocus();
  window.dispatchEvent(new CustomEvent("lingxi:device-changing", { detail: { deviceId: device } }));
  stopPlayback();
  stopBreathing();
  await loadSettings();
  if (state.ready) toast(`已切换到设备 ${device}`);
});

function applySetup(setup) {
  state.setup = setup;
  state.configured = Boolean(setup.configured);
  ui.connection.dataset.status = state.configured ? "ready" : "error";
  ui.connectionLabel.textContent = state.configured ? "服务已配置" : "等待连接服务";
  ui.setupBanner.hidden = state.configured;
  ui.baseUrl.value = setup.base_url || "https://api.stepfun.com/v1";
  const allowed = Boolean(setup.local_setup_allowed);
  [ui.apiKey, ui.baseUrl, ui.setupDeviceToken, ui.saveSetup].forEach((element) => { element.disabled = !allowed; });
  ui.setupStatus.textContent = allowed
    ? (state.configured ? "已有服务密钥。更新服务配置时，请重新填写所用密钥。" : "尚未配置服务密钥。保存后可发起真实对话；服务是否可用以首次请求结果为准。")
    : "密钥仅能在运行服务的电脑本机配置。请在电脑浏览器打开 127.0.0.1:8787/companion。";
  if (!allowed) ui.setupBannerText.textContent = "请在运行服务的电脑上打开 127.0.0.1:8787/companion，添加语音服务密钥。";
  else ui.setupBannerText.textContent = "添加服务密钥后，就能体验真实的语音识别、对话和声音回应。";
}
function openSetup() { showError(ui.setupError); ui.setupDialog.showModal(); }
ui.openSetup.addEventListener("click", openSetup);
ui.openSetupAdvanced.addEventListener("click", openSetup);
ui.closeSetup.addEventListener("click", () => { ui.apiKey.value = ""; ui.setupDeviceToken.value = ""; ui.setupDialog.close(); });
ui.setupDialog.addEventListener("close", () => { ui.apiKey.value = ""; ui.setupDeviceToken.value = ""; });
ui.setupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.setup?.local_setup_allowed) return;
  ui.saveSetup.disabled = true;
  showError(ui.setupError);
  const payload = { base_url: ui.baseUrl.value.trim() };
  if (ui.apiKey.value.trim()) payload.api_key = ui.apiKey.value.trim();
  if (ui.setupDeviceToken.value.trim()) payload.device_token = ui.setupDeviceToken.value.trim();
  try {
    await postJSON("/api/companion/setup", payload);
    // Clear the secret before a follow-up network request can fail.
    ui.apiKey.value = "";
    ui.setupDeviceToken.value = "";
    applySetup(await getJSON("/api/companion/setup"));
    ui.setupDialog.close();
    toast("服务配置已保存，可以发起第一次对话了。");
  } catch (error) { showError(ui.setupError, error.message); }
  finally { ui.apiKey.value = ""; ui.saveSetup.disabled = !state.setup?.local_setup_allowed; }
});

function addMessage(role, text) {
  if (!text) return;
  ui.messages.querySelector(".welcome-message")?.remove();
  const message = document.createElement("div");
  message.className = `message ${role}`;
  const label = document.createElement("small");
  label.textContent = role === "user" ? "你" : AVATARS[formSettings().avatar]?.name || "小伙伴";
  message.append(label, document.createTextNode(text));
  ui.messages.append(message);
  while (ui.messages.children.length > 40) ui.messages.firstElementChild.remove();
  ui.messages.scrollTop = ui.messages.scrollHeight;
}
function setBusy(busy) {
  state.busy = busy;
  if (busy) { clearPetPreview(); syncPetArtwork(); }
  ui.sendButton.disabled = busy;
  ui.micButton.disabled = busy;
  ui.messageInput.disabled = busy;
  ui.switchDevice.disabled = busy;
  ui.savePreferences.disabled = busy || !state.ready;
  ui.startFocus.disabled = busy;
  ui.endFocus.disabled = busy;
  for (const button of document.querySelectorAll("[data-prompt]")) button.disabled = busy;
  updateMotionDock();
  document.querySelectorAll("[data-tone-choice]").forEach((button) => { button.disabled = busy; });
}
function requireService() {
  if (!state.configured) { openSetup(); throw new Error("请先连接语音服务，再开始对话。"); }
}
function stopPlayback() {
  streamAudio.generation++;
  streamAudio.muted = true;
  for (const source of streamAudio.sources) { source.onended = null; try { source.stop(); } catch {} source.disconnect(); }
  streamAudio.sources.clear();
  streamAudio.nextAt = 0;
  if (state.audioSource) { state.audioSource.onended = null; try { state.audioSource.stop(); } catch { /* It may already have ended. */ } state.audioSource.disconnect(); state.audioSource = null; }
  ui.stopAudio.hidden = true;
  if (!state.recorder) setMood("idle");
}
ui.stopAudio.addEventListener("click", stopPlayback);
async function getAudioContext() {
  if (!state.audioContext || state.audioContext.state === "closed") {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error("这个浏览器暂不支持声音播放，请使用新版 Edge 或 Chrome。");
    state.audioContext = new AudioContextClass();
    state.playbackAnalyser = state.audioContext.createAnalyser();
    state.playbackAnalyser.fftSize = 256;
    state.playbackAnalyser.connect(state.audioContext.destination);
    state.waveSamples = new Uint8Array(state.playbackAnalyser.fftSize);
  }
  if (state.audioContext.state === "suspended") await state.audioContext.resume();
  return state.audioContext;
}
async function decodeConversation(response) {
  if (response.headers.get("Content-Type")?.includes("application/json")) {
    const metadata = await response.json();
    return { metadata, pcm: null };
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.length < 12 || String.fromCharCode(...bytes.subarray(0, 4)) !== "LXI1") throw new Error("收到的语音响应格式不正确，请确认网页与服务版本一致。");
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const jsonLength = view.getUint32(4, true);
  const pcmLength = view.getUint32(8, true);
  if (jsonLength > 8192 || pcmLength > 16000 * 2 * 20 || 12 + jsonLength + pcmLength !== bytes.length || pcmLength % 2) throw new Error("语音响应长度异常，请重试。");
  let metadata;
  try { metadata = JSON.parse(new TextDecoder().decode(bytes.subarray(12, 12 + jsonLength))); } catch { throw new Error("语音响应信息无法读取，请重试。"); }
  const format = metadata.audio;
  if (pcmLength && (!format || format.sample_rate !== 16000 || format.bits !== 16 || format.channels !== 1)) throw new Error("服务返回了不支持的声音格式，应为 16 kHz / PCM16 / 单声道。");
  return { metadata, pcm: pcmLength ? bytes.slice(12 + jsonLength) : null };
}
async function playPCM(pcm) {
  const context = await getAudioContext();
  stopPlayback();
  const buffer = context.createBuffer(1, pcm.byteLength / 2, 16000);
  const channel = buffer.getChannelData(0);
  const samples = new DataView(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  for (let index = 0; index < channel.length; index++) channel[index] = samples.getInt16(index * 2, true) / 32768;
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(state.playbackAnalyser || context.destination);
  state.audioSource = source;
  source.onended = () => { if (state.audioSource === source) { state.audioSource = null; ui.stopAudio.hidden = true; setMood("idle"); } source.disconnect(); };
  source.start();
  ui.stopAudio.hidden = false;
  setMood("speaking");
}

async function receiveStream(response, showTranscript) {
  if (!response.body?.getReader) throw new Error("浏览器不支持流式声音，请使用新版 Edge 或 Chrome。");
  const reader = response.body.getReader();
  let pending = new Uint8Array(0);
  let magic = false, initial = false, completed = false, totalAudio = 0, frames = 0;
  const generation = ++streamAudio.generation;
  streamAudio.muted = false;
  streamAudio.nextAt = 0;
  const decoder = new TextDecoder("utf-8", { fatal: true });
  async function queueAudio(pcm) {
    if (streamAudio.muted || generation !== streamAudio.generation) return;
    const context = await getAudioContext();
    const buffer = context.createBuffer(1, pcm.length / 2, 16000);
    const channel = buffer.getChannelData(0);
    const samples = new DataView(pcm.buffer, pcm.byteOffset, pcm.byteLength);
    for (let i = 0; i < channel.length; i++) channel[i] = samples.getInt16(i * 2, true) / 32768;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(state.playbackAnalyser || context.destination);
    if (!totalAudio) ui.replyTiming.textContent = `首声 ${((performance.now() - state.requestStarted) / 1000 + .12).toFixed(1)} 秒`;
    streamAudio.nextAt = Math.max(context.currentTime + .12, streamAudio.nextAt);
    source.start(streamAudio.nextAt);
    streamAudio.nextAt += buffer.duration;
    streamAudio.sources.add(source);
    source.onended = () => {
      streamAudio.sources.delete(source);
      source.disconnect();
      if (!streamAudio.sources.size && generation === streamAudio.generation) { ui.stopAudio.hidden = true; setMood("idle"); }
    };
    ui.stopAudio.hidden = false;
    setMood("speaking");
  }
  try {
    while (!completed) {
      let timer;
      const next = await Promise.race([
        reader.read(),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("语音传输中断，请重试。")), 30000); })
      ]).finally(() => clearTimeout(timer));
      if (next.done) break;
      if (pending.length + next.value.length > 700000) throw new Error("语音响应超过大小上限。");
      const merged = new Uint8Array(pending.length + next.value.length);
      merged.set(pending); merged.set(next.value, pending.length); pending = merged;
      if (!magic && pending.length >= 4) {
        if (String.fromCharCode(...pending.subarray(0, 4)) !== "LXS1") throw new Error("流式语音协议不匹配。");
        pending = pending.slice(4); magic = true;
      }
      while (magic && pending.length >= 5) {
        const kind = String.fromCharCode(pending[0]);
        const length = new DataView(pending.buffer, pending.byteOffset, pending.byteLength).getUint32(1, true);
        if (!"JADE".includes(kind) || length > (kind === "A" ? 4096 : 8192) || ++frames > 5000) throw new Error("流式语音帧异常。");
        if (pending.length < 5 + length) { frames--; break; }
        const payload = pending.slice(5, 5 + length);
        pending = pending.slice(5 + length);
        if (kind === "A") {
          if (!initial || length % 2 || !length || totalAudio + length > 640000) throw new Error("流式声音长度异常。");
          await queueAudio(payload); totalAudio += length;
        } else {
          let metadata;
          try { metadata = JSON.parse(decoder.decode(payload)); } catch { throw new Error("无法读取流式回复信息。"); }
          if (kind === "E") throw new Error(metadata.error || "语音合成中断，请重试。");
          if (kind === "J") {
            if (initial || metadata.audio?.sample_rate !== 16000 || metadata.audio?.bits !== 16 || metadata.audio?.channels !== 1) throw new Error("声音格式不匹配。");
            initial = true;
            if (showTranscript && metadata.transcript) addMessage("user", metadata.transcript);
            if (metadata.reply) addMessage("assistant", metadata.reply);
            applyExperience(metadata.experience);
          } else {
            if (!initial || !totalAudio || metadata.audio?.bytes !== totalAudio) throw new Error("语音没有完整接收，请重试。");
            completed = true;
            if (metadata.truncated) toast("这次声音已到时长上限，完整文字在对话里。");
            const wait = Math.max(0, (streamAudio.nextAt - (state.audioContext?.currentTime || 0)) * 1000);
            const action = metadata.experience?.action;
            if (action?.type === "breathing") setTimeout(() => { if (generation === streamAudio.generation) startBreathing(); }, wait);
            loadExperience();
            if (pending.length) throw new Error("语音结束后出现异常数据。");
            break;
          }
        }
      }
    }
    if (!completed) throw new Error("语音传输提前结束，刚才的回复可能不完整。");
  } catch (error) {
    stopPlayback();
    throw error;
  } finally { try { await reader.cancel(); } catch {} reader.releaseLock(); }
}

function applyExperience(experience) {
  if (!experience) return;
  const focus = experience.focus;
  focusEndsAt = focus?.active ? Date.parse(focus.ends_at) : 0;
  if (!Number.isFinite(focusEndsAt)) focusEndsAt = 0;
  updateFocus();
  window.dispatchEvent(new CustomEvent("lingxi:experience", { detail: { focus: experience.focus } }));
}
async function loadExperience() {
  const device = state.deviceId;
  try {
    const data = await getJSON(`/api/companion/experience?device_id=${encodeURIComponent(device)}`);
    if (device !== state.deviceId) return;
    applyExperience(data);
    ui.memoryCount.textContent = `${data.memories.length} 条记忆 · 可随时删除`;
    ui.memoryList.replaceChildren();
    if (!data.memories.length) {
      const empty = document.createElement("span"); empty.className = "kit-empty"; empty.textContent = "还没有主动保存的记忆"; ui.memoryList.append(empty);
    }
    for (const memory of data.memories) {
      const chip = document.createElement("span"); chip.className = "memory-chip";
      chip.append(document.createTextNode(memory.text));
      const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "×";
      remove.setAttribute("aria-label", `忘记：${memory.text}`);
      remove.addEventListener("click", async () => {
        remove.disabled = true;
        try { const result = await (await postJSON("/api/companion/memory/delete", { device_id: device, memory_id: memory.id })).json(); await loadExperience(); toast(result.ok ? "这条记忆已删除。" : "这条记忆已经不存在了。"); }
        catch (error) { toast(error.message); remove.disabled = false; }
      });
      chip.append(remove); ui.memoryList.append(chip);
    }
  } catch { ui.memoryCount.textContent = "记忆暂未同步"; }
}
function updateFocus() {
  const seconds = Math.max(0, Math.ceil((focusEndsAt - Date.now()) / 1000));
  const defaultMinutes = Number(document.getElementById("focusMinutes")?.value || 25);
  ui.focusClock.textContent = focusEndsAt ? `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}` : `${String(defaultMinutes).padStart(2, "0")}:00`;
  ui.focusHint.textContent = seconds ? "只做眼前这一件，已经很好。" : focusEndsAt ? "这一段结束了，伸个懒腰吧。" : "先陪你完成眼前这一小步。";
  ui.startFocus.hidden = seconds > 0;
  ui.endFocus.hidden = !seconds;
}
function startBreathing() {
  breathStartedAt = performance.now();
  ui.startBreath.textContent = "结束这次呼吸";
  updateBreathing();
}
function stopBreathing() {
  breathStartedAt = 0;
  delete ui.breathOrb.dataset.phase;
  ui.breathLabel.textContent = "呼吸";
  ui.breathHint.textContent = "按你觉得舒服的节奏，随时再来。";
  ui.startBreath.textContent = "一起呼吸 60 秒 ↗";
}
function updateBreathing() {
  if (!breathStartedAt) return;
  const elapsed = (performance.now() - breathStartedAt) / 1000;
  if (elapsed >= 60) { stopBreathing(); ui.breathHint.textContent = "一分钟到了，感受一下现在的自己。"; return; }
  const inhale = elapsed % 10 < 4;
  ui.breathOrb.dataset.phase = inhale ? "inhale" : "exhale";
  ui.breathLabel.textContent = inhale ? "轻轻吸气" : "慢慢呼气";
  ui.breathHint.textContent = `第 ${Math.floor(elapsed / 10) + 1} / 6 轮 · 还剩 ${Math.ceil(60 - elapsed)} 秒`;
}
// Focus is a direct local learning action, implemented by companion-learning.js.
ui.startBreath.addEventListener("click", () => breathStartedAt ? stopBreathing() : startBreathing());
setInterval(() => { updateFocus(); updateBreathing(); }, 250);
setInterval(() => { if (!document.hidden && !state.busy && state.ready) loadExperience(); }, 15000);
async function receiveConversation(response, showTranscript) {
  if (response.headers.get("Content-Type")?.includes("application/vnd.lingxi.voice-stream")) {
    return receiveStream(response, showTranscript);
  }
  const { metadata, pcm } = await decodeConversation(response);
  if (showTranscript && metadata.transcript) addMessage("user", metadata.transcript);
  const reply = typeof metadata.reply === "string" ? metadata.reply : metadata.reply?.text || metadata.text;
  if (reply) addMessage("assistant", reply);
  applyExperience(metadata.experience);
  loadExperience();
  if (!pcm && metadata.experience?.action?.type === "breathing") startBreathing();
  if (metadata.truncated) toast("这段声音超过时长上限，已截短。完整文字仍可查看。");
  if (!reply && !pcm) throw new Error("服务没有返回对话内容，请重试。");
  if (pcm) {
    try { await playPCM(pcm); }
    catch { toast("文字回复已收到，声音未能播放。请检查浏览器声音权限。 "); setMood("idle"); }
  } else { setMood("idle", "我把想说的话，写在下面了。 "); }
}
async function sendText(text) {
  if (!text.trim() || state.busy || state.recorder) return;
  showError(ui.chatError);
  if (Array.from(text.trim()).length > 1000) {
    showError(ui.chatError, "每条消息最多 1000 字，请分两次发送。");
    return;
  }
  try { requireService(); if (ui.voiceReply.checked) await getAudioContext(); }
  catch (error) { showError(ui.chatError, error.message); return; }
  stopPlayback();
  setBusy(true);
  setMood("thinking");
  state.requestStarted = performance.now();
  ui.replyTiming.textContent = "";
  try {
    if (state.dirty) await saveSettings({ quiet: true });
    addMessage("user", text.trim());
    ui.messageInput.value = "";
    ui.messageInput.style.height = "auto";
    const response = await request("/api/companion/chat", { method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/vnd.lingxi.voice-stream" }, body: JSON.stringify({ device_id: state.deviceId, text: text.trim(), speak: ui.voiceReply.checked }) });
    await receiveConversation(response, false);
    window.dispatchEvent(new CustomEvent("lingxi:refresh-learning"));
  } catch (error) {
    if (!ui.messageInput.value.trim()) ui.messageInput.value = text;
    showError(ui.chatError, error.message);
    setMood("idle", "刚才没有连上，再试一次好吗？");
  }
  finally { setBusy(false); }
}
ui.chatForm.addEventListener("submit", (event) => { event.preventDefault(); sendText(ui.messageInput.value); });
ui.messageInput.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendText(ui.messageInput.value); } });
ui.messageInput.addEventListener("input", () => { ui.messageInput.style.height = "auto"; ui.messageInput.style.height = `${Math.min(ui.messageInput.scrollHeight, 100)}px`; });
for (const button of document.querySelectorAll("[data-prompt]")) button.addEventListener("click", () => sendText(button.dataset.prompt));
for (const button of document.querySelectorAll("[data-draft]")) button.addEventListener("click", () => {
  if (state.busy || state.recorder) return;
  ui.messageInput.value = button.dataset.draft;
  ui.messageInput.focus();
  toast(button.dataset.draft.startsWith("添加") ? "例如：添加待办：整理演示稿。具体提醒时间可在学习页设置。" : "例如：记录学习：数学25分钟，复习矩阵。");
});
ui.clearChat.addEventListener("click", () => { ui.messages.replaceChildren(); toast("已清空本页消息，服务端对话历史保持原样。"); });

function pcm16Mono(chunks, inputRate) {
  const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const input = new Float32Array(length);
  let offset = 0;
  for (const chunk of chunks) { input.set(chunk, offset); offset += chunk.length; }
  const ratio = inputRate / 16000;
  const outputLength = Math.floor(length / ratio);
  const output = new ArrayBuffer(outputLength * 2);
  const view = new DataView(output);
  for (let index = 0; index < outputLength; index++) {
    // Average the contributing input interval when downsampling. This avoids
    // treating the browser's 44.1/48 kHz samples as if they were already 16 kHz.
    const start = index * ratio;
    const end = Math.min((index + 1) * ratio, length);
    let sum = 0;
    for (let sample = Math.floor(start); sample < Math.ceil(end); sample++) sum += input[sample] * Math.max(0, Math.min(end, sample + 1) - Math.max(start, sample));
    const value = Math.max(-1, Math.min(1, sum / (end - start)));
    view.setInt16(index * 2, value < 0 ? Math.round(value * 32768) : Math.round(value * 32767), true);
  }
  return output;
}
function releaseRecorder(recorder) {
  clearTimeout(recorder.limit);
  clearInterval(recorder.ticker);
  recorder.processor.onaudioprocess = null;
  recorder.processor.disconnect();
  recorder.source.disconnect();
  recorder.silent.disconnect();
  recorder.stream.getTracks().forEach((track) => track.stop());
}
async function finishRecording({ discard = false } = {}) {
  const recorder = state.recorder;
  if (!recorder) return;
  state.recorder = null;
  releaseRecorder(recorder);
  ui.micButton.setAttribute("aria-pressed", "false");
  ui.micButton.setAttribute("aria-label", "开始录音");
  ui.inputHint.textContent = `录音最长 ${state.inputSeconds} 秒 · 声音将发送给已配置的语音服务`;
  if (discard) { setBusy(false); setMood("idle"); return; }
  setBusy(true);
  setMood("thinking", "收到啦，我来听听你说了什么。 ");
  state.requestStarted = performance.now();
  ui.replyTiming.textContent = "";
  try {
    const pcm = pcm16Mono(recorder.chunks, recorder.rate);
    if (pcm.byteLength < 16000 * 2 * 0.3) throw new Error("这次录音太短了。点击麦克风后说一句话，再次点击发送。");
    const response = await request("/api/device/conversation", { method: "POST", headers: { "Content-Type": "audio/pcm", "X-Device-Id": state.deviceId, "Accept": "application/vnd.lingxi.voice-stream" }, body: pcm });
    await receiveConversation(response, true);
  } catch (error) { showError(ui.chatError, error.message); setMood("idle", "刚才没有听清，再试一次好吗？"); }
  finally { setBusy(false); }
}
async function startRecording() {
  if (state.busy) return;
  showError(ui.chatError);
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) return showError(ui.chatError, "浏览器麦克风需要安全页面。请在这台电脑打开 http://127.0.0.1:8787/companion，或使用 HTTPS。");
  let stream;
  try {
    requireService();
    stopPlayback();
    setBusy(true);
    if (state.dirty) await saveSettings({ quiet: true });
    const context = await getAudioContext();
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const silent = context.createGain();
    silent.gain.value = 0;
    const recorder = { source, processor, silent, stream, chunks: [], rate: context.sampleRate, frames: 0, started: performance.now(), limit: null, ticker: null };
    processor.onaudioprocess = (event) => {
      if (state.recorder !== recorder) return;
      const input = event.inputBuffer.getChannelData(0);
      let squares = 0;
      for (const value of input) squares += value * value;
      listeningEnergy = Math.sqrt(squares / input.length);
      const remaining = Math.max(0, Math.round(recorder.rate * state.inputSeconds) - recorder.frames);
      if (remaining) { const chunk = input.slice(0, remaining); recorder.chunks.push(chunk); recorder.frames += chunk.length; }
    };
    source.connect(processor);
    processor.connect(silent);
    silent.connect(context.destination);
    state.recorder = recorder;
    recorder.limit = setTimeout(() => finishRecording(), state.inputSeconds * 1000);
    recorder.ticker = setInterval(() => { ui.inputHint.textContent = `正在录音 ${Math.min(state.inputSeconds, Math.floor((performance.now() - recorder.started) / 1000))} / ${state.inputSeconds} 秒 · 再次点击麦克风发送`; }, 250);
    ui.micButton.disabled = false;
    ui.micButton.setAttribute("aria-pressed", "true");
    ui.micButton.setAttribute("aria-label", "结束录音并发送");
    ui.inputHint.textContent = "正在录音 · 再次点击麦克风发送，按 Esc 取消";
    setMood("listening");
  } catch (error) {
    stream?.getTracks().forEach((track) => track.stop());
    const message = error.name === "NotAllowedError" ? "麦克风权限未开启。请点击浏览器地址栏旁的权限图标，允许此页面使用麦克风。" : error.name === "NotFoundError" ? "没有找到麦克风，请检查电脑的录音设备。" : error.message;
    showError(ui.chatError, message);
    setBusy(false);
    setMood("idle");
  }
}
ui.micButton.addEventListener("click", () => state.recorder ? finishRecording() : startRecording());
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && state.recorder) { finishRecording({ discard: true }); toast("已取消这次录音，没有发送声音。"); } });
window.addEventListener("pagehide", () => { if (state.recorder) releaseRecorder(state.recorder); stopPlayback(); });

async function initialize() {
  ui.savePreferences.disabled = true;
  const [catalogResult, setupResult] = await Promise.allSettled([getJSON("/api/companion/catalog"), getJSON("/api/companion/setup")]);
  if (catalogResult.status === "fulfilled") populateCatalog(catalogResult.value);
  else showError(ui.settingsError, catalogResult.reason.message);
  if (setupResult.status === "fulfilled") {
    applySetup(setupResult.value);
  } else {
    ui.connection.dataset.status = "error";
    ui.connectionLabel.textContent = "服务连接失败";
    showError(ui.chatError, setupResult.reason.message);
  }
  if (catalogResult.status === "fulfilled") await loadSettings();
}
window.LingXiCompanion = {
  getDeviceId: () => state.deviceId,
  getReady: () => state.ready,
  getJSON, postJSON, toast, sendText,
  reloadExperience: loadExperience,
  applyExperience
};

const pageNames = { home: "陪伴空间", study: "学习搭子", characters: "伙伴图鉴", settings: "我的偏好" };
function navigateCompanion(page, { updateHash = true, focus = true } = {}) {
  if (!pageNames[page]) page = "home";
  if (page !== "home") { clearPetPreview(); if (document.body.classList.contains("is-showcase")) setShowcaseMode(false); }
  document.querySelectorAll("[data-view]").forEach((view) => { view.hidden = view.dataset.view !== page; });
  document.querySelectorAll(".rail-nav [data-page]").forEach((link) => {
    const active = link.dataset.page === page;
    link.classList.toggle("is-current", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  document.getElementById("currentPageLabel").textContent = pageNames[page];
  document.getElementById("reminderPanel").hidden = true;
  document.getElementById("reminderToggle").setAttribute("aria-expanded", "false");
  if (updateHash && location.hash !== `#${page}`) history.replaceState(null, "", `#${page}`);
  window.scrollTo({ top: 0, behavior: "instant" });
  if (focus) { const title = document.querySelector(`[data-view="${page}"] h1`); if (title) { title.tabIndex = -1; title.focus({ preventScroll: true }); } }
  syncPetArtwork();
}
window.LingXiNavigate = navigateCompanion;
document.querySelectorAll("[data-page]").forEach((link) => link.addEventListener("click", (event) => { event.preventDefault(); navigateCompanion(link.dataset.page); }));
window.addEventListener("hashchange", () => navigateCompanion(location.hash.slice(1), { updateHash: false }));
document.querySelectorAll("[data-choose-avatar]").forEach((button) => button.addEventListener("click", async () => {
  if (state.busy || state.recorder) return toast("等这次对话结束，再迎接新伙伴吧。");
  const field = ui.preferencesForm.querySelector(`input[name="avatar"][value="${button.dataset.chooseAvatar}"]`);
  if (!field) return;
  field.checked = true;
  showAvatar(field.value); markDirty(true);
  button.disabled = true;
  try { await saveSettings({ quiet: true }); toast(`${AVATARS[field.value].name}来陪你了。`); navigateCompanion("home"); }
  catch { toast("形象还未保存，请检查服务后再试。"); }
  finally { button.disabled = false; }
}));
document.getElementById("reminderToggle").addEventListener("click", () => {
  const panel = document.getElementById("reminderPanel"); panel.hidden = !panel.hidden;
  document.getElementById("reminderToggle").setAttribute("aria-expanded", String(!panel.hidden));
});
document.getElementById("closeReminders").addEventListener("click", () => {
  document.getElementById("reminderPanel").hidden = true;
  document.getElementById("reminderToggle").setAttribute("aria-expanded", "false");
});
const shownReminderCards = new Set();
window.addEventListener("lingxi:learning", (event) => {
  const reminders = event.detail?.data?.reminders || [];
  const count = reminders.length;
  document.getElementById("reminderDot").hidden = count === 0;
  document.getElementById("reminderToggle").setAttribute("aria-label", count ? `查看事情提醒，${count}条待查看` : "查看事情提醒");
  const fresh = reminders.some((item) => !shownReminderCards.has(`${event.detail.deviceId}:${item.id}:${item.remind_at}`));
  if (fresh) {
    reminders.forEach((item) => shownReminderCards.add(`${event.detail.deviceId}:${item.id}:${item.remind_at}`));
    document.getElementById("reminderPanel").hidden = false;
    document.getElementById("reminderToggle").setAttribute("aria-expanded", "true");
  }
});
const currentHour = new Date().getHours();
document.getElementById("timeGreeting").textContent = currentHour < 5 ? "夜深了" : currentHour < 12 ? "上午好" : currentHour < 18 ? "下午好" : "晚上好";
document.getElementById("todayDate").textContent = new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "long" }).format(new Date());
navigateCompanion(location.hash.slice(1), { updateHash: false, focus: false });
loadPetAnimations();
initialize();
