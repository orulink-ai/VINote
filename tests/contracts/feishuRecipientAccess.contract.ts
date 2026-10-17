/** Shared synthetic backend/client wire contract; no network or product imports. */
import fixture from '../fixtures/feishu_recipient_access_contract.json';

type AccessPolicy = 'grant_view_and_notify';
type ReadingStatus = 'granting' | 'unknown' | 'verified' | 'failed' | 'unverified';
type Recipient = {
  status: 'pending' | 'sending' | 'sent' | 'failed' | 'unknown' | 'permission_unknown';
  reading_permission?: { status: ReadingStatus };
};
type Delivery = {
  status: 'queued' | 'processing' | 'completed' | 'failed';
  phase?: string;
  recipient_access_policy?: AccessPolicy | null;
  recipients: Record<string, Recipient>;
};
const check: (condition: unknown) => asserts condition = condition => {
  if (!condition) throw new Error('recipient access wire contract mismatch');
};

check(fixture.status.recipient_access_protocol === 1);
check(fixture.publish.recipient_access_policy === 'grant_view_and_notify');
check(fixture.publish.source_mode === 'local_snapshot');
check(fixture.unknown_delivery.phase === 'permission_unknown');
check(fixture.unknown_delivery.recipients.ou_b.status === 'permission_unknown');
check(fixture.unknown_delivery.recipients.ou_b.reading_permission.status === 'unknown');
check(fixture.verify_action.method === 'POST' && !fixture.verify_action.dispatch_worker);
check(fixture.verify_action.provider_business_methods.join() === 'GET');

const unknown: Recipient = { status: 'permission_unknown', reading_permission: { status: 'unknown' } };
const verified: Recipient = { status: 'pending', reading_permission: { status: 'verified' } };
const result: Delivery = { status: 'failed', phase: 'partial_success',
  recipient_access_policy: 'grant_view_and_notify', recipients: { ou_b: verified } };
check(unknown.status !== 'sent' && result.recipients.ou_b.status === 'pending');
// ACL verification is not a notification receipt.
// @ts-expect-error No edit/full-access policy is exposed by this protocol.
const edit: AccessPolicy = 'grant_edit';
// @ts-expect-error Provider grant success is not a verified reading state.
const premature: ReadingStatus = 'granted';
void edit; void premature;
