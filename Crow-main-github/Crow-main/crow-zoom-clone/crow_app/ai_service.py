# crow_app/ai_service.py - GROQ VERSION (SUPER FAST & FREE!)
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        """Initialize Groq API (FAST & FREE!)"""
        self.client = None
        self.use_fallback = True
        self.api_key = getattr(settings, 'GROQ_API_KEY', None)
        
        if self.api_key and len(self.api_key) > 10:
            try:
                # Groq uses OpenAI SDK with custom base URL
                from openai import OpenAI
                
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url="https://api.groq.com/openai/v1"
                )
                
                # Test it
                logger.info("🔄 Testing Groq connection...")
                test_response = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",  # Fast, free, good model
                    messages=[{"role": "user", "content": "Say OK"}],
                    max_tokens=10,
                    temperature=0.5
                )
                
                if test_response.choices[0].message.content:
                    self.use_fallback = False
                    logger.info("✅ Groq API initialized successfully!")
                    logger.info(f"✅ Test response: {test_response.choices[0].message.content}")
                else:
                    logger.warning("⚠️ Empty response from Groq")
                    self.use_fallback = True
                    
            except ImportError:
                logger.error("❌ OpenAI package not installed")
                logger.error("💡 Install: pip install openai --break-system-packages")
                self.use_fallback = True
                
            except Exception as e:
                logger.error(f"❌ Groq initialization failed: {str(e)}")
                logger.error(f"💡 Error type: {type(e).__name__}")
                
                error_str = str(e).lower()
                if "401" in error_str or "unauthorized" in error_str:
                    logger.error("💡 Check your API key at https://console.groq.com/keys")
                elif "429" in error_str or "rate" in error_str:
                    logger.error("💡 Rate limit hit - Groq has generous limits but they exist")
                    
                self.use_fallback = True
        else:
            logger.warning("⚠️ No Groq API key found")
            logger.warning("💡 Get FREE key at: https://console.groq.com/keys")
    
    def get_chat_response(self, user_message, user_context=None):
        """Get AI response from Groq or use fallback"""
        
        if self.use_fallback or self.client is None:
            logger.info("📝 Using fallback response")
            return self._get_fallback_response(user_message, user_context)
        
        try:
            # Create system prompt
            system_prompt = self._create_system_prompt(user_context)
            
            # Call Groq API (lightning fast!)
            response = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",  # Best free model
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=500,
                temperature=0.7,
                top_p=0.9
            )
            
            ai_response = response.choices[0].message.content
            logger.info(f"✅ Got Groq response ({len(ai_response)} chars)")
            return ai_response.strip()
            
        except Exception as e:
            logger.error(f"❌ Groq API error: {str(e)}")
            return self._get_fallback_response(user_message, user_context)
    
    def _create_system_prompt(self, user_context=None):
        """Create system prompt"""
        prompt = """You are Crow AI, a helpful assistant for the Crow video conferencing platform.

About Crow:
- Video conferencing platform (like Zoom/Google Meet)
- Features: video calls, meeting scheduling, team management, calendar integration
- Users can create and join teams for organized collaboration
- WebRTC-based real-time video communication

Your role:
- Help users with meetings, scheduling, and platform features
- Provide clear, concise, friendly responses (2-4 sentences)
- Guide users to appropriate pages when needed
- Troubleshoot technical issues
- Be conversational and helpful

Available features:
- Calendar: Schedule meetings
- Teams: Create/join teams
- Contacts: Manage contacts
- Video rooms: Join video calls
- Settings: Manage preferences"""
        
        if user_context:
            if user_context.get('username'):
                prompt += f"\n\nCurrent user: {user_context['username']}"
            if user_context.get('teams'):
                teams = [t['name'] for t in user_context['teams'][:3]]
                if teams:
                    prompt += f"\nUser's teams: {', '.join(teams)}"
        
        return prompt
    
    def _get_fallback_response(self, user_message, user_context=None):
        """Fallback responses"""
        message_lower = user_message.lower()
        
        if any(word in message_lower for word in ['hello', 'hi', 'hey']):
            username = user_context.get('username', 'there') if user_context else 'there'
            return f"Hello {username}! 👋 I'm Crow AI. How can I help you today?"
        
        if any(word in message_lower for word in ['meeting', 'schedule']):
            return "Schedule meetings from the **Calendar** page. Set date, time, and restrict to teams!"
        
        if any(word in message_lower for word in ['video', 'camera', 'audio']):
            return "For video/audio: Check browser permissions, allow camera/mic, close other apps, refresh page."
        
        if any(word in message_lower for word in ['team', 'group']):
            return "Manage teams from **Teams** page. Create teams, join with codes!"
        
        if any(word in message_lower for word in ['help']):
            return "I can help with: Meetings, Teams, Video calls, Contacts. What interests you?"
        
        if any(word in message_lower for word in ['thank']):
            return "You're welcome! 😊"
        
        if any(word in message_lower for word in ['bye']):
            return "Goodbye! 👋"
        
        return "I can help with meetings, teams, video calls. What would you like to know?"

# Create singleton
ai_service = AIService()
AI_SERVICE_AVAILABLE = not ai_service.use_fallback
gemini_service = ai_service  # Compatibility

if AI_SERVICE_AVAILABLE:
    logger.info("=" * 50)
    logger.info("🤖 Groq AI is ONLINE! (SUPER FAST)")
    logger.info("=" * 50)
else:
    logger.info("=" * 50)
    logger.info("🤖 Using fallback responses")
    logger.info("=" * 50)