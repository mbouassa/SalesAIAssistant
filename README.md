# AI Demo Agent

An AI-powered demo agent that conducts product demonstrations via video calls. Built with React, FastAPI, and Daily.co.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (React)                         │
│                                                                 │
│   • Home page - Create/join rooms                               │
│   • Demo room - Video call interface with Daily.co              │
│                                                                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            │ REST API
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                        Backend (FastAPI)                         │
│                                                                 │
│   • Room management - Create, get, delete rooms                 │
│   • Token generation - Meeting tokens for participants          │
│   • Daily.co integration                                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Daily.co account ([Get API key](https://dashboard.daily.co/developers))

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp env.example .env
# Edit .env and add your DAILY_API_KEY

# Run the server
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

The app will be available at `http://localhost:5173`

## 📁 Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       └── rooms.py      # Room endpoints
│   │   ├── core/
│   │   │   └── config.py         # Settings
│   │   ├── models/
│   │   │   └── room.py           # Pydantic models
│   │   ├── services/
│   │   │   └── daily_service.py  # Daily.co API client
│   │   └── main.py               # FastAPI app
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── HomePage.tsx      # Room creation/joining
│   │   │   └── DemoRoom.tsx      # Video call interface
│   │   ├── services/
│   │   │   └── api.ts            # Backend API client
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── index.css
│   ├── package.json
│   └── vite.config.ts
│
└── README.md
```

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/rooms` | Create a new room |
| GET | `/api/v1/rooms/{name}` | Get room details |
| DELETE | `/api/v1/rooms/{name}` | Delete a room |
| POST | `/api/v1/rooms/token` | Create meeting token |
| GET | `/health` | Health check |

## 🛠️ Tech Stack

**Frontend:**
- React 18
- TypeScript
- Vite
- Tailwind CSS
- React Router
- Daily.co React SDK

**Backend:**
- FastAPI
- Python 3.11+
- Pydantic
- httpx (async HTTP client)

**Infrastructure:**
- Daily.co (video calls)

## 📝 License

MIT

