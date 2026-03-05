import fs from 'fs';
import path from 'path';
import { createServer } from 'http';

import makeWASocket, {
  Browsers,
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestWaWebVersion,
  makeCacheableSignalKeyStore,
  useMultiFileAuthState
} from '@whiskeysockets/baileys';

import { runCodex } from './codex.mjs';
import {
  createConfig,
  createQueuedCredsSaver,
  ensureDir,
  extractNormalizedMessageContent,
  extractReplyContextFromBaileysMessage,
  extractPlainTextFromBaileysMessage,
  extractTextFromBaileysMessage,
  parseInteger,
  readEnvFromFile
} from './common.mjs';
import { createLogger } from './logger.mjs';

const localEnv = readEnvFromFile(path.join(process.cwd(), '.env'));
for (const [k, v] of Object.entries(localEnv)) {
  if (process.env[k] === undefined) process.env[k] = v;
}

const config = createConfig();
ensureDir(config.stateDir);
ensureDir(config.authDir);
ensureDir(config.logsDir);
ensureDir(config.filesDir);

const logger = createLogger();
const perChatQueue = new Map();
const jidToChatId = new Map();
const chatIdToJid = new Map();
const updateQueue = [];
const updateWaiters = [];
const storedFiles = new Map();
const storedFileOrder = [];
const outboundMessageKeys = new Map();
const outboundMessageOrder = [];
const MAX_OUTBOUND_MESSAGE_KEYS = 2000;
const STORED_FILES_CLEANUP_INTERVAL_MS = 60 * 1000;

let nextInternalMessageId = 1;
let nextUpdateId = 1;
let activeSock = null;
let apiServer = null;
let storedFilesCleanupTimer = null;
const OUTBOUND_MEDIA_TYPES = new Set(['photo', 'audio', 'voice', 'document']);
const MIME_BY_EXTENSION = new Map([
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.png', 'image/png'],
  ['.webp', 'image/webp'],
  ['.gif', 'image/gif'],
  ['.pdf', 'application/pdf'],
  ['.txt', 'text/plain'],
  ['.json', 'application/json'],
  ['.ogg', 'audio/ogg'],
  ['.oga', 'audio/ogg'],
  ['.opus', 'audio/ogg; codecs=opus'],
  ['.mp3', 'audio/mpeg'],
  ['.m4a', 'audio/mp4'],
  ['.aac', 'audio/aac'],
  ['.wav', 'audio/wav']
]);

cleanupFilesDirOnStartup();

function shouldHandleChat(jid, isGroup, chatId = null) {
  // Apply numeric chat-id allowlist to groups only. DMs are controlled via
  // WA_ALLOWED_DMS and WA_DM_ALWAYS_RESPOND policy.
  if (isGroup && config.allowedChatIds.length > 0) {
    const parsedChatId = Number.isInteger(chatId) ? chatId : parseInteger(chatId, NaN, 1);
    if (!Number.isFinite(parsedChatId) || Number.isNaN(parsedChatId)) {
      return false;
    }
    if (!config.allowedChatIds.includes(parsedChatId)) {
      return false;
    }
  }
  if (isGroup && config.allowedGroups.length > 0 && !config.allowedGroups.includes(jid)) {
    return false;
  }
  if (!isGroup && config.allowedDms.length > 0 && !config.allowedDms.includes(jid)) {
    return false;
  }
  return true;
}

function enqueueByChat(chatJid, task) {
  const previous = perChatQueue.get(chatJid) || Promise.resolve();
  const next = previous
    .catch(() => undefined)
    .then(task)
    .catch((err) => {
      logger.error({ chatJid, err: String(err) }, 'task failed');
    });
  perChatQueue.set(chatJid, next);
}

function stripTrigger(text) {
  return text.replace(config.triggerRegex, '').trim();
}

function nextMessageId() {
  const value = nextInternalMessageId;
  nextInternalMessageId += 1;
  return value;
}

function rememberOutboundMessageKey(internalMessageId, chatJid, waMessageId) {
  if (!Number.isInteger(internalMessageId) || !waMessageId) return;
  outboundMessageKeys.set(internalMessageId, { chatJid, waMessageId: String(waMessageId) });
  const existingIndex = outboundMessageOrder.indexOf(internalMessageId);
  if (existingIndex >= 0) {
    outboundMessageOrder.splice(existingIndex, 1);
  }
  outboundMessageOrder.push(internalMessageId);
  while (outboundMessageOrder.length > MAX_OUTBOUND_MESSAGE_KEYS) {
    const victim = outboundMessageOrder.shift();
    if (victim !== undefined && victim !== null) {
      outboundMessageKeys.delete(victim);
    }
  }
}

function stableBaseChatId(jid) {
  let hash = 2166136261;
  for (let i = 0; i < jid.length; i += 1) {
    hash ^= jid.charCodeAt(i);
    hash = Math.imul(hash, 16777619) >>> 0;
  }
  const positive = hash & 0x7fffffff;
  return positive === 0 ? 1 : positive;
}

function getOrCreateChatId(chatJid) {
  const existing = jidToChatId.get(chatJid);
  if (existing) return existing;

  let candidate = stableBaseChatId(chatJid);
  while (true) {
    const occupied = chatIdToJid.get(candidate);
    if (!occupied || occupied === chatJid) break;
    candidate = (candidate + 1) & 0x7fffffff;
    if (candidate === 0) candidate = 1;
  }
  jidToChatId.set(chatJid, candidate);
  chatIdToJid.set(candidate, chatJid);
  return candidate;
}

function resolveChatJid(chatIdRaw, chatJidRaw = null) {
  if (chatJidRaw && typeof chatJidRaw === 'string') {
    return chatJidRaw.trim();
  }
  if (typeof chatIdRaw === 'string' && chatIdRaw.includes('@')) {
    return chatIdRaw.trim();
  }
  const parsed = parseInteger(chatIdRaw, NaN, 1);
  if (!Number.isFinite(parsed) || Number.isNaN(parsed)) return '';
  return chatIdToJid.get(parsed) || '';
}

function inferMimeTypeFromRef(fileRef, fallback = '') {
  if (!fileRef || typeof fileRef !== 'string') return fallback;
  let pathname = fileRef;
  try {
    const parsed = new URL(fileRef);
    pathname = parsed.pathname || pathname;
  } catch {
    // Not a URL; treat as local path string.
  }
  const extension = path.extname(pathname).toLowerCase();
  return MIME_BY_EXTENSION.get(extension) || fallback;
}

function resolveOutboundMediaRef(mediaRef) {
  try {
    const parsed = new URL(mediaRef);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return {
        isLocalFile: false,
        value: { url: mediaRef },
        fileName: path.basename(parsed.pathname || '') || 'upload.bin',
        mimeType: inferMimeTypeFromRef(parsed.pathname)
      };
    }
  } catch {
    // Continue with local file checks.
  }

  const resolvedPath = path.resolve(mediaRef);
  if (!fs.existsSync(resolvedPath)) {
    throw new Error('unsupported_media_ref');
  }
  const stat = fs.statSync(resolvedPath);
  if (!stat.isFile()) {
    throw new Error('unsupported_media_ref');
  }
  if (stat.size > config.bridgeFileMaxBytes) {
    throw new Error('media_file_too_large');
  }
  return {
    isLocalFile: true,
    value: fs.readFileSync(resolvedPath),
    fileName: path.basename(resolvedPath) || 'upload.bin',
    mimeType: inferMimeTypeFromRef(resolvedPath)
  };
}

function createHttpError(code, message) {
  const err = new Error(message);
  err.code = code;
  return err;
}

function removeStoredFileOrderEntry(fileId) {
  let index = storedFileOrder.indexOf(fileId);
  while (index >= 0) {
    storedFileOrder.splice(index, 1);
    index = storedFileOrder.indexOf(fileId);
  }
}

function evictStoredFile(fileId) {
  const existing = storedFiles.get(fileId);
  removeStoredFileOrderEntry(fileId);
  if (!existing) return;
  storedFiles.delete(fileId);
  try {
    fs.rmSync(existing.localPath, { force: true });
  } catch {
    // Best-effort cleanup.
  }
}

function computeStoredFileBytes() {
  let total = 0;
  for (const metadata of storedFiles.values()) {
    const size = Number(metadata?.fileSize);
    if (Number.isFinite(size) && size > 0) {
      total += size;
    }
  }
  return total;
}

function enforceStoredFileRetention() {
  const ttlMs = Math.max(0, Number(config.bridgeFileRetentionSeconds || 0) * 1000);
  const now = Date.now();
  if (ttlMs > 0) {
    for (const [fileId, metadata] of storedFiles.entries()) {
      const createdAtMs = Number(metadata?.createdAtMs || 0);
      if (createdAtMs > 0 && (now - createdAtMs) > ttlMs) {
        evictStoredFile(fileId);
      }
    }
  }

  let totalBytes = computeStoredFileBytes();
  while (totalBytes > config.bridgeFileMaxTotalBytes && storedFileOrder.length > 0) {
    const victim = storedFileOrder[0];
    evictStoredFile(victim);
    totalBytes = computeStoredFileBytes();
  }
}

function cleanupFilesDirOnStartup() {
  const ttlMs = Math.max(0, Number(config.bridgeFileRetentionSeconds || 0) * 1000);
  const now = Date.now();
  let removedByTtl = 0;
  let removedByLimit = 0;
  const candidates = [];

  let entries = [];
  try {
    entries = fs.readdirSync(config.filesDir, { withFileTypes: true });
  } catch (err) {
    logger.warn({ err: String(err), filesDir: config.filesDir }, 'failed to list bridge files directory');
    return;
  }

  for (const entry of entries) {
    if (!entry.isFile()) continue;
    const fullPath = path.join(config.filesDir, entry.name);
    let stat;
    try {
      stat = fs.statSync(fullPath);
    } catch {
      continue;
    }
    if (!stat.isFile()) continue;
    if (ttlMs > 0 && (now - stat.mtimeMs) > ttlMs) {
      try {
        fs.rmSync(fullPath, { force: true });
        removedByTtl += 1;
      } catch {
        // Best-effort startup cleanup.
      }
      continue;
    }
    candidates.push({ fullPath, mtimeMs: stat.mtimeMs, size: stat.size });
  }

  candidates.sort((a, b) => b.mtimeMs - a.mtimeMs);
  let keptBytes = 0;
  for (const candidate of candidates) {
    if (keptBytes + candidate.size <= config.bridgeFileMaxTotalBytes) {
      keptBytes += candidate.size;
      continue;
    }
    try {
      fs.rmSync(candidate.fullPath, { force: true });
      removedByLimit += 1;
    } catch {
      // Best-effort startup cleanup.
    }
  }

  if (removedByTtl > 0 || removedByLimit > 0) {
    logger.info(
      {
        removedByTtl,
        removedByLimit,
        retentionSeconds: config.bridgeFileRetentionSeconds,
        maxTotalBytes: config.bridgeFileMaxTotalBytes
      },
      'cleaned stale bridge media files on startup'
    );
  }
}

function storeMediaBuffer(buffer, mimeType, fileName, prefix) {
  if (!Buffer.isBuffer(buffer) || buffer.length === 0) return null;
  enforceStoredFileRetention();
  if (buffer.length > config.bridgeFileMaxBytes) {
    logger.warn(
      { bytes: buffer.length, max: config.bridgeFileMaxBytes },
      'incoming media skipped because it exceeds configured size limit'
    );
    return null;
  }

  const fileId = `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
  const localPath = path.join(config.filesDir, `${fileId}.bin`);
  fs.writeFileSync(localPath, buffer);
  const metadata = {
    fileId,
    fileName,
    mimeType,
    fileSize: buffer.length,
    localPath,
    createdAtMs: Date.now()
  };
  storedFiles.set(fileId, metadata);
  storedFileOrder.push(fileId);
  while (storedFileOrder.length > config.bridgeApiMaxQueueSize) {
    const victim = storedFileOrder.shift();
    if (victim) evictStoredFile(victim);
  }
  enforceStoredFileRetention();
  return metadata;
}

function pushUpdate(messagePayload) {
  const update = {
    update_id: nextUpdateId,
    message: messagePayload
  };
  nextUpdateId += 1;

  updateQueue.push(update);
  while (updateQueue.length > config.bridgeApiMaxQueueSize) {
    updateQueue.shift();
  }

  for (let i = updateWaiters.length - 1; i >= 0; i -= 1) {
    const waiter = updateWaiters[i];
    if (update.update_id >= waiter.offset) {
      updateWaiters.splice(i, 1);
      waiter.resolve();
    }
  }
}

function collectUpdates(offset, limit) {
  return updateQueue.filter((entry) => entry.update_id >= offset).slice(0, limit);
}

function waitForUpdates(offset, timeoutMs) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      const index = updateWaiters.findIndex((entry) => entry.resolve === resolve);
      if (index >= 0) updateWaiters.splice(index, 1);
      resolve();
    }, timeoutMs);
    updateWaiters.push({
      offset,
      resolve: () => {
        clearTimeout(timer);
        resolve();
      }
    });
  });
}

async function downloadIncomingMedia(sock, msg) {
  try {
    const buffer = await downloadMediaMessage(
      msg,
      'buffer',
      {},
      {
        logger,
        reuploadRequest: sock.updateMediaMessage
      }
    );
    if (!Buffer.isBuffer(buffer)) return null;
    return buffer;
  } catch (err) {
    logger.warn({ err: String(err) }, 'failed to download incoming media');
    return null;
  }
}

async function buildIncomingMessagePayload(sock, msg, chatJid) {
  const chatId = getOrCreateChatId(chatJid);
  const isGroup = chatJid.endsWith('@g.us');
  const payload = {
    message_id: nextMessageId(),
    chat: {
      id: chatId,
      type: isGroup ? 'group' : 'private'
    }
  };
  const sender = msg.key?.participant || msg.pushName || msg.key?.remoteJid || '';
  if (sender) payload.from = { username: String(sender) };

  const text = extractPlainTextFromBaileysMessage(msg);
  if (text) payload.text = text;

  const message = extractNormalizedMessageContent(msg);
  const replyToMessage = extractReplyContextFromBaileysMessage(msg);
  if (replyToMessage) {
    payload.reply_to_message = replyToMessage;
  }

  if (message.imageMessage) {
    const buffer = await downloadIncomingMedia(sock, msg);
    if (buffer) {
      const mimeType = message.imageMessage.mimetype || 'image/jpeg';
      const metadata = storeMediaBuffer(
        buffer,
        mimeType,
        `image-${payload.message_id}.jpg`,
        'img'
      );
      if (metadata) {
        payload.photo = [
          { file_id: metadata.fileId, file_size: metadata.fileSize, mime_type: metadata.mimeType }
        ];
      }
    }
    const caption = String(message.imageMessage.caption || '').trim();
    if (caption) {
      payload.caption = caption;
    }
  }

  if (message.audioMessage) {
    const buffer = await downloadIncomingMedia(sock, msg);
    if (buffer) {
      const mimeType = message.audioMessage.mimetype || 'audio/ogg';
      const metadata = storeMediaBuffer(
        buffer,
        mimeType,
        `audio-${payload.message_id}.ogg`,
        message.audioMessage.ptt ? 'voice' : 'audio'
      );
      if (metadata) {
        if (message.audioMessage.ptt) {
          payload.voice = {
            file_id: metadata.fileId,
            file_size: metadata.fileSize,
            mime_type: metadata.mimeType
          };
        } else {
          payload.document = {
            file_id: metadata.fileId,
            file_name: metadata.fileName,
            file_size: metadata.fileSize,
            mime_type: metadata.mimeType
          };
        }
      }
    }
  }

  if (message.documentMessage) {
    const buffer = await downloadIncomingMedia(sock, msg);
    if (buffer) {
      const mimeType = message.documentMessage.mimetype || 'application/octet-stream';
      const fileName = message.documentMessage.fileName || `document-${payload.message_id}.bin`;
      const metadata = storeMediaBuffer(buffer, mimeType, fileName, 'doc');
      if (metadata) {
        payload.document = {
          file_id: metadata.fileId,
          file_name: metadata.fileName,
          file_size: metadata.fileSize,
          mime_type: metadata.mimeType
        };
      }
    }
    const caption = String(message.documentMessage.caption || '').trim();
    if (caption) {
      payload.caption = caption;
    }
  }

  if (payload.caption && !payload.text && !payload.photo && !payload.voice && !payload.document) {
    payload.text = payload.caption;
  }

  if (!payload.text && !payload.photo && !payload.voice && !payload.document) {
    return null;
  }
  return payload;
}

async function enqueueIncomingUpdate(sock, msg, chatJid) {
  const payload = await buildIncomingMessagePayload(sock, msg, chatJid);
  if (!payload) return;
  pushUpdate(payload);
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body)
  });
  res.end(body);
}

async function parseJsonBody(req, maxBytes = 1024 * 1024) {
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += buffer.length;
    if (total > maxBytes) {
      throw createHttpError('request_too_large', 'request_too_large');
    }
    chunks.push(buffer);
  }
  if (chunks.length === 0) return {};
  const raw = Buffer.concat(chunks).toString('utf-8');
  if (!raw.trim()) return {};
  try {
    return JSON.parse(raw);
  } catch {
    throw createHttpError('invalid_json', 'invalid_json');
  }
}

function isAuthorized(req) {
  if (!config.bridgeApiAuthToken) return true;
  const auth = String(req.headers.authorization || '');
  return auth === `Bearer ${config.bridgeApiAuthToken}`;
}

function requireSocket(res) {
  if (!activeSock) {
    sendJson(res, 503, { ok: false, description: 'whatsapp socket is not ready' });
    return false;
  }
  return true;
}

async function handleApiRequest(req, res) {
  if (!isAuthorized(req)) {
    sendJson(res, 401, { ok: false, description: 'unauthorized' });
    return;
  }

  const host = req.headers.host || `${config.bridgeApiHost}:${config.bridgeApiPort}`;
  const url = new URL(req.url || '/', `http://${host}`);
  const { pathname } = url;
  const method = String(req.method || 'GET').toUpperCase();

  if (method === 'GET' && pathname === '/health') {
    sendJson(res, 200, { ok: true, result: { ready: Boolean(activeSock) } });
    return;
  }

  if (method === 'GET' && pathname === '/updates') {
    const offset = parseInteger(url.searchParams.get('offset'), 0, 0);
    const requestedTimeout = parseInteger(url.searchParams.get('timeout'), 0, 0);
    const timeoutSeconds = Math.min(requestedTimeout, config.bridgeApiMaxLongPollSeconds);
    const limit = config.bridgeApiMaxUpdatesPerPoll;
    let result = collectUpdates(offset, limit);
    if (result.length === 0 && timeoutSeconds > 0) {
      await waitForUpdates(offset, timeoutSeconds * 1000);
      result = collectUpdates(offset, limit);
    }
    sendJson(res, 200, { ok: true, result });
    return;
  }

  if (method === 'GET' && pathname === '/files/meta') {
    enforceStoredFileRetention();
    const fileId = String(url.searchParams.get('file_id') || '').trim();
    if (!fileId) {
      sendJson(res, 400, { ok: false, description: 'file_id is required' });
      return;
    }
    const metadata = storedFiles.get(fileId);
    if (!metadata) {
      sendJson(res, 404, { ok: false, description: 'file not found' });
      return;
    }
    sendJson(res, 200, {
      ok: true,
      result: {
        file_path: metadata.fileId,
        file_size: metadata.fileSize,
        mime_type: metadata.mimeType,
        file_name: metadata.fileName
      }
    });
    return;
  }

  if (method === 'GET' && pathname === '/files/content') {
    enforceStoredFileRetention();
    const filePathToken = String(url.searchParams.get('file_path') || '').trim();
    if (!filePathToken) {
      sendJson(res, 400, { ok: false, description: 'file_path is required' });
      return;
    }
    const metadata = storedFiles.get(filePathToken);
    if (!metadata || !fs.existsSync(metadata.localPath)) {
      sendJson(res, 404, { ok: false, description: 'file content not found' });
      return;
    }
    res.writeHead(200, {
      'Content-Type': metadata.mimeType || 'application/octet-stream',
      'Content-Length': metadata.fileSize
    });
    const stream = fs.createReadStream(metadata.localPath);
    stream.pipe(res);
    stream.on('error', () => {
      if (!res.headersSent) {
        sendJson(res, 500, { ok: false, description: 'file stream failed' });
      } else {
        res.end();
      }
    });
    return;
  }

  if (method === 'POST' && pathname === '/messages') {
    if (!requireSocket(res)) return;
    const body = await parseJsonBody(req);
    const text = String(body.text || '').trim();
    const chatJid = resolveChatJid(body.chat_id, body.chat_jid);
    if (!chatJid) {
      sendJson(res, 404, { ok: false, description: 'chat not found' });
      return;
    }
    if (!text) {
      sendJson(res, 400, { ok: false, description: 'text is required' });
      return;
    }
    const response = await activeSock.sendMessage(chatJid, { text });
    const internalMessageId = nextMessageId();
    rememberOutboundMessageKey(internalMessageId, chatJid, response?.key?.id || null);
    sendJson(res, 200, {
      ok: true,
      result: {
        message_id: internalMessageId,
        wa_message_id: response?.key?.id || null
      }
    });
    return;
  }

  if (method === 'POST' && pathname === '/media') {
    if (!requireSocket(res)) return;
    const body = await parseJsonBody(req);
    const chatJid = resolveChatJid(body.chat_id, body.chat_jid);
    if (!chatJid) {
      sendJson(res, 404, { ok: false, description: 'chat not found' });
      return;
    }
    const mediaRef = String(body.media_ref || '').trim();
    if (!mediaRef) {
      sendJson(res, 400, { ok: false, description: 'media_ref is required' });
      return;
    }
    const mediaType = String(body.media_type || 'document').toLowerCase();
    if (!OUTBOUND_MEDIA_TYPES.has(mediaType)) {
      sendJson(res, 400, { ok: false, description: 'media_type must be one of: photo,audio,voice,document' });
      return;
    }
    const caption = typeof body.caption === 'string' && body.caption.trim() ? body.caption.trim() : undefined;

    let mediaSource;
    try {
      mediaSource = resolveOutboundMediaRef(mediaRef);
    } catch (err) {
      if (String(err) === 'Error: media_file_too_large') {
        sendJson(res, 413, { ok: false, description: `media file too large (> ${config.bridgeFileMaxBytes} bytes)` });
        return;
      }
      sendJson(res, 400, { ok: false, description: 'media_ref must be an existing local file path or http(s) URL' });
      return;
    }

    let payload;
    let followUpCaption;
    if (mediaType === 'photo') {
      payload = { image: mediaSource.value };
      if (mediaSource.mimeType) payload.mimetype = mediaSource.mimeType;
      if (caption) payload.caption = caption;
    } else if (mediaType === 'audio') {
      payload = { audio: mediaSource.value };
      if (mediaSource.mimeType) payload.mimetype = mediaSource.mimeType;
      if (caption) payload.caption = caption;
    } else if (mediaType === 'voice') {
      payload = { audio: mediaSource.value, ptt: true };
      if (mediaSource.mimeType) payload.mimetype = mediaSource.mimeType;
      // Voice-note captions are not reliably supported; send follow-up text instead.
      if (caption) followUpCaption = caption;
    } else {
      payload = {
        document: mediaSource.value,
        fileName: mediaSource.fileName || 'upload.bin'
      };
      if (mediaSource.mimeType) payload.mimetype = mediaSource.mimeType;
      if (caption) payload.caption = caption;
    }

    let response;
    try {
      response = await activeSock.sendMessage(chatJid, payload);
      if (followUpCaption) {
        await activeSock.sendMessage(chatJid, { text: followUpCaption });
      }
    } catch (err) {
      logger.warn({ err: String(err), chatJid, mediaType }, 'failed sending outbound media');
      sendJson(res, 502, { ok: false, description: 'failed sending outbound media' });
      return;
    }
    const internalMessageId = nextMessageId();
    rememberOutboundMessageKey(internalMessageId, chatJid, response?.key?.id || null);
    sendJson(res, 200, {
      ok: true,
      result: {
        message_id: internalMessageId,
        wa_message_id: response?.key?.id || null,
        voice_caption_followup_sent: Boolean(followUpCaption)
      }
    });
    return;
  }

  if (method === 'POST' && pathname === '/messages/edit') {
    if (!requireSocket(res)) return;
    const body = await parseJsonBody(req);
    const chatJid = resolveChatJid(body.chat_id, body.chat_jid);
    if (!chatJid) {
      sendJson(res, 404, { ok: false, description: 'chat not found' });
      return;
    }
    const text = String(body.text || '').trim();
    if (!text) {
      sendJson(res, 400, { ok: false, description: 'text is required' });
      return;
    }
    const internalMessageId = parseInteger(body.message_id, NaN, 1);
    if (!Number.isFinite(internalMessageId) || Number.isNaN(internalMessageId)) {
      sendJson(res, 400, { ok: false, description: 'message_id is required' });
      return;
    }

    const mapped = outboundMessageKeys.get(internalMessageId);
    if (mapped && mapped.chatJid && mapped.chatJid !== chatJid) {
      logger.warn(
        { requestedChatJid: chatJid, mappedChatJid: mapped.chatJid, messageId: internalMessageId },
        'message edit chat mismatch; using mapped chat id'
      );
    }
    const effectiveChatJid = mapped?.chatJid || chatJid;
    const target = {
      remoteJid: effectiveChatJid,
      fromMe: true,
      id: mapped?.waMessageId || ''
    };

    if (!target.id) {
      sendJson(res, 409, {
        ok: false,
        description: 'message edit target not found'
      });
      return;
    }

    try {
      const edited = await activeSock.sendMessage(effectiveChatJid, { text, edit: target });
      if (edited?.key?.id) {
        rememberOutboundMessageKey(internalMessageId, effectiveChatJid, edited.key.id);
      }
      sendJson(res, 200, {
        ok: true,
        result: {
          edited: true,
          message_id: internalMessageId,
          wa_message_id: edited?.key?.id || target.id
        }
      });
    } catch (err) {
      logger.warn({ chatJid: effectiveChatJid, messageId: internalMessageId, err: String(err) }, 'message edit failed');
      sendJson(res, 502, {
        ok: false,
        description: 'message edit failed'
      });
    }
    return;
  }

  if (method === 'POST' && pathname === '/chat-action') {
    const body = await parseJsonBody(req);
    const chatJid = resolveChatJid(body.chat_id, body.chat_jid);
    if (!chatJid) {
      sendJson(res, 404, { ok: false, description: 'chat not found' });
      return;
    }
    // WhatsApp does not provide Telegram-equivalent chat actions through this bridge.
    sendJson(res, 200, { ok: true, result: { accepted: false } });
    return;
  }

  sendJson(res, 404, { ok: false, description: 'endpoint not found' });
}

function startApiServer() {
  if (apiServer) return;
  apiServer = createServer((req, res) => {
    handleApiRequest(req, res).catch((err) => {
      if (res.headersSent) {
        try {
          res.end();
        } catch {
          // Best-effort termination when response was already started.
        }
        return;
      }
      if (err?.code === 'invalid_json') {
        sendJson(res, 400, { ok: false, description: 'invalid_json' });
        return;
      }
      if (err?.code === 'request_too_large') {
        sendJson(res, 413, { ok: false, description: 'request_too_large' });
        return;
      }
      logger.error({ err: String(err) }, 'bridge API request failed');
      sendJson(res, 500, { ok: false, description: 'internal_error' });
    });
  });
  apiServer.listen(config.bridgeApiPort, config.bridgeApiHost, () => {
    logger.info(
      {
        host: config.bridgeApiHost,
        port: config.bridgeApiPort,
        authRequired: Boolean(config.bridgeApiAuthToken)
      },
      'whatsapp bridge API server listening'
    );
  });
}

async function handleIncoming(sock, msg) {
  const chatJid = msg.key?.remoteJid;
  if (!chatJid) return;
  const chatId = getOrCreateChatId(chatJid);

  const isGroup = chatJid.endsWith('@g.us');
  const text = extractTextFromBaileysMessage(msg);
  const fromMe = msg.key?.fromMe;
  const fromMeParticipant = msg.key?.participant;
  if (fromMe) {
    // Outbound messages generated by this linked bot session in groups commonly
    // have no participant; ignore them to prevent self-feedback loops.
    if (isGroup && !fromMeParticipant) {
      logger.debug({ chatJid }, 'ignored self-message: missing participant (likely bot-origin)');
      return;
    }
    const isLikelyBotEcho = Boolean(text) && /^\s*говорун\s*:/iu.test(text);
    if (isLikelyBotEcho) {
      logger.debug({ chatJid }, 'ignored self-message: bot echo prefix');
      return;
    }
    if (config.allowFromMeGroupTriggerOnly) {
      const hasTrigger = Boolean(text) && (
        config.selfTriggerRegex ? config.selfTriggerRegex.test(text) : config.triggerRegex.test(text)
      );
      const allowSelfTriggeredGroupMessage = isGroup && hasTrigger;
      if (!allowSelfTriggeredGroupMessage) {
        logger.debug(
          { chatJid, isGroup, hasText: Boolean(text) },
          'ignored self-message: group trigger required'
        );
        return;
      }
      logger.debug({ chatJid }, 'allowing trigger message from linked account (self-test mode)');
    } else {
      logger.debug({ chatJid }, 'allowing self-message (self-test unrestricted mode)');
    }
  }

  if (!shouldHandleChat(chatJid, isGroup, chatId)) {
    logger.debug({ chatJid, chatId }, 'ignored: not in allowed chat list');
    return;
  }

  if (config.pluginMode) {
    await enqueueIncomingUpdate(sock, msg, chatJid);
    return;
  }

  if (!text) return;

  let prompt = text;
  if (isGroup && config.groupTriggerRequired) {
    if (!config.triggerRegex.test(text)) {
      logger.debug({ chatJid, text }, 'ignored: trigger missing in group');
      return;
    }
    prompt = stripTrigger(text);
    if (!prompt) {
      logger.debug({ chatJid }, 'ignored: empty prompt after trigger removal');
      return;
    }
  } else if (!isGroup && !config.dmAlwaysRespond) {
    if (!config.triggerRegex.test(text)) {
      logger.debug({ chatJid, text }, 'ignored: trigger missing in dm');
      return;
    }
    prompt = stripTrigger(text);
  }

  const sender = msg.key?.participant || chatJid;
  enqueueByChat(chatJid, async () => {
    logger.info({ chatJid, isGroup, sender }, 'processing prompt');
    const preface = [
      'You are Govorun, replying in WhatsApp.',
      'Keep responses practical, concise, and directly useful.',
      'If the user asks for actions, list exact next steps clearly.',
      `Chat type: ${isGroup ? 'group' : 'dm'}.`,
      `Sender: ${sender}.`
    ].join(' ');

    const finalPrompt = `${preface}\n\nUser message:\n${prompt}`;
    const result = await runCodex(config, logger, finalPrompt);

    await sock.sendMessage(chatJid, { text: result.reply });
    logger.info({ chatJid, code: result.code }, 'sent response');
  });
}

async function start() {
  if (!storedFilesCleanupTimer) {
    storedFilesCleanupTimer = setInterval(() => {
      try {
        enforceStoredFileRetention();
      } catch (err) {
        logger.warn({ err: String(err) }, 'stored media cleanup tick failed');
      }
    }, STORED_FILES_CLEANUP_INTERVAL_MS);
    if (typeof storedFilesCleanupTimer.unref === 'function') {
      storedFilesCleanupTimer.unref();
    }
  }

  startApiServer();
  logger.info(
    {
      trigger: config.trigger,
      allowFromMeGroupTriggerOnly: config.allowFromMeGroupTriggerOnly,
      dmAlwaysRespond: config.dmAlwaysRespond,
      groupTriggerRequired: config.groupTriggerRequired,
      allowedChatIdsCount: config.allowedChatIds.length,
      pluginMode: config.pluginMode,
      model: config.codexModel,
      reasoningEffort: config.codexReasoningEffort,
      fullAccess: config.codexFullAccess
    },
    'starting whatsapp codex bridge'
  );

  let waVersion;
  try {
    const latest = await fetchLatestWaWebVersion();
    waVersion = latest.version;
    logger.info({ version: waVersion, isLatest: latest.isLatest }, 'using wa web version');
  } catch (err) {
    logger.warn({ err: String(err) }, 'failed to fetch latest wa web version, using default');
  }

  const { state, saveCreds } = await useMultiFileAuthState(config.authDir);
  const socketConfig = {
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger)
    },
    printQRInTerminal: false,
    browser: Browsers.macOS('Chrome'),
    logger
  };
  if (waVersion) socketConfig.version = waVersion;

  const sock = makeWASocket(socketConfig);
  const enqueueCredsSave = createQueuedCredsSaver(config.authDir, saveCreds, logger);

  sock.ev.on('creds.update', () => enqueueCredsSave());

  if (sock.ws && typeof sock.ws.on === 'function') {
    sock.ws.on('error', (err) => {
      logger.error({ err: String(err) }, 'bridge websocket error');
    });
  }

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect } = update;
    if (connection === 'open') {
      activeSock = sock;
      logger.info('whatsapp connection open');
      return;
    }
    if (connection === 'close') {
      if (activeSock === sock) activeSock = null;
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      logger.warn({ statusCode, shouldReconnect }, 'whatsapp connection closed');
      if (shouldReconnect) {
        setTimeout(start, 3000);
      }
    }
  });

  sock.ev.on('messages.upsert', async ({ messages }) => {
    for (const msg of messages) {
      await handleIncoming(sock, msg);
    }
  });
}

start().catch((err) => {
  logger.error({ err: String(err) }, 'fatal startup error');
  process.exit(1);
});
