import { Routes, Route } from 'react-router-dom'
import HomePage from './pages/HomePage'
import DemoRoom from './pages/DemoRoom'

/**
 * Main application component with routing.
 */
function App() {
  return (
    <div className="min-h-screen bg-demo-bg">
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/room/:roomName" element={<DemoRoom />} />
      </Routes>
    </div>
  )
}

export default App

