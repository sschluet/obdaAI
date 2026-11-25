import type {IntegrationRow} from './IntegrationRegistryPanel';
/** Registry execution_available describes legacy actions, not general agent permissions. */
export function integrationReadiness(row:IntegrationRow):'configured'|'unavailable'|'unknown'{
 if(!row.enabled)return 'unavailable';
 if(row.availability_reason&&row.availability_reason!=='ready')return 'unavailable';
 if(['gmail','google_drive'].includes(row.kind)&&!row.config.connected)return 'unavailable';
 if(row.last_check?.revision===row.revision&&row.last_check.status==='failed')return 'unavailable';
 if(row.availability_reason==='ready'||row.execution_available||row.last_check?.revision===row.revision&&row.last_check.status==='succeeded')return 'configured';
 return 'unknown';
}
