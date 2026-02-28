import fs from 'fs';
import path from 'path';

import makeWASocket, {
  Browsers,
  DisconnectReason,
  fetchLatestWaWebVersion,
  makeCacheableSignalKeyStore,
  useMultiFileAuthState
} from '@whiskeysockets/baileys';

import { runCodex } from './codex.mjs';
import {
  createConfig,
  ensureDir,
  extractTextFromBaileysMessage,
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

const logger = createLogger();
const perChatQueue = new Map();

function shouldHandleChat(jid, isGroup) {
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

async function handleIncoming(sock, msg) {
  const chatJid = msg.key?.remoteJid;
  if (!chatJid) return;

  const isGroup = chatJid.endsWith('@g.us');
  const fromMe = msg.key?.fromMe;
  if (fromMe) return;

  if (!shouldHandleChat(chatJid, isGroup)) {
    logger.debug({ chatJid }, 'ignored: not in allowed chat list');
    return;
  }

  const text = extractTextFromBaileysMessage(msg);
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
  logger.info(
    {
      trigger: config.trigger,
      dmAlwaysRespond: config.dmAlwaysRespond,
      groupTriggerRequired: config.groupTriggerRequired,
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

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect } = update;
    if (connection === 'open') {
      logger.info('whatsapp connection open');
      return;
    }
    if (connection === 'close') {
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
