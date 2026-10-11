export type Appearance={revision:number;app_name:string;display_name:string;avatar_data_url:string|null;density:'compact'|'comfortable';accent:'indigo'|'blue'|'teal'|'rose'};
export const defaultAppearance:Appearance={revision:0,app_name:'obdaAI',display_name:'',avatar_data_url:null,density:'compact',accent:'indigo'};
export function initials(name:string){return name.trim().split(/\s+/).slice(0,2).map(word=>Array.from(word)[0]).join('').toLocaleUpperCase()||'Du'}
export async function prepareAvatar(file:File):Promise<string>{
 if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>8*1024*1024)throw Error('Bitte ein PNG-, JPEG- oder WebP-Foto bis 8 MB auswählen.');
 const bitmap=await createImageBitmap(file);try{if(!bitmap.width||!bitmap.height||bitmap.width*bitmap.height>40000000)throw Error('Dieses Bild ist zu groß. Bitte eine kleinere Aufnahme verwenden.');const canvas=document.createElement('canvas');canvas.width=canvas.height=256;const context=canvas.getContext('2d');if(!context)throw Error('Bildverarbeitung ist in diesem Browser nicht verfügbar.');const side=Math.min(bitmap.width,bitmap.height);context.drawImage(bitmap,(bitmap.width-side)/2,(bitmap.height-side)/2,side,side,0,0,256,256);return canvas.toDataURL('image/webp',.85)}finally{bitmap.close()}
}
