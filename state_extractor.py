"""
Extracts structured intake state from the live transcript using Gemini REST.
Called after each agent turn to update the IntakeStateMachine.
"""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from google import genai
from google.genai import types

if TYPE_CHECKING:
    from state_machine import IntakeStateMachine

logger = logging.getLogger(__name__)

# JSON Schema for structured state extraction
EXTRACTION_SCHEMA = {
    'type': 'object',
    'properties': {
        'patient_name': {'type': ['string', 'null']},
        'chief_complaint': {'type': ['string', 'null']},
        'hpi_updates': {
            'type': 'object',
            'properties': {
                'onset':       {'type': ['string', 'null']},
                'location':    {'type': ['string', 'null']},
                'duration':    {'type': ['string', 'null']},
                'character':   {'type': ['string', 'null']},
                'aggravating': {'type': ['string', 'null']},
                'alleviating': {'type': ['string', 'null']},
                'radiation':   {'type': ['string', 'null']},
                'timing':      {'type': ['string', 'null']},
                'severity':    {'type': ['string', 'null']},
            },
        },
        'ros_updates': {
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
        'closing_complete': {'type': 'boolean'},
    },
    'required': ['patient_name', 'chief_complaint', 'hpi_updates', 'ros_updates', 'closing_complete'],
}

EXTRACTION_PROMPT = """You are a clinical intake state extractor.
Given a patient intake conversation transcript, extract structured information from what has been established.

Rules:
- patient_name: null if not yet given; string if patient has introduced themselves.
- chief_complaint: null if not stated; use patient's own words if stated.
- hpi_updates: null for each field not yet discussed. "N/A" only if patient explicitly said they don't know or it doesn't apply.
- ros_updates: only include systems where questions were ASKED AND ANSWERED. Record all positive findings and pertinent negatives.
- closing_complete: true only if the agent has delivered a clear farewell/closing message.

Transcript:
{transcript}
"""


async def extract_intake_state(sm: 'IntakeStateMachine', credentials) -> dict:
    """
    Runs a lightweight Gemini REST extraction pass over the current transcript.
    Returns the raw extraction dict. Returns {} on any error.
    """
    if not sm.transcript:
        return {}

    # Only pass recent context — last 40 turns covers even long sessions
    transcript_text = '\n'.join(
        f"{t['role'].upper()}: {t['text']}" for t in sm.transcript[-40:]
    )
    prompt = EXTRACTION_PROMPT.format(transcript=transcript_text)

    client = genai.Client(
        vertexai=True,
        project=os.environ['GOOGLE_PROJECT_ID'],
        location=os.environ.get('GOOGLE_LOCATION', 'us-central1'),
        credentials=credentials,
    )

    try:
        response = await client.aio.models.generate_content(
            model=os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash-preview-05-20'),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=EXTRACTION_SCHEMA,
                temperature=0.0,
                max_output_tokens=1024,
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        logger.warning("State extraction failed (non-fatal): %s", e)
        return {}


def apply_extraction(sm: 'IntakeStateMachine', data: dict) -> list[str]:
    """
    Applies an extraction result to the state machine.
    Returns a list of field names that changed.
    """
    from state_machine import classify_cc

    if not data:
        return []

    changed = []

    if data.get('patient_name') and not sm.patient_name:
        sm.patient_name = data['patient_name']
        changed.append('patient_name')

    if data.get('chief_complaint') and not sm.chief_complaint:
        sm.chief_complaint = data['chief_complaint']
        sm.cc_category = classify_cc(sm.chief_complaint)
        changed.append('chief_complaint')

    hpi = data.get('hpi_updates') or {}
    for field, value in hpi.items():
        if value is not None and field in sm.hpi_fields and sm.hpi_fields[field] is None:
            if value == 'N/A':
                sm.mark_na_if_unknown(field)
            else:
                sm.set_hpi_field(field, value)
            changed.append(f'hpi.{field}')

    ros = data.get('ros_updates') or {}
    for system, findings in ros.items():
        if system not in sm.ros_data:
            sm.update_ros(
                system,
                findings.get('positive', []),
                findings.get('negative', []),
            )
            changed.append(f'ros.{system}')

    return changed
