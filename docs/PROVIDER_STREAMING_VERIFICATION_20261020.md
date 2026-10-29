# 阶跃语音流式接口验证（2026-10-20）

## 实现

`providers/stepfun.py` 新增 `iter_synthesize_pcm(...)`，保留已有 `synthesize(...)` 的兼容行为。

- 请求 `/audio/speech`，模型保持 `stepaudio-2.5-tts`，显式设置 `response_format="pcm"`、`stream_format="audio"`、`sample_rate=16000`。
- 使用 `HTTPResponse.read1(2048)` 逐块读取，接到音频即可交给下游；没有等待完整响应的隐藏 `read()`。
- PCM 为接口约定的单声道 16 位小端格式，采样率由请求参数指定。跨网络分片保存半个采样，向下游只输出偶数字节。
- 默认最多接收 640000 字节。拒绝空响应、JSON/文本错误、其他编码格式、半个采样及超限音频；网络中断转换为不含凭证的错误。
- 消费端应在停止接收时调用生成器 `close()`，从而关闭上游 HTTP 响应。

官方接口说明：[语音合成](https://platform.stepfun.com/docs/zh/api-reference/audio/create-audio)。文档明确支持 PCM、16000 Hz 及 `stream_format`。本机取得的文档原文保存在 `tmp/stepfun-tts-official.html`，不含 API Key。

实测显式流式模式不支持 WAV：请求 `stream_format="audio"` 与 `response_format="wav"` 返回 HTTP 400，提示 `wav format is not supported for stream mode`。因此新增方法使用原始 PCM。旧 WAV 解析路径仍按文件头中的实际采样率转换，不能把未知 WAV 数据直接标记为 16 kHz。

## 小样本实测

测试使用本机保存的有效凭证，凭证没有输出或写入测试记录。

| 测试 | 首个 PCM 分片 | 完整接收 | 音频大小 / 时长 |
| --- | ---: | ---: | --- |
| 新方法，单次短句 | 1156 ms | 3406 ms | 128000 字节 / 4000 ms，80 个分片 |
| 直接 HTTP PCM，另一短句 | 953 ms | 1953 ms | 48640 字节，30 个分片 |

新增方法的结果及音频分别为 `tmp/probe_iter_pcm.json`、`tmp/probe_iter_pcm.wav`。控制请求的 WAV 文件头确认 16000 Hz、16 位、单声道。

另一次直接 HTTP PCM 请求返回 HTTP 200、`text/plain`、空响应。新方法会将这种响应报告为上游错误，不会播放文本或伪造成功。该异常说明网络和提供商仍会波动。

这些数字仅衡量**已有文字之后的 TTS 请求**，不是用户松开 BOOT 到扬声器响起的总时间；尚未包含 ASR、模型首字、完整文本生成、本机网络和板端预缓冲。样本很少，不构成所有新问题的延迟保证，也不能证明物理麦克风或扬声器已通过测试。整条链路需另外记录首音频与完整响应时间。

## 自动检查

`python -m unittest discover -s tests -p test_stepfun.py -v`：17 项通过，包含有界读取、首块提前输出、主动中止关闭连接、半采样拼接、格式与长度异常、网络中断和无效参数检查。

## 对话模型参数

保持 `step-3.7-flash` 与 `reasoning_effort="low"`。官方文档只列出 `low`、`medium`、`high`，没有给该模型列出关闭思考的 `none`、`enable_thinking` 或 `thinking.disabled` 参数，本次未添加未验证的开关或更换模型。

来源：[Step 3.7 Flash](https://platform.stepfun.com/docs/zh/guides/models/step-3.7-flash)、[Chat Completions 参数](https://platform.stepfun.com/docs/zh/api-reference/chat/chat-completion-create)。本机原文为 `tmp/stepfun-model-official.html`、`tmp/stepfun-chat-official.html`。
