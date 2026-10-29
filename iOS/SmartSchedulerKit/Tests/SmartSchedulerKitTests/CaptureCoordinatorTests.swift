import Foundation
import Testing
@testable import SmartSchedulerKit

@Suite struct CaptureCoordinatorTests {
    private let capturedAt = Date(timeIntervalSince1970: 1_793_621_700)

    private func coordinator(
        _ transport: FakeTransport,
        store: InMemoryPendingCaptureStore = InMemoryPendingCaptureStore(),
        mirror: RecordingMirror? = nil
    ) -> CaptureCoordinator {
        let capturedAt = capturedAt
        return CaptureCoordinator(
            api: SchedulerAPI(baseURL: baseURL, transport: transport),
            account: FixedAccount(id: userID),
            store: store,
            mirror: mirror,
            now: { capturedAt }
        )
    }

    @Test func scheduledCaptureIsMirroredToTheDeviceCalendar() async throws {
        let eventID = UUID()
        let transport = FakeTransport { _ in (201, captureJSON(event: eventJSON(id: eventID))) }
        let mirror = RecordingMirror()

        let outcome = try await coordinator(transport, mirror: mirror)
            .submit(text: "  mañana a las tres dentista ", channel: .voice, sttEngine: "apple_speech")

        guard case .scheduled(let scheduled) = outcome else {
            Issue.record("expected a scheduled event, got \(outcome)")
            return
        }
        #expect(scheduled.event.id == eventID)
        #expect(scheduled.travel == nil)
        #expect(mirror.mirrored.map(\.id) == [eventID])
        #expect(jsonBody(transport.requests[0])["text"] as? String == "mañana a las tres dentista")
    }

    @Test func emptyNoteIsRejectedWithoutARequest() async throws {
        let transport = FakeTransport { _ in (201, captureJSON(event: eventJSON())) }

        let outcome = try await coordinator(transport).submit(text: "   ", channel: .voice)

        #expect(outcome == .rejected("La nota está vacía."))
        #expect(transport.requests.isEmpty)
    }

    @Test func unreachableServerQueuesCaptureAsOffline() async throws {
        let transport = FakeTransport { _ in throw URLError(.notConnectedToInternet) }
        let store = InMemoryPendingCaptureStore()

        let outcome = try await coordinator(transport, store: store).submit(text: "comprar pan", channel: .voice)

        #expect(outcome == .queued)
        let queued = try #require(store.load().first)
        #expect(queued.text == "comprar pan")
        #expect(queued.createdOffline)
        #expect(queued.capturedAt == capturedAt)
    }

    @Test func unavailableModelQueuesCaptureAsOnline() async throws {
        let transport = FakeTransport { _ in (503, #"{"detail": "The language model is unavailable"}"#) }
        let store = InMemoryPendingCaptureStore()

        let outcome = try await coordinator(transport, store: store).submit(text: "comprar pan", channel: .text)

        #expect(outcome == .queued)
        #expect(store.load().first?.createdOffline == false)
    }

    @Test(arguments: [409, 422])
    func refusedCaptureIsNotQueued(status: Int) async throws {
        let transport = FakeTransport { _ in (status, #"{"detail": "No free slot"}"#) }
        let store = InMemoryPendingCaptureStore()

        let outcome = try await coordinator(transport, store: store).submit(text: "reunión", channel: .voice)

        #expect(outcome == .rejected("No free slot"))
        #expect(store.load().isEmpty)
    }

    @Test func flushResendsWithTheOriginalLocalIdInOrder() async throws {
        let first = CaptureRequest(text: "uno", channel: .voice, capturedAt: capturedAt, createdOffline: true)
        let second = CaptureRequest(text: "dos", channel: .voice, capturedAt: capturedAt, createdOffline: true)
        let store = InMemoryPendingCaptureStore([first, second])
        let transport = FakeTransport { _ in (201, captureJSON(event: eventJSON())) }

        let results = try await coordinator(transport, store: store).flushPending()

        #expect(results.map(\.capture.localId) == [first.localId, second.localId])
        #expect(transport.requests.map { jsonBody($0)["local_id"] as? String } == [
            first.localId.uuidString, second.localId.uuidString,
        ])
        #expect(store.load().isEmpty)
    }

    @Test func flushStopsAtFirstRetryableFailureAndKeepsTheRest() async throws {
        let first = CaptureRequest(text: "uno", channel: .voice, capturedAt: capturedAt)
        let second = CaptureRequest(text: "dos", channel: .voice, capturedAt: capturedAt)
        let store = InMemoryPendingCaptureStore([first, second])
        let transport = FakeTransport { _ in throw URLError(.timedOut) }

        let results = try await coordinator(transport, store: store).flushPending()

        #expect(results.isEmpty)
        #expect(transport.requests.count == 1)
        #expect(store.load() == [first, second])
    }

    @Test func flushDropsCapturesTheServerRefuses() async throws {
        let refused = CaptureRequest(text: "uno", channel: .voice, capturedAt: capturedAt)
        let accepted = CaptureRequest(text: "dos", channel: .voice, capturedAt: capturedAt)
        let store = InMemoryPendingCaptureStore([refused, accepted])
        let transport = FakeTransport { request in
            jsonBody(request)["text"] as? String == "uno"
                ? (409, #"{"detail": "The requested time overlaps an existing event"}"#)
                : (201, captureJSON(event: eventJSON()))
        }

        let results = try await coordinator(transport, store: store).flushPending()

        #expect(results.map(\.outcome).first == .rejected("The requested time overlaps an existing event"))
        #expect(results.count == 2)
        #expect(store.load().isEmpty)
    }

    @Test func captureQueuedDuringFlushIsKept() async throws {
        let pending = CaptureRequest(text: "uno", channel: .voice, capturedAt: capturedAt)
        let store = InMemoryPendingCaptureStore([pending])
        let transport = FakeTransport { _ in throw URLError(.notConnectedToInternet) }
        let coordinator = coordinator(transport, store: store)

        async let flushed = coordinator.flushPending()
        async let submitted = coordinator.submit(text: "dos", channel: .voice)
        _ = try await (flushed, submitted)

        #expect(Set(store.load().map(\.text)) == ["uno", "dos"])
    }
}
