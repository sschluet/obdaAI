'use strict';
const labels={live:'Live geprüft',implemented:'Implementiert',limited:'Begrenzter Teilstand',local:'Lokal geprüft'};
const node=(tag,text,className)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;};
let category='all',query='',selected=0,project;
function renderFeatures(){
 const target=document.querySelector('#feature-groups');target.replaceChildren();let count=0;
 for(const group of project.groups){
  if(category!=='all'&&category!==group.id)continue;
  const features=group.features.filter(f=>(f.title+' '+f.description+' '+group.name).toLocaleLowerCase('de').includes(query));
  if(!features.length)continue;count+=features.length;
  const section=node('section',undefined,'feature-group');const heading=node('div',undefined,'group-heading');heading.append(node('span',group.symbol,'group-symbol'));const copy=node('div');copy.append(node('h3',group.name),node('p',group.intro));heading.append(copy);section.append(heading);
  const grid=node('div',undefined,'feature-grid');for(const f of features){const card=node('article',undefined,'feature-card');card.append(node('span',labels[f.status],'badge '+f.status),node('h4',f.title),node('p',f.description));grid.append(card);}section.append(grid);target.append(section);
 }
 document.querySelector('#feature-count').textContent=count+' Funktionen · '+(category==='all'?'alle Bereiche':project.groups.find(g=>g.id===category).name);
 if(!count)target.append(node('p','Keine passende Funktion gefunden. Probiere einen anderen Suchbegriff.','empty'));
 document.querySelectorAll('#feature-tabs button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.category===category)));
}
function selectCategory(id){category=id;renderFeatures();}
function showScreenshot(index){
 selected=index;const shot=project.screenshots[index];document.querySelector('#gallery-image').src=shot.image;document.querySelector('#gallery-image').alt=shot.title+' – echte Oberfläche mit synthetischen Beispieldaten';document.querySelector('#gallery-title').textContent=shot.title;document.querySelector('#gallery-description').textContent=shot.description;document.querySelector('#gallery-number').textContent=String(index+1).padStart(2,'0')+' / 05';document.querySelector('#gallery-panel').setAttribute('aria-labelledby','gallery-tab-'+index);
 document.querySelectorAll('#gallery-tabs button').forEach((button,i)=>{button.setAttribute('aria-selected',String(i===index));button.tabIndex=i===index?0:-1;});
}
async function init(){
 const response=await fetch('project.json');if(!response.ok)throw Error('Projektinformationen nicht verfügbar');project=await response.json();
 const tabs=document.querySelector('#feature-tabs');for(const group of [{id:'all',name:'Alle Features'},...project.groups]){const b=node('button',group.name);b.dataset.category=group.id;b.type='button';b.setAttribute('aria-pressed',String(group.id==='all'));b.addEventListener('click',()=>selectCategory(group.id));tabs.append(b);}
 document.querySelector('#feature-search').addEventListener('input',e=>{query=e.target.value.trim().toLocaleLowerCase('de');renderFeatures();});
 document.querySelectorAll('a[data-category]').forEach(a=>a.addEventListener('click',()=>{query='';document.querySelector('#feature-search').value='';selectCategory(a.dataset.category);}));
 const gallery=document.querySelector('#gallery-tabs');const names=['Chat','Projekte','Dateien','Aufgaben','Wissen'];project.screenshots.forEach((shot,i)=>{const b=node('button',names[i]);b.type='button';b.id='gallery-tab-'+i;b.setAttribute('role','tab');b.setAttribute('aria-controls','gallery-panel');b.addEventListener('click',()=>showScreenshot(i));b.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?4:(i+(e.key==='ArrowRight'?1:4))%5;showScreenshot(n);gallery.children[n].focus();});gallery.append(b);});showScreenshot(0);
 const dialog=document.querySelector('#image-dialog');document.querySelector('#expand-image').addEventListener('click',()=>{const image=document.querySelector('#dialog-image');image.src=project.screenshots[selected].image;image.alt=project.screenshots[selected].title+' – synthetische Beispieldaten';dialog.showModal();});document.querySelector('#close-image').addEventListener('click',()=>dialog.close());dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});
 const roadmap=document.querySelector('#roadmap-items');project.roadmap.forEach((item,i)=>{const el=node('article',undefined,'roadmap-item');el.append(node('span',String(i+1).padStart(2,'0')));const copy=node('div');copy.append(node('h4',item.title),node('p',item.text));el.append(copy);roadmap.append(el);});
 if(project.development){document.querySelector('#development-status').textContent='Neu lokal geprüft: integrierter Chat-Arbeitsbereich, einfachere Dialoge und gespeicherte Antwortvorgaben · Schema '+project.development.schema+'. Noch keine Serverinstallation dieser Lieferung.';}
 document.querySelector('#updated').textContent='Stand: '+project.updated.split('-').reverse().join('.');document.querySelector('#tests-count').textContent=project.tests;document.querySelector('#app-release').textContent=project.applicationCommit;document.querySelector('#ci-link').href=project.ciUrl;renderFeatures();
 try{const build=await fetch('build.json');if(build.ok){const info=await build.json();document.querySelector('#website-revision').textContent='Website: '+info.revision;}}catch{/* Build metadata is optional for local previews. */}
}
init().catch(()=>{document.querySelector('#feature-count').textContent='Projektinformationen konnten nicht geladen werden. Bitte lade die Seite erneut.';});
