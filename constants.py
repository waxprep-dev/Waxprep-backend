"""
Shared constants for WaxPrep onboarding.
Import this file in both whatsapp/flows/onboarding.py and telegram/onboarding.py.
"""

EXAM_SUBJECTS = {
    'JAMB': [
        'English Language', 'Mathematics', 'Physics', 'Chemistry', 'Biology',
        'Economics', 'Government', 'Literature in English', 'Geography',
        'Commerce', 'Agricultural Science', 'Christian Religious Studies',
        'Islamic Religious Studies', 'History', 'Yoruba', 'Igbo', 'Hausa'
    ],
    'WAEC': [
        'English Language', 'Mathematics', 'Physics', 'Chemistry', 'Biology',
        'Economics', 'Government', 'Literature in English', 'Geography',
        'Commerce', 'Agricultural Science', 'Further Mathematics',
        'Food and Nutrition', 'Computer Studies', 'Technical Drawing'
    ],
    'NECO': [
        'English Language', 'Mathematics', 'Physics', 'Chemistry', 'Biology',
        'Economics', 'Government', 'Literature in English', 'Geography',
        'Commerce', 'Agricultural Science'
    ],
    'COMMON_ENTRANCE': [
        'English Language', 'Mathematics', 'Basic Science',
        'Social Studies', 'Verbal Reasoning', 'Quantitative Reasoning'
    ],
    'POST_UTME': [
        'English Language', 'Mathematics', 'Physics', 'Chemistry',
        'Biology', 'Economics', 'Government'
    ],
}

CLASS_LEVELS = ['JSS1', 'JSS2', 'JSS3', 'SS1', 'SS2', 'SS3']

NIGERIAN_STATES = [
    'Abia', 'Adamawa', 'Akwa Ibom', 'Anambra', 'Bauchi', 'Bayelsa', 'Benue',
    'Borno', 'Cross River', 'Delta', 'Ebonyi', 'Edo', 'Ekiti', 'Enugu', 'FCT',
    'Gombe', 'Imo', 'Jigawa', 'Kaduna', 'Kano', 'Katsina', 'Kebbi', 'Kogi',
    'Kwara', 'Lagos', 'Nasarawa', 'Niger', 'Ogun', 'Ondo', 'Osun', 'Oyo',
    'Plateau', 'Rivers', 'Sokoto', 'Taraba', 'Yobe', 'Zamfara'
]

SUBJECT_INTROS = {
    ('physics', 'chemistry', 'biology'): (
        "There's one concept that controls all three sciences: **Energy.** "
        "It's the same energy that powers a generator (Physics), makes bread "
        "rise with yeast (Biology), and burns kerosene in a lamp (Chemistry). "
        "Understand this one thing, and you've already gained ground in three "
        "subjects at once. It'll take 2 minutes. Ready?"
    ),
    ('physics', 'chemistry'): (
        "There's one idea that connects both your science subjects: **Matter.** "
        "Everything around you — the air, the water, your phone — is made of "
        "atoms. Physics tells you how they move. Chemistry tells you how they "
        "react. Master this link and both subjects become easier. 2 minutes. Ready?"
    ),
    ('physics', 'biology'): (
        "Here's a connection most students miss: **Force and Motion** appear "
        "in both Physics and Biology. Blood flowing through your body follows "
        "the same principles as water through a pipe. An okada turning a corner "
        "is the same physics as your heartbeat. See the link? 2 minutes. Ready?"
    ),
    ('chemistry', 'biology'): (
        "Both your sciences meet at **Chemical Reactions.** Digestion is chemistry "
        "inside your body. Fermentation is chemistry inside a palm wine gourd. "
        "Rust on a roof is chemistry in the open air. Same principles, different "
        "scenes. 2 minutes to connect them. Ready?"
    ),
    ('government', 'economics', 'commerce'): (
        "Your three subjects share one big idea: **Systems.** Government sets "
        "the rules. Economics tracks the money. Commerce moves the goods. "
        "Understand how they feed each other, and you understand how Nigeria "
        "works. 2 minutes. Ready?"
    ),
    ('government', 'literature'): (
        "Both your subjects explore **Power.** Who holds it in a government? "
        "Who holds it in a story? From the Constitution to Chinua Achebe, the "
        "same struggle plays out: who gets to decide, and who pays the price. "
        "2 minutes. Ready?"
    ),
    ('economics', 'commerce', 'geography'): (
        "Your subjects revolve around **Resources.** Where they come from "
        "(Geography), how they're traded (Commerce), and who profits (Economics). "
        "Oil from the Delta, cocoa from Ondo, markets from Onitsha — it's all "
        "connected. 2 minutes. Ready?"
    ),
    ('english', 'literature', 'christian religious studies'): (
        "Your subjects share one thread: **Narrative.** The Bible tells stories "
        "of faith. Achebe tells stories of change. Your English exam tests how "
        "well you understand both. Stories shape beliefs — let me show you how. "
        "2 minutes. Ready?"
    ),
    ('mathematics', 'physics', 'chemistry'): (
        "Your three subjects speak one language: **Equations.** Maths gives you "
        "the grammar. Physics and Chemistry give you the sentences. Once you "
        "see equations as a language instead of a punishment, everything shifts. "
        "2 minutes. Ready?"
    ),
}

def get_welcome_intro(subjects: list) -> str:
    """Return a personalised intro based on the student's subjects."""
    if not subjects:
        return "Let's start with the basics and build from there. Ready?"
    
    subject_lower = [s.lower().strip() for s in subjects]
    
    # Check each combination (order matters — most specific first)
    for combo, intro in SUBJECT_INTROS.items():
        if all(c in subject_lower for c in combo):
            return intro
    
    # Fallback: pick the first subject and give a general tip
    first = subjects[0] if subjects else 'your subject'
    return f"Let's start with {first} — that's a strong choice. We'll build your foundation step by step. Ready?"
