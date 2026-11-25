/** An explicit read-only check of the same uncertain job; never replay its effects. */
export function reconciliationRequest(conversationId:string,job:{id:string;goal:string}){
 return {path:'/conversations/'+conversationId+'/agent-runs',body:{
  request_id:crypto.randomUUID(),read_only:true,research_allowed:false,reconcile_job_id:job.id,
  // The server binds the full private source goal and affected targets by this ID.
  goal:'Prüfe ausschließlich lesend den tatsächlichen Zustand nach dem unklaren Auftrag. Keine Änderung wiederholen.',
 }};
}
