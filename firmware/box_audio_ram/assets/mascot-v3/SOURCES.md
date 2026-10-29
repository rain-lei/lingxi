# v3 蓝色袋鼠与校徽素材来源

## AI 角色

- `kangaroo-concept.png`：根据用户提供的蓝色毛绒袋鼠形象参考，使用内置 imagegen 生成。
  这是灵犀项目的 AI 辅助角色素材，不是学校发布的官方吉祥物。
- 原始尺寸 1536×1024、RGBA，三列两行，依次为待机、眨眼、倾听、思考、开心回应和关切。
- `GENERATION_PROMPT.txt` 保留生成提示词。生成图中的胸部图案随原始文件保留；
  正式显示的校徽以独立叠加的官方标识图层为准。
- `tools/pack_mascot.py --largest-component --prefix ui_kangaroo` 在每格以 alpha≥32
  提取最大的 8 连通角色区域，保留 2 像素毛绒抗锯齿边缘，去除相邻格的独立残片，
  再统一裁切、缩放和编码为 RGB565+alpha8。原始 PNG 不修改。
- `pack-report.json` 记录原图 SHA-256、每格来源坐标、主连通区域统计及统一变换。
  当前裁切 `(36,0,512,511)`，缩放为 `112×120`，置于128×128贴图的 `(8,4)`。

## 官方 DUT 校徽

官方来源核对日期：2026-10-20。

- [大连理工大学学校 VI 页面](https://www.dlut.edu.cn/xxgk/dxwh/xxVI.htm)，包含“A-1 校徽”和应用规范。
- [大连理工大学官网标识 SVG](https://www.dlut.edu.cn/images/logo.svg)。
- `dlut-official-emblem-a1.png`：从官方 VI 页面取得的校徽参考图。
- `dlut-official-logo.svg`：官网 SVG 原始资源副本。
- `dlut-badge.svg`、`dlut-badge.png`：供伙伴页面与板端胸前叠加使用的独立校徽资源。
  缩放、栅格化与位置映射服务于显示；图层随角色移动，切换机器人形象时隐藏。
- 板端校徽打包由 `tools/pack_badge.py` 完成，角色主贴图与校徽分别存储，
  便于保持官方校徽图形并适配六种姿态的位置。

校徽标识权利归大连理工大学，项目代码许可不改变该标识的权利归属；使用时保留官方来源和 VI 规范。

## 中文字体

固定界面及动态回复字形来自 [Google Fonts 的 Noto Sans SC](https://github.com/google/fonts/tree/main/ofl/notosanssc)。
字体按 SIL Open Font License 1.1 使用，原始版权和完整许可保留在 `../NotoSansSC-OFL.txt`。
`tools/generate_ui_font.py` 生成固定文案的4-bit字形；`tools/generate_ui_cjk.py`
生成动态回复使用的全部6763个GB2312汉字，12×16、每字24字节、连续MSB位序，Unicode升序索引。
完整字体不随固件部署；衍生字库保留字体许可，不将其重标为项目代码许可。
