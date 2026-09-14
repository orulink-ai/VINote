# 会议记录真实模型验证（2026-09-14）

## 结论与范围

公开四人中文音频已通过会议记录共用的上传、说话人区分、真实 STT、真实 LLM、个人笔记保存、逐字稿读取和媒体 Range 读取链路。最终总结保留说话人和时间引用，没有发现虚构决策或待办；仍存在 STT 用词问题，需要回听校对。

本次以 FastAPI TestClient 在进程内调用桌面端相同的 HTTP 路由，并运行前端组件测试。没有操作鼠标、打开原生桌面窗口或录制用户麦克风，因此不能据此宣称原生录音、录屏权限、悬浮窗交互或音频播放体验通过实机验收。

## 输入与服务

- 音频：sherpa-onnx 公开发布的 [0-four-speakers-zh.wav](https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/0-four-speakers-zh.wav)，约 57 秒，1,819,586 字节。
- 本地文件：`data/diarization-four-speakers.wav`。未使用私人会议录音。
- 说话人分析：本地 sherpa-onnx，Pyannote 分段与 3D-Speaker 特征聚类，手动指定已知 4 人。
- ViLab：本机 `http://127.0.0.1:9878`，使用现有关联账号认证，没有更改服务端模型选择。
- STT：`asr:6:aliyun:22:paraformer-realtime-v2`。
- LLM：`gpt-5.6-luna`。

## 过程与修复

| 检查 | 实际发现 | 处理与复查 |
| --- | --- | --- |
| 服务稳定性 | 默认模型接口曾返回 503；首轮转写中途出现 502 | 显式 STT 502/503/504 最多重试两次，失败仍终止任务，不跳过片段；重跑完成 |
| 短句转写 | 14 个片段中出现“机会站在阳台上吹吹风” | 连续同一人的不超过 1 秒停顿合并；新一轮得到“非常累的时候就会站在阳台上吹吹风”，共 8 段 |
| 时间证据 | 原总结把 13.75–17.04 秒发言写成 13–22 秒 | LLM 输入同时提供开始和结束时间，禁止用下一人开始时间代替结束；最终总结用各段开始时间引用 |
| 模板诱导 | 一轮总结虚构“继续进行说话人日志测试”待办，并将资料缺失变成未决问题 | 决策/待办/未决问题改为有原文依据才出现；同一份真实逐字稿重新调用 LLM 后未再出现上述条目 |
| 角色混淆 | 一轮总结声称说话人 2/3 在播放音频 | 模板区分被引用的声音和操作播放的人；最终总结只记录发言与介绍关系 |

没有对生成结果做人工文字修补后冒充模型输出。最终 Markdown 是修订模板后真实 LLM 的原始返回，并通过笔记 PATCH 接口保存和 GET 回读核验。

## 结果与质量

- 首次成功：任务 `56e826d8-7f1e-4d9a-8ca6-5d9c4bf641a1`，14 段、4 个标签，HTTP 上传到成功约 79.61 秒。
- 分段调整后：任务 `5b3a4c47-c44f-45fb-9e19-e6e150464a4e`，8 段、4 个标签，约 81.74 秒。服务内部转写约 66.31 秒，总结约 12.20 秒；这两次实测没有显示速度提升。
- 最终总结重生成复用第二轮真实逐字稿，模型调用及保存约 2.66 秒，未再次调用 STT。
- 最终个人笔记 ID：`33de44b3-a70a-42ba-af1b-4d1316dede2b`，标题「测试｜公开四人音频会议总结」。应用启动后查看该测试笔记；较早对照笔记保留。
- 媒体 Range 请求返回 206；逐字稿接口保留说话人编号、时间和原始文本。
- 最终总结覆盖 8 段发言：开场、阳台远眺、坚持到底、测试音频介绍、年度演讲、往事、非凡追求、结束说明。未发现新增负责人、截止时间、决策或待办。
- 剩余问题：“这是我第四次颁年度演讲”不自然，“五大往事”等词仍需回听核对。没有人工标注的标准逐字稿，未计算字错率或说话人错误率；不能声称内容完全准确。
- 指定 4 人得到 4 个标签不等于逐段归属均正确。此前自动人数分析得到 7 类，本次没有验证自动人数已改善，也没有覆盖长会议、远场、噪声和抢话。
- 此文件只有音频，不验证视频关键帧、屏幕内容理解或图文总结。

## 回归与复现

- 后端完整测试：121 passed（10 warnings）。最后一次模板调整后，提示词、说话人和重试相关测试再次执行：13 passed。
- 前端完整测试：21 个文件、82 项通过；包含会议提交参数、捕获资源清理、录音控件状态测试。
- 新增真实检查入口：`scripts/check_meeting_generation.py`；总结对照入口：`scripts/check_meeting_summary.py`。均要求显式 `--live`，会调用真实模型并保存测试笔记。

```powershell
.venv\Scripts\python.exe scripts/check_meeting_generation.py data/diarization-four-speakers.wav --live --speakers 4 --output data/meeting-live-report.json
.venv\Scripts\python.exe scripts/check_meeting_summary.py data/meeting-live-report.json --live --output data/meeting-reviewed-summary.md
```

本机证据（不提交生成产物）：

- `data/meeting-live-report.json`：中途失败任务。
- `data/meeting-live-report-retry.json`：首轮成功原始总结和逐字稿。
- `data/meeting-live-report-final.json`：分段调整后整链路结果，内含模板收紧前的对照总结。
- `data/meeting-reviewed-summary.md`：最终修订模板生成的总结，已保存到上述最终笔记。
- `data/meeting-summary-review.log`：最终总结保存回读记录。

最终保存笔记的内容已更新；原任务目录的 `note.md` 和 `result.json` 保留当轮整链路原始输出，以便对照，不能把它们当作最终模板结果。
