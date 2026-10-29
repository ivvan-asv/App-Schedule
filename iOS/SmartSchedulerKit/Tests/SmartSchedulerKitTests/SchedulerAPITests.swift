import Foundation
import Testing
@testable import SmartSchedulerKit

@Suite struct SchedulerJSONTests {
    @Test(arguments: [
        ("2026-11-02T12:15:00Z", 0.0),
        ("2026-11-02T09:15:00-03:00", 0.0),
        ("2026-11-02T12:15:00.5Z", 0.5),
        ("2026-11-02T12:15:00.123456Z", 0.123),
        ("2026-11-02T09:15:00.123456-03:00", 0.123),
    ])
    func parsesBackendDatetimes(value: String, fraction: Double) throws {
        let date = try #require(SchedulerJSON.date(from: value))
        let expected = Date(timeIntervalSince1970: 1_793_621_700 + fraction)
        #expect(abs(date.timeIntervalSince(expected)) < 0.001)
    }

    @Test func rejectsDatetimesWithoutOffset() {
        #expect(SchedulerJSON.date(from: "2026-11-02T12:15:00") == nil)
    }

    @Test func encodesDatesWithOffset() {
        let value = SchedulerJSON.string(from: Date(timeIntervalSince1970: 1_793_621_700))
        #expect(value == "2026-11-02T12:15:00.000Z")
    }
}

@Suite struct SchedulerAPITests {
    @Test func submitsCaptureWithBackendFieldNames() async throws {
        let transport = FakeTransport { _ in (201, captureJSON(event: eventJSON())) }
        let api = SchedulerAPI(baseURL: baseURL, transport: transport)
        let capture = CaptureRequest(
            text: "mañana a las tres dentista",
            channel: .voice,
            capturedAt: Date(timeIntervalSince1970: 1_793_621_700),
            createdOffline: true,
            sttEngine: "apple_speech"
        )

        let submission = try await api.submitCapture(userID: userID, capture)

        let request = try #require(transport.requests.first)
        #expect(request.httpMethod == "POST")
        #expect(request.url?.path == "/api/v1/users/\(userID.uuidString)/captures")
        let body = jsonBody(request)
        #expect(body["text"] as? String == "mañana a las tres dentista")
        #expect(body["channel"] as? String == "voz")
        #expect(body["local_id"] as? String == capture.localId.uuidString)
        #expect(body["captured_at"] as? String == "2026-11-02T12:15:00.000Z")
        #expect(body["created_offline"] as? Bool == true)
        #expect(body["stt_engine"] as? String == "apple_speech")

        #expect(!submission.alreadyProcessed)
        #expect(submission.result.latencyMs == 1204)
        #expect(submission.result.event?.title == "Dentista")
    }

    @Test func reportsAlreadyProcessedCaptures() async throws {
        let transport = FakeTransport { _ in (200, captureJSON(event: eventJSON())) }
        let api = SchedulerAPI(baseURL: baseURL, transport: transport)

        let submission = try await api.submitCapture(
            userID: userID,
            CaptureRequest(text: "x", channel: .text, capturedAt: .now)
        )

        #expect(submission.alreadyProcessed)
    }

    @Test(arguments: [
        (409, #"{"detail": "No free slot"}"#, SchedulerAPIError.conflict("No free slot")),
        (422, #"{"detail": [{"msg": "a"}, {"msg": "b"}]}"#, .notUnderstood("a; b")),
        (503, #"{"detail": "LLM down"}"#, .serviceUnavailable("LLM down")),
        (404, #"{"detail": "User not found"}"#, .notFound("User not found")),
        (500, "Internal Server Error", .server(status: 500, detail: "internal server error")),
    ])
    func mapsErrorResponses(status: Int, body: String, expected: SchedulerAPIError) async {
        let transport = FakeTransport { _ in (status, body) }
        let api = SchedulerAPI(baseURL: baseURL, transport: transport)

        await #expect(throws: expected) {
            _ = try await api.createDemoUser()
        }
    }

    @Test func mapsNetworkFailuresToUnreachable() async {
        let transport = FakeTransport { _ in throw URLError(.notConnectedToInternet) }
        let api = SchedulerAPI(baseURL: baseURL, transport: transport)

        await #expect(throws: SchedulerAPIError.unreachable) {
            _ = try await api.createDemoUser()
        }
    }

    @Test func sendsEventRangeAsQuery() async throws {
        let transport = FakeTransport { _ in (200, "[\(eventJSON())]") }
        let api = SchedulerAPI(baseURL: baseURL, transport: transport)

        let events = try await api.events(
            userID: userID,
            from: Date(timeIntervalSince1970: 1_793_621_700),
            to: Date(timeIntervalSince1970: 1_793_621_700 + 86_400)
        )

        #expect(events.count == 1)
        let components = try #require(
            transport.requests.first?.url.flatMap { URLComponents(url: $0, resolvingAgainstBaseURL: false) }
        )
        #expect(components.queryItems?.first { $0.name == "from" }?.value == "2026-11-02T12:15:00.000Z")
        #expect(components.queryItems?.first { $0.name == "to" }?.value == "2026-11-03T12:15:00.000Z")
    }

    @Test func updatesUserWithPatch() async throws {
        let transport = FakeTransport { _ in (200, userJSON(timezone: "Europe/Madrid")) }
        let api = SchedulerAPI(baseURL: baseURL, transport: transport)

        let user = try await api.updateUser(userID, UserUpdate(timezone: "Europe/Madrid"))

        let request = try #require(transport.requests.first)
        #expect(request.httpMethod == "PATCH")
        #expect(jsonBody(request) as NSDictionary == ["timezone": "Europe/Madrid"])
        #expect(user.timezone == "Europe/Madrid")
    }
}
