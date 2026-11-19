# macOS 0.3.11 原生 OTA 验收

## 验收范围与方法

2026-11-19，macOS 26.3 arm64。使用与发布包 Cargo.lock 相同的 Tauri 2.12.5、tauri-plugin-updater 2.14.1，以及发布包的同一可信公钥和 HTTPS 入口。验收目标是：安装当前公证 DMG 后，后续正式 macOS 版本能够走应用内 OTA。

- 当前版本上下文设为 0.3.11，读取真实 stable 入口：正常返回无新版本；现有 stable 为 Windows 0.3.10，并非更高的 macOS 版本。
- 旧版本上下文模拟为 0.3.10，读取真实已发布的 0.3.11 清单，下载公开 macOS 更新归档，由原生插件执行签名验证和替换安装。公开仓库未创建伪造的更高版本。
- 安装路径是规范化临时目录内的独立 `.app` 副本。检查替换前后根目录 inode 变化，以及副本外数据哨兵内容保持一致。
- 原生安装后检查实际 App 的 deep/strict 签名、notarization ticket、Gatekeeper 和冻结后端启动冒烟。

## 发现的问题及修复

此前仅密码学签名、BSD tar 解压后的 App 校验通过，未证明原生安装。旧归档含 `._VINote.app`，Tauri 原生提取器移除首个组件后尝试把元数据写到提取目录本身，报 `failed to unpack ._VINote.app`。BSD tar 列表和解压可能处理、隐藏这些 AppleDouble 成员。

新生产函数以 `COPYFILE_DISABLE=1` 创建归档，Python 标准库直接读取原始成员，拒绝 AppleDouble、非唯一 App 根目录、`./` 前缀包装、路径逃逸及空包。真实 `Contents/CodeResources` 票据文件保留。打包、项目 verify 和 CI 均接入检查。相关脚本 39 项通过，含先失败后通过的 AppleDouble 和前置点目录反例。

App 与 DMG 内容不变，现有公证继续有效；更新归档重新生成后，旧签名被正确拒绝，新归档使用原密钥重新签名。更新信任公钥保持不变。

## 原生演练结果

原生测试程序的实际输出：

```text
PASS: shipping 0.3.11 configuration checks the live stable feed without update errors
PASS: native updater finds a higher macOS release and its signed public payload
PASS: native download and signature verification finished
PASS: native macOS updater installed the complete signed application into the isolated bundle
```

安装后的票据校验成功，签名校验通过，Gatekeeper 返回 `accepted`、`source=Notarized Developer ID`。冻结后端冒烟结果：

```text
Desktop backend smoke test passed: database, task status polling, routes, frontend, ffmpeg, ffprobe and bundled speaker inference.
```

## 发布文件

| 产物 | SHA-256 |
| --- | --- |
| 当前 OTA `release-macos-0311-notarized-ota-VINote.app.tar.gz` | `9b6889b065b56c9420c74686aa0fea5d1fa7338f406bfce3737d942257aaabc6` |
| 当前 OTA `.sig` | `e679e5ac406811405570caef3492bf655f02f034ab260434fe9f47840764c2bd` |
| 未改变的公证 DMG | `a641f4ad1311868e0d73c65432a9a142c67944ebfbb901ac5b75c783b77bc1e5` |

源仓库与公开仓库均已替换为新 OTA 归档和签名；两仓库最终五项资产的 SHA-256 全部与已验收本地文件一致。旧 AppleDouble 归档及签名已移除。已下载公证 DMG 的用户无需更换文件，安装到应用程序目录后，在应用内检查并安装后续新版本。

[前次公证验收](2026-11-19-macos-0311-notarization.md) 继续作为 App/DMG 公证证据；旧 OTA 哈希对应历史文件，本页补足其原生安装消费证据。
