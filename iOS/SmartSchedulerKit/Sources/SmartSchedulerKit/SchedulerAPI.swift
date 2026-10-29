import Foundation

public protocol HTTPTransport: Sendable {
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse)
}

public struct URLSessionTransport: HTTPTransport {
    private let session: URLSession

    public init(session: URLSession = .shared) {
        self.session = session
    }

    public func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw SchedulerAPIError.invalidResponse
        }
        return (data, httpResponse)
    }
}

public enum SchedulerAPIError: Error, Equatable, Sendable, LocalizedError {
    /// The server could not be reached (no network, host down, timeout).
    case unreachable
    /// 409: the requested time is taken or no free slot exists.
    case conflict(String)
    /// 422: the note or the request could not be turned into an event.
    case notUnderstood(String)
    /// 503: the language model is unavailable or not configured.
    case serviceUnavailable(String)
    case notFound(String)
    case server(status: Int, detail: String)
    case invalidResponse

    /// Whether sending the same request later may succeed.
    public var isRetryable: Bool {
        switch self {
        case .unreachable, .serviceUnavailable:
            true
        case .server(let status, _):
            status >= 500
        case .conflict, .notUnderstood, .notFound, .invalidResponse:
            false
        }
    }

    public var errorDescription: String? {
        switch self {
        case .unreachable:
            "No se pudo conectar con el servidor."
        case .conflict(let detail), .notUnderstood(let detail),
             .serviceUnavailable(let detail), .notFound(let detail):
            detail
        case .server(let status, let detail):
            "Error del servidor (\(status)): \(detail)"
        case .invalidResponse:
            "Respuesta inválida del servidor."
        }
    }
}

public struct CaptureSubmission: Sendable, Equatable {
    public let result: CaptureResult
    /// True when the server already had this `localId` (HTTP 200 instead of 201).
    public let alreadyProcessed: Bool
}

/// Client for the Smart Scheduler FastAPI backend (`/api/v1`).
public struct SchedulerAPI: Sendable {
    public let baseURL: URL
    private let transport: any HTTPTransport

    public init(baseURL: URL, transport: any HTTPTransport = URLSessionTransport()) {
        self.baseURL = baseURL
        self.transport = transport
    }

    public func createDemoUser() async throws -> SchedulerUser {
        try await send("POST", "users/demo")
    }

    public func updateUser(_ userID: UUID, _ update: UserUpdate) async throws -> SchedulerUser {
        try await send("PATCH", "users/\(userID.uuidString)", body: update)
    }

    public func workingHoursRules(userID: UUID) async throws -> [WorkingHoursRule] {
        try await send("GET", "users/\(userID.uuidString)/availability-rules")
    }

    public func createWorkingHoursRule(
        userID: UUID,
        _ rule: WorkingHoursRuleRequest
    ) async throws -> WorkingHoursRule {
        try await send("POST", "users/\(userID.uuidString)/availability-rules", body: rule)
    }

    public func submitCapture(
        userID: UUID,
        _ capture: CaptureRequest,
        busyIntervals: [BusyInterval] = []
    ) async throws -> CaptureSubmission {
        let (result, status): (CaptureResult, Int) = try await sendReturningStatus(
            "POST",
            "users/\(userID.uuidString)/captures",
            body: CapturePayload(capture: capture, busyIntervals: busyIntervals)
        )
        return CaptureSubmission(result: result, alreadyProcessed: status == 200)
    }

    public func events(userID: UUID, from: Date, to: Date) async throws -> [ScheduledEvent] {
        try await send(
            "GET",
            "users/\(userID.uuidString)/events",
            query: [
                URLQueryItem(name: "from", value: SchedulerJSON.string(from: from)),
                URLQueryItem(name: "to", value: SchedulerJSON.string(from: to)),
            ]
        )
    }

    // MARK: - Request plumbing

    /// The stored capture plus `busy_intervals`, which are read fresh from the
    /// device calendar on every attempt instead of being queued with the note.
    private struct CapturePayload: Encodable {
        let capture: CaptureRequest
        let busyIntervals: [BusyInterval]

        enum CodingKeys: String, CodingKey {
            case busyIntervals
        }

        func encode(to encoder: any Encoder) throws {
            try capture.encode(to: encoder)
            var container = encoder.container(keyedBy: CodingKeys.self)
            try container.encode(busyIntervals, forKey: .busyIntervals)
        }
    }

    private struct EmptyBody: Encodable {}

    private func send<Response: Decodable>(
        _ method: String,
        _ path: String,
        query: [URLQueryItem] = []
    ) async throws -> Response {
        try await sendReturningStatus(method, path, query: query, body: Optional<EmptyBody>.none).0
    }

    private func send<Response: Decodable, Body: Encodable>(
        _ method: String,
        _ path: String,
        body: Body
    ) async throws -> Response {
        try await sendReturningStatus(method, path, body: body).0
    }

    private func sendReturningStatus<Response: Decodable, Body: Encodable>(
        _ method: String,
        _ path: String,
        query: [URLQueryItem] = [],
        body: Body?
    ) async throws -> (Response, Int) {
        var request = URLRequest(url: url(for: path, query: query))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = try SchedulerJSON.encoder().encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }

        let data: Data
        let response: HTTPURLResponse
        do {
            (data, response) = try await transport.send(request)
        } catch is URLError {
            throw SchedulerAPIError.unreachable
        }

        guard (200..<300).contains(response.statusCode) else {
            throw Self.error(status: response.statusCode, data: data)
        }
        do {
            return (try SchedulerJSON.decoder().decode(Response.self, from: data), response.statusCode)
        } catch {
            throw SchedulerAPIError.invalidResponse
        }
    }

    private func url(for path: String, query: [URLQueryItem]) -> URL {
        let url = baseURL.appending(path: "api/v1").appending(path: path)
        guard !query.isEmpty,
              var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        else { return url }
        components.queryItems = query
        // URLComponents leaves "+" unescaped, which servers read as a space.
        components.percentEncodedQuery = components.percentEncodedQuery?
            .replacingOccurrences(of: "+", with: "%2B")
        return components.url ?? url
    }

    static func error(status: Int, data: Data) -> SchedulerAPIError {
        let detail = errorDetail(from: data) ?? HTTPURLResponse.localizedString(forStatusCode: status)
        switch status {
        case 404: return .notFound(detail)
        case 409: return .conflict(detail)
        case 422: return .notUnderstood(detail)
        case 503: return .serviceUnavailable(detail)
        default: return .server(status: status, detail: detail)
        }
    }

    /// Reads FastAPI's `{"detail": "..."}` or validation `{"detail": [{"msg": ...}]}`.
    private static func errorDetail(from data: Data) -> String? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        if let detail = object["detail"] as? String {
            return detail
        }
        if let items = object["detail"] as? [[String: Any]] {
            let messages = items.compactMap { $0["msg"] as? String }
            return messages.isEmpty ? nil : messages.joined(separator: "; ")
        }
        return nil
    }
}

/// JSON conventions shared with the backend: snake_case keys and ISO 8601
/// datetimes that always carry a UTC offset.
public enum SchedulerJSON {
    public static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(string(from: date))
        }
        return encoder
    }

    public static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let value = try container.decode(String.self)
            guard let date = date(from: value) else {
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "Invalid ISO 8601 datetime: \(value)"
                )
            }
            return date
        }
        return decoder
    }

    public static func string(from date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }

    /// Parses datetimes from Pydantic, which may send microseconds
    /// ("2026-11-02T12:15:00.123456Z") that `ISO8601DateFormatter` rejects.
    public static func date(from value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        guard let fractionRange = value.range(of: #"\.\d+"#, options: .regularExpression) else {
            return formatter.date(from: value)
        }

        let digits = value[fractionRange].dropFirst()
        let milliseconds = String(digits.prefix(3)).padding(toLength: 3, withPad: "0", startingAt: 0)
        let trimmed = value.replacingCharacters(in: fractionRange, with: "." + milliseconds)
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: trimmed)
    }
}
