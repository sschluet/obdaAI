import {useRef,useState} from 'react';
import {UploadCloud,Plus} from 'lucide-react';
import './file-dropzone.css';
export function FileDropzone({disabled,onFiles,label='Dateien zum Projekt hinzufügen'}:{disabled:boolean;onFiles:(files:File[]|null)=>void|Promise<void>;label?:string}){
 const input=useRef<HTMLInputElement>(null),[dragging,setDragging]=useState(false);
 return <div className={'file-dropzone'+(dragging?' is-dragging':'')} onDragOver={event=>{event.preventDefault();if(!disabled)setDragging(true)}} onDragLeave={event=>{if(!event.currentTarget.contains(event.relatedTarget as Node))setDragging(false)}} onDrop={event=>{event.preventDefault();setDragging(false);if(!disabled)void onFiles(Array.from(event.dataTransfer.files))}}>
  <UploadCloud size={27} aria-hidden="true"/><strong>{dragging?'Hier ablegen':'Unterlagen als Kontext hinzufügen'}</strong><p>Dateien hier ablegen oder auswählen.<br/>Die Verarbeitung bleibt lokal.</p>
  <input ref={input} className="file-dropzone-input" type="file" multiple aria-label={label} tabIndex={-1} disabled={disabled} accept=".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={event=>{const files=Array.from(event.target.files||[]);event.target.value='';void onFiles(files)}}/>
  <button type="button" disabled={disabled} onClick={()=>input.current?.click()}><Plus size={16}/>{disabled?'Upload nicht verfügbar':'Dateien auswählen'}</button><small>Dokumente, Tabellen, Präsentationen und Bilder · bis 40 MiB je Datei</small>
 </div>;
}
