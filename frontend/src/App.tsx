import { useState, useRef, useEffect } from 'react'

function stripThinking(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>/gi, '').replace(/<\|think\|>[\s\S]*?<\/\|think\|>/gi, '').replace(/<thinking>[\s\S]*?<\/thinking>/gi, '').replace(/<think>[\s\S]*/gi, '').trim()
}

// ─── Types ────────────────────────────────────────────────────────────────────
interface Message { role: 'user' | 'assistant' | 'system', content: string }
interface ScenarioMeta { key: string, name: string, description: string, icon: string, difficulty: string, learning: string }
interface PodInfo { name: string, status: string, restarts: string, ready: string }
interface ClusterStatus { active: boolean, scenario_key: string | null, scenario_name: string | null, elapsed_seconds: number, events: string[], pods: PodInfo[] }
interface PostMortem { elapsed: number, commandsRun: number, scenario: string }
interface TerminalEntry { cmd: string, output: string, isError: boolean }

const API = 'http://127.0.0.1:8000'

function fmt(secs: number) {
  const m = Math.floor(secs / 60).toString().padStart(2, '0')
  const s = (secs % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

function diffBadge(d: string) { return d === 'Beginner' ? 'badge-green' : d === 'Intermediate' ? 'badge-yellow' : 'badge-red' }
function podStatusColor(status: string) { return status === 'Running' ? '#10b981' : status === 'Pending' ? '#f59e0b' : '#ef4444' }

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioMeta[]>([])
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [clusterStatus, setClusterStatus] = useState<ClusterStatus>({ active: false, scenario_key: null, scenario_name: null, elapsed_seconds: 0, events: [], pods: [] })

  // Chat State
  const [messages, setMessages] = useState<Message[]>([])
  const [chatInput, setChatInput] = useState('')
  const [loadingChat, setLoadingChat] = useState(false)

  // Terminal State
  const [terminalHistory, setTerminalHistory] = useState<TerminalEntry[]>([])
  const [terminalInput, setTerminalInput] = useState('')
  const [loadingTerminal, setLoadingTerminal] = useState(false)
  const [commandsRunCount, setCommandsRunCount] = useState(0)

  const [postMortem, setPostMortem] = useState<PostMortem | null>(null)

  const chatEndRef = useRef<HTMLDivElement>(null)
  const terminalEndRef = useRef<HTMLDivElement>(null)

  // Polling & Setup
  useEffect(() => { fetch(`${API}/api/scenarios`).then(r => r.json()).then(setScenarios).catch(() => { }) }, [])
  useEffect(() => {
    const poll = () => {
      fetch(`${API}/api/status`).then(r => r.json()).then((s: ClusterStatus) => {
        setClusterStatus(s); if (!s.active && clusterStatus.active) setSelectedKey(null)
      }).catch(() => { })
    }
    poll(); const id = setInterval(poll, 3000); return () => clearInterval(id)
  }, [clusterStatus.active])

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loadingChat])
  useEffect(() => { terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [terminalHistory, loadingTerminal])

  // Actions
  const injectChaos = async () => {
    if (!selectedKey) return
    try {
      const res = await fetch(`${API}/api/chaos/inject`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenario: selectedKey }) })
      const data = await res.json()
      if (!res.ok) { alert(data.detail); return }

      setTerminalHistory([{ cmd: 'System initialized.', output: `Loaded scenario: ${data.scenario}`, isError: false }])
      setCommandsRunCount(0)

      const initMessages: Message[] = []
      if (data.briefing) initMessages.push({ role: 'assistant', content: stripThinking(data.briefing.answer) })
      setMessages(initMessages)
      setPostMortem(null)
    } catch (e) { alert('Cannot reach backend') }
  }

  const healCluster = async () => {
    try {
      await fetch(`${API}/api/chaos/cleanup`, { method: 'POST' })
      setPostMortem({ elapsed: clusterStatus.elapsed_seconds, commandsRun: commandsRunCount, scenario: clusterStatus.scenario_name ?? '' })
    } catch (e) { alert('Cannot reach backend') }
  }

  // --- TERMINAL LOGIC ---
  const submitTerminal = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!terminalInput.trim() || loadingTerminal) return
    const cmd = terminalInput.trim()
    setTerminalInput('')

    if (cmd.toLowerCase() === 'clear') { setTerminalHistory([]); return }

    setCommandsRunCount(c => c + 1)
    const newEntryIndex = terminalHistory.length
    setTerminalHistory(p => [...p, { cmd, output: 'Executing...', isError: false }])
    setLoadingTerminal(true)

    try {
      const res = await fetch(`${API}/api/command/execute`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: cmd })
      })
      const data = await res.json()
      setTerminalHistory(p => {
        const copy = [...p];
        copy[newEntryIndex].output = data.output || data.error || '(no output)';
        copy[newEntryIndex].isError = !!data.error || data.returncode !== 0;
        return copy;
      })
    } catch (e) {
      setTerminalHistory(p => { const copy = [...p]; copy[newEntryIndex].output = 'Connection Error.'; copy[newEntryIndex].isError = true; return copy; })
    } finally { setLoadingTerminal(false) }
  }

  // --- CHAT LOGIC ---
  const sendChat = async (overrideMsg?: string) => {
    const text = overrideMsg || chatInput
    if (!text.trim() || loadingChat) return
    setChatInput(''); setLoadingChat(true)

    const nextMessages = [...messages, { role: 'user', content: text } as Message]
    setMessages(nextMessages)

    // Compile recent terminal context for the AI
    const recentTerminal = terminalHistory.slice(-5).map(t => `$ ${t.cmd}\n${t.output}`).join('\n\n')

    try {
      const res = await fetch(`${API}/api/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: nextMessages, terminal_history: recentTerminal }),
      })
      const data = await res.json()
      setMessages(p => [...p, { role: 'assistant', content: stripThinking(data.answer) }])
    } catch (e) {
      setMessages(p => [...p, { role: 'assistant', content: `(Connection Error) I can't reach the server right now.` }])
    } finally { setLoadingChat(false) }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-brand">
          <span className="brand-icon">⚡</span>
          <span className="brand-name">KubeQuest: Infra Simulator</span>
        </div>
        <div className="topbar-status">
          <span className={`pulse-dot ${clusterStatus.active ? 'pulse-red' : 'pulse-green'}`} />
          <span className={clusterStatus.active ? 'status-critical' : 'status-ok'}>
            {clusterStatus.active ? `🔴 Incident Active — ${fmt(clusterStatus.elapsed_seconds)}` : '🟢 System Healthy'}
          </span>
        </div>
      </header>

      <div className="main-grid split-layout">

        {/* ── LEFT: GAME CONTROL ── */}
        <aside className="panel left-panel">
          <section className="panel-section">
            <h2 className="section-title">Select Level</h2>
            <div className="scenario-list">
              {scenarios.map(s => (
                <button
                  key={s.key} disabled={clusterStatus.active} onClick={() => setSelectedKey(s.key)}
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
            <div className="chaos-actions" style={{ marginTop: '1rem' }}>
              <button className="btn btn-danger" disabled={!selectedKey || clusterStatus.active} onClick={injectChaos}>▶ Start Simulator</button>
              <button className="btn btn-heal" disabled={!clusterStatus.active} onClick={healCluster}>🏁 Finish Level</button>
            </div>
          </section>

          <section className="panel-section" style={{ flexGrow: 1 }}>
            <h2 className="section-title">Live Pods Dashboard</h2>
            {clusterStatus.pods.length === 0 ? <p className="muted">No workloads running.</p> : (
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

        {/* ── CENTER RIGHT: Split Interaction Zone ── */}
        <div className="interaction-column">

          {/* TOP: CHAT WITH MENTOR */}
          <main className="panel game-chat-panel">
            <div className="panel-header">
              <h3>👩‍🏫 Mentor Chat</h3>
              <div className="quick-actions">
                <button className="btn-hint" onClick={() => sendChat("I'm stuck. Can you give me a hint on what command to run next?")}>💡 Get Hint</button>
              </div>
            </div>
            <div className="chat-bubbles">
              {messages.length === 0 && (
                <div className="chat-empty">
                  <p>Welcome to the simulator! Select a level on the left to begin.</p>
                </div>
              )}
              {messages.map((msg, idx) => (
                <div key={idx} className={`chat-bubble-wrapper ${msg.role === 'user' ? 'student' : 'mentor'}`}>
                  <div className="bubble">{msg.content}</div>
                </div>
              ))}
              {loadingChat && <div className="chat-bubble-wrapper mentor"><div className="bubble typing">...</div></div>}
              <div ref={chatEndRef} />
            </div>
            <form className="chat-form" onSubmit={e => { e.preventDefault(); sendChat() }}>
              <input type="text" value={chatInput} onChange={e => setChatInput(e.target.value)} placeholder="Ask your mentor a question..." disabled={loadingChat || !clusterStatus.active} />
              <button type="submit" disabled={!chatInput || loadingChat}>Send</button>
            </form>
          </main>

          {/* BOTTOM: THE REAL TERMINAL */}
          <main className="panel real-terminal-panel">
            <div className="panel-header dark">
              <h3>🖥️ Sandbox Terminal</h3>
            </div>
            <div className="terminal-screen">
              {terminalHistory.length === 0 && <div className="terminal-muted">Type `kubectl get pods` to begin...</div>}
              {terminalHistory.map((entry, idx) => (
                <div key={idx} className="terminal-block">
                  <div className="term-cmd"><span className="prompt">$</span> {entry.cmd}</div>
                  <div className={`term-out ${entry.isError ? 'term-error' : ''}`}>{entry.output}</div>
                </div>
              ))}
              <div ref={terminalEndRef} />
            </div>
            <form className="terminal-form" onSubmit={submitTerminal}>
              <span className="prompt">$</span>
              <input type="text" value={terminalInput} onChange={e => setTerminalInput(e.target.value)} placeholder={clusterStatus.active ? "kubectl get pods..." : "Wait for scenario to start..."} disabled={loadingTerminal || !clusterStatus.active} autoFocus />
            </form>
          </main>

        </div>
      </div>

      {/* POST MORTEM MODAL */}
      {postMortem && (
        <div className="modal-overlay" onClick={() => setPostMortem(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2>🎉 Level Complete!</h2>
            <p className="modal-scenario">{postMortem.scenario}</p>
            <div className="mortem-stats">
              <div className="mortem-stat"><span className="stat-label">Time Elapsed</span><span className="stat-val">{fmt(postMortem.elapsed)}</span></div>
              <div className="mortem-stat"><span className="stat-label">Commands Run</span><span className="stat-val yellow">{postMortem.commandsRun}</span></div>
            </div>
            <p style={{ marginBottom: '1.5rem', color: '#9ca3af', textAlign: 'center' }}>Great job debugging this incident! Ask your mentor for a detailed breakdown, or start the next level.</p>
            <button className="btn btn-heal" onClick={() => setPostMortem(null)}>Continue Training</button>
          </div>
        </div>
      )}
    </div>
  )
}