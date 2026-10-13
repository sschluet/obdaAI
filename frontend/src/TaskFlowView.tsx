export type TaskFlow={nodes:{id:string;sequence:number;name:string;effect:string;condition:string}[];include_system_reports:boolean;label:string};
export function TaskFlowView({plan}:{plan:TaskFlow}){
 return <div className="task-flow" aria-label="Geprüfter Aufgabenablauf"><ol>{plan.nodes.map(n=><li key={n.id}><span className="flow-number">{n.sequence}</span><div><strong>{n.name}</strong><small>{n.effect==='write'?'Konkrete Schreibfreigabe erforderlich':n.effect==='model'?'Lokales Modell':'Lesend'}{n.condition==='ha_updates_available'?' · nur bei verfügbaren HA-Updates':''}</small></div></li>)}</ol>{plan.include_system_reports&&<p className="hint">Die ausgewählten Berichte sind für diese lokale Auswertung freigegeben. Private Inhalte bleiben in obdaAI.</p>}</div>;
}
