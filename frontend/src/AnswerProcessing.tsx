import './answer-processing.css';
export type Processing={run_id:string;provider:string;model:string|null;model_used:boolean|null;status:string};
const providers:Record<string,string>={local:'Lokal',openrouter:'OpenRouter',openai:'OpenAI direkt',anthropic:'Anthropic direkt'};
export function AnswerProcessing({processing}:{processing?:Processing|null}){
 if(!processing)return <small className="answer-processing" aria-label="Antwortverarbeitung" title="Für diese ältere Antwort ist kein Lauf eindeutig zugeordnet.">Verarbeitung nicht erfasst</small>;
 const provider=providers[processing.provider]||'Anbieter nicht erfasst';
 const model=processing.model_used===false?'Systemantwort':processing.model?.trim()||'Modell nicht erfasst';
 const title=processing.model_used===false?'Für diese Antwort wurde kein gesondertes Antwortmodell aufgerufen.':processing.model?'Für diese Antwort angefragtes Modell: '+processing.model+'. Anbieter können Modell-Aliase intern auflösen.':'Anbieter aus dem gespeicherten Antwortlauf; Modell wurde nicht erfasst.';
 return <small className="answer-processing" aria-label="Antwortverarbeitung" title={title}>{provider}<span aria-hidden="true"> · </span>{model}{['failed','cancelled','interrupted'].includes(processing.status)&&<span className="answer-partial"> · Teilantwort · {processing.status==='cancelled'?'abgebrochen':processing.status==='interrupted'?'unterbrochen':'unvollständig'}</span>}</small>;
}
