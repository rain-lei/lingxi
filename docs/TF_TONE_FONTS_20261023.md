# TF 卡语气字体 · 2026-10-23

已制作四套真正不同的字体，网页与板端采用相同的字体来源。

| 语气 | 视觉风格 | 字体来源 | 板端缓存 |
| --- | --- | --- | --- |
| warm / 温柔 | 柔和圆体 | Resource Han Rounded CN Medium | 992,677 字节 |
| calm / 平静 | 平静宋体 | Noto Serif SC，600 字重 | 994,855 字节 |
| cheerful / 活泼 | 灵动手写 | LXGW WenKai Regular | 992,789 字节 |
| direct / 直接 | 清晰黑体 | Noto Sans SC，600 字重 | 994,523 字节 |

全部为 SIL OFL 1.1 授权。每套包括 **6763 个 GB2312 汉字与 ASCII、常见标点，共 7029 个码点**；生成时逐套核对原字体 cmap，无缺失汉字或占位方框。保留原作者版权声明、版本及来源哈希；衍生位图与网页字体使用独立 LingXi 名称。

## 下载与安装

- 网页字体：`public/fonts/v1/{warm,calm,cheerful,direct}.woff2`，随语气切换加载。
- 独立字体压缩包：`public/fonts/v1/lingxi-tf-fonts-v1.zip`，约 1.86 MiB。
- 板端字体数据：`public/fonts/v1/lingxi-fonts-v1.lxff`，3,975,164 字节，约 3.79 MiB。
- TF 卡保存路径：`/lingxi/fonts-v1.lxff`。
- 字体可单独更新，无须重新传输动画包。
- 配套新固件的板子配置页新增“安装语气字体”按钮，可由电脑服务下载。旧固件仅复制文件不会启用这些字体。

LXFF 文件 SHA-256：

`d4d8cc1bb8399bf559a81aa7bbfa7c5a65f1df416f571533ba425af4a9e494d2`

## 清晰度与性能

直接从源字体轮廓生成原生 20 px、26 px 行高、2 位抗锯齿字形。长回复保持每行约 14 个汉字、4 行一页，不缩小字体。四套采用相同的排版前进宽度；异步切换字体不会改变分页或使文字跳动。

TF worker 在录音和对话空闲时预加载当前语气的一套字形到 PSRAM；UI 绘制只二分查找内存字形，不逐字读取 TF 卡。切换期间保留旧缓存；新字体检查通过才交换。常驻缓存不足 1 MiB，交换瞬间旧、新缓存合计约 1.9 MiB。若 PSRAM 不足，保留旧字体并稍后重试。

无卡或字体未安装时，仍使用嵌入式 Noto Sans 原生 20 px 字体，覆盖完整 7029 字集合。移除第二套嵌入位图，节省约 889 KiB Flash。

## 安装校验

字体包采用独立 LXFF v1 格式：固定四种语气、64 字节头、64 字节字体索引、12 字节字形索引、2 位 alpha 数据。

- 仅接受固定 `/fonts/v1/install.json` 与 `/fonts/v1/lingxi-fonts-v1.lxff`；不接受用户提供任意下载地址。
- 文件最大 8 MiB；单字体缓存最大 1200 KiB。
- 下载校验长度、完整文件 SHA-256、包体 SHA-256 与四字体 CRC32。
- 在 `.part` 文件中下载并同步，完整校验后替换，保留 `.previous`。
- 缓存加载再验证字形排序、尺寸、范围、CRC 和问号回退字形。
- 安装中暂缓 BOOT 对话，避免同时访问卡与录音。

## 已完成验证

1. `tools/lxff_verify.c` 使用生产 C 解析器和独立 Windows BCrypt SHA-256 验证完整包、四套 CRC、全部字形与 ASCII；未知字回退测试通过。
2. 字体数量、保留字段、截断索引、截断文件、溢出偏移、范围间隙、重复语气编号、破损字形偏移/高度等负向用例均被拒绝。
3. `tools/test_tf_fonts.py` 使用真实 `ui_scene.c` 渲染四套 LCD 画面；长回复六页、所有分页局部重绘与全屏渲染像素一致；四字体分页一致、画布哨兵与无卡回退测试通过。
4. `public/fonts/v1/font-styles.png` 与 `tmp/font-tests-v3/four-tone-lcd.png` 已人工检查清晰度及四字体差异。

上述属于生成、解析与主机渲染验证。实板安装与现场帧率验证由整体固件发布流程完成，不能由本报告代替。

## 重新生成

使用包含 Pillow 的 Python，并安装 `fonttools` 和 `brotli`（本次依赖位于 `tmp/font-tools`）：

```powershell
python tools/build_tf_fonts.py
python firmware/box_audio_ram/tools/test_tf_fonts.py
```

嵌入式后备字体可用 `generate_ui_reply_font.py --single-fallback` 重建。完整版权与来源见 `public/fonts/v1/SOURCES.md`、`public/fonts/v1/licenses/`。
