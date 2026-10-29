"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
  const state = { manifest: null, fontManifest: null, version: 1, avatar: "kangaroo", clip: "idle", view: "hd", paused: false, animated: false, manualPlay: false, mediaSrc: "", revision: 0, previewRevision: 0, previewPending: null, sequence: false, sequenceStep: 0, sequenceTimer: null, touchTimer: null };
  const portraits = { kangaroo: "/assets/mascot-kangaroo-preview.png", robot: "/assets/mascot-robot-preview.png", cat: "/assets/companion-cat.png", otter: "/assets/companion-otter.png", sprout: "/assets/companion-sprout.png" };
  const roles = { kangaroo: "你的大工小伙伴", robot: "认真又有点呆萌", cat: "软软的温柔搭子", otter: "陪你慢慢读懂", sprout: "和你一起长大" };
  const characters = ["kangaroo", "robot", "cat", "otter", "sprout"];
  const labels = { idle: "眨眨眼", listening: "听你说", thinking: "想一想", speaking: "说点什么", comfort: "抱抱你", celebrate: "好开心", greeting: "来啦你好", focus: "一起专注", sleepy: "晚安时刻", stretch: "伸个懒腰" };
  const descriptions = { idle: "偶尔发发呆，也会认真等你。", listening: "你慢慢说，我把耳朵借给你。", thinking: "让我好好想想，再给你一个答案。", speaking: "想说的有好多，先从这一句开始。", comfort: "没关系，今天也可以慢一点。", celebrate: "这件小事，值得为你开心！", greeting: "看见你的一瞬间，就想挥挥小手。", focus: "翻开书，我陪你把这一页慢慢读完。", sleepy: "辛苦了一天，现在可以好好休息啦。", stretch: "伸伸小爪子，给认真生活的你充一点电。" };
  const speech = { idle: "你来啦，我一直都在。", listening: "嗯嗯，我在认真听。", thinking: "唔……让我想一想。", speaking: "我有个小小的想法！", comfort: "给你一个软软的抱抱。", celebrate: "你做到了，真好呀！", greeting: "是你呀，今天也想见到你。", focus: "这一页，我陪你一起读。", sleepy: "晚安，把今天轻轻放下。", stretch: "伸个懒腰，再慢慢出发！" };
  const iconPaths = { idle: "M20 14A8 8 0 0 1 10 4a8 8 0 1 0 10 10ZM16 3h4m-4 4h4m-2-4v4", listening: "M8 14a6 6 0 1 1 10-4c0 4-5 4-5 7a3 3 0 0 1-6 0m4-6a2 2 0 1 1 4-1M4 8 2 7m2 5H2m3 4-2 1", thinking: "M9 17h6m-6 3h6M8 13a6 6 0 1 1 8 0c-1 1-1 2-1 3H9c0-1 0-2-1-3ZM12 2V1M4 5 3 4m17 1 1-1M3 12H1m20 0h2", speaking: "M20 11a8 8 0 0 1-8 8H5l-4 3 2-7a8 8 0 1 1 17-4ZM7 10h.1M12 10h.1M17 10h.1M8 14q4 3 8 0", comfort: "M12 20 4 12a5 5 0 0 1 7-7l1 1 1-1a5 5 0 0 1 7 7l-8 8ZM4 17l-2 2m18-2 2 2", celebrate: "m7 10-5 12 12-5-7-7ZM9 2l1 4m8-2-3 4m7 3-4 1m1 6 3 2M13 2h.1M21 5h.1M4 6h.1" };
  Object.assign(iconPaths, { greeting: "M9 12V4a1.5 1.5 0 0 1 3 0v7m0-6a1.5 1.5 0 0 1 3 0v7m0-5a1.5 1.5 0 0 1 3 0v8c0 4-2 7-6 7h-1c-2 0-3-1-4-3l-4-6a1.5 1.5 0 0 1 2-2l4 4M4 3 2 1m18 3 2-2", focus: "M12 5C9 3 5 3 2 4v15c4-1 7-1 10 1 3-2 6-2 10-1V4c-3-1-7-1-10 1Zm0 0v15M5 8h4M5 12h4M15 8h4M15 12h4", sleepy: "M20 14A8 8 0 0 1 10 4a8 8 0 1 0 10 10ZM16 3h5l-5 5h5", stretch: "M12 7v9m0-5L5 5m7 6 7-6M4 2v4h4m12-4v4h-4M12 16l-4 6m4-6 4 6M12 2h.01" });
  const node = (tag, className, value) => { const element = document.createElement(tag); if (className) element.className = className; if (value !== undefined) element.textContent = value; return element; };
  function icon(id) { const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); const path = document.createElementNS("http://www.w3.org/2000/svg", "path"); path.setAttribute("d", iconPaths[id] || iconPaths.idle); svg.append(path); return svg; }
  function bytes(value) { const number = Number(value); if (!Number.isFinite(number) || number < 0) return "—"; return number >= 1024 ** 2 ? `${(number / 1024 ** 2).toFixed(1)} MiB` : number >= 1024 ? `${(number / 1024).toFixed(1)} KiB` : `${number} B`; }
  function assetURL(value, extensions) {
    if (typeof value !== "string" || !value.startsWith("/")) return null;
    try { const url = new URL(value, location.origin); if (url.origin !== location.origin || url.search || url.hash || !(/^\/animations\/v[123]\//.test(url.pathname) || url.pathname.startsWith("/downloads/") || url.pathname.startsWith("/fonts/v1/"))) return null; if (extensions && !extensions.some((extension) => url.pathname.toLowerCase().endsWith(extension))) return null; return url.pathname; } catch { return null; }
  }
  function avatarNow() { return state.manifest?.avatars.find((item) => item.id === state.avatar); }
  function clipNow() { const avatar = avatarNow(); return avatar?.clips.find((item) => item.id === state.clip) || avatar?.clips[0]; }
  function setBadge(avatar, clip, portrait = false) {
    const badge = $("staticBadge");
    // V1 board exports were inspected with the official badge included. New
    // assets must explicitly state that their own visible badge is baked in.
    const modeFlag = state.view === "hd" ? clip?.web_badge_baked : clip?.board_badge_baked;
    const baked = !portrait && (typeof modeFlag === "boolean" ? modeFlag : clip?.badge_baked === true || avatar.badge_baked === true || state.view === "board" && state.version === 1);
    badge.hidden = avatar.id !== "kangaroo" || baked;
    const centers = { idle: [53.5, 71.8], listening: [51, 72.3], thinking: [54.3, 69.9], speaking: [49.4, 67.4], comfort: [50.2, 68.2], celebrate: [49.4, 67.4] };
    const center = portrait ? centers.idle : centers[clip?.id] || centers.idle;
    badge.style.left = `${center[0]}%`; badge.style.top = `${center[1]}%`;
  }
  function disableLink(element) { element.removeAttribute("href"); element.removeAttribute("download"); element.classList.add("is-disabled"); element.setAttribute("aria-disabled", "true"); element.tabIndex = -1; }
  function enableLink(element, file, url) { element.href = url; element.download = typeof file.filename === "string" ? file.filename.replace(/[\\/]/g, "_") : url.split("/").pop(); element.classList.remove("is-disabled"); element.setAttribute("aria-disabled", "false"); element.removeAttribute("tabindex"); }
  async function verifyFile(file, extensions, allowed = true) {
    const url = file && assetURL(file.url, extensions), expected = Number(file?.size_bytes); if (!url || !allowed || !Number.isSafeInteger(expected) || expected <= 0) return null;
    try { const response = await fetch(url, { method: "HEAD", cache: "no-store", signal: AbortSignal.timeout(10000) }); if (!response.ok) return null; const length = Number(response.headers.get("Content-Length")); return length === expected ? url : null; } catch { return null; }
  }
  async function loadFonts() {
    disableLink($("fontArchiveDownload"));
    try {
      const response = await fetch("/fonts/v1/manifest.json", { cache: "no-store", signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error("字体目录暂未就绪");
      const manifest = await response.json();
      if (manifest.schema_version !== 1 || !Array.isArray(manifest.fonts) || !["warm", "calm", "cheerful", "direct"].every((id) => manifest.fonts.some((font) => font.id === id && font.tone === id))) throw new Error("四套语气字体尚未齐备");
      state.fontManifest = manifest;
      const file = { url: manifest.archive?.path, size_bytes: manifest.archive?.bytes, filename: "lingxi-tf-fonts-v1.zip" };
      const url = await verifyFile(file, [".zip"]);
      if (!url) throw new Error("字体包正在核对，稍后重新读取即可");
      enableLink($("fontArchiveDownload"), file, url);
      $("fontArchiveSize").textContent = bytes(file.size_bytes);
      $("fontPackageStatus").textContent = "4 套独立字形 · 字体包文件已核对";
      const cardPath = typeof manifest.card_path === "string" && /^\/lingxi\/[a-zA-Z0-9_.-]+\.lxff$/.test(manifest.card_path) ? manifest.card_path.slice(1) : "lingxi/fonts-v1.lxff";
      $("fontCardPath").textContent = cardPath;
      if (state.manifest) renderIntegrity(state.manifest);
    } catch (error) {
      $("fontPackageStatus").textContent = error.message || "字体包暂未载入，稍后可以重新读取";
      $("fontArchiveSize").textContent = "待核对";
    }
  }
  function setPauseLabel() { $("pausePreview").setAttribute("aria-pressed", String(state.paused)); $("pausePreview").querySelector("span").textContent = state.paused ? "播放" : "暂停"; $("pausePreview").querySelector("use").setAttribute("href", state.paused ? "#play" : "#pause"); $("previewStage").classList.toggle("is-paused", state.paused); }
  function freezePreview() {
    if (!state.animated) return;
    const image = $("previewImage"), canvas = $("pausedFrame");
    try { canvas.width = image.naturalWidth; canvas.height = image.naturalHeight; canvas.getContext("2d").drawImage(image, 0, 0); canvas.hidden = false; image.hidden = true; state.paused = true; } catch { state.paused = false; }
    setPauseLabel();
  }
  function resumePreview() { if (!state.animated) return; state.manualPlay = true; $("pausedFrame").hidden = true; $("previewImage").hidden = false; if ($("previewImage").getAttribute("src") !== state.mediaSrc) $("previewImage").src = state.mediaSrc; state.paused = false; setPauseLabel(); }
  function stopSequence(freeze = false) { clearTimeout(state.sequenceTimer); state.sequenceTimer = null; state.sequence = false; $("playSequence").setAttribute("aria-pressed", "false"); $("playSequence").querySelector("span").textContent = "看看它的一天"; $("playSequence").querySelector("use").setAttribute("href", "#play"); if (freeze) freezePreview(); }
  function scheduleSequence() {
    clearTimeout(state.sequenceTimer); if (!state.sequence || document.hidden) return;
    const clip = clipNow(); const duration = Number(state.view === "hd" ? clip?.web_duration_ms || clip?.duration_ms : clip?.duration_ms) || 3000;
    state.sequenceTimer = setTimeout(() => { const clips = avatarNow()?.clips || []; if (state.sequenceStep + 1 >= clips.length) { stopSequence(); $("sequenceNote").textContent = "一圈小动作看完啦。喜欢哪个，就再点一次。"; $("interactionStatus").textContent = `${clips.length} 个动作连播完成`; return; } state.sequenceStep += 1; state.clip = clips[state.sequenceStep].id; renderClip(); }, Math.max(1000, Math.min(duration, 10000)));
  }
  function renderAvatarChoices() {
    $("avatarPicker").replaceChildren();
    for (const avatar of state.manifest.avatars) { const button = node("button", "avatar-button"); button.type = "button"; button.dataset.avatar = avatar.id; button.setAttribute("aria-pressed", String(avatar.id === state.avatar)); button.setAttribute("aria-label", `选择${avatar.name}`); const image = document.createElement("img"); image.src = assetURL(avatar.portrait_url || avatar.clips.find((clip) => clip.id === "idle")?.web_poster_url, [".png", ".webp"]) || portraits[avatar.id] || portraits.kangaroo; image.alt = ""; button.append(image, node("span", "", avatar.name)); button.addEventListener("click", () => { stopSequence(); state.avatar = avatar.id; renderAvatarChoices(); renderClip(); }); $("avatarPicker").append(button); }
  }
  function renderMotionChoices(avatar) {
    $("statePicker").replaceChildren();
    $("motionCount").textContent = String(avatar.clips.length).padStart(2, "0");
    for (const clip of avatar.clips) { const button = node("button", "state-button"); button.type = "button"; button.setAttribute("aria-pressed", String(clip.id === state.clip)); button.setAttribute("aria-label", clip.label || labels[clip.id] || clip.id); button.title = clip.label || labels[clip.id] || clip.id; const seconds = Number(state.view === "hd" ? clip.web_duration_ms || clip.duration_ms : clip.duration_ms) / 1000; button.append(icon(clip.id), node("span", "", labels[clip.id] || clip.label || clip.id)); if (seconds > 0) button.append(node("small", "", `${seconds.toFixed(1)}s`)); button.addEventListener("click", () => { stopSequence(); state.clip = clip.id; renderClip(); }); $("statePicker").append(button); }
  }
  function showPortrait(avatar, message) {
    state.animated = false; state.paused = false; state.mediaSrc = ""; $("pausedFrame").hidden = true; $("previewImage").hidden = false; $("previewImage").onload = null; $("previewImage").onerror = null; $("previewImage").src = portraits[avatar.id] || portraits.kangaroo; $("previewImage").alt = `${avatar.name}的高清静态形象`; setBadge(avatar, null, true); $("previewKind").textContent = message; $("pausePreview").disabled = true; $("playSequence").disabled = true; $("sequenceNote").textContent = "高清动画生成后，这里将开放动作连播。"; setPauseLabel(); stopSequence();
  }
  function renderClip() {
    const avatar = avatarNow(); if (!avatar) return;
    const clip = clipNow(); state.clip = clip?.id || "idle"; const previewRevision = ++state.previewRevision;
    if (state.previewPending) { state.previewPending.onload = state.previewPending.onerror = null; state.previewPending.removeAttribute("src"); state.previewPending = null; }
    $("previewStage").dataset.avatar = avatar.id; $("previewStage").dataset.view = state.view;
    $("selectedAvatar").textContent = avatar.name; $("characterNumber").textContent = `NO. ${String(characters.indexOf(avatar.id) + 1).padStart(2, "0")}`; $("characterRole").textContent = roles[avatar.id] || "愿意陪你的伙伴";
    $("selectedClip").textContent = clip?.label || "待机眨眼"; $("clipDescription").textContent = clip?.description || descriptions[state.clip] || "小小动作，陪你慢慢度过。"; $("petSpeech").textContent = speech[state.clip] || speech.idle;
    $("petTouch").setAttribute("aria-label", `摸摸${avatar.name}，${avatar.clips.some((item) => item.id === "celebrate" && item.web_preview_url) ? "播放庆祝动作" : "打个招呼"}`); $("petTouch").disabled = state.view === "board"; $("viewHD").setAttribute("aria-pressed", String(state.view === "hd")); $("viewBoard").setAttribute("aria-pressed", String(state.view === "board"));
    renderMotionChoices(avatar);
    const highURL = clip && assetURL(clip.web_preview_url, [".webp", ".png", ".apng", ".gif"]), boardURL = clip && assetURL(clip.preview_url, [".gif", ".webp", ".png"]);
    const url = state.view === "hd" ? highURL : boardURL;
    const webFrames = Number(clip?.web_frame_count) || 0, webFps = Number(clip?.web_fps || state.manifest.web_fps) || 0;
    const frames = state.view === "hd" ? webFrames : Number(clip?.frame_count) || 0;
    const duration = Number(state.view === "hd" ? clip?.web_duration_ms || clip?.duration_ms : clip?.duration_ms);
    $("clipTiming").textContent = `${duration > 0 ? `${(duration / 1000).toFixed(1)} 秒` : "—"}${clip?.loop === false ? " · 单次动作" : " · 循环动作"}`;
    $("resolutionNote").textContent = state.view === "hd" ? highURL ? "高清观赏保留原始材质与透明边缘；设备中的角色区域为 128 × 128，可切换查看。" : "正在使用高清静态肖像。新版高清动画仍在制作；板端实际可查看已有动作。" : "这里按 128 × 128 原始像素显示角色区域；设备实际帧率与文字排版以插卡实测为准。";
    $("stageLabel").textContent = state.view === "hd" ? "伙伴观察室" : "设备像素预览";
    if (!url) { showPortrait(avatar, state.view === "hd" ? "高清静态形象 · 动画整理中" : "板端动作暂未载入"); return; }
    state.animated = frames > 1; state.paused = false; state.manualPlay = false; state.mediaSrc = `${url}?play=${previewRevision}`;
    const poster = state.view === "hd" && clip ? assetURL(clip.web_poster_url, [".webp", ".png"]) : null;
    const initialSource = state.animated && motionPreference.matches && !state.sequence && poster ? poster : state.mediaSrc;
    const image = new Image(); image.id = "previewImage"; image.decoding = "async"; image.draggable = false; state.previewPending = image;
    $("previewKind").textContent = "正在载入新的小动作…"; $("pausePreview").disabled = true; $("playSequence").disabled = true; setPauseLabel();
    image.alt = `${avatar.name} · ${clip?.label || labels[state.clip] || "动画"}${state.view === "hd" ? "高清预览" : "板端实际像素"}`;
    image.onload = async () => {
      if (previewRevision !== state.previewRevision) return;
      try { if (image.decode) await image.decode(); } catch { if (!image.naturalWidth) { image.onerror?.(); return; } }
      if (previewRevision !== state.previewRevision) return;
      if (!image.naturalWidth) { image.onerror?.(); return; }
      const previous = $("previewImage"); previous.replaceWith(image); previous.onload = previous.onerror = null; previous.removeAttribute("src"); state.previewPending = null;
      image.onload = null; image.hidden = false; $("pausedFrame").hidden = true; setBadge(avatar, clip);
      const width = image.naturalWidth;
      $("previewKind").textContent = state.view === "hd" ? `高清 ${width} px${webFps ? ` · 素材 ${webFps} fps` : ""}` : `实际 ${state.manifest.frame_size?.width || 128} × ${state.manifest.frame_size?.height || 128} · ${frames} 帧`;
      $("pausePreview").disabled = !state.animated; $("playSequence").disabled = !state.animated; $("sequenceNote").textContent = state.sequence ? "动作连播中。点任意动作，留下你喜欢的表情。" : `按顺序看看 ${avatar.clips.length} 个动作，随时可以停下。`;
      if (motionPreference.matches && !state.sequence && !state.manualPlay) freezePreview();
      if (state.sequence) scheduleSequence();
    };
    image.onerror = () => { if (previewRevision !== state.previewRevision) return; image.onload = image.onerror = null; image.removeAttribute("src"); state.previewPending = null; showPortrait(avatar, "动画暂未载入 · 高清静态形象"); $("resolutionNote").textContent = "这个预览文件暂未就绪，可以重新读取素材，或切换板端实际查看已有动作。"; };
    image.src = initialSource;
  }
  function renderIntegrity(manifest) {
    $("integrityList").replaceChildren();
    const entries = [["资源版本", manifest.pack_id], ["TF 动画包", manifest.archive?.sha256], ["板端 LXAF", manifest.download?.sha256], ["固件压缩包", manifest.firmware?.sha256]];
    if (manifest.web_archive) entries.push(["高清离线包", manifest.web_archive.sha256]);
    if (state.fontManifest) entries.push(["四语气字体包", state.fontManifest.archive?.sha256]);
    for (const [label, value] of entries) { const row = node("div"); row.append(node("dt", "", label), node("dd", "", value || "尚未生成")); $("integrityList").append(row); }
  }
  function hardwareStatusText(manifest) {
    const validation = manifest.hardware_validation;
    const sameHash = (left, right) => typeof left === "string" && typeof right === "string" && /^[0-9a-f]{64}$/i.test(left) && left.toLowerCase() === right.toLowerCase();
    const matchingInstall = manifest.installation_verified === true
      && validation?.scope === "current_connected_device"
      && sameHash(validation.animation_sha256, manifest.download?.sha256)
      && (!validation.firmware_binary_sha256 || sameHash(validation.firmware_binary_sha256, manifest.firmware?.binary_sha256));
    if (!matchingInstall) return manifest.hardware_verified === true
      ? "资源已完成发布记录中的实板验证，你的卡仍需首次识别。"
      : "首次需先更新配套固件。当前尚未完成你的 TF 卡实测。";
    const parts = ["本次接入设备：动画已写入并校验。"];
    const fps = validation.measured_fps;
    const seconds = validation.fps_sample_seconds;
    const context = typeof validation.fps_context === "string" ? validation.fps_context.replace(/\s+/g, " ").trim().slice(0, 40) : "";
    // A measured result needs a real sampling window and scene description.
    // manifest.fps is only the source schedule and is never used here.
    if (typeof fps === "number" && Number.isFinite(fps) && fps > 0 && fps <= 240
      && typeof seconds === "number" && Number.isFinite(seconds) && seconds >= 1 && context) {
      parts.push(`${context}实测约 ${fps.toFixed(1)} fps（采样 ${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} 秒）。`);
    }
    if (validation.font_installation_verified === true && sameHash(validation.font_sha256, manifest.fonts?.download?.sha256)) {
      const styles = new Set(Array.isArray(validation.fonts_loaded) ? validation.fonts_loaded : []);
      parts.push(["warm", "calm", "cheerful", "direct"].every((id) => styles.has(id))
        ? "四套语气字体已写入并加载。" : "语气字体已写入并校验。");
    }
    const pending = [];
    if (validation.visual_confirmed !== true) pending.push("视觉");
    if (validation.buttons_confirmed !== true) pending.push("按键");
    parts.push(pending.length ? `${pending.join("与")}仍待人工确认。` : "视觉与按键已完成人工确认。");
    return parts.join("");
  }
  async function readManifest(version) {
    const response = await fetch(`/animations/v${version}/manifest.json`, { cache: "no-store", signal: AbortSignal.timeout(10000) }); if (!response.ok) throw new Error(`素材目录暂不可用（HTTP ${response.status}）`);
    const value = await response.json();
    if (version >= 2 && (value.web_ready === false || value.ready === false)) throw new Error("高清动作仍在完成最后检查");
    if (value.schema_version !== 1 || !Array.isArray(value.avatars)) throw new Error("素材目录格式不匹配");
    const avatars = value.avatars.filter((avatar) => avatar && typeof avatar.id === "string" && typeof avatar.name === "string" && Array.isArray(avatar.clips) && avatar.clips.length);
    if (!avatars.length) throw new Error("素材目录还没有可用的小伙伴"); return { ...value, avatars };
  }
  async function load() {
    const revision = ++state.revision; stopSequence(); $("pageError").hidden = true; $("retryLoad").disabled = true; $("packageStatus").textContent = "正在核对文件"; $("webArchiveDownload").hidden = true; ["archiveDownload", "packDownload", "firmwareDownload", "webArchiveDownload"].forEach((id) => disableLink($(id)));
    try {
      let manifest, version = 3;
      for (const candidate of [3, 2, 1]) { try { manifest = await readManifest(candidate); version = candidate; break; } catch (error) { if (candidate === 1) throw error; } }
      if (revision !== state.revision) return;
      state.manifest = manifest; state.version = version;
      if (!manifest.avatars.some((item) => item.id === state.avatar)) state.avatar = manifest.avatars[0].id;
      renderAvatarChoices(); renderClip(); renderIntegrity(manifest);
      const count = manifest.avatars.reduce((sum, avatar) => sum + avatar.clips.length, 0);
      $("avatarCount").textContent = `${manifest.avatars.length} 位伙伴 · ${count} 段动作`;
      $("packageSize").textContent = `卡上 ${bytes(manifest.download?.size_bytes)}`; $("frameSize").textContent = `${manifest.frame_size?.width || "—"} × ${manifest.frame_size?.height || "—"} · ${manifest.fps || "—"} fps 素材`;
      const date = new Date(manifest.created_at); $("updatedAt").textContent = Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(date) : "—";
      const format = Number(manifest.format_version) || 1;
      const compatibleFirmware = Boolean(format < 2 || Number(manifest.firmware?.animation_format_version) >= format || manifest.firmware?.supported_lxaf_versions?.includes(format));
      const [archive, pack, firmware, webArchive] = await Promise.all([verifyFile(manifest.archive, [".zip"]), verifyFile(manifest.download, [".lxaf"]), verifyFile(manifest.firmware, [".bin", ".zip"], manifest.firmware?.ready === true && compatibleFirmware), verifyFile(manifest.web_archive, [".zip"])]);
      if (revision !== state.revision) return;
      if (archive) enableLink($("archiveDownload"), manifest.archive, archive); if (pack) enableLink($("packDownload"), manifest.download, pack); if (firmware) enableLink($("firmwareDownload"), manifest.firmware, firmware);
      if (webArchive) { enableLink($("webArchiveDownload"), manifest.web_archive, webArchive); $("webArchiveSize").textContent = `（${bytes(manifest.web_archive.size_bytes)}）`; $("webArchiveDownload").hidden = false; }
      $("packageStatus").textContent = archive && pack ? "资源已就绪" : archive || pack ? "部分资源已就绪" : "资源正在整理";
      $("archiveSize").textContent = archive ? bytes(manifest.archive.size_bytes) : "整理中";
      $("downloadNote").textContent = archive && pack ? "TF 动画包内含卡上资源、板端 GIF 和安装说明。高清预览留在电脑，无需复制上卡。" : "入口只在真实文件就绪后开放。稍后可重新读取素材。";
      $("previewStatus").textContent = version >= 2 ? `V${version} · ${count} 段高清动作` : "V1 可用 · 高清版制作中";
      $("firmwareStatus").textContent = firmware ? `配套固件可下载 · ${bytes(manifest.firmware.size_bytes)}` : "配套固件尚未就绪";
      $("hardwareStatus").textContent = hardwareStatusText(manifest);
      $("formatNotice").hidden = format < 2;
      $("formatNotice").textContent = format >= 2 ? "V3 使用 LXAF 2 无损压缩格式。必须先更新明确支持 LXAF 2 的配套固件，旧版 LXAF 1 固件无法读取。" : "";
      if (manifest.install?.copy_instructions) $("copyInstructions").textContent = manifest.install.copy_instructions;
      if (manifest.install?.wifi_instructions) $("wifiInstructions").textContent = manifest.install.wifi_instructions;
      $("wifiStatus").textContent = "板子使用已配置的 Wi-Fi 向电脑取文件。保持电脑服务运行，手机提示无互联网正常。";
    } catch (error) {
      if (revision !== state.revision) return;
      $("pageErrorText").textContent = error instanceof TypeError ? "无法连接本机服务。双击项目中的 start_animations.cmd，再刷新此页。" : `${error.message}。请确认灵犀服务仍在运行，再重新读取。`;
      $("pageError").hidden = false; $("packageStatus").textContent = "目录暂未读取"; $("previewStatus").textContent = "等待素材目录"; $("downloadNote").textContent = "暂未取得素材目录，下载入口保持关闭。";
    } finally { if (revision === state.revision) $("retryLoad").disabled = false; }
  }
  $("viewHD").addEventListener("click", () => { stopSequence(); state.view = "hd"; renderClip(); });
  $("viewBoard").addEventListener("click", () => { stopSequence(); state.view = "board"; renderClip(); });
  $("pausePreview").addEventListener("click", () => { if (!state.animated) return; if (state.paused) resumePreview(); else { stopSequence(); freezePreview(); } });
  $("playSequence").addEventListener("click", () => {
    if (state.sequence) { stopSequence(true); $("sequenceNote").textContent = "停在这一刻。点播放，就能继续看这个动作。"; return; }
    state.sequence = true; state.sequenceStep = 0; state.clip = avatarNow().clips[0].id; $("playSequence").setAttribute("aria-pressed", "true"); $("playSequence").querySelector("span").textContent = "停在这一刻"; $("playSequence").querySelector("use").setAttribute("href", "#pause"); renderClip();
  });
  $("petTouch").addEventListener("click", (event) => {
    if (state.view !== "hd" || !avatarNow()) return;
    const celebrate = avatarNow().clips.find((clip) => clip.id === "celebrate"); if (!celebrate?.web_preview_url) { $("petSpeech").textContent = "收到你的小小招呼啦。"; $("interactionStatus").textContent = "收到你的小小招呼"; return; }
    stopSequence(); state.clip = celebrate.id; renderClip(); $("petSpeech").textContent = "被你摸摸，开心加一！"; $("interactionStatus").textContent = `${avatarNow().name}收到了摸摸，正在播放庆祝动作`;
    const rect = $("previewStage").getBoundingClientRect(); const hasPointer = event.detail > 0; $("previewStage").style.setProperty("--ripple-x", `${hasPointer ? event.clientX - rect.left : rect.width / 2}px`); $("previewStage").style.setProperty("--ripple-y", `${hasPointer ? event.clientY - rect.top : rect.height / 2}px`);
    $("previewStage").classList.remove("is-touched"); void $("previewStage").offsetWidth; $("previewStage").classList.add("is-touched"); clearTimeout(state.touchTimer); state.touchTimer = setTimeout(() => $("previewStage").classList.remove("is-touched"), 700);
  });
  // The rendered joints provide the motion. Keep the artwork plane fixed so
  // dragging the pointer cannot turn a waving hand into a moving photograph.
  motionPreference.addEventListener("change", (event) => { if (event.matches) { stopSequence(); freezePreview(); } });
  document.addEventListener("visibilitychange", () => { if (document.hidden) { stopSequence(); if (state.animated && !state.paused) freezePreview(); } });
  $("retryLoad").addEventListener("click", () => { load(); loadFonts(); });
  load();
  loadFonts();
})();
