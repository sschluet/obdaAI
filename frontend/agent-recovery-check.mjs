// Synthetic recovery checks: no model, mailbox or target tool is contacted.
export async function checkAgentChatRecovery({page, base, call, capture}) {
  const chat = await call('/conversations', 'POST', {cloud_allowed: false});
  const detail = await call('/conversations/' + chat.id);
  const goal = 'Welche Mails gab es diese Woche?';
  const job = {id: 'synthetic-recovery-job', status: 'running', goal, summary: '', cancel_requested: false, steps: []};
  let captureProfile;
  let jobs = [job], failedRefresh = false, retryRequests = 0, messageRequests = 0, agentRequests = 0, retryAsAgent = false;
  const detailPath = '**/api/conversations/' + chat.id;
  const jobsPath = '**/api/agent-runs?conversation_id=' + chat.id;
  const retryPath = '**/api/conversations/' + chat.id + '/retry';
  const agentPath = '**/api/conversations/' + chat.id + '/agent-runs';
  const messagePath = '**/api/conversations/' + chat.id + '/messages';
  const routePath = '**/api/conversations/' + chat.id + '/integration-route';
  const response = { ...detail, messages: [{id: 'synthetic-recovery-question', role: 'user', content: goal, label: 'LOCAL_ONLY'}], runs: []};
  await page.route(detailPath, route => {
    if (failedRefresh) {failedRefresh = false; return route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({detail: 'Synthetischer Ladefehler'})});}
    return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(response)});
  });
  await page.route(jobsPath, route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(jobs)}));
  await page.route(retryPath, route => {
    retryRequests++; failedRefresh = retryRequests === 2;
    return route.fulfill({status: 409, contentType: 'application/json', body: JSON.stringify({detail: 'In diesem Gespräch wartet oder läuft bereits ein Agentenauftrag'})});
  });
  await page.route(messagePath, route => {messageRequests++; return route.fulfill({status: 200, contentType: 'text/event-stream', body: 'event: done\ndata: {"status":"succeeded"}\n\n'});});
  await page.route(routePath, route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(retryAsAgent ? {route: 'agent', integration_ids: ['synthetic-mail-target']} : {route: 'chat', integration_ids: []})}));
  await page.route(agentPath, route => {const body = route.request().postDataJSON(); if (body.goal !== goal || body.integration_ids?.[0] !== 'synthetic-mail-target') throw Error('Prepared retry lost goal or current integration routing'); agentRequests++; return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({...job, id: 'synthetic-fresh-mail-job', status: 'observed'})});});
  try {
    await page.goto(base + '/?view=Chat&chat=' + chat.id);
    const edit = page.getByRole('button', {name: 'Nachricht bearbeiten', exact: true});
    const retry = page.getByRole('button', {name: 'Antwort erneut erzeugen', exact: true});
    const send = page.getByRole('button', {name: 'Nachricht senden', exact: true});
    const composer = page.getByRole('textbox', {name: 'Nachricht', exact: true});
    await page.getByRole('region', {name: 'Systemsteuerung', exact: true}).getByText('In Arbeit · ' + goal, {exact: true}).waitFor();
    await composer.fill('Entwurf nach der Mailfrage');
    if (await edit.isEnabled() || await retry.isEnabled() || await send.isEnabled()) throw Error('Active agent permits editing, regeneration or parallel send');
    // Even a newer terminal record must not hide a still active job.
    jobs = [{...job, id: 'synthetic-newer-terminal', status: 'failed', goal: 'Anderer abgeschlossener Auftrag'}, job];
    await page.getByText('Angehalten · Anderer abgeschlossener Auftrag', {exact: true}).waitFor();
    if (await send.isEnabled()) throw Error('Latest terminal record hides an active agent');
    jobs = [{...job, status: 'awaiting_input', summary: 'Synthetische Rückfrage'}];
    await page.getByText('Synthetische Rückfrage', {exact: true}).waitFor();
    await page.waitForFunction(() => !document.querySelector('button[aria-label="Nachricht senden"]').disabled);
    if (await edit.isEnabled() || await retry.isEnabled()) throw Error('Clarification permits editing or regeneration of the active agent turn');
    jobs = [{...job, status: 'failed', summary: 'Synthetischer Planungsfehler'}];
    await page.getByText('Synthetischer Planungsfehler', {exact: true}).waitFor({state: 'attached'});
    if (!await edit.isEnabled() || !await retry.isEnabled() || !await send.isEnabled()) throw Error('Terminal agent leaves the composer blocked');
    // Simulate a concurrent server guard and a failed final reload. Neither may
    // retain the local busy flag or the preparation status indefinitely.
    await retry.click();
    await page.getByRole('alert').filter({hasText: 'In diesem Gespräch wartet oder läuft bereits ein Agentenauftrag'}).waitFor();
    await page.waitForFunction(() => ![...document.querySelectorAll('[role=alert]')].some(element => element.textContent.includes('In diesem Gespräch wartet oder läuft bereits ein Agentenauftrag')));
    await retry.click();
    await page.getByRole('alert').filter({hasText: 'Synthetischer Ladefehler'}).waitFor();
    if (retryRequests !== 2) throw Error('Unexpected retry replay');
    if (await page.getByRole('button', {name: 'Antwort abbrechen', exact: true}).count()) throw Error('Failed retry reload leaves composer busy');
    if (await page.getByText('Neue Antwort wird vorbereitet', {exact: true}).count()) throw Error('Failed retry leaves preparation status');
    if (await composer.inputValue() !== 'Entwurf nach der Mailfrage') throw Error('Failed retry loses draft');
    await send.click();
    await page.waitForFunction(() => !document.querySelector('button[aria-label="Antwort abbrechen"]'));
    if (messageRequests !== 1) throw Error('New question after failed agent/retry cannot be sent');
    await page.getByText('Angehalten · ' + goal, {exact: true}).click();
    await page.getByRole('button', {name: 'Frage erneut vorbereiten', exact: true}).click();
    if (await composer.inputValue() !== goal || agentRequests) throw Error('Preparing failed question loses goal or executes before Send');
    retryAsAgent = true;
    await send.click();
    await page.waitForFunction(() => !document.querySelector('button[aria-label="Antwort abbrechen"]'));
    if (agentRequests !== 1 || messageRequests !== 1) throw Error('Prepared question bypasses fresh integration routing');
    if (capture) {
      captureProfile = await call('/integrations', 'POST', {name: 'Proton Mail · Aurora', kind: 'mcp', url: 'https://mail.example.test/mcp', auth: 'none', protocol: '2026-07-28'});
      captureProfile = await call('/integrations/' + captureProfile.id + '/control', 'PATCH', {expected_revision: captureProfile.revision, enabled: true});
      const summary = 'Das lokale Modell hat beim nächsten Planungsschritt nicht rechtzeitig geantwortet. Der Auftrag wurde beendet; bereits gelesene Ergebnisse bleiben erhalten. Du kannst eine neue Anfrage stellen.';
      jobs = [{...job, status: 'failed', summary, steps: [
        {sequence: 1, kind: 'read', status: 'succeeded', sha256: 'a'.repeat(64), document: {message: 'Freigegebene Postfach-Werkzeuge geprüft'}, result: {}},
        {sequence: 2, kind: 'read', status: 'succeeded', sha256: 'b'.repeat(64), document: {message: 'Postfach-Status gelesen'}, result: {}},
        {sequence: 3, kind: 'error', status: 'failed', sha256: 'c'.repeat(64), document: {message: 'Lokale Planung: Zeitlimit erreicht'}, result: {}},
      ]}];
      response.messages = [...response.messages, {id: 'synthetic-recovery-answer', role: 'assistant', content: summary, label: 'LOCAL_ONLY', processing: {agent_job_id: job.id}}];
      await page.setViewportSize({width: 1440, height: 1150});
      await page.reload();
      await page.getByText('Angehalten · ' + goal, {exact: true}).click();
      await page.getByRole('button', {name: 'Frage erneut vorbereiten', exact: true}).click();
      await page.evaluate(() => document.activeElement?.blur());
      if (!await send.isEnabled()) throw Error('Synthetic recovery capture has a blocked composer');
      await page.screenshot({path: capture, fullPage: true});
    }

  } finally {
    for (const path of [detailPath, jobsPath, retryPath, messagePath, routePath, agentPath]) await page.unroute(path);
    const preview = await call('/conversations/' + chat.id + '/deletion');
    if (preview.blockers.length) throw Error('Synthetic recovery chat cleanup blocked');
    await call('/conversations/' + chat.id, 'DELETE', {expected_state: preview.expected_state});
    if (captureProfile) await call('/integrations/' + captureProfile.id, 'DELETE', {expected_revision: captureProfile.revision});
  }
}
