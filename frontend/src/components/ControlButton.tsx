interface ControlButtonProps {
  onClick: () => void
  isActive: boolean
  activeIcon: React.ReactNode
  inactiveIcon: React.ReactNode
  disabled?: boolean
}

export default function ControlButton({ onClick, isActive, activeIcon, inactiveIcon, disabled }: ControlButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`p-3 rounded-xl transition-all duration-200 ${
        disabled
          ? 'bg-white/5 text-gray-600 cursor-not-allowed'
          : isActive
          ? 'bg-white/5 hover:bg-white/10 text-white'
          : 'bg-red-500 hover:bg-red-600 text-white'
      }`}
    >
      {isActive ? activeIcon : inactiveIcon}
    </button>
  )
}
