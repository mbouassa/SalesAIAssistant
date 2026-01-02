import { useState } from 'react'

interface JoinLobbyProps {
  roomName: string
  onJoin: (userName: string) => void
}

export default function JoinLobby({ roomName, onJoin }: JoinLobbyProps) {
  const [userName, setUserName] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (userName.trim()) {
      onJoin(userName.trim())
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 relative overflow-hidden flex flex-col">
      {/* Background effects */}
      <div className="absolute inset-0 bg-gradient-to-br from-gray-950 via-gray-900 to-brand-950 pointer-events-none" />
      <div className="absolute top-1/4 right-1/4 w-[500px] h-[500px] bg-brand-600/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 left-1/4 w-[400px] h-[400px] bg-brand-400/5 rounded-full blur-3xl pointer-events-none" />

      {/* Header */}
      <header className="relative z-20 border-b border-white/10 flex-shrink-0">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-brand-600 flex items-center justify-center">
              <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </div>
            <span className="text-white font-semibold text-lg">Karumi</span>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="relative z-10 flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-md">
          {/* Glass card container */}
          <div className="p-8 sm:p-10 rounded-3xl glass">
            {/* Header */}
            <div className="text-center mb-10">
              <h1 className="text-3xl sm:text-4xl font-bold text-white mb-4">
                Join this room
              </h1>
              <p className="text-gray-400 leading-relaxed">
                Enter your name to join the demo session.
              </p>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="relative">
                <input
                  type="text"
                  value={userName}
                  onChange={(e) => setUserName(e.target.value)}
                  placeholder="Your name"
                  autoFocus
                  className="w-full px-5 py-4 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500/50 transition-all"
                />
              </div>

              <button
                type="submit"
                disabled={!userName.trim()}
                className="btn-primary-glow w-full group flex items-center justify-center gap-3 px-8 py-5 bg-brand-600 hover:bg-brand-500 text-white rounded-2xl font-semibold text-lg hover:scale-[1.02] transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
              >
                <span>Join Room</span>
                <svg 
                  className="w-5 h-5 text-brand-200 group-hover:translate-x-1 transition-transform" 
                  fill="none" 
                  viewBox="0 0 24 24" 
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                </svg>
              </button>
            </form>

            {/* Room ID footer */}
            <div className="mt-8 pt-6 border-t border-white/10">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500 uppercase tracking-wider">Room ID</span>
                <span className="text-sm text-gray-400 font-mono">{roomName?.slice(0, 12)}...</span>
              </div>
            </div>
          </div>

          {/* Footer */}
          <p className="text-center text-gray-600 text-sm mt-6">
            Camera & microphone access required
          </p>
        </div>
      </main>
    </div>
  )
}
