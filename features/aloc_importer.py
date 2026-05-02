"""
ALOC Past Question Importer
Fetches questions from the ALOC API and stores them in Supabase.
Triggered via admin command: ADMIN IMPORT_QUESTIONS
"""

import httpx
from config.settings import settings

ALOC_BASE_URL = "https://questions.aloc.com.ng/api/v2"
ALOC_TOKEN = settings.ALOC_API_TOKEN

SUBJECTS = [
    "english", "mathematics", "physics", "chemistry", "biology",
    "economics", "government", "literature", "geography",
    "commerce", "agriculture", "accounting", "crs", "irs",
]

YEAR_RANGE = range(2000, 2023)  # ALOC covers roughly 2000-2022


async def import_questions_from_aloc() -> str:
    """
    Fetches past questions from ALOC and inserts them into Supabase.
    Returns a summary message.
    """
    from database.client import supabase

    total_inserted = 0
    errors = 0

    headers = {
        "Authorization": f"Bearer {ALOC_TOKEN}",
    }

    for subject in SUBJECTS:
        for year in YEAR_RANGE:
            try:
                url = f"{ALOC_BASE_URL}/m?subject={subject}&year={year}&type=utme"
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url, headers=headers)
                    if response.status_code != 200:
                        errors += 1
                        continue

                    data = response.json()
                    questions = data.get("questions", []) or data.get("data", [])
                    if not questions:
                        continue

                    for q in questions:
                        try:
                            question_text = q.get("question", "")
                            options = q.get("option", {})
                            option_a = options.get("a", "")
                            option_b = options.get("b", "")
                            option_c = options.get("c", "")
                            option_d = options.get("d", "")
                            correct = q.get("answer", "").lower()
                            explanation = q.get("explanation", "")
                            exam_type = "JAMB"  # default to JAMB for utme type
                            exam_year = year

                            # Skip if any critical field is missing
                            if not question_text or not option_a or not option_b or not correct:
                                continue

                            # Check if this question already exists (by text)
                            existing = supabase.table("questions") \
                                .select("id") \
                                .eq("question_text", question_text) \
                                .execute()
                            if existing.data:
                                continue

                            supabase.table("questions").insert({
                                "exam_type": exam_type,
                                "subject": subject,
                                "topic": "General",  # will be refined later
                                "year": exam_year,
                                "question_text": question_text,
                                "option_a": option_a,
                                "option_b": option_b,
                                "option_c": option_c,
                                "option_d": option_d,
                                "correct_answer": correct,
                                "explanation": explanation or "",
                                "difficulty": "medium",
                                "verified": True,
                            }).execute()
                            total_inserted += 1
                        except Exception as e:
                            errors += 1
                            print(f"ALOC insert error: {e}")
            except Exception as e:
                errors += 1
                print(f"ALOC fetch error ({subject} {year}): {e}")

    return f"ALOC import complete. {total_inserted} questions added. {errors} errors."
