import Foundation
@testable import SmartSchedulerKit

/// Answers requests from a script and records them for assertions.
final class FakeTransport: HTTPTransport, @unchecked Sendable {
    typealias Handler = (URLRequest) throws -> (Int, String)

    private let lock = NSLock()
    private var handler: Handler
    private var recorded: [URLRequest] = []

    init(_ handler: @escaping Handler) {
        self.handler = handler
    }

    var requests: [URLRequest] {
        lock.withLock { recorded }
    }

    func respond(with handler: @escaping Handler) {
        lock.withLock { self.handler = handler }
    }

    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let handler = lock.withLock {
            recorded.append(request)
            return self.handler
        }
        let (status, body) = try handler(request)
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: status,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
        return (Data(body.utf8), response)
    }
}

final class MemoryKeyValueStore: KeyValueStore, @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String: String] = [:]

    func string(forKey key: String) -> String? {
        lock.withLock { values[key] }
    }

    func set(_ value: String?, forKey key: String) {
        lock.withLock { values[key] = value }
    }
}

struct FixedAccount: AccountProviding {
    let id: UUID

    func userID() async throws -> UUID { id }
}

final class RecordingMirror: CalendarMirror, @unchecked Sendable {
    private let lock = NSLock()
    private var events: [ScheduledEvent] = []

    var mirrored: [ScheduledEvent] {
        lock.withLock { events }
    }

    func mirror(_ event: ScheduledEvent) async {
        lock.withLock { events.append(event) }
    }
}

let baseURL = URL(string: "http://localhost:8000")!
let userID = UUID(uuidString: "6F9619FF-8B86-D011-B42D-00C04FC964FF")!

func jsonBody(_ request: URLRequest) -> [String: Any] {
    guard let body = request.httpBody,
          let object = try? JSONSerialization.jsonObject(with: body) as? [String: Any]
    else { return [:] }
    return object
}

func userJSON(timezone: String = "America/Santiago") -> String {
    """
    {"id": "\(userID.uuidString)", "email": "demo@smart-scheduler.local",
     "display_name": "Demo User", "timezone": "\(timezone)",
     "created_at": "2026-10-11T12:00:00.123456Z"}
    """
}

func eventJSON(id: UUID = UUID(), title: String = "Dentista") -> String {
    """
    {"id": "\(id.uuidString)", "title": "\(title)", "description": null,
     "type": "tarea", "status": "confirmado", "priority": "media",
     "start": "2026-11-03T18:00:00Z", "end": "2026-11-03T19:00:00Z",
     "location_id": null, "flexible": false}
    """
}

func captureJSON(event: String?) -> String {
    """
    {"id": "\(UUID().uuidString)", "status": "procesada", "channel": "voz",
     "transcription": "mañana a las tres dentista", "captured_at": "2026-11-02T12:15:00Z",
     "processed_at": "2026-11-02T12:15:01.204Z", "latency_ms": 1204,
     "event": \(event ?? "null")}
    """
}

final class FakeBusyTimes: BusyTimeProvider, @unchecked Sendable {
    private let lock = NSLock()
    private var intervals: [BusyInterval]
    private var queried: [(Date, Date)] = []

    init(_ intervals: [BusyInterval] = []) {
        self.intervals = intervals
    }

    var queries: [(Date, Date)] {
        lock.withLock { queried }
    }

    func set(_ intervals: [BusyInterval]) {
        lock.withLock { self.intervals = intervals }
    }

    func busyIntervals(from start: Date, to end: Date) async -> [BusyInterval] {
        lock.withLock {
            queried.append((start, end))
            return intervals
        }
    }
}

func busy(_ startHour: Double, _ endHour: Double) -> BusyInterval {
    let base = Date(timeIntervalSince1970: 1_793_621_700)
    return BusyInterval(
        start: base.addingTimeInterval(startHour * 3_600),
        end: base.addingTimeInterval(endHour * 3_600)
    )
}
