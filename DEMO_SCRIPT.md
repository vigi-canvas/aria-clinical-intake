# Demo Patient Script — Michael Chen, Chest Pain

Use this script to demo the full intake flow. You are playing the patient.
Respond naturally — don't read this word-for-word. Aria will ask the questions; you provide these answers.

The scenario is designed to:
- Cover all 9 OLDCARTS fields
- Trigger the **chest_pain** ROS pathway (cardiovascular, respiratory, GI, musculoskeletal, constitutional)
- Include one clinical flag (exertional symptoms + radiation)
- Demonstrate Aria handling a partial answer and an "I'm not sure"

---

## Patient Profile

**Name:** Michael Chen  
**Age:** 52  
**Scenario:** Chest tightness for one week, worse with exertion, some radiation to the left shoulder

---

## Phase 1 — Greeting

**Aria asks:** "Could I start with your name?"

**You say:**
> My name is Michael Chen.

---

## Phase 2 — Chief Complaint

**Aria asks:** "What brings you in today / what's the main thing you'd like to address?"

**You say:**
> I've been having this tightness in my chest for about a week now. It keeps coming back and I'm a bit worried about it.

---

## Phase 3 — History of Present Illness (OLDCARTS)

Aria will ask about each item below. Respond to whichever question she asks — she may ask them in a slightly different order.

---

### Onset
**Aria asks something like:** "When did this start? Did it come on suddenly or gradually?"

**You say:**
> It started about a week ago. It wasn't sudden — it kind of crept up on me. The first time I really noticed it was when I was walking up the stairs at work.

---

### Location
**Aria asks something like:** "Where exactly do you feel it?"

**You say:**
> Right here in the middle of my chest, kind of behind the breastbone. It doesn't really stay in one spot though.

*(This seeds the radiation question naturally.)*

---

### Character
**Aria asks something like:** "How would you describe the sensation?"

**You say:**
> It's like a pressure, or a tightness. Like something heavy is sitting on my chest. Not really sharp or stabbing — more like a squeezing feeling.

---

### Aggravating factors
**Aria asks something like:** "What makes it worse?"

**You say:**
> Walking up stairs or any kind of physical effort. Even walking fast on a flat surface sometimes brings it on. Stress at work seems to make it worse too.

---

### Alleviating factors
**Aria asks something like:** "What makes it better? Have you tried anything?"

**You say:**
> If I stop and rest, it goes away within maybe 10 to 15 minutes. I tried an antacid once thinking it might be heartburn, but it didn't really help.

---

### Radiation
**Aria asks something like:** "Does it spread or move to anywhere else?"

**You say:**
> Yeah actually, sometimes it goes up into my left shoulder. Not every time, but maybe once or twice it went there.

---

### Timing
**Aria asks something like:** "Is it constant or does it come and go?"

**You say:**
> It comes and goes. It's not there all the time. I'd say it happens maybe two or three times a day, usually when I'm being active.

---

### Duration
**Aria asks something like:** "When it happens, how long does it last?"

**You say:**
> Each episode is maybe 10 to 15 minutes. Sometimes a bit less if I sit down quickly.

---

### Severity
**Aria asks something like:** "On a scale of 1 to 10, how bad is it?"

**You say:**
> At its worst I'd say about a 6 out of 10. It's uncomfortable but I can push through it. That's actually part of why I waited a week to come in.

---

## Phase 4 — Review of Systems

Aria will ask about specific body systems. Answer yes/no naturally. Here are the expected questions and your answers:

---

### Cardiovascular
**Aria might ask about:** palpitations, heart racing, ankle swelling, dizziness, fainting

**You say:**
> No, my heart doesn't race or flutter. No swelling in my ankles that I've noticed. I did feel a little lightheaded once after an episode but it passed quickly.

---

### Respiratory
**Aria might ask about:** shortness of breath, wheezing, cough

**You say:**
> I do get a little short of breath when the chest tightness comes on, but only during those episodes. No wheezing, no cough.

---

### Gastrointestinal
**Aria might ask about:** heartburn, nausea, vomiting, abdominal pain

**You say:**
> I get heartburn occasionally but it feels different from this. No nausea or vomiting. No stomach pain.

---

### Musculoskeletal
**Aria might ask about:** muscle pain, joint pain, can you reproduce the pain by pressing

**You say:**
> No, if I press on my chest it doesn't hurt. It's definitely not a muscle thing — it doesn't feel like that.

---

### Constitutional
**Aria might ask about:** fever, fatigue, weight loss, night sweats, chills

**You say:**
> I've been more tired than usual lately, but I figured that was just stress. No fever, no night sweats, no weight loss that I know of.

---

## Phase 5 — Closing

**Aria asks:** "Is there anything else you'd like your doctor to know about?"

**You say:**
> My father had a heart attack at 58, so I guess that's on my mind. I'm also on blood pressure medication — lisinopril — and I take a statin.

*(This is a great clinical flag for the brief.)*

**Aria closes the session.**

---

## What the brief should show

After the session ends, the clinical brief panel should populate with:

- **Chief Complaint:** Exertional substernal chest pressure × 1 week
- **HPI table:** All 9 OLDCARTS fields filled
- **ROS:** Cardiovascular (positive: exertional dyspnea, transient lightheadedness / negative: no palpitations, no edema), Respiratory (positive: exertional dyspnea / negative: no wheezing), GI (negative), Musculoskeletal (negative), Constitutional (positive: fatigue)
- **Clinical Narrative:** 2–3 sentence clinical summary using terms like *exertional substernal pressure*, *left shoulder radiation*, *exertional dyspnea*
- **Flags:** Family history of MI, current medications, exertional symptoms with radiation — cardiac workup indicated

---

## Tips for a smooth demo

- Speak at normal conversational pace — Gemini Live has VAD (voice activity detection), it knows when you've finished
- If Aria asks a question you've already answered, you can say "I already mentioned that — [repeat it]" and she'll move on
- If Aria mishears something, just restate it naturally
- The OLDCARTS tracker on the right panel updates live as fields are extracted — good to show during the demo
- The brief generation takes about 5–10 seconds after the closing — the panel shows a spinner

---

## Alternative: Shorter demo (3 min)

If time is tight, compress the chief complaint to include more detail upfront:

> "I've been having chest tightness for about a week. It comes on when I'm physically active, feels like pressure in the middle of my chest, sometimes goes to my left shoulder, rates about a 6 out of 10, and gets better when I rest."

This front-loads OLDCARTS and lets Aria confirm fields rather than dig for each one individually.
