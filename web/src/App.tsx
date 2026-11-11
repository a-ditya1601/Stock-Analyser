import { type FormEvent, useEffect, useRef, useState } from 'react'
import { motion, useInView, useReducedMotion } from 'framer-motion'
import './App.css'

type RiskProfile = 'defensive' | 'balanced' | 'aggressive'

type FadingVideoProps = {
  src: string
  className?: string
  style?: React.CSSProperties
}

type IconProps = {
  className?: string
}

const FALLBACK_RISK_PROFILES: RiskProfile[] = ['defensive', 'balanced', 'aggressive']
const DEFAULT_RISK_PROFILE: RiskProfile = 'balanced'
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')

const HERO_VIDEO =
  'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260418_080021_d598092b-c4c2-4e53-8e46-94cf9064cd50.mp4'

const FADE_MS = 500
const FADE_OUT_LEAD = 0.55

const riseIn = {
  hidden: { filter: 'blur(10px)', opacity: 0, y: 20 },
  visible: { filter: 'blur(0px)', opacity: 1, y: 0 },
}

const capabilities = [
  {
    title: 'Hybrid Quant Projections',
    body: 'Blend options IV expected moves, empirical return quantiles, ATR context, and support/resistance gravity wells into scenario ranges.',
    tags: ['IV Expected Move', 'Quantiles', 'S/R Gravity', 'POC/HVN'],
    icon: ChartIcon,
  },
  {
    title: 'Smart Money & Flow',
    body: 'Surface F&O context, PCR, rollover, max pain, OBV trend, relative volume, and volatility posture before a position is sized.',
    tags: ['F&O', 'PCR', 'Rollover', 'OBV Flow'],
    icon: FlowIcon,
  },
  {
    title: 'Relative Valuation',
    body: 'Compare the asset against a deterministic local peer universe and expose valuation, margin, and growth spreads in the final PDF.',
    tags: ['Peer Basket', 'Margins', 'Growth', 'PDF Ready'],
    icon: NetworkIcon,
  },
]

function App() {
  const [query, setQuery] = useState('')
  const [riskProfile, setRiskProfile] = useState<RiskProfile>(DEFAULT_RISK_PROFILE)
  const [riskProfiles, setRiskProfiles] = useState<RiskProfile[]>(FALLBACK_RISK_PROFILES)
  const [isGenerating, setIsGenerating] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    const abortController = new AbortController()

    async function loadRiskProfiles() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/meta/risk-profiles`, {
          signal: abortController.signal,
        })
        if (!response.ok) {
          return
        }

        const payload = (await response.json()) as {
          riskProfiles?: unknown
          defaultRiskProfile?: unknown
        }

        const profiles = toRiskProfiles(payload.riskProfiles)
        if (!profiles.length) {
          return
        }

        setRiskProfiles(profiles)
        const defaultFromApi = toRiskProfile(payload.defaultRiskProfile)
        setRiskProfile(defaultFromApi && profiles.includes(defaultFromApi) ? defaultFromApi : profiles[0])
      } catch {
        // Keep fallback profiles; dropdown remains usable even when metadata endpoint is unavailable.
      }
    }

    void loadRiskProfiles()
    return () => abortController.abort()
  }, [])

  async function handleGenerate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const cleanedQuery = query.trim()
    if (!cleanedQuery) {
      setErrorMessage('Please enter a company name or ticker symbol.')
      setStatusMessage(null)
      return
    }

    setIsGenerating(true)
    setErrorMessage(null)
    setStatusMessage('Generating report... this can take a minute while the model builds charts and tables.')

    try {
      const response = await fetch(`${API_BASE_URL}/api/reports/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: cleanedQuery,
          riskProfile,
        }),
      })

      if (!response.ok) {
        const detail = await parseErrorDetail(response)
        throw new Error(toFriendlyErrorMessage(response.status, detail))
      }

      const fileBlob = await response.blob()
      const filename =
        parseFilename(response.headers.get('Content-Disposition')) ||
        `${toFilenameSafe(cleanedQuery)}_Equity_Research_Report.pdf`

      triggerDownload(fileBlob, filename)
      setStatusMessage(`Success. Download started for ${filename}`)
      setErrorMessage(null)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to generate report right now.'
      setErrorMessage(message)
      setStatusMessage(null)
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <main className="site-shell">
      <FadingVideo
        src={HERO_VIDEO}
        className="site-background-video"
      />
      <HeroSection
        query={query}
        setQuery={setQuery}
        riskProfile={riskProfile}
        setRiskProfile={setRiskProfile}
        riskProfiles={riskProfiles}
        isGenerating={isGenerating}
        statusMessage={statusMessage}
        errorMessage={errorMessage}
        onGenerate={handleGenerate}
      />
      <CapabilitiesSection />
    </main>
  )
}

function HeroSection({
  query,
  setQuery,
  riskProfile,
  setRiskProfile,
  riskProfiles,
  isGenerating,
  statusMessage,
  errorMessage,
  onGenerate,
}: {
  query: string
  setQuery: (value: string) => void
  riskProfile: RiskProfile
  setRiskProfile: (value: RiskProfile) => void
  riskProfiles: RiskProfile[]
  isGenerating: boolean
  statusMessage: string | null
  errorMessage: string | null
  onGenerate: (event: FormEvent<HTMLFormElement>) => void
}) {
  return (
    <section className="hero-section" id="home">
      <div className="section-content hero-content-layer">
        <Navbar />
        <div className="hero-grid">
          <motion.div
            className="hero-copy"
            initial="hidden"
            animate="visible"
            transition={{ staggerChildren: 0.16 }}
          >
            <motion.div className="hero-badge liquid-glass" variants={riseIn} transition={{ duration: 0.7 }}>
              <span>New</span>
              <p>Hybrid Quant projections, F&O flow, and deterministic peer relativity</p>
            </motion.div>

            <BlurText text="Institutional-grade equity research in one click" />

            <motion.p className="hero-subtitle" variants={riseIn} transition={{ duration: 0.7, delay: 0.2 }}>
              Enter any company name or ticker and generate a professional PDF with fundamentals,
              technicals, volume flow, F&O smart-money context, peer valuation, and scenario projections.
            </motion.p>

            <motion.div className="hero-actions" variants={riseIn} transition={{ duration: 0.7, delay: 0.32 }}>
              <a className="primary-link liquid-glass-strong" href="#report-generator">
                Generate Research Report <ArrowUpRightIcon className="icon-sm" />
              </a>
              <a className="secondary-link" href="#capabilities">
                View Engine <PlayIcon className="icon-xs" />
              </a>
            </motion.div>

            <motion.div className="stats-row" variants={riseIn} transition={{ duration: 0.7, delay: 0.44 }}>
              <StatCard icon={<ClockIcon className="stat-icon" />} value="5 Pages" label="Institutional PDF Layout" />
              <StatCard icon={<GlobeIcon className="stat-icon" />} value="IN + US" label="Market Universe Coverage" />
            </motion.div>
          </motion.div>

          <motion.section
            id="report-generator"
            className="report-panel liquid-glass"
            aria-labelledby="report-form-title"
            initial={{ filter: 'blur(12px)', opacity: 0, y: 28 }}
            animate={{ filter: 'blur(0px)', opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.45, ease: 'easeOut' }}
          >
            <div className="panel-kicker">Research Terminal</div>
            <h2 id="report-form-title">Generate PDF Report</h2>
            <p className="panel-copy">The backend fetches live market data and returns a downloadable research PDF.</p>

            {errorMessage ? (
              <div className="status-banner error" role="alert">
                {errorMessage}
              </div>
            ) : null}

            {!errorMessage && statusMessage ? (
              <div className="status-banner success" role="status">
                {statusMessage}
              </div>
            ) : null}

            <form onSubmit={onGenerate} noValidate>
              <label className="field-label" htmlFor="companyQuery">
                Company / Ticker
              </label>
              <input
                id="companyQuery"
                className="field-input"
                placeholder="Apple, AAPL, RELIANCE.NS, MapmyIndia"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                disabled={isGenerating}
              />

              <label className="field-label" htmlFor="riskProfile">
                Risk Profile
              </label>
              <select
                id="riskProfile"
                className="field-input"
                value={riskProfile}
                onChange={(event) => setRiskProfile(toRiskProfile(event.target.value) || DEFAULT_RISK_PROFILE)}
                disabled={isGenerating}
              >
                {riskProfiles.map((profile) => (
                  <option key={profile} value={profile}>
                    {toDisplayRiskProfile(profile)}
                  </option>
                ))}
              </select>

              <button className="primary-btn liquid-glass-strong" type="submit" disabled={isGenerating}>
                {isGenerating ? 'Generating...' : 'Generate Report'}
                <ArrowUpRightIcon className="icon-sm" />
              </button>
            </form>

            <p className="meta-line">
              API route: <code>{API_BASE_URL || 'same-origin / dev proxy'}</code>
            </p>
          </motion.section>
        </div>

        <motion.div
          className="partner-strip"
          initial={{ opacity: 0, y: 16, filter: 'blur(10px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          transition={{ duration: 0.7, delay: 1.25, ease: 'easeOut' }}
        >
          <span className="liquid-glass">Built for disciplined investors, analysts, and curious market operators</span>
          <div className="partner-names" aria-label="Engine modules">
            <p>Fundamentals</p>
            <p>Technicals</p>
            <p>F&amp;O</p>
            <p>Peers</p>
            <p>Projections</p>
          </div>
        </motion.div>
        <div className="hero-transition-veil" aria-hidden="true" />
      </div>
    </section>
  )
}

function Navbar() {
  return (
    <motion.nav
      className="navbar"
      initial={{ opacity: 0, y: -18, filter: 'blur(10px)' }}
      animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      transition={{ duration: 0.75, ease: 'easeOut' }}
      aria-label="Primary navigation"
    >
      <a className="brand-mark liquid-glass" href="#home" aria-label="EquityScope home">
        e
      </a>
      <div className="nav-links liquid-glass">
        <a href="#home">Home</a>
        <a href="#report-generator">Report</a>
        <a href="#capabilities">Engine</a>
        <a href="#capabilities">Signals</a>
        <a href="#report-generator" className="nav-cta">
          Start Analysis <ArrowUpRightIcon className="icon-xs" />
        </a>
      </div>
      <div className="nav-spacer" aria-hidden="true" />
    </motion.nav>
  )
}

function CapabilitiesSection() {
  return (
    <section className="capabilities-section" id="capabilities">
      <div className="section-content capabilities-content">
        <motion.header
          className="capabilities-header"
          initial={{ opacity: 0, y: 42, scale: 0.985, filter: 'blur(16px)' }}
          whileInView={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
          viewport={{ once: true, amount: 0.25 }}
          transition={{ duration: 0.95, ease: 'easeOut' }}
        >
          <p>// Capabilities</p>
          <h2>
            Research
            <br /> evolved
          </h2>
        </motion.header>

        <div className="capability-grid">
          {capabilities.map((capability, index) => {
            const Icon = capability.icon
            return (
              <motion.article
                className="capability-card liquid-glass"
                key={capability.title}
                initial={{ opacity: 0, y: 26, filter: 'blur(12px)' }}
                whileInView={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                viewport={{ once: true, amount: 0.22 }}
                transition={{ duration: 0.7, delay: index * 0.12, ease: 'easeOut' }}
              >
                <div className="card-topline">
                  <div className="card-icon liquid-glass">
                    <Icon className="icon-md" />
                  </div>
                  <div className="card-tags">
                    {capability.tags.map((tag) => (
                      <span className="liquid-glass" key={tag}>
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="card-copy">
                  <h3>{capability.title}</h3>
                  <p>{capability.body}</p>
                </div>
              </motion.article>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function FadingVideo({ src, className = '', style }: FadingVideoProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const rafRef = useRef<number | null>(null)
  const fadingOutRef = useRef(false)

  useEffect(() => {
    const videoElement = videoRef.current
    if (!videoElement) {
      return undefined
    }
    const video = videoElement

    function cancelFade() {
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }

    function fadeTo(target: number, duration: number) {
      cancelFade()
      const startOpacity = Number.parseFloat(video.style.opacity || '0') || 0
      const startTime = performance.now()

      const step = (now: number) => {
        const progress = Math.min((now - startTime) / duration, 1)
        const eased = 1 - Math.pow(1 - progress, 3)
        video.style.opacity = String(startOpacity + (target - startOpacity) * eased)
        if (progress < 1) {
          rafRef.current = window.requestAnimationFrame(step)
        }
      }

      rafRef.current = window.requestAnimationFrame(step)
    }

    function playVideo() {
      const playPromise = video.play()
      if (playPromise && typeof playPromise.catch === 'function') {
        playPromise.catch(() => undefined)
      }
    }

    function handleLoadedData() {
      video.style.opacity = '0'
      playVideo()
      fadeTo(1, FADE_MS)
    }

    function handleTimeUpdate() {
      if (!Number.isFinite(video.duration) || video.duration <= 0) {
        return
      }
      const remaining = video.duration - video.currentTime
      if (!fadingOutRef.current && remaining <= FADE_OUT_LEAD && remaining > 0) {
        fadingOutRef.current = true
        fadeTo(0, FADE_MS)
      }
    }

    function handleEnded() {
      video.style.opacity = '0'
      window.setTimeout(() => {
        video.currentTime = 0
        fadingOutRef.current = false
        playVideo()
        fadeTo(1, FADE_MS)
      }, 100)
    }

    video.addEventListener('loadeddata', handleLoadedData)
    video.addEventListener('timeupdate', handleTimeUpdate)
    video.addEventListener('ended', handleEnded)

    return () => {
      cancelFade()
      video.removeEventListener('loadeddata', handleLoadedData)
      video.removeEventListener('timeupdate', handleTimeUpdate)
      video.removeEventListener('ended', handleEnded)
    }
  }, [src])

  return (
    <video
      ref={videoRef}
      className={`fading-video ${className}`}
      src={src}
      muted
      playsInline
      autoPlay
      preload="auto"
      style={{ opacity: 0, ...style }}
    />
  )
}

function BlurText({ text }: { text: string }) {
  const ref = useRef<HTMLParagraphElement | null>(null)
  const reducedMotion = useReducedMotion()
  const inView = useInView(ref, { once: true, amount: 0.1 })
  const words = text.split(' ')

  return (
    <p className="blur-headline" ref={ref}>
      {words.map((word, index) => (
        <motion.span
          key={`${word}-${index}`}
          initial={reducedMotion ? false : { filter: 'blur(10px)', opacity: 0, y: 50 }}
          animate={
            reducedMotion || inView
              ? { filter: 'blur(0px)', opacity: 1, y: 0 }
              : { filter: 'blur(10px)', opacity: 0, y: 50 }
          }
          transition={{
            duration: reducedMotion ? 0 : 0.7,
            delay: reducedMotion ? 0 : index * 0.1,
            times: [0, 0.5, 1],
            ease: 'easeOut',
          }}
        >
          {word}
        </motion.span>
      ))}
    </p>
  )
}

function StatCard({ icon, value, label }: { icon: React.ReactNode; value: string; label: string }) {
  return (
    <div className="stat-card liquid-glass">
      {icon}
      <p>{value}</p>
      <span>{label}</span>
    </div>
  )
}

function ArrowUpRightIcon({ className = '' }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M7 17L17 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M7 7h10v10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function PlayIcon({ className = '' }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M6 4l14 8-14 8V4Z" />
    </svg>
  )
}

function ClockIcon({ className = '' }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 7v5l3.5 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function GlobeIcon({ className = '' }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z" stroke="currentColor" strokeWidth="1.8" />
      <path d="M3 12h18M12 3c2.25 2.45 3.38 5.45 3.38 9S14.25 18.55 12 21M12 3c-2.25 2.45-3.38 5.45-3.38 9S9.75 18.55 12 21" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function ChartIcon({ className = '' }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 19V5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M4 19h16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M7 15l3-4 3 2 5-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M17 6h1v1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function FlowIcon({ className = '' }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 7h7a3 3 0 0 1 3 3v0a3 3 0 0 0 3 3h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M4 17h5a3 3 0 0 0 3-3v-4a3 3 0 0 1 3-3h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M18 5l2 2-2 2M18 11l2 2-2 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function NetworkIcon({ className = '' }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M7 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM17 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM17 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" stroke="currentColor" strokeWidth="1.7" />
      <path d="M9.6 6.5h4.8M8.8 8.4l6.4 7.2M15.2 8.4 8.8 15.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

function toRiskProfiles(value: unknown): RiskProfile[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter(isRiskProfile)
}

function toRiskProfile(value: unknown): RiskProfile | null {
  return isRiskProfile(value) ? value : null
}

function isRiskProfile(value: unknown): value is RiskProfile {
  return value === 'defensive' || value === 'balanced' || value === 'aggressive'
}

function toDisplayRiskProfile(profile: RiskProfile): string {
  return `${profile.slice(0, 1).toUpperCase()}${profile.slice(1)}`
}

function parseFilename(contentDisposition: string | null): string | null {
  if (!contentDisposition) {
    return null
  }

  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(contentDisposition)
  if (utf8Match?.[1]) {
    return decodeURIComponentSafe(utf8Match[1].trim())
  }

  const quotedMatch = /filename="([^"]+)"/i.exec(contentDisposition)
  if (quotedMatch?.[1]) {
    return quotedMatch[1].trim()
  }

  const plainMatch = /filename=([^;]+)/i.exec(contentDisposition)
  if (plainMatch?.[1]) {
    return plainMatch[1].trim()
  }

  return null
}

function decodeURIComponentSafe(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    const detail = payload?.detail

    if (typeof detail === 'string') {
      return detail
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: unknown }
      if (typeof first?.msg === 'string') {
        return first.msg
      }
    }
  } catch {
    // No JSON detail available.
  }
  return 'Unexpected API response.'
}

function toFriendlyErrorMessage(status: number, detail: string): string {
  if (status === 400 || status === 422) {
    return detail || 'Please check the company/ticker input and risk profile.'
  }
  if (status === 404) {
    return detail || 'Could not resolve this company/ticker from the market data source.'
  }
  if (status === 502) {
    return detail || 'Upstream market data provider returned an error. Please retry.'
  }
  if (status === 503) {
    return detail || 'Service is temporarily unavailable or timed out. Please retry shortly.'
  }
  if (status >= 500) {
    return 'Server error while generating the report. Please retry in a moment.'
  }
  return detail || `Request failed with status ${status}.`
}

function toFilenameSafe(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^_+|_+$/g, '') || 'report'
}

function triggerDownload(blob: Blob, filename: string) {
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(objectUrl)
}

export default App

