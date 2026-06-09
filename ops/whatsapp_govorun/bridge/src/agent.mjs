import { runCodex } from './codex.mjs';
import { runPi } from './pi.mjs';

// Single dispatch point for index.mjs. Routes to runCodex or runPi based on
// config.agentRuntime (env WA_AGENT_RUNTIME). Defaults to "codex" so the
// existing behavior is preserved out of the box.
//
// Both runtimes return { reply, code } so callers are runtime-agnostic.
export async function runAgent(config, logger, userPrompt) {
  const runtime = (config.agentRuntime || 'codex').toLowerCase();
  if (runtime === 'pi') {
    logger.info(
      {
        runtime: 'pi',
        provider: config.piProvider,
        model: config.piModel,
        thinking: config.piThinking,
        timeoutMs: config.piTimeoutMs
      },
      'agent runtime: pi'
    );
    return runPi(config, logger, userPrompt);
  }
  if (runtime === 'codex') {
    logger.info(
      {
        runtime: 'codex',
        model: config.codexModel,
        effort: config.codexReasoningEffort,
        timeoutMs: config.codexTimeoutMs
      },
      'agent runtime: codex'
    );
    return runCodex(config, logger, userPrompt);
  }
  // Unknown runtime: fail loud rather than silently falling back, so an
  // operator typo in WA_AGENT_RUNTIME is visible in the bridge log.
  throw new Error(
    `unknown WA_AGENT_RUNTIME='${runtime}'; expected 'codex' or 'pi'`
  );
}
