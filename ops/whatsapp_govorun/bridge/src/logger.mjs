import pino from 'pino';

export function createLogger() {
  const level = process.env.LOG_LEVEL || 'info';
  return pino({ level });
}
