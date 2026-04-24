import { useState, useRef, useEffect } from 'react'

// Strip any residual thinking tags that slip through the backend parser
function stripThinking(text: string): string {
  return text
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .replace(/<\|think\|>[\s\S]*?<\/\|think\|>/gi, '')
    .replace(/<thinking>[\s\S]*?<\/thinking>/gi, '')
    .replace(/<think>[\s\S]*/gi, '')   // unclosed
    .trim()
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface Message {
  role: 'user' | 'assistant' | 'system'
  content: string
  thought?: string
}

interface PendingAction {
  command: string
  thought: string
  answer: string
}

interface ScenarioMeta {
  key: string
  name: string
  description: string
  icon: string
  difficulty: string
  learning: string
}

interface PodInfo {
  name: string
  status: string
  restarts: string
  ready: string
}

interface ClusterStatus {
  active: boolean
  scenario_key: string | null
  scenario_name: string | null
  elapsed_seconds: number
  events: string[]
  pods: PodInfo[]
}

interface PostMortem {
  elapsed: number
  approved: number
  rejected: number
  scenario: string
}

const API = 'http://127.0.0.1:8000'

function fmt(secs: number) {
  const m = Math.floor(secs / 60).toString().padStart(2, '0')
  const s = (secs % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

function diffBadge(d: string) {
  if (d === 'Beginner') return 'badge-green'
  if (d === 'Intermediate') return 'badge-yellow'
  return 'badge-red'
}

function podStatusColor(status: string) {
  if (status === 'Running') return '#10b981'
  if (status === 'Pending') return '#f59e0b'
  return '#ef4444'
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioMeta[]>([])
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [clusterStatus, setClusterStatus] = useState<ClusterStatus>({
    active: false, scenario_key: null, scenario_name: null,
    elapsed_seconds: 0, events: [], pods: [],
  })
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [loading, setLoading] = useState(false)
  const [postMortem, setPostMortem] = useState<PostMortem | null>(null)
  const [approvedCount, setApprovedCount] = useState(0)
  const [rejectedCount, setRejectedCount] = useState(0)

  const chatEndRef = useRef<HTMLDivElement>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  // Load scenarios once
  useEffect(() => {
    fetch(`${API}/api/scenarios`).then(r => r.json()).then(setScenarios).catch(() => {})
  }, [])

  // Poll cluster status every 3 s
  useEffect(() => {
    const poll = () => {
      fetch(`${API}/api/status`).then(r => r.json()).then((s: ClusterStatus) => {
        setClusterStatus(s)
        // If it was active and now cleaned up externally, reset
        if (!s.active && clusterStatus.active) setSelectedKey(null)
      }).catch(() => {})
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [clusterStatus.active])

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, pending, loading])
  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [clusterStatus.events])

  const injectChaos = async () => {
    if (!selectedKey) return
    try {
      const res = await fetch(`${API}/api/chaos/inject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario: selectedKey }),
      })
      if (!res.ok) { const d = await res.json(); alert(d.detail); return }
      const data = await res.json()

      const initMessages: Message[] = [
        { role: 'system', content: `🚨 Incident injected: ${data.scenario}. The agent is analyzing the situation...` }
      ]

      // If the backend returned an auto-briefing, add it as the agent's first message
      if (data.briefing?.answer) {
        initMessages.push({
          role: 'assistant',
          content: data.briefing.answer,
          thought: data.briefing.thought || undefined,
        })
      }

      setMessages(initMessages)
      setApprovedCount(0); setRejectedCount(0); setPostMortem(null)
    } catch (e) { alert('Cannot reach backend') }
  }

  const healCluster = async () => {
    try {
      const res = await fetch(`${API}/api/chaos/cleanup`, { method: 'POST' })
      if (!res.ok) { const d = await res.json(); alert(d.detail); return }
      setPostMortem({
        elapsed: clusterStatus.elapsed_seconds,
        approved: approvedCount,
        rejected: rejectedCount,
        scenario: clusterStatus.scenario_name ?? '',
      })
    } catch (e) { alert('Cannot reach backend') }
  }

  const sendMessage = async () => {
    if (!input.trim() || loading || pending) return
    const userMsg: Message = { role: 'user', content: input }
    const next = [...messages, userMsg]
    setMessages(next); setInput(''); setLoading(true)
    try {
      const history = next.filter(m => m.role !== 'system').map(m => ({ role: m.role, content: m.content }))
      const res = await fetch(`${API}/api/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history }),
      })
      const data = await res.json()
      if (data.type === 'action_required') {
        setPending({ ...data, answer: stripThinking(data.answer) })
      } else {
        setMessages(p => [...p, { role: 'assistant', content: stripThinking(data.answer), thought: data.thought }])
      }
    } catch (e) { console.error(e) } finally { setLoading(false) }
  }

  const handleAction = async (approved: boolean) => {
    if (!pending) return
    const action = pending; setPending(null); setLoading(true)
    if (approved) {
      setApprovedCount(c => c + 1)
      setMessages(p => [...p,
        { role: 'assistant', content: stripThinking(action.answer), thought: action.thought },
        { role: 'system', content: `$ ${action.command}` },
      ])
      try {
        const res = await fetch(`${API}/api/command/execute`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: action.command }),
        })
        const data = await res.json()
        const out = data.output || data.error || '(no output)'
        setMessages(p => [...p, { role: 'system', content: out }])
        const history = [
          ...messages,
          { role: 'assistant', content: action.answer },
          { role: 'user', content: `Command output:\n${out}` },
        ].filter(m => m.role !== 'system').map(m => ({ role: m.role, content: m.content }))
        const nextRes = await fetch(`${API}/api/chat`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ history }),
        })
        const nextData = await nextRes.json()
        if (nextData.type === 'action_required') {
          setPending({ ...nextData, answer: stripThinking(nextData.answer) })
        } else {
          setMessages(p => [...p, { role: 'assistant', content: stripThinking(nextData.answer), thought: nextData.thought }])
        }
      } catch (e) { console.error(e) }
    } else {
      setRejectedCount(c => c + 1)
      setMessages(p => [...p, { role: 'system', content: '⛔ Command rejected by student.' }])
    }
    setLoading(false)
  }

  const score = postMortem
    ? Math.max(0, 100 - Math.floor(postMortem.elapsed / 6) + postMortem.rejected * 5 - postMortem.approved * 2)
    : 0
  const grade = score >= 85 ? 'A' : score >= 70 ? 'B' : score >= 55 ? 'C' : 'D'

  return (
    <div className="app-shell">
      {/* ── HEADER ── */}
      <header className="topbar">
        <div className="topbar-brand">
          <span className="brand-icon">⚡</span>
          <span className="brand-name">Infrastructure Healer</span>
          <span className="brand-sub">Sandboxed Cloud Outage Simulator</span>
        </div>
        <div className="topbar-status">
          <span className={`pulse-dot ${clusterStatus.active ? 'pulse-red' : 'pulse-green'}`} />
          <span className={clusterStatus.active ? 'status-critical' : 'status-ok'}>
            {clusterStatus.active ? `🔴 ${clusterStatus.scenario_name} — ${fmt(clusterStatus.elapsed_seconds)}` : '🟢 Cluster Healthy'}
          </span>
        </div>
      </header>

      <div className="main-grid">
        {/* ── LEFT: SCENARIOS + METRICS ── */}
        <aside className="panel left-panel">
          <section className="panel-section">
            <h2 className="section-title">Chaos Scenarios</h2>
            <div className="scenario-list">
              {scenarios.map(s => (
                <button
                  key={s.key}
                  disabled={clusterStatus.active}
                  onClick={() => setSelectedKey(s.key)}
                  className={`scenario-card ${selectedKey === s.key ? 'scenario-card--selected' : ''} ${clusterStatus.active ? 'scenario-card--disabled' : ''}`}
                >
                  <span className="scenario-icon">{s.icon}</span>
                  <div className="scenario-info">
                    <span className="scenario-name">{s.name}</span>
                    <span className={`badge ${diffBadge(s.difficulty)}`}>{s.difficulty}</span>
                  </div>
                </button>
              ))}
            </div>
            {selectedKey && !clusterStatus.active && (
              <div className="selected-info">
                {(() => {
                  const s = scenarios.find(x => x.key === selectedKey)!
                  return s ? <p className="learning-obj">📚 {s.learning}</p> : null
                })()}
              </div>
            )}
            <div className="chaos-actions">
              <button
                className="btn btn-danger"
                disabled={!selectedKey || clusterStatus.active}
                onClick={injectChaos}
              >Inject Outage</button>
              <button
                className="btn btn-heal"
                disabled={!clusterStatus.active}
                onClick={healCluster}
              >Heal Cluster</button>
            </div>
          </section>

          {/* Pods table */}
          <section className="panel-section">
            <h2 className="section-title">Pod Status</h2>
            {clusterStatus.pods.length === 0 ? (
              <p className="muted">No chaos pods running.</p>
            ) : (
              <table className="pod-table">
                <thead><tr><th>Pod</th><th>Status</th><th>↩</th></tr></thead>
                <tbody>
                  {clusterStatus.pods.map(p => (
                    <tr key={p.name}>
                      <td className="pod-name">{p.name}</td>
                      <td><span className="pod-status" style={{ color: podStatusColor(p.status) }}>{p.status}</span></td>
                      <td className="pod-restarts">{p.restarts}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </aside>

        {/* ── CENTER: CHAT ── */}
        <main className="panel chat-panel">
          <div className="chat-header">
            <div className="agent-dot" />
            <span className="agent-name">Junior DevOps Agent</span>
            <span className="model-badge">gemma4:e2b · Ollama</span>
          </div>

          <div className="chat-messages">
            {messages.length === 0 && (
              <div className="chat-empty">
                <p>🖥️ System online.</p>
                <p>Select a scenario, inject an outage, then ask me to investigate.</p>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`msg-row ${m.role === 'user' ? 'msg-row--right' : 'msg-row--left'}`}>
                {m.thought && (
                  <div className="thought-bubble">
                    <span className="thought-label">🤔 Agent Thinking</span>
                    <p>{m.thought}</p>
                  </div>
                )}
                <div className={`msg-bubble ${
                  m.role === 'user' ? 'bubble-user' :
                  m.role === 'system' ? 'bubble-system' : 'bubble-agent'
                }`}>
                  {m.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="msg-row msg-row--left">
                <div className="typing-indicator">
                  <span /><span /><span />
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* HITL Confirmation Gate */}
          {pending && (
            <div className="hitl-gate">
              <div className="hitl-header">
                <span>⚠️</span>
                <h3>Agent Action Pending — Your Approval Required</h3>
              </div>
              {pending.thought && (
                <div className="hitl-thought">
                  <span className="hitl-label">Reasoning</span>
                  <p>{pending.thought}</p>
                </div>
              )}
              <div className="hitl-answer">
                <p>{pending.answer}</p>
              </div>
              <div className="hitl-command">
                <span className="cmd-prompt">$</span>
                <code>{pending.command}</code>
              </div>
              <div className="hitl-actions">
                <button className="btn btn-approve" onClick={() => handleAction(true)}>✅ Approve & Execute</button>
                <button className="btn btn-reject" onClick={() => handleAction(false)}>⛔ Reject</button>
              </div>
            </div>
          )}

          <form className="chat-input-row" onSubmit={e => { e.preventDefault(); sendMessage() }}>
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder={clusterStatus.active ? "Ask the agent to investigate..." : "Inject a scenario first..."}
              disabled={loading || !!pending}
              className="chat-input"
            />
            <button type="submit" disabled={loading || !!pending || !input.trim()} className="btn btn-send">Send</button>
          </form>
        </main>

        {/* ── RIGHT: EVENT LOG ── */}
        <aside className="panel right-panel">
          <section className="panel-section" style={{ height: '100%' }}>
            <h2 className="section-title">Event Log</h2>
            <div className="event-log">
              {clusterStatus.events.length === 0
                ? <p className="muted">Waiting for events...</p>
                : clusterStatus.events.map((e, i) => (
                    <div key={i} className="event-line">{e}</div>
                  ))}
              <div ref={logEndRef} />
            </div>
          </section>
        </aside>
      </div>

      {/* ── POST-MORTEM MODAL ── */}
      {postMortem && (
        <div className="modal-overlay" onClick={() => setPostMortem(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2 className="modal-title">📋 Post-Mortem Report</h2>
            <p className="modal-scenario">{postMortem.scenario}</p>
            <div className="score-ring">
              <span className="score-grade">{grade}</span>
              <span className="score-num">{Math.min(score, 100)}</span>
            </div>
            <div className="mortem-stats">
              <div className="mortem-stat">
                <span className="stat-label">Time to Resolve</span>
                <span className="stat-val">{fmt(postMortem.elapsed)}</span>
              </div>
              <div className="mortem-stat">
                <span className="stat-label">Commands Approved</span>
                <span className="stat-val green">{postMortem.approved}</span>
              </div>
              <div className="mortem-stat">
                <span className="stat-label">Commands Rejected</span>
                <span className="stat-val yellow">{postMortem.rejected}</span>
              </div>
            </div>
            <button className="btn btn-heal" onClick={() => { setPostMortem(null); setMessages([]) }}>
              New Incident
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
