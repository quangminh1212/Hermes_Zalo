/**
 * Hermes_Zalo — personal-account bridge (OpenClaw zalouser pattern).
 * https://github.com/quangminh1212/Hermes_Zalo
 *
 * Unofficial zca-js — risk of account ban. Use a secondary account.
 *
 * HTTP API (127.0.0.1 only):
 *   GET  /health
 *   GET  /messages
 *   POST /send            { chatId, message, isGroup?, replyTo? }
 *   POST /send-media      { chatId, filePath|fileUrl, mediaType, caption?, isGroup?, fileName? }
 *   POST /typing          { chatId, isGroup? }
 *   GET  /chat/:id        ?isGroup=0|1
 *   GET  /allowlist
 *   POST /allowlist       { users: "id1,id2" | ["id1"], allowAll?: bool }  // hot-reload, no restart
 *   GET  /qr  /qr.png
 *   POST /pair
 *   GET  /me
 */
import express from 'express';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { Zalo, ThreadType, LoginQRCallbackEventType } from 'zca-js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
function getArg(name, def) {
  const i = args.indexOf(`--${name}`);
  return i !== -1 && args[i + 1] ? args[i + 1] : def;
}

const PORT = parseInt(getArg('port', process.env.ZALO_BRIDGE_PORT || '3001'), 10);
const SESSION_DIR = getArg(
  'session',
  process.env.ZALO_SESSION_DIR ||
    path.join(process.env.HERMES_HOME || path.join(process.env.HOME || process.env.USERPROFILE || '', '.hermes'), 'zalo', 'session'),
);
const CRED_PATH = path.join(SESSION_DIR, 'credentials.json');
const PAIR_ONLY = args.includes('--pair-only');
const FORWARD_SELF = ['1', 'true', 'yes', 'on'].includes(
  String(process.env.ZALO_FORWARD_SELF_MESSAGES || 'true').toLowerCase(),
);
const SEND_SEEN = ['1', 'true', 'yes', 'on'].includes(
  String(process.env.ZALO_SEND_SEEN || 'true').toLowerCase(),
);
const MAX_QUEUE = 500;
const TEXT_LIMIT = 2000;
const MEDIA_CACHE = path.join(SESSION_DIR, '..', 'media_cache');
fs.mkdirSync(SESSION_DIR, { recursive: true });
fs.mkdirSync(MEDIA_CACHE, { recursive: true });

let SCRIPT_HASH = '';
try {
  SCRIPT_HASH = createHash('sha256').update(fs.readFileSync(fileURLToPath(import.meta.url))).digest('hex').slice(0, 16);
} catch {}

/** @type {Set<string>} */
let ALLOWED = new Set();
let ALLOW_ALL = true;

function parseAllowlist(rawUsers, allowAllFlag) {
  const usersSrc = rawUsers != null ? rawUsers : (process.env.ZALO_ALLOWED_USERS || '*');
  const set = new Set(
    String(usersSrc)
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
  );
  const flagSrc = allowAllFlag != null ? allowAllFlag : (process.env.ZALO_ALLOW_ALL_USERS || '');
  let all =
    set.has('*') ||
    ['1', 'true', 'yes', 'on'].includes(String(flagSrc).toLowerCase());
  if (set.has('*')) all = true;
  return { set, all };
}

function applyAllowlist(rawUsers, allowAllFlag) {
  const { set, all } = parseAllowlist(rawUsers, allowAllFlag);
  ALLOWED = set;
  ALLOW_ALL = all;
  // Persist into process env so spawned tools / health reflect current state
  process.env.ZALO_ALLOWED_USERS = all ? '*' : [...ALLOWED].filter((x) => x !== '*').join(',') || '';
  process.env.ZALO_ALLOW_ALL_USERS = all ? 'true' : 'false';
  log(`🔒 Allowlist updated: ${all ? '*' : [...ALLOWED].join(', ') || '(none)'}`);
  return { allowAll: all, users: all ? ['*'] : [...ALLOWED] };
}

// initial
applyAllowlist(process.env.ZALO_ALLOWED_USERS, process.env.ZALO_ALLOW_ALL_USERS);

let api = null;
let connectionState = 'disconnected'; // disconnected | pairing | connected
let ownId = '';
let displayName = '';
let lastQr = null;
let lastError = null;
const messageQueue = [];
const recentSent = new Set();
const recentInbound = new Set();
const MAX_RECENT = 300;

function log(...a) {
  console.log(...a);
}

function saveCreds(creds) {
  fs.writeFileSync(CRED_PATH, JSON.stringify({ ...creds, savedAt: new Date().toISOString() }, null, 2), 'utf8');
}

function loadCreds() {
  try {
    if (!fs.existsSync(CRED_PATH)) return null;
    const j = JSON.parse(fs.readFileSync(CRED_PATH, 'utf8'));
    if (!j?.imei || !j?.cookie || !j?.userAgent) return null;
    return { imei: j.imei, cookie: j.cookie, userAgent: j.userAgent, language: j.language || 'vi' };
  } catch {
    return null;
  }
}

function trackId(set, id) {
  if (!id) return;
  set.add(String(id));
  if (set.size > MAX_RECENT) {
    const first = set.values().next().value;
    set.delete(first);
  }
}

function isAllowed(senderId) {
  if (ALLOW_ALL || ALLOWED.has('*')) return true;
  const s = String(senderId || '');
  if (!s) return false;
  if (ALLOWED.has(s)) return true;
  for (const a of ALLOWED) {
    if (!a || a === '*') continue;
    if (s === a || s.startsWith(a) || a.startsWith(s)) return true;
    // phone variants: 0xxx vs 84xxx
    const digits = (x) => String(x).replace(/\D/g, '');
    const sd = digits(s);
    const ad = digits(a);
    if (sd && ad && (sd === ad || sd.endsWith(ad) || ad.endsWith(sd))) return true;
  }
  return false;
}

function extractText(content) {
  if (typeof content === 'string') return content;
  if (!content || typeof content !== 'object') return '';
  if (typeof content.title === 'string' && content.title) {
    const parts = [content.title];
    if (content.description) parts.push(String(content.description));
    if (content.href) parts.push(String(content.href));
    return parts.filter(Boolean).join('\n');
  }
  if (typeof content.text === 'string') return content.text;
  if (typeof content.msg === 'string') return content.msg;
  if (typeof content.description === 'string') return content.description;
  if (typeof content.href === 'string') return content.href;
  try {
    return JSON.stringify(content).slice(0, 500);
  } catch {
    return '';
  }
}

function extractMediaMeta(content, msgType) {
  if (!content || typeof content !== 'object') return null;
  const href = content.href || content.url || content.hdUrl || content.normalUrl || content.fileUrl || '';
  const thumb = content.thumb || content.thumbUrl || content.previewThumb || '';
  const title = content.title || content.fileName || content.filename || '';
  const mt = String(msgType || content.type || '').toLowerCase();
  let kind = null;
  if (mt.includes('photo') || mt.includes('image') || /\.(jpe?g|png|gif|webp)(\?|$)/i.test(href)) kind = 'image';
  else if (mt.includes('video') || /\.(mp4|mov|webm)(\?|$)/i.test(href)) kind = 'video';
  else if (mt.includes('voice') || mt.includes('audio') || /\.(m4a|mp3|aac|ogg|amr)(\?|$)/i.test(href)) kind = 'audio';
  else if (mt.includes('share') || mt.includes('file') || mt.includes('doc') || href) kind = 'document';
  if (!href && !thumb) return null;
  return {
    kind: kind || 'document',
    url: href || thumb,
    thumb: thumb || '',
    fileName: title || '',
  };
}

function chunkText(text) {
  const t = String(text || '');
  if (t.length <= TEXT_LIMIT) return [t];
  const out = [];
  for (let i = 0; i < t.length; i += TEXT_LIMIT) out.push(t.slice(i, i + TEXT_LIMIT));
  return out;
}

function enqueueMessage(evt) {
  messageQueue.push(evt);
  if (messageQueue.length > MAX_QUEUE) messageQueue.shift();
}

function threadType(isGroup) {
  return isGroup ? ThreadType.Group : ThreadType.User;
}

function extractSendMessageId(result) {
  if (!result || typeof result !== 'object') return null;
  const direct = result.msgId ?? result.messageId;
  if (direct != null) return String(direct);
  const primary = result.message?.msgId;
  if (primary != null) return String(primary);
  const att = result.attachment?.[0]?.msgId;
  if (att != null) return String(att);
  return null;
}

async function snapshotAndSave(apiInst) {
  try {
    const ctx = apiInst.getContext?.() || {};
    const jar = apiInst.getCookie?.();
    const cookieJson = jar?.toJSON?.() || jar;
    const cookies = cookieJson?.cookies || cookieJson;
    const imei = ctx.imei;
    const userAgent = ctx.userAgent;
    if (imei && cookies && userAgent) {
      saveCreds({ imei, cookie: cookies, userAgent, language: ctx.language || 'vi' });
      log('💾 Credentials saved');
    }
  } catch (e) {
    log('warn: could not snapshot credentials:', e?.message || e);
  }
}

function attachListener(apiInst) {
  apiInst.listener.on('message', (message) => {
    try {
      const isGroup = message.type === ThreadType.Group;
      const data = message.data || {};
      const threadId = String(message.threadId || data.threadId || data.idTo || '');
      const senderId = String(
        data.uidFrom || data.senderId || (message.isSelf ? ownId : threadId) || '',
      );
      const msgId = String(data.msgId || data.messageId || `${Date.now()}`);
      const cliMsgId = data.cliMsgId != null ? String(data.cliMsgId) : '';
      const body = extractText(data.content);
      const media = extractMediaMeta(data.content, data.msgType);

      if (recentInbound.has(msgId) || (cliMsgId && recentInbound.has(cliMsgId))) return;
      trackId(recentInbound, msgId);
      if (cliMsgId) trackId(recentInbound, cliMsgId);

      if (message.isSelf) {
        if (!FORWARD_SELF) return;
        if (recentSent.has(msgId) || (cliMsgId && recentSent.has(cliMsgId))) return;
      } else if (!isAllowed(senderId)) {
        log(JSON.stringify({ event: 'ignored', reason: 'allowlist', senderId, threadId }));
        return;
      }

      if (!body && !media) return;

      // fire-and-forget seen/delivered (don't block queue)
      if (SEND_SEEN && !message.isSelf && apiInst.sendSeenEvent) {
        try {
          Promise.resolve(apiInst.sendSeenEvent(message)).catch(() => {});
        } catch {}
      }

      enqueueMessage({
        messageId: msgId,
        cliMsgId: cliMsgId || null,
        chatId: threadId,
        senderId,
        senderName: data.dName || data.displayName || senderId,
        chatName: isGroup ? threadId : data.dName || senderId,
        isGroup,
        body: body || (media ? `[${media.kind}]` : ''),
        fromMe: !!message.isSelf,
        timestamp: data.ts || data.timestamp || Date.now(),
        rawType: message.type,
        msgType: data.msgType || null,
        mediaType: media?.kind || null,
        mediaUrl: media?.url || null,
        mediaThumb: media?.thumb || null,
        mediaFileName: media?.fileName || null,
        quote: data.quote
          ? {
              msgId: data.quote.globalMsgId || data.quote.msgId || null,
              body: data.quote.msg || '',
              ownerId: data.quote.ownerId || null,
            }
          : null,
      });
    } catch (e) {
      log('message handler error:', e?.message || e);
    }
  });

  apiInst.listener.on('error', (err) => {
    lastError = err?.message || String(err);
    log('listener error:', lastError);
  });

  apiInst.listener.on('closed', () => {
    connectionState = 'disconnected';
    log('listener closed');
  });

  apiInst.listener.start({ retryOnClose: true });
}

async function connectWithCreds(creds) {
  const zalo = new Zalo({ logging: false });
  api = await zalo.login(creds);
  await snapshotAndSave(api);
  try {
    ownId = String(api.getOwnId?.() || '');
  } catch {
    ownId = '';
  }
  try {
    const info = await api.fetchAccountInfo?.();
    const profile = info?.profile || info;
    displayName = profile?.displayName || profile?.zaloName || profile?.name || '';
    if (!ownId && profile?.userId) ownId = String(profile.userId);
  } catch {}
  attachListener(api);
  connectionState = 'connected';
  lastError = null;
  log(`✅ Zalo connected as ${displayName || ownId || 'unknown'}`);
}

async function startQrLogin() {
  if (connectionState === 'pairing') return;
  connectionState = 'pairing';
  lastQr = null;
  lastError = null;
  log('📱 Zalo QR pairing… scan with Zalo mobile app');

  const zalo = new Zalo({ logging: false });
  try {
    api = await zalo.loginQR(undefined, (event) => {
      try {
        if (event.type === LoginQRCallbackEventType.QRCodeGenerated) {
          const image = event.data?.image || '';
          lastQr = {
            code: event.data?.code || '',
            image,
            at: Date.now(),
          };
          try {
            import('qrcode-terminal')
              .then((mod) => {
                const qr = mod.default || mod;
                if (event.data?.code) qr.generate(event.data.code, { small: true });
              })
              .catch(() => {});
          } catch {}
          try {
            const b64 = image.replace(/^data:image\/\w+;base64,/, '');
            if (b64) fs.writeFileSync(path.join(SESSION_DIR, 'qr.png'), Buffer.from(b64, 'base64'));
            log(`📁 QR saved: ${path.join(SESSION_DIR, 'qr.png')}`);
          } catch {}
          log('QR generated — open /qr or qr.png');
        } else if (event.type === LoginQRCallbackEventType.QRCodeScanned) {
          log(`QR scanned by ${event.data?.display_name || 'user'}`);
        } else if (event.type === LoginQRCallbackEventType.QRCodeExpired) {
          log('QR expired');
          lastQr = null;
        } else if (event.type === LoginQRCallbackEventType.QRCodeDeclined) {
          lastError = 'QR declined';
          connectionState = 'disconnected';
        } else if (event.type === LoginQRCallbackEventType.GotLoginInfo) {
          saveCreds({
            imei: event.data.imei,
            cookie: event.data.cookie,
            userAgent: event.data.userAgent,
            language: 'vi',
          });
          log('GotLoginInfo — credentials stored');
        }
      } catch (e) {
        log('QR callback error:', e?.message || e);
      }
    });

    await snapshotAndSave(api);
    try {
      ownId = String(api.getOwnId?.() || '');
    } catch {}
    try {
      const info = await api.fetchAccountInfo?.();
      const profile = info?.profile || info;
      displayName = profile?.displayName || profile?.zaloName || '';
      if (!ownId && profile?.userId) ownId = String(profile.userId);
    } catch {}
    attachListener(api);
    connectionState = 'connected';
    lastQr = null;
    log(`✅ Zalo paired as ${displayName || ownId || 'unknown'}`);
  } catch (e) {
    lastError = e?.message || String(e);
    connectionState = 'disconnected';
    api = null;
    log('❌ QR login failed:', lastError);
    throw e;
  }
}

async function boot() {
  const creds = loadCreds();
  if (creds) {
    try {
      await connectWithCreds(creds);
      return;
    } catch (e) {
      log('cookie login failed, will need QR:', e?.message || e);
      lastError = e?.message || String(e);
      try {
        fs.renameSync(CRED_PATH, CRED_PATH + '.bad');
      } catch {}
    }
  }
  if (PAIR_ONLY || !creds) {
    await startQrLogin();
  }
}

function requireConnected(res) {
  if (!api || connectionState !== 'connected') {
    res.status(503).json({ error: 'Not connected to Zalo' });
    return false;
  }
  return true;
}

async function sendTextInternal(chatId, message, isGroup, replyTo) {
  const type = threadType(isGroup);
  const chunks = chunkText(String(message ?? ''));
  const ids = [];
  for (let i = 0; i < chunks.length; i++) {
    const payload = { msg: chunks[i] };
    // quote support if caller passed a prior message snapshot
    if (replyTo && i === 0 && typeof replyTo === 'object') {
      payload.quote = replyTo;
    }
    const result = await api.sendMessage(payload, String(chatId), type);
    const mid = extractSendMessageId(result);
    if (mid) {
      trackId(recentSent, mid);
      ids.push(mid);
    }
    const cli = result?.message?.cliMsgId || result?.cliMsgId;
    if (cli) trackId(recentSent, String(cli));
    if (i < chunks.length - 1) await new Promise((r) => setTimeout(r, 350));
  }
  return ids;
}

async function sendMediaInternal({ chatId, filePath, fileUrl, mediaType, caption, isGroup, fileName }) {
  const type = threadType(isGroup);
  let buffer = null;
  let name = fileName || '';

  if (filePath) {
    const abs = path.resolve(String(filePath));
    if (!fs.existsSync(abs)) throw new Error(`File not found: ${abs}`);
    buffer = fs.readFileSync(abs);
    if (!name) name = path.basename(abs);
  } else if (fileUrl) {
    const resp = await fetch(String(fileUrl));
    if (!resp.ok) throw new Error(`download failed HTTP ${resp.status}`);
    buffer = Buffer.from(await resp.arrayBuffer());
    if (!name) {
      try {
        name = path.basename(new URL(fileUrl).pathname) || 'upload.bin';
      } catch {
        name = 'upload.bin';
      }
    }
  } else {
    throw new Error('filePath or fileUrl required');
  }

  if (!name.includes('.')) {
    const ext =
      mediaType === 'image' ? 'jpg' : mediaType === 'video' ? 'mp4' : mediaType === 'audio' || mediaType === 'voice' ? 'm4a' : 'bin';
    name = `${name}.${ext}`;
  }

  const kind = String(mediaType || 'document').toLowerCase();
  const cap = caption != null ? String(caption) : '';

  // Voice: upload then sendVoice
  if (kind === 'audio' || kind === 'voice' || kind === 'ptt') {
    if (cap) {
      await sendTextInternal(chatId, cap, isGroup, null);
    }
    const uploaded = await api.uploadAttachment(
      [
        {
          data: buffer,
          filename: name,
          metadata: { totalSize: buffer.length },
        },
      ],
      String(chatId),
      type,
    );
    const asset = (uploaded || []).find((u) => u && (u.fileUrl || u.normalUrl || u.hdUrl));
    const voiceUrl = asset?.fileUrl || asset?.hdUrl || asset?.normalUrl;
    if (!voiceUrl) throw new Error('uploadAttachment returned no URL for voice');
    const result = await api.sendVoice({ voiceUrl }, String(chatId), type);
    const mid = extractSendMessageId(result);
    if (mid) trackId(recentSent, mid);
    return mid;
  }

  // Image/video/document via sendMessage attachments (zca-js uploads internally)
  const result = await api.sendMessage(
    {
      msg: cap.slice(0, TEXT_LIMIT),
      attachments: [
        {
          data: buffer,
          filename: name,
          metadata: { totalSize: buffer.length },
        },
      ],
    },
    String(chatId),
    type,
  );
  const mid = extractSendMessageId(result);
  if (mid) trackId(recentSent, mid);
  for (const a of result?.attachment || []) {
    if (a?.msgId) trackId(recentSent, String(a.msgId));
  }
  return mid;
}

// ── HTTP ──────────────────────────────────────────────────────────
const app = express();
app.use(express.json({ limit: '12mb' }));

app.use((req, res, next) => {
  const host = String(req.headers.host || '').split(':')[0].toLowerCase();
  if (!['localhost', '127.0.0.1', '::1'].includes(host)) {
    return res.status(403).json({ error: 'host not allowed' });
  }
  next();
});

app.get('/health', (_req, res) => {
  res.json({
    status: connectionState,
    queueLength: messageQueue.length,
    uptime: process.uptime(),
    scriptHash: SCRIPT_HASH,
    ownId,
    displayName,
    error: lastError,
    allowAll: ALLOW_ALL,
    allowedUsers: ALLOW_ALL ? ['*'] : [...ALLOWED],
    features: [
      'text',
      'media',
      'typing',
      'chat_info',
      'allowlist_hot_reload',
      'seen',
      'inbound_media_meta',
    ],
  });
});

app.get('/me', (_req, res) => {
  res.json({ ownId, displayName, status: connectionState });
});

app.get('/allowlist', (_req, res) => {
  res.json({ allowAll: ALLOW_ALL, users: ALLOW_ALL ? ['*'] : [...ALLOWED] });
});

app.post('/allowlist', (req, res) => {
  try {
    const body = req.body || {};
    let users = body.users;
    if (Array.isArray(users)) users = users.join(',');
    if (users == null && body.allowed_users != null) {
      users = Array.isArray(body.allowed_users) ? body.allowed_users.join(',') : body.allowed_users;
    }
    if (users == null) {
      return res.status(400).json({ error: 'users required (string or array)' });
    }
    const result = applyAllowlist(users, body.allowAll ?? body.allow_all);
    res.json({ success: true, ...result });
  } catch (e) {
    res.status(500).json({ error: e?.message || String(e) });
  }
});

app.get('/qr', (_req, res) => {
  if (!lastQr) return res.status(404).json({ error: 'no active QR' });
  res.json(lastQr);
});

app.get('/qr.png', (_req, res) => {
  const p = path.join(SESSION_DIR, 'qr.png');
  if (!fs.existsSync(p)) return res.status(404).send('no qr');
  res.type('png').send(fs.readFileSync(p));
});

app.post('/pair', async (_req, res) => {
  try {
    if (connectionState === 'connected') {
      return res.json({ ok: true, status: 'already_connected', ownId, displayName });
    }
    startQrLogin().catch(() => {});
    res.json({ ok: true, status: 'pairing' });
  } catch (e) {
    res.status(500).json({ error: e?.message || String(e) });
  }
});

app.get('/messages', (_req, res) => {
  const msgs = messageQueue.splice(0, messageQueue.length);
  res.json(msgs);
});

app.post('/send', async (req, res) => {
  if (!requireConnected(res)) return;
  const { chatId, message, isGroup, replyTo } = req.body || {};
  if (!chatId || message == null || message === '') {
    return res.status(400).json({ error: 'chatId and message required' });
  }
  try {
    const ids = await sendTextInternal(chatId, message, !!isGroup, replyTo || null);
    res.json({ success: true, messageId: ids[ids.length - 1] || null, messageIds: ids });
  } catch (e) {
    res.status(500).json({ error: e?.message || String(e) });
  }
});

app.post('/send-media', async (req, res) => {
  if (!requireConnected(res)) return;
  const { chatId, filePath, fileUrl, mediaType, caption, isGroup, fileName } = req.body || {};
  if (!chatId || (!filePath && !fileUrl)) {
    return res.status(400).json({ error: 'chatId and filePath|fileUrl required' });
  }
  try {
    const messageId = await sendMediaInternal({
      chatId,
      filePath,
      fileUrl,
      mediaType: mediaType || 'document',
      caption,
      isGroup: !!isGroup,
      fileName,
    });
    res.json({ success: true, messageId });
  } catch (e) {
    res.status(500).json({ error: e?.message || String(e) });
  }
});

app.post('/typing', async (req, res) => {
  if (!requireConnected(res)) return;
  const { chatId, isGroup } = req.body || {};
  if (!chatId) return res.status(400).json({ error: 'chatId required' });
  try {
    if (api.sendTypingEvent) {
      await api.sendTypingEvent(String(chatId), threadType(!!isGroup));
    }
    res.json({ success: true });
  } catch (e) {
    // typing is best-effort
    res.json({ success: false, error: e?.message || String(e) });
  }
});

app.get('/chat/:id', async (req, res) => {
  if (!requireConnected(res)) return;
  const id = String(req.params.id || '');
  const isGroup = ['1', 'true', 'yes'].includes(String(req.query.isGroup || '').toLowerCase()) || id.startsWith('group:');
  const clean = id.startsWith('group:') ? id.slice(6) : id;
  try {
    if (isGroup && api.getGroupInfo) {
      const info = await api.getGroupInfo(clean);
      const g = info?.gridInfoMap?.[clean] || {};
      return res.json({
        name: g.name || clean,
        type: 'group',
        participants: g.memVerList || g.currentMems || [],
        memberCount: g.totalMember,
      });
    }
    if (api.getUserInfo) {
      const info = await api.getUserInfo(clean);
      const p = info?.changed_profiles?.[clean] || {};
      return res.json({
        name: p.displayName || p.zaloName || p.username || clean,
        type: 'dm',
        avatar: p.avatar || null,
        userId: p.userId || clean,
      });
    }
    res.json({ name: clean, type: isGroup ? 'group' : 'dm' });
  } catch (e) {
    res.json({ name: clean, type: isGroup ? 'group' : 'dm', error: e?.message || String(e) });
  }
});

if (PAIR_ONLY) {
  boot()
    .then(() => {
      log('pair-only done, exiting');
      process.exit(connectionState === 'connected' ? 0 : 1);
    })
    .catch((e) => {
      console.error(e);
      process.exit(1);
    });
} else {
  app.listen(PORT, '127.0.0.1', () => {
    log(`🌉 Zalo bridge listening on port ${PORT}`);
    log(`📁 Session: ${SESSION_DIR}`);
    log(`🔒 Allow: ${ALLOW_ALL ? '*' : [...ALLOWED].join(', ') || '(none)'}`);
    boot().catch((e) => {
      lastError = e?.message || String(e);
      log('boot error:', lastError);
    });
  });
}
