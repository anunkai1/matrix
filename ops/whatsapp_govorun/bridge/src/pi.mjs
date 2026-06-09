import os from 'os';
import { spawn } from 'child_process';

function runProcess(command, args, options, timeoutMs) {
  return new Promise((resolve) => {
    const child = spawn(command, args, options);
    let stdout = '';
    let stderr = '';
    let finished = false;
    const timeout = setTimeout(() => {
      if (finished) return;
      finished = true;
      try { child.kill('SIGKILL'); } catch {}
      resolve({ code: 124, stdout, stderr: `${stderr}\npi timeout` });
    }, timeoutMs);

    const finalize = (payload) => {
      if (finished) return;
      finished = true;
      clearTimeout(timeout);
      resolve(payload);
    };

    child.stdout?.on('data', (d) => { stdout += String(d); });
    child.stderr?.on('data', (d) => { stderr += String(d); });
    child.on('error', (err) => {
      finalize({ code: 1, stdout, stderr: `${stderr}\n${String(err)}` });
    });
    child.on('close', (code) => {
      finalize({ code: code ?? 1, stdout, stderr });
    });
  });
}

// v1: --print mode (simple, blocking, matches runCodex's spawn-and-wait shape).
// Returns { reply, code } so the call site in index.mjs doesn't have to know
// whether it ran codex or pi. v2 (PI_RPC_MODE=true) can add streaming later.
export async function runPi(config, logger, userPrompt) {
  const args = [
    '--provider', config.piProvider,
    '--model', config.piModel,
    '--thinking', config.piThinking,
    '--no-session',
    '--mode', 'text',
    '--print',
    userPrompt
  ];

  const env = {
    ...process.env,
    HOME: process.env.HOME || os.homedir()
  };

  const result = await runProcess(
    config.piBinary,
    args,
    {
      cwd: config.piWorkdir,
      env,
      stdio: ['ignore', 'pipe', 'pipe']
    },
    config.piTimeoutMs
  );

  let reply = String(result.stdout || '').trim();

  if (!reply) {
    reply = 'I could not generate a response right now.';
  }

  if (reply.length > config.responseMaxChars) {
    reply = reply.slice(0, config.responseMaxChars) + '...';
  }

  logger.info(
    {
      runtime: 'pi',
      provider: config.piProvider,
      model: config.piModel,
      thinking: config.piThinking,
      code: result.code,
      stdoutPreview: String(result.stdout || '').slice(0, 200),
      stderrPreview: String(result.stderr || '').slice(0, 200)
    },
    'pi exec finished'
  );

  return { reply, code: result.code };
}
