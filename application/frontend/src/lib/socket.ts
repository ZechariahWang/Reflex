const BASE_MS = 500
const MAX_MS = 5000

/** Exponential reconnect delay with jitter: ~0.5 s, 1 s, 2 s, 4 s, then 5 s. */
export function backoffDelay(attempt: number): number {
  const ceiling = Math.min(MAX_MS, BASE_MS * 2 ** attempt)
  return ceiling * (0.75 + Math.random() * 0.25)
}

/**
 * Detach every handler and close. A socket that is still connecting is closed
 * once it opens, which avoids the browser's "closed before the connection is
 * established" console error (React strict mode mounts effects twice in dev).
 */
export function closeQuietly(socket: WebSocket): void {
  socket.onmessage = null
  socket.onclose = null
  socket.onerror = null
  if (socket.readyState === WebSocket.CONNECTING) {
    socket.onopen = () => socket.close()
  } else {
    socket.onopen = null
    socket.close()
  }
}
