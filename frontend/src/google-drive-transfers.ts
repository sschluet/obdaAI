import type {IntegrationAPI} from './IntegrationRegistryPanel';
import type {GoogleDriveSetupView} from './GoogleDriveSetupPanel';

type DriveTransfer = {id:string;request_id:string;status:string;integration_revision:number;[key:string]:unknown};
function transfers(value:unknown):DriveTransfer[]{
  if(Array.isArray(value))return value;
  if(value&&typeof value==='object'&&'transfers' in value&&Array.isArray(value.transfers))return value.transfers;
  return [];
}
/** Human-triggered status check. Reconciles only uncertain, currently authorized intents.
 * The server performs remote metadata GETs; this path never creates or uploads a file. */
export async function checkGoogleDriveTransfers(api:IntegrationAPI,integrationId:string,requestId?:string){
  const prefix='/integrations/google-drive/'+encodeURIComponent(integrationId);
  let setup:GoogleDriveSetupView=await api('/integrations/google-drive/setup?integration_id='+encodeURIComponent(integrationId));
  const existing=transfers(await api(prefix+'/exports'));
  for(const row of existing.slice(0,50)){
    if(row.status!=='uncertain'||(requestId&&row.request_id!==requestId)||row.integration_revision!==setup.revision||!row.id)continue;
    await api(prefix+'/exports/'+encodeURIComponent(row.id)+'/reconcile','POST',{expected_revision:setup.revision});
    setup=await api('/integrations/google-drive/setup?integration_id='+encodeURIComponent(integrationId));
  }
  const current=transfers(await api(prefix+'/exports'));
  return {setup,transfers:current};
}
