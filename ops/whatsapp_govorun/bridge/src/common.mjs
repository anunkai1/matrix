import fs from 'fs';
import os from 'os';
import path from 'path';

export function parseBool(value, defaultValue = false) {
  if (value === undefined || value === null || value === '') return defaultValue;
  return ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase());
}

export function parseInteger(value, defaultValue, minimum = 0) {
  if (value === undefined || value === null || value === '') return defaultValue;
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed) || Number.isNaN(parsed)) return defaultValue;
  if (parsed < minimum) return minimum;
  return parsed;
}

export function splitCsv(value) {
  if (!value) return [];
  return value
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean);
}

export function parseIntegerCsv(value, minimum = 1) {
  const parsed = [];
  const seen = new Set();
  for (const raw of splitCsv(value)) {
    const next = Number.parseInt(raw, 10);
    if (!Number.isFinite(next) || Number.isNaN(next) || next < minimum) continue;
    if (seen.has(next)) continue;
    seen.add(next);
    parsed.push(next);
  }
  return parsed;
}

export function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

export function readEnvFromFile(filePath) {
  const env = {};
  if (!fs.existsSync(filePath)) return env;
  const lines = fs.readFileSync(filePath, 'utf-8').split(/\r?\n/);
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    env[key] = value;
  }
  return env;
}

function getMessageText(message) {
  if (!message) return '';
  if (message.conversation) return message.conversation;
  if (message.extendedTextMessage?.text) return message.extendedTextMessage.text;
  if (message.imageMessage?.caption) return message.imageMessage.caption;
  if (message.videoMessage?.caption) return message.videoMessage.caption;
  if (message.documentMessage?.caption) return message.documentMessage.caption;
  return '';
}

export function extractTextFromBaileysMessage(msg) {
  return getMessageText(msg?.message).trim();
}

export function createConfig() {
  const home = process.env.HOME || os.homedir();
  const stateDir = process.env.WA_STATE_DIR || path.join(home, 'whatsapp-govorun', 'state');
  const authDir = process.env.WA_AUTH_DIR || path.join(stateDir, 'auth');
  const logsDir = process.env.WA_LOGS_DIR || path.join(stateDir, 'logs');
  const filesDir = process.env.WA_FILES_DIR || path.join(stateDir, 'files');
  const codexWorkdir = process.env.CODEX_WORKDIR || '/home/architect/matrix';
  const trigger = process.env.WA_TRIGGER || '@говорун';
  const trimmedTrigger = trigger.trim();
  const triggerCore = trimmedTrigger.startsWith('@') ? trimmedTrigger.slice(1).trim() : trimmedTrigger;
  const escapedTriggerCore = escapeRegex(triggerCore || trimmedTrigger);
  const leadingNoiseClass = '[\\s\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069\\ufeff]*';
  const pairingPhone = String(process.env.WA_PAIRING_PHONE || '').replace(/[^\d]/g, '');
  const pairingCode = String(process.env.WA_PAIRING_CODE || '').trim();

  return {
    trigger,
    // Accept trigger with optional leading '@' and followed by end-of-message,
    // whitespace, or common punctuation.
    triggerRegex: new RegExp(
      `^${leadingNoiseClass}@?${escapedTriggerCore}(?:$|\\b|\\s|[,:;.!?\\-])`,
      'iu'
    ),
    // Stricter summon regex for self-messages (no colon/semicolon) to avoid
    // bot reply echoes like "Говорун: ..." being re-consumed as new prompts.
    selfTriggerRegex: new RegExp(
      `^${leadingNoiseClass}@?${escapedTriggerCore}(?:$|\\b|\\s|[,.!?\\-])`,
      'iu'
    ),
    // Match trigger anywhere in text as a standalone token (used for tolerant self-message checks).
    triggerSearchRegex: new RegExp(`(?:^|\\s|[(:;,.!?\\-])@?${escapedTriggerCore}(?:$|\\b|\\s|[,:;.!?\\-)])`, 'iu'),
    allowFromMeGroupTriggerOnly: parseBool(process.env.WA_ALLOW_FROM_ME_GROUP_TRIGGER_ONLY, true),
    dmAlwaysRespond: parseBool(process.env.WA_DM_ALWAYS_RESPOND, true),
    groupTriggerRequired: parseBool(process.env.WA_GROUP_TRIGGER_REQUIRED, true),
    allowedChatIds: parseIntegerCsv(process.env.WA_ALLOWED_CHAT_IDS, 1),
    allowedGroups: splitCsv(process.env.WA_ALLOWED_GROUPS),
    allowedDms: splitCsv(process.env.WA_ALLOWED_DMS),
    authDir,
    stateDir,
    logsDir,
    filesDir,
    codexWorkdir,
    codexModel: process.env.CODEX_MODEL || 'gpt-5-codex-mini',
    codexReasoningEffort: process.env.CODEX_REASONING_EFFORT || 'medium',
    codexFullAccess: parseBool(process.env.CODEX_FULL_ACCESS, true),
    codexBinary: process.env.CODEX_BIN || 'codex',
    codexTimeoutMs: parseInteger(process.env.CODEX_TIMEOUT_MS, 240000, 1000),
    responseMaxChars: parseInteger(process.env.WA_RESPONSE_MAX_CHARS, 3500, 200),
    pluginMode: parseBool(process.env.WA_PLUGIN_MODE, false),
    bridgeApiHost: process.env.WA_API_HOST || '127.0.0.1',
    bridgeApiPort: parseInteger(process.env.WA_API_PORT, 8787, 1),
    bridgeApiAuthToken: String(process.env.WA_API_AUTH_TOKEN || '').trim(),
    bridgeApiMaxUpdatesPerPoll: parseInteger(process.env.WA_API_MAX_UPDATES_PER_POLL, 100, 1),
    bridgeApiMaxQueueSize: parseInteger(process.env.WA_API_MAX_QUEUE_SIZE, 2000, 10),
    bridgeApiMaxLongPollSeconds: parseInteger(process.env.WA_API_MAX_LONG_POLL_SECONDS, 30, 1),
    bridgeFileMaxBytes: parseInteger(process.env.WA_FILE_MAX_BYTES, 50 * 1024 * 1024, 1024),
    pairingPhone,
    pairingCode
  };
}

export function createQueuedCredsSaver(authDir, saveCreds, logger) {
  let queue = Promise.resolve();
  const credsPath = path.join(authDir, 'creds.json');
  const backupPath = path.join(authDir, 'creds.backup.json');

  return function enqueueCredsSave() {
    queue = queue
      .then(async () => {
        try {
          if (fs.existsSync(credsPath)) {
            const raw = fs.readFileSync(credsPath, 'utf-8');
            try {
              JSON.parse(raw);
              fs.copyFileSync(credsPath, backupPath);
              try {
                fs.chmodSync(backupPath, 0o600);
              } catch {
                // Best-effort permission tightening.
              }
            } catch {
              // Keep prior backup if current creds file is malformed.
            }
          }
        } catch {
          // Backup is best-effort.
        }

        try {
          await Promise.resolve(saveCreds());
          try {
            fs.chmodSync(credsPath, 0o600);
          } catch {
            // Best-effort permission tightening.
          }
        } catch (err) {
          logger?.warn?.({ err: String(err) }, 'failed saving whatsapp creds');
        }
      })
      .catch((err) => {
        logger?.warn?.({ err: String(err) }, 'whatsapp creds save queue error');
      });
  };
}
