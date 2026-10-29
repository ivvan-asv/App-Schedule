# Smart Scheduler — cliente iOS (Swift)

Cliente nativo en Swift 6 / SwiftUI para iOS 17+. Cubre la Fase 1 del plan:
capturar una nota por voz sin abrir la app, enviarla al backend, que la
convierte en evento, y escribir ese evento en el calendario del dispositivo.

## Estructura

```text
iOS/
├── project.yml              # Especificación XcodeGen del proyecto
├── SmartSchedulerKit/       # Paquete Swift sin UI (se prueba con `swift test`)
│   ├── Sources/SmartSchedulerKit/
│   │   ├── Models.swift              # Modelos del API (nombres del backend)
│   │   ├── SchedulerAPI.swift        # Cliente HTTP y mapeo de errores
│   │   ├── SchedulerAccount.swift    # Usuario, zona horaria, horario laboral inicial
│   │   ├── PendingCaptureStore.swift # Cola offline cifrada (Data Protection)
│   │   └── CaptureCoordinator.swift  # Envío, encolado y reenvío de capturas
│   └── Tests/
└── SmartScheduler/          # Target de la app
    ├── App/                 # @main, AppServices (dependencias), AppModel (estado)
    ├── Capture/             # Dictado con Speech on-device y pantalla de captura
    ├── Agenda/              # Próximos 7 días
    ├── Settings/            # Servidor, permiso de calendario, cola, Back Tap
    ├── Intents/             # App Intents y App Shortcuts (RF01)
    └── Platform/            # EventKit y monitor de red
```

## Cómo se cubren los requisitos

| Requisito | Implementación |
| :--- | :--- |
| RF01 Activación | `ScheduleNoteIntent` («Agendar nota») se ejecuta sin abrir la app; el sistema pide la nota por dictado. `DictateCaptureIntent` abre la app escuchando. Ambos aparecen en Atajos y Siri, y se asignan a Back Tap o al botón de Acción. |
| RF02 STT | `SpeechTranscriber`: `SFSpeechRecognizer` con `requiresOnDeviceRecognition` cuando el idioma está instalado. Termina sola tras 1,5 s de silencio. |
| RF03 Extracción | La hace el backend (`POST /users/{id}/captures`); la app solo envía el texto. |
| Fase 1: EventKit | `EventKitCalendar` escribe cada evento agendado en el calendario del iPhone y no lo duplica si una captura se reenvía. |
| Fase 2: calendario local | Con acceso completo, cada captura envía las horas ocupadas de los próximos 14 días (`busy_intervals`), sin títulos ni asistentes. Se omiten los eventos de todo el día, los marcados como libres y las invitaciones rechazadas. Se leen al enviar, no al encolar, para que una nota en cola use el calendario actual. |
| RNF01 Latencia | Se usa la transcripción parcial sin esperar el resultado final. El backend devuelve `latency_ms`. |
| RNF02 Privacidad | El audio solo pasa por memoria. La cola offline se guarda con `completeFileProtectionUntilFirstUserAuthentication`, que la cifra con AES-256 en reposo. |
| RNF03 Offline | Si el servidor no responde o el LLM devuelve 503, la nota queda en cola con su `local_id`. Se reenvía al recuperar la red (`NWPathMonitor`), al volver a primer plano o en un `BGAppRefreshTask`. El backend devuelve la captura original en vez de duplicarla. |
| RNF04 Batería | No hay procesos en segundo plano permanentes: solo APIs del sistema invocadas bajo demanda. |

## Requisitos

- Xcode 16 o posterior (Swift 6, SDK de iOS 17+).
- [XcodeGen](https://github.com/yonaskolb/XcodeGen): `brew install xcodegen`.
- El backend corriendo (ver `Backend/README.md`) con `ANTHROPIC_API_KEY`.

## Generar y ejecutar

```bash
cd iOS
xcodegen                     # crea SmartScheduler.xcodeproj
open SmartScheduler.xcodeproj
```

Selecciona tu equipo en *Signing & Capabilities* y ejecuta en un simulador o
dispositivo. En el simulador el servidor por defecto es `http://localhost:8000`.

En un iPhone físico (misma red Wi-Fi que el Mac):

1. Arranca uvicorn con `--host 0.0.0.0`.
2. Busca el nombre del Mac con `scutil --get LocalHostName`.
3. En **Ajustes › Servidor** escribe `http://<ese-nombre>.local:8000`.
4. Acepta el aviso de **red local** que muestra iOS.

Usa el nombre `.local` y no la IP: la excepción de ATS para desarrollo
(`NSAllowsLocalNetworking`) permite HTTP sin cifrar hacia nombres `.local`.

En el primer uso la app crea el usuario demo, le asigna la zona horaria del
dispositivo y, si no tiene ninguno, crea un horario laboral de lunes a viernes
de 09:00 a 18:00, que el backend necesita para colocar notas sin hora.

## Configurar Back Tap

1. En **Atajos**, crea un atajo con la acción **Agendar nota** de Smart Scheduler.
2. En **Ajustes › Accesibilidad › Tocar › Toque atrás**, asigna el atajo a
   doble o triple toque. En iPhone 15 Pro o posterior también se puede asignar
   al botón de Acción.
3. Al tocar la parte trasera, iOS pide la nota, la dictas y recibes la
   confirmación hablada y háptica.

## Pruebas

```bash
cd iOS/SmartSchedulerKit
swift test
```

Las pruebas usan un transporte HTTP falso y no necesitan backend. Cubren el
formato del API (snake_case y fechas con microsegundos de Pydantic), el
mapeo de errores HTTP, el arranque de la cuenta y la cola offline, incluido
que no se pierda una captura encolada mientras se vacía la cola.
