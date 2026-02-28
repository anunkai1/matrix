import fs from 'fs';
import path from 'path';
import { execSync } from 'child_process';

import makeWASocket, {
  Browsers,
  fetchLatestWaWebVersion,
  makeCacheableSignalKeyStore,
  useMultiFileAuthState
} from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import qrcodeTerminal from 'qrcode-terminal';

import { createConfig, ensureDir, readEnvFromFile } from './common.mjs';
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

function maskPhone(phone) {
  if (!phone) return '';
  if (phone.length <= 4) return '****';
  return `${'*'.repeat(phone.length - 4)}${phone.slice(-4)}`;
}

function writeQrHtml(qr) {
  const out = path.join(config.stateDir, 'qr-auth.html');
  return QRCode.toString(qr, { type: 'svg' }).then((svg) => {
    const html = `<!doctype html><html><body style="font-family:sans-serif"><h2>Scan with WhatsApp</h2>${svg}</body></html>`;
    fs.writeFileSync(out, html);
    return out;
  });
}

async function startAuth() {
  let waVersion;
  try {
    const latest = await fetchLatestWaWebVersion();
    waVersion = latest.version;
    logger.info({ version: waVersion, isLatest: latest.isLatest }, 'using wa web version for auth');
  } catch (err) {
    logger.warn({ err: String(err) }, 'failed to fetch latest wa web version for auth, using default');
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
  let pairingRequested = false;

  sock.ev.on('creds.update', saveCreds);

  if (!state.creds.registered && config.pairingPhone) {
    setTimeout(async () => {
      if (pairingRequested) return;
      pairingRequested = true;
      try {
        const code = await sock.requestPairingCode(config.pairingPhone, config.pairingCode || undefined);
        logger.info(
          { pairingPhone: maskPhone(config.pairingPhone), pairingCode: code },
          'pairing code generated'
        );
      } catch (err) {
        logger.error({ err: String(err) }, 'failed to generate pairing code');
      }
    }, 2500);
  }

  sock.ev.on('connection.update', async (update) => {
    if (update.qr) {
      logger.info('received qr code for whatsapp auth');
      const qrPath = await writeQrHtml(update.qr);
      let opened = false;
      try {
        execSync(`xdg-open ${JSON.stringify(qrPath)}`, { stdio: 'ignore' });
        opened = true;
      } catch {
        opened = false;
      }

      if (!opened) {
        qrcodeTerminal.generate(update.qr, { small: true });
        logger.info({ qrPath }, 'could not auto-open browser, QR printed in terminal');
      } else {
        logger.info({ qrPath }, 'QR opened in browser');
      }
    }

    if (update.connection === 'open') {
      logger.info('whatsapp auth successful');
      process.exit(0);
    }

    if (update.connection === 'close') {
      logger.warn('auth connection closed before success');
    }
  });
}

startAuth().catch((err) => {
  logger.error({ err: String(err) }, 'auth failed');
  process.exit(1);
});
