import { useEffect, useState, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import DailyIframe, { DailyCall, DailyParticipant } from '@daily-co/daily-js'
import { roomsApi, agentApi } from '../services/api'
import JoinLobby from '../components/JoinLobby'
import VideoRoom from '../components/VideoRoom'

type RoomState = 'lobby' | 'joining' | 'joined' | 'error'

/**
 * Demo room page - orchestrates the join flow and video room.
 */
export default function DemoRoom() {
  const { roomName } = useParams<{ roomName: string }>()
  const navigate = useNavigate()

  const [roomState, setRoomState] = useState<RoomState>('lobby')
  const [userName, setUserName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [callObject, setCallObject] = useState<DailyCall | null>(null)
  const [participants, setParticipants] = useState<DailyParticipant[]>([])
  const [browserLiveUrl, setBrowserLiveUrl] = useState<string | undefined>()
  
  const isJoiningRef = useRef(false)

  // Check for browser session URL on mount
  useEffect(() => {
    if (roomName) {
      const storedUrl = sessionStorage.getItem(`browser_${roomName}`)
      if (storedUrl) {
        setBrowserLiveUrl(storedUrl)
      }
    }
  }, [roomName])

  const updateParticipants = useCallback((call: DailyCall | null) => {
    if (call) {
      const allParticipants = call.participants()
      setParticipants(Object.values(allParticipants))
    }
  }, [])

  const handleJoin = useCallback(async (name: string) => {
    if (!roomName || isJoiningRef.current) return
    
    isJoiningRef.current = true
    setUserName(name)
    setRoomState('joining')

    let dailyCall: DailyCall | null = null

    try {
      const { token, room_url } = await roomsApi.createToken({
        room_name: roomName,
        user_name: name,
        is_owner: false,
      })

      dailyCall = DailyIframe.createCallObject({
        audioSource: true,
        videoSource: false,  // Camera off by default
      })

      dailyCall.on('joined-meeting', async () => {
        setRoomState('joined')
        updateParticipants(dailyCall)
        
        // Spawn AI agent to join the call
        try {
          await agentApi.joinRoom(roomName)
          console.log('[DemoRoom] AI Agent joining...')
        } catch (err) {
          console.error('[DemoRoom] Failed to spawn AI agent:', err)
        }
      })

      dailyCall.on('participant-joined', () => updateParticipants(dailyCall))
      dailyCall.on('participant-left', () => updateParticipants(dailyCall))
      dailyCall.on('participant-updated', () => updateParticipants(dailyCall))

      dailyCall.on('error', (event: { errorMsg?: string }) => {
        setError(event?.errorMsg || 'An error occurred')
        setRoomState('error')
      })

      dailyCall.on('left-meeting', () => navigate('/'))

      await dailyCall.join({ url: room_url, token })
      setCallObject(dailyCall)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to join room')
      setRoomState('error')
      isJoiningRef.current = false
    }
  }, [roomName, navigate, updateParticipants])

  const handleLeave = useCallback(async () => {
    // Clean up AI agent first
    if (roomName) {
      try {
        await agentApi.leaveRoom(roomName)
        console.log('[DemoRoom] AI Agent leaving...')
      } catch (err) {
        console.error('[DemoRoom] Failed to remove AI agent:', err)
      }
    }
    
    if (callObject) {
      callObject.leave()
    }
    navigate('/')
  }, [callObject, navigate, roomName])

  useEffect(() => {
    return () => {
      if (callObject) {
        callObject.leave()
        callObject.destroy()
      }
    }
  }, [callObject])

  // ============================================================================
  // RENDER BASED ON STATE
  // ============================================================================

  if (roomState === 'lobby') {
    return <JoinLobby roomName={roomName || ''} onJoin={handleJoin} />
  }

  if (roomState === 'joining') {
    return (
      <div className="min-h-screen bg-gray-950 relative overflow-hidden flex items-center justify-center">
        {/* Background effects */}
        <div className="absolute inset-0 bg-gradient-to-br from-gray-950 via-gray-900 to-brand-950 pointer-events-none" />
        <div className="absolute top-1/4 right-1/4 w-[500px] h-[500px] bg-brand-600/10 rounded-full blur-3xl pointer-events-none" />
        
        <div className="relative z-10 p-8 rounded-2xl glass">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 border-2 border-brand-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
            <div>
              <p className="text-white font-medium">Joining room...</p>
              <p className="text-gray-400 text-sm">Connecting as {userName}</p>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (roomState === 'error') {
    return (
      <div className="min-h-screen bg-gray-950 relative overflow-hidden flex items-center justify-center px-6">
        {/* Background effects */}
        <div className="absolute inset-0 bg-gradient-to-br from-gray-950 via-gray-900 to-brand-950 pointer-events-none" />
        
        <div className="relative z-10 w-full max-w-sm p-8 rounded-2xl glass text-center">
          <div className="w-14 h-14 mx-auto mb-5 rounded-2xl bg-red-500/10 flex items-center justify-center">
            <svg className="w-6 h-6 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-white mb-2">Couldn't join room</h2>
          <p className="text-gray-400 text-sm mb-6">{error}</p>
          <button
            onClick={() => navigate('/')}
            className="px-6 py-3 bg-white/5 hover:bg-white/10 border border-white/10 text-white text-sm font-medium rounded-xl transition-colors"
          >
            Go back home
          </button>
        </div>
      </div>
    )
  }

  if (roomState === 'joined' && callObject) {
    return (
      <VideoRoom
        roomName={roomName || ''}
        callObject={callObject}
        participants={participants}
        onLeave={handleLeave}
        browserLiveUrl={browserLiveUrl}
      />
    )
  }

  return null
}
