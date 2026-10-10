import {useRef,useState} from 'react';
import type {FormEvent} from 'react';
import {LockKeyhole,ShieldCheck} from 'lucide-react';
import './password.css';

type API=(path:string,method?:string,body?:unknown)=>Promise<any>;
export function PasswordPanel({api,onPasswordChanged}:{api:API;onPasswordChanged?:()=>void}){
 const [current,setCurrent]=useState(''),[next,setNext]=useState(''),[confirmation,setConfirmation]=useState('');
 const [review,setReview]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[changed,setChanged]=useState(false);
 const confirmButton=useRef<HTMLButtonElement>(null),reviewButton=useRef<HTMLButtonElement>(null);
 const valid=!!current&&next.length>=12&&next.length<=256&&next===confirmation&&next!==current;
 function edit(setValue:(value:string)=>void,value:string){setValue(value);setReview(false);setError('')}
 function prepare(event:FormEvent){event.preventDefault();if(!valid||busy||changed)return;setError('');setReview(true);requestAnimationFrame(()=>confirmButton.current?.focus())}
 async function change(){if(!valid||!review||busy||changed)return;setBusy(true);setError('');try{
  const result=await api('/account/password','POST',{current_password:current,new_password:next,confirm_password:confirmation});
  if(result.changed!==true||result.reauthenticate!==true)throw Error('Die Passwortänderung konnte nicht bestätigt werden. Bitte melde dich erneut an.');
  setCurrent('');setNext('');setConfirmation('');setReview(false);setChanged(true);onPasswordChanged?.();
 }catch(e){setReview(false);setError(e instanceof Error?e.message:'Passwort konnte nicht geändert werden. Bitte versuche es erneut.');requestAnimationFrame(()=>reviewButton.current?.focus())}finally{setBusy(false)}}
 return <section className="setting-card password-panel" aria-label="Passwort und Anmeldung">
  <div className="password-heading"><span><LockKeyhole size={22} aria-hidden="true"/></span><div><h2>Passwort ändern</h2><p>Schütze den Zugang zu deinem privaten Arbeitsraum.</p></div></div>
  <p className="hint">Nach der Änderung werden alle angemeldeten Sitzungen beendet – auch auf anderen Geräten. Melde dich anschließend mit deinem neuen Passwort an.</p>
  {changed?<p role="status" className="password-success"><ShieldCheck size={18} aria-hidden="true"/>Passwort geändert. Bitte melde dich mit dem neuen Passwort an.</p>:<form onSubmit={prepare}>
   <label htmlFor="account-current-password">Aktuelles Passwort<input id="account-current-password" name="current_password" type="password" autoComplete="current-password" required maxLength={256} value={current} disabled={busy} readOnly={review} onChange={event=>edit(setCurrent,event.target.value)}/></label>
   <label htmlFor="account-new-password">Neues Passwort<input id="account-new-password" name="new_password" type="password" autoComplete="new-password" required minLength={12} maxLength={256} aria-describedby="account-password-help" value={next} disabled={busy} readOnly={review} onChange={event=>edit(setNext,event.target.value)}/></label>
   <p id="account-password-help" className="hint">Mindestens 12 Zeichen. Verwende ein neues, möglichst langes Passwort.</p>
   <label htmlFor="account-confirm-password">Neues Passwort bestätigen<input id="account-confirm-password" name="confirm_password" type="password" autoComplete="new-password" required minLength={12} maxLength={256} aria-describedby={confirmation&&confirmation!==next?'account-password-mismatch':undefined} aria-invalid={!!confirmation&&confirmation!==next} value={confirmation} disabled={busy} readOnly={review} onChange={event=>edit(setConfirmation,event.target.value)}/></label>
   {confirmation&&confirmation!==next&&<p className="password-validation" id="account-password-mismatch">Die neuen Passwörter stimmen noch nicht überein.</p>}
   {next&&next===current&&<p className="password-validation">Das neue Passwort muss sich vom aktuellen unterscheiden.</p>}
   {error&&<p className="error" role="alert">{error}</p>}
   {review?<div className="password-confirmation" role="group" aria-label="Passwortänderung bestätigen"><strong>Alle Sitzungen jetzt beenden?</strong><p>Dein Passwort wird geändert und du wirst auf allen Geräten abgemeldet. Halte das neue Passwort für die nächste Anmeldung bereit.</p><div className="password-actions"><button type="button" disabled={busy} onClick={()=>{setReview(false);requestAnimationFrame(()=>reviewButton.current?.focus())}}>Zurück</button><button ref={confirmButton} className="primary" type="button" disabled={busy} onClick={()=>void change()}>{busy?'Passwort wird geändert …':'Passwort ändern und neu anmelden'}</button></div></div>:<button ref={reviewButton} className="primary" type="submit" disabled={!valid||busy}>Passwortänderung prüfen</button>}
  </form>}
 </section>;
}
