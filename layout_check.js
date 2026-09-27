// Layout + interaction QA for the leaderboard page via CDP.
// Usage: node layout_check.js [file:// path or http URL]
const http = require('http');
const { spawn } = require('child_process');

const TARGET = process.argv[2] || 'file:///home/clawdbot/.openclaw/workspace/flop-leaderboard/index.html';
const CHROME = '/usr/bin/google-chrome';
const PORT = 9777;

function wait(ms){ return new Promise(r => setTimeout(r, ms)); }

function cdpSend(ws, id, method, params){
  return new Promise((resolve, reject) => {
    const onMsg = (data) => {
      try {
        const m = JSON.parse(data.toString());
        if (m.id === id) { ws.removeListener('message', onMsg); resolve(m.result); }
      } catch(e){}
    };
    ws.on('message', onMsg);
    ws.send(JSON.stringify({id, method, params}));
  });
}

async function main(){
  // minimal websocket client (no deps)
  const net = require('net');
  const crypto = require('crypto');

  const chrome = spawn(CHROME, [
    '--headless=new','--disable-gpu','--no-sandbox','--remote-debugging-port='+PORT,
    '--window-size=1280,1700','about:blank'
  ], {stdio: ['ignore','ignore','pipe']});
  let chromeErr = '';
  chrome.stderr.on('data', d => { chromeErr += d.toString(); });

  // wait for devtools endpoint
  let targets = null;
  for (let i=0;i<40;i++){
    await wait(250);
    try {
      targets = await new Promise((resolve, reject) => {
        http.get('http://127.0.0.1:'+PORT+'/json/list', res => {
          let b=''; res.on('data',c=>b+=c); res.on('end',()=>resolve(JSON.parse(b)));
        }).on('error', reject);
      });
      break;
    } catch(e){}
  }
  if (!targets) { console.error('no devtools', chromeErr.slice(0,500)); process.exit(1); }
  const page = targets.find(t => t.type === 'page');
  const wsUrl = page.webSocketDebuggerUrl;

  // raw websocket handshake
  const key = crypto.randomBytes(16).toString('base64');
  const u = new URL(wsUrl);
  const sock = net.connect(parseInt(u.port), '127.0.0.1', () => {
    sock.write('GET '+u.pathname+' HTTP/1.1\r\nHost: 127.0.0.1:'+u.port+'\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: '+key+'\r\nSec-WebSocket-Version: 13\r\n\r\n');
  });
  await new Promise(r => sock.once('data', r));
  // naive frame reader
  let buf = Buffer.alloc(0);
  const listeners = [];
  sock.on('data', d => {
    buf = Buffer.concat([buf, d]);
    while (true){
      if (buf.length < 2) break;
      const op = buf[0] & 0x0f;
      let len = buf[1] & 0x7f, off = 2;
      if (len === 126){ if (buf.length < 4) break; len = buf.readUInt16BE(2); off = 4; }
      else if (len === 127){ if (buf.length < 10) break; len = Number(buf.readBigUInt64BE(2)); off = 10; }
      if (buf.length < off + len) break;
      const payload = buf.slice(off, off + len);
      buf = buf.slice(off + len);
      if (op === 1 || op === 2){
        const msg = JSON.parse(payload.toString());
        listeners.forEach(l => l(msg));
      }
    }
  });
  function send(obj){
    const p = Buffer.from(JSON.stringify(obj));
    const mask = crypto.randomBytes(4);
    const masked = Buffer.alloc(p.length);
    for (let i=0;i<p.length;i++) masked[i] = p[i] ^ mask[i%4];
    let hdr;
    if (p.length < 126){ hdr = Buffer.from([0x81, 0x80 | p.length]); }
    else { hdr = Buffer.alloc(4); hdr[0]=0x81; hdr[1]=0x80|126; hdr.writeUInt16BE(p.length,2); }
    sock.write(Buffer.concat([hdr, mask, masked]));
  }
  function call(method, params){
    return new Promise(resolve => {
      const id = call._id = (call._id||0)+1;
      const l = m => { if (m.id === id){ listeners.splice(listeners.indexOf(l),1); resolve(m.result); } };
      listeners.push(l);
      send({id, method, params});
    });
  }
  function onceEvent(method){
    return new Promise(resolve => {
      const l = m => { if (m.method === method){ listeners.splice(listeners.indexOf(l),1); resolve(m); } };
      listeners.push(l);
    });
  }

  await call('Page.enable');
  await call('Runtime.enable');
  const loaded = onceEvent('Page.loadEventFired');
  await call('Page.navigate', {url: TARGET});
  await Promise.race([loaded, wait(8000)]);
  await wait(600);

  const eval_ = async (expr) => (await call('Runtime.evaluate', {expression: expr, returnByValue: true})).result.value;

  const checks = [];
  const ok = (name, cond, detail) => { checks.push([name, !!cond, detail||'']); console.log((cond?'PASS':'FAIL')+' '+name+(detail?' — '+detail:'')); };

  // structural
  ok('rows rendered', await eval_("document.querySelectorAll('#tbody tr').length") === 48, await eval_("document.querySelectorAll('#tbody tr').length") + ' rows');
  ok('our rank shown', await eval_("document.querySelector('#usgrid').textContent.includes('#131')"));
  ok('top score shown', await eval_("document.querySelector('#tbody').textContent.includes('9,387')"));
  ok('no leftover template tokens', await eval_("!document.body.textContent.includes('__')"));
  // geometry: no horizontal overflow
  ok('no horizontal overflow', await eval_("document.documentElement.scrollWidth <= window.innerWidth + 2"), await eval_("document.documentElement.scrollWidth + ' vs ' + window.innerWidth"));
  // every cell visible width > 0
  ok('all first-column cells have width', await eval_("[...document.querySelectorAll('#tbody td')].every(td => td.getBoundingClientRect().width > 0)"));
  // DID cells don't overlap the Score column: did cell right edge < score cell left edge
  ok('no cell overlap', await eval_(`(function(){
    const rows = [...document.querySelectorAll('#tbody tr')];
    let bad = 0;
    for (const r of rows){
      const tds = [...r.children];
      for (let i=0;i<tds.length-1;i++){
        if (tds[i].getBoundingClientRect().right > tds[i+1].getBoundingClientRect().left + 1) bad++;
      }
    }
    return bad === 0;
  })()`));
  // pills rendered
  ok('pills rendered', await eval_("document.querySelectorAll('.pill').length >= 3"));
  // network counters rendered
  ok('network counters', await eval_("document.querySelector('#netgrid').children.length >= 6"));
  // interaction: search filter
  await eval_("document.getElementById('q').value='z6Mkh'; document.getElementById('q').dispatchEvent(new Event('input'))");
  await wait(150);
  const filtered = await eval_("document.querySelectorAll('#tbody tr').length");
  ok('filter narrows rows', filtered > 0 && filtered < 48, filtered + ' rows after filter');
  await eval_("document.getElementById('q').value=''; document.getElementById('q').dispatchEvent(new Event('input'))");
  // interaction: sort by score desc
  await eval_("document.querySelector('th[data-k=score]').click()");
  await wait(150);
  const firstScore = await eval_("document.querySelector('#tbody tr td:nth-child(3)').textContent");
  ok('sort by score works', firstScore === '9,387', 'first score cell after sort: ' + firstScore);
  // interaction: sort by attests given (numeric, desc default)
  await eval_("document.querySelector('th[data-k=attests_given]').click()");
  await wait(150);
  const firstGiven = await eval_("document.querySelector('#tbody tr td:nth-child(7)').textContent");
  const maxGiven = await eval_("Math.max(...SNAPSHOT.leaderboard.map(r => r.attests_given || 0))");
  ok('sort by attests works', firstGiven === maxGiven.toLocaleString('en-US'), 'first given cell: ' + firstGiven + ', snapshot max: ' + maxGiven);
  // back to rank
  await eval_("document.querySelector('th[data-k=rank]').click()");
  await wait(100);

  // screenshot for the record
  const shot = await call('Page.captureScreenshot', {format: 'png'});
  require('fs').writeFileSync('/home/clawdbot/.openclaw/workspace/flop-leaderboard/qa_screenshot.png', Buffer.from(shot.data, 'base64'));
  console.log('screenshot saved');

  const fails = checks.filter(c => !c[1]);
  console.log(fails.length === 0 ? 'ALL ' + checks.length + ' CHECKS PASSED' : fails.length + ' CHECKS FAILED');
  chrome.kill();
  sock.destroy();
  process.exit(fails.length === 0 ? 0 : 1);
}
main().catch(e => { console.error(e); process.exit(1); });
