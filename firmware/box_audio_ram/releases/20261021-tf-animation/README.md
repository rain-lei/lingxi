# TF animation firmware — 2026-10-21

Target: ATK-DNESP32S3B V1.1, ESP32-S3, ESP-IDF 5.4.4.

- Application only: `lingxi-tf-animation.bin`, offset `0x10000`.
- Size: 4,102,080 bytes (`0x3e97c0`). Existing application partition: `0x3f0000`; 26,688 bytes remain.
- SHA256: `cb48d94016a09189d547fa3167a88ebd0e4f07ad542746287d20cd12b83f28a5`.
- No partition layout change, no formatting, and no device flashing were performed during preparation.

## Optional TF resources

The TF card uses FAT32 and heap long filenames (maximum 64 bytes). LCD uses its existing I80 bus; card uses SPI2 SCLK7/MOSI16/MISO15/CS17 at 10 MHz. Missing or invalid card/package retains the embedded kangaroo/robot interface. Newly selected card-only characters fall back to the embedded blue kangaroo until a verified frame is available.

The package is `/sdcard/lingxi/animations-v1.lxaf`. The reader accepts LXAF v1, 128×128 interleaved RGB565 little-endian + alpha, up to 30 clips, 96 frames per clip, and a 64 MiB file limit. It checks metadata, duplicate identifiers, overlap, overflow, reserved fields, SHA256, and every clip CRC32. Animation is loaded into PSRAM by a worker, with a separate speaking cache prefetched before audio.

## Install from the computer without a card reader

1. After updating this application, turn the board off and insert the FAT32 card, then power it on.
2. Keep the computer's LingXi service running and ensure the board's saved Wi-Fi can reach it.
3. Connect the phone to the board's existing `LingXi-922C` setup hotspot. A no-Internet notice is expected for that hotspot.
4. Open `http://192.168.4.1/` and press **从电脑安装动画**. If a device pairing token was configured, enter that token in the page first.
5. Wait for **动画已就绪**. The worker downloads the fixed `/animations/v1/lingxi-animations-v1.lxaf` endpoint from the configured computer service, writes `.part`, verifies it, and then activates it. Transfer timeout is five minutes; full integrity verification follows the transfer. A failed or interrupted install retains the previous valid package.

Installation is an explicit button action. It never starts on boot. Voice activity rejects installation; BOOT recording is deferred while an installation is active.

## Status API

`GET /api/assets` returns `mounted`, `installed`, `downloading`, `bytes_received`, `total_bytes`, `progress` (0–100), `stage`, and `error`.

`POST /api/assets/install` accepts exactly `{}` with `Content-Type: application/json`. If configured, `X-Device-Token` is required. The browser Origin must match the device host. No arbitrary URL is accepted. Success is HTTP 202; voice busy, not connected, or another active installation returns HTTP 409.

## Playback behavior

| State | Current board behavior |
| --- | --- |
| Idle | Current character clip automatically plays from PSRAM; target tick 83 ms, actual board frame rate awaits testing. |
| Thinking | Current character thinking clip plays while waiting for the service. |
| Speaking | Prefetched RAM clip animates the small reply header at most once per 250 ms. The 20 px reply text remains still. A header render slower than 10 ms disables further header animation for that audio session. No phoneme synchronization is claimed. |
| Listening | Recording retains a static pose; no new card reads are started during audio capture. |
| Comfort / celebration | Included and validated in the package; automatic emotional/task events are not yet connected. Celebration is non-looping and the reader clamps to the last frame. |

Characters: 0 蓝蓝/kangaroo, 1 小犀/robot, 2 奶泡/cat, 3 团团/otter, 4 芽芽/sprout.

## Verification completed

- ESP-IDF 5.4.4 application build and partition-size gate passed, including FAT32 long filenames and separate speaking cache. Existing vendor legacy-I2S deprecation warning remains.
- Independent Windows C reader using BCrypt SHA256 verified the actual 44,237,824-byte package: all 30 clip CRC32 values and first/final frame boundaries passed.
- Portable parser self-tests rejected duplicate identifiers, overlap, overflowing offsets, excessive frames, reserved-byte changes, and truncated metadata/files; standard CRC32 vector passed.
- The same C LCD renderer rendered all five actual LXAF characters. Cardless fallback, partial repaint equivalence, and unchanged reply pixels during speaking-header animation passed. Preview: `tmp/tf-ui-preview/tf-five-avatars.png` in the repository.
- Real-card mounting, Wi-Fi transfer, playback frame rate, and audio performance need the user's later on-device test. No serial port was opened and no current board firmware was changed.
