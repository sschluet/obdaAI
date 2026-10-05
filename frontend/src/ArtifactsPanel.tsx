import {useEffect, useState} from 'react';
import type {FormEvent} from 'react';

type API = (path:string, method?:string, body?:unknown)=>Promise<any>;
type Source = {id:string; name:string; sha256:string; revision:number};
type Row = {artifact_id:string; revision:number; title:string; kind:string; status:string;
  error:string; spec:any; spec_sha256:string; output:any; accepted:number|null};
type Section = {heading:string; paragraphs:string; table:string[][]};
type Slide = {title:string; bullets:string; notes:string};
type Page = {sourceId:string; page:number; rotation:number};
type Tile = {sourceId:string; crop:number[]};
const status:Record<string,string> = {queued:'In Warteschlange', rendering:'Datei und Vorschau werden erstellt',
  needs_review:'Vorschau prüfen', published:'Freigegeben', failed:'Fehlgeschlagen', cancelled:'Abgebrochen'};

export function ArtifactsPanel({api, project, sources}:{api:API;
  project:{id:string; archived:boolean}; sources:Source[]}) {
  const [configured,setConfigured] = useState(false), [rows,setRows] = useState<Row[]>([]);
  const [editing,setEditing] = useState(false), [original,setOriginal] = useState<Row|null>(null);
  const [kind,setKind] = useState('docx'), [title,setTitle] = useState('');
  const [sections,setSections] = useState<Section[]>([{heading:'Ergebnis',paragraphs:'',table:[]}]);
  const [boundIds,setBoundIds] = useState<string[]>([]);
  const [slides,setSlides] = useState<Slide[]>([{title:'',bullets:'',notes:''}]);
  const [pages,setPages] = useState<Page[]>([]), [tiles,setTiles] = useState<Tile[]>([]);
  const [columns,setColumns] = useState(1), [width,setWidth] = useState(1024), [height,setHeight] = useState(768);
  const [format,setFormat] = useState('png'), [busy,setBusy] = useState(false), [error,setError] = useState('');
  const [preview,setPreview] = useState<Row|null>(null), [reviewed,setReviewed] = useState(false);
  const prefix = '/projects/'+project.id+'/artifacts';
  const pdfs = sources.filter(s=>/\.pdf$/i.test(s.name));
  const images = sources.filter(s=>/\.(png|jpe?g|webp)$/i.test(s.name));
  const base = (r:Row)=>prefix+'/'+r.artifact_id+'/versions/'+r.revision;
  useEffect(()=>{
    let alive = true;
    const refresh = async()=>{
      const [state,list] = await Promise.all([api('/artifact-status'),api(prefix)]);
      if(!alive)return;
      setConfigured(state.configured);setRows(list);
      setPreview(old=>old?(list.find((r:Row)=>r.artifact_id===old.artifact_id&&r.revision===old.revision)||old):null);
    };
    void refresh().catch(e=>{if(alive)setError(e.message)});
    const timer=setInterval(()=>void refresh().catch(()=>{}),3000);
    return()=>{alive=false;clearInterval(timer)};
  },[project.id]);
  function start(row:Row|null=null){
    setError('');setOriginal(row);setTitle(row?.title||'');setKind(row?.kind||'docx');
    const plan=row?.spec.plan;
    setSections(plan?.sections?.map((s:any)=>({heading:s.heading,paragraphs:s.paragraphs.join('\n\n'),table:s.table||[]}))||[{heading:'Ergebnis',paragraphs:'',table:[]}]);
    setBoundIds(row?.spec.sources?.map((s:any)=>s.id)||[]);
    setSlides(plan?.slides?.map((s:any)=>({title:s.title,bullets:s.bullets.join('\n'),notes:s.notes||''}))||[{title:'',bullets:'',notes:''}]);
    const bound=row?.spec.sources||[];
    setPages(plan?.pages?.map((p:any)=>({sourceId:bound[p.source].id,page:p.page,rotation:p.rotation}))||[]);
    setTiles(plan?.tiles?.map((t:any)=>({sourceId:bound[t.source].id,crop:t.crop.map((v:number)=>v*100)}))||[]);
    setColumns(plan?.columns||1);setWidth(plan?.tile_width||1024);setHeight(plan?.tile_height||768);
    setFormat(plan?.format||'png');setEditing(true);
  }
  function move<T>(list:T[],index:number,direction:number):T[]{
    const next=[...list],other=index+direction;if(other<0||other>=list.length)return next;
    [next[index],next[other]]=[next[other],next[index]];return next;
  }
  async function save(event:FormEvent){
    event.preventDefault();if(busy)return;setBusy(true);setError('');
    try{
      const sourceIds=Array.from(new Set(kind==='pdf'?pages.map(p=>p.sourceId):kind==='image'?tiles.map(t=>t.sourceId):boundIds));
      if(sourceIds.some(id=>!id||!sources.find(s=>s.id===id)))throw Error('Bitte für jede Seite bzw. jedes Bild eine Quelldatei auswählen.');
      const bindings=sourceIds.map(id=>{const s=sources.find(s=>s.id===id)!;return{id:s.id,revision:s.revision,sha256:s.sha256}});
      let plan:any;
      if(kind==='docx'){
        const entries=sections.map(s=>({heading:s.heading,paragraphs:s.paragraphs.split(/\n\s*\n/).map(p=>p.trim()).filter(Boolean),table:s.table}));
        if(entries.some(s=>s.paragraphs.length>30||s.paragraphs.some(p=>p.length>4000)))throw Error('Je Abschnitt maximal 30 Absätze mit jeweils 4000 Zeichen verwenden.');
        plan={kind,title,sections:entries};
      }
      else if(kind==='pptx'){
        const entries=slides.map(s=>({title:s.title,notes:s.notes,bullets:s.bullets.split('\n').map(v=>v.trim()).filter(Boolean)}));
        if(entries.some(s=>!s.bullets.length||s.bullets.length>5||s.bullets.some(v=>v.length>140)))throw Error('Je Folie bitte ein bis fünf Stichpunkte mit maximal 140 Zeichen eingeben.');
        plan={kind,title,slides:entries};
      }else if(kind==='pdf'){
        if(!pages.length)throw Error('Bitte mindestens eine Ausgabeseite hinzufügen.');
        plan={kind,title,pages:pages.map(p=>({source:sourceIds.indexOf(p.sourceId),page:p.page,rotation:p.rotation}))};
      }else{
        if(!tiles.length)throw Error('Bitte mindestens ein Bild hinzufügen.');
        plan={kind:'image',title,tiles:tiles.map(t=>({source:sourceIds.indexOf(t.sourceId),crop:t.crop.map(v=>v/100)})),columns,tile_width:width,tile_height:height,format};
      }
      const body={request_id:crypto.randomUUID(),spec:{plan,sources:bindings},...(original?{expected_revision:original.revision}:{})};
      await api(original?prefix+'/'+original.artifact_id+'/versions':prefix,'POST',body);
      setRows(await api(prefix));setEditing(false);
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function accept(){
    if(!preview||busy)return;setBusy(true);setError('');
    try{await api(base(preview)+'/accept','POST',{spec_sha256:preview.spec_sha256,output_sha256:preview.output.sha256,reviewed_all_pages:reviewed});setRows(await api(prefix));setPreview(null)}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  return <section className="setting-card">
    <h2>Dateien erstellen und bearbeiten</h2>
    <p>Word und PowerPoint erstellen, PDF-Seiten zusammenstellen oder Bilder zuschneiden. Jede Ausgabe erhält eine eigene Version mit Vorschau.</p>
    {!configured&&<p className="hint">Der lokale Dateirunner ist noch nicht eingerichtet. Vorhandene Originale kannst du weiterhin im Bereich Dokumente verwenden.</p>}
    {error&&!editing&&!preview&&<p className="error" role="alert">{error}</p>}
    <button className="primary" disabled={!configured||project.archived} onClick={()=>start()}>Neue Datei erstellen</button>
    {!rows.length&&<p className="muted">Noch keine erzeugten Dateien in diesem Projektraum.</p>}
    {rows.map(row=><article key={row.artifact_id+'-'+row.revision} className="citation">
      <b>{row.title} · Version {row.revision}</b><p>{status[row.status]||row.status} · {row.kind==='image'?'Bild':row.kind.toUpperCase()} · Lokal</p>
      {row.error&&<p className="error">{row.error}</p>}
      {['needs_review','published'].includes(row.status)&&<button onClick={()=>{setError('');setReviewed(false);setPreview(row)}}>Vorschau öffnen</button>}
      {row.status==='published'&&<a href={'/api'+base(row)+'/download'} download>Datei herunterladen</a>}
      {configured&&!project.archived&&row.revision===Math.max(...rows.filter(r=>r.artifact_id===row.artifact_id).map(r=>r.revision))&&<button onClick={()=>start(row)}>Neue Version bearbeiten</button>}
      {['queued','rendering','needs_review','failed'].includes(row.status)&&<button disabled={busy} onClick={async()=>{setBusy(true);try{await api(base(row)+'/cancel','POST');setRows(await api(prefix))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>Diese Version abbrechen</button>}
    </article>)}
    {editing&&<div className="modal"><div role="dialog" aria-modal="true" aria-label="Datei erstellen">
      <h2>{original?'Neue Dateiversion':'Neue Datei'}</h2>
      <p>Die Erstellung erfolgt lokal. Nach der Verarbeitung prüfst du die Vorschau und gibst die Datei zum Download frei.</p>
      {error&&<p className="error" role="alert">{error}</p>}
      <form onSubmit={save}>
        <label>Dateiformat<select aria-label="Dateiformat" value={kind} onChange={e=>{setKind(e.target.value);setError('')}}><option value="docx">Word-Dokument</option><option value="pptx">PowerPoint-Präsentation</option><option value="pdf">PDF-Seiten bearbeiten</option><option value="image">Bild / Collage</option></select></label>
        <label>Dateititel<input required value={title} maxLength={160} onChange={e=>setTitle(e.target.value)}/></label>
        {kind==='docx'&&<>{sections.map((section,index)=><fieldset key={index}><legend>Abschnitt {index+1}</legend>
          <label>Abschnittsüberschrift<input required maxLength={160} value={section.heading} onChange={e=>setSections(sections.map((s,i)=>i===index?{...s,heading:e.target.value}:s))}/></label>
          <label>Dokumenttext<textarea aria-label="Dokumenttext" maxLength={30000} rows={8} value={section.paragraphs} onChange={e=>setSections(sections.map((s,i)=>i===index?{...s,paragraphs:e.target.value}:s))}/></label>
          {section.table.map((row,r)=><fieldset key={r}><legend>Tabellenzeile {r+1}</legend>{row.map((cell,col)=><label key={col}>Spalte {col+1}<input required maxLength={160} value={cell} onChange={e=>setSections(sections.map((s,i)=>i===index?{...s,table:s.table.map((cells,j)=>j===r?cells.map((value,c)=>c===col?e.target.value:value):cells)}:s))}/></label>)}<button type="button" onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,table:s.table.filter((_,j)=>j!==r)}:s))}>Tabellenzeile entfernen</button></fieldset>)}
          {!section.table.length?<button type="button" onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,table:[['',''],['','']]}:s))}>Tabelle hinzufügen</button>:<><button type="button" disabled={section.table.length>=30} onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,table:[...s.table,s.table[0].map(()=>'')]}:s))}>Tabellenzeile hinzufügen</button><button type="button" disabled={section.table[0].length>=6} onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,table:s.table.map(row=>[...row,''])}:s))}>Tabellenspalte hinzufügen</button><button type="button" onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,table:[]}:s))}>Tabelle entfernen</button></>}
          <button type="button" disabled={index===0} onClick={()=>setSections(move(sections,index,-1))}>Abschnitt nach oben</button><button type="button" disabled={sections.length===1} onClick={()=>setSections(sections.filter((_,i)=>i!==index))}>Abschnitt entfernen</button>
        </fieldset>)}<button type="button" disabled={sections.length>=30} onClick={()=>setSections([...sections,{heading:'',paragraphs:'',table:[]}])}>Abschnitt hinzufügen</button><p className="hint">Eine Leerzeile trennt die Absätze. Text und Tabellen bleiben editierbar.</p></>}
        {kind==='pptx'&&<><p>{slides.length} Folie{slides.length===1?'':'n'} · Die Ausgabe enthält genau diese Folien.</p>{slides.map((slide,index)=><fieldset key={index}><legend>Folie {index+1}</legend>
          <label>Folientitel<input required maxLength={160} value={slide.title} onChange={e=>setSlides(slides.map((s,i)=>i===index?{...s,title:e.target.value}:s))}/></label>
          <label>Stichpunkte<textarea aria-label="Stichpunkte" required rows={5} value={slide.bullets} onChange={e=>setSlides(slides.map((s,i)=>i===index?{...s,bullets:e.target.value}:s))}/></label><p className="hint">Ein Stichpunkt je Zeile, maximal fünf.</p>
          <label>Sprechernotizen<textarea aria-label="Sprechernotizen" maxLength={4000} value={slide.notes} onChange={e=>setSlides(slides.map((s,i)=>i===index?{...s,notes:e.target.value}:s))}/></label>
          <button type="button" disabled={index===0} onClick={()=>setSlides(move(slides,index,-1))}>Folie nach oben</button><button type="button" disabled={index===slides.length-1} onClick={()=>setSlides(move(slides,index,1))}>Folie nach unten</button><button type="button" disabled={slides.length===1} onClick={()=>setSlides(slides.filter((_,i)=>i!==index))}>Folie entfernen</button>
        </fieldset>)}<button type="button" disabled={slides.length>=30} onClick={()=>setSlides([...slides,{title:'',bullets:'',notes:''}])}>Folie hinzufügen</button></>}
        {kind==='pdf'&&<><p>Füge die gewünschten Ausgabeseiten in ihrer Reihenfolge hinzu. Nicht ausgewählte Seiten werden weggelassen; Originale bleiben erhalten.</p>{!pdfs.length&&<p>Bitte zuerst eine PDF unter Dokumente hinzufügen.</p>}{pages.map((page,index)=><fieldset key={index}><legend>Ausgabeseite {index+1}</legend>
          <label>PDF-Quelldatei<select aria-label="PDF-Quelldatei" required value={page.sourceId} onChange={e=>setPages(pages.map((p,i)=>i===index?{...p,sourceId:e.target.value}:p))}><option value="">Bitte auswählen</option>{pdfs.map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</select></label>
          <label>Seite im Original<input type="number" required min={1} max={1000} value={page.page} onChange={e=>setPages(pages.map((p,i)=>i===index?{...p,page:Number(e.target.value)}:p))}/></label>
          <label>Im Uhrzeigersinn drehen<select aria-label="Im Uhrzeigersinn drehen" value={page.rotation} onChange={e=>setPages(pages.map((p,i)=>i===index?{...p,rotation:Number(e.target.value)}:p))}>{[0,90,180,270].map(v=><option key={v} value={v}>{v}°</option>)}</select></label>
          <button type="button" disabled={index===0} onClick={()=>setPages(move(pages,index,-1))}>Seite nach oben</button><button type="button" disabled={index===pages.length-1} onClick={()=>setPages(move(pages,index,1))}>Seite nach unten</button><button type="button" onClick={()=>setPages(pages.filter((_,i)=>i!==index))}>Seite entfernen</button>
        </fieldset>)}<button type="button" disabled={!pdfs.length||pages.length>=100} onClick={()=>setPages([...pages,{sourceId:pdfs[0].id,page:1,rotation:0}])}>Ausgabeseite hinzufügen</button><p className="hint">Signierte und verschlüsselte PDF werden hier nicht verändert. Die neue PDF übernimmt Seiteninhalte; Kommentare, Formularfelder und Links werden entfernt.</p></>}
        {kind==='image'&&<><p>Wähle echte hochgeladene Bilder. Zuschnitte werden in Prozent der Bildbreite bzw. -höhe angegeben.</p>{!images.length&&<p>Bitte zuerst ein Bild unter Dokumente hinzufügen.</p>}{tiles.map((tile,index)=><fieldset key={index}><legend>Bild {index+1}</legend>
          <label>Bildquelle<select aria-label="Bildquelle" required value={tile.sourceId} onChange={e=>setTiles(tiles.map((t,i)=>i===index?{...t,sourceId:e.target.value}:t))}><option value="">Bitte auswählen</option>{images.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          {['Linker Rand (%)','Oberer Rand (%)','Rechter Rand (%)','Unterer Rand (%)'].map((label,part)=><label key={part}>{label}<input type="number" required min={0} max={100} step={0.1} value={tile.crop[part]} onChange={e=>setTiles(tiles.map((t,i)=>i===index?{...t,crop:t.crop.map((v,j)=>j===part?Number(e.target.value):v)}:t))}/></label>)}
          <button type="button" disabled={index===0} onClick={()=>setTiles(move(tiles,index,-1))}>Bild nach oben</button><button type="button" onClick={()=>setTiles(tiles.filter((_,i)=>i!==index))}>Bild entfernen</button>
        </fieldset>)}<button type="button" disabled={!images.length||tiles.length>=12} onClick={()=>setTiles([...tiles,{sourceId:images[0].id,crop:[0,0,100,100]}])}>Bild hinzufügen</button>
          <label>Spalten in der Collage<input type="number" min={1} max={4} value={columns} onChange={e=>setColumns(Number(e.target.value))}/></label>
          <label>Breite je Bild (Pixel)<input type="number" min={128} max={2048} value={width} onChange={e=>setWidth(Number(e.target.value))}/></label>
          <label>Höhe je Bild (Pixel)<input type="number" min={128} max={2048} value={height} onChange={e=>setHeight(Number(e.target.value))}/></label>
          <label>Bildformat<select aria-label="Bildformat" value={format} onChange={e=>setFormat(e.target.value)}><option value="png">PNG</option><option value="jpeg">JPEG</option></select></label>
        </>}
        {['docx','pptx'].includes(kind)&&sources.length>0&&<details><summary>Gebundene Quelldateien</summary><p className="hint">Die Auswahl dokumentiert die zugehörigen Originale. Der eingegebene Text wird unverändert übernommen.</p>{sources.map(source=><label key={source.id}><input type="checkbox" checked={boundIds.includes(source.id)} onChange={e=>setBoundIds(e.target.checked?[...boundIds,source.id]:boundIds.filter(id=>id!==source.id))}/>{source.name}</label>)}</details>}
        <p className="hint">Neue Versionen ersetzen keine älteren Dateien. Quellen anderer Projekte werden nicht einbezogen.</p>
        <button className="primary" disabled={busy}>Datei und Vorschau erstellen</button>
      </form><button disabled={busy} onClick={()=>setEditing(false)}>Abbrechen</button>
    </div></div>}
    {preview&&<div className="modal"><div role="dialog" aria-modal="true" aria-label="Dateivorschau">
      <h2>{preview.title} · Version {preview.revision}</h2>
      {error&&<p className="error" role="alert">{error}</p>}
      <p>{preview.output?.previews.length||0} Vorschauseiten · Lokal · {status[preview.status]}</p>
      {preview.output?.previews.map((page:any)=><figure key={page.page}><img className="artifact-preview" src={'/api'+base(preview)+'/preview/'+page.page} alt={'Vorschauseite '+page.page}/><figcaption>Seite {page.page}</figcaption></figure>)}
      {preview.status==='needs_review'&&<><label><input type="checkbox" checked={reviewed} onChange={e=>setReviewed(e.target.checked)}/> Ich habe alle Vorschauseiten geprüft.</label><button className="primary" disabled={!reviewed||busy} onClick={()=>void accept()}>Diese Dateiversion freigeben</button></>}
      {preview.status==='published'&&<a href={'/api'+base(preview)+'/download'} download>Datei herunterladen</a>}
      <button disabled={busy} onClick={()=>{setPreview(null);setError('')}}>Schließen</button>
    </div></div>}
  </section>;
}
