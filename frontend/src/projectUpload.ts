// Project sources retain the raw bytes and encoded filename accepted by the API.
export async function uploadProjectSource(projectId:string,file:File,csrf:string):Promise<void>{
 if(file.size>40*1024*1024)throw Error('Eine Datei darf höchstens 40 MiB groß sein.');
 let response:Response;
 try{response=await fetch('/api/projects/'+encodeURIComponent(projectId)+'/sources',{method:'POST',headers:{'X-CSRF-Token':csrf,'X-File-Name':encodeURIComponent(file.name),'Content-Type':'application/octet-stream'},body:file})}
 catch{throw Error('Die Datei konnte nicht übertragen werden. Bitte Verbindung prüfen und erneut versuchen.');}
 if(response.ok)return;
 // A reverse proxy may return HTML or an empty body; never require JSON here.
 let detail:string|undefined;
 try{const payload:unknown=JSON.parse(await response.text());if(payload&&typeof payload==='object'&&'detail' in payload&&typeof payload.detail==='string')detail=payload.detail}catch{/* Use the HTTP status if no API error is available. */}
 if(detail)throw Error(detail);
 if(response.status===413)throw Error('Der Server hat die Datei wegen ihrer Größe abgelehnt. Erlaubt sind bis zu 40 MiB je Datei.');
 if(response.status===401)throw Error('Deine Anmeldung ist abgelaufen. Bitte erneut anmelden.');
 if(response.status===403)throw Error('Der Upload wurde nicht freigegeben. Bitte die Seite neu laden und erneut versuchen.');
 throw Error('Die Datei konnte nicht hochgeladen werden (HTTP '+response.status+'). Bitte erneut versuchen.');
}
