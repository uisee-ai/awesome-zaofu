import { useEffect, useState } from 'react'

import { loadBundledCanLab, type BundledCanLab } from './app/load.ts'
import { CanLabWorkspace } from './ui/shared/index.tsx'

export interface AppProps {
  readonly fetcher?: typeof fetch
}

type AppState =
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly bundle: BundledCanLab }
  | { readonly status: 'failed'; readonly message: string }

export const App = ({ fetcher = globalThis.fetch }: AppProps) => {
  const [state, setState] = useState<AppState>({ status: 'loading' })

  useEffect(() => {
    let active = true
    void loadBundledCanLab(fetcher).then(
      (bundle) => {
        if (active) setState({ status: 'ready', bundle })
      },
      (error: unknown) => {
        if (active) {
          setState({
            status: 'failed',
            message: error instanceof Error ? error.message : String(error),
          })
        }
      },
    )
    return () => {
      active = false
    }
  }, [fetcher])

  if (state.status === 'loading') {
    return (
      <main className="can-lab-workspace">
        <section className="panel trace-panel" role="status">
          Loading bundled CAN Lab assets…
        </section>
      </main>
    )
  }

  if (state.status === 'failed') {
    return (
      <main className="can-lab-workspace">
        <section className="panel trace-panel error-state" role="alert">
          <h1>Unable to load the bundled CAN Lab assets</h1>
          <p>{state.message}</p>
          <p>This offline lab fails closed when its packaged fixtures disagree.</p>
        </section>
      </main>
    )
  }

  return <CanLabWorkspace {...state.bundle} />
}
