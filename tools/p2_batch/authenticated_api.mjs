// No login bypass or cookie export: use one existing owner-authenticated Page.
export async function request(inputPath, outputPath) {
  const fs = await import('node:fs/promises');
  const input = JSON.parse(await fs.readFile(inputPath, 'utf8'));
  const task = await taskSpace(input.task_space);
  const page = task.page(input.page);
  if (new URL(await page.url()).origin !== input.origin) throw new Error('API_ORIGIN_MISMATCH');
  const csrf = await page.evaluate(() => document.querySelector('[data-csrf]')?.getAttribute('data-csrf'));
  if (!csrf) throw new Error('AUTHENTICATED_PAGE_WITH_CSRF_REQUIRED');
  const options = {method: input.payload === null ? 'GET' : 'POST',
    headers: {'content-type': 'application/json', 'X-CSRF-Token': csrf}, timeout: 20000};
  if (input.payload !== null) options.body = JSON.stringify(input.payload);
  const response = await page.fetch(input.endpoint, options);
  let body;
  try { body = JSON.parse(response.body); }
  catch { body = {code: 'API_NON_JSON_RESPONSE'}; }
  await fs.writeFile(outputPath, JSON.stringify({ok: response.ok, status: response.status, body}), 'utf8');
}
