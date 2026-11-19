# macOS v0.3.11 公证修订验收

## 环境与来源

- 验收日期：2026-11-19，Asia/Shanghai。
- 环境：macOS 26.3，arm64。
- 运行时代码：既有 v0.3.11 标签提交 `fc3adda0fe50d66d7dccdcdf25c8ee3532c2fe51`，保持标签不变。
- 构建保障修复：[PR #81](https://github.com/orulink-ai/VINote/pull/81)，已合入 `dev`，合入提交 `29a29c6efaa4ef8871729f28e9307eb772351a98`。
- FFmpeg / FFprobe：8.1.3；飞书 CLI：1.0.93；Langfuse：关闭。构建需用 `VINOTE_LARK_CLI_PATH` 明确选择目标 CLI，避免 PATH 中旧版本混入。

## 本地检查

| 检查 | 结果 |
| --- | --- |
| 父仓库后端 `python -m pytest -q --ignore=VINote-app`（8.1.3 工具链） | 5137 通过、7 项按平台/夹具条件跳过、19 个 subtest 通过 |
| 前端全部测试 | 1946 通过 |
| 前端生产构建 | 通过 |
| 发布脚本回归 | 27 通过 |
| 包内 FFmpeg / 默认工具链的桌面及媒体集成检查 | 各 19 通过、3 项按夹具条件跳过 |
| 只含系统 PATH 的冻结后端冒烟 | 通过，含数据库、状态存储、路由、前端、音频降噪及包内说话人推理 |
| 原生分发签名 | 174 个 Mach-O 的 Developer ID、Team LP4D78XZ45、安全时间戳和 hardened runtime 全部通过 |

本地失败记录：旧 FFmpeg 8.0.1 在 EOF 空缓冲区上误报 Opus 解析错误，曾造成 9 项真实媒体测试失败。采用上游已修复的 8.1.3 后原失败用例与完整回归通过，未忽略 stderr 或关闭包校验。首次扫描到独立 App 的第三方 Pods 后，按父仓库测试范围排除子模块。

跳过项包括 3 项 Windows 专属行为、3 项需显式私有原件夹具的检查，以及 1 项已有图示兼容用例；本次未伪造夹具或把平台跳过记为通过。

## Apple 与分发校验

| 产物 | Apple 提交 ID | 最终状态 |
| --- | --- | --- |
| 最终 App | `55d7e338-2f54-4a5e-9e4d-9d82e25d0514` | Accepted |
| 最终 DMG | `00d92327-66ea-4d56-8485-c9937289e65b` | Accepted |

- App 与 DMG 均完成 staple 和 validate，Gatekeeper 返回 `accepted`、`source=Notarized Developer ID`。
- DMG 完整性校验通过；以只读方式挂载后，镜像内 App 的 deep/strict 签名、票据和 Gatekeeper 均通过。仅卸载本次挂载的镜像。
- OTA 归档解压后的 App 票据与签名通过；新归档签名与应用现有公钥匹配。签名使用已有密钥，未更换更新信任公钥。
- 旧包的 Apple 拒绝日志包含内部 ad-hoc 签名、缺少安全时间戳与 hardened runtime；这些记录对应旧提交，不作为最终包结果。

## 最终文件校验值

| 文件 | SHA-256 |
| --- | --- |
| `release-macos-0311-notarized-VINote_0.3.11_aarch64.dmg` | `a641f4ad1311868e0d73c65432a9a142c67944ebfbb901ac5b75c783b77bc1e5` |
| `release-macos-0311-notarized-VINote.app.tar.gz` | `2c76b046a76d0a6cd248bdda8b7d39a1571902cdf6f61c836304dbf6cb197622` |
| 更新归档 `.sig` | `11d11f3b92ed68882e07c34b3a4e62b0ae28cad93d8410ebe0eb1ab710f02fa8` |

## 仓库发布

- [公开下载](https://github.com/vilab-orulink/Vinote-public/releases/tag/v0.3.11) 与 [源码仓库镜像](https://github.com/orulink-ai/VINote/releases/tag/v0.3.11) 均已发布，isDraft=false。
- 两仓库均只保留最终 DMG、OTA 归档、签名、manifest.json、latest.json 共五项资产，其远端 SHA-256 全部与本地已验收文件一致。
- 旧的未公证资产已从两仓库移除；更新元数据在新文件与签名验证完成后切换，保留 Windows v0.3.10 的既有 latest 选择。
- 安装此同版本公证修订版需重新下载并覆盖安装。


## 后续补充：原生 OTA 安装

[原生 OTA 验收](2026-11-19-macos-ota-e2e.md) 发现本记录中旧 OTA 文件虽有有效签名和可由 BSD tar 解压，仍含原生插件拒绝的 AppleDouble 成员。该 OTA 文件及签名由新的 `notarized-ota` 文件替换；App 与 DMG 字节、公证提交 ID 和 DMG 哈希保持不变。后续原生下载、验签、替换和更新后验证结果以补充记录为准。
