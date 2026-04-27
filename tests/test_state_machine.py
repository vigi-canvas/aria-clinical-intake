import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from state_machine import IntakeStateMachine, OLDCARTS_FIELDS, CC_TO_ROS_MAP, classify_cc


def test_phase_transitions_full_sequence():
    sm = IntakeStateMachine()
    assert sm.phase == 'GREETING'

    sm.patient_name = 'Michael'
    sm.advance_phase()
    assert sm.phase == 'CHIEF_COMPLAINT'

    sm.chief_complaint = 'chest pain'
    sm.advance_phase()
    assert sm.phase == 'HPI'

    for f in OLDCARTS_FIELDS:
        sm.set_hpi_field(f, 'test value')
    assert sm.hpi_complete()

    sm.advance_phase()
    assert sm.phase == 'ROS'
    assert len(sm.ros_systems) > 0


def test_phase_does_not_skip():
    sm = IntakeStateMachine()
    sm.advance_phase()
    assert sm.phase == 'CHIEF_COMPLAINT'  # still advances — caller is responsible for guards
    sm.advance_phase()
    assert sm.phase == 'HPI'


def test_hpi_not_complete_when_fields_missing():
    sm = IntakeStateMachine()
    sm.set_hpi_field('onset', 'two days ago')
    assert not sm.hpi_complete()


def test_hpi_not_complete_when_empty():
    sm = IntakeStateMachine()
    assert not sm.hpi_complete()


def test_na_counts_as_complete():
    sm = IntakeStateMachine()
    for f in OLDCARTS_FIELDS:
        sm.mark_na_if_unknown(f)
    assert sm.hpi_complete()


def test_mixed_na_and_values_complete():
    sm = IntakeStateMachine()
    for i, f in enumerate(OLDCARTS_FIELDS):
        if i % 2 == 0:
            sm.set_hpi_field(f, 'some value')
        else:
            sm.mark_na_if_unknown(f)
    assert sm.hpi_complete()


def test_cc_to_ros_chest_pain():
    sm = IntakeStateMachine()
    sm.patient_name = 'Test'
    sm.chief_complaint = 'chest pain'
    sm.cc_category = 'chest_pain'
    sm.advance_phase()  # GREETING → CHIEF_COMPLAINT
    sm.advance_phase()  # CHIEF_COMPLAINT → HPI
    sm.advance_phase()  # HPI → ROS
    assert 'cardiovascular' in sm.ros_systems
    assert 'respiratory' in sm.ros_systems


def test_cc_to_ros_default_fallback():
    sm = IntakeStateMachine()
    sm.patient_name = 'Test'
    sm.chief_complaint = 'something unusual'
    sm.cc_category = 'default'
    sm.advance_phase()
    sm.advance_phase()
    sm.advance_phase()
    assert sm.ros_systems == CC_TO_ROS_MAP['default']


def test_ros_complete_after_all_systems_reviewed():
    sm = IntakeStateMachine()
    sm.patient_name = 'Test'
    sm.chief_complaint = 'chest pain'
    sm.cc_category = 'chest_pain'
    for _ in range(3):
        sm.advance_phase()
    # Mark all ROS systems as reviewed
    for system in sm.ros_systems:
        sm.update_ros(system, ['palpitations'], ['no fever'])
    assert sm.ros_complete()


def test_ros_not_complete_when_systems_missing():
    sm = IntakeStateMachine()
    sm.patient_name = 'Test'
    sm.chief_complaint = 'chest pain'
    sm.cc_category = 'chest_pain'
    for _ in range(3):
        sm.advance_phase()
    sm.update_ros('cardiovascular', ['palpitations'], [])
    assert not sm.ros_complete()


def test_transcript_logging():
    sm = IntakeStateMachine()
    sm.append_transcript('agent', 'Hello')
    sm.append_transcript('patient', 'Hi')
    assert len(sm.transcript) == 2
    assert sm.transcript[0]['role'] == 'agent'
    assert sm.transcript[0]['text'] == 'Hello'
    assert sm.transcript[1]['role'] == 'patient'
    assert sm.transcript[1]['text'] == 'Hi'


def test_transcript_has_timestamp():
    sm = IntakeStateMachine()
    sm.append_transcript('agent', 'Hello')
    assert 'timestamp' in sm.transcript[0]


def test_classify_cc_chest_pain():
    assert classify_cc('I have chest pain') == 'chest_pain'
    assert classify_cc('My heart is pounding') == 'chest_pain'


def test_classify_cc_headache():
    assert classify_cc('I have a terrible headache') == 'headache'
    assert classify_cc('migraine for 3 days') == 'headache'


def test_classify_cc_dyspnea():
    assert classify_cc('shortness of breath') == 'dyspnea'
    assert classify_cc('trouble breathing when I walk') == 'dyspnea'


def test_classify_cc_default():
    assert classify_cc('feeling weird') == 'default'
    assert classify_cc('not sure what is wrong') == 'default'


def test_auth_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS', str(tmp_path / 'missing.json'))
    from auth import get_credentials
    with pytest.raises(FileNotFoundError):
        get_credentials()


def test_hpi_summary_shows_collected_and_missing():
    sm = IntakeStateMachine()
    sm.set_hpi_field('onset', 'two days ago')
    sm.set_hpi_field('severity', '7/10')
    summary = sm.get_hpi_summary()
    assert 'onset' in summary['collected']
    assert 'severity' in summary['collected']
    assert 'location' in summary['missing']


def test_full_session_state_sequence():
    """Simulates a complete intake session state progression."""
    sm = IntakeStateMachine()
    assert sm.phase == 'GREETING'

    sm.patient_name = 'Jane'
    sm.advance_phase()
    assert sm.phase == 'CHIEF_COMPLAINT'

    sm.chief_complaint = 'shortness of breath'
    sm.cc_category = 'dyspnea'
    sm.advance_phase()
    assert sm.phase == 'HPI'

    for f in OLDCARTS_FIELDS:
        sm.set_hpi_field(f, 'answered')
    assert sm.hpi_complete()

    sm.advance_phase()
    assert sm.phase == 'ROS'
    assert 'respiratory' in sm.ros_systems
    assert 'cardiovascular' in sm.ros_systems

    for s in sm.ros_systems:
        sm.update_ros(s, [], ['no symptoms'])
    assert sm.ros_complete()

    sm.advance_phase()
    assert sm.phase == 'CLOSING'

    sm.advance_phase()
    assert sm.phase == 'DONE'
