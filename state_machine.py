import datetime

OLDCARTS_FIELDS = [
    'onset',
    'location',
    'duration',
    'character',
    'aggravating',
    'alleviating',
    'radiation',
    'timing',
    'severity',
]

CC_TO_ROS_MAP = {
    'chest_pain':   ['cardiovascular', 'respiratory', 'gastrointestinal', 'musculoskeletal', 'constitutional'],
    'headache':     ['neurological', 'ent', 'ophthalmological', 'constitutional', 'psychiatric'],
    'abdominal':    ['gastrointestinal', 'genitourinary', 'constitutional', 'gynecological'],
    'dyspnea':      ['respiratory', 'cardiovascular', 'constitutional', 'musculoskeletal'],
    'joint_pain':   ['musculoskeletal', 'constitutional', 'dermatological', 'immunological'],
    'cough':        ['respiratory', 'ent', 'constitutional', 'cardiovascular'],
    'default':      ['constitutional', 'cardiovascular', 'respiratory', 'gastrointestinal', 'neurological'],
}


def classify_cc(chief_complaint: str) -> str:
    cc = chief_complaint.lower()
    if any(w in cc for w in ['chest', 'heart', 'cardiac', 'palpitation']):
        return 'chest_pain'
    if any(w in cc for w in ['head', 'migraine', 'headache']):
        return 'headache'
    if any(w in cc for w in ['abdomen', 'abdominal', 'stomach', 'belly', 'nausea', 'vomit']):
        return 'abdominal'
    if any(w in cc for w in ['breath', 'breathe', 'breathing', 'shortness', 'dyspnea']):
        return 'dyspnea'
    if any(w in cc for w in ['joint', 'knee', 'hip', 'shoulder', 'back', 'muscle']):
        return 'joint_pain'
    if any(w in cc for w in ['cough', 'wheez', 'throat']):
        return 'cough'
    return 'default'


class IntakeStateMachine:
    def __init__(self):
        self.phase = 'GREETING'
        self.patient_name: str | None = None
        self.chief_complaint: str | None = None
        self.cc_category: str = 'default'
        self.hpi_fields: dict = {f: None for f in OLDCARTS_FIELDS}
        self.ros_systems: list[str] = []
        self.ros_data: dict = {}
        self.transcript: list[dict] = []

    def hpi_complete(self) -> bool:
        filled = sum(1 for v in self.hpi_fields.values() if v is not None)
        return filled >= 8  # 8 of 9 OLDCARTS fields sufficient to advance

    def ros_complete(self) -> bool:
        return len(self.ros_systems) > 0 and all(s in self.ros_data for s in self.ros_systems)

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
        if field in self.hpi_fields:
            self.hpi_fields[field] = 'N/A'

    def update_ros(self, system: str, positives: list[str], negatives: list[str]):
        self.ros_data[system] = {
            'positive': positives,
            'negative': negatives,
        }

    def append_transcript(self, role: str, text: str):
        self.transcript.append({
            'role': role,
            'text': text,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

    def get_hpi_summary(self) -> dict:
        collected = {k: v for k, v in self.hpi_fields.items() if v is not None}
        missing = [k for k, v in self.hpi_fields.items() if v is None]
        return {'collected': collected, 'missing': missing}

    def get_system_prompt(self) -> str:
        from prompts import build_system_prompt
        return build_system_prompt(self)
