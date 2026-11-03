/**
 * The scanning flow: form, wait, result or failure. Tasks 8.2, 8.4, 8.8.
 *
 * Four states and nothing in between:
 *
 *   idle      the form, and whatever was last looked at
 *   scanning  the progress panel
 *   done      the report
 *   failed    the error notice
 *
 * **The previous result stays on screen while a new scan runs.** Replacing it
 * with a spinner throws away something the person may still be reading, and
 * if the new scan fails they are left with nothing where they used to have a
 * report.
 *
 * **A 401 mid-session is handled specially.** It means the code stopped being
 * accepted -- it was changed, or the backend restarted with a different one.
 * The stored code is dropped so the gate asks again, which is the only honest
 * thing to do: carrying on would show a form that cannot work.
 */

import { useCallback, useRef, useState } from 'react'
import { scanUrl } from '../api/client'
import type { ApiFailure } from '../api/client'
import type { Report } from '../api/types'
import { forgetCode } from '../access/storage'
import ReportView from '../report/ReportView'
import ErrorNotice from './ErrorNotice'
import ScanForm from './ScanForm'
import ScanProgress from './ScanProgress'
import { prepare } from './urlInput'

type Phase = 'idle' | 'scanning' | 'done' | 'failed'

interface Props {
  /** Shown before the first scan. The saved demo, in practice. */
  initialReport?: Report
  initialReportIsHandWritten?: boolean
}

export default function ScanPanel({
  initialReport,
  initialReportIsHandWritten = false,
}: Props) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [report, setReport] = useState<Report | null>(initialReport ?? null)
  const [showingDemo, setShowingDemo] = useState(initialReport !== undefined)
  const [failure, setFailure] = useState<ApiFailure | null>(null)
  const [scanning, setScanning] = useState('')
  const inFlight = useRef<AbortController | null>(null)

  const run = useCallback(async (raw: string) => {
    const url = prepare(raw)
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller

    setScanning(url)
    setPhase('scanning')
    setFailure(null)

    let result
    try {
      result = await scanUrl(url, { signal: controller.signal })
    } catch {
      // The only rejection is our own cancellation, and the handler that
      // cancelled has already set whatever state it wanted.
      return
    }
    if (controller.signal.aborted) return

    if (result.ok) {
      setReport(result.data)
      setShowingDemo(false)
      setPhase('done')
      return
    }

    if (result.error.code === 'unauthorized') {
      // The gate will ask again on the next load. Done before the state is
      // set, so a reload at any point after this lands on the code screen.
      forgetCode()
    }

    setFailure(result.error)
    setPhase('failed')
  }, [])

  const cancel = useCallback(() => {
    inFlight.current?.abort()
    inFlight.current = null
    setPhase(report === null ? 'idle' : 'done')
  }, [report])

  return (
    <div className="flex flex-col gap-6">
      <ScanForm onScan={run} busy={phase === 'scanning'} />

      {phase === 'scanning' && <ScanProgress url={scanning} onCancel={cancel} />}

      {phase === 'failed' && failure !== null && (
        <>
          <ErrorNotice
            failure={failure}
            onRetry={scanning ? () => void run(scanning) : undefined}
          />
          {failure.code === 'unauthorized' && (
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-paper"
            >
              Enter the access code again
            </button>
          )}
        </>
      )}

      {report !== null && phase !== 'scanning' && (
        <ReportView
          report={report}
          explanationsAreHandWritten={showingDemo && initialReportIsHandWritten}
        />
      )}
    </div>
  )
}
