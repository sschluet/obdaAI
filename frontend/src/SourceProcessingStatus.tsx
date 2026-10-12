import './source-processing.css';
import {RotateCcw} from 'lucide-react';
type Source={name:string;status:string;error?:string};
export function SourceProcessingStatus({source,disabled,onRetry}:{source:Source;disabled:boolean;onRetry:()=>void}){
 if(source.status!=='failed')return null;
 return <div className="source-processing-error"><p role="alert">{source.error||'Die Quelle konnte noch nicht eingelesen werden. Bitte erneut verarbeiten.'}</p><p className="hint">Die Originaldatei bleibt unverändert. Ein neuer Versuch liest sie lokal erneut ein.</p><button type="button" disabled={disabled} aria-label={'Quelle erneut verarbeiten: '+source.name} onClick={onRetry}><RotateCcw size={14}/> Erneut verarbeiten</button></div>;
}
