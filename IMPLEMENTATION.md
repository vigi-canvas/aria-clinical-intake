# Clinical Intake Voice Agent — Implementation Handoff

## Overview

Build a web-based clinical intake voice agent that conducts a structured pre-visit interview with a simulated patient and generates a structured clinical brief (CC, HPI, ROS) at the end. The conversation must be production-quality — medically accurate, resilient, and complete. The demo medium is a browser with a microphone; the conversation logic is what would be deployed on a real call.

**Time box:** 4–5 hours  
**Output:** Working app + GitHub repo (Loom video recorded separately by human)

---

## Stack

| Layer | Technology |
|---|---|
| Voice pipeline | Gemini 2.5 Flash Live API (bidirectional WebSocket — handles STT + LLM + TTS in one) |
| Brief generation | Gemini 2.5 Flash REST (structured JSON extraction from transcript) |
| Backend | Python FastAPI + uvicorn |
| Auth | Google service account JSON at project root (`service_account.json`) |
| Frontend | Single `static/index.html` — vanilla JS, no frameworks |
| Config | `.env` via python-dotenv |

---

## Project Layout

```
clinical-intake-agent/
├── main.py                  # FastAPI app, WebSocket /ws/session
├── session.py               # GeminiLiveSession — wraps Gemini Live WebSocket
├── state_machine.py         # IntakeStateMachine — phases, OLDCARTS tracking, ROS mapping
├── prompts.py               # All system prompts (per-phase, brief extraction)
├── brief_generator.py       # Sends transcript to Gemini REST, returns structured JSON
├── auth.py                  # Loads service_account.json, returns google.oauth2 Credentials
├── static/
│   └── index.html           # Full frontend: mic capture, WS client, audio playback, brief panel
├── tests/
│   └── test_state_machine.py
├── requirements.txt
├── .env                     # Never commit
├── .gitignore               # Must include: service_account.json, .env, __pycache__
└── service_account.json     # Provided at runtime — never commit
```

---

## Environment Variables (`.env`)

```
GOOGLE_PROJECT_ID=your-gcp-project-id
GOOGLE_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash-preview
GOOGLE_APPLICATION_CREDENTIALS=service_account.json
```

---

## Dependencies (`requirements.txt`)

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
websockets==12.0
google-genai==1.0.0
google-auth==2.29.0
python-dotenv==1.0.1
httpx==0.27.0
pydantic==2.7.0
pytest==8.0.0
pytest-asyncio==0.23.0
```

GCP APIs to enable on the project:
- `aiplatform.googleapis.com`
- `generativelanguage.googleapis.com`

Service account needs role: `roles/aiplatform.user`

---

## Run

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# Open: http://localhost:8000/static/index.html
```

---

## Clinical Intake Flow

The agent (named **Aria**) progresses through 5 phases in strict order. The Python state machine controls phase transitions — Gemini only generates natural language within the current phase.

```
GREETING → CHIEF_COMPLAINT → HPI → ROS → CLOSING → [generate brief]
```

### Phase Details

| Phase | Gemini's Job | Completion Criteria |
|---|---|---|
| GREETING | Introduce as Aria, explain purpose, ask patient name | `patient_name` is set |
| CHIEF_COMPLAINT | Ask open-ended "What brings you in today?" | `chief_complaint` is set |
| HPI | Collect all 9 OLDCARTS fields one at a time, conversationally | All 9 OLDCARTS fields set (or marked N/A) |
| ROS | Ask about pertinent systems based on chief complaint | All mapped systems reviewed |
| CLOSING | Thank patient, confirm no urgent symptoms, end call | Closing spoken — trigger brief generation |

---

## `state_machine.py` — Full Spec

```python
OLDCARTS_FIELDS = [
    'onset',        # When did it start?
    'location',     # Where exactly?
    'duration',     # How long per episode?
    'character',    # Sharp, dull, burning, pressure?
    'aggravating',  # What makes it worse?
    'alleviating',  # What makes it better?
    'radiation',    # Does it spread anywhere?
    'timing',       # Constant or intermittent?
    'severity',     # 1–10 scale
]

# Chief complaint category → ROS systems to cover
CC_TO_ROS_MAP = {
    'chest_pain':   ['cardiovascular', 'respiratory', 'gastrointestinal', 'musculoskeletal', 'constitutional'],
    'headache':     ['neurological', 'ent', 'ophthalmological', 'constitutional', 'psychiatric'],
    'abdominal':    ['gastrointestinal', 'genitourinary', 'constitutional', 'gynecological'],
    'dyspnea':      ['respiratory', 'cardiovascular', 'constitutional', 'musculoskeletal'],
    'joint_pain':   ['musculoskeletal', 'constitutional', 'dermatological', 'immunological'],
    'cough':        ['respiratory', 'ent', 'constitutional', 'cardiovascular'],
    'default':      ['constitutional', 'cardiovascular', 'respiratory', 'gastrointestinal', 'neurological'],
}

class IntakeStateMachine:
    def __init__(self):
        self.phase = 'GREETING'
        self.patient_name: str | None = None
        self.chief_complaint: str | None = None
        self.cc_category: str = 'default'       # set after CC phase
        self.hpi_fields: dict = {f: None for f in OLDCARTS_FIELDS}
        self.ros_systems: list[str] = []         # populated on HPI→ROS transition
        self.ros_data: dict = {}                 # system → {'positive': [], 'negative': []}
        self.transcript: list[dict] = []         # {'role': 'agent'|'patient', 'text': str}

    def hpi_complete(self) -> bool:
        return all(v is not None for v in self.hpi_fields.values())

    def ros_complete(self) -> bool:
        return all(s in self.ros_data for s in self.ros_systems)

    def advance_phase(self):
        order = ['GREETING', 'CHIEF_COMPLAINT', 'HPI', 'ROS', 'CLOSING', 'DONE']
        idx = order.index(self.phase)
        if idx < len(order) - 1:
            self.phase = order[idx + 1]
            if self.phase == 'ROS':
                self.ros_systems = CC_TO_ROS_MAP.get(self.cc_category, CC_TO_ROS_MAP['default'])

    def set_hpi_field(self, field: str, value: str):
        if field in self.hpi_fields:
            self.hpi_fields[field] = value

    def mark_na_if_unknown(self, field: str):
        """Call when patient says 'I don't know' — never loop on this field again."""
        self.hpi_fields[field] = 'N/A'

    def append_transcript(self, role: str, text: str):
        import datetime
        self.transcript.append({
            'role': role,
            'text': text,
            'timestamp': datetime.datetime.utcnow().isoformat()
        })

    def get_system_prompt(self) -> str:
        """Returns the full system prompt for the current phase."""
        from prompts import build_system_prompt
        return build_system_prompt(self)
```

**Resilience rules the state machine must enforce:**
- If patient answers multiple OLDCARTS fields in one response → mark all answered fields, skip those questions
- If patient says "I don't know" / "not sure" → call `mark_na_if_unknown()`, move on, never re-ask
- If patient gives a partial answer → field stays None, Gemini probes once more with a gentle rephrasing, then marks N/A after second non-answer
- Phase only advances when completion criteria are met — never skip a phase

---

## `prompts.py` — Full Spec

Build a `build_system_prompt(sm: IntakeStateMachine) -> str` function that returns the full system instruction for the current phase.

### Base Prompt (always prepended)

```
You are Aria, an AI clinical intake assistant for a primary care practice.
Your role is to conduct a structured pre-visit medical intake with the patient
before they see their physician. You are warm, professional, empathetic, and speak clearly.

CRITICAL RULES — follow these without exception:
1. Ask ONE question at a time. Never ask two questions in the same response.
2. Listen to the patient's full response before asking the next question.
3. Keep responses concise — this is a voice conversation, not a written note.
4. If a patient seems in pain or distress, acknowledge it before proceeding.
5. Never provide medical advice, diagnoses, or treatment recommendations.
6. EMERGENCY RULE: If the patient describes any of the following, IMMEDIATELY say
   "I'm concerned about what you're describing. Please call 911 or go to your nearest
   emergency room right now. Do not wait for this appointment." — then end the session:
   - Crushing chest pain with arm/jaw radiation
   - Severe difficulty breathing at rest
   - Sudden severe headache ("worst of my life")
   - Signs of stroke (facial droop, arm weakness, speech difficulty)
   - Uncontrolled bleeding
7. If the patient says "I don't know" or cannot answer a question, acknowledge it
   naturally and move to the next question. Do not repeat the same question.
```

### Phase-Specific Additions

**GREETING:**
```
Introduce yourself: "Hello, I'm Aria, an AI clinical assistant for your upcoming
visit. I'll ask you a few questions so your doctor is prepared when you meet.
This should take about 5 minutes. Could I start with your name?"
```

**CHIEF_COMPLAINT:**
```
Ask an open-ended question to learn the patient's primary concern.
Good: "What brings you in today — what's the main thing you'd like to address?"
Let the patient describe fully before asking anything else.
The chief complaint should be in the patient's own words.
```

**HPI — OLDCARTS:**
```
You are now gathering the History of Present Illness.
Collect the following fields, one at a time, in natural conversational order.
Adapt the wording to what the patient has told you — do not read these as a list.

Fields to collect (in roughly this order, but be flexible):
  onset       — When did this start? Was it sudden or gradual?
  location    — Where exactly do you feel it?
  duration    — How long does it last when it happens?
  character   — How would you describe it? (sharp, dull, burning, pressure, aching)
  aggravating — What makes it worse?
  alleviating — What makes it better? Have you tried anything for relief?
  radiation   — Does it spread or move anywhere else?
  timing      — Is it constant or does it come and go? Any pattern?
  severity    — On a scale of 1 to 10, how would you rate it right now?

Already collected fields: {list collected OLDCARTS fields and their values here}
Still needed: {list remaining fields here}

When all fields are collected, say: "Thank you, that's really helpful."
```

**ROS — inject the pertinent systems list:**
```
You are now conducting a Review of Systems.
Ask about the following body systems only: {list ros_systems here}

For each system, ask 2–3 targeted yes/no questions, then move on.
Examples:
  cardiovascular: palpitations, chest tightness, ankle swelling, lightheadedness
  respiratory: shortness of breath, wheezing, cough, sputum
  gastrointestinal: heartburn, nausea, vomiting, abdominal pain, changes in bowel habits
  neurological: headaches, dizziness, numbness, tingling, vision changes
  constitutional: fever, chills, fatigue, unintentional weight loss, night sweats

Record both POSITIVE findings (symptoms present) and PERTINENT NEGATIVES (symptoms absent).
Move through all systems before transitioning to closing.
```

**CLOSING:**
```
Thank the patient warmly. Confirm: "Is there anything else you'd like your doctor to know
about today?" Then say: "We're all set. Your doctor will review this before your visit.
Thank you for your time, and we look forward to seeing you soon."
```

---

## `auth.py` — Full Spec

```python
import os
from google.oauth2 import service_account

SCOPES = [
    'https://www.googleapis.com/auth/cloud-platform',
]

def get_credentials():
    sa_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'service_account.json')
    if not os.path.exists(sa_path):
        raise FileNotFoundError(
            f"Service account JSON not found at '{sa_path}'. "
            "Place service_account.json in the project root or set "
            "GOOGLE_APPLICATION_CREDENTIALS in .env"
        )
    return service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
```

---

## `session.py` — Full Spec

Wraps the Gemini Live API WebSocket session. One instance per connected browser client.

```python
import asyncio, base64, os, json
from google import genai
from google.genai import types
from state_machine import IntakeStateMachine
from prompts import build_system_prompt
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.environ['GOOGLE_PROJECT_ID']
LOCATION   = os.environ.get('GOOGLE_LOCATION', 'us-central1')
MODEL      = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash-preview')

class GeminiLiveSession:
    def __init__(self, sm: IntakeStateMachine, credentials):
        self.sm = sm
        self.credentials = credentials
        self._session = None
        self._client = None

    async def start(self):
        self._client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location=LOCATION,
            credentials=self.credentials,
        )
        config = types.LiveConnectConfig(
            response_modalities=['AUDIO'],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name='Aoede')
                )
            ),
            system_instruction=build_system_prompt(self.sm),
        )
        self._session = await self._client.aio.live.connect(
            model=MODEL,
            config=config,
        ).__aenter__()

    async def update_system_prompt(self):
        """Call after each phase transition to inject new phase instructions."""
        # Gemini Live supports updating system instructions mid-session
        # If not supported, close and reopen session with new prompt (acceptable latency)
        pass  # implement based on SDK version capabilities

    async def send_audio(self, pcm_bytes: bytes):
        """Send raw PCM 16kHz mono audio from browser mic."""
        await self._session.send(
            input=types.LiveClientRealtimeInput(
                media_chunks=[types.Blob(
                    mime_type='audio/pcm;rate=16000',
                    data=pcm_bytes,
                )]
            )
        )

    async def receive(self):
        """
        Async generator. Yields dicts:
          {'type': 'audio', 'data': '<base64 PCM>'}
          {'type': 'transcript', 'role': 'agent'|'patient', 'text': '...'}
          {'type': 'turn_complete'}
        """
        async for response in self._session.receive():
            if response.data:
                yield {'type': 'audio', 'data': base64.b64encode(response.data).decode()}
            if response.text:
                self.sm.append_transcript('agent', response.text)
                yield {'type': 'transcript', 'role': 'agent', 'text': response.text}
            if response.server_content and response.server_content.turn_complete:
                yield {'type': 'turn_complete'}

    async def close(self):
        if self._session:
            await self._session.__aexit__(None, None, None)
```

**Audio format:** Browser must send PCM 16-bit signed, 16kHz, mono (little-endian). Gemini Live returns PCM 24kHz. The frontend handles the sample rate difference via Web Audio API.

---

## `brief_generator.py` — Full Spec

```python
import json, os
from google import genai
from dotenv import load_dotenv

load_dotenv()

BRIEF_PROMPT = """
You are a clinical documentation assistant. Given the following patient intake
conversation transcript, extract a structured clinical brief in JSON format.

Output ONLY valid JSON matching this schema exactly — no markdown, no explanation:
{
  "patient_name": "string",
  "chief_complaint": {
    "statement": "Patient's own words describing their main concern",
    "onset_of_complaint": "How long they have had this problem overall"
  },
  "hpi": {
    "onset": "string or null",
    "location": "string or null",
    "duration": "string or null",
    "character": "string or null",
    "aggravating_factors": "string or null",
    "alleviating_factors": "string or null",
    "radiation": "string or null",
    "timing": "string or null",
    "severity": "string (e.g. '7/10') or null"
  },
  "ros": {
    "<system_name>": {
      "positive": ["list of symptoms patient confirmed present"],
      "negative": ["list of pertinent symptoms patient denied"]
    }
  },
  "clinical_narrative": "2–3 sentence clinical summary written as a clinician would document it. Include chief complaint, key HPI findings, and notable ROS positives and pertinent negatives.",
  "flags": ["Any urgent or notable items the clinician should be aware of (empty list if none)"]
}

Use null for any HPI field the patient could not answer.
Use clinical terminology in the narrative (e.g. 'exertional dyspnea', 'pleuritic chest pain').

Transcript:
{transcript}
"""

async def generate_brief(transcript: list[dict], credentials) -> dict:
    """
    Takes the session transcript list and returns a structured clinical brief dict.
    Raises ValueError if JSON parsing fails — caller should handle gracefully.
    """
    text_transcript = '\n'.join(
        f"{t['role'].upper()}: {t['text']}" for t in transcript
    )
    prompt = BRIEF_PROMPT.replace('{transcript}', text_transcript)

    client = genai.Client(
        vertexai=True,
        project=os.environ['GOOGLE_PROJECT_ID'],
        location=os.environ.get('GOOGLE_LOCATION', 'us-central1'),
        credentials=credentials,
    )
    response = await client.aio.models.generate_content(
        model=os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash-preview'),
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type='application/json',
            temperature=0.1,   # low temp for structured extraction
        ),
    )
    try:
        return json.loads(response.text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Brief extraction returned invalid JSON: {e}\nRaw: {response.text}")
```

---

## `main.py` — Full Spec

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import asyncio, json, os
from dotenv import load_dotenv

from auth import get_credentials
from state_machine import IntakeStateMachine
from session import GeminiLiveSession
from brief_generator import generate_brief

load_dotenv()

app = FastAPI(title="Clinical Intake Voice Agent")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.websocket("/ws/session")
async def ws_session(websocket: WebSocket):
    await websocket.accept()
    creds = get_credentials()
    sm = IntakeStateMachine()
    session = GeminiLiveSession(sm, creds)
    brief_sent = False

    try:
        await session.start()

        # Send initial phase info to frontend
        await websocket.send_json({'type': 'phase', 'phase': sm.phase})

        async def receive_from_browser():
            """Read raw PCM bytes from browser, forward to Gemini Live."""
            async for message in websocket.iter_bytes():
                await session.send_audio(message)
                # Also capture patient speech text via Gemini transcript events

        async def send_to_browser():
            """Forward Gemini responses to browser. Manage phase transitions."""
            nonlocal brief_sent
            async for chunk in session.receive():
                await websocket.send_json(chunk)

                # After each agent turn, check if phase should advance
                if chunk['type'] == 'turn_complete':
                    _check_and_advance_phase(sm, session)
                    await websocket.send_json({'type': 'phase', 'phase': sm.phase})

                    if sm.phase == 'DONE' and not brief_sent:
                        brief_sent = True
                        try:
                            brief = await generate_brief(sm.transcript, creds)
                            await websocket.send_json({'type': 'brief', 'data': brief})
                        except ValueError as e:
                            # Brief extraction failed — send raw transcript as fallback
                            await websocket.send_json({
                                'type': 'brief_error',
                                'message': str(e),
                                'transcript': sm.transcript
                            })
                        break

        await asyncio.gather(receive_from_browser(), send_to_browser())

    except WebSocketDisconnect:
        pass  # clean client disconnect
    except Exception as e:
        try:
            await websocket.send_json({'type': 'error', 'code': 'SESSION_ERROR', 'message': str(e)})
        except Exception:
            pass
    finally:
        await session.close()


def _check_and_advance_phase(sm: IntakeStateMachine, session: GeminiLiveSession):
    """Advance phase if completion criteria met. Called after each agent turn."""
    current = sm.phase
    if current == 'GREETING' and sm.patient_name:
        sm.advance_phase()
    elif current == 'CHIEF_COMPLAINT' and sm.chief_complaint:
        sm.advance_phase()
    elif current == 'HPI' and sm.hpi_complete():
        sm.advance_phase()
    elif current == 'ROS' and sm.ros_complete():
        sm.advance_phase()
    elif current == 'CLOSING':
        sm.advance_phase()  # advance to DONE after closing turn
```

---

## `static/index.html` — Full Spec

Single file. No external JS dependencies. Use inline `<script>` and `<style>`.

### Layout

```
┌─────────────────────────────────────────────┐
│  Clinical Intake — Aria                     │
│  ┌───────────────────────────────────────┐  │
│  │  Phase indicator (e.g. "HPI — OLDCARTS") │
│  └───────────────────────────────────────┘  │
│                                             │
│  [ Start Session ]  [ End Session ]        │
│                                             │
│  Status: "Listening..." / "Aria speaking"  │
│                                             │
│  ── Live Transcript ──────────────────────  │
│  ARIA: Hello, I'm Aria...                  │
│  PATIENT: I have chest pain...             │
│  ...                                       │
│                                             │
│  ── Clinical Brief ───────────────────────  │
│  (hidden until session ends)               │
│  Chief Complaint: ...                      │
│  HPI: [table of OLDCARTS fields]           │
│  ROS: [system by system]                   │
│  Narrative: ...                            │
└─────────────────────────────────────────────┘
```

### JavaScript Implementation

```javascript
// === Audio capture ===
// Use ScriptProcessorNode (or AudioWorklet) to capture PCM 16-bit 16kHz from mic
// Convert Float32 samples to Int16 PCM before sending

function floatTo16BitPCM(float32Array) {
    const buffer = new ArrayBuffer(float32Array.length * 2);
    const view = new DataView(buffer);
    for (let i = 0; i < float32Array.length; i++) {
        const s = Math.max(-1, Math.min(1, float32Array[i]));
        view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true); // little-endian
    }
    return buffer;
}

// Mic → PCM → WebSocket
const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
const audioCtx = new AudioContext({ sampleRate: 16000 });
const source = audioCtx.createMediaStreamSource(stream);
const processor = audioCtx.createScriptProcessor(4096, 1, 1);
processor.onaudioprocess = (e) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        const pcm = floatTo16BitPCM(e.inputBuffer.getChannelData(0));
        ws.send(pcm);
    }
};
source.connect(processor);
processor.connect(audioCtx.destination);

// === Audio playback ===
// Gemini returns PCM 24kHz. Decode base64 → Int16 → Float32 → play via AudioContext

async function playPCMAudio(base64Data, sampleRate = 24000) {
    const binary = atob(base64Data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const int16 = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;
    const buffer = playCtx.createBuffer(1, float32.length, sampleRate);
    buffer.getChannelData(0).set(float32);
    const src = playCtx.createBufferSource();
    src.buffer = buffer;
    src.connect(playCtx.destination);
    src.start();
}

// === WebSocket message handler ===
ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    switch (msg.type) {
        case 'audio':
            playPCMAudio(msg.data);
            setStatus('Aria speaking...');
            break;
        case 'transcript':
            appendTranscript(msg.role, msg.text);
            if (msg.role === 'patient') setStatus('Listening...');
            break;
        case 'phase':
            updatePhaseIndicator(msg.phase);
            break;
        case 'brief':
            renderBrief(msg.data);   // show formatted clinical note
            break;
        case 'brief_error':
            renderBriefError(msg.transcript);
            break;
        case 'error':
            showError(msg.message);
            break;
    }
};

// === Brief rendering ===
// renderBrief(data) should show:
// 1. Chief Complaint section
// 2. HPI table: one row per OLDCARTS field (field name | patient report)
// 3. ROS section: one subsection per system, positives in green, negatives in gray
// 4. Clinical Narrative paragraph (styled as a clinical note)
// 5. Flags (if any) in amber/orange
// Also render raw JSON in a collapsible <details> block below
```

---

## `tests/test_state_machine.py` — Required Tests

Write these tests. They must pass before touching any API code.

```python
# All tests use no API calls — pure Python state machine logic

def test_phase_transitions_full_sequence():
    sm = IntakeStateMachine()
    assert sm.phase == 'GREETING'
    sm.patient_name = 'Michael'
    sm.advance_phase(); assert sm.phase == 'CHIEF_COMPLAINT'
    sm.chief_complaint = 'chest pain'
    sm.advance_phase(); assert sm.phase == 'HPI'
    for f in OLDCARTS_FIELDS: sm.set_hpi_field(f, 'test value')
    assert sm.hpi_complete()
    sm.advance_phase(); assert sm.phase == 'ROS'
    assert len(sm.ros_systems) > 0   # populated on HPI→ROS transition

def test_hpi_not_complete_when_fields_missing():
    sm = IntakeStateMachine()
    sm.set_hpi_field('onset', 'two days ago')
    assert not sm.hpi_complete()

def test_na_counts_as_complete():
    sm = IntakeStateMachine()
    for f in OLDCARTS_FIELDS: sm.mark_na_if_unknown(f)
    assert sm.hpi_complete()

def test_cc_to_ros_chest_pain():
    sm = IntakeStateMachine()
    sm.patient_name = 'Test'
    sm.chief_complaint = 'chest pain'; sm.cc_category = 'chest_pain'
    sm.advance_phase(); sm.advance_phase()   # → HPI → ROS
    assert 'cardiovascular' in sm.ros_systems
    assert 'respiratory' in sm.ros_systems

def test_cc_to_ros_default_fallback():
    sm = IntakeStateMachine()
    sm.patient_name = 'Test'; sm.chief_complaint = 'something unusual'
    sm.cc_category = 'default'
    sm.advance_phase(); sm.advance_phase()
    assert sm.ros_systems == CC_TO_ROS_MAP['default']

def test_transcript_logging():
    sm = IntakeStateMachine()
    sm.append_transcript('agent', 'Hello')
    sm.append_transcript('patient', 'Hi')
    assert len(sm.transcript) == 2
    assert sm.transcript[0]['role'] == 'agent'
    assert sm.transcript[1]['text'] == 'Hi'

def test_auth_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS', str(tmp_path / 'missing.json'))
    from auth import get_credentials
    import pytest
    with pytest.raises(FileNotFoundError):
        get_credentials()
```

---

## Error Handling Rules

| Error | Where | Behaviour |
|---|---|---|
| `service_account.json` missing | `auth.py` startup | Raise `FileNotFoundError` with clear message — fail fast |
| Gemini Live connect fails | `session.py start()` | Let exception propagate to `main.py` → send `{type: 'error'}` to browser |
| Gemini Live drops mid-session | `session.py receive()` | Catch exception, yield `{type: 'error', code: 'SESSION_DROPPED'}` — browser shows reconnect option |
| Brief JSON parse fails | `brief_generator.py` | Raise `ValueError` → `main.py` catches, sends `brief_error` with raw transcript as fallback |
| Patient describes emergency | Gemini (via system prompt) | Agent speaks emergency redirect — `main.py` listens for `EMERGENCY` sentinel in transcript, advances to DONE |
| Browser mic denied | `static/index.html` | Catch `getUserMedia` rejection, show banner: "Microphone access is required to use this service" |
| Browser disconnects | `main.py WebSocketDisconnect` | Log, clean up session, no error |

---

## CC Category Classification

After the CHIEF_COMPLAINT phase, classify the CC into a category for ROS mapping. Do this with a lightweight Gemini call (or simple keyword matching as fallback):

```python
def classify_cc(chief_complaint: str) -> str:
    """Map CC text to a CC_TO_ROS_MAP key. Keyword fallback — replace with Gemini call if time allows."""
    cc = chief_complaint.lower()
    if any(w in cc for w in ['chest', 'heart', 'cardiac', 'palpitation']): return 'chest_pain'
    if any(w in cc for w in ['head', 'migraine', 'headache']): return 'headache'
    if any(w in cc for w in ['abdomen', 'abdominal', 'stomach', 'belly', 'nausea', 'vomit']): return 'abdominal'
    if any(w in cc for w in ['breath', 'breathe', 'breathing', 'shortness', 'dyspnea']): return 'dyspnea'
    if any(w in cc for w in ['joint', 'knee', 'hip', 'shoulder', 'back', 'muscle', 'pain']): return 'joint_pain'
    if any(w in cc for w in ['cough', 'wheez', 'throat']): return 'cough'
    return 'default'
```

Call this immediately when `chief_complaint` is set, before advancing to HPI.

---

## Build Phases — Do These In Order

### Phase 1 (~45 min): Scaffold + Auth
- Create all files/folders
- Write `requirements.txt`, `.env.example`, `.gitignore`
- Implement `auth.py`
- Verify: `python -c "from auth import get_credentials; print(get_credentials())"` works with service_account.json present

### Phase 2 (~60 min): State Machine + Tests
- Implement `state_machine.py` fully
- Implement `classify_cc()`
- Write and run all tests in `tests/test_state_machine.py`
- All tests must pass before Phase 3

### Phase 3 (~60 min): Prompts + Gemini Live Session
- Implement `prompts.py` with `build_system_prompt(sm)`
- Implement `session.py`
- Quick test: Python script that opens a Gemini Live session and prints the greeting text response

### Phase 4 (~45 min): FastAPI Backend
- Implement `main.py` fully
- Implement `brief_generator.py`
- Test with `wscat` or a minimal browser test page sending canned bytes

### Phase 5 (~45 min): Frontend
- Implement `static/index.html` with mic capture, WebSocket, playback, brief rendering
- Full end-to-end browser test

### Phase 6 (~30 min): Integration Polish
- Run 2–3 complete simulated patient sessions
- Verify OLDCARTS coverage (all 9 fields collected)
- Verify brief JSON structure (all keys present)
- Fix any prompt drift or phase transition bugs
- Verify brief renders cleanly in browser for Loom demo

---

## Git Setup

```bash
git init
git add .
# Verify service_account.json and .env are NOT staged:
git status | grep -E "service_account|\.env"  # should be empty
git commit -m "feat: clinical intake voice agent"
```

`.gitignore` must contain:
```
service_account.json
.env
__pycache__/
*.pyc
.pytest_cache/
```

---

## Loom Demo Script (5 min)

The human will record this — no code needed, just ensure the flow works:

1. Open browser, click Start Session
2. Hear Aria greet and ask for name → respond
3. Hear CC question → "I've been having chest pain for about a week"
4. Go through OLDCARTS naturally (Aria asks one at a time)
5. ROS questions for cardiac, respiratory, GI
6. Hear closing → session ends
7. Brief panel appears showing structured CC, HPI table, ROS findings, clinical narrative
8. Show raw JSON alongside
9. Point out: "this is what a clinician sees before the visit"

---

## Key Decisions (Do Not Change)

| Decision | Choice | Reason |
|---|---|---|
| Voice pipeline | Gemini 2.5 Flash Live API | Single API handles STT + LLM + TTS — no pipeline errors, richer understanding |
| Flow control | Explicit Python state machine | Deterministic — every OLDCARTS field collected every time |
| HPI framework | OLDCARTS (9 fields) | US clinical standard for history of present illness |
| ROS scope | Pertinent systems only (CC-driven) | Clinically correct, demo-appropriate |
| Brief format | JSON + browser-rendered HTML | Machine-readable + visually clear for Loom demo |
| Auth | Service account JSON at root | Direct, portable, no gcloud CLI required |
| Frontend | Vanilla JS, no framework | Fast to build, nothing to configure or compile |
