import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsNav } from "./SettingsNav";

afterEach(cleanup);
describe("SettingsNav", () => {
  it("groups preferences, device processing and services with one active destination", () => {
    const onChange = vi.fn();
    const view = render(<SettingsNav activeTab="models" onChange={onChange} />);
    const nav = screen.getByRole("navigation", { name: "设置分类" });
    for (const label of ["账号与协作", "使用偏好", "当前设备与处理", "服务"]) {
      expect(within(nav).getByRole("heading", { name: label })).toBeVisible();
    }
    expect(within(nav).getAllByRole("button")).toHaveLength(8);
    expect(
      within(nav).getByRole("button", { name: "转写与总结" }),
    ).toHaveAttribute("aria-current", "page");
    expect(within(nav).queryByRole("button", { name: "连接与工具" })).not.toBeInTheDocument();
    const storage = within(nav).getByRole("button", { name: "存储" });
    expect(storage).not.toHaveAttribute("aria-current");
    fireEvent.click(storage);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("storage");
    view.rerender(<SettingsNav activeTab="storage" onChange={onChange} />);
    expect(storage).toHaveAttribute("aria-current", "page");
    expect(
      within(nav).getByRole("button", { name: "转写与总结" }),
    ).not.toHaveAttribute("aria-current");
  });
});
