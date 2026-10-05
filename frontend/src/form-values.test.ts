import { describe, expect, it } from 'vitest';
import { editableValues } from './FormRuntime';
import type { components } from './api-schema';

describe('submission payload', () => {
  it('strips server-owned formulas and instructions at every repeating level', () => {
    const fields: components['schemas']['Component-Output'][] = [
      { key: 'quantity', label: 'Quantity', kind: 'integer', required: true },
      { key: 'total', label: 'Total', kind: 'calculated', required: false },
      { key: 'items', label: 'Items', kind: 'table', required: false, children: [
        { key: 'name', label: 'Name', kind: 'text', required: true },
        { key: 'derived', label: 'Derived', kind: 'calculated', required: false },
      ] },
    ];
    expect(editableValues(fields, { quantity: 3, total: '6', items: [{ name: 'Item', derived: '7' }] })).toEqual({ quantity: 3, items: [{ name: 'Item' }] });
  });
});
