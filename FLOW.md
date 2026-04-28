# Aria — Execution Flow

## Bird's Eye View

```
Browser mic audio
      │
      ▼
FastAPI WebSocket (/ws/session)
      │
      ├──► Gemini Live API  (STT + LLM + TTS in one WebSocket)
      │         │
      │         │  streams back: audio chunks + transcripts
      │         ▼
      │    session.py receive()
      │         │  buffers text per turn, emits at turn_complete
      │         ▼
      │    main.py send_to_browser()
      │         │  forwards audio/transcript to browser
      │         │  on turn_complete → spawns background task ↓
      │
      └──► _extract_and_advance()  [runs after every agent turn]
                │
                ├── state_extractor.py  (Gemini REST call)
                │       extracts: name, CC, OLDCARTS fields, ROS, closing flag
                │
                ├── apply_extraction()  updates IntakeStateMachine fields
                │
                ├── _check_and_advance_phase()  advances phase if criteria met
                │
                ├── closing_complete=True → force jump to DONE
                │
                └── phase==DONE → generate brief → send session_complete
```

---

## Per-Turn Sequence

```
1. Patient speaks into mic
2. Browser captures 16kHz PCM → sends raw bytes over WebSocket
3. FastAPI receive_from_browser() → gemini.send_realtime_input(audio)
4. Gemini Live processes audio (STT + LLM + TTS)
5. Gemini streams back:
     - response.data          → raw PCM audio (24kHz Aria voice)
     - sc.input_transcription → patient speech text (chunked)
     - sc.output_transcription→ Aria speech text (chunked)
     - sc.turn_complete       → signals end of this turn
6. session.py buffers transcript chunks; on turn_complete emits:
     {'type': 'transcript', 'role': 'patient', 'text': '...full turn...'}
     {'type': 'transcript', 'role': 'agent',   'text': '...full turn...'}
     {'type': 'turn_complete'}
7. Both appended to sm.transcript (the running log)
8. turn_complete triggers _extract_and_advance() as asyncio background task
```

---

## State Machine Phases

```
GREETING
  │  trigger: patient_name extracted
  ▼
CHIEF_COMPLAINT
  │  trigger: chief_complaint extracted
  ▼
HPI
  │  trigger: ≥8 of 9 OLDCARTS fields filled
  ▼
ROS  ◄── ros_systems list set HERE from CC_TO_ROS_MAP[cc_category]
  │  trigger: ≥3 of expected ROS systems covered
  ▼
CLOSING
  │  trigger: immediate on entry (Aria already has the script)
  ▼       OR: closing_complete=True detected → jumps straight to DONE
DONE
  │  triggers: generate_brief() → send brief → send session_complete
  └──► stop_event set → WebSocket tears down cleanly
```

---

## Where ros_systems Gets Its Value

```
state_machine.py  __init__:   self.ros_systems = []   ← empty at start

state_machine.py  advance_phase():
    if self.phase == 'ROS':
        self.ros_systems = CC_TO_ROS_MAP[self.cc_category]
```

This runs **once**, when the phase transitions from HPI → ROS.
The list is derived from the chief complaint. Examples:

| Chief Complaint | cc_category   | ros_systems assigned                                              |
|-----------------|---------------|-------------------------------------------------------------------|
| stomach pain    | abdominal     | gastrointestinal, genitourinary, constitutional, gynecological    |
| chest tightness | chest_pain    | cardiovascular, respiratory, gastrointestinal, musculoskeletal, constitutional |
| headache        | headache      | neurological, ent, ophthalmological, constitutional, psychiatric  |
| (other)         | default       | constitutional, cardiovascular, respiratory, gastrointestinal, neurological |

---

## Key Files

| File                 | Responsibility                                                    |
|----------------------|-------------------------------------------------------------------|
| `main.py`            | FastAPI app, WebSocket handler, orchestrates all tasks            |
| `session.py`         | Wraps Gemini Live WebSocket, multi-turn receive loop              |
| `prompts.py`         | Single system prompt covering all 5 phases sent at session start  |
| `state_machine.py`   | Phase tracker, OLDCARTS fields, ROS data, transcript store        |
| `state_extractor.py` | Post-turn Gemini REST call — extracts structured fields from transcript |
| `brief_generator.py` | End-of-session Gemini REST call — produces the full clinical brief |
| `auth.py`            | Loads Google service account credentials                          |
| `static/index.html`  | Browser UI — mic capture, audio playback, transcript, brief view  |

---

## Brief Generation (end of session)

```
sm.transcript  (full list of {role, text, timestamp} dicts)
      │
      ▼
brief_generator.generate_brief()
      │  Gemini REST with response_schema (guaranteed JSON)
      ▼
{
  patient_name,
  chief_complaint: { statement, onset_of_complaint },
  hpi: { onset, location, duration, character, aggravating_factors,
         alleviating_factors, radiation, timing, severity },
  ros: { system: { positive: [...], negative: [...] }, ... },
  clinical_narrative,   ← 2-3 sentence clinical-style summary
  flags                 ← concerns / incomplete data for clinician
}
      │
      ▼
Browser renders brief cards + print button
```
