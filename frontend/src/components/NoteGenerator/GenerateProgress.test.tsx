import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { GenerateProgress } from "./GenerateProgress";
vi.mock("../../lib/i18n", () => ({
  useI18n: () => ({
    copy: {
      progress: {
        prepareRequest: "准备",
        downloadAudio: "下载",
        transcribeAudio: "转写",
        generateNote: "笔记",
        processScreenshots: "截图",
        failed: "失败",
        completed: "完成",
      },
    },
  }),
}));
afterEach(cleanup);
it('does not advertise screenshots for Bilibili audio intake and keeps saving pending', () => {
  render(<GenerateProgress audioOnlySource status="processing" currentStep="transcribing" />);
  expect(screen.queryByText('截图')).not.toBeInTheDocument();
  expect(screen.getByRole('listitem', { name: '保存笔记：待开始' })).toHaveAttribute('data-stage-state', 'pending');
  expect(screen.getByRole('heading', { name: '语音转写' })).toBeVisible();
});
it('uses hollow future steps and one animated current step at meeting step two of four', () => {
  render(<GenerateProgress meeting status="processing" currentStep="transcribing" />);
  const list = screen.getByRole('list', { name: '会议纪要处理步骤' });
  const rows = within(list).getAllByRole('listitem');
  expect(rows.map(row => row.getAttribute('data-stage-state'))).toEqual(['completed', 'active', 'pending', 'pending']);
  expect(rows[0].querySelector('svg')).toHaveClass('lucide-check-circle2');
  expect(rows[1]).toHaveAttribute('aria-current', 'step');
  expect(rows[1].querySelector('svg')).toHaveClass('lucide-loader2', 'motion-safe:animate-spin', 'motion-reduce:animate-none');
  for (const row of rows.slice(2)) {
    expect(row.querySelector('svg')).toHaveClass('lucide-circle');
    expect(row.querySelector('.lucide-check-circle2')).toBeNull();
    expect(row).not.toHaveAttribute('aria-current');
    expect(row).toHaveAccessibleName(/待开始/);
    expect(within(row).getByText('待开始')).toBeVisible();
  }
});
it('failure marks only the failed stage and success alone completes remaining stages', () => {
  const { rerender } = render(<GenerateProgress meeting status="failed" currentStep="transcribing" />);
  const rows = () => within(screen.getByRole('list')).getAllByRole('listitem');
  expect(rows()[1]).toHaveAttribute('data-stage-state', 'failed');
  expect(rows()[1].querySelector('svg')).toHaveClass('lucide-alert-circle');
  expect(rows()[1]).toHaveAccessibleName(/失败/);
  expect(rows().every(row => !row.hasAttribute('aria-current'))).toBe(true);
  expect(rows()[3]).toHaveAttribute('data-stage-state', 'pending');
  rerender(<GenerateProgress meeting status="success" currentStep="success" />);
  for (const row of rows()) {
    expect(row).toHaveAttribute('data-stage-state', 'completed');
    expect(row.querySelector('svg')).toHaveClass('lucide-check-circle2');
  }
});
it('document saving remains a hollow pending step until its stage is reached', () => {
  render(<GenerateProgress documentSource status="processing" currentStep="summarizing" />);
  const saving = screen.getByRole('listitem', { name: '保存笔记：待开始' });
  expect(saving.querySelector('svg')).toHaveClass('lucide-circle');
  expect(saving).toHaveAttribute('data-stage-state', 'pending');
});
it.each(['preparing', 'summarizing', 'saving'])('uses meeting title and progress label during %s without inventing completion', currentStep => {
  render(<GenerateProgress meeting status="processing" currentStep={currentStep} />);
  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('正在生成会议纪要');
  expect(screen.getByRole('progressbar', { name: '会议纪要生成进度' })).not.toHaveAttribute('aria-valuenow');
  expect(screen.queryByRole('progressbar', { name: '生成笔记阶段进度' })).not.toBeInTheDocument();
});
it('keeps note progress wording outside the meeting workflow', () => {
  render(<GenerateProgress status="processing" currentStep="summarizing" />);
  expect(screen.getByRole('progressbar', { name: '生成笔记阶段进度' })).toBeVisible();
  expect(screen.queryByRole('progressbar', { name: '会议纪要生成进度' })).not.toBeInTheDocument();
});
it('separates measured streamed audio from confirmed transcript and speaker detection', () => {
  render(<GenerateProgress meeting status="processing" currentStep="transcribing" receivedSeconds={40} processedSeconds={0} totalSeconds={80} speakerDetectionProgress={.75} />);
  expect(screen.getByRole('progressbar', { name: '音频提交进度' })).toHaveAttribute('aria-valuenow', '50');
  expect(screen.getByRole('progressbar', { name: '发言区间检测进度' })).toHaveAttribute('aria-valuenow', '75');
  expect(screen.getByText('已提交识别 00:40 / 01:20')).toBeVisible();
  expect(screen.getAllByRole('status')).toHaveLength(2);
  expect(screen.queryByText('会议纪要已保存')).not.toBeInTheDocument();
});
it('shows meeting analysis and saving without a screenshot step during diarization', () => {
  render(<GenerateProgress meeting status="processing" currentStep="diarizing" processedSeconds={0} totalSeconds={340} message="正在区分说话人：55%" />);
  expect(screen.getByRole('heading', { name: '说话人分析' })).toBeVisible();
  expect(screen.getByText('转写与说话人分析').parentElement).toHaveAttribute('data-state', 'processing');
  expect(screen.getByText('保存会议纪要')).toBeVisible();
  expect(screen.queryByText('截图')).not.toBeInTheDocument();
  expect(screen.getByRole('progressbar', { name: '音频转写进度' })).toHaveAttribute('aria-valuenow', '0');
  expect(screen.getByRole('progressbar', { name: '发言区间检测进度' })).not.toHaveAttribute('aria-valuenow');
});
it("preserves completed steps and measured transcription coverage on failure", () => {
  render(
    <GenerateProgress
      status="failed"
      progress={30}
      processedSeconds={18}
      totalSeconds={60}
      currentStep="transcribing"
    />,
  );
  expect(screen.getByText("下载").parentElement).toHaveAttribute(
    "data-state",
    "completed",
  );
  expect(screen.getByText("转写").parentElement).toHaveAttribute(
    "data-state",
    "failed",
  );
  expect(screen.getByText("笔记").parentElement).toHaveAttribute(
    "data-state",
    "pending",
  );
  expect(
    screen.getByRole("progressbar", { name: "音频转写进度" }),
  ).toHaveAttribute("aria-valuenow", "30");
  expect(screen.getByRole("progressbar").firstElementChild).toHaveStyle({ width: "30%" });
  expect(
    screen.queryByRole("status", { name: "正在生成与处理资料" }),
  ).not.toBeInTheDocument();
});
it("replaces raw chunk and waiting messages with one product explanation and no invented percentage", () => {
  render(<GenerateProgress status="processing" progress={45} currentStep="transcribing" message="Transcribing chunk 2/3 (16:00 - 32:00)..." />);
  expect(screen.queryByText(/chunk|第 2\/3 段|等待服务端|暂不显示/)).not.toBeInTheDocument();
  expect(screen.getByText('转写完成后，将生成笔记；返回后可继续查看。')).toBeVisible();
  expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');
  expect(screen.queryByText('45%')).not.toBeInTheDocument();
});

it("shows measured zero and coverage, then removes it in an unmeasured next stage", () => {
  const { rerender } = render(<GenerateProgress status="processing" currentStep="transcribing" progress={30} processedSeconds={0} totalSeconds={60} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  rerender(<GenerateProgress status="processing" currentStep="transcribing" progress={30} processedSeconds={30} totalSeconds={60} />);
  expect(screen.getByText("50%")).toBeVisible();
  expect(screen.getByRole("progressbar").firstElementChild).toHaveStyle({ width: "50%" });
  rerender(<GenerateProgress status="processing" currentStep="summarizing" progress={80} processedSeconds={60} totalSeconds={60} />);
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  expect(screen.getByText("进度待更新")).toBeVisible();
  expect(screen.queryByText("100%")).not.toBeInTheDocument();
});

it.each([
  [undefined, 60], [30, undefined], [30, 0], [NaN, 60], [30, Infinity], [-1, 60],
])("never fabricates a percentage for invalid coverage (%s / %s)", (processedSeconds, totalSeconds) => {
  render(<GenerateProgress status="processing" currentStep="transcribing" progress={80} processedSeconds={processedSeconds} totalSeconds={totalSeconds} />);
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  expect(screen.getByRole("progressbar").firstElementChild).toHaveClass("motion-reduce:animate-none");
});

it("only reports whole-note completion after success and stops motion after unknown failure", () => {
  const { rerender } = render(<GenerateProgress status="failed" currentStep="summarizing" progress={80} error="服务暂不可用" />);
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  expect(screen.getByRole("progressbar").firstElementChild).not.toHaveClass("motion-safe:animate-pulse");
  expect(screen.getByRole("alert")).toHaveTextContent("服务暂不可用");
  rerender(<GenerateProgress status="success" currentStep="success" progress={80} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  expect(screen.getByText(/100% · 笔记已完成/)).toBeVisible();
});
it('keeps ASR time and speaker saved completion independent without claiming final transcript success', () => {
  render(<GenerateProgress meeting status="processing" currentStep="transcribing" receivedSeconds={2772} processedSeconds={0} totalSeconds={3037} speakersReady speakerDetectionProgress={.4} />);
  expect(screen.getByText('语音转写')).toBeVisible();
  expect(screen.queryByText(/ASR/)).not.toBeInTheDocument();
  expect(screen.getByText('已提交识别 46:12 / 50:37')).toBeVisible();
  expect(screen.getByRole('progressbar', { name: '音频提交进度' })).toHaveAttribute('aria-valuenow', '91');
  expect(screen.getByRole('progressbar', { name: '说话人分析已保存' })).toHaveAttribute('aria-valuenow', '100');
  expect(screen.getByText('分析已保存')).toBeVisible();
  expect(screen.queryByRole('progressbar', { name: '发言区间检测进度' })).not.toBeInTheDocument();
  expect(screen.queryByText('逐字稿已保存')).not.toBeInTheDocument();
});

it('shows complete detection as refinement, not a saved speaker analysis', () => {
  render(<GenerateProgress meeting status="processing" currentStep="diarizing" totalSeconds={340} speakerDetectionProgress={1} />);
  expect(screen.getByText('正在核对声音特征')).toBeVisible();
  expect(screen.getByRole('progressbar', { name: '发言区间检测进度' })).toHaveAttribute('aria-valuenow', '100');
  expect(screen.queryByText('分析已保存')).not.toBeInTheDocument();
  expect(screen.getByRole('progressbar', { name: '音频转写进度' })).not.toHaveAttribute('aria-valuenow');
});

it('waits for final transcript confirmation at the audio end instead of reporting 100 percent saved', () => {
  render(<GenerateProgress meeting status="processing" currentStep="transcribing" totalSeconds={80} receivedSeconds={80} processedSeconds={0} />);
  expect(screen.getByRole('progressbar', { name: '音频提交进度' })).toHaveAttribute('aria-valuenow', '99');
  expect(screen.getByText('音频已提交，正在等待最终逐字稿。')).toBeVisible();
  expect(screen.queryByText('逐字稿已保存')).not.toBeInTheDocument();
});

it.each([undefined, NaN, Infinity, -1, 1.2])('does not invent a speaker percentage for unknown or invalid detection %s', speakerDetectionProgress => {
  render(<GenerateProgress meeting status="processing" currentStep="diarizing" speakerDetectionProgress={speakerDetectionProgress} progress={50} />);
  expect(screen.getByRole('progressbar', { name: '发言区间检测进度' })).not.toHaveAttribute('aria-valuenow');
  expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument();
});

it('shows video verification after ready ASR without inventing a video percentage or completing the minutes', () => {
  render(<GenerateProgress meeting videoSource status="processing" currentStep="analyzing_video" processedSeconds={900} totalSeconds={900} receivedSeconds={900} speakersReady progress={80} />)
  expect(screen.getByRole('heading', { name: '核对共享画面与发言' })).toBeVisible()
  expect(screen.getByRole('listitem', { name: '核对共享画面与发言：进行中' })).toHaveAttribute('aria-current', 'step')
  expect(screen.getByRole('listitem', { name: '转写与说话人分析：已完成' })).toBeVisible()
  expect(screen.getByRole('listitem', { name: '生成并核对会议纪要：待开始' })).toBeVisible()
  expect(screen.getByRole('listitem', { name: '保存会议纪要：待开始' })).toBeVisible()
  expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
  expect(screen.queryByText(/100%|80%/)).toBeNull()
  expect(screen.getByRole('status')).toHaveTextContent('逐字稿已就绪不代表纪要已完成')
})
