import { useState, useCallback, useRef, useEffect } from 'react'
import { DailyCall, DailyParticipant } from '@daily-co/daily-js'
import VideoTile from './VideoTile'
import ControlButton from './ControlButton'
import BrowserView from './BrowserView'
import { 
  MicOnIcon, MicOffIcon, 
  VideoOnIcon, VideoOffIcon, 
  ScreenShareIcon, LinkIcon, CheckIcon,
  UserPlusIcon, PhoneOffIcon 
} from './icons'

interface VideoRoomProps {
  roomName: string
  callObject: DailyCall
  participants: DailyParticipant[]
  onLeave: () => void
  browserLiveUrl?: string
}

export default function VideoRoom({ roomName, callObject, participants, onLeave, browserLiveUrl }: VideoRoomProps) {
  const [isMuted, setIsMuted] = useState(false)
  const [isVideoOff, setIsVideoOff] = useState(true)  // Camera off by default
  const [linkCopied, setLinkCopied] = useState(false)
  
  // Draggable user tile state
  const [tilePosition, setTilePosition] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const dragRef = useRef<{ startX: number; startY: number; initialX: number; initialY: number } | null>(null)
  
  const handleDragStart = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    e.preventDefault()
    const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
    const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY
    
    dragRef.current = {
      startX: clientX,
      startY: clientY,
      initialX: tilePosition.x,
      initialY: tilePosition.y,
    }
    setIsDragging(true)
  }, [tilePosition])
  
  // Attach move/end handlers to document for smooth dragging
  useEffect(() => {
    if (!isDragging) return
    
    const handleMouseMove = (e: MouseEvent) => {
      if (!dragRef.current) return
      const deltaX = e.clientX - dragRef.current.startX
      const deltaY = e.clientY - dragRef.current.startY
      setTilePosition({
        x: dragRef.current.initialX + deltaX,
        y: dragRef.current.initialY + deltaY,
      })
    }
    
    const handleTouchMove = (e: TouchEvent) => {
      if (!dragRef.current || !e.touches[0]) return
      const deltaX = e.touches[0].clientX - dragRef.current.startX
      const deltaY = e.touches[0].clientY - dragRef.current.startY
      setTilePosition({
        x: dragRef.current.initialX + deltaX,
        y: dragRef.current.initialY + deltaY,
      })
    }
    
    const handleEnd = () => {
      setIsDragging(false)
      dragRef.current = null
    }
    
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleEnd)
    document.addEventListener('touchmove', handleTouchMove)
    document.addEventListener('touchend', handleEnd)
    
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleEnd)
      document.removeEventListener('touchmove', handleTouchMove)
      document.removeEventListener('touchend', handleEnd)
    }
  }, [isDragging])

  const copyLink = useCallback(() => {
    const url = window.location.href
    navigator.clipboard.writeText(url)
    setLinkCopied(true)
    setTimeout(() => setLinkCopied(false), 2000)
  }, [])

  const toggleMute = useCallback(() => {
    callObject.setLocalAudio(isMuted)
    setIsMuted(!isMuted)
  }, [callObject, isMuted])

  const toggleVideo = useCallback(async () => {
    if (isVideoOff) {
      // Turn camera ON - need to start the video input
      await callObject.setInputDevicesAsync({ videoSource: 'default' as unknown as MediaStreamTrack })
      callObject.setLocalVideo(true)
    } else {
      // Turn camera OFF
      callObject.setLocalVideo(false)
    }
    setIsVideoOff(!isVideoOff)
  }, [callObject, isVideoOff])

  const localParticipant = participants.find(p => p.local)
  const remoteParticipants = participants.filter(p => !p.local)

  return (
    <div className="h-screen flex flex-col bg-gray-950 relative overflow-hidden">
      {/* Background */}
      <div className="absolute inset-0 bg-gradient-to-br from-gray-950 via-gray-900 to-brand-950 pointer-events-none" />

      {/* Header */}
      <header className="relative z-10 flex items-center justify-between px-5 py-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          </div>
          <span className="text-gray-400 text-sm font-mono">{roomName?.slice(0, 16)}...</span>
        </div>
        
        <div className="flex items-center gap-2">
          {/* Copy Link Button */}
          <button
            onClick={copyLink}
            className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl transition-all text-sm font-medium"
          >
            {linkCopied ? (
              <>
                <CheckIcon className="w-4 h-4 text-green-400" />
                <span className="text-green-400">Copied!</span>
              </>
            ) : (
              <>
                <LinkIcon className="w-4 h-4 text-gray-400" />
                <span className="text-gray-300">Invite</span>
              </>
            )}
          </button>

          {/* Participant count */}
          <div className="flex items-center gap-2 px-3 py-2 bg-white/5 border border-white/10 rounded-xl">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
            <span className="text-gray-300 text-sm font-medium">{participants.length}</span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="relative z-10 flex-1 flex gap-4 p-4 overflow-hidden">
        {/* Browser View Mode (product demo) */}
        {browserLiveUrl ? (
          <div className="flex-1 min-w-0 relative">
            {/* Full-width browser */}
            <BrowserView liveUrl={browserLiveUrl} className="w-full h-full" />
            
            {/* User video tile - floating & draggable */}
            {localParticipant && (
              <div
                className={`absolute bottom-4 right-4 w-52 h-40 z-20 shadow-2xl select-none ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
                style={{
                  transform: `translate(${tilePosition.x}px, ${tilePosition.y}px)`,
                }}
                onMouseDown={handleDragStart}
                onTouchStart={handleDragStart}
              >
                <VideoTile
                  participant={localParticipant}
                  callObject={callObject}
                  isLocal={true}
                />
              </div>
            )}
            
            {/* Hidden audio elements for remote participants (AI voice) */}
            <div className="hidden">
              {remoteParticipants.map((participant) => (
                <VideoTile
                  key={participant.session_id}
                  participant={participant}
                  callObject={callObject}
                  isLocal={false}
                />
              ))}
            </div>
          </div>
        ) : (
          /* Standard Video Grid Mode (no browser) */
          <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-4 auto-rows-fr">
            {/* Local Participant */}
            {localParticipant && (
              <VideoTile
                participant={localParticipant}
                callObject={callObject}
                isLocal={true}
              />
            )}
            
            {/* Remote Participants */}
            {remoteParticipants.map((participant) => (
              <VideoTile
                key={participant.session_id}
                participant={participant}
                callObject={callObject}
                isLocal={false}
              />
            ))}

            {/* Empty state when alone */}
            {remoteParticipants.length === 0 && (
              <div className="rounded-2xl glass flex flex-col items-center justify-center p-8">
                <div className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center mb-4">
                  <UserPlusIcon className="w-7 h-7 text-gray-500" />
                </div>
                <p className="text-gray-400 text-sm font-medium mb-1">Waiting for others</p>
                <button
                  onClick={copyLink}
                  className="mt-3 text-brand-400 hover:text-brand-300 text-sm font-medium flex items-center gap-1.5 transition-colors"
                >
                  <LinkIcon className="w-4 h-4" />
                  Copy invite link
                </button>
              </div>
            )}
          </div>
        )}
      </main>

      {/* Controls Bar */}
      <footer className="relative z-10 flex items-center justify-center gap-3 px-5 py-5">
        <div className="flex items-center gap-2 rounded-2xl glass p-2">
          <ControlButton
            onClick={toggleMute}
            isActive={!isMuted}
            activeIcon={<MicOnIcon />}
            inactiveIcon={<MicOffIcon />}
          />

          <ControlButton
            onClick={toggleVideo}
            isActive={!isVideoOff}
            activeIcon={<VideoOnIcon />}
            inactiveIcon={<VideoOffIcon />}
          />

          <ControlButton
            onClick={() => {}}
            isActive={false}
            activeIcon={<ScreenShareIcon />}
            inactiveIcon={<ScreenShareIcon />}
            disabled
          />

          <div className="w-px h-8 bg-white/10 mx-1"></div>

          <button
            onClick={onLeave}
            className="p-3 bg-red-500 hover:bg-red-600 text-white rounded-xl transition-all"
          >
            <PhoneOffIcon className="w-5 h-5" />
          </button>
        </div>
      </footer>
    </div>
  )
}
