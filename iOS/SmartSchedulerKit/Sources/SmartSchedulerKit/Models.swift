import Foundation

// Wire models for the FastAPI backend (Backend/app/schemas). Enum raw values
// keep the Spanish names stored in the database.

public enum CaptureChannel: String, Codable, Sendable {
    case voice = "voz"
    case text = "texto"
}

public enum CaptureStatus: String, Codable, Sendable {
    case queued = "encolada"
    case processing = "procesando"
    case processed = "procesada"
    case error = "error"
}

public enum EventType: String, Codable, Sendable {
    case task = "tarea"
    case meeting = "reunion"
    case travel = "traslado"
    case buffer = "buffer"
}

public enum EventStatus: String, Codable, Sendable {
    case tentative = "tentativo"
    case confirmed = "confirmado"
    case cancelled = "cancelado"
}

public enum EventPriority: String, Codable, Sendable {
    case low = "baja"
    case medium = "media"
    case high = "alta"
    case urgent = "urgente"
}

public struct SchedulerUser: Codable, Sendable, Equatable {
    public let id: UUID
    public let email: String
    public let displayName: String
    public let timezone: String
    public let createdAt: Date
}

public struct UserUpdate: Encodable, Sendable, Equatable {
    public var displayName: String?
    public var timezone: String?

    public init(displayName: String? = nil, timezone: String? = nil) {
        self.displayName = displayName
        self.timezone = timezone
    }
}

public struct ScheduledEvent: Codable, Sendable, Equatable, Identifiable {
    public let id: UUID
    public let title: String
    public let description: String?
    public let type: EventType
    public let status: EventStatus
    public let priority: EventPriority
    public let start: Date
    public let end: Date
    public let locationId: UUID?
    /// True when the backend chose the time; the optimizer may move it later.
    public let flexible: Bool

    public init(
        id: UUID,
        title: String,
        description: String? = nil,
        type: EventType = .task,
        status: EventStatus = .confirmed,
        priority: EventPriority = .medium,
        start: Date,
        end: Date,
        locationId: UUID? = nil,
        flexible: Bool = false
    ) {
        self.id = id
        self.title = title
        self.description = description
        self.type = type
        self.status = status
        self.priority = priority
        self.start = start
        self.end = end
        self.locationId = locationId
        self.flexible = flexible
    }
}

/// A dictated or typed note sent to `POST /users/{id}/captures`.
///
/// `localId` is generated on the device so that resending a capture from the
/// offline queue returns the original result instead of a duplicate event.
public struct CaptureRequest: Codable, Sendable, Equatable, Identifiable {
    public var text: String
    public var channel: CaptureChannel
    public var localId: UUID
    public var capturedAt: Date
    public var createdOffline: Bool
    public var sttEngine: String?

    public var id: UUID { localId }

    public init(
        text: String,
        channel: CaptureChannel,
        localId: UUID = UUID(),
        capturedAt: Date,
        createdOffline: Bool = false,
        sttEngine: String? = nil
    ) {
        self.text = text
        self.channel = channel
        self.localId = localId
        self.capturedAt = capturedAt
        self.createdOffline = createdOffline
        self.sttEngine = sttEngine
    }
}

public struct CaptureResult: Codable, Sendable, Equatable {
    public let id: UUID
    public let status: CaptureStatus
    public let channel: CaptureChannel
    public let transcription: String?
    public let capturedAt: Date
    public let processedAt: Date?
    /// Server-side processing time, tracked against the 3 s budget (RNF01).
    public let latencyMs: Int?
    public let event: ScheduledEvent?
}

public struct WorkingHoursRule: Codable, Sendable, Equatable, Identifiable {
    public let id: UUID
    public let name: String?
    /// ISO weekdays: 1 = Monday … 7 = Sunday.
    public let weekdays: [Int]
    /// Local wall-clock times as sent by the backend, e.g. "09:00:00".
    public let startTime: String?
    public let endTime: String?
    public let active: Bool
}

public struct WorkingHoursRuleRequest: Encodable, Sendable, Equatable {
    public var name: String?
    public var weekdays: [Int]
    public var startTime: String
    public var endTime: String

    public init(name: String?, weekdays: [Int], startTime: String, endTime: String) {
        self.name = name
        self.weekdays = weekdays
        self.startTime = startTime
        self.endTime = endTime
    }

    public static let defaultWorkweek = WorkingHoursRuleRequest(
        name: "Horario laboral",
        weekdays: [1, 2, 3, 4, 5],
        startTime: "09:00",
        endTime: "18:00"
    )
}

/// A busy time from a calendar the backend does not see (the device calendar).
/// Only times are sent, never titles or attendees.
public struct BusyInterval: Codable, Sendable, Equatable {
    public let start: Date
    public let end: Date

    public init(start: Date, end: Date) {
        self.start = start
        self.end = end
    }

    /// The backend accepts at most this many intervals per capture.
    public static let maxPerCapture = 500

    /// Sorted, with overlapping or touching intervals joined, so busy days fit
    /// in fewer intervals. Empty or inverted intervals are dropped.
    public static func merged(_ intervals: [BusyInterval]) -> [BusyInterval] {
        var merged: [BusyInterval] = []
        for interval in intervals.filter({ $0.end > $0.start }).sorted(by: { $0.start < $1.start }) {
            if let last = merged.last, interval.start <= last.end {
                merged[merged.count - 1] = BusyInterval(start: last.start, end: max(last.end, interval.end))
            } else {
                merged.append(interval)
            }
        }
        return merged
    }
}
