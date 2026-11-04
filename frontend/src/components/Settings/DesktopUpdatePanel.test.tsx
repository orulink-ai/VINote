import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { check, type Update } from '@tauri-apps/plugin-updater';
import { relaunch } from '@tauri-apps/plugin-process';
import { isTauriRuntime } from '@/lib/desktopMicrophonePermission';
import { desktopUpdateBlockReason } from '@/lib/desktopUpdateSafety';
import { DesktopUpdatePanel } from './DesktopUpdatePanel';

vi.mock('@tauri-apps/api/app', () => ({ getVersion: vi.fn().mockResolvedValue('0.3.4') }));
vi.mock('@tauri-apps/plugin-updater', () => ({ check: vi.fn() }));
vi.mock('@tauri-apps/plugin-process', () => ({ relaunch: vi.fn() }));
vi.mock('@/lib/desktopMicrophonePermission', () => ({ isTauriRuntime: vi.fn() }));
vi.mock('@/lib/desktopUpdateSafety', () => ({ desktopUpdateBlockReason: vi.fn() }));
beforeEach(() => { vi.clearAllMocks(); vi.mocked(isTauriRuntime).mockReturnValue(true); vi.mocked(desktopUpdateBlockReason).mockReturnValue(''); });
function available() {
  const update = { version: '0.3.5', body: '改进会议录制', close: vi.fn().mockResolvedValue(undefined), download: vi.fn().mockResolvedValue(undefined), install: vi.fn().mockResolvedValue(undefined) };
  vi.mocked(check).mockResolvedValue(update as unknown as Update);
  return update;
}
it('browser explains desktop-only updates and never invokes the updater', () => {
  vi.mocked(isTauriRuntime).mockReturnValue(false);
  render(<DesktopUpdatePanel />);
  expect(screen.getByText(/应用内更新仅适用于桌面客户端/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '检查更新' })).not.toBeInTheDocument();
  expect(check).not.toHaveBeenCalled();
});
it('checks only on explicit request and reports no update', async () => {
  vi.mocked(check).mockResolvedValue(null);
  render(<DesktopUpdatePanel />);
  expect(check).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  expect(await screen.findByText('当前已是最新版本。')).toBeInTheDocument();
  expect(check).toHaveBeenCalledWith({ timeout: 30000 });
});
it('reports a check failure and permits retry', async () => {
  vi.mocked(check).mockRejectedValue(new Error('offline'));
  render(<DesktopUpdatePanel />);
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('检查更新失败');
  expect(screen.getByRole('button', { name: '检查更新' })).toBeEnabled();
});
it('downloads with progress, then requires a separate guarded install and explicit restart', async () => {
  const update = available();
  let finish!: () => void;
  update.download.mockImplementation(((callback: (e: unknown) => void) => {
    callback({ event: 'Started', data: { contentLength: 100 } });
    callback({ event: 'Progress', data: { chunkLength: 25 } });
    return new Promise<void>(resolve => { finish = resolve; });
  }) as never);
  render(<DesktopUpdatePanel />);
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  fireEvent.click(await screen.findByRole('button', { name: '下载更新' }));
  expect(await screen.findByText('正在下载：25%')).toBeInTheDocument();
  expect(update.install).not.toHaveBeenCalled();
  finish();
  const install = await screen.findByRole('button', { name: '确认安装更新' });
  vi.mocked(desktopUpdateBlockReason).mockReturnValue('还有未保存的编辑');
  fireEvent.click(install);
  expect(update.install).not.toHaveBeenCalled();
  expect(screen.getByRole('alert')).toHaveTextContent('还有未保存的编辑');
  vi.mocked(desktopUpdateBlockReason).mockReturnValue('');
  fireEvent.click(install);
  await screen.findByText('更新已安装，重新启动后生效。');
  expect(update.install).toHaveBeenCalledWith({ restartAfterInstall: false });
  expect(relaunch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '立即重启' }));
  expect(relaunch).toHaveBeenCalledTimes(1);
});
it('failed download/signature verification never enables installation', async () => {
  const update = available(); update.download.mockRejectedValue(new Error('signature'));
  render(<DesktopUpdatePanel />);
  fireEvent.click(screen.getByRole('button', { name: '检查更新' }));
  fireEvent.click(await screen.findByRole('button', { name: '下载更新' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('签名校验失败');
  expect(screen.queryByRole('button', { name: '确认安装更新' })).not.toBeInTheDocument();
  expect(update.install).not.toHaveBeenCalled();
});
it('closes a late check resource after leaving settings', async () => {
  const update = available(); let finish!: (value: Update) => void;
  vi.mocked(check).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const page = render(<DesktopUpdatePanel />);
  fireEvent.click(screen.getByRole('button', { name: '检查更新' })); page.unmount();
  finish(update as unknown as Update);
  await waitFor(() => expect(update.close).toHaveBeenCalledTimes(1));
});
