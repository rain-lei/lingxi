# 蓝蓝新增日常动作源（2026-10-23）

使用 Codex 内置 imagegen 编辑，未使用 CLI/API Key 路径。身份参考为项目 V2 `public/animations/v2/previews/kangaroo-idle-poster.png`；最终原图保存在本目录 `kangaroo-extra-source.png`。`kangaroo-extra-source-v1.png` 是修改书本位置前的中间稿，不用于最终渲染。

原图为 1280 × 1280 透明 RGBA 四格图。模型没有完全遵守透明边距要求，打包阶段使用扩展窗口与最大连通主体提取，再统一尺度和脚底位置；不直接沿格边裁掉尾尖。输出为欢迎、专注、困倦、伸展四姿态。

## 校标

生成源的胸口刻意留空。全部最终动画使用 `assets/mascot-v3/dlut-badge.png` 官方图层合成；蓝毛手爪保留前景遮挡。来源、许可说明沿用 `assets/mascot-v3/SOURCES.md`。专注姿态先把书本移到腿上，给胸前校标留出完整空间。最终四张海报已经逐一目检校标、轮廓和尾尖。

### 2026-10-23 胸口定位修订 `badge-center-r2`

本次按每张源姿态的乳白胸腹区域重新设置校标锚点与尺寸。锚点是角色胸口的坐标，不是整张图或透明画布的中心；源格坐标经过主体提取、裁切、统一比例及基线变换后，转换到 512 × 512 规范纹理。

校标在纹理采样时与角色合成，随后随该姿态的呼吸、躯干、手臂与整体动作使用同一套坐标变形。蓝毛手爪仍保留在校标前方；专注姿态的书在腿部，不以浮在手上方的贴图补齐被遮挡部分。合成保持原主体 alpha，不把校标画到角色轮廓外。

蓝蓝十段动画的海报、透明 APNG 与板端 GIF 文件名均加入 `-badge-center-r2`，并更新目录 URL。锚点记录参与构建缓存 fingerprint，避免继续复用居中修订前的画面。完整修订与验证说明见项目根目录 `docs/BADGE_CENTERING_20261023.md`；实机写卡状态以该说明中单独补充的安装记录为准。

## 内置工具提示词

### 第一轮：新增四姿态

```text
Use case: identity-preserve. Create a production-ready 2 by 2 transparent RGBA pose atlas of EXACTLY the same adorable blue plush kangaroo companion as reference. Premium stylized 3D toy rendering, fine dense blue microfiber fur, same long asymmetrical upright ears, oversized warm brown eyes, round dark brown felt nose, soft cream chest and belly, tiny round paws, thick curved blue tail, friendly slightly dopey personality, consistent color, soft studio light, camera and scale. Four separate whole-body poses in equal square cells, each cell contains ONE complete kangaroo with tail, ears, all hands and feet uncut, with at least 60px transparent gutter on ALL four sides. Canvas exactly square, 1024x1024 or greater square; invisible 2x2 grid. Pose top-left GREETING: seated, right hand lifted in warm open-paw wave, bright gentle open eyes, closed friendly smiling mouth. Pose top-right FOCUS: seated reading a small elegant cream and light blue open notebook held LOW below chest so cream chest remains visible; eyes looking down attentively, serious but cute. Pose bottom-left SLEEPY: seated relaxed shoulders, eyes fully gently closed, head leaning slightly, paws in lap, sweet small sleeping smile, tail resting. Pose bottom-right STRETCH: seated energetic full stretch with both short arms reaching upward OUTSIDE ears, big happy closed-eye smile, back straight, paws and tail complete. No text, no letters, no speech bubbles, no stars, no ground, no checkerboard. IMPORTANT leave chest BLANK CREAM without any logo or text in all four poses: official university emblem is composited exactly from the original official vector by application after generation. Maintain identical body and consistent warm fine 3D material. Do not change into rabbit, dog or human; do not give fingers or clothes. Render all 4 subjects at same apparent sitting body size, consistent baseline, perfectly isolated transparent alpha, no scene background, no cropping.
```

### 第二轮：把书移到腿上，保留胸前空间

```text
Precise object edit of this 2x2 transparent plush blue kangaroo pose atlas. Preserve the entire top-left greeting pose, bottom-left sleepy pose, bottom-right stretching pose and identical character, fur, lighting, camera, positions and scale. ONLY change TOP-RIGHT reading pose: move the small open book MUCH LOWER, resting on the lap between the feet. Both paws hold the lower left and lower right edges of the book down at belly/lap level. The entire upper cream chest must be fully visible, from neck down to mid-belly, with a large empty oval region 120x120 pixels centered on the chest reserved for an official embroidered round university patch added later. Book may not overlap this empty cream chest region. Tilt eyes slightly down to the book, keep all same body proportions and complete tail/ears/feet. All four cream chests stay blank no logos/no text. Isolated TRUE transparent RGBA, retain 2x2 layout, complete silhouettes with clean transparent gutters. Do not add background, shadows on ground, symbols, written letters or watermark. Original reference is the final material and identity, do not redesign.
```

## 动画与编码

`tools/tf_animation_renderer_v3.c` 对静态纹理做局部头、耳、手、尾、呼吸与收势动作；这是 3D 风格的二维贴图动画，不是实时 3D 模型或音素口型同步。

蓝蓝新增四个真实姿态。`badge-center-r2` 修订后，**蓝蓝全部十段高清动画及板端动画均重新渲染**：前六段仍以 V2 原始高分辨率姿态纹理为来源，但不再直接复用 V2 的已合成 APNG；后四段使用本目录新增四姿态源。

其他四位伙伴的流程保持原样：前六段高清素材继续复用已验证的 V2 APNG，板端重新采样为 50 ms 调度；新增四动作沿用原高分辨率姿态并使用新的局部运动节奏，没有为它们冒充新增图像源。本次校标修订前后，这四位伙伴合计四十段板端 clip 的载荷经比较保持逐字节一致。

`tools/build_tf_animation_v3.py` 生成 50 段、2,700 张板端帧；LXAF 协议 v2 使用逐帧 RLE3 无损压缩 RGB565LE+alpha8，包含逐帧目录、body SHA-256 和分段 CRC。20 fps 是素材时间表，实际 LCD 帧率以实板 `/api/display` 测量为准。校标已经合成的元数据分别声明网页与板端，避免隐藏错误的备用图层。
