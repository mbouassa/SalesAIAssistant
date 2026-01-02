import { useState, useCallback } from 'react'
import { DailyCall, DailyParticipant } from '@daily-co/daily-js'
import VideoTile from './VideoTile'
import ControlButton from './ControlButton'
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
}

export default function VideoRoom({ roomName, callObject, participants, onLeave }: VideoRoomProps) {
  const [isMuted, setIsMuted] = useState(false)
  const [isVideoOff, setIsVideoOff] = useState(false)
  const [linkCopied, setLinkCopied] = useState(false)

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

  const toggleVideo = useCallback(() => {
    callObject.setLocalVideo(isVideoOff)
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
        {/* Video Grid */}
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

        {/* Side Panel */}
        <div className="hidden xl:flex w-72 flex-col gap-4">
          {/* AI Agent Card */}
          <div className="flex-1 bg-gradient-to-br from-brand-600 to-brand-800 rounded-2xl p-6 flex flex-col items-center justify-center relative overflow-hidden">
            <div className="absolute inset-0 bg-[url('data:image/svg+xml,...')] opacity-10" />
            <div className="relative z-10 text-center">
              <div className="w-14 h-14 rounded-2xl bg-white/10 backdrop-blur-sm flex items-center justify-center mb-4 mx-auto">
                <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
              </div>
              <p className="text-white font-semibold">AI Agent</p>
              <p className="text-white/60 text-sm mt-1">Ready to demo</p>
            </div>
          </div>

          {/* Chat */}
          <div className="h-48 rounded-2xl glass p-4">
            <div className="flex items-center gap-2 mb-3 pb-3 border-b border-white/10">
              <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
              <span className="text-gray-400 text-sm font-medium">Chat</span>
            </div>
            <div className="flex-1 flex items-center justify-center h-24">
              <p className="text-gray-600 text-xs">No messages yet</p>
            </div>
          </div>
        </div>
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
