export type UseCaseAPI=(path:string,method?:string,body?:unknown)=>Promise<any>;
export type AIField={key:string;label:string;type:'text'|'long_text'|'number'|'date'|'choice'|'file';required:boolean;choices:string[]};
export type AIColumn={label:string;source:string};
export type AISpec={name:string;description:string;presentation:'form'|'dialogue';fields:AIField[];output_kind:'table'|'csv'|'xlsx'|'bi'|'chat';output_columns:AIColumn[];text_template:string;processing_prompt:string;execution_kind:'ai'};
export type AICase={id:string;project_id:string|null;revision:number;spec:AISpec};
export const aiOutputLabels={chat:'KI-Antwort',table:'Tabelle',csv:'CSV',xlsx:'Excel',bi:'Diagramm'};
export const aiFieldLabels={text:'Text',long_text:'Mehrzeilig',number:'Zahl',date:'Datum',choice:'Auswahl',file:'Datei'};
export function newAISpec():AISpec{return {name:'',description:'',presentation:'form',fields:[{key:'feld_1',label:'Deine Anforderung',type:'long_text',required:true,choices:[]}],output_kind:'chat',output_columns:[],text_template:'',execution_kind:'ai',processing_prompt:''}}
export type AIRun={id:string;revision:number;created:number;spec:AISpec;status:string;execution_run_id?:string;values:Record<string,unknown>;output:{columns:string[];rows?:unknown[][];row:unknown[];text:string;chart:{label:string;value:number}[]};provider?:string;model?:string;error?:string;files?:{id:string;name:string;field:string;receipt?:{notes:string[]}}[]};
export type AIDialogue={id:string;revision:number;turn:number;status:string;model_mode:'auto'|'local'|'cloud';execution_run_id?:string;messages:{role:string;content:string}[];values:Record<string,unknown>;ready:boolean;error?:string;provider?:string;model?:string};
export const pendingAI=(status:string)=>['queued','routing','streaming','pending','running'].includes(status);
