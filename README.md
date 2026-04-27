# Aria — AI Clinical Intake Agent

Aria is a voice AI agent that conducts structured pre-visit medical intake calls with patients before they see their physician. Aria calls the patient, asks all the questions, and delivers a formatted clinical brief to the physician before the appointment — no manual note-taking, no intake forms.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue) ![Gemini Live 2.5 Flash](https://img.shields.io/badge/model-gemini--live--2.5--flash-orange)

---

## What it does

Before a patient's appointment, Aria places an outbound call. The patient just speaks — Aria guides the entire conversation, collecting:

1. **Chief Complaint** — reason for the visit in the patient's own words
2. **History of Present Illness** — full OLDCARTS framework (Onset, Location, Duration, Character, Aggravating factors, Alleviating factors, Radiation, Timing, Severity)
3. **Review of Systems** — targeted to the chief complaint (e.g. chest pain triggers cardiovascular, respiratory, GI, musculoskeletal, constitutional)
4. **Closing** — confirms nothing was missed

When the call ends, the physician receives a structured clinical brief: CC, full HPI table, ROS findings with pertinent negatives, a clinical narrative written in clinical documentation style, and any flags.

---

## Production vs. this demo

| | Production | This demo |
|---|---|---|
| Patient interface | Outbound phone call (telephony integration) | Browser with microphone |
| Trigger | Automated pre-appointment scheduling | Manual — click Start Session |
| Delivery to physician | EHR / care coordination system | Rendered in the same browser window |

The conversation logic, state machine, prompts, and brief generation are identical in both. The browser interface exists to demo the full call flow without needing telephony infrastructure.

---

## Stack

| Layer | Technology |
|---|---|
| Voice (STT + LLM + TTS) | Gemini Live 2.5 Flash — bidirectional audio WebSocket |
| Brief generation | Gemini 2.5 Flash REST with `response_schema` |
| Backend | Python FastAPI + uvicorn |
| Frontend (demo) | Vanilla JS — no framework, no build step |
| Auth | Google service account |

---

## Architecture

```
Patient phone / browser mic (PCM 16kHz)
        │
        ▼
FastAPI WebSocket ──▶ Gemini Live 2.5 Flash
                              │
                        audio + transcripts
                              │
        ◀─────────────────────┘
        │
        ├── after each turn:
        │     Gemini REST → extract filled fields → update state machine
        │
        └── when session ends:
              Gemini REST → structured clinical brief → physician
```

The Python state machine controls which phase the session is in. Gemini generates natural conversation within the current phase. Phase transitions are driven by the state machine confirming completion criteria — not by Gemini.

```
GREETING → CHIEF_COMPLAINT → HPI (OLDCARTS) → ROS → CLOSING → [brief]
```

---

## Getting started

### Prerequisites

- Python 3.11+
- A GCP project with these APIs enabled:

```bash
gcloud services enable aiplatform.googleapis.com generativelanguage.googleapis.com
```

- A service account with `roles/aiplatform.user`:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SA@YOUR_PROJECT.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

- A JSON key for that service account saved as `service-account.json` in the project root

### Install

```bash
git clone https://github.com/vigi-canvas/aria-clinical-intake
cd aria-clinical-intake
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
```

Edit `.env`:

```
GOOGLE_PROJECT_ID=your-gcp-project-id
GOOGLE_LOCATION=us-central1
GEMINI_MODEL=gemini-2.5-flash
GEMINI_LIVE_MODEL=gemini-live-2.5-flash-preview
GOOGLE_APPLICATION_CREDENTIALS=service-account.json
```

### Run

```bash
uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000/static/index.html](http://localhost:8000/static/index.html), click **Start Session**, and allow microphone access to demo the call flow in the browser.

---

## Clinical brief output

```json
{
  "patient_name": "Michael Chen",
  "chief_complaint": {
    "statement": "tightness in my chest for about a week",
    "onset_of_complaint": "approximately one week"
  },
  "hpi": {
    "onset": "one week ago, gradual onset",
    "location": "central chest, retrosternal",
    "duration": "10–15 minutes per episode",
    "character": "pressure, squeezing sensation",
    "aggravating_factors": "exertion, climbing stairs",
    "alleviating_factors": "rest",
    "radiation": "left shoulder intermittently",
    "timing": "intermittent, 2–3 times daily",
    "severity": "6/10"
  },
  "ros": {
    "cardiovascular": {
      "positive": ["exertional dyspnea", "transient lightheadedness"],
      "negative": ["no palpitations", "no ankle edema", "no syncope"]
    }
  },
  "clinical_narrative": "Mr. Chen presents with a one-week history of exertional substernal chest pressure rated 6/10, occurring 2–3 times daily and lasting 10–15 minutes per episode. Symptoms are precipitated by physical activity and relieved by rest, with intermittent radiation to the left shoulder. ROS notable for exertional dyspnea and transient lightheadedness; no palpitations, peripheral edema, or diaphoresis.",
  "flags": [
    "Exertional chest pain with left shoulder radiation — cardiac evaluation indicated",
    "Family history: father MI at age 58"
  ]
}
```

---

## Project structure

```
├── main.py              # FastAPI app + WebSocket session handler
├── session.py           # Gemini Live 2.5 Flash wrapper
├── state_machine.py     # Phase tracking, OLDCARTS, ROS state
├── prompts.py           # Phase-specific system prompts
├── state_extractor.py   # Post-turn field extraction via Gemini REST
├── brief_generator.py   # Transcript → structured clinical brief
├── auth.py              # Service account credentials
├── static/index.html    # Browser demo interface
├── tests/               # 19 unit tests (no API calls)
└── .env.example
```

---

## Tests

```bash
pytest tests/ -v
```

19 tests covering state machine logic, phase transitions, OLDCARTS completion, ROS mapping, and CC classification. No API calls required.

---

## Emergency handling

If a patient describes a medical emergency during the call (crushing chest pain with radiation, stroke symptoms, severe dyspnea at rest, uncontrolled bleeding), Aria immediately says: *"I'm concerned about what you're describing. Please call 911 or go to your nearest emergency room right now. Do not wait for this appointment."*
