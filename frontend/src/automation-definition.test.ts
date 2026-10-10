import { describe, expect, it } from 'vitest';
import { parseAutomationDefinition } from './automation-definition';
describe('automation declarative editor', () => {
  it('preserves pinned actions, channels and expression content for server validation', () => {
    const definition = { trigger: 'submission.submitted', form_id: 'form', form_number: 2,
      condition: { kind: 'literal', value: true }, actions: [{ kind: 'notify', recipients: ['recipient'], channels: ['email'] }, { kind: 'start_workflow', workflow_id: 'workflow', workflow_number: 3 }] };
    expect(parseAutomationDefinition(JSON.stringify(definition))).toEqual(definition);
  });
  it('rejects executable text and structurally empty or excessive actions', () => {
    for (const input of ['alert(1)', 'null', '{"trigger":"task.created","actions":[]}', JSON.stringify({ trigger: 'task.created', actions: Array.from({ length: 21 }, () => ({ kind: 'notify' })) })]) expect(() => parseAutomationDefinition(input)).toThrow();
  });
});
