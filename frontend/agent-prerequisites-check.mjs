// Node24 runs the actual shared UI helper, without providers or target calls.
import assert from 'node:assert/strict';
import {hasBackupBeforeUpdates,setBackupBeforeUpdates} from './src/agentPrerequisites.ts';
const operation={tool:'http',method:'POST',path:'/api/services/update/install'};
const requires={tool:'http',method:'POST',path:'/api/services/backup/create_automatic'};
const foreign={operation:{...operation,path:'/api/services/script/turn_on'},requires:{...requires}};
const extended={operation,requires,custom:'preserve'};
const original=[foreign,extended],snapshot=structuredClone(original);
assert.equal(hasBackupBeforeUpdates([]),false);
const enabled=setBackupBeforeUpdates(original,true);assert.equal(enabled.length,3);assert.equal(hasBackupBeforeUpdates(enabled),true);
assert.deepEqual(original,snapshot);assert.deepEqual(enabled.slice(0,2),snapshot);
assert.deepEqual(setBackupBeforeUpdates(enabled,true),enabled);
assert.deepEqual(setBackupBeforeUpdates(enabled,false),snapshot);
const reordered=[{requires:{path:requires.path,method:'POST',tool:'http'},operation:{path:operation.path,tool:'http',method:'POST'}}];
assert.equal(hasBackupBeforeUpdates(reordered),true);assert.deepEqual(setBackupBeforeUpdates(reordered,false),[]);
assert.deepEqual(setBackupBeforeUpdates([foreign],false),[foreign]);
console.log('HA prerequisite helper passed: optional empty default, idempotent exact rule toggle, object-order independence, no mutation, foreign/custom rule preservation.');

const basic={operation,requires:{...requires,path:'/api/services/backup/create'}};
assert.equal(hasBackupBeforeUpdates([foreign,basic]),true);
assert.deepEqual(setBackupBeforeUpdates([foreign,basic],true),[foreign,basic]);
assert.deepEqual(setBackupBeforeUpdates(setBackupBeforeUpdates([foreign,basic],false),true,[foreign,basic]),[foreign,basic]);
assert.deepEqual(setBackupBeforeUpdates([basic],false),[]);
console.log('HA backup defaults passed: new rule uses configured create_automatic; existing exact basic create stays recognized and unchanged, including off/on restoration without a second prerequisite.');
