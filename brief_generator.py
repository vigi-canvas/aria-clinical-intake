"""
Generates a structured clinical brief from the session transcript using Gemini REST.
Uses response_schema for guaranteed JSON structure.
"""
import logging
import os

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# JSON Schema for structured brief output
BRIEF_SCHEMA = {
    'type': 'object',
    'properties': {
        'patient_name': {'type': 'string'},
        'chief_complaint': {
            'type': 'object',
            'properties': {
                'statement': {'type': 'string'},
                'onset_of_complaint': {'type': 'string'},
            },
            'required': ['statement', 'onset_of_complaint'],
        },
        'hpi': {
            'type': 'object',
            'properties': {
                'onset':              {'type': ['string', 'null']},
                'location':           {'type': ['string', 'null']},
                'duration':           {'type': ['string', 'null']},
                'character':          {'type': ['string', 'null']},
                'aggravating_factors':{'type': ['string', 'null']},
                'alleviating_factors':{'type': ['string', 'null']},
                'radiation':          {'type': ['string', 'null']},
                'timing':             {'type': ['string', 'null']},
                'severity':           {'type': ['string', 'null']},
            },
        },
        'ros': {
            'type': 'object',
            'additionalProperties': {
                'type': 'object',
                'properties': {
                    'positive': {'type': 'array', 'items': {'type': 'string'}},
                    'negative': {'type': 'array', 'items': {'type': 'string'}},
                },
                'required': ['positive', 'negative'],
            },
        },
        'clinical_narrative': {'type': 'string'},
        'flags': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['patient_name', 'chief_complaint', 'hpi', 'ros', 'clinical_narrative', 'flags'],
}

BRIEF_PROMPT = """You are a clinical documentation assistant. Given the following patient intake
conversation transcript, extract a structured clinical brief.

Instructions:
- patient_name: the patient's full name as provided.
- chief_complaint.statement: patient's own words for their main concern.
- chief_complaint.onset_of_complaint: how long they've had this problem overall.
- hpi: fill each OLDCARTS field from the conversation; use null if not discussed.
- ros: include only systems that were actually reviewed; record both positive findings and pertinent negatives.
- clinical_narrative: 2–3 sentence summary in clinical documentation style (use clinical terms: exertional dyspnea, pleuritic chest pain, etc.). Include chief complaint, key HPI findings, and notable ROS positives/negatives.
- flags: list any concerning symptoms, incomplete data, or items needing clinician follow-up. Empty list if none.

Transcript:
{transcript}
"""


async def generate_brief(transcript: list[dict], credentials) -> dict:
    """
    Takes the session transcript and returns a structured clinical brief dict.
    Raises ValueError if generation fails.
    """
    if not transcript:
        raise ValueError("Transcript is empty — cannot generate brief")

    text_transcript = '\n'.join(
        f"{t['role'].upper()}: {t['text']}" for t in transcript
    )
    prompt = BRIEF_PROMPT.format(transcript=text_transcript)

    client = genai.Client(
        vertexai=True,
        project=os.environ['GOOGLE_PROJECT_ID'],
        location=os.environ.get('GOOGLE_LOCATION', 'us-central1'),
        credentials=credentials,
    )

    response = await client.aio.models.generate_content(
        model=os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash-preview-05-20'),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type='application/json',
            response_schema=BRIEF_SCHEMA,
            temperature=0.1,
        ),
    )

    import json
    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, AttributeError) as e:
        raise ValueError(
            f"Brief extraction returned invalid JSON: {e}\nRaw: {getattr(response, 'text', '')[:500]}"
        )
