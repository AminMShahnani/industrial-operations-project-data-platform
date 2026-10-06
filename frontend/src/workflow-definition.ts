import type { components } from './api-schema';
type Definition = components['schemas']['WorkflowCreate']['definition'];
export function parseWorkflowDefinition(text: string): Definition {
  const value: unknown=JSON.parse(text);
  if (!value || typeof value!=='object' || !('form_id' in value) || typeof value.form_id!=='string' || !('form_number' in value) || typeof value.form_number!=='number' || !('nodes' in value) || !Array.isArray(value.nodes) || !('transitions' in value) || !Array.isArray(value.transitions)) throw new Error('Enter a workflow definition with nodes and transitions.');
  if (value.nodes.length < 2 || value.nodes.length > 100 || value.transitions.length < 1 || value.transitions.length > 200) throw new Error('Workflow exceeds graph limits.');
  for (const node of value.nodes as unknown[]) if (!node || typeof node!=='object' || !('key' in node) || typeof node.key!=='string' || !('name' in node) || typeof node.name!=='string' || !('kind' in node) || !['start','review','approval','decision','notify','end'].includes(String(node.kind))) throw new Error('Invalid workflow node.');
  for (const edge of value.transitions as unknown[]) if (!edge || typeof edge!=='object' || !('source' in edge) || typeof edge.source!=='string' || !('target' in edge) || typeof edge.target!=='string') throw new Error('Invalid workflow transition.');
  return value as Definition;
}
export function approvalWorkflow(form: string, number: number, recipients: string[], mode: 'one'|'all'|'quorum'|'sequential', quorum: number): Definition {
  if (!form || !Number.isSafeInteger(number) || number < 1 || !recipients.length || new Set(recipients).size !== recipients.length) throw new Error('Choose a published form and distinct approvers.');
  if (mode === 'quorum' && (!Number.isSafeInteger(quorum) || quorum < 1 || quorum > recipients.length)) throw new Error('Quorum must fit the approver list.');
  return { form_id: form, form_number: number, nodes: [
    {key:'start',name:'Start',kind:'start'},
    {key:'approval',name:'Approval',kind:'approval',assignments:recipients.map(target_id=>({kind:'user',target_id})),policy:{mode,...(mode==='quorum'?{quorum}:{})},return_to:'submitter'},
    {key:'end',name:'End',kind:'end'},
  ], transitions:[{source:'start',target:'approval',outcome:'continue'},{source:'approval',target:'end',outcome:'continue'}] };
}
