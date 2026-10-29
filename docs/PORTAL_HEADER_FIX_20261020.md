# 手机配网页 HTTP 431 修复

用户手机已连到 LingXi-922C 并访问到板端 HTTP 服务，但显示 `Header fields are too long`。
该文本对应 ESP-IDF 5.4.4 `httpd_txrx.c` 的 HTTP 431 错误，产生于请求解析阶段。

构建原配置为 `CONFIG_HTTPD_MAX_REQ_HDR_LEN=512`。手机浏览器的请求头超出此默认值，配网页处理函数尚未运行即被拒绝。

修复：

- `firmware/box_audio_ram/prepare.py` 生成及更新工程时设置 `CONFIG_HTTPD_MAX_REQ_HDR_LEN=8192`。
- 保持 URI 上限和配置请求体大小不变。
- `network_probe.c` 的启动日志输出生效的请求头上限；成功发送配网页时输出无敏感信息的诊断日志。
- SDK 的解析 scratch buffer 属于 HTTP 服务实例的堆对象，此修改增加约7680字节堆内存。

修改配置需重新编译、烧录。更换浏览器或清理手机数据不构成固件修复。
验收需检查生成的 sdkconfig.h、实板启动，以及手机刷新配网页的结果。

本次结果：生成的 sdkconfig.h 已为8192；IDF编译成功；COM12应用烧录及哈希校验通过。
实板日志明确输出 `headers 8192 bytes`，AP/DHCP与音频初始化正常，40秒观察期间无崩溃。
日志位于 `tmp/portal-header-fix-boot-20261020.log`。用户已确认重新连接热点、刷新后出现 Wi-Fi 配置表单，手机访问恢复正常。
