-- =====================================================================
--  Smart Scheduler AI — Modelo de base de datos (PostgreSQL 15+)
--  Cubre: RF01–RF08 y RNF02/RNF03 de la especificación.
--  Redis queda fuera de este esquema: caché de tokens OAuth, rate-limit
--  y estado efímero de sesiones de negociación.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()

-- ---------------------------------------------------------------------
-- Tipos enumerados
-- ---------------------------------------------------------------------
CREATE TYPE plataforma_t        AS ENUM ('ios', 'android', 'web');
CREATE TYPE proveedor_cal_t     AS ENUM ('google', 'microsoft', 'apple_local');
CREATE TYPE estado_cuenta_t     AS ENUM ('activa', 'token_expirado', 'revocada');
CREATE TYPE canal_entrada_t     AS ENUM ('voz', 'texto');
CREATE TYPE estado_captura_t    AS ENUM ('encolada', 'procesando', 'procesada', 'error');
CREATE TYPE tipo_evento_t       AS ENUM ('tarea', 'reunion', 'traslado', 'buffer');
CREATE TYPE estado_evento_t     AS ENUM ('tentativo', 'confirmado', 'cancelado');
CREATE TYPE origen_evento_t     AS ENUM ('captura', 'manual', 'negociacion', 'sincronizacion');
CREATE TYPE prioridad_t         AS ENUM ('baja', 'media', 'alta', 'urgente');
CREATE TYPE modo_transporte_t   AS ENUM ('auto', 'transporte_publico', 'caminando', 'bicicleta');
CREATE TYPE tipo_regla_t        AS ENUM ('horario_laboral', 'comida', 'buffer_por_defecto', 'no_molestar', 'bloqueo');
CREATE TYPE canal_mensaje_t     AS ENUM ('whatsapp', 'sms', 'email');
CREATE TYPE estado_negoc_t      AS ENUM ('borrador', 'enviada', 'confirmada', 'rechazada', 'expirada', 'cancelada');
CREATE TYPE estado_propuesta_t  AS ENUM ('ofrecida', 'aceptada', 'descartada');
CREATE TYPE direccion_msg_t     AS ENUM ('saliente', 'entrante');
CREATE TYPE estado_msg_t        AS ENUM ('en_cola', 'enviado', 'entregado', 'leido', 'fallido', 'recibido');
CREATE TYPE motivo_reprog_t     AS ENUM ('retraso_trafico', 'evento_extendido', 'cancelacion', 'conflicto_nuevo');
CREATE TYPE estado_reprog_t     AS ENUM ('pendiente', 'aceptada', 'rechazada', 'expirada');


-- =====================================================================
-- 1. USUARIOS Y DISPOSITIVOS
-- =====================================================================
CREATE TABLE usuarios (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    nombre          VARCHAR(120) NOT NULL,
    telefono        VARCHAR(20),
    zona_horaria    VARCHAR(64)  NOT NULL DEFAULT 'America/Santiago',
    idioma          VARCHAR(10)  NOT NULL DEFAULT 'es',
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    actualizado_en  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    eliminado_en    TIMESTAMPTZ                      -- borrado lógico (derecho al olvido GDPR)
);

CREATE TABLE dispositivos (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id       UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    plataforma       plataforma_t NOT NULL,
    modelo           VARCHAR(80),
    version_app      VARCHAR(20),
    push_token       TEXT,                           -- APNs / FCM
    ultima_conexion  TIMESTAMPTZ,
    creado_en        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_dispositivos_usuario ON dispositivos(usuario_id);


-- =====================================================================
-- 2. CALENDARIOS EXTERNOS (RF07 — sincronización bidireccional)
-- =====================================================================
CREATE TABLE cuentas_calendario (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id               UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    proveedor                proveedor_cal_t NOT NULL,
    email_externo            VARCHAR(255),
    access_token_cifrado     BYTEA,                  -- AES-256 a nivel de aplicación (RNF02)
    refresh_token_cifrado    BYTEA,
    token_expira_en          TIMESTAMPTZ,
    scopes                   TEXT[],
    estado                   estado_cuenta_t NOT NULL DEFAULT 'activa',
    creado_en                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (usuario_id, proveedor, email_externo)
);

CREATE TABLE calendarios (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cuenta_id          UUID NOT NULL REFERENCES cuentas_calendario(id) ON DELETE CASCADE,
    id_externo         VARCHAR(255) NOT NULL,        -- id en Google / Graph / EventKit
    nombre             VARCHAR(150) NOT NULL,
    es_principal       BOOLEAN NOT NULL DEFAULT FALSE,
    sincronizar        BOOLEAN NOT NULL DEFAULT TRUE,
    sync_token         TEXT,                         -- syncToken (Google) / deltaLink (Graph)
    ultima_sync_en     TIMESTAMPTZ,
    UNIQUE (cuenta_id, id_externo)
);


-- =====================================================================
-- 3. UBICACIONES (lugares frecuentes y de eventos)
-- =====================================================================
CREATE TABLE ubicaciones (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id    UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    alias         VARCHAR(80),                       -- "Casa", "Oficina", "Supermercado"
    direccion     TEXT,
    latitud       NUMERIC(9,6) NOT NULL,
    longitud      NUMERIC(9,6) NOT NULL,
    place_id      VARCHAR(255),                      -- Google Place ID / Mapbox
    es_frecuente  BOOLEAN NOT NULL DEFAULT FALSE,
    creado_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ubicaciones_usuario ON ubicaciones(usuario_id);


-- =====================================================================
-- 4. CAPTURAS (RF01–RF03, RNF03 offline)
--    No se guarda el audio: solo la transcripción (RNF02).
-- =====================================================================
CREATE TABLE capturas (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id          UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    dispositivo_id      UUID REFERENCES dispositivos(id) ON DELETE SET NULL,
    id_local            UUID,                        -- id generado en el móvil (idempotencia al sincronizar offline)
    canal               canal_entrada_t NOT NULL,
    transcripcion       TEXT,
    motor_stt           VARCHAR(40),                 -- 'apple_speech', 'whisper_groq', ...
    modelo_llm          VARCHAR(40),                 -- 'gemini-1.5-flash', 'gpt-4o-mini'
    resultado_llm       JSONB,                       -- salida estructurada completa del JSON Schema
    estado              estado_captura_t NOT NULL DEFAULT 'encolada',
    error_detalle       TEXT,
    creada_offline      BOOLEAN NOT NULL DEFAULT FALSE,
    capturada_en        TIMESTAMPTZ NOT NULL,        -- momento real del gesto en el dispositivo
    procesada_en        TIMESTAMPTZ,
    latencia_total_ms   INTEGER,                     -- para medir RNF01 (< 3000 ms)
    UNIQUE (dispositivo_id, id_local)
);
CREATE INDEX idx_capturas_usuario_estado ON capturas(usuario_id, estado);


-- =====================================================================
-- 5. EVENTOS (núcleo de la agenda)
--    Un traslado o buffer es también un evento (tipo='traslado'/'buffer')
--    ligado a la tarea que lo origina mediante evento_padre_id.
-- =====================================================================
CREATE TABLE eventos (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id          UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    calendario_id       UUID REFERENCES calendarios(id) ON DELETE SET NULL,
    captura_id          UUID REFERENCES capturas(id) ON DELETE SET NULL,
    ubicacion_id        UUID REFERENCES ubicaciones(id) ON DELETE SET NULL,
    evento_padre_id     UUID REFERENCES eventos(id) ON DELETE CASCADE,
    id_externo          VARCHAR(255),                -- id en el proveedor de calendario
    etag_externo        VARCHAR(255),                -- control de concurrencia en la sync
    titulo              VARCHAR(255) NOT NULL,
    descripcion         TEXT,
    tipo                tipo_evento_t   NOT NULL DEFAULT 'tarea',
    estado              estado_evento_t NOT NULL DEFAULT 'confirmado',
    origen              origen_evento_t NOT NULL,
    prioridad           prioridad_t     NOT NULL DEFAULT 'media',
    inicio              TIMESTAMPTZ NOT NULL,
    fin                 TIMESTAMPTZ NOT NULL,
    todo_el_dia         BOOLEAN NOT NULL DEFAULT FALSE,
    es_flexible         BOOLEAN NOT NULL DEFAULT FALSE,  -- el motor CSP puede moverlo
    ventana_desde       TIMESTAMPTZ,                     -- restricción temporal extraída por el LLM
    ventana_hasta       TIMESTAMPTZ,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_evento_rango   CHECK (fin > inicio),
    CONSTRAINT ck_evento_ventana CHECK (ventana_hasta IS NULL OR ventana_desde IS NULL OR ventana_hasta > ventana_desde),
    CONSTRAINT ck_traslado_padre CHECK (tipo NOT IN ('traslado','buffer') OR evento_padre_id IS NOT NULL),
    UNIQUE (calendario_id, id_externo)
);
CREATE INDEX idx_eventos_usuario_rango ON eventos(usuario_id, inicio, fin);
CREATE INDEX idx_eventos_padre        ON eventos(evento_padre_id);

-- Detalle de cálculo de un bloque de traslado (RF04, Distance Matrix)
CREATE TABLE traslados (
    evento_id           UUID PRIMARY KEY REFERENCES eventos(id) ON DELETE CASCADE,  -- 1:1 con evento tipo 'traslado'
    origen_id           UUID REFERENCES ubicaciones(id) ON DELETE SET NULL,
    destino_id          UUID REFERENCES ubicaciones(id) ON DELETE SET NULL,
    modo                modo_transporte_t NOT NULL DEFAULT 'auto',
    duracion_seg        INTEGER NOT NULL CHECK (duracion_seg >= 0),
    distancia_m         INTEGER CHECK (distancia_m >= 0),
    proveedor_rutas     VARCHAR(30) NOT NULL,       -- 'google_distance_matrix', 'mapbox', 'mapkit'
    calculado_en        TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =====================================================================
-- 6. REGLAS DE AGENDA (restricciones del motor CSP)
-- =====================================================================
CREATE TABLE reglas_agenda (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id      UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    tipo            tipo_regla_t NOT NULL,
    nombre          VARCHAR(100),
    dias_semana     SMALLINT[] NOT NULL DEFAULT '{1,2,3,4,5}',   -- 1=lunes … 7=domingo
    hora_inicio     TIME,
    hora_fin        TIME,
    minutos         INTEGER,                        -- p.ej. duración de buffer por defecto
    es_estricta     BOOLEAN NOT NULL DEFAULT TRUE,  -- restricción dura vs. preferencia blanda
    peso            SMALLINT NOT NULL DEFAULT 1,    -- penalización si es blanda
    activa          BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT ck_regla_horas CHECK (hora_inicio IS NULL OR hora_fin IS NULL OR hora_fin > hora_inicio)
);
CREATE INDEX idx_reglas_usuario ON reglas_agenda(usuario_id) WHERE activa;


-- =====================================================================
-- 7. CONTACTOS Y CANALES (RF05)
-- =====================================================================
CREATE TABLE contactos (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id         UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    id_libreta_local   VARCHAR(255),                -- CNContact.identifier / Android contact id
    nombre             VARCHAR(150) NOT NULL,
    es_frecuente       BOOLEAN NOT NULL DEFAULT FALSE,
    zona_horaria       VARCHAR(64),
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (usuario_id, id_libreta_local)
);
CREATE INDEX idx_contactos_nombre ON contactos(usuario_id, lower(nombre));

CREATE TABLE contacto_canales (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contacto_id   UUID NOT NULL REFERENCES contactos(id) ON DELETE CASCADE,
    tipo          canal_mensaje_t NOT NULL,
    valor         VARCHAR(255) NOT NULL,            -- teléfono E.164 o email
    es_preferido  BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (contacto_id, tipo, valor)
);
-- Un solo canal preferido por contacto
CREATE UNIQUE INDEX uq_canal_preferido ON contacto_canales(contacto_id) WHERE es_preferido;


-- =====================================================================
-- 8. NEGOCIACIÓN DE REUNIONES (RF06, RF07)
-- =====================================================================
CREATE TABLE negociaciones (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id          UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    contacto_id         UUID NOT NULL REFERENCES contactos(id) ON DELETE RESTRICT,
    canal_id            UUID REFERENCES contacto_canales(id) ON DELETE SET NULL,
    captura_id          UUID REFERENCES capturas(id) ON DELETE SET NULL,
    evento_final_id     UUID REFERENCES eventos(id) ON DELETE SET NULL,   -- se llena al confirmar
    titulo              VARCHAR(255) NOT NULL,
    duracion_min        INTEGER NOT NULL CHECK (duracion_min > 0),
    estado              estado_negoc_t NOT NULL DEFAULT 'borrador',
    token_hash          CHAR(64) NOT NULL UNIQUE,    -- SHA-256 del token del enlace firmado; nunca el token en claro
    expira_en           TIMESTAMPTZ NOT NULL,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    resuelta_en         TIMESTAMPTZ
);
CREATE INDEX idx_negociaciones_abiertas ON negociaciones(usuario_id, estado) WHERE estado = 'enviada';

CREATE TABLE propuestas_horario (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    negociacion_id        UUID NOT NULL REFERENCES negociaciones(id) ON DELETE CASCADE,
    numero_opcion         SMALLINT NOT NULL CHECK (numero_opcion BETWEEN 1 AND 5),
    inicio                TIMESTAMPTZ NOT NULL,
    fin                   TIMESTAMPTZ NOT NULL,
    evento_tentativo_id   UUID REFERENCES eventos(id) ON DELETE SET NULL,  -- bloqueo tentativo en la agenda
    estado                estado_propuesta_t NOT NULL DEFAULT 'ofrecida',
    CONSTRAINT ck_propuesta_rango CHECK (fin > inicio),
    UNIQUE (negociacion_id, numero_opcion)
);
-- Solo una propuesta aceptada por negociación
CREATE UNIQUE INDEX uq_propuesta_aceptada ON propuestas_horario(negociacion_id) WHERE estado = 'aceptada';

CREATE TABLE mensajes (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    negociacion_id     UUID NOT NULL REFERENCES negociaciones(id) ON DELETE CASCADE,
    direccion          direccion_msg_t NOT NULL,
    canal              canal_mensaje_t NOT NULL,
    proveedor          VARCHAR(30) NOT NULL,         -- 'meta_cloud', 'twilio', 'resend'
    id_proveedor       VARCHAR(255),                 -- wamid / SID / id de Resend
    plantilla          VARCHAR(100),                 -- nombre de plantilla de WhatsApp
    contenido          TEXT,
    estado             estado_msg_t NOT NULL,
    enviado_en         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (proveedor, id_proveedor)                 -- idempotencia de webhooks
);
CREATE INDEX idx_mensajes_negociacion ON mensajes(negociacion_id);


-- =====================================================================
-- 9. REPROGRAMACIÓN ADAPTATIVA (RF08)
-- =====================================================================
CREATE TABLE reprogramaciones (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id        UUID NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    evento_id         UUID NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,   -- evento afectado
    motivo            motivo_reprog_t NOT NULL,
    minutos_desvio    INTEGER,
    cambios_propuestos JSONB NOT NULL,              -- [{evento_id, inicio_nuevo, fin_nuevo}, ...] ajuste en cascada
    estado            estado_reprog_t NOT NULL DEFAULT 'pendiente',
    detectada_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    notificada_en     TIMESTAMPTZ,
    resuelta_en       TIMESTAMPTZ
);
CREATE INDEX idx_reprog_pendientes ON reprogramaciones(usuario_id) WHERE estado = 'pendiente';
