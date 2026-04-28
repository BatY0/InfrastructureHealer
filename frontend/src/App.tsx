import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'

function stripThinking(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>/gi, '').replace(/<\|think\|>[\s\S]*?<\/\|think\|>/gi, '').replace(/<thinking>[\s\S]*?<\/thinking>/gi, '').replace(/<think>[\s\S]*/gi, '').trim()
}

// ─── Types ────────────────────────────────────────────────────────────────────
interface Message { role: 'user' | 'assistant' | 'system', content: string }
interface ScenarioMeta { 
  key: string, 
  order: number,
  name: string, 
  description: string, 
  icon: string, 
  difficulty: string, 
  learning: string,
  taught_commands: string[],
  tutorial_text: string,
  victory_message?: string
}
interface PodInfo { name: string, status: string, restarts: string, ready: string }
interface ClusterStatus { active: boolean, scenario_key: string | null, scenario_name: string | null, elapsed_seconds: number, events: string[], pods: PodInfo[], victory?: boolean }
interface PostMortem { elapsed: number, commandsRun: number, scenario: string, leveledUp: boolean, stars: number }
interface TerminalEntry { cmd: string, output: string, isError: boolean }
interface LevelStats { stars: number, bestTime: number }

const API = 'http://127.0.0.1:8000'

function fmt(secs: number) {
  const m = Math.floor(secs / 60).toString().padStart(2, '0')
  const s = (secs % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

function diffBadge(d: string) { return d === 'Beginner' ? 'badge-green' : d === 'Intermediate' ? 'badge-yellow' : d === 'Expert' ? 'badge-purple' : 'badge-red' }
function podStatusColor(status: string) { return status === 'Running' ? '#10b981' : status === 'Pending' ? '#f59e0b' : '#ef4444' }

// Renders stars based on a 1-3 number
function StarDisplay({ count }: { count: number }) {
  if (count === 0) return null;
  return <span style={{ letterSpacing: '2px', textShadow: '0 0 5px rgba(250, 204, 21, 0.5)' }}>{'⭐'.repeat(count)}</span>;
}

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioMeta[]>([])
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [clusterStatus, setClusterStatus] = useState<ClusterStatus>({ active: false, scenario_key: null, scenario_name: null, elapsed_seconds: 0, events: [], pods: [] })

  // --- PROGRESSION & STATS STATE ---
  const [playerLevel, setPlayerLevel] = useState<number>(() => {
    const saved = localStorage.getItem('kubeQuest_level')
    return saved ? parseInt(saved, 10) : 1
  })
  const [levelStats, setLevelStats] = useState<Record<string, LevelStats>>(() => {
    const saved = localStorage.getItem('kubeQuest_stats')
    return saved ? JSON.parse(saved) : {}
  })
  const [showBriefing, setShowBriefing] = useState(false)

  // Smooth Clock State
  const [localElapsed, setLocalElapsed] = useState(0)
  
  // Traffic & Victory State
  const [victoryTriggered, setVictoryTriggered] = useState(false)
  const isHealingRef = useRef(false)

  // Chat State
  const [messages, setMessages] = useState<Message[]>([])
  const [chatInput, setChatInput] = useState('')
  const [loadingChat, setLoadingChat] = useState(false)

  // Terminal State
  const [terminalHistory, setTerminalHistory] = useState<TerminalEntry[]>([])
  const [terminalInput, setTerminalInput] = useState('')
  const [loadingTerminal, setLoadingTerminal] = useState(false)
  const [commandsRunCount, setCommandsRunCount] = useState(0)
  
  // Terminal Arrow History State
  const [cmdStack, setCmdStack] = useState<string[]>([])
  const [historyIndex, setHistoryIndex] = useState<number>(-1)
  const [draftInput, setDraftInput] = useState<string>('')

  const [postMortem, setPostMortem] = useState<PostMortem | null>(null)

  const chatEndRef = useRef<HTMLDivElement>(null)
  const terminalEndRef = useRef<HTMLDivElement>(null)

  // Derived state
  const selectedScenario = scenarios.find(s => s.key === selectedKey)
  const activeScenario = scenarios.find(s => s.key === clusterStatus.scenario_key)

  // Polling & Setup
  useEffect(() => { fetch(`${API}/api/scenarios`).then(r => r.json()).then(setScenarios).catch(() => { }) }, [])
  
  useEffect(() => {
    const poll = () => {
      fetch(`${API}/api/status`).then(r => r.json()).then((s: ClusterStatus) => {
        setClusterStatus(s); 
        if (!s.active && clusterStatus.active) setSelectedKey(null);
        if (s.active) setLocalElapsed(prev => Math.max(prev, s.elapsed_seconds));

        // Auto Victory Trigger
        if (s.active && s.victory && !isHealingRef.current && !victoryTriggered) {
          setVictoryTriggered(true);
        }
      }).catch(() => { })
    }
    poll(); 
    const id = setInterval(poll, 3000); 
    return () => clearInterval(id)
  }, [clusterStatus.active])

  useEffect(() => {
    if (victoryTriggered && !isHealingRef.current) {
      if (!loadingChat) {
        isHealingRef.current = true;
        sendChat(undefined, true);
      }
    }
  }, [victoryTriggered, loadingChat])

  useEffect(() => {
    let id: ReturnType<typeof setInterval>;
    if (clusterStatus.active) {
      id = setInterval(() => {
        setLocalElapsed(prev => prev + 1);
      }, 1000);
    } else {
      setLocalElapsed(0);
      setVictoryTriggered(false);
      isHealingRef.current = false;
    }
    return () => clearInterval(id);
  }, [clusterStatus.active])

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loadingChat])
  useEffect(() => { terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [terminalHistory, loadingTerminal])

  // Actions
  const handleStartClick = () => {
    if (!selectedKey) return
    setShowBriefing(true)
  }

  const confirmAndInject = async () => {
    if (!selectedKey) return
    setShowBriefing(false)
    try {
      const res = await fetch(`${API}/api/chaos/inject`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenario: selectedKey }) })
      const data = await res.json()
      if (!res.ok) { alert(data.detail); return }

      setTerminalHistory([{ cmd: 'System initialized.', output: `Loaded scenario: ${data.scenario}`, isError: false }])
      setCommandsRunCount(0)
      setCmdStack([])

      const initMessages: Message[] = []
      if (data.briefing) initMessages.push({ role: 'assistant', content: stripThinking(data.briefing.answer) })
      setMessages(initMessages)
      setPostMortem(null)
    } catch (e) { alert('Cannot reach backend') }
  }

  const calculateStars = (time: number, cmds: number, difficulty: string) => {
    if (cmds === 0) return 0; // Prevent instant 3-star exploits

    let multi = 1;
    if (difficulty === 'Intermediate') multi = 1.5;
    if (difficulty === 'Advanced') multi = 2.5;
    if (difficulty === 'Expert') multi = 4.0;

    if (time <= 120 * multi && cmds <= Math.ceil(8 * multi)) return 3;
    if (time <= 300 * multi && cmds <= Math.ceil(20 * multi)) return 2;
    return 1;
  }

  const healCluster = async () => {
    if (!clusterStatus.scenario_key) return;
    const currentKey = clusterStatus.scenario_key;

    try {
      await fetch(`${API}/api/chaos/cleanup`, { method: 'POST' })
      
      let leveledUp = false;
      if (activeScenario && activeScenario.order >= playerLevel) {
        const nextLevel = activeScenario.order + 1;
        setPlayerLevel(nextLevel);
        localStorage.setItem('kubeQuest_level', nextLevel.toString());
        leveledUp = true;
      }

      const earnedStars = calculateStars(localElapsed, commandsRunCount, activeScenario?.difficulty || 'Beginner');
      
      // Update Stats
      setLevelStats(prev => {
        const currentStats = prev[currentKey] || { stars: 0, bestTime: Infinity };
        const newStats = {
          ...prev,
          [currentKey]: {
            stars: Math.max(currentStats.stars, earnedStars),
            bestTime: Math.min(currentStats.bestTime, localElapsed)
          }
        };
        localStorage.setItem('kubeQuest_stats', JSON.stringify(newStats));
        return newStats;
      });

      setPostMortem({ 
        elapsed: localElapsed, 
        commandsRun: commandsRunCount, 
        scenario: clusterStatus.scenario_name ?? '',
        leveledUp,
        stars: earnedStars
      })
    } catch (e) { alert('Cannot reach backend') }
  }

  // --- TERMINAL LOGIC ---
  const handleTerminalKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (cmdStack.length > 0) {
        const nextIdx = historyIndex === -1 ? cmdStack.length - 1 : Math.max(0, historyIndex - 1);
        if (historyIndex === -1) setDraftInput(terminalInput);
        setHistoryIndex(nextIdx);
        setTerminalInput(cmdStack[nextIdx]);
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIndex !== -1) {
        const nextIdx = historyIndex + 1;
        if (nextIdx >= cmdStack.length) {
          setHistoryIndex(-1);
          setTerminalInput(draftInput);
        } else {
          setHistoryIndex(nextIdx);
          setTerminalInput(cmdStack[nextIdx]);
        }
      }
    }
  }

  const submitTerminal = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!terminalInput.trim() || loadingTerminal) return
    const cmd = terminalInput.trim()
    setTerminalInput('')
    
    setCmdStack(prev => [...prev, cmd])
    setHistoryIndex(-1)
    setDraftInput('')

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
  const sendChat = async (overrideMsg?: string, isVictoryReview: boolean = false) => {
    const text = overrideMsg || chatInput
    if ((!text.trim() && !isVictoryReview) || loadingChat) return
    setChatInput(''); setLoadingChat(true)

    let nextMessages = messages;
    if (!isVictoryReview) {
       nextMessages = [...messages, { role: 'user', content: text } as Message]
       setMessages(nextMessages)
    } else {
       nextMessages = [...messages, { role: 'user', content: '[SYSTEM_INTERNAL: The user has successfully triggered the victory condition. Please generate the victory review according to the system prompt instructions.]' } as Message]
    }



    const recentTerminal = terminalHistory.slice(-5).map(t => {
      const out = t.output.length > 500 ? t.output.slice(0, 500) + '\n...[output truncated for brevity]' : t.output;
      return `$ ${t.cmd}\n${out}`;
    }).join('\n\n')

    try {
      const res = await fetch(`${API}/api/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
           history: nextMessages, 
           terminal_history: recentTerminal,
           is_victory_review: isVictoryReview
        }),
      })
      const data = await res.json()
      setMessages(p => [...p, { role: 'assistant', content: stripThinking(data.answer) }])
      
      if (isVictoryReview) {
        setTimeout(() => healCluster(), 3000);
      }
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
            {clusterStatus.active ? `🔴 Incident Active — ${fmt(localElapsed)}` : '🟢 System Healthy'}
          </span>
        </div>
      </header>

      <div className="main-grid split-layout">

        {/* ── LEFT: GAME CONTROL ── */}
        <aside className="panel left-panel">
          <section className="panel-section">
            <h2 className="section-title">Select Level</h2>
            <div className="scenario-list">
              {scenarios.map(s => {
                const isLocked = s.order > playerLevel;
                const stats = levelStats[s.key];
                return (
                  <button
                    key={s.key} 
                    disabled={clusterStatus.active || isLocked} 
                    onClick={() => setSelectedKey(s.key)}
                    className={`scenario-card ${selectedKey === s.key ? 'scenario-card--selected' : ''} ${clusterStatus.active || isLocked ? 'scenario-card--disabled' : ''}`}
                    style={isLocked ? { opacity: 0.6, cursor: 'not-allowed', filter: 'grayscale(100%)' } : {}}
                  >
                    <span className="scenario-icon">{isLocked ? '🔒' : s.icon}</span>
                    <div className="scenario-info" style={{ width: '100%' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span className="scenario-name">{s.name}</span>
                        {stats && <StarDisplay count={stats.stars} />}
                      </div>
                      <span className={`badge ${diffBadge(s.difficulty)}`}>{s.difficulty}</span>
                    </div>
                  </button>
                )
              })}
            </div>
            <div className="chaos-actions" style={{ marginTop: '1rem' }}>
              <button className="btn btn-danger" disabled={!selectedKey || clusterStatus.active} onClick={handleStartClick}>▶ Start Simulator</button>
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
                  <div className="bubble">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                </div>
              ))}
              {loadingChat && <div className="chat-bubble-wrapper mentor"><div className="bubble typing">...</div></div>}
              <div ref={chatEndRef} />
            </div>
            <form className="chat-form" onSubmit={e => { e.preventDefault(); sendChat() }}>
              <input type="text" value={chatInput} onChange={e => setChatInput(e.target.value)} placeholder="Ask your mentor a question..." disabled={loadingChat} />
              <button type="submit" disabled={!chatInput || loadingChat}>Send</button>
            </form>
          </main>

          {/* BOTTOM: THE REAL TERMINAL */}
          <main className="panel real-terminal-panel">
            <div className="panel-header dark" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3>🖥️ Sandbox Terminal</h3>
              {clusterStatus.active && activeScenario && (
                <div style={{ fontSize: '0.85rem', color: '#9ca3af', background: '#1e293b', padding: '4px 10px', borderRadius: '6px', border: '1px solid #334155' }}>
                  <strong>Target Commands: </strong> 
                  {activeScenario.taught_commands.map((c, i) => <code key={i} style={{ marginLeft: '8px', color: '#38bdf8' }}>{c}</code>)}
                </div>
              )}
            </div>
            <div className="terminal-screen">
              {terminalHistory.length === 0 && <div className="terminal-muted" style={{color: '#475569'}}>System ready...</div>}
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
              <input 
                type="text" 
                value={terminalInput} 
                onChange={e => setTerminalInput(e.target.value)} 
                onKeyDown={handleTerminalKeyDown}
                placeholder={clusterStatus.active ? "kubectl get pods..." : "Wait for scenario to start..."} 
                disabled={loadingTerminal || !clusterStatus.active} 
                autoFocus 
              />
            </form>
          </main>

        </div>
      </div>

      {/* BRIEFING MODAL */}
      {showBriefing && selectedScenario && (
        <div className="modal-overlay" onClick={() => setShowBriefing(false)}>
          <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: '600px', textAlign: 'left' }}>
            <h2 style={{ marginBottom: '1rem', borderBottom: '1px solid #374151', paddingBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span>{selectedScenario.icon}</span> Briefing: {selectedScenario.name}
            </h2>
            <div style={{ lineHeight: '1.6', color: '#d1d5db', marginBottom: '1.5rem' }}>
              <ReactMarkdown>{selectedScenario.tutorial_text}</ReactMarkdown>
            </div>
            <div style={{ background: '#1f2937', padding: '1rem', borderRadius: '8px', marginBottom: '1.5rem', border: '1px solid #374151' }}>
              <h4 style={{ margin: '0 0 0.5rem 0', color: '#9ca3af' }}>🛠️ Commands to Learn:</h4>
              <ul style={{ margin: 0, paddingLeft: '1.5rem', color: '#38bdf8', fontFamily: 'monospace' }}>
                {selectedScenario.taught_commands.map(cmd => (
                  <li key={cmd} style={{ marginBottom: '0.25rem' }}>{cmd}</li>
                ))}
              </ul>
            </div>
            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
              <button className="btn" style={{ background: 'transparent', border: '1px solid #4b5563' }} onClick={() => setShowBriefing(false)}>Cancel</button>
              <button className="btn btn-danger" onClick={confirmAndInject}>Acknowledge & Start Level</button>
            </div>
          </div>
        </div>
      )}

      {/* POST MORTEM MODAL */}
      {postMortem && (
        <div className="modal-overlay" onClick={() => setPostMortem(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: '3rem', marginBottom: '0.5rem' }}>
              <StarDisplay count={postMortem.stars} />
            </div>
            {postMortem.leveledUp ? (
              <h2 style={{ color: '#10b981', fontSize: '2rem' }}>🌟 Level Up!</h2>
            ) : (
              <h2>🎉 Scenario Complete!</h2>
            )}
            <p className="modal-scenario">{postMortem.scenario}</p>
            <div className="mortem-stats">
              <div className="mortem-stat"><span className="stat-label">Time Elapsed</span><span className="stat-val">{fmt(postMortem.elapsed)}</span></div>
              <div className="mortem-stat"><span className="stat-label">Commands Run</span><span className="stat-val yellow">{postMortem.commandsRun}</span></div>
            </div>
            {postMortem.leveledUp ? (
              <p style={{ marginBottom: '1.5rem', color: '#9ca3af', textAlign: 'center' }}>You learned new skills and unlocked the next scenario! Keep up the great work.</p>
            ) : (
              <p style={{ marginBottom: '1.5rem', color: '#9ca3af', textAlign: 'center' }}>Great job debugging this incident! Ask your mentor for a detailed breakdown, or replay{postMortem.stars < 3 ? ' to get 3 stars' : ''}.</p>
            )}
            <button className="btn btn-heal" onClick={() => setPostMortem(null)}>Continue Training</button>
          </div>
        </div>
      )}
    </div>
  )
}