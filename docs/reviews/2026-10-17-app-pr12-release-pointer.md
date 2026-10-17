# App PR12 合并后的父仓发布核对

## 固定源码

- 父仓准备基线：最新 fetched `origin/dev`，`45a62469ad32f80b7997887dfb630961f1deb4b9`，已包含提取接口及内存并发边界修复 PR57、PR58。
- App gitlink：从 `407fd76f7371b78f0aaf390aec3bd55bc35219f5` 更新为 `f57c4369cc555cfcc9085f7cc9cc85fc3986fa4f`。
- [App PR12](https://github.com/orulink-ai/VINote-app/pull/12) 已正常合入 App `main`；合并提交包含独立复审的 `9e8f36a701b0879c42ad37cfc1c12e13417e4e19`。已 fetch App `main` 核实远端可达及祖先关系。
- `.gitmodules` 继续跟踪 App `main`；普通 checkout 使用父仓提交中的精确 gitlink，不自动选择远端最新提交。

## 离线证据

- 在精确 `9e8f36a` 上独立复审并运行单 worker、Node heap512 定向测试，9 suites / 187 tests 通过。覆盖 URL fragment 与相同正文别名、Bili receipt 写入失败后恢复同一未派发操作、真实 API/session gate 的发送前后边界，以及保留未知记录退出和过期输入不能清除新 slot。
- API 边界测试使用真实 App API、session gate、text stream 代码及模拟 XHR；来源提取、模型和原生能力使用离线替代。此证据不是实际供应商、设备或完整链路验收。
- 本次父仓检查确认 gitlink 模式为 `160000`，值精确等于上述 App 合并 SHA；App PR12 head 为 `9e8f36a`、状态为 merged、base 为 `main`。
- `assertProjectVersion()` 通过：桌面/后端各受检 manifest 与 lock 保持 `0.3.3`。读取 App 合并提交核验 package/lock、Android versionName、iOS 两个配置均为 `0.1.4`；Android versionCode 为 `9`。
- Windows 空白检查使用 `git -c core.whitespace=cr-at-eol diff --cached --check`，保留既有换行方式。

## 发布边界

本次仅推进父仓 gitlink 与核对文档；没有修改运行 checkout、运行服务、App 源码、环境凭证、`.venv` 或 junction，也没有构建、部署、设备操作或新的 ASR/LLM 调用。既往旧包的实际验收不得替代本 gitlink 新包的验收；iOS 原生尚无本轮实机验收依据。

App 新笔记由安装通道固定 VILab Origin 执行推理，共用账号/飞书与纯提取服务不构成模型 Origin 回退。旧回执与未知请求不重放。发布仍需按正常父仓 PR 审查、CI、合并流程，绑定最终合并 SHA 后再由主线程构建/部署和验收；本文不宣称已发布。
