import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { MeetingRecorderExternalSnapshot } from "../../stores/meetingRecorderStore";
import { MeetingRecorderController } from "./MeetingRecorderController";

const controls = vi.hoisted(() => ({
  hide: vi.fn().mockResolvedValue(undefined),
  send: vi.fn().mockResolvedValue(undefined),
  listen: vi.fn(),
}));

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({ hide: controls.hide }),
}));
vi.mock("../../lib/meetingController", () => ({
  listenMeetingState: controls.listen,
  sendMeetingAction: controls.send,
}));
vi.mock("../../lib/desktopRecorderWindow", () => ({
  showMainWindow: vi.fn(),
  startCurrentRecorderWindowDrag: vi.fn(),
}));
vi.mock("../../lib/i18n", () => ({
  useI18n: () => ({
    locale: "zh-CN",
    copy: {
      meetingRecorder: {
        phases: { requesting: "正在请求", recording: "录制中" },
        pause: "暂停",
      },
    },
  }),
}));

it("hides the desktop controls during capture without pausing or stopping it", async () => {
  let updateState: (snapshot: MeetingRecorderExternalSnapshot) => void = () => {
    throw new Error("Recorder state listener not registered");
  };
  controls.listen.mockImplementation(async (handler) => {
    updateState = handler;
    return vi.fn();
  });
  render(<MeetingRecorderController />);
  act(() => updateState({ phase: "recording", elapsedSeconds: 5 }));

  await userEvent.click(screen.getByRole("button", { name: "隐藏悬浮窗" }));

  expect(controls.hide).toHaveBeenCalledOnce();
  expect(controls.send.mock.calls).toEqual([["sync"]]);
  act(() => updateState({ phase: "recording", elapsedSeconds: 12 }));
  expect(screen.getByText("0:12")).toBeVisible();
  expect(screen.getByRole("button", { name: "结束" })).toBeEnabled();
});
