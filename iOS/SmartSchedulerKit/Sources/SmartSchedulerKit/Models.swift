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
    /// Set on travel blocks: the event the trip leads to.
    public let parentId: UUID?

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
        flexible: Bool = false,
        parentId: UUID? = nil
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
        self.parentId = parentId
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
    /// Place named in the note ("dentista en Providencia"), for the app to
    /// resolve with MapKit. Nil when the note names no place.
    public let locationQuery: String?
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

public struct Coordinate: Codable, Sendable, Equatable {
    public let latitude: Double
    public let longitude: Double

    public init(latitude: Double, longitude: Double) {
        self.latitude = latitude
        self.longitude = longitude
    }

    /// Great-circle distance in meters.
    public func distance(to other: Coordinate) -> Double {
        let earthRadius = 6_371_000.0
        let lat1 = latitude * .pi / 180
        let lat2 = other.latitude * .pi / 180
        let deltaLat = (other.latitude - latitude) * .pi / 180
        let deltaLon = (other.longitude - longitude) * .pi / 180
        let a = sin(deltaLat / 2) * sin(deltaLat / 2)
            + cos(lat1) * cos(lat2) * sin(deltaLon / 2) * sin(deltaLon / 2)
        return 2 * earthRadius * atan2(sqrt(a), sqrt(1 - a))
    }
}

/// A place stored in the backend (`ubicaciones`): a saved one like "Casa", or
/// one resolved for an event.
public struct SavedLocation: Codable, Sendable, Equatable, Identifiable {
    public let id: UUID
    public let alias: String?
    public let address: String?
    public let latitude: Double
    public let longitude: Double
    public let placeId: String?
    public let isFrequent: Bool

    public init(
        id: UUID,
        alias: String?,
        address: String? = nil,
        latitude: Double,
        longitude: Double,
        placeId: String? = nil,
        isFrequent: Bool = false
    ) {
        self.id = id
        self.alias = alias
        self.address = address
        self.latitude = latitude
        self.longitude = longitude
        self.placeId = placeId
        self.isFrequent = isFrequent
    }

    public var coordinate: Coordinate {
        Coordinate(latitude: latitude, longitude: longitude)
    }

    public var displayName: String {
        alias ?? address ?? "Ubicación"
    }
}

public struct LocationInput: Codable, Sendable, Equatable {
    public var alias: String?
    public var address: String?
    public var latitude: Double
    public var longitude: Double
    public var placeId: String?
    public var isFrequent: Bool

    public init(
        alias: String?,
        address: String? = nil,
        coordinate: Coordinate,
        placeId: String? = nil,
        isFrequent: Bool = false
    ) {
        self.alias = alias
        self.address = address
        self.latitude = coordinate.latitude
        self.longitude = coordinate.longitude
        self.placeId = placeId
        self.isFrequent = isFrequent
    }
}

public struct TravelInput: Codable, Sendable, Equatable {
    /// Nil when the trip starts at the user's current position.
    public var originLocationId: UUID?
    public var durationSeconds: Int
    public var distanceMeters: Int?
    /// `modo_transporte_t`: "auto", "transporte_publico", "caminando", "bicicleta".
    public var mode: String
    public var provider: String

    public init(
        originLocationId: UUID?,
        durationSeconds: Int,
        distanceMeters: Int?,
        mode: String = "auto",
        provider: String = "mapkit"
    ) {
        self.originLocationId = originLocationId
        self.durationSeconds = durationSeconds
        self.distanceMeters = distanceMeters
        self.mode = mode
        self.provider = provider
    }
}

/// Body of `PUT /users/{id}/events/{id}/location`. Give `locationId` or `location`.
public struct EventLocationUpdate: Codable, Sendable, Equatable {
    public var locationId: UUID?
    public var location: LocationInput?
    public var travel: TravelInput?
    public var busyIntervals: [BusyInterval]

    public init(
        locationId: UUID? = nil,
        location: LocationInput? = nil,
        travel: TravelInput? = nil,
        busyIntervals: [BusyInterval] = []
    ) {
        self.locationId = locationId
        self.location = location
        self.travel = travel
        self.busyIntervals = busyIntervals
    }
}

public struct EventLocationResult: Codable, Sendable, Equatable {
    public let event: ScheduledEvent
    public let location: SavedLocation
    public let travel: ScheduledEvent?
    /// A flexible event was moved so the trip fits.
    public let moved: Bool
    /// The trip overlaps another commitment; the user may arrive late.
    public let travelOverlaps: Bool
}
