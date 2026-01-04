# Karumi - AI Sales Demo Agent

## Demos
Part 1: https://www.loom.com/share/5e391d35f95744dcafb5feab357eeccf
Part 2: https://www.loom.com/share/237c26392fc44251b36d6f4a86c0e534

An AI-powered sales agent that conducts live product demonstrations via video calls. The AI joins your call, controls a browser to demo your product, and has natural voice conversations with prospects.

## 🎯 What It Does

- **Joins video calls** as an AI participant via Daily.co
- **Controls a live browser** to demonstrate any web product
- **Has voice conversations** using speech-to-text and text-to-speech
- **Navigates intelligently** based on user requests ("show me the pricing page")
- **Runs scripted demos** with playbooks for consistent product tours
- **Schedules meetings** via Calendly integration when prospects are ready

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Frontend (React)                                │
│                                                                             │
│   HomePage                    DemoRoom                    VideoRoom         │
│   - Create room               - Join flow                 - Browser embed   │
│   - Select persona            - Spawn AI agent            - User video tile │
│   - Enter product URL         - Daily.co connection       - Call controls   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ REST API
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Backend (FastAPI)                               │
│                                                                             │
│   /api/v1/rooms     - Room CRUD, token generation                          │
│   /api/v1/agent     - Spawn/remove AI agent                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AI Agent (Orchestrator)                            │
│                                                                             │
│   Joins Daily call → Listens (STT) → Thinks (LLM) → Speaks (TTS)           │
│   Controls browser → Executes navigation plans → Runs demo playbooks       │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 🤖 Agentic AI Architecture

The AI uses a layered architecture where specialized services work together:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AI Agent (Orchestrator)                              │
│            Coordinates all services, manages Daily call, response loop       │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   Perception  │         │     Planner     │         │    Presenter    │
│   "The Eyes"  │────────▶│   "The Brain"   │────────▶│   "The Voice"   │
│               │         │                 │         │                 │
│ • DOM parsing │         │ • LLM planning  │         │ • Persona config│
│ • Clickables  │         │ • Multi-step    │         │ • Natural speech│
│ • Page state  │         │   navigation    │         │ • Context-aware │
└───────────────┘         └─────────────────┘         └─────────────────┘
        │                           │
        │                           ▼
        │                 ┌─────────────────┐
        │                 │     Intent      │
        │                 │   Detection     │
        │                 │                 │
        │                 │ • Closing intent│
        │                 │ • Demo requests │
        │                 │ • Affirmatives  │
        │                 └─────────────────┘
        │
        ▼
┌───────────────┐         ┌─────────────────┐         ┌─────────────────┐
│    Browser    │         │   Demo Runner   │         │    Calendly     │
│   Service     │◀────────│                 │         │    Service      │
│               │         │ • Playbook exec │         │                 │
│ • Browserbase │         │ • Barge-in      │         │ • Scheduling    │
│ • Playwright  │         │ • Parallel gen  │         │ • Form filling  │
└───────────────┘         └─────────────────┘         └─────────────────┘
```

### Service Responsibilities

| Service | Role | Description |
|---------|------|-------------|
| **Perception** | 👁️ The Eyes | Extracts DOM state, clickable elements, page structure |
| **Planner** | 🧠 The Brain | LLM-based decision maker, creates multi-step navigation plans |
| **Presenter** | 🎤 The Voice | Persona-aware response generation, natural language |
| **Intent** | 🎯 Classifier | Detects closing intent, demo requests, affirmatives |
| **Browser** | 🤚 The Hands | Browserbase + Playwright control (click, scroll, type) |
| **Demo Runner** | 🎬 Director | Executes scripted playbooks with parallel narration |
| **Calendly** | 📅 Scheduler | Handles scheduling flow, form filling, confirmation |

### Response Flow

When a user speaks, the AI processes it in 3 phases:

```
User: "Show me the meditation section"
                    │
                    ▼
┌─────────────────────────────────────┐
│  PHASE 1: Create Navigation Plan    │
│                                     │
│  • Check intents (closing? demo?)   │
│  • Get page context from browser    │
│  • Planner creates step-by-step plan│
│    → speak: "Sure, let me show you" │
│    → click: "Listen Now"            │
│    → done                           │
└─────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────┐
│  PHASE 2: Execute Plan Steps        │
│                                     │
│  • Speak pre-navigation message     │
│  • Browser clicks "Listen Now"      │
│  • Wait for page to load            │
└─────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────┐
│  PHASE 3: Post-Navigation Response  │
│                                     │
│  • Detect new screen from content   │
│  • Check if explanation needed      │
│  • Generate contextual response     │
│  • Ask follow-up question           │
└─────────────────────────────────────┘
```

## 🛠️ Tech Stack

### Frontend
- **React 18** + TypeScript
- **Vite** for fast builds
- **Tailwind CSS** for styling
- **Daily.co React SDK** for video calls

### Backend
- **FastAPI** (Python 3.11+)
- **Daily Python SDK** for AI bot participation
- **Deepgram Flux** for speech-to-text with turn detection
- **OpenAI GPT-4** for conversation and planning
- **ElevenLabs** for natural text-to-speech
- **Browserbase** + Playwright for browser automation
- **Firebase Firestore** for conversation memory

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- API keys for: Daily.co, Deepgram, OpenAI, ElevenLabs, Browserbase
- Firebase credentials (optional, for memory persistence)

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp env.example .env
# Edit .env with your API keys

# Run the server
uvicorn app.main:app --reload
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

The app will be at `http://localhost:5173`

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the `backend/` directory:

```env
# Daily.co (video calls)
DAILY_API_KEY=your_daily_api_key

# Deepgram (speech-to-text)
DEEPGRAM_API_KEY=your_deepgram_key

# OpenAI (LLM)
OPENAI_API_KEY=your_openai_key

# ElevenLabs (text-to-speech)
ELEVENLABS_API_KEY=your_elevenlabs_key

# Browserbase (browser automation)
BROWSERBASE_API_KEY=your_browserbase_key
BROWSERBASE_PROJECT_ID=your_project_id
```

### Company Personas

Create YAML files in `backend/app/personas/` to customize the AI for different companies:

```yaml
# persona_mycompany.yaml

name: "Alex"
company: "MyCompany"
role: "Product Specialist"

tone: "friendly, professional, enthusiastic"
speaking_style: "concise and conversational"

product_name: "MyProduct"
product_description: "An amazing solution for..."

greeting_template: "Hey {user_name}! Ready for a quick tour?"

# Navigation structure
home_url: "https://myproduct.com/dashboard"
site_map:
  - section: "features"
    keywords: ["features", "capabilities", "what can it do"]
    button_text: "Features"

# Screen descriptions for context-aware responses
screens:
  dashboard:
    name: "Dashboard"
    description: "Main dashboard showing..."
    purpose: "Your central hub for..."

# Closing flow
closing:
  founder_name: "Jane"
  calendly_url: "https://calendly.com/jane/30min"
  closing_message: "Thanks for checking this out! Want to chat with {founder_name}?"
```

### Demo Playbooks

Create YAML files in `backend/app/playbooks/` for scripted demos:

```yaml
# mycompany_demo.yaml

meta:
  company_id: "persona_mycompany"
  name: "Full Product Demo"
  start_url: "https://myproduct.com/dashboard"

triggers:
  - "give me a demo"
  - "show me everything"
  - "full tour"

steps:
  - id: "intro"
    screen: "dashboard"
    narrate_intent: "welcome user to the dashboard"

  - id: "show_features"
    screen: "features"
    action:
      type: "click"
      target: "Features"
    narrate_intent: "explain the key features"

  - id: "closing"
    narrate_intent: "wrap up and ask if they have questions"
```

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/rooms` | Create a new room |
| GET | `/api/v1/rooms/{name}` | Get room details |
| DELETE | `/api/v1/rooms/{name}` | Delete a room |
| POST | `/api/v1/rooms/token` | Create meeting token |
| POST | `/api/v1/agent/join/{room}` | Spawn AI agent in room |
| POST | `/api/v1/agent/leave/{room}` | Remove AI agent from room |
| GET | `/api/v1/agent/status/{room}` | Check agent status |
| GET | `/health` | Health check |

## 📁 Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── rooms.py          # Room management
│   │   │   └── agent.py          # AI agent control
│   │   ├── core/
│   │   │   └── config.py         # Settings
│   │   ├── personas/
│   │   │   └── persona_*.yaml    # Company personas
│   │   ├── playbooks/
│   │   │   └── *.yaml            # Demo playbooks
│   │   ├── services/
│   │   │   ├── ai_agent.py       # Main orchestrator
│   │   │   ├── planner_service.py    # Navigation planning
│   │   │   ├── presenter_service.py  # Response generation
│   │   │   ├── intent_service.py     # Intent detection
│   │   │   ├── browser_service.py    # Browser control
│   │   │   ├── demo_runner.py        # Playbook execution
│   │   │   ├── calendly_service.py   # Scheduling
│   │   │   ├── perception_service.py # DOM extraction
│   │   │   ├── llm_service.py        # OpenAI wrapper
│   │   │   ├── tts_service.py        # ElevenLabs TTS
│   │   │   ├── memory_service.py     # Firebase memory
│   │   │   └── daily_service.py      # Daily.co API
│   │   └── main.py               # FastAPI app
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── HomePage.tsx      # Room creation
│   │   │   └── DemoRoom.tsx      # Video call
│   │   ├── components/
│   │   │   ├── VideoRoom.tsx     # Call interface
│   │   │   ├── BrowserView.tsx   # Live browser embed
│   │   │   └── ...
│   │   ├── services/
│   │   │   └── api.ts            # Backend client
│   │   └── App.tsx
│   └── package.json
│
└── README.md
```

## 🔑 Key Features

### Intelligent Navigation
The Planner uses LLM reasoning to understand user intent and create multi-step navigation plans. It matches requests like "show me the pricing" to the appropriate section using keyword matching and site structure.

### Barge-In Support
Users can interrupt the AI at any time. The system detects speech during AI output and gracefully stops the current plan, allowing natural conversation flow.

### Parallel Execution
During demos, browser actions and LLM narration generation run simultaneously, reducing perceived latency.

### Multi-Tenant Personas
Each company can have its own persona configuration with custom:
- Name, tone, and speaking style
- Product knowledge and objection handling
- Site structure and navigation
- Screen descriptions for context-aware responses
- Closing flow with Calendly integration

### Conversation Memory
Firebase Firestore stores conversation history per room, allowing the AI to maintain context across the call and reference previous messages.

## 📝 License

MIT
