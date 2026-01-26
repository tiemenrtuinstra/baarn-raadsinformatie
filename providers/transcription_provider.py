#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Transcription Provider voor Baarn Politiek MCP Server.
Transcribeert video/audio met OpenAI Whisper (lokaal).
Ondersteunt: Notubiz video URLs, YouTube, lokale bestanden.
"""

import os
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from core.config import Config
from core.database import Database, get_database
from shared.logging_config import get_logger, LogContext

logger = get_logger('transcription-provider')

# Whisper support (lazy loaded)
WHISPER_AVAILABLE = False
whisper_model = None

try:
    import whisper
    WHISPER_AVAILABLE = True
    logger.info('OpenAI Whisper available')
except ImportError:
    logger.warning(
        'openai-whisper not installed. '
        'Install with: pip install openai-whisper'
    )

# YouTube download support
YT_DLP_AVAILABLE = False
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
    logger.info('yt-dlp available for YouTube downloads')
except ImportError:
    logger.warning('yt-dlp not installed. YouTube download disabled.')


class TranscriptionProvider:
    """
    Provider voor video/audio transcriptie.

    Gebruikt OpenAI Whisper lokaal voor transcriptie.
    Ondersteunt Notubiz video URLs, YouTube en lokale bestanden.
    """

    def __init__(self, db: Database = None):
        """Initialize transcription provider."""
        self.db = db or get_database()
        self._model = None
        self.model_size = os.getenv('WHISPER_MODEL', 'small')
        self.language = os.getenv('TRANSCRIPTION_LANGUAGE', 'nl')
        self.keep_audio = os.getenv('KEEP_AUDIO_FILES', 'false').lower() == 'true'
        self.audio_dir = Config.DATA_DIR / 'audio'
        self.audio_dir.mkdir(exist_ok=True)

        logger.info(f'TranscriptionProvider initialized (whisper: {WHISPER_AVAILABLE}, model: {self.model_size})')

    def _load_model(self):
        """Lazy load Whisper model."""
        global whisper_model

        if not WHISPER_AVAILABLE:
            raise RuntimeError(
                'OpenAI Whisper is niet geïnstalleerd. '
                'Installeer met: pip install openai-whisper'
            )

        if whisper_model is None:
            logger.info(f'Loading Whisper model: {self.model_size}')
            whisper_model = whisper.load_model(self.model_size)
            logger.info('Whisper model loaded successfully')

        self._model = whisper_model

    def _check_ffmpeg(self) -> bool:
        """Check if FFmpeg is available."""
        try:
            subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning('FFmpeg not found. Install FFmpeg for audio extraction.')
            return False

    def _download_video(self, url: str, output_path: Path) -> bool:
        """Download video from URL using yt-dlp."""
        if not YT_DLP_AVAILABLE:
            raise RuntimeError('yt-dlp niet geïnstalleerd voor video download')

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(output_path),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return True
        except Exception as e:
            logger.error(f'Video download failed: {e}')
            return False

    def _download_direct_url(self, url: str, output_path: Path) -> bool:
        """Download audio/video directly from URL."""
        import requests

        try:
            response = requests.get(url, stream=True, timeout=300)
            response.raise_for_status()

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            logger.error(f'Direct download failed: {e}')
            return False

    def _extract_audio(self, video_path: Path, audio_path: Path) -> bool:
        """Extract audio from video using FFmpeg."""
        try:
            subprocess.run([
                'ffmpeg', '-i', str(video_path),
                '-vn', '-acodec', 'mp3', '-ab', '192k',
                '-y', str(audio_path)
            ], capture_output=True, check=True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f'Audio extraction failed: {e}')
            return False

    def _transcribe_audio(self, audio_path: Path) -> Dict:
        """Transcribe audio file with Whisper."""
        self._load_model()

        logger.info(f'Transcribing: {audio_path}')

        # Transcribe with word-level timestamps
        result = self._model.transcribe(
            str(audio_path),
            language=self.language if self.language != 'auto' else None,
            verbose=False
        )

        return {
            'text': result['text'],
            'language': result.get('language', self.language),
            'segments': result.get('segments', []),
            'duration': result.get('segments', [{}])[-1].get('end', 0) if result.get('segments') else 0
        }

    def transcribe_meeting(self, meeting_id: int) -> Dict:
        """
        Transcribeer de video van een vergadering.

        Args:
            meeting_id: Database ID van de vergadering

        Returns:
            Dict met transcriptie resultaat
        """
        meeting = self.db.get_meeting(meeting_id=meeting_id)
        if not meeting:
            return {'error': f'Vergadering {meeting_id} niet gevonden'}

        video_url = meeting.get('video_url')
        if not video_url:
            return {'error': f'Vergadering {meeting_id} heeft geen video URL'}

        # Check of er al een transcriptie is
        existing = self.db.get_transcription(meeting_id=meeting_id)
        if existing and existing.get('transcription_status') == 'completed':
            return {
                'transcription_id': existing['id'],
                'status': 'already_exists',
                'text': existing.get('transcript_text', '')[:500] + '...' if existing.get('transcript_text') else '',
                'message': 'Transcriptie bestaat al'
            }

        # Maak transcriptie record
        transcription_id = existing['id'] if existing else self.db.add_transcription(
            source_type='notubiz',
            meeting_id=meeting_id,
            source_url=video_url,
            transcription_status='processing'
        )

        if not existing:
            self.db.update_transcription(transcription_id, transcription_status='processing')

        with LogContext(logger, 'transcribe_meeting', meeting_id=meeting_id):
            try:
                # Bepaal source type
                if 'youtube.com' in video_url or 'youtu.be' in video_url:
                    result = self.transcribe_youtube(video_url)
                else:
                    result = self.transcribe_url(video_url, source_type='notubiz')

                if 'error' in result:
                    self.db.update_transcription(
                        transcription_id,
                        transcription_status='failed',
                        error_message=result['error']
                    )
                    return result

                # Update database
                self.db.update_transcription(
                    transcription_id,
                    transcript_text=result['text'],
                    transcript_language=result.get('language', 'nl'),
                    whisper_model=self.model_size,
                    duration_seconds=int(result.get('duration', 0)),
                    transcription_status='completed'
                )

                # Index embeddings voor semantic search
                self._index_transcription(transcription_id, result['text'], result.get('segments', []))

                return {
                    'transcription_id': transcription_id,
                    'meeting_id': meeting_id,
                    'status': 'completed',
                    'text_preview': result['text'][:500] + '...' if len(result['text']) > 500 else result['text'],
                    'duration_seconds': result.get('duration', 0),
                    'language': result.get('language', 'nl')
                }

            except Exception as e:
                logger.error(f'Transcription failed: {e}')
                self.db.update_transcription(
                    transcription_id,
                    transcription_status='failed',
                    error_message=str(e)
                )
                return {'error': str(e)}

    def transcribe_url(self, url: str, source_type: str = 'direct') -> Dict:
        """
        Transcribeer video/audio van een URL.

        Args:
            url: Video/audio URL
            source_type: 'notubiz', 'youtube', of 'direct'

        Returns:
            Dict met transcriptie text en metadata
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Download
            if source_type == 'youtube' or 'youtube.com' in url or 'youtu.be' in url:
                audio_path = temp_path / 'audio.mp3'
                if not self._download_video(url, temp_path / 'audio'):
                    return {'error': 'Video download mislukt'}
                # yt-dlp adds .mp3 extension
                audio_path = temp_path / 'audio.mp3'
            else:
                # Direct download
                video_path = temp_path / 'video.mp4'
                if not self._download_direct_url(url, video_path):
                    return {'error': 'Video download mislukt'}

                # Extract audio
                audio_path = temp_path / 'audio.mp3'
                if not self._extract_audio(video_path, audio_path):
                    # Try transcribing video directly
                    audio_path = video_path

            if not audio_path.exists():
                return {'error': 'Audio bestand niet gevonden na download'}

            # Transcribe
            result = self._transcribe_audio(audio_path)

            # Keep audio if configured
            if self.keep_audio:
                permanent_path = self.audio_dir / f'{datetime.now().strftime("%Y%m%d_%H%M%S")}.mp3'
                audio_path.rename(permanent_path)
                result['local_path'] = str(permanent_path)

            return result

    def transcribe_youtube(self, youtube_url: str) -> Dict:
        """
        Download en transcribeer YouTube video.

        Args:
            youtube_url: YouTube URL

        Returns:
            Dict met transcriptie
        """
        return self.transcribe_url(youtube_url, source_type='youtube')

    def transcribe_file(self, file_path: str) -> Dict:
        """
        Transcribeer een lokaal audio/video bestand.

        Args:
            file_path: Pad naar audio/video bestand

        Returns:
            Dict met transcriptie
        """
        path = Path(file_path)
        if not path.exists():
            return {'error': f'Bestand niet gevonden: {file_path}'}

        # Check if audio or video
        audio_extensions = {'.mp3', '.wav', '.m4a', '.ogg', '.flac'}
        video_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.webm'}

        if path.suffix.lower() in audio_extensions:
            return self._transcribe_audio(path)
        elif path.suffix.lower() in video_extensions:
            with tempfile.TemporaryDirectory() as temp_dir:
                audio_path = Path(temp_dir) / 'audio.mp3'
                if not self._extract_audio(path, audio_path):
                    # Try transcribing video directly
                    return self._transcribe_audio(path)
                return self._transcribe_audio(audio_path)
        else:
            return {'error': f'Onbekend bestandstype: {path.suffix}'}

    def _index_transcription(self, transcription_id: int, text: str, segments: List[Dict]):
        """Index transcriptie voor semantic search."""
        try:
            from core.document_index import get_document_index, EMBEDDINGS_AVAILABLE

            if not EMBEDDINGS_AVAILABLE:
                logger.warning('Embeddings not available - skipping transcription indexing')
                return

            index = get_document_index()

            # Delete existing embeddings
            self.db.delete_transcription_embeddings(transcription_id)

            # Create chunks with timestamps
            if segments:
                # Use Whisper segments for better timestamp accuracy
                for i, segment in enumerate(segments):
                    chunk_text = segment.get('text', '').strip()
                    if not chunk_text:
                        continue

                    embedding = index._get_embedding(chunk_text)
                    self.db.add_transcription_embedding(
                        transcription_id=transcription_id,
                        chunk_index=i,
                        chunk_text=chunk_text,
                        embedding=index._embedding_to_bytes(embedding),
                        timestamp_start=segment.get('start'),
                        timestamp_end=segment.get('end'),
                        model=index.model_name
                    )
            else:
                # Fallback: chunk text without timestamps
                chunks = index._chunk_text(text)
                for i, chunk in enumerate(chunks):
                    embedding = index._get_embedding(chunk)
                    self.db.add_transcription_embedding(
                        transcription_id=transcription_id,
                        chunk_index=i,
                        chunk_text=chunk,
                        embedding=index._embedding_to_bytes(embedding),
                        model=index.model_name
                    )

            logger.info(f'Indexed transcription {transcription_id}')

        except Exception as e:
            logger.error(f'Failed to index transcription: {e}')

    def search_transcriptions(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Zoek in transcripties met semantic search.

        Args:
            query: Zoekopdracht
            limit: Maximum resultaten

        Returns:
            Lijst met zoekresultaten inclusief timestamps
        """
        try:
            from core.document_index import get_document_index, EMBEDDINGS_AVAILABLE
            import numpy as np

            if not EMBEDDINGS_AVAILABLE:
                # Fallback to keyword search
                return self.db.search_transcriptions(query, limit)

            index = get_document_index()
            query_embedding = index._get_embedding(query)

            # Get all transcription embeddings
            embeddings = self.db.get_all_transcription_embeddings()
            if not embeddings:
                return []

            # Calculate similarities
            results = []
            for emb_data in embeddings:
                doc_embedding = index._bytes_to_embedding(emb_data['embedding'])
                similarity = index._cosine_similarity(query_embedding, doc_embedding)

                results.append({
                    'transcription_id': emb_data['transcription_id'],
                    'meeting_id': emb_data['meeting_id'],
                    'meeting_title': emb_data.get('meeting_title', ''),
                    'meeting_date': emb_data.get('meeting_date', ''),
                    'chunk_text': emb_data['chunk_text'],
                    'timestamp_start': emb_data.get('timestamp_start'),
                    'timestamp_end': emb_data.get('timestamp_end'),
                    'similarity': similarity
                })

            # Sort by similarity
            results.sort(key=lambda x: x['similarity'], reverse=True)

            return results[:limit]

        except Exception as e:
            logger.error(f'Transcription search failed: {e}')
            return self.db.search_transcriptions(query, limit)

    def get_pending_transcriptions_count(self) -> int:
        """Get count of meetings without transcription."""
        meetings = self.db.get_meetings_without_transcription()
        return len(meetings)

    def transcribe_all_pending(self, limit: int = 10) -> Dict:
        """
        Transcribeer alle vergaderingen zonder transcriptie.

        Args:
            limit: Maximum aantal te verwerken

        Returns:
            Dict met resultaat samenvatting
        """
        meetings = self.db.get_meetings_without_transcription()[:limit]

        results = {
            'total': len(meetings),
            'success': 0,
            'failed': 0,
            'details': []
        }

        for meeting in meetings:
            result = self.transcribe_meeting(meeting['id'])
            if 'error' in result:
                results['failed'] += 1
            else:
                results['success'] += 1
            results['details'].append({
                'meeting_id': meeting['id'],
                'title': meeting.get('title', ''),
                'result': result
            })

        return results


# Singleton instance
_provider_instance = None


def get_transcription_provider() -> TranscriptionProvider:
    """Get singleton transcription provider instance."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = TranscriptionProvider()
    return _provider_instance


if __name__ == '__main__':
    # Test
    provider = get_transcription_provider()

    print(f"Whisper available: {WHISPER_AVAILABLE}")
    print(f"yt-dlp available: {YT_DLP_AVAILABLE}")
    print(f"Model size: {provider.model_size}")

    pending = provider.get_pending_transcriptions_count()
    print(f"Meetings without transcription: {pending}")
