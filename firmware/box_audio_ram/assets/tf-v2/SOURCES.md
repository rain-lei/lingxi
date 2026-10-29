# 动作精修 v2 素材

日期：2026-10-21。沿用蓝蓝、小犀、奶泡、团团、芽芽的角色身份。

## 新的完整轮廓源

- `kangaroo-poses-v2-source.png`：使用 Codex 内置 imagegen 编辑既有蓝蓝六姿态，保留蓝色毛绒、棕鼻、圆眼、奶油肚和坐姿。胸口留空，供渲染器合成官方校标。完整请求与检查说明见 `kangaroo-prompt.txt`。
- `sprout-poses-v2.png`：同样使用内置 imagegen 编辑既有芽芽，补全原图在格边被裁掉的尾尖与叶片。提示词和检查记录见 `sprout-prompt-v2.txt`、`sprout-SOURCES-v2.md`。

两张图片均为真实 RGBA，alpha 范围 0–254。生成模型没有完全遵守预留透明边距要求，因此边距由普通图集打包阶段完成；不能将源图未经检查直接按格裁成纹理。蓝蓝尾尖延伸到相邻格空白，需使用扩展窗口和最大连通区域恢复完整轮廓，再统一缩放、留白和对齐脚底。

小犀、奶泡、团团继续使用原始高分辨率六姿态，来源分别见 `assets/mascot-v2/` 和 `assets/tf-v1/SOURCES.md`。它们的原始完整轮廓经过检查，无须重新生成人物。

## 校标

蓝蓝最终动画和海报使用既有官方大连理工大学校徽图层，由渲染器合成回胸口；不是生成模型重画的校标。官方来源见 `assets/mascot-v3/SOURCES.md`。原图胸口留空不代表成品缺少校标。

## 动画处理

`tools/tf_animation_renderer_v2.c` 对不可变的高分辨率纹理进行局部连续运动与图层合成。眼部、头部、耳朵、手、身体与尾巴有各自的动作节奏；不再将整张不同姿态做透明溶解，避免双眼、双鼻和双校标重影。

`tools/build_tf_animation_v2.py` 负责透明区域取景、尺寸归一、编码和打包；保留原始源图，不用 Python 绘制五官。网页高清素材与板端 128 × 128 帧包分别编码。精确尺寸、帧数、校验及源文件摘要由最终 `public/animations/v2/manifest.json`、`pack-report.json` 记录。

### 最终编码与实际规模

- 网页：512 × 512、50 ms / 帧、透明无损 APNG；五角色六状态共 2,050 帧。`*-poster.png` 是同一个 C 渲染器输出的静态首帧。
- 板端：独立缩小至 128 × 128 后编码 RGB565 + alpha8；83 ms / 帧，共 1,230 帧，LXAF 仍为协议 v1，文件 60,457,984 字节。并非将 128 像素素材放大给网页。
- 眨眼：上眼睑的空间覆盖边界扫描真实闭眼姿态的局部纹理，窄边缘羽化；不将整个眼球或整个身体按透明度灰化。身体、头、手、耳与尾的运动使用不同相位和幅度。
- 校徽：先合成官方 PNG，蓝毛手爪保留为前景遮挡，再与角色一起变形；网页、海报和板端帧都有校徽。manifest 的蓝蓝 clip 显式记录 `badge_baked` / `web_badge_baked` / `board_badge_baked`。
- 透明留白：扩展取景提取最大连通区域；逐姿态仅平移对齐脚底，再统一比例缩放到 512 规范纹理，至少 36 像素留白。完整取景范围、脚底平移和缩放记录在 `pack-report.json`。

本机 WebP 动画编解码样例出现透明边缘灰块或彩色残留，最终改用 APNG；失败样例仅留在 `tmp/tf-v2-codec-diagnostics/`，未放入最终资源 ZIP。每段 APNG 的首、中、末帧使用新解码器读回，与原始 RGBA 逐字节比较。Pillow 12.3 的同一 APNG 对象向后 seek 会触发错误的解码状态，因此验证使用独立新打开的对象正向 seek。

交付分为 `lingxi-tf-animations-v2.zip`（轻量 TF 安装包，包含板端 GIF 和总览）与 `lingxi-hd-animations-v2.zip`（可选高清 APNG 与海报包）。高清包不需要复制到 TF 卡；卡只读取 `lingxi/animations-v1.lxaf`。

复现命令：

```powershell
python tools/build_tf_animation_v2.py
```

需要 Pillow、NumPy、GCC。可用 `--avatars kangaroo,robot` 等组合在不同进程中并行渲染角色，最后不带 `--avatars` 运行一次，会核对并复用已有 clip 缓存后统一打包。每个进程有独立 C 纹理状态；没有对共享 C 全局状态做线程并行。`--samples` 仅输出蓝蓝待机和回应样例，不写最终 manifest。
