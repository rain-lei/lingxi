# TF 动画实板安装与下载时限修复：2026-10-23

## 当前结论

本次通过 UART **COM12** 连接正点原子 ESP32-S3 BOX。板子已经成功挂载用户插入的 TF 卡，状态接口返回 `mounted: true`；没有格式化 TF 卡。

第一次安装因旧固件的 300 秒下载总时限退出。修复固件已写入并通过应用校验，第二次下载安装正在进行。**本说明写入时，`tmp/tf-device-install-20261023.json` 尚未记录 `success: true`，因此目前等待最终安装结果，不能据此宣称动画安装或实际播放成功。**

最终结论应以 `../tmp/tf-device-install-20261023.json` 的最新结果为准。第一次失败记录另存为 `../tmp/tf-device-install-20261023-attempt1.json`；第二次过程日志为 `../tmp/tf-device-install-20261023-retry.log`。即使最终验包成功，屏幕播放、校标显示和对话时声音并发仍需分别观察确认。

## 第一次失败及原因

- 下载目标：新版 LXAF，**60,457,984 字节**，30 段动作。
- 实际写入 **49,864,704 字节（82%）** 后退出；本次耗时约 **303.9 秒**。
- 返回 `Transfer interrupted; previous animation retained`。当时 `mounted: true`、`installed: false`，说明卡片已经挂载并写入了部分资源，不能把这次问题归因为 D 盘权限或 TF 卡格式。
- 固件下载循环原先设置了固定 **300 秒**截止时间。按本次约 166 KB/s 的整体速度，新版完整资源需要超过 300 秒，旧截止时间会在资源尚未完成时中止。

源码中该通用报错也覆盖读取中断、TF 短写及文件刷新失败；本次经过时间与固定 300 秒门槛吻合，因此先实施针对总时限的最小修复，并通过第二次实际传输验证。

## 本次最小修复与构建

`firmware/box_audio_ram/main/asset_storage.c` 的下载总时限由 **300 秒提高到 900 秒**，并增加明确的超时错误文案。**本次没有加入 `ESP_ERR_HTTP_EAGAIN` 重试逻辑，也没有加入“30 秒无进展”计时机制。** HTTP 单次读取超时仍为 2,500 ms；卡内 `.part` 写入、完整 SHA-256/逐段 CRC 校验、校验后替换和原有效包保护机制保持原有实现。

电脑安装状态轮询等待延长到 **1,080 秒**，为传输和后续校验留出时间。下载时保持供电和本地服务运行，暂停对话，不拔卡。

原 `D:\esp32` 中旧工程的 Windows ACL 限制了写入；本次**没有更改原目录权限**。重新准备工程到允许写入的 ASCII 路径后编译：

```text
C:\Users\twofl\.codex\visualizations\2026\10\13\01a13355-cde6-7b21-adff-2a27813b3af9\lingxi_tf_20261023
```

最终新应用保存在：

```text
firmware/box_audio_ram/releases/20261023-tf-download/lingxi-tf-animation.bin
```

## 应用备份与升级记录

升级前已保存当时应用分区备份：

```text
tmp/tf-before-20261023-app.bin
SHA-256: 1d96af82a9fa9987a4152ad5c964f12824cd7e6b68a7723d3367cf9b741629ec
```

本日进行了两次应用更新：先写入原配套 TF 固件，再写入下载时限修复固件。**两次均已完成 `verify_flash`，日志显示 `verify OK (digest matched)`。** 只写入并校验应用地址 **`0x10000`**，保留既有 NVS、配网和分区表；未擦除整片 Flash，未格式化 TF 卡。

对应日志：

- `../tmp/tf-application-update-20261023.log`
- `../tmp/tf-download-fixed-flash-20261023.log`

## 新版固件及网页下载

| 项目 | 大小 | SHA-256 |
| --- | ---: | --- |
| 新应用 BIN | 4,102,160 字节 | `2b4d949d2842de8e00d989d37e7a7af9ad1528124959ca6d6468da07d4befd6a` |
| 网页固件 ZIP | 2,051,744 字节 | `8c891af3f64f5cfc11f6f423e1ed19a95cb17406bd68b68507a91098ac6ad8b2` |

应用分区大小为 `0x3F0000`，新应用剩余 **26,608 字节**。网页继续使用原有兼容下载路径：

```text
/downloads/lingxi-tf-animation-v1.bin
/downloads/lingxi-tf-firmware-v1.zip
```

已同步 V1/V2 manifest 的固件信息，核验发布 BIN 与构建产物一致、ZIP 内 BIN 与 `SHA256SUMS.txt` 一致，ZIP CRC 和刷写脚本均通过检查。报告见 `../tmp/tf-firmware-publish-verification-20261023.json`。

动画资源本身没有变更：LXAF 仍为 60,457,984 字节，SHA-256 为 `5cf9b17f1affd729b8a246c732876d02aea52f4801840fb83e28c5a10118f06c`。TF ZIP 和高清 ZIP 的内容校验值也保持不变。

## 安装成功需要的证据

板子 `GET /api/assets` 应返回 `mounted: true`、`installed: true`、`downloading: false`、`stage: "ready"` 且 `error` 为空，收到字节和总字节都应是 **60,457,984**。这表示卡内文件通过完整验包，不等同于实际屏幕和音频效果已经确认。

## 最终安装结果

第二次安装已成功，`../tmp/tf-device-install-20261023.json` 记录 `success: true`。板子完成全部文件写入与读回验包，并在五秒后的复查中保持正常：

```json
{"mounted":true,"installed":true,"downloading":false,"bytes_received":60457984,"total_bytes":60457984,"progress":100,"stage":"ready","error":""}
```

卡内已激活新版 `lingxi/animations-v1.lxaf`，包含五位伙伴、30 段动作；文件内容由板子进行 body SHA-256 和所有分段 CRC 校验。第二次传输及校验日志见 `../tmp/tf-device-install-20261023-retry.log`，第一次失败记录保留在 `../tmp/tf-device-install-20261023-attempt1.json`。

安装和文件校验已完成。屏幕动画、校标及音频并发效果等待用户现场确认，尚未将这些观察项标为已验证。
