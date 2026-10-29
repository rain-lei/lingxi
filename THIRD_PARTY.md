# 第三方资源及 AI 工具使用声明

本项目主动披露开发、运行和部署中使用的第三方资源。仓库不包含真实账号、API Key、设备令牌或未经授权的个人数据。

## 模型与 API

- **StepFun / 阶跃星辰开放平台**：使用 `step-3.7-flash` 完成文字与图片理解，使用 `stepaudio-2.5-asr` 和 `stepaudio-2.5-tts` 完成语音识别与合成。API Key 由用户在本机服务中配置；本机网页可用于输入密钥，不回显，不写入仓库或硬件固件。真实云端对话须在用户配置有效密钥后验收。

## 开发与部署组件

- **Python 3.12 标准库**：HTTP 服务、SQLite、数据校验和测试。
- **SQLite**：用户显式偏好、会话、反馈规则和召回统计。
- **Docker**：服务容器化与版本回滚。
- **Nginx / Let's Encrypt**：HTTPS 反向代理与证书。
- **GitHub**：公开源代码托管和开发历史。

## AI 辅助开发

- 使用 **OpenAI Codex** 辅助代码实现、测试、文档整理和部署检查。
- 项目需求选择、产品边界、最终集成与提交责任由参赛团队承担；所有生成内容均应由团队检查、理解并能够解释。

## 代码、设计与素材

- 应用业务代码、页面结构、样式和 SVG 图标均随仓库公开。
- 当前网页没有复制或打包第三方商业模板、未授权图片、用户隐私数据或旧项目主体代码。
- 赛题与赛制 PDF 仅用于需求对齐，不在公开仓库中重新分发。
- ESP32S3 BOX 内存录音实验通过准备脚本读取用户本地的正点原子板卡资料，复用 ES8311、LCD、I2C、IO 扩展和按键驱动；保留原厂版权，并标注本地适配。原厂驱动不在本仓库打包，详见 firmware/box_audio_ram/THIRD_PARTY.md。
- 板端“小犀”v2 角色参考用户提供的风格图片，使用内置 imagegen 生成蓝色 3D 风格素材，以贴图接入 C 界面；生成图及提示词保留在 firmware/box_audio_ram/assets/mascot-v2。内置中文字形子集来自 Noto Sans SC，使用 SIL OFL 1.1，完整字体许可证保留在 firmware/box_audio_ram/assets/NotoSansSC-OFL.txt。
- v3 蓝色毛绒袋鼠参考用户提供的形象，使用内置 imagegen 生成六种姿态，原图和提示词保留在 firmware/box_audio_ram/assets/mascot-v3。官方 DUT 校徽作为独立图层叠加，来源为[大连理工大学学校 VI](https://www.dlut.edu.cn/xxgk/dxwh/xxVI.htm)及[官网标识 SVG](https://www.dlut.edu.cn/images/logo.svg)，权利归大连理工大学；AI 形象和官方标识分别标注，详见该目录 SOURCES.md。
- 设备动态中文回复另含 Noto Sans SC 的全部 6763 个 GB2312 汉字，12×16、每字24字节，由 firmware/box_audio_ram/tools/generate_ui_cjk.py 生成；按 SIL OFL 1.1 使用，保留原始字体版权和完整许可证。
- 可读版的20px回复字库另使用 Noto Sans SC 与 [Resource Han Rounded](https://github.com/CyanoHao/Resource-Han-Rounded) 常用字子集；资源圆体源自作者 v0.990 简体发布包，字体采用 SIL OFL 1.1，完整声明保留在 firmware/box_audio_ram/assets/ResourceHanRounded-OFL.txt，详见固件目录 THIRD_PARTY.md。
