/** This optional ordering rule adds no tool permission or autonomous authority. */
const backupBeforeUpdates={
 operation:{tool:'http',method:'POST',path:'/api/services/update/install'},
 requires:{tool:'http',method:'POST',path:'/api/services/backup/create_automatic'},
};
const existingBasicBackup={...backupBeforeUpdates,requires:{...backupBeforeUpdates.requires,path:'/api/services/backup/create'}};
function exactObject(value:unknown,expected:Record<string,unknown>):boolean{
 if(!value||typeof value!=='object'||Array.isArray(value))return false;
 const row=value as Record<string,unknown>;
 return Object.keys(row).length===Object.keys(expected).length&&Object.entries(expected).every(([key,item])=>typeof item==='object'?exactObject(row[key],item as Record<string,unknown>):row[key]===item);
}
function recognized(rule:unknown):boolean{return exactObject(rule,backupBeforeUpdates)||exactObject(rule,existingBasicBackup)}
export function hasBackupBeforeUpdates(rules:readonly unknown[]):boolean{return rules.some(recognized)}
export function backupBeforeUpdateMethods(rules:readonly unknown[]):string[]{
 return [
  ...(rules.some(rule=>exactObject(rule,backupBeforeUpdates))?['backup.create_automatic']:[]),
  ...(rules.some(rule=>exactObject(rule,existingBasicBackup))?['backup.create']:[]),
 ];
}
export function setBackupBeforeUpdates(rules:readonly unknown[],enabled:boolean,saved:readonly unknown[]=[]):unknown[]{
 if(!enabled)return rules.filter(rule=>!recognized(rule));
 if(hasBackupBeforeUpdates(rules))return [...rules];
 const original=saved.filter(recognized);
 return [...rules,...structuredClone(original.length?original:[backupBeforeUpdates])];
}
