# Native capture (Fase 1)

La app Expo en `apps/mobile` consume el mismo contrato HTTP que el portal web.

El puente nativo (todavía por implementar en Swift/Kotlin) debe:

1. Registrarse como App Intent (iOS Back Tap / Action Button) o Quick Setting (Android).
2. Abrir el stream de micrófono.
3. Transcribir on-device (Speech framework / SpeechRecognizer) o enviar a Whisper.
4. POST `{ "transcript": "..." }` a `/api/v1/intents/transcribe`.
5. No persistir el audio.

Hasta que el puente nativo esté compilado, el campo de texto de Expo simula exactamente ese payload.
