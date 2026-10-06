import { describe, expect, it } from 'vitest';
import { parseSchedule } from './schedule-definition';
describe('schedule input boundary',()=>{
  it('keeps exact form versions and typed recurrence targets',()=>{
    const definition={form_id:'pinned',form_number:2,recurrence:{kind:'daily',timezone:'UTC',starts_local:'2026-10-06T09:00:00'},assignments:[{kind:'role',role:'Contributor'}]};
    expect(parseSchedule(JSON.stringify(definition))).toEqual(definition);
  });
  it('rejects malformed and oversized definition structures',()=>{
    for(const input of ['null','{}',JSON.stringify({form_id:'a',form_number:1,recurrence:{kind:'daily'},assignments:[{kind:'execute_code'}]}),' '.repeat(65537)]) expect(()=>parseSchedule(input)).toThrow();
  });
});
