import Foundation
import Testing
@testable import SmartSchedulerKit

@Suite struct BusyIntervalTests {
    @Test func mergesOverlappingAndTouchingIntervals() {
        let merged = BusyInterval.merged([busy(5, 6), busy(1, 2), busy(1.5, 3), busy(3, 4), busy(7, 7)])

        #expect(merged == [busy(1, 4), busy(5, 6)])
    }

    @Test func keepsContainedIntervalsInsideTheLongerOne() {
        #expect(BusyInterval.merged([busy(1, 5), busy(2, 3)]) == [busy(1, 5)])
    }

    @Test func captureSendsBusyIntervalsReadAtSendTime() async throws {
        let transport = FakeTransport { _ in throw URLError(.notConnectedToInternet) }
        let busyTimes = FakeBusyTimes([busy(2, 3), busy(1, 2)])
        let store = InMemoryPendingCaptureStore()
        let now = Date(timeIntervalSince1970: 1_793_621_700)
        let coordinator = CaptureCoordinator(
            api: SchedulerAPI(baseURL: baseURL, transport: transport),
            account: FixedAccount(id: userID),
            store: store,
            busyTimes: busyTimes,
            now: { now }
        )

        #expect(try await coordinator.submit(text: "dentista", channel: .voice) == .queued)

        busyTimes.set([busy(4, 5)])
        transport.respond { _ in (201, captureJSON(event: eventJSON())) }
        _ = try await coordinator.flushPending()

        let outcomes = transport.requests.map(jsonBody)
        let sent = outcomes.map { ($0["busy_intervals"] as? [[String: String]]) ?? [] }
        #expect(sent[0] == [["start": "2026-11-02T13:15:00.000Z", "end": "2026-11-02T15:15:00.000Z"]])
        #expect(sent[1] == [["start": "2026-11-02T16:15:00.000Z", "end": "2026-11-02T17:15:00.000Z"]])
        #expect(outcomes[1]["text"] as? String == "dentista")
        #expect(outcomes[1]["local_id"] != nil)
        #expect(busyTimes.queries.first.map { $0.1.timeIntervalSince($0.0) } == CaptureCoordinator.busyHorizon)
    }

    @Test func trimsToTheBackendLimitKeepingTheNearestTimes() async throws {
        let transport = FakeTransport { _ in (201, captureJSON(event: eventJSON())) }
        let many = (0..<(BusyInterval.maxPerCapture + 20)).map { busy(Double($0), Double($0) + 0.5) }
        let coordinator = CaptureCoordinator(
            api: SchedulerAPI(baseURL: baseURL, transport: transport),
            account: FixedAccount(id: userID),
            store: InMemoryPendingCaptureStore(),
            busyTimes: FakeBusyTimes(many.reversed())
        )

        _ = try await coordinator.submit(text: "dentista", channel: .voice)

        let sent = try #require(jsonBody(transport.requests[0])["busy_intervals"] as? [[String: String]])
        #expect(sent.count == BusyInterval.maxPerCapture)
        #expect(sent.first?["start"] == "2026-11-02T12:15:00.000Z")
    }

    @Test func withoutProviderSendsAnEmptyList() async throws {
        let transport = FakeTransport { _ in (201, captureJSON(event: eventJSON())) }
        let coordinator = CaptureCoordinator(
            api: SchedulerAPI(baseURL: baseURL, transport: transport),
            account: FixedAccount(id: userID),
            store: InMemoryPendingCaptureStore()
        )

        _ = try await coordinator.submit(text: "dentista", channel: .voice)

        #expect((jsonBody(transport.requests[0])["busy_intervals"] as? [Any])?.isEmpty == true)
    }
}
