import {useEffect, useRef, useState} from 'react';
import type {FormEvent} from 'react';
import {FileText,Presentation,Files,Image,Check} from 'lucide-react';
import './artifacts.css';

export type ArtifactSeed = {project_id:string|null;conversation_id:string;message_id:string;revision:number;content:string};
type API = (path:string, method?:string, body?:unknown)=>Promise<any>;
type Source = {id:string; name:string; sha256:string; revision:number};
type Row = {artifact_id:string; revision:number; title:string; kind:string; status:string;
  error:string; spec:any; spec_sha256:string; output:any; accepted:number|null; draft?:any; chat?:any};
type DocumentImage = {sourceId:string;caption:string;width:number};
type Section = {heading:string; paragraphs:string; table:string[][]; images?:DocumentImage[]};
type Slide = {title:string; bullets:string; notes:string};
type Page = {sourceId:string; page:number; rotation:number; splitAfter?:boolean};
type Tile = {sourceId:string; crop:number[];caption?:string};
type FileTemplate = {id:string;kind:'docx'|'pptx';name:string;headings:string[];instruction:string};
const fileTemplates:FileTemplate[] = [
  {id:'project-overview',kind:'docx',name:'Projektübersicht',headings:['Ziel und Umfang','Aktueller Stand','Risiken und offene Fragen','Nächste Schritte'],instruction:'Erstelle eine Projektübersicht mit Ziel und Umfang, aktuellem Stand, Risiken und offenen Fragen sowie nächsten Schritten.'},
  {id:'meeting-note',kind:'docx',name:'Besprechungsnotiz',headings:['Anlass und Teilnehmende','Besprochene Themen','Entscheidungen','Aufgaben und offene Punkte'],instruction:'Erstelle eine Besprechungsnotiz mit Anlass und Teilnehmenden, besprochenen Themen, Entscheidungen sowie Aufgaben und offenen Punkten.'},
  {id:'decision-brief',kind:'docx',name:'Entscheidungsvorlage',headings:['Entscheidungsfrage','Optionen und Kriterien','Abwägung','Entscheidung und nächste Schritte'],instruction:'Erstelle eine Entscheidungsvorlage mit Entscheidungsfrage, Optionen und Kriterien, Abwägung sowie Entscheidung und nächsten Schritten. Kennzeichne eine noch ausstehende Entscheidung.'},
  {id:'project-status',kind:'pptx',name:'Projektstatus',headings:['Ziel und Überblick','Fortschritt und Ergebnisse','Risiken und offene Fragen','Nächste Schritte'],instruction:'Erstelle eine Projektstatus-Präsentation mit vier Folien: Ziel und Überblick, Fortschritt und Ergebnisse, Risiken und offene Fragen, nächste Schritte.'},
];
const fileFormats=[
  {id:'docx',label:'Word-Dokument',short:'Word',description:'Texte und Tabellen',icon:FileText},
  {id:'pptx',label:'PowerPoint-Präsentation',short:'Präsentation',description:'Folien und Notizen',icon:Presentation},
  {id:'pdf',label:'PDF-Dokument',short:'PDF',description:'Dokument oder Seiten',icon:Files},
  {id:'image',label:'Bild / Collage',short:'Bild',description:'Ausschnitte und Collagen',icon:Image},
];
const status:Record<string,string> = {queued:'In Warteschlange', rendering:'Datei und Vorschau werden erstellt',
  needs_review:'Vorschau prüfen', published:'Freigegeben', failed:'Fehlgeschlagen', cancelled:'Abgebrochen'};

export function ArtifactsPanel({api, project, sources, seed, embedded=false, contextLabel, initialArtifactId}:{api:API;initialArtifactId?:string|null;seed?:ArtifactSeed|null;embedded?:boolean;contextLabel?:string;
  project:{id:string; archived:boolean}; sources:Source[]}) {
  const appliedTarget=useRef<string|null>(null);
  const targetRow=useRef<HTMLElement|null>(null);
  const [highlighted,setHighlighted]=useState<string|null>(null);
  const storageKey='hub-ui-draft:artifact:'+project.id;
  const [savedDraft,setSavedDraft] = useState<any|null>(null);
  const [resumeNotice,setResumeNotice] = useState('');
  const [resumeNeedsReview,setResumeNeedsReview] = useState(false);
  const [templateId,setTemplateId] = useState('');
  const [pendingTemplate,setPendingTemplate] = useState<FileTemplate|null>(null);
  const [templateNotice,setTemplateNotice] = useState('');
  const [mode,setMode] = useState<'model'|'manual'>('model');
  const [contentOpen,setContentOpen] = useState(false);
  const [configured,setConfigured] = useState(false), [rows,setRows] = useState<Row[]>([]);
  const [editing,setEditing] = useState(false), [original,setOriginal] = useState<Row|null>(null);
  const [kind,setKind] = useState('docx'), [title,setTitle] = useState('');
  const [sections,setSections] = useState<Section[]>([{heading:'Ergebnis',paragraphs:'',table:[]}]);
  const [boundIds,setBoundIds] = useState<string[]>([]);
  const [pdfExport,setPdfExport] = useState(false), [pdfMode,setPdfMode] = useState('pages');
  const [slides,setSlides] = useState<Slide[]>([{title:'',bullets:'',notes:''}]);
  const [pages,setPages] = useState<Page[]>([]), [tiles,setTiles] = useState<Tile[]>([]);
  const [columns,setColumns] = useState(1), [width,setWidth] = useState(1024), [height,setHeight] = useState(768);
  const [format,setFormat] = useState('png'), [busy,setBusy] = useState(false), [error,setError] = useState('');
  const [chatSource,setChatSource] = useState<any|null>(null);
  const [goal,setGoal] = useState(''), [draftToken,setDraftToken] = useState<string|null>(null), [draftInfo,setDraftInfo] = useState<any|null>(null), [slideCount,setSlideCount] = useState(3);
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
  useEffect(()=>{
    if(!initialArtifactId||appliedTarget.current===initialArtifactId||editing)return;
    const latest=rows.filter(r=>r.artifact_id===initialArtifactId).sort((a,b)=>b.revision-a.revision)[0];
    if(!latest)return;
    appliedTarget.current=initialArtifactId;setHighlighted(latest.artifact_id+'-'+latest.revision);setReviewed(false);setError('');
    if(['needs_review','published'].includes(latest.status))setPreview(latest);
  },[initialArtifactId,rows,editing]);
  useEffect(()=>{if(!highlighted)return;targetRow.current?.scrollIntoView({block:'center'});targetRow.current?.focus({preventScroll:true})},[highlighted]);
  useEffect(()=>{
    try { const raw=sessionStorage.getItem(storageKey);const value=raw?JSON.parse(raw):null;
      setSavedDraft(value?.schema===1&&value.projectId===project.id?value:null);
    } catch { setSavedDraft(null); }
  },[storageKey]);
  useEffect(()=>{
    if(!editing)return;
    const sourceIds=Array.from(new Set([...boundIds,...pages.map(p=>p.sourceId),...tiles.map(t=>t.sourceId),...sections.flatMap(s=>(s.images||[]).map(i=>i.sourceId))])).filter(Boolean);
    const value={schema:1,templateId,requiresReview:resumeNeedsReview,projectId:project.id,kind,title,sections,boundIds,pdfExport,pdfMode,slides,pages,tiles,columns,width,height,format,goal,slideCount,
      original:original?{artifact_id:original.artifact_id,revision:original.revision,spec_sha256:original.spec_sha256}:null,
      chatSource,sourceBindings:sourceIds.map(id=>sources.find(s=>s.id===id)).filter(Boolean)};
    try { sessionStorage.setItem(storageKey,JSON.stringify(value));setSavedDraft(value); } catch { /* Storage can be disabled or full. In-memory editing stays available. */ }
  },[editing,kind,title,sections,boundIds,pdfExport,pdfMode,slides,pages,tiles,columns,width,height,format,goal,slideCount,original,chatSource,storageKey,resumeNeedsReview,templateId]);
  function discardDraft(){try{sessionStorage.removeItem(storageKey)}catch{}setSavedDraft(null);setResumeNotice('');setResumeNeedsReview(false);}
  async function resumeDraft(){
    const saved=savedDraft;if(!saved||busy)return;setBusy(true);setError('');
    try{
      const bindings=saved.sourceBindings||[];
      const stale=new Set<string>(bindings.filter((old:Source)=>!sources.some(s=>s.id===old.id&&s.revision===old.revision&&s.sha256===old.sha256)).map((s:Source)=>s.id));
      let origin:Row|null=null,chat=saved.chatSource;
      const notices:string[]=saved.requiresReview?['Der Entwurf benötigt weiterhin eine erneute Planung oder eine ausdrückliche manuelle Kopie.']:[];
      if(saved.original){const current=await api(prefix);origin=current.find((r:Row)=>r.artifact_id===saved.original.artifact_id&&r.revision===saved.original.revision&&r.spec_sha256===saved.original.spec_sha256)||null;
        if(current.some((r:Row)=>r.artifact_id===saved.original.artifact_id&&r.revision>saved.original.revision))origin=null;
        if(!origin)notices.push('Die Ausgangsversion hat sich geändert. Der Inhalt wird als neuer Dateientwurf übernommen.');}
      if(chat){try{const detail=await api('/conversations/'+chat.conversation_id);const message=detail.messages.find((m:any)=>m.id===chat.message_id&&m.role==='assistant'&&m.revision===chat.revision);
          if(!message)throw Error('changed');}catch{chat=null;notices.push('Die Chatantwort konnte nicht unverändert bestätigt werden. Wähle sie erneut aus, um die Herkunft zu binden.');}}
      if(stale.size)notices.push('Quellen wurden geändert oder fehlen. Die betroffenen Bindungen wurden entfernt; wähle Quellen erneut und prüfe den Inhalt.');
      setTemplateId(fileTemplates.some(t=>t.id===saved.templateId&&t.kind===saved.kind)?saved.templateId:'');setPendingTemplate(null);setTemplateNotice('');
      setOriginal(origin);setChatSource(chat);setKind(saved.kind);setTitle(saved.title);setGoal(saved.goal);setSlideCount(saved.slideCount);
      setSections(saved.sections.map((section:Section)=>({...section,images:(section.images||[]).map(image=>({...image,sourceId:stale.has(image.sourceId)?'':image.sourceId}))})));
      setBoundIds(saved.boundIds.filter((id:string)=>!stale.has(id)));setPdfExport(saved.pdfExport);setPdfMode(saved.pdfMode);setSlides(saved.slides);
      setPages(saved.pages.map((page:Page)=>({...page,sourceId:stale.has(page.sourceId)?'':page.sourceId})));setTiles(saved.tiles.map((tile:Tile)=>({...tile,sourceId:stale.has(tile.sourceId)?'':tile.sourceId})));
      setColumns(saved.columns);setWidth(saved.width);setHeight(saved.height);setFormat(saved.format);
      setResumeNeedsReview(notices.length>0);setDraftToken(null);setDraftInfo(null);setMode('manual');setContentOpen(true);setEditing(true);
      setResumeNotice([...notices,'Inhalt und Ziel wiederhergestellt. Modellbelege und Freigaben werden nicht wiederverwendet; du kannst den Inhalt manuell prüfen oder erneut lokal entwerfen.'].join(' '));
    }catch{setError('Der gespeicherte Entwurf konnte nicht geöffnet werden. Du kannst ihn verwerfen und neu beginnen.');}finally{setBusy(false)}
  }
  function start(row:Row|null=null){
    setTemplateId('');setPendingTemplate(null);setTemplateNotice('');
    setResumeNeedsReview(false);setResumeNotice('');setMode(row?'manual':'model');setContentOpen(!!row);
    setError('');setChatSource(null);setDraftToken(null);setDraftInfo(null);setGoal('');setOriginal(row);setTitle(row?.title||'');setKind(row?.kind||'docx');
    const plan=row?.spec.plan;
    setPdfExport(plan?.pdf_export||false);setPdfMode(plan?.sections?.length?'text':'pages');
    setSections(plan?.sections?.map((s:any)=>({heading:s.heading,paragraphs:s.paragraphs.join('\n\n'),table:s.table||[],images:(s.images||[]).map((image:any)=>({sourceId:row!.spec.sources[image.source].id,caption:image.caption||'',width:image.width_inches}))}))||[{heading:'Ergebnis',paragraphs:'',table:[]}]);
    setBoundIds(row?.spec.sources?.map((s:any)=>s.id)||[]);
    setSlides(plan?.slides?.map((s:any)=>({title:s.title,bullets:s.bullets.join('\n'),notes:s.notes||''}))||[{title:'',bullets:'',notes:''}]);
    const bound=row?.spec.sources||[];
    setPages(plan?.pages?.map((p:any)=>({sourceId:bound[p.source].id,page:p.page,rotation:p.rotation,splitAfter:(plan.split_after||[]).includes(plan.pages.indexOf(p)+1)}))||[]);
    setTiles(plan?.tiles?.map((t:any)=>({sourceId:bound[t.source].id,crop:t.crop.map((v:number)=>v*100),caption:t.caption||''}))||[]);
    setColumns(plan?.columns||1);setWidth(plan?.tile_width||1024);setHeight(plan?.tile_height||768);
    setFormat(plan?.format||'png');setSlideCount(plan?.slides?.length||3);setEditing(true);
  }
  function applyTemplate(template:FileTemplate){
    if(busy||template.kind!==kind)return;
    if(template.kind==='docx')setSections(template.headings.map(heading=>({heading,paragraphs:'',table:[]})));
    else {setSlides(template.headings.map(title=>({title,bullets:'',notes:''})));setSlideCount(template.headings.length);}
    if(!title.trim())setTitle(template.name);
    setDraftToken(null);setDraftInfo(null);setPendingTemplate(null);setMode('manual');setContentOpen(true);
    setTemplateNotice('Gliederung „'+template.name+'“ eingesetzt. Die Inhalte sind leer; ergänze belegte Angaben oder entwirf mit dem lokalen Modell.');
  }
  function requestTemplate(){
    const template=fileTemplates.find(t=>t.id===templateId&&t.kind===kind);if(!template||busy)return;
    const content=kind==='docx'?sections.some(section=>section.paragraphs.trim()||section.table.length||(section.images||[]).length||section.heading!=='Ergebnis'):
      slides.some(slide=>slide.title.trim()||slide.bullets.trim()||slide.notes.trim());
    if(content||original||chatSource||draftToken)setPendingTemplate(template);else applyTemplate(template);
  }
  function addTemplateGoal(){
    const template=fileTemplates.find(t=>t.id===templateId&&t.kind===kind);if(!template||busy)return;
    const instruction=template.instruction+' Verwende nur belegte Angaben aus dem Auftrag und den ausdrücklich gewählten Quellen. Erfinde keine Namen, Zahlen, Termine, Entscheidungen oder Fortschritte. Kennzeichne fehlende Angaben als offen.';
    if(goal.includes(instruction)){setTemplateNotice('Das Vorlagenziel steht bereits im KI-Auftrag.');setMode('model');return;}
    const next=[goal.trim(),instruction].filter(Boolean).join('\n\n');
    if(next.length>4000){setError('Der KI-Auftrag mit Vorlagenziel wäre länger als 4000 Zeichen. Kürze deinen Auftrag vor dem Übernehmen.');return;}
    setGoal(next);setMode('model');if(template.kind==='pptx')setSlideCount(template.headings.length);
    setTemplateNotice('Vorlagenziel ergänzt. Es wird beim nächsten „Lokal entwerfen“ als Teil deines KI-Auftrags verwendet. Bestehender Inhalt bleibt bis dahin erhalten.');
  }
  function move<T>(list:T[],index:number,direction:number):T[]{
    const next=[...list],other=index+direction;if(other<0||other>=list.length)return next;
    [next[index],next[other]]=[next[other],next[index]];return next;
  }
  async function save(event:FormEvent){
    event.preventDefault();if(busy||resumeNeedsReview)return;setBusy(true);setError('');
    try{
      const sourceIds=Array.from(new Set([...(draftToken?boundIds:[]),...(kind==='pdf'&&pdfMode==='pages'?pages.map(p=>p.sourceId):kind==='image'?tiles.map(t=>t.sourceId):(kind==='docx'||kind==='pdf')?[...boundIds,...sections.flatMap(s=>(s.images||[]).map(image=>image.sourceId))]:boundIds)]));
      if(sourceIds.some(id=>!id||!sources.find(s=>s.id===id)))throw Error('Bitte für jede Seite bzw. jedes Bild eine Quelldatei auswählen.');
      const bindings=sourceIds.map(id=>{const s=sources.find(s=>s.id===id)!;return{id:s.id,revision:s.revision,sha256:s.sha256}});
      let plan:any;
      if(kind==='docx'||(kind==='pdf'&&pdfMode==='text')){
        const entries=sections.map(s=>({heading:s.heading,paragraphs:s.paragraphs.split(/\n\s*\n/).map(p=>p.trim()).filter(Boolean),table:s.table,images:(s.images||[]).map(image=>({source:sourceIds.indexOf(image.sourceId),caption:image.caption,width_inches:image.width}))}));
        if(entries.some(s=>s.paragraphs.length>30||s.paragraphs.some(p=>p.length>4000)))throw Error('Je Abschnitt maximal 30 Absätze mit jeweils 4000 Zeichen verwenden.');
        plan={kind,title,sections:entries,...(kind==='docx'?{pdf_export:pdfExport}:{})};
      }
      else if(kind==='pptx'){
        const entries=slides.map(s=>({title:s.title,notes:s.notes,bullets:s.bullets.split('\n').map(v=>v.trim()).filter(Boolean)}));
        if(entries.some(s=>!s.bullets.length||s.bullets.length>5||s.bullets.some(v=>v.length>140)))throw Error('Je Folie bitte ein bis fünf Stichpunkte mit maximal 140 Zeichen eingeben.');
        plan={kind,title,slides:entries};
      }else if(kind==='pdf'){
        if(!pages.length)throw Error('Bitte mindestens eine Ausgabeseite hinzufügen.');
        plan={kind,title,pages:pages.map(p=>({source:sourceIds.indexOf(p.sourceId),page:p.page,rotation:p.rotation})),split_after:pages.flatMap((p,i)=>p.splitAfter&&i<pages.length-1?[i+1]:[])};
      }else{
        if(!tiles.length)throw Error('Bitte mindestens ein Bild hinzufügen.');
        plan={kind:'image',title,tiles:tiles.map(t=>({source:sourceIds.indexOf(t.sourceId),crop:t.crop.map(v=>v/100),caption:t.caption||''})),columns,tile_width:width,tile_height:height,format};
      }
      const body={request_id:crypto.randomUUID(),spec:{plan,sources:bindings},...(draftToken?{draft_token:draftToken}:{}),...(chatSource?{chat_source:chatSource}:{}),...(original?{expected_revision:original.revision}:{})};
      await api(original?prefix+'/'+original.artifact_id+'/versions':prefix,'POST',body);
      setRows(await api(prefix));setEditing(false);discardDraft();
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function generate(){
    if(busy||!goal.trim())return;setBusy(true);setError('');
    try{
      const bindings=boundIds.map(id=>{const s=sources.find(s=>s.id===id);if(!s)throw Error('Ausgewählte Quelle fehlt');return{id:s.id,revision:s.revision,sha256:s.sha256}});
      const draft=await api('/projects/'+project.id+'/artifact-drafts','POST',{goal,kind,pdf_mode:kind==='pdf'&&pdfMode==='pages'?'pages':'content',slide_count:slideCount,sources:bindings,...(chatSource?{chat_source:chatSource}:{}),...(original?{base_artifact_id:original.artifact_id,base_revision:original.revision}:{})});
      const plan=draft.spec.plan;setTitle(plan.title);
      if(kind==='docx'||(kind==='pdf'&&pdfMode==='text'))setSections(plan.sections.map((s:any)=>({heading:s.heading,paragraphs:s.paragraphs.join('\n\n'),table:s.table||[]})));
      else if(kind==='pptx')setSlides(plan.slides.map((s:any)=>({title:s.title,bullets:s.bullets.join('\n'),notes:s.notes||''})));
      else if(kind==='pdf')setPages(plan.pages.map((p:any)=>({sourceId:draft.spec.sources[p.source].id,page:p.page,rotation:p.rotation,splitAfter:(plan.split_after||[]).includes(plan.pages.indexOf(p)+1)})));
      else {setTiles(plan.tiles.map((t:any)=>({sourceId:draft.spec.sources[t.source].id,crop:t.crop.map((v:number)=>v*100),caption:t.caption||''})));setColumns(plan.columns);setWidth(plan.tile_width);setHeight(plan.tile_height);setFormat(plan.format)}
      setDraftToken(draft.draft_token);setDraftInfo(draft);setContentOpen(true);setResumeNeedsReview(false);
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function accept(){
    if(!preview||busy)return;setBusy(true);setError('');
    try{await api(base(preview)+'/accept','POST',{spec_sha256:preview.spec_sha256,output_sha256:preview.output.sha256,reviewed_all_pages:reviewed});setRows(await api(prefix));setPreview(null)}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  return <section className={"setting-card artifacts-panel"+(embedded?" artifacts-embedded":"")}>
    <div className="artifact-panel-heading"><div><span className="artifact-eyebrow">Ergebnisse · Lokal</span><h2>Dateien erstellen und bearbeiten</h2></div><span className="artifact-count">{rows.length} Versionen</span></div>
    {contextLabel&&<p className="artifact-context">Projekt: {contextLabel}</p>}
    {!embedded&&<p>Vom gewünschten Ergebnis zur bearbeitbaren Datei. Word, PowerPoint, PDF und Bilder mit erhaltenen Originalen und geprüfter Vorschau.</p>}
    {!configured&&<p className="hint">Der lokale Dateirunner ist noch nicht eingerichtet. Vorhandene Originale kannst du weiterhin im Bereich Dokumente verwenden.</p>}
    {error&&!editing&&!preview&&<p className="error" role="alert">{error}</p>}
    <button className="primary" disabled={!configured||project.archived} onClick={()=>start()}>Neue Datei erstellen</button>
    {seed&&(!seed.project_id||seed.project_id===project.id)&&<button disabled={!configured||project.archived} onClick={()=>{start();setMode('manual');setContentOpen(true);setTitle('Antwort als Dokument');setSections([{heading:'Antwort',paragraphs:seed.content.match(/[\s\S]{1,4000}/g)?.join('\n\n')||seed.content,table:[]}]);setChatSource({conversation_id:seed.conversation_id,message_id:seed.message_id,revision:seed.revision})}}>Chatantwort als Word übernehmen</button>}
    {savedDraft&&!editing&&<div className="artifact-context" role="status"><b>Gespeicherter Dateientwurf</b><p>{savedDraft.title||savedDraft.goal||'Noch ohne Titel'} · nur in dieser Browsersitzung</p><button disabled={busy||project.archived} onClick={()=>void resumeDraft()}>Entwurf fortsetzen</button><button disabled={busy} onClick={discardDraft}>Entwurf verwerfen</button></div>}
    {!rows.length&&<p className="muted">Noch keine erzeugten Dateien in diesem Projektraum.</p>}
    {rows.map(row=><article key={row.artifact_id+'-'+row.revision} className="citation" tabIndex={-1} ref={highlighted===row.artifact_id+'-'+row.revision?targetRow:undefined} data-search-target={highlighted===row.artifact_id+'-'+row.revision||undefined}>
      {highlighted===row.artifact_id+'-'+row.revision&&<small className="status-chip">Suchergebnis</small>}<b>{row.title} · Version {row.revision}</b>{row.chat&&<p className="hint">Aus Chatantwort · Revision {row.chat.revision} · lokal gespeichert</p>}{row.draft&&<details><summary>Modell und verwendete Quellen</summary><p>{row.draft.provider.model} · lokales Modell · {row.draft.user_edited?'Entwurf anschließend bearbeitet':'Entwurf übernommen'}</p>{row.draft.inherited_from&&<p>Ursprünglicher Modellentwurf: Version {row.draft.inherited_from.revision} · diese Folgeversion wurde manuell bearbeitet.</p>}{row.draft.citations.map((c:any,i:number)=><p key={i}>{c.reference} · Revision {c.revision}</p>)}{row.draft.web_research&&<><p>Verwendete Websuchauszüge · lokal verarbeitet</p>{row.draft.web_research.citations.map((c:any,i:number)=><p key={'web-'+i}>{c.reference}</p>)}</>}<p className="hint">Quellenbelege zeigen verwendete Auszüge. Die sachliche Richtigkeit wurde nicht automatisch bestätigt.</p></details>}<p>{status[row.status]||row.status} · {row.kind==='image'?'Bild':row.kind.toUpperCase()} · Lokal</p>
      {row.error&&<p className="error">{row.error}</p>}
      {['needs_review','published'].includes(row.status)&&<button onClick={()=>{setError('');setReviewed(false);setPreview(row)}}>Vorschau öffnen</button>}
      {row.status==='published'&&<><a href={'/api'+base(row)+'/download'} download>{row.output?.parts?.length?'Alle PDF-Teile als ZIP herunterladen':'Datei herunterladen'}</a>{row.output?.parts?.map((part:any,i:number)=><a key={part.filename} href={'/api'+base(row)+'/download?part='+(i+1)} download>PDF-Teil {i+1} herunterladen · {part.pages} Seiten</a>)}{row.output?.pdf_export&&<a href={'/api'+base(row)+'/download?pdf=true'} download>Zusätzliches PDF herunterladen</a>}</>}
      {configured&&!project.archived&&row.revision===Math.max(...rows.filter(r=>r.artifact_id===row.artifact_id).map(r=>r.revision))&&<button onClick={()=>start(row)}>Neue Version bearbeiten</button>}
      {['queued','rendering','needs_review','failed'].includes(row.status)&&<button disabled={busy} onClick={async()=>{setBusy(true);try{await api(base(row)+'/cancel','POST');setRows(await api(prefix))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>Diese Version abbrechen</button>}
    </article>)}
    {editing&&<div className="modal"><div className="artifact-editor" role="dialog" aria-modal="true" aria-label="Datei erstellen">
      <h2>{original?'Neue Dateiversion':'Neue Datei'}</h2>
      <p>1. Inhalt entwerfen · 2. Datei erstellen · 3. Vorschau prüfen und freigeben</p>
      <div className="artifact-mode" role="group" aria-label="Arbeitsweise"><button type="button" aria-pressed={mode==='model'} disabled={busy} onClick={()=>setMode('model')}>Mit KI entwerfen</button><button type="button" aria-pressed={mode==='manual'} disabled={busy} onClick={()=>{setMode('manual');setContentOpen(true)}}>Inhalt selbst eingeben</button></div>
      <p className="hint">Beim Wechsel bleiben dein Ziel, Quellen und bearbeiteter Inhalt erhalten.</p>
      {original&&<p className="artifact-context">Grundlage: {original.title} · Version {original.revision}. Es entsteht eine neue Version.</p>}
      {chatSource&&<p className="artifact-context">Grundlage: ausgewählte Chatantwort · Revision {chatSource.revision}. Die Herkunft bleibt mit der Datei verbunden.</p>}
      {error&&<p className="error" role="alert">{error}</p>}
      {resumeNotice&&<p className="artifact-context" role="status">{resumeNotice}</p>}
      {resumeNeedsReview&&<div className="artifact-context"><p>Vor dem Erstellen musst du mit aktuell ausgewählten Quellen neu entwerfen oder den erhaltenen Text ausdrücklich als manuelle Kopie verwenden.</p><button type="button" disabled={busy} onClick={()=>{setOriginal(null);setChatSource(null);setResumeNeedsReview(false);setMode('manual');setContentOpen(true)}}>Als manuelle Kopie ohne frühere Herkunft verwenden</button></div>}
      <form onSubmit={save}>
        <fieldset className="artifact-choice-field" disabled={busy}><legend>Dateiformat</legend><div className="artifact-format-options" role="radiogroup" aria-label="Dateiformat">{fileFormats.map(option=><label key={option.id} className={'artifact-format-card'+(kind===option.id?' is-selected':'')}><input type="radio" name={'artifact-format-'+project.id} aria-label={option.label} value={option.id} checked={kind===option.id} onChange={()=>{setKind(option.id);setTemplateId('');setPendingTemplate(null);setTemplateNotice('');setDraftToken(null);setDraftInfo(null);setError('')}}/><option.icon size={20}/><strong>{option.short}</strong><small>{option.description}</small>{kind===option.id&&<Check className="artifact-choice-check" size={13}/>}</label>)}</div></fieldset>
        {(kind==='docx'||kind==='pptx')&&<div className="artifact-template">
          <fieldset className="artifact-choice-field" disabled={busy}><legend>Startpunkt wählen</legend><div className="artifact-template-options" role="radiogroup" aria-label="Vorlage"><label className={'artifact-template-card'+(!templateId?' is-selected':'')}><input type="radio" name={'artifact-template-'+project.id} aria-label="Ohne Vorlage" value="" checked={!templateId} onChange={()=>{setTemplateId('');setPendingTemplate(null);setTemplateNotice('')}}/><span><strong>Ohne Vorlage</strong><small>Eigene Struktur und Inhalte</small></span>{!templateId&&<Check size={14}/>}</label>{fileTemplates.filter(t=>t.kind===kind).map(template=><label key={template.id} className={'artifact-template-card'+(templateId===template.id?' is-selected':'')}><input type="radio" name={'artifact-template-'+project.id} aria-label={template.name} value={template.id} checked={templateId===template.id} onChange={()=>{setTemplateId(template.id);setPendingTemplate(null);setTemplateNotice('')}}/><span><strong>{template.name}</strong><small>{template.headings.length} {kind==='pptx'?'Folien':'Abschnitte'} · leere Gliederung</small></span>{templateId===template.id&&<Check size={14}/>}</label>)}</div></fieldset>
          <p className="hint">Vorlagen liefern eine leere Gliederung. Sie ergänzen keine Fakten und ändern weder Quellen noch Freigaben.</p>
          <button type="button" disabled={busy||!templateId} onClick={requestTemplate}>Gliederung einsetzen</button><button type="button" disabled={busy||!templateId} onClick={addTemplateGoal}>Vorlagenziel in KI-Auftrag übernehmen</button>
          {pendingTemplate&&<div className="artifact-template-confirm" role="group" aria-label="Vorlagenwechsel bestätigen"><p>Die Gliederung „{pendingTemplate.name}“ ersetzt die Abschnitte bzw. Folien dieses Entwurfs einschließlich Text, Tabellen und Bildern. Gespeicherte Versionen bleiben erhalten. Dein Dateititel, KI-Auftrag und ausgewählte Quellen bleiben bestehen.</p><button type="button" disabled={busy} onClick={()=>applyTemplate(pendingTemplate)}>Entwurfsinhalt durch leere Gliederung ersetzen</button><button type="button" disabled={busy} onClick={()=>setPendingTemplate(null)}>Inhalt behalten</button></div>}
          {templateNotice&&<p role="status" className="hint">{templateNotice}</p>}
        </div>}
        {<details className="artifact-draft" open={mode==='model'}><summary onClick={e=>{e.preventDefault();setMode('model')}}>Mit dem lokalen Modell entwerfen</summary>
          <p className="hint">Beschreibe das Ergebnis. Es werden nur die ausdrücklich ausgewählten Projektquellen verwendet. Textentwürfe nutzen bis zu vier Quellen mit Auszügen; Seiten- und Bildoperationen verwenden die ausgewählten Originale. Danach Text, Fakten und Quellen selbst prüfen. Es entsteht noch keine Datei.</p>
          <label>Gewünschtes Ergebnis<textarea aria-label="Gewünschtes Ergebnis" maxLength={4000} rows={3} value={goal} onChange={e=>setGoal(e.target.value)}/></label>
          {kind==='pptx'&&<label>Gewünschte Folienanzahl<input type="number" min={1} max={30} value={slideCount} onChange={e=>setSlideCount(Number(e.target.value))}/></label>}
          <button type="button" disabled={busy||!goal.trim()||boundIds.length>((kind==='image'||(kind==='pdf'&&pdfMode==='pages'))?20:4)||(!!chatSource&&(kind==='image'||(kind==='pdf'&&pdfMode==='pages')))} onClick={()=>void generate()}>{busy?'Lokaler Entwurf läuft…':'Lokal entwerfen'}</button>
          {chatSource&&<p className="hint">Die übernommene Antwort kannst du hier bearbeiten. KI-Folgeänderungen sind nach Erstellung der ersten Dateiversion verfügbar.</p>}
        </details>}
        {kind==='pdf'&&<label>PDF erstellen aus<select aria-label="PDF erstellen aus" value={pdfMode} onChange={e=>{setPdfMode(e.target.value);setDraftToken(null);setDraftInfo(null)}}><option value="pages">Seiten vorhandener PDF-Dateien</option><option value="text">Text, Tabellen und Bilder</option></select></label>}
        {draftInfo&&<p className="artifact-feedback" role="status">Lokaler Entwurf bereit · {draftInfo.provider.model}. Inhalt bearbeiten, anschließend Datei und Vorschau erstellen.</p>}
        {sources.length>0&&<details className="artifact-source-selection"><summary>Gebundene Quelldateien</summary><p className="hint">Nur ausgewählte Quellen werden an das lokale Modell übergeben. Textentwürfe nutzen bis zu vier Quellen mit Auszügen. Jede Auswahl wird an Revision und Hash gebunden.</p>{(kind==='image'?images:kind==='pdf'&&pdfMode==='pages'?pdfs:sources).map(source=><label key={source.id}><input type="checkbox" checked={boundIds.includes(source.id)} onChange={e=>{setBoundIds(e.target.checked?[...boundIds,source.id]:boundIds.filter(id=>id!==source.id));setDraftToken(null);setDraftInfo(null)}}/>{source.name}</label>)}</details>}
        <details className="artifact-content" open={contentOpen} onToggle={e=>setContentOpen(e.currentTarget.open)}><summary>Inhalt bearbeiten{original?' · neue Version':''}</summary>
        <label>Dateititel<input required value={title} maxLength={160} onChange={e=>setTitle(e.target.value)}/></label>
        {(kind==='docx'||(kind==='pdf'&&pdfMode==='text'))&&<>{kind==='docx'&&<label><input type="checkbox" checked={pdfExport} onChange={e=>setPdfExport(e.target.checked)}/> Zusätzlich als PDF zum Download bereitstellen</label>}{sections.map((section,index)=><fieldset key={index}><legend>Abschnitt {index+1}</legend>
          <label>Abschnittsüberschrift<input required maxLength={160} value={section.heading} onChange={e=>setSections(sections.map((s,i)=>i===index?{...s,heading:e.target.value}:s))}/></label>
          <label>Dokumenttext<textarea aria-label="Dokumenttext" maxLength={30000} rows={8} value={section.paragraphs} onChange={e=>setSections(sections.map((s,i)=>i===index?{...s,paragraphs:e.target.value}:s))}/></label>
          <details className="artifact-advanced" open={section.table.length>0||(section.images||[]).length>0}><summary>Tabellen, Bilder und Abschnittsoptionen</summary>
          {section.table.map((row,r)=><fieldset key={r}><legend>Tabellenzeile {r+1}</legend>{row.map((cell,col)=><label key={col}>Spalte {col+1}<input required maxLength={160} value={cell} onChange={e=>setSections(sections.map((s,i)=>i===index?{...s,table:s.table.map((cells,j)=>j===r?cells.map((value,c)=>c===col?e.target.value:value):cells)}:s))}/></label>)}<button type="button" onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,table:s.table.filter((_,j)=>j!==r)}:s))}>Tabellenzeile entfernen</button></fieldset>)}
          {!section.table.length?<button type="button" onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,table:[['',''],['','']]}:s))}>Tabelle hinzufügen</button>:<><button type="button" disabled={section.table.length>=30} onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,table:[...s.table,s.table[0].map(()=>'')]}:s))}>Tabellenzeile hinzufügen</button><button type="button" disabled={section.table[0].length>=6} onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,table:s.table.map(row=>[...row,''])}:s))}>Tabellenspalte hinzufügen</button><button type="button" onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,table:[]}:s))}>Tabelle entfernen</button></>}
          {(section.images||[]).map((picture,n)=><fieldset key={n}><legend>Dokumentbild {n+1}</legend><label>Bild im Dokument<select aria-label="Bild im Dokument" required value={picture.sourceId} onChange={e=>setSections(sections.map((s,i)=>i===index?{...s,images:(s.images||[]).map((image,j)=>j===n?{...image,sourceId:e.target.value}:image)}:s))}>{images.map(image=><option key={image.id} value={image.id}>{image.name}</option>)}<option value="">Bitte auswählen</option></select></label><label>Bildunterschrift<input maxLength={160} value={picture.caption} onChange={e=>setSections(sections.map((s,i)=>i===index?{...s,images:(s.images||[]).map((image,j)=>j===n?{...image,caption:e.target.value}:image)}:s))}/></label><label>Bildbreite (Zoll)<input type="number" min={0.5} max={6.5} step={0.1} value={picture.width} onChange={e=>setSections(sections.map((s,i)=>i===index?{...s,images:(s.images||[]).map((image,j)=>j===n?{...image,width:Number(e.target.value)}:image)}:s))}/></label><button type="button" onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,images:(s.images||[]).filter((_,j)=>j!==n)}:s))}>Dokumentbild entfernen</button></fieldset>)}
          <button type="button" disabled={!images.length||(section.images||[]).length>=4||sections.reduce((count,s)=>count+(s.images||[]).length,0)>=12} onClick={()=>setSections(sections.map((s,i)=>i===index?{...s,images:[...(s.images||[]),{sourceId:images[0].id,caption:'',width:5.5}]}:s))}>Bild in Abschnitt einfügen</button>
          <button type="button" disabled={index===0} onClick={()=>setSections(move(sections,index,-1))}>Abschnitt nach oben</button><button type="button" disabled={sections.length===1} onClick={()=>setSections(sections.filter((_,i)=>i!==index))}>Abschnitt entfernen</button></details>
        </fieldset>)}<button type="button" disabled={sections.length>=30} onClick={()=>setSections([...sections,{heading:'',paragraphs:'',table:[]}])}>Abschnitt hinzufügen</button><p className="hint">Eine Leerzeile trennt die Absätze. Text und Tabellen bleiben editierbar.</p></>}
        {kind==='pptx'&&<><p>{slides.length} Folie{slides.length===1?'':'n'} · Die Ausgabe enthält genau diese Folien.</p>{slides.map((slide,index)=><fieldset key={index}><legend>Folie {index+1}</legend>
          <label>Folientitel<input required maxLength={160} value={slide.title} onChange={e=>setSlides(slides.map((s,i)=>i===index?{...s,title:e.target.value}:s))}/></label>
          <label>Stichpunkte<textarea aria-label="Stichpunkte" required rows={5} value={slide.bullets} onChange={e=>setSlides(slides.map((s,i)=>i===index?{...s,bullets:e.target.value}:s))}/></label><p className="hint">Ein Stichpunkt je Zeile, maximal fünf.</p>
          <details className="artifact-advanced"><summary>Notizen und Folienreihenfolge</summary><label>Sprechernotizen<textarea aria-label="Sprechernotizen" maxLength={4000} value={slide.notes} onChange={e=>setSlides(slides.map((s,i)=>i===index?{...s,notes:e.target.value}:s))}/></label>
          <button type="button" disabled={index===0} onClick={()=>setSlides(move(slides,index,-1))}>Folie nach oben</button><button type="button" disabled={index===slides.length-1} onClick={()=>setSlides(move(slides,index,1))}>Folie nach unten</button><button type="button" disabled={slides.length===1} onClick={()=>setSlides(slides.filter((_,i)=>i!==index))}>Folie entfernen</button></details>
        </fieldset>)}<button type="button" disabled={slides.length>=30} onClick={()=>setSlides([...slides,{title:'',bullets:'',notes:''}])}>Folie hinzufügen</button></>}
        {kind==='pdf'&&pdfMode==='pages'&&<><p>Füge Ausgabeseiten in ihrer Reihenfolge hinzu. Für mehrere PDF-Dateien markiere, nach welcher Ausgabeseite ein neuer Teil beginnen soll. Alle Teile werden einzeln und als ZIP zum Download angeboten.</p><button type="button" disabled={pages.length<2||pages.length>20} onClick={()=>setPages(pages.map((p,i)=>({...p,splitAfter:i<pages.length-1})))}>Jede Ausgabeseite als eigene PDF</button><button type="button" onClick={()=>setPages(pages.map(p=>({...p,splitAfter:false})))}>Eine zusammenhängende PDF</button>{!pdfs.length&&<p>Bitte zuerst eine PDF unter Dokumente hinzufügen.</p>}{pages.map((page,index)=><fieldset key={index}><legend>Ausgabeseite {index+1}</legend>
          <label>PDF-Quelldatei<select aria-label="PDF-Quelldatei" required value={page.sourceId} onChange={e=>setPages(pages.map((p,i)=>i===index?{...p,sourceId:e.target.value}:p))}><option value="">Bitte auswählen</option>{pdfs.map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</select></label>
          <label>Seite im Original<input type="number" required min={1} max={1000} value={page.page} onChange={e=>setPages(pages.map((p,i)=>i===index?{...p,page:Number(e.target.value)}:p))}/></label>
          <label>Im Uhrzeigersinn drehen<select aria-label="Im Uhrzeigersinn drehen" value={page.rotation} onChange={e=>setPages(pages.map((p,i)=>i===index?{...p,rotation:Number(e.target.value)}:p))}>{[0,90,180,270].map(v=><option key={v} value={v}>{v}°</option>)}</select></label>
          <button type="button" disabled={index===0} onClick={()=>setPages(move(pages,index,-1))}>Seite nach oben</button><button type="button" disabled={index===pages.length-1} onClick={()=>setPages(move(pages,index,1))}>Seite nach unten</button><button type="button" onClick={()=>setPages(pages.filter((_,i)=>i!==index))}>Seite entfernen</button>
        <label><input type="checkbox" disabled={index===pages.length-1} checked={!!page.splitAfter&&index<pages.length-1} onChange={e=>setPages(pages.map((p,i)=>i===index?{...p,splitAfter:e.target.checked}:p))}/> Nach Ausgabeseite {index+1} einen neuen PDF-Teil beginnen</label></fieldset>)}<button type="button" disabled={!pdfs.length||pages.length>=100} onClick={()=>setPages([...pages,{sourceId:pdfs[0].id,page:1,rotation:0}])}>Ausgabeseite hinzufügen</button><p className="hint">Signierte und verschlüsselte PDF werden hier nicht verändert. Die neue PDF übernimmt Seiteninhalte; Kommentare, Formularfelder und Links werden entfernt.</p></>}
        {kind==='image'&&<><p>Wähle echte hochgeladene Bilder. Zuschnitte werden in Prozent der Bildbreite bzw. -höhe angegeben.</p>{!images.length&&<p>Bitte zuerst ein Bild unter Dokumente hinzufügen.</p>}{tiles.map((tile,index)=><fieldset key={index}><legend>Bild {index+1}</legend>
          <label>Bildquelle<select aria-label="Bildquelle" required value={tile.sourceId} onChange={e=>setTiles(tiles.map((t,i)=>i===index?{...t,sourceId:e.target.value}:t))}><option value="">Bitte auswählen</option>{images.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <label>Bildbeschriftung<input aria-label="Bildbeschriftung" maxLength={140} value={tile.caption||''} onChange={e=>setTiles(tiles.map((t,i)=>i===index?{...t,caption:e.target.value}:t))}/></label>
          <details className="artifact-advanced" open={!!draftInfo}><summary>Zuschnitt in Prozent</summary>{['Linker Rand (%)','Oberer Rand (%)','Rechter Rand (%)','Unterer Rand (%)'].map((label,part)=><label key={part}>{label}<input type="number" required min={0} max={100} step={0.1} value={tile.crop[part]} onChange={e=>setTiles(tiles.map((t,i)=>i===index?{...t,crop:t.crop.map((v,j)=>j===part?Number(e.target.value):v)}:t))}/></label>)}</details>
          <button type="button" disabled={index===0} onClick={()=>setTiles(move(tiles,index,-1))}>Bild nach oben</button><button type="button" onClick={()=>setTiles(tiles.filter((_,i)=>i!==index))}>Bild entfernen</button>
        </fieldset>)}<button type="button" disabled={!images.length||tiles.length>=12} onClick={()=>setTiles([...tiles,{sourceId:images[0].id,crop:[0,0,100,100]}])}>Bild hinzufügen</button>
          <details className="artifact-advanced"><summary>Collagegröße und Bildformat</summary><label>Spalten in der Collage<input type="number" min={1} max={4} value={columns} onChange={e=>setColumns(Number(e.target.value))}/></label>
          <label>Breite je Bild (Pixel)<input type="number" min={128} max={2048} value={width} onChange={e=>setWidth(Number(e.target.value))}/></label>
          <label>Höhe je Bild (Pixel)<input type="number" min={128} max={2048} value={height} onChange={e=>setHeight(Number(e.target.value))}/></label>
          <label>Bildformat<select aria-label="Bildformat" value={format} onChange={e=>setFormat(e.target.value)}><option value="png">PNG</option><option value="jpeg">JPEG</option></select></label></details>
        </>}
        </details>
        <p className="hint">Neue Versionen ersetzen keine älteren Dateien. Quellen anderer Projekte werden nicht einbezogen.</p>
        <button className="primary" disabled={busy||resumeNeedsReview||(mode==='model'&&!draftInfo&&!original&&!chatSource)}>Datei und Vorschau erstellen</button>
        {mode==='model'&&!draftInfo&&!original&&!chatSource&&<p className="hint">Erstelle zuerst einen lokalen Entwurf oder wähle „Inhalt selbst eingeben“.</p>}
      </form><button disabled={busy} onClick={()=>setEditing(false)}>Abbrechen</button>
    </div></div>}
    {preview&&<div className="modal"><div role="dialog" aria-modal="true" aria-label="Dateivorschau">
      <h2>{preview.title} · Version {preview.revision}</h2>
      {error&&<p className="error" role="alert">{error}</p>}
      <p>{preview.output?.previews.length||0} Vorschauseiten · Lokal · {status[preview.status]}</p>
      {preview.output?.previews.map((page:any)=><figure key={page.page}><img className="artifact-preview" src={'/api'+base(preview)+'/preview/'+page.page} alt={'Vorschauseite '+page.page}/><figcaption>Ausgabeseite {page.page}{preview.output?.parts?.length?' · PDF-Teil '+(preview.output.parts.findIndex((p:any)=>page.page>=p.first_page&&page.page<p.first_page+p.pages)+1):''}</figcaption></figure>)}
      {preview.status==='needs_review'&&<><label><input type="checkbox" checked={reviewed} onChange={e=>setReviewed(e.target.checked)}/> Ich habe alle Vorschauseiten geprüft.</label><button className="primary" disabled={!reviewed||busy} onClick={()=>void accept()}>Diese Dateiversion freigeben</button></>}
      {preview.status==='published'&&<><a href={'/api'+base(preview)+'/download'} download>{preview.output?.parts?.length?'Alle PDF-Teile als ZIP herunterladen':'Datei herunterladen'}</a>{preview.output?.parts?.map((part:any,i:number)=><a key={part.filename} href={'/api'+base(preview)+'/download?part='+(i+1)} download>PDF-Teil {i+1} herunterladen · {part.pages} Seiten</a>)}{preview.output?.pdf_export&&<a href={'/api'+base(preview)+'/download?pdf=true'} download>Zusätzliches PDF herunterladen</a>}</>}
      <button disabled={busy} onClick={()=>{setPreview(null);setError('')}}>Schließen</button>
    </div></div>}
  </section>;
}
