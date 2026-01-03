/**
 * BrowserView - Displays the Browserbase live view in an iframe.
 * Shows the product page that the AI is controlling.
 */

interface BrowserViewProps {
  liveUrl: string
  className?: string
}

export default function BrowserView({ liveUrl, className = '' }: BrowserViewProps) {
  return (
    <div className={`relative rounded-2xl overflow-hidden bg-gray-900 ${className}`}>
      {/* Header */}
      <div className="absolute top-0 left-0 right-0 z-10 px-4 py-2 bg-gradient-to-b from-gray-900/90 to-transparent">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-brand-500 animate-pulse" />
          <span className="text-xs text-gray-400 font-medium">Live Demo</span>
        </div>
      </div>
      
      {/* Browser iframe */}
      <iframe
        src={liveUrl}
        className="w-full h-full border-0"
        sandbox="allow-same-origin allow-scripts"
        title="Product Demo"
      />
      
      {/* Gradient overlay at bottom */}
      <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-gray-900/50 to-transparent pointer-events-none" />
    </div>
  )
}

