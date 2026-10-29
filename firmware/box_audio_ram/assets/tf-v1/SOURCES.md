# 灵犀 TF 动画 v1 资源来源

制作日期：2026-10-21。此目录保存新增三位伙伴的透明姿态原图和完整生成提示词。

## 新增伙伴

| 角色 ID | 角色 | 参考肖像 | 透明姿态图 | 提示词 |
| --- | --- | --- | --- | --- |
| 2 | 奶泡 `cat` | `public/assets/companion-cat.png` | `cat-poses.png` | `cat-prompt.txt` |
| 3 | 团团 `otter` | `public/assets/companion-otter.png` | `otter-poses.png` | `otter-prompt.txt` |
| 4 | 芽芽 `sprout` | `public/assets/companion-sprout.png` | `sprout-poses.png` | `sprout-prompt.txt` |

三张原图均使用 Codex 内置 imagegen，以对应现有肖像为唯一角色参考生成；输出为 1536 × 1024 RGBA，每图六个 512 × 512 单元。先检查了肖像和每张输出，再由已有 `pack_mascot.py` 的透明连通区域方法裁切，并用统一边界、统一比例缩小。该阶段不重画五官或替换表情。

姿态顺序统一为：

1. 正面待机，眼睛睁开，轻微闭口微笑。
2. 自然闭眼眨眼。
3. 侧耳倾听，手放耳侧。
4. 抬眼思考，轻扶下巴。
5. 开心开口，小手抬起。
6. 温和关怀，双手向前。

逐图检查了围巾、蓝书、头顶叶片等识别特征；均保留完整全身、透明背景和相近视角。原始 alpha 最大值为 254，属于有效透明纹理；编包时只清除极低 alpha 的背景噪点，保留毛绒边缘。

## 复用伙伴及校徽

- `avatar_id=0` 蓝蓝：`main/ui_kangaroo.c` 中六套既有 RGB565 + alpha8 纹理。
- `avatar_id=1` 小犀：`main/ui_mascot.c` 中六套既有 RGB565 + alpha8 纹理。
- 蓝蓝胸前校徽：复用 `main/ui_badge.c` 既有官方校徽层和每姿态中心位置，不让生成模型重新绘制校徽。

每项实际输入的 SHA256 记录在输出目录 `public/animations/v1/pack-report.json` 的 `source_art` 中。

## 动画生成与复现

入口脚本：`tools/build_tf_animation_pack.py`。主机渲染器：`tools/tf_animation_renderer.c`。依赖 Python、Pillow 及 GCC；不依赖连接硬件或 TF 卡。

```powershell
python tools/build_tf_animation_pack.py
```

已有最终帧，只需重新纳入安装说明或预览时，可运行 `python tools/build_tf_animation_pack.py --archive-only`；该模式不重渲染、不改 LXAF，只更新 ZIP 和 `manifest.archive`，保留已发布的固件及安装字段。

完整 ZIP 包含卡根目录下的 `lingxi/animations-v1.lxaf`、报告、README、完整安装指南及全部 30 个 GIF 和总览 PNG。只有 `lingxi/` 目录需要放入 TF 卡，预览和说明可以保存在电脑。

输出目录默认为 `public/animations/v1/`。C 渲染器使用不可变姿态纹理、双线性透明采样、缓动姿态过渡以及轻微呼吸、点头、耳朵/叶片摆动、小跳跃，生成真正的多帧动画。Python 负责透明裁切、缩放、二进制打包和从最终像素生成预览，不手绘修改表情。

每位伙伴含待机、倾听、思考、说话、安慰、庆祝六状态；每段 24 或 36 帧，83 ms/帧。局部画面为 128 × 128，采用 RGB565LE16 + alpha8 交错存储。全部 30 片段共 900 帧，原始包 44,237,824 字节。状态、帧数、循环标记、偏移及 CRC32 见 `pack-report.json`。

说话状态在真实闭口待机和真实开口挥手姿态间切换，不承诺音素口型同步。素材为预渲染 3D 风格的二维动画；实际板端播放流畅度需配套固件和 TF 卡实测。

预览 `previews/*.gif` 直接解码最终 LXAF 包的实际帧；`previews/contact-sheet.png` 用于同时检查五角色、六状态。GIF 的时间单位为 10 ms，浏览器显示会将 83 ms 取整，板端帧间隔仍使用 LXAF 记录的 83 ms。

编包后执行完整结构、SHA256、逐片段 CRC32、连续边界和重复 ID 检查，并拒绝截断、尾部多字节、像素篡改、伪造偏移、伪造 CRC 五种破坏输入。固件侧另行使用独立 C 解析器交叉验证。
