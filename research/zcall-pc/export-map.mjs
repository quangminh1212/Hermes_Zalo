/**
 * Re-scan Zalo PC app.asar for call keywords (Phase B static map).
 * Usage: node export-map.mjs [path-to-app.asar]
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const asar =
  process.argv[2] ||
  path.join(
    process.env.LOCALAPPDATA || '',
    'Programs',
    'Zalo',
    'Zalo-26.7.10',
    'resources',
    'app.asar',
  );

if (!fs.existsSync(asar)) {
  console.error('asar not found:', asar);
  process.exit(1);
}

const buf = fs.readFileSync(asar);
const keys = [
  '[zcall-v2]',
  'handleControl',
  'handleRecvSignal',
  '_sendToNative',
  'isIncomingCallEvent',
  'group_request',
  'recvSignal',
  'voicecall-wpa',
  'apiVoiceCallDomain',
  'generateReceiveCallMessage',
  'isZaloCalling',
  'enable_ipc_call',
  'initCall',
  'sendDataToNative',
  'onCallRequest',
  'onCallSignal',
  'onCallUpdate',
];

function count(key) {
  const needle = Buffer.from(key);
  let idx = 0;
  let n = 0;
  while (true) {
    idx = buf.indexOf(needle, idx);
    if (idx < 0) break;
    n++;
    idx += needle.length;
  }
  return n;
}

const report = {
  asar,
  size: buf.length,
  scannedAt: new Date().toISOString(),
  counts: Object.fromEntries(keys.map((k) => [k, count(k)])),
};

const out = path.join(__dirname, 'map_counts.json');
fs.writeFileSync(out, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
console.log('wrote', out);
