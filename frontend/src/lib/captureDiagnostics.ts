/** Local development diagnostics. Never include device IDs, labels, or media. */
export function captureDiagnostic(stage: string, details: Record<string, string | number | boolean | undefined> = {}) {
  if (!import.meta.env.DEV) return
  try {
    import.meta.hot?.send('vinote:capture-diagnostic', {
      stage,
      time: new Date().toISOString(),
      ...details,
    })
  } catch {
    // Diagnostics must not affect recording.
  }
}

export function captureFailure(stage: string, error: unknown, startedAt: number) {
  captureDiagnostic(stage, {
    elapsedMs: Date.now() - startedAt,
    errorName: error instanceof Error ? error.name : 'UnknownError',
    errorMessage: error instanceof Error ? error.message : String(error),
  })
}

captureDiagnostic('diagnostics.ready')
