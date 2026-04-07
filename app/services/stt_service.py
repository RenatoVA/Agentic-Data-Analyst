from __future__ import annotations

from typing import Final

# Importamos AsyncGroq y los errores específicos de su SDK
from groq import AsyncGroq, APIStatusError, APIConnectionError, APIError

from app.core.config import Settings
from app.core.errors import STTTranscriptionError
import httpx


SUPPORTED_AUDIO_TYPES: Final[set[str]] = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/webm",
    "audio/ogg",
    "application/octet-stream",
}


class STTService:
    def __init__(self, settings: Settings):
        self.settings = settings
        api_key = self.settings.GROQ_API_KEY
        
        if not api_key:
            # Es mejor fallar rápido al iniciar el servicio si no hay API Key
            raise ValueError("Missing GROQ_API_KEY in configuration.")
            
        # Inicializamos el cliente asíncrono de Groq
        self.client = AsyncGroq(api_key=api_key,http_client=httpx.AsyncClient(verify=False))

    async def transcribe(self, *, audio_bytes: bytes, filename: str, content_type: str | None = None) -> str:
        try:
            if not audio_bytes:
                raise STTTranscriptionError("Audio payload is empty.")

            # Limpiar el MIME type para la validación
            mime = content_type or "application/octet-stream"
            base_mime = mime.split(";")[0].strip()
            
            if base_mime not in SUPPORTED_AUDIO_TYPES:
                raise STTTranscriptionError(f"Unsupported audio content type: {mime}", status_code=415)

            model = str(self.settings.GROQ_STT_MODEL or "").strip()
            if not model:
                raise STTTranscriptionError("Missing GROQ_STT_MODEL in configuration.", status_code=500)

            response_format = str(self.settings.GROQ_STT_RESPONSE_FORMAT or "json")
            
            # Preparamos los argumentos para el SDK de Groq
            kwargs = {
                # El SDK acepta una tupla (nombre_archivo, bytes) para subir archivos en memoria
                "file": (filename, audio_bytes),
                "model": model,
                "response_format": response_format,
            }

            if self.settings.GROQ_STT_LANGUAGE:
                kwargs["language"] = str(self.settings.GROQ_STT_LANGUAGE)

            try:
                # Llamada asíncrona usando el SDK oficial
                transcription = await self.client.audio.transcriptions.create(**kwargs)
                
            except APIStatusError as exc:
                # Errores que devuelve la API de Groq (ej. 400, 500)
                raise STTTranscriptionError(
                    f"STT provider rejected request ({exc.status_code}): {exc.message}",
                    status_code=502,
                ) from exc
            except APIConnectionError as exc:
                raise STTTranscriptionError(f"STT connection failed: {exc}", status_code=502) from exc
            except APIError as exc:
                raise STTTranscriptionError(f"STT request failed: {exc}", status_code=502) from exc

            # Dependiendo de response_format, el SDK devuelve un objeto con .text o un string
            if hasattr(transcription, "text"):
                text = transcription.text
            elif isinstance(transcription, str):
                text = transcription
            elif isinstance(transcription, dict):
                text = transcription.get("text")
            else:
                text = None

            if not text:
                raise STTTranscriptionError("STT response missing transcription text.", status_code=502)

            return str(text).strip()

        except STTTranscriptionError:
            raise
        except Exception as exc:
            raise STTTranscriptionError(f"Unexpected STT processing error: {exc}", status_code=502) from exc