import { useEffect, useState, useRef } from 'react'
import { DailyCall, DailyParticipant } from '@daily-co/daily-js'

interface VideoTileProps {
  participant: DailyParticipant
  callObject: DailyCall | null
  isLocal: boolean
}

export default function VideoTile({ participant, callObject, isLocal }: VideoTileProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const [hasVideo, setHasVideo] = useState(false)

  // Handle VIDEO track
  useEffect(() => {
    if (!callObject || !videoRef.current) return

    const videoTrack = participant.tracks?.video
    
    if (videoTrack?.state === 'playable' && videoTrack.track) {
      const stream = new MediaStream([videoTrack.track])
      videoRef.current.srcObject = stream
      setHasVideo(true)
    } else {
      videoRef.current.srcObject = null
      setHasVideo(false)
    }
  }, [callObject, participant.tracks?.video])

  // Handle AUDIO track (for remote participants only)
  useEffect(() => {
    if (!callObject || !audioRef.current || isLocal) return

    const audioTrack = participant.tracks?.audio
    
    if (audioTrack?.state === 'playable' && audioTrack.track) {
      console.log(`[VideoTile] Attaching audio track for ${participant.user_name}`)
      const stream = new MediaStream([audioTrack.track])
      audioRef.current.srcObject = stream
      audioRef.current.play().catch(err => {
        console.warn('[VideoTile] Audio autoplay failed:', err)
      })
    } else {
      audioRef.current.srcObject = null
    }
  }, [callObject, participant.tracks?.audio, isLocal, participant.user_name])

  // Handle CUSTOM AUDIO tracks (for bots using CustomAudioSource)
  useEffect(() => {
    if (!callObject || isLocal) return

    const customAudio = (participant as any).tracks?.customAudio
    if (customAudio) {
      Object.entries(customAudio).forEach(([trackName, trackInfo]: [string, any]) => {
        if (trackInfo?.state === 'playable' && trackInfo.track) {
          const audioId = `custom-audio-${participant.session_id}-${trackName}`
          
          // Remove existing element if any
          const existing = document.getElementById(audioId)
          if (existing) existing.remove()
          
          console.log(`[VideoTile] 🔊 Attaching custom audio: ${trackName} for ${participant.user_name}`)
          
          const audioEl = document.createElement('audio')
          audioEl.id = audioId
          audioEl.autoplay = true
          const stream = new MediaStream([trackInfo.track])
          audioEl.srcObject = stream
          document.body.appendChild(audioEl)
          
          audioEl.play().catch(err => {
            console.warn('[VideoTile] Custom audio play failed:', err)
          })
        }
      })
    }
  }, [callObject, participant, isLocal])

  // Check if muted
  const audioTrack = participant.tracks?.audio
  const hasAudio = audioTrack?.state === 'playable' || audioTrack?.state === 'sendable'
  
  // AI Assistant is never muted (uses custom audio track)
  const isAIAssistant = participant.user_name === 'AI Assistant'
  
  const isMuted = !isAIAssistant && !hasAudio
  const userName = participant.user_name || (isLocal ? 'You' : 'Guest')

  return (
    <div className="relative rounded-2xl overflow-hidden h-full min-h-[120px] bg-gray-900/80 backdrop-blur-sm border border-white/10">
      {/* Video Element */}
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted={isLocal}
        className={`absolute inset-0 w-full h-full object-cover ${hasVideo ? 'opacity-100' : 'opacity-0'}`}
      />
      
      {/* Audio Element (for remote participants) */}
      {!isLocal && (
        <audio
          ref={audioRef}
          autoPlay
          playsInline
        />
      )}

      {/* Avatar fallback when no video */}
      {!hasVideo && (
        <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-gray-900 to-gray-950">
          <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-brand-600 to-brand-800 flex items-center justify-center text-white text-2xl font-semibold shadow-lg shadow-brand-600/20">
            {userName.charAt(0).toUpperCase()}
          </div>
        </div>
      )}

      {/* Bottom overlay */}
      <div className="absolute inset-x-0 bottom-0 p-4 bg-gradient-to-t from-black/60 to-transparent">
        <div className="flex items-center justify-between">
          <span className="text-white text-sm font-medium">
            {userName}
            {isLocal && <span className="text-white/50 ml-1">(You)</span>}
          </span>
          
          {isMuted && (
            <div className="w-6 h-6 rounded-lg bg-red-500 flex items-center justify-center">
              <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4M9.172 9.172a4 4 0 015.656 0M15 11V5a3 3 0 00-6 0v6" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3l18 18" />
              </svg>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
