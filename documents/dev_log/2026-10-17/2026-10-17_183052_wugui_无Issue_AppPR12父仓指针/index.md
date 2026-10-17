# App PR12 父仓指针与发布核对

- 时间：2026-10-17 18:30:52 +08:00；建档作者：wugui。
- 需求：App PR12 已合并后，按最新 AGENTS 从 root 最新 `origin/dev` 的独立干净 checkout 更新 gitlink，中文提交/PR，推进至 CI ready，不合并或部署。
- 分支：`codex/update-reviewed-app-pr12`；基线：`45a62469ad32f80b7997887dfb630961f1deb4b9`。
- 范围：仅 `VINote-app` gitlink、[发布核对说明](../../../../docs/reviews/2026-10-17-app-pr12-release-pointer.md) 和本档案。运行目录、环境及 `.venv`/junction 不变。
- 状态：指针与说明已准备，待本分支提交和 PR CI；不提前声明已合入或发布。

## 验证记录

- fetch root dev 与 App main；核实 App PR12 正常 merge `f57c4369cc555cfcc9085f7cc9cc85fc3986fa4f`，包含复审 head `9e8f36a`。
- gitlink 保持 `160000`，仅从 `407fd76` 更新为 `f57c4369`；`.gitmodules` 仍为 main。
- root `assertProjectVersion()` 返回 `0.3.3`；App 合并提交 package/lock、Android/iOS 版本均为 `0.1.4`，Android versionCode9。
- 独立前置复审证据：9 suites/187 tests 通过，详见核对说明；本次不重复 App 测试或执行构建/推理。
- 本次为声明性 gitlink/文档交付，不适用产品行为 TDD；使用 Git 对象、PR 合并关系、版本一致性与变更范围检查替代。
- 后续：主线程在父仓 PR CI/审查通过后正常合并，再按最终合并提交推进发布；不得把源码/模拟离线测试当新包实际验收。
