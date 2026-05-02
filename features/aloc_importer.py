"""
ALOC Past Question Importer
Fetches questions from the ALOC API and stores them in Supabase via upsert.
Triggered via admin command: ADMIN IMPORT_QUESTIONS
"""

import httpx
from config.settings import settings

ALOC_BASE_URL = "https://questions.aloc.com.ng/api/v2"
ALOC_TOKEN = settings.ALOC_API_TOKEN

if not ALOC_TOKEN:
    raise RuntimeError("ALOC_API_TOKEN environment variable is not set")

SUBJECTS = [
    "english", "mathematics", "physics", "chemistry", "biology",
    "economics", "government", "literature", "geography",
    "commerce", "agriculture", "accounting", "crs", "irs",
]

YEAR_RANGE = range(2000, 2023)


async def import_questions_from_aloc() -> str:
    from database.client import supabase

    total_inserted = 0
    errors = 0

    headers = {"AccessToken": ALOC_TOKEN}

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
                    questions = []

                    if isinstance(data.get("data"), list):
                        questions = data["data"]
                    elif isinstance(data.get("data"), dict):
                        questions = [data["data"]]
                    elif isinstance(data.get("questions"), list):
                        questions = data["questions"]
                    elif data.get("question"):
                        questions = [data]

                    if not questions:
                        continue

                    insert_batch = []
                    for q in questions:
                        question_text = q.get("question", "")
                        options = q.get("option", {})
                        if isinstance(options, list):
                            option_a = options[0] if len(options) > 0 else ""
                            option_b = options[1] if len(options) > 1 else ""
                            option_c = options[2] if len(options) > 2 else ""
                            option_d = options[3] if len(options) > 3 else ""
                        else:
                            option_a = options.get("a", "")
                            option_b = options.get("b", "")
                            option_c = options.get("c", "")
                            option_d = options.get("d", "")
                        correct = q.get("answer", "").lower().strip()
                        explanation = q.get("explanation", "")

                        if not question_text or not option_a or not option_b or not correct:
                            continue

                        insert_batch.append({
                            "exam_type": "JAMB",
                            "subject": subject,
                            "topic": "General",
                            "year": year,
                            "question_text": question_text,
                            "option_a": option_a,
                            "option_b": option_b,
                            "option_c": option_c,
                            "option_d": option_d,
                            "correct_answer": correct,
                            "explanation": explanation or "",
                            "difficulty": "medium",
                            "verified": True,
                        })

                    if insert_batch:
                        try:
                            result = supabase.table("questions").upsert(
                                insert_batch,
                                on_conflict="question_text"
                            ).execute()
                            total_inserted += len(result.data) if result.data else 0
                        except Exception as e:
                            errors += len(insert_batch)
                            print(f"ALOC batch insert error: {e}")
            except Exception as e:
                errors += 1
                print(f"ALOC fetch error ({subject} {year}): {e}")

    return f"ALOC import complete. {total_inserted} questions added. {errors} errors."
