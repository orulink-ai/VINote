# macOS 原生 OTA 安装验收

- 日期与时区：2026-11-19，Asia/Shanghai；作者：orulink-wugui
- 分支：codex/macos-ota-archive-safety；状态：已完成：修复、重签、原生完整演练和双仓库发布校验通过。
- 用户目标：下载安装当前 DMG 后，后续可正常 OTA；同时查询 iOS TestFlight 当前审核状态。

## 根因与范围

与发布 App 相同的 Tauri 2.12.5 / updater 2.14.1 在隔离 `.app` 副本验证：当前 0.3.11 正常读取 live stable feed，没有比它更新的版本；模拟旧版本 0.3.10 可识别公开 0.3.11 macOS 清单。随后原生 install 对旧归档报 failed to unpack ._VINote.app。普通 BSD tar 列表/解压会处理或隐藏 AppleDouble，未覆盖 Rust 原生解包器行为；已有公证和签名证据不能替代安装验收。

DMG 和 App 字节保持不变，公证仍成立。仅重新生成不含 AppleDouble 的 OTA 归档并重新签名；不重签或替换更新公钥，不公开伪造更高版本，不操作正在使用的 VINote 安装或数据。

## 实现与 TDD

- createMacUpdaterArchive 使用 COPYFILE_DISABLE=1，保留真实 Contents/CodeResources 票据文件。Python 标准库逐个读取 raw tar 成员，拒绝 AppleDouble、不同根目录、路径逃逸及空归档。
- 所有正式 macOS 归档均检查结构；原有延后签名分支复用同一生产函数。项目 verify 与 CI 纳入枚举签名和归档回归。
- Red：已发布旧归档在原生插件安装时失败；新的验证器初始空实现使 AppleDouble 反例断言失败。
- Green：完整相关脚本 38 项通过；旧实际归档被 raw checker 拒绝，新实际归档通过。新归档标准解压后的票据、完整签名和 Gatekeeper 通过。
- 原生安装检查坚持签名验证，重新打包后旧签名被正确拒绝；新归档正在使用原密钥重新签名。
- 完整公开下载、验签、原生替换、更新后运行及数据哨兵检查尚待完成，不提前标记通过。

## 关联历史

[前次公证任务](../2026-11-19_145500_orulink-wugui_无Issue_macOS媒体工具链与公证/index.md) 的 App/DMG 公证及密码学签名验证仍成立，本次补足其未覆盖的原生 OTA 容器消费环节。

2026-11-19｜orulink-wugui：增加 `./VINote.app` 包装反例，先观察唯一根目录断言失败，再以原始首段而非规范化路径检查，修复后所有相关脚本 39 项通过。CI 原文件采用 CRLF，保持其换行格式，空白检查以 cr-at-eol 区分换行和真正尾随空格；未批量重排原工作流。新归档 SHA-256 为 9b6889b065b56c9420c74686aa0fea5d1fa7338f406bfce3737d942257aaabc6，已在两仓库上传并核对哈希，原密钥签名任务已触发，公开元数据仍待切换。

2026-11-19｜orulink-wugui：同版本原生更新插件已从公开 URL 下载新归档，完成签名校验与隔离 App 的真实原子替换；根目录 inode 改变，副本外数据哨兵不变。更新后的票据、签名、Gatekeeper 与冻结后端冒烟均通过。新签名 SHA-256 为 e679e5ac406811405570caef3492bf655f02f034ab260434fe9f47840764c2bd。原 App、DMG、公钥与公证记录不变，最终双仓库发布核对仍在收尾。[完整验收记录](../../../../docs/reviews/2026-11-19-macos-ota-e2e.md)。

2026-11-19｜orulink-wugui：原生演练通过后完成两仓库元数据切换、旧 OTA 归档与签名移除、五项最终资产远端哈希核对；均为已发布状态。公证 DMG 不变，已下载该 DMG 的用户无需重新下载；后续正式版本可通过应用内更新。补齐最终验收文档与历史证据的双向关联，未修改运行时公钥或发布虚假更高版本。
