// Live-mode E2E: load page, click "Go live", verify it polls /api/stats and updates UI.
const http = require('http');
const { spawn } = require('child_process');
const net = require('net');
const crypto = require('crypto');
const PORT = 9778;
const wait = ms => new Promise(r => setTimeout(r, ms));

async function main(){
  const chrome = spawn('/usr/bin/google-chrome', [
    '--headless=new','--disable-gpu','--no-sandbox','--remote-debugging-port='+PORT,
    '--window-size=1280,1700','about:blank'
  ], {stdio:['ignore','ignore','ignore']});
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
  const page = targets.find(t => t.type === 'page');
  const u = new URL(page.webSocketDebuggerUrl);
  const key = crypto.randomBytes(16).toString('base64');
  const sock = net.connect(parseInt(u.port), '127.0.0.1', () => {
    sock.write('GET '+u.pathname+' HTTP/1.1\r\nHost: 127.0.0.1:'+u.port+'\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: '+key+'\r\nSec-WebSocket-Version: 13\r\n\r\n');
  });
  await new Promise(r => sock.once('data', r));
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
      if (op === 1 || op === 2) listeners.forEach(l => l(JSON.parse(payload.toString())));
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
  const eval_ = async (expr) => (await call('Runtime.evaluate', {expression: expr, returnByValue: true})).result.value;

  await call('Page.enable');
  await call('Runtime.enable');
  await call('Page.navigate', {url: 'file:///home/clawdbot/.openclaw/workspace/flop-leaderboard/index.html'});
  await wait(1000);

  const before = await eval_("document.getElementById('pill-when').textContent");
  console.log('before click:', before.trim());

  await eval_("document.getElementById('livebtn').click()");
  // wait for the fetch round-trips
  let livePill = '', usnote = '';
  for (let i=0;i<20;i++){
    await wait(500);
    livePill = await eval_("document.getElementById('pill-when').textContent");
    usnote = await eval_("document.getElementById('usnote').textContent");
    if (livePill.includes('live')) break;
  }
  console.log('after click:', livePill.trim());
  console.log('us card note:', usnote.trim());
  const rows = await eval_("document.querySelectorAll('#tbody tr').length");
  console.log('rows in live mode:', rows);
  const stop = await eval_("document.getElementById('livebtn').click()"), // toggle off
        offText = await eval_("document.getElementById('livebtn').textContent");
  console.log('after stop, button reads:', offText.trim());

  const pass = livePill.includes('live') && usnote.includes('live from') && Number(rows) > 0;
  console.log(pass ? 'LIVE MODE E2E PASSED' : 'LIVE MODE E2E FAILED');
  chrome.kill(); sock.destroy();
  process.exit(pass ? 0 : 1);
}
main().catch(e => { console.error(e); process.exit(1); });
