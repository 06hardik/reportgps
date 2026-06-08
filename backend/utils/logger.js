const LOG_LEVELS = { info: '\u2139\ufe0f ', error: '\u274c ', warn: '\u26a0\ufe0f ' };

export function logInfo(message, data = null) {
  const timestamp = new Date().toISOString();
  if (data) {
    console.log(`${LOG_LEVELS.info}[${timestamp}] ${message}`, data);
  } else {
    console.log(`${LOG_LEVELS.info}[${timestamp}] ${message}`);
  }
}

export function logError(message, error = null) {
  const timestamp = new Date().toISOString();
  if (error) {
    console.error(`${LOG_LEVELS.error}[${timestamp}] ${message}`, error?.message || error);
  } else {
    console.error(`${LOG_LEVELS.error}[${timestamp}] ${message}`);
  }
}

export function logWarn(message, data = null) {
  const timestamp = new Date().toISOString();
  if (data) {
    console.warn(`${LOG_LEVELS.warn}[${timestamp}] ${message}`, data);
  } else {
    console.warn(`${LOG_LEVELS.warn}[${timestamp}] ${message}`);
  }
}
