import { describe, expect, it } from 'vitest';
import { approvalWorkflow } from './workflow-definition';
describe('workflow approval configuration',()=>{
  it('preserves sequential order and requires distinct voters',()=>{
    const row=approvalWorkflow('form',1,['second','first'],'sequential',1);
    expect(row.nodes[1]?.assignments?.map(item=>item.target_id)).toEqual(['second','first']);
    expect(()=>approvalWorkflow('form',1,['first','first'],'all',1)).toThrow('distinct');
  });
  it('rejects unattainable quorum before publishing',()=>{
    expect(()=>approvalWorkflow('form',1,['first'],'quorum',2)).toThrow('Quorum');
    expect(approvalWorkflow('form',1,['first','second'],'quorum',2).nodes[1]?.policy?.quorum).toBe(2);
  });
});
