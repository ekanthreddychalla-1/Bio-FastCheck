
import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  CircleAlert,
  Database,
  Dna,
  FileUp,
  FlaskConical,
  Mail,
  RefreshCw,
  ShieldCheck,
  UploadCloud,
  X
} from 'lucide-react'

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || ''
).replace(/\/$/, '')

function formatDate(value) {
  if (!value) return '—'

  const date = new Date(value)

  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString()
}

// Extract only safe, useful information from an S3 XML error.
async function getS3Error(response) {
  const xml = await response.text()

  try {
    const document = new DOMParser().parseFromString(
      xml,
      'application/xml'
    )

    const code = document.querySelector('Code')?.textContent
    const message = document.querySelector('Message')?.textContent

    if (code || message) {
      return `S3 upload failed (${response.status}): ${
        code || 'UnknownError'
      }${message ? ` — ${message}` : ''}`
    }
  } catch {
    // Use the generic message below if the response is not XML.
  }

  return `S3 upload failed (${response.status}). Check the S3 request details.`
}

export default function App() {
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [results, setResults] = useState([])
  const [loadingResults, setLoadingResults] = useState(false)
  const [dragging, setDragging] = useState(false)

  const validFile = file && /\.(fasta|fa|fna)$/i.test(file.name)
  const latest = useMemo(() => results[0], [results])

  async function loadResults() {
    if (!API_BASE) {
      setError('Set VITE_API_BASE_URL in your .env file first.')
      return
    }

    setLoadingResults(true)

    try {
      const response = await fetch(`${API_BASE}/results`)
      const data = await response.json()

      if (!response.ok) {
        throw new Error(
          data.message || `Results request failed (${response.status})`
        )
      }

      setResults(Array.isArray(data.items) ? data.items : [])
      setError('')
    } catch (e) {
      setError(
        `${e.message}. Check the API URL, CORS and Lambda permissions.`
      )
    } finally {
      setLoadingResults(false)
    }
  }

  useEffect(() => {
    if (API_BASE) loadResults()
  }, [])

  async function uploadFile() {
    setError('')
    setMessage('')

    if (!API_BASE) {
      setError('Set VITE_API_BASE_URL in your .env file.')
      return
    }

    if (!file) {
      setError('Choose a FASTA file first.')
      return
    }

    if (!validFile) {
      setError('Choose a .fasta, .fa or .fna file.')
      return
    }

    setBusy(true)

    try {
      // Step 1: Ask API Gateway for a presigned S3 PUT URL.
      const urlResponse = await fetch(`${API_BASE}/upload-url`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          fileName: file.name,
          contentType: 'text/plain'
        })
      })

      const urlData = await urlResponse.json()

      if (!urlResponse.ok) {
        throw new Error(
          urlData.message ||
          `Could not prepare upload (${urlResponse.status})`
        )
      }

      if (!urlData.uploadUrl || !urlData.key) {
        throw new Error(
          'The API did not return an upload URL and object key.'
        )
      }

      // Step 2: Upload directly to S3 using HTTP PUT.
      // The Content-Type must match the value used when signing the URL.
      const putResponse = await fetch(urlData.uploadUrl, {
        method: 'PUT',
        headers: {
          'Content-Type': 'text/plain'
        },
        body: file
      })

      if (!putResponse.ok) {
        throw new Error(await getS3Error(putResponse))
      }

      // Step 3: Tell the user that S3 accepted the upload.
      setMessage(
        `Uploaded ${urlData.key}. AWS is processing your file. ` +
        'Wait a few seconds, then refresh results.'
      )

      setFile(null)

      const input = document.getElementById('fasta-input')
      if (input) input.value = ''

      // Refresh shortly after successful upload.
      window.setTimeout(() => {
        loadResults()
      }, 3000)
    } catch (e) {
      setError(e.message || 'Upload failed. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const stats = [
    {
      label: 'Results found',
      value: results.length,
      icon: Database
    },
    {
      label: 'Latest sequence length',
      value: latest?.Sequence_Length ?? '—',
      icon: Dna
    },
    {
      label: 'Latest GC content',
      value:
        latest?.GC_Content != null
          ? `${latest.GC_Content}%`
          : '—',
      icon: Activity
    }
  ]

  function handleDrop(event) {
    event.preventDefault()
    setDragging(false)

    const droppedFile = event.dataTransfer.files?.[0]

    if (droppedFile) {
      setFile(droppedFile)
      setError('')
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#">
          <span className="brand-mark">
            <Dna size={22} />
          </span>
          <span>
            Bio<span className="brand-accent">-FastCheck</span>
          </span>
        </a>

        <div className="topbar-right">
          <span className="live-dot" />
          <span>AWS pipeline dashboard</span>
          <span className="region">eu-north-1</span>
        </div>
      </header>

      <main className="container">
        <section className="hero">
          <div className="hero-copy">
            <div className="eyebrow">
              <span className="eyebrow-line" />
              GENOMIC DATA · CLOUD AUTOMATION
            </div>

            <h1>
              From FASTA file
              <br />
              <span>to insights.</span>
            </h1>

            <p>
              Upload a sequence and let your AWS pipeline analyze
              base composition, calculate GC content, store results,
              and email an analysis report.
            </p>

            <div className="hero-tags">
              <span>
                <ShieldCheck size={15} />
                Server-side processing
              </span>
              <span>
                <Activity size={15} />
                Event-driven workflow
              </span>
            </div>
          </div>

          <div className="hero-art" aria-hidden="true">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />

            <div className="dna-card">
              <Dna size={100} strokeWidth={1.1} />
              <span>DNA</span>
            </div>

            <div className="floating-chip chip-top">
              <CheckCircle2 size={16} />
              S3 event detected
            </div>

            <div className="floating-chip chip-bottom">
              <Database size={16} />
              Results persisted
            </div>
          </div>
        </section>

        <section className="status-strip">
          <div className="status-label">
            <span className="live-dot" />
            PIPELINE COMPONENTS
          </div>

          <div className="status-items">
            <span><span className="status-check">✓</span> Amazon S3</span>
            <ArrowUpRight size={14} />
            <span><span className="status-check">✓</span> AWS Lambda</span>
            <ArrowUpRight size={14} />
            <span><span className="status-check">✓</span> DynamoDB</span>
            <ArrowUpRight size={14} />
            <span><span className="status-check">✓</span> Amazon SNS</span>
          </div>
        </section>

        <div className="section-heading">
          <div>
            <div className="eyebrow">WORKSPACE</div>
            <h2>Sequence analysis</h2>
          </div>

          <div className="region-pill">
            <span className="live-dot" />
            Stockholm region
          </div>
        </div>

        <section className="workspace-grid">
          <div className="panel upload-panel">
            <div className="panel-title">
              <div className="panel-icon">
                <UploadCloud size={20} />
              </div>
              <div>
                <h3>Upload a FASTA file</h3>
                <p>Start a new cloud analysis job</p>
              </div>
            </div>

            <label
              className={`dropzone ${dragging ? 'dragging' : ''}`}
              htmlFor="fasta-input"
              onDragOver={event => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
            >
              <div className="upload-circle">
                <FileUp size={25} />
              </div>

              <strong>
                {file ? file.name : 'Drop your sequence file here'}
              </strong>

              <span>
                {file
                  ? `${(file.size / 1024).toFixed(2)} KB · ready to upload`
                  : 'or click to browse from your computer'}
              </span>

              <span className="file-types">FASTA · FA · FNA</span>

              <input
                id="fasta-input"
                type="file"
                accept=".fasta,.fa,.fna,text/plain"
                onChange={event => {
                  setFile(event.target.files?.[0] || null)
                  setError('')
                }}
              />
            </label>

            <div className="upload-actions">
              <span className="secure-note">
                <ShieldCheck size={15} />
                Temporary secure upload URL
              </span>

              <button
                className="primary-btn"
                disabled={busy || !file || !validFile}
                onClick={uploadFile}
              >
                {busy ? (
                  <>
                    <RefreshCw className="spin" size={16} />
                    Uploading…
                  </>
                ) : (
                  <>
                    <UploadCloud size={16} />
                    Upload & analyze
                  </>
                )}
              </button>
            </div>

            {message && (
              <div className="notice success">
                <CheckCircle2 size={17} />
                <span>{message}</span>
                <button
                  aria-label="Dismiss"
                  onClick={() => setMessage('')}
                >
                  <X size={15} />
                </button>
              </div>
            )}

            {error && (
              <div className="notice error">
                <CircleAlert size={17} />
                <span>{error}</span>
                <button
                  aria-label="Dismiss"
                  onClick={() => setError('')}
                >
                  <X size={15} />
                </button>
              </div>
            )}

            <div className="privacy-note">
              <ShieldCheck size={17} />
              <span>
                Files go directly to S3 using a time-limited URL.
                Never put AWS access keys in this website.
              </span>
            </div>
          </div>

          <div className="panel pipeline-panel">
            <div className="panel-title">
              <div className="panel-icon purple">
                <FlaskConical size={20} />
              </div>
              <div>
                <h3>How the pipeline works</h3>
                <p>Automated after every upload</p>
              </div>
            </div>

            <div className="pipeline-list">
              <div className="pipeline-step">
                <div className="step-icon blue">
                  <UploadCloud size={17} />
                </div>
                <div>
                  <strong>01 · Ingest</strong>
                  <span>FASTA object saved in Amazon S3</span>
                </div>
                <span className="step-state">READY</span>
              </div>

              <div className="step-connector" />

              <div className="pipeline-step">
                <div className="step-icon violet">
                  <Activity size={17} />
                </div>
                <div>
                  <strong>02 · Analyze</strong>
                  <span>Lambda quality-gates the file, scans for primers and calculates metrics</span>
                </div>
                <span className="step-state">AUTO</span>
              </div>

              <div className="step-connector" />

              <div className="pipeline-step">
                <div className="step-icon green">
                  <Database size={17} />
                </div>
                <div>
                  <strong>03 · Store</strong>
                  <span>DynamoDB keeps the structured report</span>
                </div>
                <span className="step-state">AUTO</span>
              </div>

              <div className="step-connector" />

              <div className="pipeline-step">
                <div className="step-icon amber">
                  <Mail size={17} />
                </div>
                <div>
                  <strong>04 · Notify</strong>
                  <span>SNS sends the report to your subscribed email</span>
                </div>
                <span className="step-state">AUTO</span>
              </div>
            </div>

            <div className="pipeline-footer">
              <span className="live-dot" />
              Event-driven · no manual processing
            </div>
          </div>
        </section>

        <section className="results-section">
          <div className="section-heading results-heading">
            <div>
              <div className="eyebrow">DATABASE</div>
              <h2>Recent analysis results</h2>
              <p>Live records from your DynamoDB table</p>
            </div>

            <button
              className="secondary-btn"
              onClick={loadResults}
              disabled={loadingResults}
            >
              <RefreshCw
                size={16}
                className={loadingResults ? 'spin' : ''}
              />
              {loadingResults ? 'Refreshing…' : 'Refresh results'}
            </button>
          </div>

          <div className="stats-grid">
            {stats.map(({ label, value, icon: Icon }) => (
              <div className="stat-card" key={label}>
                <div className="stat-icon">
                  <Icon size={18} />
                </div>
                <div>
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              </div>
            ))}
          </div>

          <div className="panel table-panel">
            {results.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">
                  <Database size={26} />
                </div>
                <strong>No results loaded yet</strong>
                <span>
                  Click refresh to load results. After uploading,
                  allow a few seconds for Lambda to finish.
                </span>
              </div>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Source file</th>
                      <th>Length</th>
                      <th>GC content</th>
                      <th>Base composition</th>
                      <th>Status</th>
                      <th>Processed at</th>
                    </tr>
                  </thead>

                  <tbody>
                    {results.map((r, i) => (
                      <tr key={r.FileID || `${r.SourceFile}-${i}`}>
                        <td>
                          <div className="file-cell">
                            <span className="file-mini">
                              <Dna size={15} />
                            </span>
                            <span>
  {(r.SourceFile || '—').split('/').pop().replace(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-/i, '')}
</span>
                          </div>
                          <small>{r.FileID || ''}</small>
                        </td>

                        <td>{r.Sequence_Length ?? '—'}</td>

                        <td>
                          {r.GC_Content != null
                            ? `${r.GC_Content}%`
                            : '—'}
                        </td>

                        <td>
                          <span className="base-composition">
                            A {r.Base_A ?? 0} · T {r.Base_T ?? 0} ·
                            {' '}C {r.Base_C ?? 0} · G {r.Base_G ?? 0}
                          </span>
                        </td>

                        <td>
                          <span
                            className={`status-badge ${
                              (r.Status || '').toLowerCase()
                            }`}
                          >
                            {r.Status || 'UNKNOWN'}
                          </span>
                          {Array.isArray(r.Flags) && r.Flags.length > 0 && (
                            <small className="flag-line">
                              {r.Flags.join(', ')}
                            </small>
                          )}
                          {r.Primer_Hits &&
                            Object.keys(r.Primer_Hits).length > 0 && (
                              <small className="flag-line primer">
                                Primer:{' '}
                                {Object.entries(r.Primer_Hits)
                                  .map(([k, v]) => `${k} ×${v}`)
                                  .join(', ')}
                              </small>
                            )}
                        </td>

                        <td>{formatDate(r.Timestamp)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>

        <footer>
          <div className="footer-brand">
            <Dna size={17} />
            Bio-FastCheck
          </div>
          <span>
            Cloud-based genomic sequence analytics · Demo application
          </span>
          <span>Built on AWS</span>
        </footer>
      </main>
    </div>
  )
}
