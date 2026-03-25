"""
AI Radio Service for Freedify.
Generates continuous playlist recommendations based on a seed track or mood.
"""
import os
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class AIRadioService:
    """AI-powered radio that generates track recommendations."""
    
    def __init__(self):
        # Helper for key fallback logic if needed, but primary is env var
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self._genai = None
        self._model = None
    
    def _init_genai(self):
        """Lazy initialization of Gemini client."""
        if self._genai is None:
            try:
                import google.generativeai as genai
                if not self.api_key:
                    logger.warning("GEMINI_API_KEY not set - AI Radio will use basic mode")
                    return False
                genai.configure(api_key=self.api_key)
                self._genai = genai
                self._model = genai.GenerativeModel('gemini-2.0-flash')
                logger.info("AI Radio: Gemini initialized")
                return True
            except ImportError:
                logger.warning("google-generativeai not installed")
                return False
            except Exception as e:
                logger.error(f"Failed to initialize Gemini for AI Radio: {e}")
                return False
        return True
    
    async def generate_recommendations(
        self,
        seed_track: Optional[Dict[str, Any]] = None,
        mood: Optional[str] = None,
        current_queue: List[Dict[str, Any]] = None,
        count: int = 5,
        mood_liked: Optional[List[str]] = None,
        mood_disliked: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate track recommendations for AI Radio.
        
        Args:
            seed_track: A track to base recommendations on (name, artist, bpm, key)
            mood: A mood/vibe description if no seed track
            current_queue: Current queue to avoid duplicates
            count: Number of recommendations to generate
            
        Returns:
            Dict with search_terms to find recommended tracks
        """
        current_queue = current_queue or []
        
        # Build context
        if seed_track:
            context = f"""Based on this seed track:
Title: "{seed_track.get('name', 'Unknown')}"
Artist: {seed_track.get('artists', 'Unknown')}
BPM: {seed_track.get('bpm', 'Unknown')}
Key: {seed_track.get('camelot', 'Unknown')}"""
            # Append mood alongside seed track (not elif — both can coexist)
            if mood:
                context += f'\nMood/vibe context: "{mood}"'
        elif mood:
            context = f'Based on this mood/vibe: "{mood}"'
        else:
            context = "Generate a diverse mix of popular tracks"

        # Append mood-based personalization context
        if mood_liked:
            liked_str = ", ".join(mood_liked[:5])
            context += f"\nThe user especially enjoys tracks like: {liked_str} in this mood."
        if mood_disliked:
            disliked_str = ", ".join(mood_disliked[:5])
            context += f"\nAvoid tracks like: {disliked_str}"
        
        # Exclude current queue tracks
        exclude_list = []
        for t in current_queue[:10]:  # Limit to last 10
            exclude_list.append(f"- {t.get('name', '')} by {t.get('artists', '')}")
        
        exclude_str = "\n".join(exclude_list) if exclude_list else "None"
        
        # Try AI generation
        if self._init_genai() and self._model:
            try:
                return await self._ai_generate_recommendations(
                    context, exclude_str, count, seed_track
                )
            except Exception as e:
                logger.error(f"AI recommendation failed: {e}")
        
        # Fallback: return genre-based search terms
        return self._fallback_recommendations(seed_track, mood, count)
    
    async def _ai_generate_recommendations(
        self,
        context: str,
        exclude_str: str,
        count: int,
        seed_track: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate recommendations using Gemini AI."""
        import json
        
        prompt = f"""{context}

TASK: Recommend {count} songs that would flow well in a DJ mix or playlist.

RULES:
1. Match the energy, tempo, and vibe of the seed track or mood
2. Consider harmonic compatibility (Camelot wheel)
3. Mix well-known tracks with hidden gems
4. Vary artists but keep genre/style consistent

EXCLUDE these tracks already in queue:
{exclude_str}

Respond ONLY with valid JSON:
{{
  "recommendations": [
    {{"artist": "Artist Name", "title": "Song Title", "reason": "Why it fits"}},
    ...
  ],
  "suggested_searches": ["search term 1", "search term 2", ...],
  "vibe_description": "Brief description of the vibe"
}}"""

        response = await self._model.generate_content_async(prompt)
        text = response.text.strip()
        
        # Extract JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        data = json.loads(text)
        
        # Build search terms from recommendations
        search_terms = []
        for rec in data.get("recommendations", [])[:count]:
            artist = rec.get("artist", "")
            title = rec.get("title", "")
            if artist and title:
                search_terms.append(f"{artist} {title}")
        
        # Add suggested searches as fallback
        search_terms.extend(data.get("suggested_searches", [])[:3])
        
        logger.info(f"AI Radio generated {len(search_terms)} recommendations")
        
        return {
            "search_terms": search_terms,
            "recommendations": data.get("recommendations", []),
            "vibe_description": data.get("vibe_description", ""),
            "method": "ai"
        }
    
    def _fallback_recommendations(
        self,
        seed_track: Optional[Dict[str, Any]],
        mood: Optional[str],
        count: int
    ) -> Dict[str, Any]:
        """Fallback when AI is unavailable."""
        search_terms = []
        
        if seed_track:
            # Search for similar based on artist
            artist = seed_track.get("artists", "").split(",")[0].strip()
            if artist:
                search_terms.append(f"{artist}")
                search_terms.append(f"{artist} remix")
        
        if mood:
            search_terms.append(mood)
        
        # Generic fallback
        if not search_terms:
            search_terms = ["popular electronic", "chill beats", "dance hits"]
        
        return {
            "search_terms": search_terms[:count],
            "recommendations": [],
            "vibe_description": "Based on your selection",
            "method": "fallback"
        }
    

    
    async def generate_playlist(
        self,
        description: str,
        duration_mins: int = 60,
        track_count: int = 15,
        mood: Optional[str] = None,
        mood_liked: Optional[List[str]] = None,
        mood_disliked: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a playlist from a natural language description.

        Args:
            description: Playlist description like "morning coffee jazz" or "high energy workout"
            duration_mins: Target duration in minutes
            track_count: Number of tracks to generate
            mood: Current mood context (e.g. "Focus", "Workout", or free-form)
            mood_liked: Tracks the user enjoys in this mood
            mood_disliked: Tracks the user dislikes in this mood

        Returns:
            Dict with tracks (artist + title pairs), playlist name, description
        """
        if not self._init_genai() or not self._model:
            return {
                "tracks": [],
                "playlist_name": "Generated Playlist",
                "description": description,
                "method": "fallback",
                "error": "AI not available"
            }
        
        try:
            import json
            
            # Estimate tracks based on duration (avg 3.5 min per track)
            estimated_tracks = min(max(duration_mins // 4, 5), track_count)
            
            mood_context = ""
            if mood:
                mood_context += f'\nMOOD/VIBE: "{mood}"'
            if mood_liked:
                liked_str = ", ".join(mood_liked[:5])
                mood_context += f"\nUSER FAVORITES IN THIS MOOD: {liked_str}"
            if mood_disliked:
                disliked_str = ", ".join(mood_disliked[:5])
                mood_context += f"\nAVOID TRACKS LIKE: {disliked_str}"

            prompt = f"""You are a music curator. Create a playlist based on this description.

DESCRIPTION: "{description}"
TARGET DURATION: ~{duration_mins} minutes ({estimated_tracks} tracks){mood_context}

TASK: Generate a cohesive playlist that matches the vibe and purpose.

RULES:
1. Mix popular tracks with quality deep cuts
2. Consider flow and energy progression
3. Vary artists while maintaining style consistency
4. Include specific, real songs (not made-up titles)
5. If mood preferences are provided, lean toward the user's taste and avoid disliked styles

Respond ONLY with valid JSON:
{{
  "playlist_name": "Creative name for this playlist",
  "description": "Brief description of the vibe",
  "tracks": [
    {{"artist": "Artist Name", "title": "Song Title"}},
    ...
  ]
}}"""

            response = await self._model.generate_content_async(prompt)
            text = response.text.strip()
            
            # Extract JSON
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(text)
            data["method"] = "ai"
            data["requested_duration"] = duration_mins
            
            logger.info(f"Generated playlist '{data.get('playlist_name')}' with {len(data.get('tracks', []))} tracks")
            return data
            
        except Exception as e:
            logger.error(f"Playlist generation error: {e}")
            return {
                "tracks": [],
                "playlist_name": "Generated Playlist",
                "description": description,
                "method": "fallback",
                "error": str(e)
            }


# Singleton instance
ai_radio_service = AIRadioService()
