import { beforeEach, expect, it, vi } from 'vitest';
import { apiJson } from './api';
import { readAutomaticDelivery, checkAutomaticDelivery, publishToFeishu, disableDeviceAutomaticDelivery } from './feishu';
import { useAuthStore } from '@/stores/authStore';
vi.mock('./api', () => ({ apiJson: vi.fn() }));
vi.mock('./connectorPlugins', () => ({ createConnectorPluginStore: () => ({ read: async () => ({ installed: true, enabled: true }) }) }));
beforeEach(() => { vi.resetAllMocks(); useAuthStore.setState({ user: { id: 'receipt-owner', email: 'test@example.invalid' } }) });
it('404 on initial GET is absence, while check is an exact no-body query and its errors stay errors', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce({ status: 404 }).mockResolvedValueOnce({ status: 'unknown', operation_id: 'frozen-operation', job_id: null, error: '', can_check: true }).mockRejectedValueOnce({ status: 404 });
  expect(await readAutomaticDelivery('note/one')).toBeNull();
  await checkAutomaticDelivery('note/one');
  expect(apiJson).toHaveBeenLastCalledWith('/api/feishu/automatic-deliveries/local/note%2Fone/check', { cache: 'no-store', method: 'POST' });
  await expect(checkAutomaticDelivery('note/one')).rejects.toEqual({ status: 404 });
});
it('malformed or unavailable state never becomes permission to publish', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce({ status: 'success' });
  await expect(publishToFeishu('note', 'title', 'body')).rejects.toThrow('未核验');
  expect(vi.mocked(apiJson).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0);
});
it('known failed automatic state permits deliberate manual publication without importing preference contacts', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce({ status: 'failed', can_check: false, error: 'failed' }).mockResolvedValueOnce({ id: 'manual-job' });
  await publishToFeishu('note', 'title', 'body');
  const body = JSON.parse(vi.mocked(apiJson).mock.calls[1][1]!.body as string);
  expect(body.automatic).toBe(false); expect(body.contacts).toBeUndefined(); expect(body.automatic_delivery_consent).toBeUndefined();
});
it('an ABA response from a previous owner visit is discarded without another dispatch', async () => {
  let finish!: (value: { status: 'unknown' }) => void;
  vi.mocked(apiJson).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }));
  const pending = readAutomaticDelivery('note'); const rejected = expect(pending).rejects.toThrow('账号');
  useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }); useAuthStore.setState({ user: { id: 'receipt-owner', email: 'test@example.invalid' } });
  finish({ status: 'unknown' }); await rejected; expect(apiJson).toHaveBeenCalledTimes(1);
});
it('device disable binds the expected user and never touches shared authorization or documents', async () => {
  vi.mocked(apiJson).mockResolvedValueOnce({ disabled: true });
  expect(await disableDeviceAutomaticDelivery('receipt-owner')).toEqual({ legacy: false });
  expect(apiJson).toHaveBeenCalledExactlyOnceWith('/api/feishu/automatic-deliveries/device-disable', { method: 'POST', cache: 'no-store', body: JSON.stringify({ expected_user_id: 'receipt-owner' }) });
});
it('a 404 fallback permits only an actually read legacy status and never masks protocol one', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce({ status: 404 }).mockResolvedValueOnce({ configured: true, connected: true, auto_publish: false, groups: [] });
  expect(await disableDeviceAutomaticDelivery('receipt-owner')).toEqual({ legacy: true });
  vi.mocked(apiJson).mockRejectedValueOnce({ status: 404 }).mockResolvedValueOnce({ configured: true, connected: true, auto_publish: false, groups: [], automatic_delivery_protocol: 1 });
  await expect(disableDeviceAutomaticDelivery('receipt-owner')).rejects.toThrow('关闭接口不可用');
});
it.each([2, 0, -1, NaN, Infinity, null, '1'])('protocol %s cannot use the no-protocol legacy device-stop bypass', async protocol => {
  vi.mocked(apiJson).mockRejectedValueOnce({ status: 404 }).mockResolvedValueOnce({ configured: true, connected: true, auto_publish: true, groups: [], automatic_delivery_protocol: protocol });
  await expect(disableDeviceAutomaticDelivery('receipt-owner')).rejects.toThrow('关闭接口不可用');
});
it('an invalid status or failed stop cannot authorize a legacy fallback', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce({ status: 404 }).mockResolvedValueOnce({});
  await expect(disableDeviceAutomaticDelivery('receipt-owner')).rejects.toThrow('关闭接口不可用');
  vi.mocked(apiJson).mockRejectedValueOnce(new Error('stop failed'));
  await expect(disableDeviceAutomaticDelivery('receipt-owner')).rejects.toThrow('stop failed');
  expect(apiJson).toHaveBeenCalledTimes(3);
});
it('unverified grant status is not evidence of a legacy service for the 404 fallback', async () => {
  vi.mocked(apiJson).mockRejectedValueOnce({ status: 404 }).mockResolvedValueOnce({ configured: true, connected: false, auto_publish: false, groups: [], connection_state: 'service_unavailable' });
  await expect(disableDeviceAutomaticDelivery('receipt-owner')).rejects.toThrow('关闭接口不可用');
});
it('stale owner and ABA disable acknowledgements never authorize a plugin write', async () => {
  await expect(disableDeviceAutomaticDelivery('other')).rejects.toThrow('账号'); expect(apiJson).not.toHaveBeenCalled();
  let finish!: (value: { disabled: true }) => void;
  vi.mocked(apiJson).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }));
  const pending = disableDeviceAutomaticDelivery('receipt-owner'), rejected = expect(pending).rejects.toThrow('账号');
  useAuthStore.setState({ user: { id: 'other', email: 'other@example.invalid' } }); useAuthStore.setState({ user: { id: 'receipt-owner', email: 'test@example.invalid' } });
  finish({ disabled: true }); await rejected;
});
