"""
OpenAI Client — Vision AI and Voice for WaxPrep

Vision: Scholar+ students send photos of textbooks, past papers, diagrams.
Wax reads the image and responds naturally.

Voice In: Scholar+ students send voice notes.
Groq Whisper transcribes them. Wax responds in text.

Voice Out: Elite students receive voice replies from Wax (future feature).
Uses OpenAI TTS or ElevenLabs.
"""

from openai import AsyncOpenAI
from config.settings import settings
import base64
import httpx

openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def analyze_image(
    image_url: str = None,
    image_base64: str = None,
    prompt: str = None,
    student: dict = None
) -> str:
    """
    Analyzes an image using GPT-4o-mini.
    Returns Wax's natural response about the image content.
    """
    if not prompt:
        name = student.get('name', 'the student').split()[0] if student else 'the student'
        exam = student.get('target_exam', 'JAMB') if student else 'JAMB'
        subjects = ', '.join(student.get('subjects', [])) if student else 'general subjects'

        prompt = (
            f"You are Wax, a brilliant personal AI teacher for Nigerian secondary school students. "
            f"This student's name is {name}, preparing for {exam}, studying {subjects}.\n\n"
            f"Look at this image and respond as a teacher would:\n"
            f"- If it contains a question or problem: solve it and explain your working clearly\n"
            f"- If it's a diagram or graph: explain what it shows and why it matters\n"
            f"- If it's textbook content: identify the key concepts and explain them\n"
            f"- If it's a past question paper: identify the questions and work through them\n\n"
            f"Use Nigerian context and examples where helpful. "
            f"Format your response clearly for WhatsApp. "
            f"Be warm, be clear, be a teacher."
        )

    if image_url:
        image_content = {
            "type": "image_url",
            "image_url": {"url": image_url, "detail": "high"}
        }
    elif image_base64:
        image_content = {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_base64}",
                "detail": "high"
            }
        }
    else:
        return "I could not read that image. Please try sending it again."

    try:
        response = await openai_client.chat.completions.create(
            model=settings.OPENAI_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        image_content,
                        {"type": "text", "text": prompt}
                    ]
                }
            ],
            max_tokens=1500,
        )

        result = response.choices[0].message.content

        if hasattr(response, 'usage') and student:
            from ai.cost_tracker import track_ai_cost
            await track_ai_cost(
                student_id=student.get('id'),
                model=settings.OPENAI_VISION_MODEL,
                tokens_input=response.usage.prompt_tokens,
                tokens_output=response.usage.completion_tokens,
                query_type='image_analysis'
            )

        return result

    except Exception as e:
        print(f"OpenAI vision error: {e}")
        return (
            "I had trouble reading that image.\n\n"
            "Please try:\n"
            "• Taking a clearer photo in good lighting\n"
            "• Making sure the text is clearly visible\n"
            "• Sending just one page at a time\n\n"
            "Or type your question and I'll help immediately!"
        )


async def transcribe_voice_note(audio_id: str) -> str | None:
    """
    Downloads a voice note from WhatsApp and transcribes it using Groq Whisper.
    Returns the transcribed text, or None if transcription fails.
    """
    # Download the audio
    audio_b64 = await download_whatsapp_media(audio_id, 'audio')

    if not audio_b64:
        return None

    try:
        from groq import AsyncGroq

        groq_async = AsyncGroq(api_key=settings.GROQ_API_KEY)

        # Decode base64 back to bytes
        audio_bytes = base64.b64decode(audio_b64)

        transcription = await groq_async.audio.transcriptions.create(
            file=("voice.ogg", audio_bytes, "audio/ogg"),
            model=settings.GROQ_WHISPER_MODEL,
            language="en",
            response_format="text"
        )

        if isinstance(transcription, str):
            return transcription.strip()

        # Some versions return an object
        if hasattr(transcription, 'text'):
            return transcription.text.strip()

        return str(transcription).strip()

    except Exception as e:
        print(f"Voice transcription error: {e}")

        # Try OpenAI Whisper as fallback if Groq fails
        if settings.OPENAI_API_KEY:
            try:
                audio_bytes = base64.b64decode(audio_b64)
                response = await openai_client.audio.transcriptions.create(
                    file=("voice.ogg", audio_bytes, "audio/ogg"),
                    model="whisper-1",
                    language="en"
                )
                return response.text.strip()
            except Exception as e2:
                print(f"OpenAI Whisper fallback error: {e2}")

        return None


async def generate_voice_reply(text: str) -> bytes | None:
    """
    Converts text to speech using OpenAI TTS.
    Returns audio bytes, or None if generation fails.
    This is for the Elite tier voice reply feature (future).
    """
    if not settings.OPENAI_API_KEY:
        return None

    try:
        response = await openai_client.audio.speech.create(
            model=settings.OPENAI_TTS_MODEL,
            voice=settings.OPENAI_TTS_VOICE,
            input=text,
            response_format="mp3"
        )
        return response.content
    except Exception as e:
        print(f"TTS generation error: {e}")
        return None


async def download_whatsapp_image(image_id: str) -> str | None:
    """
    Downloads an image from WhatsApp's servers.
    Returns the image as base64-encoded string.
    """
    return await download_whatsapp_media(image_id, 'image')


async def download_whatsapp_media(media_id: str, media_type: str = 'image') -> str | None:
    """Downloads any media from WhatsApp by media ID. Returns base64 string."""
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            media_response = await client.get(
                f"{settings.WHATSAPP_API_URL}/{media_id}",
                headers=headers
            )

            if media_response.status_code != 200:
                print(f"Failed to get media URL: {media_response.text[:200]}")
                return None

            media_data = media_response.json()
            media_url = media_data.get('url')

            if not media_url:
                return None

            file_response = await client.get(media_url, headers=headers)

            if file_response.status_code != 200:
                print(f"Failed to download media: {file_response.status_code}")
                return None

            return base64.b64encode(file_response.content).decode('utf-8')

        except Exception as e:
            print(f"Media download error: {e}")
            return None
