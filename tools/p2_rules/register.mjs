// Run only for approved drafts through an existing authenticated ego-browser Page.
// Import from a task script and call registerRules({page, drafts, checkpoint}).
export async function registerRules({page, drafts, checkpoint}) {
  const csrf = await page.evaluate(() => document.querySelector('[data-csrf]')?.getAttribute('data-csrf'));
  if (!csrf) throw new Error('AUTHENTICATED_PAGE_WITH_CSRF_REQUIRED');
  const results = [];
  for (let i = 0; i < drafts.length; i++) {
    const draft = drafts[i];
    // Server validates scope/effect, revision and owner authentication.
    const requestId = crypto.randomUUID();
    await checkpoint({index: i, requestId, state: 'prepared'});
    const response = await page.fetch('/api/imports/rules', {
      method: 'POST', headers: {'content-type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify({draft, expected_revision: 0, request_id: requestId}), timeout: 20000,
    });
    const result = {index: i, requestId, status: response.status, ok: response.ok};
    results.push(result);
    await checkpoint({...result, state: 'completed'});
    if (!response.ok) throw new Error(`RULE_REGISTRATION_STOPPED_${response.status}`);
  }
  return results;
}
