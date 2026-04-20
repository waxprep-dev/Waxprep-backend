"""
OpenAI Client — Vision AI for WaxPrep

Used exclusively for image analysis.
When a Scholar+ student sends a photo of:
- A textbook page
- A past question paper
- A handwritten note
- A diagram or graph

GPT-4o reads the image and either:
1. Extracts the text/questions and helps with them
2. Explains diagrams and graphs
3. Solves problems visible in the image

This is one of the most powerful features of WaxPrep for serious students.
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
    Analyzes an image using GPT-4o.
    
    You can provide either:
    - image_url: A direct URL to the image
    - image_base64: Base64-encoded image data
    
    prompt: What to ask about the image.
    If None, defaults to "Please analyze this educational content and help the student."
    """
    
    if not prompt:
        name = student.get('name', 'the student').split()[0] if student else 'the student'
        exam = student.get('target_exam', 'JAMB') if student else 'JAMB'
        
        prompt = (
            f"You are WaxPrep, an AI study companion for Nigerian secondary school students. "
            f"The student's name is {name} and they're preparing for {exam}.\n\n"
            f"Please look at this image and:\n"
            f"1. If it contains a question or problem, solve it and explain your working\n"
            f"2. If it's a diagram or graph, explain what it shows\n"
            f"3. If it's text from a textbook, summarize the key points\n"
            f"4. If it's a past question paper, identify the questions and help answer them\n\n"
            f"Always use Nigerian context and examples where helpful.\n"
            f"Format your response clearly for WhatsApp."
        )
    
    # Build the message with image
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
        return "I couldn't read that image. Please try sending it again."
    
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
        
        # Track cost
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
            "I had trouble reading that image. 😕\n\n"
            "Please try:\n"
            "• Taking a clearer photo in good lighting\n"
            "• Making sure the text is clearly visible\n"
            "• Sending just one page at a time\n\n"
            "Or type your question in text and I'll help immediately!"
        )

async def download_whatsapp_image(image_id: str) -> str | None:
    """
    Downloads an image from WhatsApp's servers using the image ID.
    Returns the image as base64-encoded string.
    
    WhatsApp images are not directly accessible by URL —
    you must first get the media URL using the media ID,
    then download from that URL using your token.
    """
    from config.settings import settings
    
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Get the media URL from the media ID
        media_response = await client.get(
            f"{settings.WHATSAPP_API_URL}/{image_id}",
            headers=headers
        )
        
        if media_response.status_code != 200:
            print(f"Failed to get media URL: {media_response.text}")
            return None
        
        media_data = media_response.json()
        media_url = media_data.get('url')
        
        if not media_url:
            return None
        
        # Step 2: Download the actual image
        image_response = await client.get(media_url, headers=headers)
        
        if image_response.status_code != 200:
            print(f"Failed to download image: {image_response.status_code}")
            return None
        
        # Convert to base64
        image_b64 = base64.b64encode(image_response.content).decode('utf-8')
        return image_b64

async def transcribe_voice_note(audio_id: str) -> str | None:
    """
    Transcribes a voice note from WhatsApp using Groq's Whisper model.
    
    This is V2 territory but I'm adding the infrastructure now
    so it's ready when you flip the switch.
    
    Returns the transcribed text, or None if transcription fails.
    """
    from groq import AsyncGroq
    
    # First download the audio file from WhatsApp
    audio_b64 = await download_whatsapp_media(audio_id, 'audio')
    
    if not audio_b64:
        return None
    
    try:
        groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        
        # Decode base64 back to bytes
        audio_bytes = base64.b64decode(audio_b64)
        
        transcription = await groq_client.audio.transcriptions.create(
            file=("audio.ogg", audio_bytes, "audio/ogg"),
            model="whisper-large-v3",
            language="en",
            response_format="text"
        )
        
        return transcription
        
    except Exception as e:
        print(f"Voice transcription error: {e}")
        return None

async def download_whatsapp_media(media_id: str, media_type: str = 'image') -> str | None:
    """Generic function to download any media from WhatsApp."""
    from config.settings import settings
    
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            media_response = await client.get(
                f"{settings.WHATSAPP_API_URL}/{media_id}",
                headers=headers
            )
            
            media_data = media_response.json()
            media_url = media_data.get('url')
            
            if not media_url:
                return None
            
            file_response = await client.get(media_url, headers=headers)
            return base64.b64encode(file_response.content).decode('utf-8')
            
        except Exception as e:
            print(f"Media download error: {e}")
            return None
