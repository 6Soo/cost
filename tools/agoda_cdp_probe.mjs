const port = Number(process.argv[2] || 9232);
const destination = process.argv[3] || 'https://www.agoda.com/account/bookings.html';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const target = pages.find((item) => item.type === 'page' && item.url === 'about:blank')
  || pages.find((item) => item.type === 'page' && item.webSocketDebuggerUrl);
if (!target?.webSocketDebuggerUrl) throw new Error('cdp_page_target_missing');

const socket = new WebSocket(target.webSocketDebuggerUrl);
let nextId = 1;
const pending = new Map();
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const settle = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) settle.reject(new Error(message.error.message || 'cdp_command_failed'));
    else settle.resolve(message.result);
  }
});
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', () => reject(new Error('cdp_socket_error')), { once: true });
});
const command = (method, params = {}) => new Promise((resolve, reject) => {
  const id = nextId++;
  pending.set(id, { resolve, reject });
  socket.send(JSON.stringify({ id, method, params }));
});

await command('Page.enable');
await command('Runtime.enable');
await command('Page.navigate', { url: destination });
await sleep(5000);
const result = await command('Runtime.evaluate', {
  expression: `(() => {
    const text = document.body?.innerText || '';
    const lower = text.toLowerCase();
    return JSON.stringify({
      url: location.href,
      title: document.title,
      body_length: text.length,
      login_marker: /sign.?in|log.?in|로그인|인증/.test(lower),
      bookings_marker: /booking|reservation|예약/.test(lower),
      upcoming_marker: /upcoming|다가오는/.test(lower),
      completed_marker: /completed|완료된/.test(lower),
      cancelled_marker: /cancelled|canceled|취소된/.test(lower),
      page_count: document.querySelectorAll('a,button').length,
      error_prefix: location.protocol === 'chrome-error:' ? text.slice(0, 500) : ''
    });
  })()`,
  returnByValue: true
});
console.log(result.result.value);
socket.close();
