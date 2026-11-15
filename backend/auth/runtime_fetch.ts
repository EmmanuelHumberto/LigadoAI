export function assertRuntimeAuthenticationConfigured(): void {
  const mode = process.env.OPENTRACY_RUNTIME_SECURITY ?? ''
  if (mode !== '' && mode !== 'required') throw new Error('Unknown runtime security mode')
  if (mode === 'required' && (process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN?.trim().length ?? 0) < 32) {
    throw new Error('Runtime authentication is not configured')
  }
}

/** Internal credentials are attached only to the configured runtime origin. */
export function createRuntimeFetch(transport: typeof fetch = fetch): typeof fetch {
  return async (input, init) => {
    const destination = new URL(input instanceof Request ? input.url : String(input))
    const runtime = new URL(process.env.RUNTIME_URL ?? 'http://127.0.0.1:8001')
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined))
    headers.delete('x-opentracy-runtime-key')
    if (destination.origin === runtime.origin) {
      const token = process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN?.trim()
      if (!token && process.env.OPENTRACY_RUNTIME_SECURITY === 'required') {
        throw new Error('Runtime authentication is not configured')
      }
      if (token) headers.set('x-opentracy-runtime-key', token)
    }
    return transport(input, { ...init, headers, ...(destination.origin === runtime.origin ? { redirect: 'error' } : {}) })
  }
}
export const runtimeFetch: typeof fetch = (input, init) => createRuntimeFetch()(input, init)
