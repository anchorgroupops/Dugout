/**
 * fetch wrapper with exponential-backoff retry for transient server errors.
 * Retries only on network errors and 5xx responses (not 4xx).
 */
export async function fetchWithBackoff(url, options = {}, maxRetries = 3) {
  let lastError;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetch(url, options);
      if (res.ok || res.status < 500) return res;
      throw new Error(`HTTP ${res.status}`);
    } catch (err) {
      lastError = err;
      if (attempt < maxRetries) {
        await new Promise(r => setTimeout(r, 500 * 2 ** attempt));
      }
    }
  }
  throw lastError;
}
