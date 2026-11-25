// Node24 executes the actual pure TS reducer; no browser, server or model side effects.
import assert from 'node:assert/strict';
import {latestAgentJob,mergeAgentJobs} from './src/agentJobState.ts';
import {reconciliationRequest} from './src/agentReconciliation.ts';
const row=(id,status,sequence=1,other={})=>({id,status,created:10,goal:'Synthetic',summary:'',cancel_requested:false,steps:[{sequence,status:'succeeded',kind:'read',document:{},result:{},sha256:'a'}],...other});
const pending=row('new','queued',1,{created:20}),old=row('old','uncertain',2,{created:10});
assert.equal(latestAgentJob(pending,old),pending);assert.equal(latestAgentJob(pending,null),pending);
const completed=row('newer','observed',1,{created:30});assert.equal(latestAgentJob(pending,completed),completed);
const previous=row('same','awaiting_input',4),reply=row('same','queued',5);assert.equal(latestAgentJob(previous,reply),reply);
const approval=row('same','awaiting_approval',4),approved=row('same','queued',4,{steps:[{...approval.steps[0],approved:true}]});assert.equal(latestAgentJob(approval,approved),approved);assert.equal(latestAgentJob(approved,approval),approved);
const cancelled=row('same','running',4,{cancel_requested:true});assert.equal(latestAgentJob(cancelled,row('same','running',4)),cancelled);
const revoked=row('same','cancelled',4);assert.equal(latestAgentJob(approved,revoked),revoked);
const done=row('same','failed',4);assert.equal(latestAgentJob(done,row('same','running',4)),done);
assert.equal(latestAgentJob(reply,previous),reply);assert.deepEqual(mergeAgentJobs([pending],[old]),[pending,old]);assert.deepEqual(mergeAgentJobs([pending],[completed]),[completed]);
console.log('Agent state checks passed: stale older-ID/step/cancel/approval receipts cannot undo accepted state; same-job reply/approval may legitimately requeue; newer completed jobs remain visible. No status-rank or heartbeat inference.');

// An accepted maximum-length source is referenced intact, never concatenated or truncated.
const source={id:'00000000-0000-0000-0000-000000000601',goal:'x'.repeat(8000)};
const request=reconciliationRequest('00000000-0000-0000-0000-000000000602',source);
assert.equal(source.goal.length,8000);assert.equal(source.goal,'x'.repeat(8000));
assert.equal(request.body.reconcile_job_id,source.id);assert.equal(request.body.read_only,true);assert.equal(request.body.research_allowed,false);
assert.ok(request.body.goal.length<160);assert.ok(!request.body.goal.includes(source.goal));
assert.equal(request.path,'/conversations/00000000-0000-0000-0000-000000000602/agent-runs');
assert.match(request.body.request_id,/^[0-9a-f-]{36}$/);
console.log('Bounded reconciliation request passed: 8000-character private source retained by server-bound source ID, no concatenation/truncation, explicit read-only/no-research authority.');
