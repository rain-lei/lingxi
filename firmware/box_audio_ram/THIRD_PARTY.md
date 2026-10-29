# 板卡驱动来源

- 本目录的主程序、界面、对话客户端、CMake 配置和准备脚本为灵犀设备端实现。
- prepare.py 在用户指定的本地构建目录中复制正点原子资料盘
  4，程序源码/v_5.4版本例程/1，标准例程-IDF版/24_recoding(ES8311)/components/BSP
  内的 KEY、MYIIC、LCD、LED、XL9555、ES8311，以及 MYI2S 头文件。
- 配置基于同资料盘 10_lcd 的 sdkconfig；当前使用本项目的 partitions-16MiB.csv，
  将应用布局扩展至 Flash 前 4 MiB（factory 为 4032 KiB），保留 NVS 与射频分区起点。
- 原厂驱动声明：
  Copyright (c) 2020-2032, 广州市星翼电子科技有限公司。
  准备脚本保留原始作者与版权头，不将其标记为灵犀原创或擅自声明 MIT 许可。
  这些驱动不打包进本目录；公开分发驱动前需核实厂商的再分发许可。
- 原厂 ES8311 的本地副本仅修改 BCLK 倍数和 I2C 重试/等待超时，改动在代码中标注。
- 固件使用乐鑫 ESP-IDF 5.4.4，其组件保留各自许可证。
- 当前 v2 小犀角色根据用户提供的形象参考，使用内置 imagegen 生成蓝色 3D 风格素材。
  参考图用于风格与比例指引；附件原图没有打包到项目。生成图、提示词与制作说明保留在
  assets/mascot-v2，打包来源及 SHA-256 记录在 assets/mascot-pack-report.json。
  固件以 RGB565 + alpha8 贴图显示，界面排版、交互与刷新由 C 代码实现。
- v3 蓝色毛绒袋鼠按用户提供的形象参考使用内置 imagegen 生成，原始六格 PNG、
  提示词与来源记录位于 assets/mascot-v3。打包仅提取主连通角色、统一裁切缩放及编码，
  不修改原始 PNG；处理参数与 SHA-256 保留在 assets/mascot-v3/pack-report.json。
- 袋鼠胸前的官方校徽由独立图层叠加。官方来源为
  [大连理工大学学校 VI 页面](https://www.dlut.edu.cn/xxgk/dxwh/xxVI.htm) 和
  [官网标识 SVG](https://www.dlut.edu.cn/images/logo.svg)，校徽标识权利归大连理工大学。
  项目的代码许可不改变官方标识的权利归属；官方资源和 AI 角色分开保存、分别标注。
  具体文件及转换说明见 assets/mascot-v3/SOURCES.md。
- 中文字形来自 Google Fonts 发布的 Noto Sans SC，生成内置 4-bit 灰度字形子集；
  来源：https://github.com/google/fonts/tree/main/ofl/notosanssc 。
  字体按 SIL Open Font License 1.1 使用，原始版权和完整许可证保留在
  assets/NotoSansSC-OFL.txt。完整字体没有打包；修改界面文案后，可用
  tools/generate_ui_font.py 和原始 Noto Sans SC 字体重新生成字形子集。
- 动态回复使用同一 Noto Sans SC 来源的完整 GB2312 汉字子集（6763 字），
  由 tools/generate_ui_cjk.py 生成 main/ui_cjk.h/c：Unicode 升序索引，
  12×16、1-bit、每字 24 字节。字体仍按 SIL OFL 1.1 使用，保留原始版权与许可证，
  不将字体或其衍生字库重新声明为项目代码许可。
- 小犀界面、图片打包和预览工具由 Codex 辅助实现，角色素材由 AI 辅助生成，需由团队验收实机效果。
- 20px 回复字库加入 Resource Han Rounded CN Medium（资源圆体），来源为作者
  [官方 v0.990 简体发布包](https://github.com/CyanoHao/Resource-Han-Rounded/releases/tag/v0.990)。
  字体采用 SIL OFL 1.1，作者完整声明保留在 assets/ResourceHanRounded-OFL.txt。
  本机源文件 assets/fonts/ResourceHanRoundedCN-Medium.ttf 的 SHA-256 为
  B2EC1727FBC04B70255DB6CB71BE0ECA3B7A7167EF11655059C5576CC920143F。
  原生20px位图子集与 Noto Sans SC 回复字库均保留各自字体许可，不重新声明为代码许可。
