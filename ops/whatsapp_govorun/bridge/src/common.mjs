import fs from 'fs';
import os from 'os';
import path from 'path';

export function parseBool(value, defaultValue = false) {
  if (value === undefined || value === null || value === '') return defaultValue;
  return ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase());
}

export function splitCsv(value) {
  if (!value) return [];
  return value
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean);
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
  const codexWorkdir = process.env.CODEX_WORKDIR || '/home/architect/matrix';
  const trigger = process.env.WA_TRIGGER || '@govorun';
  const pairingPhone = String(process.env.WA_PAIRING_PHONE || '').replace(/[^\d]/g, '');
  const pairingCode = String(process.env.WA_PAIRING_CODE || '').trim();

  return {
    trigger,
    triggerRegex: new RegExp(`^\\s*${escapeRegex(trigger)}(?:\\b|\\s|[:,.-])`, 'iu'),
    dmAlwaysRespond: parseBool(process.env.WA_DM_ALWAYS_RESPOND, true),
    groupTriggerRequired: parseBool(process.env.WA_GROUP_TRIGGER_REQUIRED, true),
    allowedGroups: splitCsv(process.env.WA_ALLOWED_GROUPS),
    allowedDms: splitCsv(process.env.WA_ALLOWED_DMS),
    authDir,
    stateDir,
    logsDir,
    codexWorkdir,
    codexModel: process.env.CODEX_MODEL || 'gpt-5-codex-mini',
    codexReasoningEffort: process.env.CODEX_REASONING_EFFORT || 'medium',
    codexFullAccess: parseBool(process.env.CODEX_FULL_ACCESS, true),
    codexBinary: process.env.CODEX_BIN || 'codex',
    codexTimeoutMs: Number(process.env.CODEX_TIMEOUT_MS || 240000),
    responseMaxChars: Number(process.env.WA_RESPONSE_MAX_CHARS || 3500),
    pairingPhone,
    pairingCode
  };
}
