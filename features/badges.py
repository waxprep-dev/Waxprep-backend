"""
Badge Awarding System — Standalone Module

This file exists specifically to break the circular import between
whatsapp/handler.py and whatsapp/flows/*.py

All badge awarding goes through this file.
No imports from whatsapp/ are allowed here.
"""


async def award_badge(student_id: str, badge_code: str) -> dict | None:
    """
    Awards a badge to a student if they don't already have it.
    Returns the badge dict if newly awarded, None if already had it.
    """
    try:
        from database.client import supabase

        badge_result = supabase.table('badges').select('*').eq('badge_code', badge_code).execute()
        if not badge_result.data:
            return None

        badge = badge_result.data[0]

        existing = supabase.table('student_badges')\
            .select('id')\
            .eq('student_id', student_id)\
            .eq('badge_id', badge['id'])\
            .execute()

        if existing.data:
            return None

        supabase.table('student_badges').insert({
            'student_id': student_id,
            'badge_id': badge['id'],
        }).execute()

        try:
            supabase.rpc('add_points_to_student', {
                'student_id_param': student_id,
                'points_to_add': badge.get('points_awarded', 50)
            }).execute()
        except Exception:
            pass

        return badge

    except Exception as e:
        print(f"Badge award error: {e}")
        return None


async def check_and_award_milestone_badges(student_id: str, total_answered: int) -> list:
    """
    Checks if a student has hit a question count milestone and awards it.
    Returns list of newly awarded badges.
    """
    badge_map = {
        1: 'FIRST_QUESTION',
        10: 'QUESTIONS_10',
        50: 'QUESTIONS_50',
        100: 'QUESTIONS_100',
        250: 'QUESTIONS_250',
        500: 'QUESTIONS_500',
        1000: 'QUESTIONS_1000',
    }

    awarded = []
    if total_answered in badge_map:
        badge = await award_badge(student_id, badge_map[total_answered])
        if badge:
            awarded.append(badge)

    return awarded


async def check_streak_badges(student_id: str, current_streak: int) -> list:
    """Awards streak-based badges."""
    streak_badges = {
        3: 'STREAK_3',
        7: 'STREAK_7',
        14: 'STREAK_14',
        30: 'STREAK_30',
        60: 'STREAK_60',
        100: 'STREAK_100',
    }

    awarded = []
    if current_streak in streak_badges:
        badge = await award_badge(student_id, streak_badges[current_streak])
        if badge:
            awarded.append(badge)

    return awarded
