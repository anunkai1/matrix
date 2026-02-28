import fs from 'fs';
import os from 'os';
import path from 'path';
import { spawn } from 'child_process';

import { ensureDir } from './common.mjs';

function runProcess(command, args, options, timeoutMs) {
  return new Promise((resolve) => {
    const child = spawn(command, args, options);
    let stdout = '';
    let stderr = '';
    let finished = false;
    const timeout = setTimeout(() => {
      if (finished) return;
      finished = true;
      child.kill('SIGKILL');
      resolve({ code: 124, stdout, stderr: `${stderr}\ncodex timeout` });
    }, timeoutMs);

    const finalize = (payload) => {
      if (finished) return;
      finished = true;
      clearTimeout(timeout);
      resolve(payload);
    };

    child.stdout?.on('data', (d) => {
      stdout += String(d);
    });
    child.stderr?.on('data', (d) => {
      stderr += String(d);
    });
    child.on('error', (err) => {
      finalize({ code: 1, stdout, stderr: `${stderr}\n${String(err)}` });
    });
    child.on('close', (code) => {
      finalize({ code: code ?? 1, stdout, stderr });
    });
  });
}

export async function runCodex(config, logger, userPrompt) {
  const tempDir = path.join(config.stateDir, 'tmp');
  ensureDir(tempDir);
  const outFile = path.join(tempDir, `codex-last-${Date.now()}.txt`);

  const args = [
    'exec',
    '--skip-git-repo-check',
    '--model',
    config.codexModel,
    '-c',
    `model_reasoning_effort=\"${config.codexReasoningEffort}\"`,
    '--output-last-message',
    outFile
  ];

  if (config.codexFullAccess) {
    args.push('--dangerously-bypass-approvals-and-sandbox');
  }

  args.push(userPrompt);

  const env = {
    ...process.env,
    HOME: process.env.HOME || os.homedir()
  };

  const result = await runProcess(
    config.codexBinary,
    args,
    {
    cwd: config.codexWorkdir,
    env,
    stdio: ['ignore', 'pipe', 'pipe']
    },
    config.codexTimeoutMs
  );

  let reply = '';
  if (fs.existsSync(outFile)) {
    reply = fs.readFileSync(outFile, 'utf-8').trim();
    fs.rmSync(outFile, { force: true });
  }

  if (!reply && result.stdout) {
    reply = result.stdout.trim();
  }

  if (!reply) {
    reply = 'I could not generate a response right now.';
  }

  if (reply.length > config.responseMaxChars) {
    reply = reply.slice(0, config.responseMaxChars) + '...';
  }

  logger.info(
    {
      code: result.code,
      stdoutPreview: String(result.stdout || '').slice(0, 200),
      stderrPreview: String(result.stderr || '').slice(0, 200)
    },
    'codex exec finished'
  );

  return { reply, code: result.code };
}
