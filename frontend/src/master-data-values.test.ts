import { expect, test } from 'vitest';
import { recordValues } from './master-data-values';

test('decimal precision and reference identifiers survive form serialization', () => {
  const form = new FormData();
  form.set('value-amount', '123456789012345678.123456');
  form.set('value-reference', '01a10c74-e65b-7006-85b3-ca890d11516c');
  form.set('value-count', '12');
  expect(recordValues([
    { key: 'amount', kind: 'decimal', required: true },
    { key: 'reference', kind: 'reference', required: true },
    { key: 'count', kind: 'integer', required: true },
    { key: 'enabled', kind: 'boolean', required: false },
  ], form)).toEqual({ amount: '123456789012345678.123456', reference: '01a10c74-e65b-7006-85b3-ca890d11516c', count: 12, enabled: false });
});

test('unsafe integers and expression text are rejected before submission', () => {
  const form = new FormData();
  for (const value of ['9007199254740993', '1e3', '1+2', '1.5']) {
    form.set('value-count', value);
    expect(() => recordValues([{ key: 'count', kind: 'integer', required: true }], form)).toThrow();
  }
});
