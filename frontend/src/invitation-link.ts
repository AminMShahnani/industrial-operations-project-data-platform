export interface InvitationTarget { organization: string; invitation: string }

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function invitationTargetFromState(value: unknown): InvitationTarget | undefined {
  if (!value || typeof value !== 'object' || !('invitation' in value)) return;
  const target = value.invitation;
  if (!target || typeof target !== 'object' || !('organization' in target) || !('invitation' in target)) return;
  if (typeof target.organization !== 'string' || typeof target.invitation !== 'string' ||
      !uuid.test(target.organization) || !uuid.test(target.invitation)) return;
  return { organization: target.organization, invitation: target.invitation };
}

export function readInvitationTarget(search: string): InvitationTarget | undefined {
  const params = new URLSearchParams(search);
  if (params.getAll('organization').length !== 1 || params.getAll('invitation').length !== 1) return;
  return invitationTargetFromState({ invitation: {
    organization: params.get('organization'), invitation: params.get('invitation'),
  } });
}

export function invitationPath(target: InvitationTarget): string {
  return '/?' + new URLSearchParams({ organization: target.organization, invitation: target.invitation }).toString();
}

export function invitationRequestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let timestamp = Date.now();
  for (let index = 5; index >= 0; index--) { bytes[index] = timestamp % 256; timestamp = Math.floor(timestamp / 256); }
  bytes[6] = 0x70 | ((bytes[6] ?? 0) & 0x0f);
  bytes[8] = 0x80 | ((bytes[8] ?? 0) & 0x3f);
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
