/**
 * API service for communicating with the backend.
 */

// Use environment variable for production, fallback to relative URL for local dev
const API_BASE_URL = import.meta.env.VITE_API_URL 
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : '/api/v1'

/**
 * Room creation request parameters.
 */
export interface CreateRoomRequest {
  name?: string
  privacy?: 'public' | 'private'
  expires_in_minutes?: number
  product_url?: string
  company_id?: string
}

/**
 * Room details returned from the API.
 */
export interface RoomResponse {
  id: string
  name: string
  url: string
  privacy: string
  created_at: string
  product_url?: string
  browser_live_url?: string
  company_id?: string
}

/**
 * Token request parameters.
 */
export interface CreateTokenRequest {
  room_name: string
  user_name: string
  is_owner?: boolean
  expires_in_minutes?: number
}

/**
 * Token response from the API.
 */
export interface TokenResponse {
  token: string
  room_url: string
}

/**
 * API client for room operations.
 */
export const roomsApi = {
  /**
   * Create a new Daily.co room.
   */
  async createRoom(request: CreateRoomRequest = {}): Promise<RoomResponse> {
    const response = await fetch(`${API_BASE_URL}/rooms`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    })

    if (!response.ok) {
      throw new Error(`Failed to create room: ${response.statusText}`)
    }

    return response.json()
  },

  /**
   * Get details of an existing room.
   */
  async getRoom(roomName: string): Promise<RoomResponse> {
    const response = await fetch(`${API_BASE_URL}/rooms/${roomName}`)

    if (!response.ok) {
      throw new Error(`Failed to get room: ${response.statusText}`)
    }

    return response.json()
  },

  /**
   * Create a meeting token for joining a room.
   */
  async createToken(request: CreateTokenRequest): Promise<TokenResponse> {
    const response = await fetch(`${API_BASE_URL}/rooms/token`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    })

    if (!response.ok) {
      throw new Error(`Failed to create token: ${response.statusText}`)
    }

    return response.json()
  },
}

/**
 * Agent join response.
 */
export interface AgentJoinResponse {
  success: boolean
  message: string
  room_name: string
}

/**
 * API client for AI agent operations.
 */
export const agentApi = {
  /**
   * Spawn an AI agent to join the room.
   */
  async joinRoom(roomName: string): Promise<AgentJoinResponse> {
    const response = await fetch(`${API_BASE_URL}/agent/join/${roomName}`, {
      method: 'POST',
    })

    if (!response.ok) {
      throw new Error(`Failed to spawn agent: ${response.statusText}`)
    }

    return response.json()
  },

  /**
   * Remove AI agent from the room.
   */
  async leaveRoom(roomName: string): Promise<AgentJoinResponse> {
    const response = await fetch(`${API_BASE_URL}/agent/leave/${roomName}`, {
      method: 'POST',
    })

    if (!response.ok) {
      throw new Error(`Failed to remove agent: ${response.statusText}`)
    }

    return response.json()
  },
}

