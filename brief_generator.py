"""
Generates a structured clinical brief from the session transcript using Gemini REST.
Uses response_schema for guaranteed JSON structure.
"""
import json
import logging
import os

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

_NULLABLE_STRING = {'type': 'STRING', 'nullable': True}
_STRING_ARRAY = {'type': 'ARRAY', 'items': {'type': 'STRING'}}

BRIEF_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'patient_name': {'type': 'STRING'},
        'chief_complaint': {
            'type': 'OBJECT',
            'properties': {
                'statement':           {'type': 'STRING'},
                'onset_of_complaint':  {'type': 'STRING'},
            },
            'required': ['statement', 'onset_of_complaint'],
        },
        'hpi': {
            'type': 'OBJECT',
            'properties': {
                'onset':               _NULLABLE_STRING,
                'location':            _NULLABLE_STRING,
                'duration':            _NULLABLE_STRING,
                'character':           _NULLABLE_STRING,
                'aggravating_factors': _NULLABLE_STRING,
                'alleviating_factors': _NULLABLE_STRING,
                'radiation':           _NULLABLE_STRING,
                'timing':              _NULLABLE_STRING,
                'severity':            _NULLABLE_STRING,
            },
        },
        'ros': {
            'type': 'OBJECT',
            'additionalProperties': {
                'type': 'OBJECT',
                'properties': {
                    'positive': _STRING_ARRAY,
                    'negative': _STRING_ARRAY,
                },
                'required': ['positive', 'negative'],
            },
        },
        'clinical_narrative': {'type': 'STRING'},
        'flags': _STRING_ARRAY,
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
- ros: include only systems that were actually reviewed; record positive findings and pertinent negatives.
- clinical_narrative: 2-3 sentence summary in clinical documentation style using clinical terms (exertional dyspnea, pleuritic chest pain, etc). Include chief complaint, key HPI findings, and notable ROS positives/negatives.
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
        model=os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash'),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type='application/json',
            response_schema=BRIEF_SCHEMA,
            temperature=0.1,
        ),
    )

    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, AttributeError) as e:
        raise ValueError(
            f"Brief extraction returned invalid JSON: {e}\nRaw: {getattr(response, 'text', '')[:500]}"
        )
