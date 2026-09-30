# Smart Scheduler AI ⏱️⚡

[![Status](https://img.shields.io/badge/status-active%20development-brightgreen)](#)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](#)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI%20%7C%20Python-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![React Native](https://img.shields.io/badge/Mobile-React%20Native%20%7C%20Expo-61DAFB.svg?logo=react)](https://reactnative.dev)
[![Next.js](https://img.shields.io/badge/Web-Next.js%2014-black.svg?logo=next.js)](https://nextjs.org)

**Smart Scheduler AI** es un asistente contextual de última generación diseñado para eliminar por completo la fricción operativa en la gestión de tiempo personal y profesional. Transforma intenciones expresadas por voz o texto en bloques de tiempo optimizados, calculando automáticamente traslados en tiempo real y negociando reuniones con terceros de forma desatendida.

---

## 🌟 Propuesta de Valor & Características Principales

* 🎙️ **Captura Ubicua y Sin Fricción:** Invocación instantánea mediante gestos del sistema (*Back Tap* o *Action Button* en iOS vía Native App Intents; *Quick Settings* / App Actions en Android) sin necesidad de abrir la aplicación.
* ⚡ **Procesamiento de Ultra Baja Latencia (<3.0s):** Pipeline híbrido de voz a texto (Apple Speech on-device con fallback a Whisper API) y modelos LLM ligeros con *Structured Outputs* (JSON Schema estricto).
* 🚗 **Orquestación Contextual Inteligente:** Motor de optimización CSP (*Constraint Satisfaction Problem* vía Google OR-Tools) que inserta automáticamente bloques de desplazamiento dinámicos usando Google Maps Distance Matrix / MapKit.
* 🤖 **Negociación Desatendida con Terceros:** Coordina y reserva espacios enviando 2 a 3 opciones óptimas por el canal preferido del destinatario (WhatsApp vía Meta Cloud API, SMS o Email) sin obligar a la otra persona a registrarse o instalar la app.
* 🔄 **Sincronización Multi-Calendario Bidireccional:** Integración transparente con Google Calendar v3, Microsoft Graph (Outlook) y calendarios locales vía EventKit.
* 🔒 **Seguridad y Privacidad Estricta:** Cifrado en tránsito (TLS 1.3) y en reposo (AES-256). Streaming de audio sin persistencia permanente en cumplimiento con GDPR y CCPA.

---

## 🏗️ Arquitectura del Sistema

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        CLIENTES & INTERFACES                          │
├───────────────────────────────────┬────────────────────────────────────┤
│           Móvil (React Native/Expo)│       Web Portal (Next.js 14)      │
│  [Swift Bridge]   [Kotlin Bridge] │   - Confirmación rápida (URLs)     │
│  • App Intents     • Quick Settings│   - Panel de usuario & métricas    │
│  • Speech/EventKit • App Actions   │   - Tailwind CSS                   │
└─────────────────┬─────────────────┴──────────────────┬─────────────────┘
                  │                                    │
                  └────────────► HTTPS / WSS ◄─────────┘
                                       │
┌──────────────────────────────────────▼─────────────────────────────────┐
│                    BACKEND ORQUESTADOR (FastAPI / Python)              │
├────────────────────────────────────────────────────────────────────────┤
│  • Pipelines Asíncronos & Autenticación OAuth                          │
│  • Motor CSP (Google OR-Tools): Cálculo de restricciones y holguras    │
│  • Integración IA: Apple Speech / OpenAI Whisper + Gemini / GPT        │
│  • Webhooks Engine (Meta Cloud API, Resend, Twilio)                    │
└──────────────────┬───────────────────────────────────┬─────────────────┘
                   │                                   │
┌──────────────────▼───────────────┐   ┌───────────────▼─────────────────┐
│       PERSISTENCIA & CACHÉ       │   │        SERVICIOS EXTERNOS       │
├──────────────────────────────────┤   ├─────────────────────────────────┤
│ • PostgreSQL (Prisma / SQLA)     │   │ • Google / Outlook Calendar API │
│ • Redis (Sessions, Pub/Sub, Rate)│   │ • Google Maps Distance Matrix   │
└──────────────────────────────────┘   │ • Meta Cloud API (WhatsApp)     │
                                       └─────────────────────────────────┘
```

---

## 🛠️ Stack Tecnológico

| Capa | Tecnologías |
| :--- | :--- |
| **Mobile App** | React Native (Expo), Swift Modules (App Intents, EventKit, Speech), Kotlin Modules |
| **Web & Landing** | Next.js (App Router), React, Tailwind CSS |
| **Backend API** | Python 3.11+, FastAPI, Uvicorn, Pydantic v2 |
| **Motor de Optimización**| Google OR-Tools (Constraint Satisfaction Problem Solver) |
| **Modelos de IA** | Apple Speech Framework, OpenAI Whisper API, Gemini 1.5 Flash / GPT-4o-mini |
| **Base de Datos & Caché**| PostgreSQL 15+, Redis 7+ |
| **APIs Externas** | Google Calendar v3, Microsoft Graph, Google Maps Distance Matrix, Meta Cloud API |

---

## 📂 Estructura del Repositorio

```bash
smart-scheduler-ai/
├── apps/
│   ├── mobile/             # Aplicación React Native (Expo)
│   │   ├── ios/            # Extensiones y puentes nativos Swift (App Intents)
│   │   ├── android/        # Extensiones nativas Kotlin
│   │   └── src/            # Lógica compartida de UI y estado
│   └── web/                # Portal Web y Landing de confirmación (Next.js)
│
├── services/
│   └── api/                # Backend Orquestador FastAPI
│       ├── app/
│       │   ├── api/        # Routers y endpoints (v1)
│       │   ├── core/       # Configuraciones y seguridad
│       │   ├── engine/     # Algoritmo CSP con OR-Tools y cálculos de rutas
│       │   ├── services/   # Clientes de IA, Calendarios y Mensajería
│       │   └── models/     # Esquemas Pydantic y modelos de DB
│       ├── tests/
│       └── Dockerfile
│
├── packages/               # Paquetes compartidos (tipos, esquemas JSON, configs)
├── docker-compose.yml      # Entorno local para PostgreSQL, Redis y API
└── README.md
```

---

## 🚀 Puesta en Marcha Local

### Prerrequisitos
* **Node.js** >= 18.x & **pnpm** / **npm**
* **Python** >= 3.11
* **Docker** & **Docker Compose**
* Xcode (opcional, para compilar módulos nativos iOS en simulador/dispositivo)

### 1. Clonar el repositorio
```bash
git clone https://github.com/tu-organizacion/smart-scheduler-ai.git
cd smart-scheduler-ai
```

### 2. Variables de Entorno
Copia el archivo de ejemplo y completa las claves de API necesarias:
```bash
cp .env.example .env
```
Campos clave en `.env`:
* `OPENAI_API_KEY` / `GEMINI_API_KEY`
* `GOOGLE_MAPS_API_KEY`
* `META_WHATSAPP_TOKEN`
* `DATABASE_URL` y `REDIS_URL`

### 3. Levantar Infraestructura y Backend
```bash
# Iniciar PostgreSQL y Redis
docker compose up -d postgres redis

# Iniciar el backend FastAPI
cd services/api
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
La documentación interactiva estará disponible en `http://localhost:8000/docs`.

### 4. Iniciar Frontend Móvil y Web
```bash
# En la raíz del proyecto
pnpm install

# Para iniciar el portal Web (Next.js)
pnpm --filter web dev

# Para iniciar Expo (Mobile)
pnpm --filter mobile start
```

---

## 🔄 Flujo de Trabajo (End-to-End)

```mermaid
sequenceDiagram
    autonumber
    actor User as Usuario
    participant OS as iOS (Back Tap / AppIntent)
    participant STT as STT Engine (Apple/Whisper)
    participant API as FastAPI Backend
    participant LLM as LLM (Structured JSON)
    participant CSP as OR-Tools + Maps API
    participant Cal as EventKit / Google Cal

    User->>OS: Triple toque trasero (Back Tap)
    OS->>STT: Stream de Audio en tiempo real
    STT->>API: Transcripción de texto
    API->>LLM: Prompt + Esquema de Entidades
    LLM-->>API: JSON {evento, fecha, ubicación, personas}
    API->>CSP: Resolver conflictos y calcular ruta/tráfico
    CSP-->>API: Slot óptimo + Bloque de viaje
    API->>Cal: Inyectar cita y tiempos de tránsito
    Cal-->>User: Feedback Háptico + Banner de confirmación (<3s)
```

---

## 🗺️ Hoja de Ruta (Roadmap)

- [x] **Fase 1: Captura de Voz a Calendario (MVP)**
  - Integración nativa de App Intents vinculables a Back Tap.
  - Streaming STT + Extracción estructurada con LLM.
  - Inserción local de eventos vía EventKit.
- [ ] **Fase 2: Motor de Rutas y Optimización CSP**
  - Integración con Google Maps Distance Matrix.
  - Algoritmo CSP con Google OR-Tools para gestión de bloques de tránsito.
  - Sincronización remota con Google Calendar y Outlook Graph.
- [ ] **Fase 3: Coordinación Externa Desatendida**
  - Despacho de plantillas interactivas vía WhatsApp (Meta Cloud API).
  - Webhooks y portal web ligero para confirmación sin autenticación requerida.
- [ ] **Fase 4: Reprogramación Adaptativa**
  - Detección en segundo plano de desviaciones por tráfico o demoras.
  - Re-scheduling inteligente en cascada a un toque.

---

## 🛡️️ Seguridad y Buenas Prácticas

* **No-Log Audio Policy:** El flujo de voz recibido por streaming se procesa en memoria volátil y se descarta inmediatamente tras la transcripción.
* **Cifrado Estricto:** Toda comunicación externa utiliza TLS 1.3. La base de datos opera bajo cifrado AES-256.
* **Tokens Criptográficos Temporales:** Los enlaces de confirmación enviados a terceros utilizan URLs firmadas con expiración automática.

---

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor, revisa las guías antes de enviar un Pull Request:

1. Crea un branch para tu feature: `git checkout -b feature/AmazingFeature`
2. Realiza tus commits respetando Conventional Commits: `git commit -m 'feat: add route buffer calculation'`
3. Haz push a tu rama: `git push origin feature/AmazingFeature`
4. Abre un Pull Request describiendo el contexto y pruebas ejecutadas.

---

## 📄 Licencia

Este proyecto está bajo los términos de la licencia **MIT**. Consulta el archivo `LICENSE` para más información.