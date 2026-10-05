/** Parse our JSON contract without displaying proxy HTML or claiming a write failed. */
export async function apiResponse(response:Response,method:string):Promise<any>{
 let data:any;
 try{data=await response.json()}catch{
  const message=method==='GET'
   ?'obdaAI ist gerade nicht verfügbar. Die Ansicht wird erneut geprüft.'
   :'Die Aktion wurde nicht bestätigt. Prüfe ihren Status, bevor du sie erneut startest.';
  throw Object.assign(new Error(message),{status:response.status});
 }
 if(!response.ok){
  const detail=typeof data?.detail==='string'?data.detail.slice(0,500):
   response.status===422?'Bitte die Eingaben prüfen.':'Anfrage konnte nicht bestätigt werden.';
  throw Object.assign(new Error(detail),{status:response.status});
 }
 return data;
}
