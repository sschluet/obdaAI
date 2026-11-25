import type {AgentJob} from './AgentRunsPanel';
const active=new Set(['queued','running','awaiting_approval','awaiting_input']);
/** Read-after-write polling must not undo a newer receipt already shown to its owner. */
export function latestAgentJob(previous:AgentJob|null,next:AgentJob|null):AgentJob|null{
 if(!previous)return next;
 if(!next)return active.has(previous.status)?previous:null;
 if(previous.id!==next.id){
  if(previous.created!==undefined&&next.created!==undefined&&previous.created!==next.created)return previous.created>next.created?previous:next;
  return active.has(previous.status)&&!active.has(next.status)?previous:next;
 }
 const sequence=(job:AgentJob)=>Math.max(0,...job.steps.map(step=>step.sequence));
 if(sequence(previous)>sequence(next))return previous;
 if(sequence(previous)===sequence(next)){
  if(active.has(previous.status)&&!active.has(next.status))return next;
  if(previous.cancel_requested&&!next.cancel_requested&&active.has(next.status))return previous;
  if(!active.has(previous.status)&&active.has(next.status))return previous;
  if(previous.steps.some(step=>step.approved&&!next.steps.find(row=>row.sequence===step.sequence)?.approved))return previous;
 }
 return next;
}
export function mergeAgentJobs(previous:AgentJob[],next:AgentJob[]):AgentJob[]{
 const result=next.map(job=>latestAgentJob(previous.find(old=>old.id===job.id)||null,job)!);
 for(const job of previous)if(active.has(job.status)&&!result.some(row=>row.id===job.id)&&!result.some(row=>job.created!==undefined&&row.created!==undefined&&row.created>job.created))result.unshift(job);
 return result;
}
