# Karumi - AI Sales Demo Agent

## Demos
- **Part 1**: https://www.loom.com/share/5e391d35f95744dcafb5feab357eeccf
- **Part 2**: https://www.loom.com/share/237c26392fc44251b36d6f4a86c0e534
- **Part 3**: https://www.loom.com/share/5dcb43800c4b43eabcddcc1ab501c75f
- **Part 4**: https://www.loom.com/share/6ab31df460ce42e6bf24de123d0954a1

## 🚀 Try It Live

**Deployed version:** [sales-ai-assistant-do5t.vercel.app](https://sales-ai-assistant-do5t.vercel.app)

### Quick Test Setup

1. **Product Page URL:** `https://healing-path.vercel.app/signin`
2. **AI Persona:** Select "Healing Path"
3. Click **Create New Room** and join the meeting

### Important: Manual Login Required

When you join, you'll see a browser showing the Healing Path login page. **Sign in manually** before speaking to the AI:

- **Email:** `mb5165@columbia.edu`
- **Password:** `StU111@2015`

> ⚠️ **Don't speak until you've signed in!** The AI expects to start on the dashboard, not the login page. The AI will speak first asking you if you want a demo. You can reply to that once logged in.

---

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

The AI uses a layered architecture where specialized services work together. This is a **real-time voice agent** that listens, thinks, acts, and speaks—all concurrently.

### Core Agent Loop

The agent runs a continuous audio pipeline with concurrent processing:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           REAL-TIME AUDIO PIPELINE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Daily.co Call                Deepgram Flux              Response          │
│   ┌─────────┐                  ┌─────────┐               ┌─────────┐       │
│   │ Virtual │   raw audio      │  STT +  │  transcript   │ Orchestr│       │
│   │ Speaker │ ──────────────▶  │  Turn   │ ───────────▶  │  ator   │       │
│   │ Device  │   (16kHz PCM)    │ Detect  │   (queue)     │         │       │
│   └─────────┘                  └─────────┘               └────┬────┘       │
│                                                               │             │
│   ┌─────────┐                  ┌─────────┐               ┌────▼────┐       │
│   │ Virtual │   TTS audio      │Eleven   │   text        │  LLM    │       │
│   │   Mic   │ ◀──────────────  │  Labs   │ ◀───────────  │ + Plan  │       │
│   │ Device  │   (streamed)     │   TTS   │               │         │       │
│   └─────────┘                  └─────────┘               └─────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Three concurrent loops run simultaneously:**
1. **Audio Receive Loop** (`_audio_receive_loop`): Captures audio from Daily virtual speaker, sends to Deepgram
2. **Transcript Process Loop** (`_transcript_process_loop`): Monitors transcript queue, triggers response after 1s silence
3. **Deepgram Listener** (`_run_deepgram_listener`): Receives STT results and turn detection events

**Turn Detection**: Deepgram Flux detects when the user stops speaking (end-of-turn). The agent waits 1 second of silence before responding, allowing for natural pauses.

### Decision Hierarchy

When a user speaks, the agent checks intents in **priority order**:

```
User speaks: "Sure, that sounds good"
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. CALENDLY ACTIVE?                                            │
│     └─ awaiting_scheduling_confirmation? → Open calendar        │
│     └─ awaiting_confirmation? → Process booking                 │
│     └─ awaiting_info? → Fill form fields                        │
│     └─ on_calendly? → Handle time selection                     │
└─────────────────────────────────────────────────────────────────┘
                    │ no
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. DEMO INTENT?                                                │
│     └─ LLM checks: "Does user want a FULL product tour?"        │
│     └─ If yes → Run scripted playbook                           │
└─────────────────────────────────────────────────────────────────┘
                    │ no
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. CLOSING INTENT?                                             │
│     └─ LLM checks: "Is user done/wrapping up?"                  │
│     └─ If yes → Offer to schedule call with founder             │
└─────────────────────────────────────────────────────────────────┘
                    │ no
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. NAVIGATION / CONVERSATION                                   │
│     └─ Get page context from browser                            │
│     └─ Planner creates navigation plan (or speech-only)         │
│     └─ Execute plan steps                                       │
└─────────────────────────────────────────────────────────────────┘
```

### Service Architecture

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
│  • Check for interruption before    │
│    each step (_plan_interrupted)    │
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

### How the Planner Creates Navigation Plans

The Planner is an LLM that receives rich context from both **YAML configuration files** and **live page state** to make intelligent decisions.

#### Context Injected into the Planner Prompt

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PLANNER LLM PROMPT CONTEXT                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  FROM PERSONA YAML (static config):                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  • persona_name: "Maya"                                              │   │
│  │  • persona_tone: "warm, empathetic, spiritually-minded"              │   │
│  │  • persona_style: "uses gentle language, asks reflective questions" │   │
│  │  • persona_product: "Healing Path - inner child healing app"        │   │
│  │  • site_map: [{section: "meditation", keywords: [...], button: ...}]│   │
│  │  • home_url: "https://healing-path.vercel.app/dashboard"            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  FROM LIVE PAGE (runtime extraction via Perception):                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  • available_elements: ["Listen Now", "Sacred Library", "Reply"]    │   │
│  │  • current_url: "https://healing-path.vercel.app/dashboard"         │   │
│  │  • page_title: "Your Journey - Healing Path"                        │   │
│  │  • is_on_home_page: true/false (LLM-detected)                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  FROM CONVERSATION (memory):                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  • Recent 6 messages for context                                    │   │
│  │  • Helps interpret "Sure" as response to previous AI question       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  USER REQUEST: "Show me the meditation section"                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PLANNER OUTPUT (JSON)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  {                                                                          │
│    "goal": "Navigate to meditation section",                                │
│    "target_section": "meditation",                                          │
│    "plan": [                                                                │
│      {"step": 1, "action": "speak", "details": "Let me show you that!"},   │
│      {"step": 2, "action": "click", "details": "Listen Now"},              │
│      {"step": 3, "action": "done", "details": null}                        │
│    ]                                                                        │
│  }                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Two-Phase Execution

1. **Plan Creation** (`create_navigation_plan`): LLM analyzes user request + page state → outputs JSON plan
2. **Plan Execution** (`execute_plan_step`): For each step, LLM maps action to exact clickable element

This separation allows the Planner to think strategically (what to do) while the Executor handles tactical decisions (which exact button to click).

### Demo Mode vs Freestyle Mode

The agent operates in two distinct modes:

#### **Freestyle Mode** (Default)
User-driven exploration with LLM planning on-the-fly:
- User: "Take me to the journaling section"
- Planner analyzes page, creates navigation plan
- Agent speaks → clicks → waits → explains new screen

#### **Demo Mode** (Playbook)
Scripted product tour with parallel execution:
- Triggered by: "Give me a demo" / "Show me everything"
- Loads YAML playbook with predefined steps
- **Parallel execution**: Browser action + LLM narration generation happen simultaneously
- Each step: navigate → narrate (while generating next narration)

```
┌─────────────────────────────────────────────────────────────────┐
│  DEMO MODE: Parallel Action + Narration                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step 1:  [Click "Features"] ──────────────────────────────▶   │
│           [Generate narration for step 1] ─────────────────▶   │
│                                                                 │
│  Step 2:  [Wait for page] [Speak step 1 narration] ────────▶   │
│           [Generate narration for step 2] ─────────────────▶   │
│                                                                 │
│  Step 3:  [Click "Pricing"] [Speak step 2 narration] ──────▶   │
│           ... and so on                                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Barge-In & Interruption Handling

The agent supports **barge-in**—users can interrupt at any time:

```python
# In _transcript_process_loop, when user speaks during AI action:
if self.is_speaking or self._responding:
    self._plan_interrupted = True  # Signal to stop current plan
    
# In Phase 2 execution, before each step:
for step in plan_steps:
    if self._plan_interrupted:
        print("Plan interrupted by user, stopping execution")
        break  # Stop executing, process new user input
```

**How it works:**
1. User speaks while AI is executing a plan
2. Deepgram detects speech, queues transcript
3. `_plan_interrupted` flag is set to `True`
4. Current plan execution stops at next step boundary
5. New user message is processed immediately

This allows natural conversation flow—users don't have to wait for the AI to finish before speaking.

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


