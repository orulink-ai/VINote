import { useEffect, useRef, useState } from 'react';
import { getVersion } from '@tauri-apps/api/app';
import { check, type Update } from '@tauri-apps/plugin-updater';
import { relaunch } from '@tauri-apps/plugin-process';
import { Button } from '@/components/ui/button';
import { isTauriRuntime } from '@/lib/desktopMicrophonePermission';
import { desktopUpdateBlockReason } from '@/lib/desktopUpdateSafety';
import packageJson from '../../../package.json';

type Phase = 'idle' | 'checking' | 'available' | 'current' | 'downloading' | 'ready' | 'installing' | 'installed';

export function DesktopUpdatePanel() {
  const desktop = isTauriRuntime();
  const [version, setVersion] = useState(packageJson.version);
  const [phase, setPhase] = useState<Phase>('idle');
  const [update, setUpdate] = useState<Update | null>(null);
  const [error, setError] = useState('');
  const [downloaded, setDownloaded] = useState(0);
  const [total, setTotal] = useState<number>();
  const mounted = useRef(true);
  const resource = useRef<Update | null>(null);
  const busy = useRef(false);
  useEffect(() => {
    mounted.current = true;
    if (desktop) void getVersion().then(value => { if (mounted.current) setVersion(value); }).catch(() => {});
    return () => {
      mounted.current = false;
      if (!busy.current) { void resource.current?.close().catch(() => {}); resource.current = null; }
    };
  }, [desktop]);
  const releaseAfterUnmount = () => {
    busy.current = false;
    if (!mounted.current) { void resource.current?.close().catch(() => {}); resource.current = null; }
  };
  async function checkUpdate() {
    if (!desktop || busy.current) return;
    busy.current = true;
    setError(''); setPhase('checking'); setUpdate(null);
    try {
      await resource.current?.close(); resource.current = null;
      const next = await check({ timeout: 30000 });
      resource.current = next;
      if (mounted.current) { setUpdate(next); setPhase(next ? 'available' : 'current'); }
    } catch {
      if (mounted.current) { setError('检查更新失败。请检查网络连接或稍后重试；当前应用可以继续使用。'); setPhase('idle'); }
    } finally { releaseAfterUnmount(); }
  }
  async function download() {
    if (!update || busy.current) return;
    busy.current = true; setError(''); setDownloaded(0); setTotal(undefined); setPhase('downloading');
    try {
      await update.download(event => {
        if (!mounted.current) return;
        if (event.event === 'Started') setTotal(event.data.contentLength);
        if (event.event === 'Progress') setDownloaded(value => value + event.data.chunkLength);
      }, { timeout: 300000 });
      if (mounted.current) setPhase('ready');
    } catch {
      if (mounted.current) { setError('下载或签名校验失败，更新未安装。请重新下载。'); setPhase('available'); }
    } finally { releaseAfterUnmount(); }
  }
  async function install() {
    if (!update || busy.current || phase !== 'ready') return;
    const reason = desktopUpdateBlockReason();
    if (reason) { setError(reason); return; }
    busy.current = true; setError(''); setPhase('installing');
    try {
      await update.install({ restartAfterInstall: false });
      if (mounted.current) setPhase('installed');
    } catch {
      if (mounted.current) { setError('安装更新失败。请重新检查更新并下载；当前资料不受影响。'); setPhase('idle'); }
    } finally { releaseAfterUnmount(); }
  }
  async function restart() {
    const reason = desktopUpdateBlockReason();
    if (reason) { setError(reason); return; }
    try { await relaunch(); } catch { setError('重启失败，请关闭并重新打开 VINote。'); }
  }
  return <div className="flex flex-col gap-3" aria-label="应用更新">
    <p className="text-sm text-muted-foreground">版本 {version}</p>
    {!desktop ? <p className="text-sm text-muted-foreground">应用内更新仅适用于桌面客户端，浏览器无需安装更新。</p> : <>
      <p className="text-sm text-muted-foreground">手动检查稳定版更新。下载完成后由你决定何时安装。</p>
      <div role="status" aria-live="polite" className="text-sm">
        {phase === 'checking' && '正在检查更新…'}
        {phase === 'current' && '当前已是最新版本。'}
        {update && ['available', 'downloading', 'ready'].includes(phase) && `可用版本 ${update.version}`}
        {phase === 'downloading' && <p>正在下载：{total ? `${Math.min(100, Math.round(downloaded / total * 100))}%` : `${(downloaded / 1024 / 1024).toFixed(1)} MB`}</p>}
        {phase === 'ready' && <p className="mt-2">下载及签名校验已完成。安装会关闭 Windows 客户端；请先保存工作。安装后请自行重新打开应用。</p>}
        {phase === 'installing' && '正在启动安装，请勿关闭安装程序…'}
        {phase === 'installed' && '更新已安装，重新启动后生效。'}
      </div>
      {update?.body && <details className="text-sm"><summary className="cursor-pointer">版本说明</summary><p className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-muted-foreground">{update.body}</p></details>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="flex flex-wrap gap-2">
        {['idle', 'current', 'available'].includes(phase) && <Button variant="outline" onClick={() => void checkUpdate()}>检查更新</Button>}
        {phase === 'available' && <Button onClick={() => void download()}>下载更新</Button>}
        {phase === 'ready' && <Button onClick={() => void install()}>确认安装更新</Button>}
        {phase === 'installed' && <Button onClick={() => void restart()}>立即重启</Button>}
      </div>
    </>}
  </div>;
}
