import Foundation

/// Copies events the backend scheduled into a calendar on the device (EventKit).
public protocol CalendarMirror: Sendable {
    /// Must be idempotent: the same event can arrive again when a queued
    /// capture is resent.
    func mirror(_ event: ScheduledEvent) async
}

/// Busy times from calendars on the device, so the backend does not place a
/// capture on top of them.
public protocol BusyTimeProvider: Sendable {
    func busyIntervals(from start: Date, to end: Date) async -> [BusyInterval]
}

public enum CaptureOutcome: Sendable, Equatable {
    /// The backend placed the note in the agenda.
    case scheduled(ScheduledEvent)
    /// The backend or the network is unavailable; the note is queued and sent later.
    case queued
    /// The backend refused the note (time taken, nothing to schedule). Resending will not help.
    case rejected(String)
}

public struct FlushedCapture: Sendable, Equatable {
    public let capture: CaptureRequest
    public let outcome: CaptureOutcome
}

/// Sends captures to the backend and keeps the ones that cannot be sent yet.
///
/// Queued captures keep their `localId`, so resending one after a lost
/// response returns the event created the first time instead of a duplicate.
public actor CaptureCoordinator {
    /// How far ahead device busy times are sent; covers windows like "la próxima semana".
    public static let busyHorizon: TimeInterval = 14 * 24 * 60 * 60

    private let api: SchedulerAPI
    private let account: any AccountProviding
    private let store: any PendingCaptureStore
    private let mirror: (any CalendarMirror)?
    private let busyTimes: (any BusyTimeProvider)?
    private let now: @Sendable () -> Date
    private var isFlushing = false

    public init(
        api: SchedulerAPI,
        account: any AccountProviding,
        store: any PendingCaptureStore,
        mirror: (any CalendarMirror)? = nil,
        busyTimes: (any BusyTimeProvider)? = nil,
        now: @escaping @Sendable () -> Date = Date.init
    ) {
        self.api = api
        self.account = account
        self.store = store
        self.mirror = mirror
        self.busyTimes = busyTimes
        self.now = now
    }

    public func submit(
        text: String,
        channel: CaptureChannel,
        sttEngine: String? = nil
    ) async throws -> CaptureOutcome {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return .rejected("La nota está vacía.")
        }
        let capture = CaptureRequest(
            text: trimmed,
            channel: channel,
            capturedAt: now(),
            sttEngine: sttEngine
        )

        do {
            return try await send(capture)
        } catch let error as SchedulerAPIError where error.isRetryable {
            var queued = capture
            queued.createdOffline = error == .unreachable
            try enqueue(queued)
            return .queued
        }
    }

    /// Sends queued captures in the order they were taken. Stops at the first
    /// one that still cannot be delivered and keeps it and the rest queued.
    public func flushPending() async throws -> [FlushedCapture] {
        guard !isFlushing else { return [] }
        isFlushing = true
        defer { isFlushing = false }

        var results: [FlushedCapture] = []
        while let capture = try store.load().first {
            let outcome: CaptureOutcome
            do {
                outcome = try await send(capture)
            } catch let error as SchedulerAPIError where error.isRetryable {
                break
            } catch let error as SchedulerAPIError {
                // A permanent error would block the queue forever; report and drop it.
                outcome = .rejected(error.localizedDescription)
            }
            try remove(capture)
            results.append(FlushedCapture(capture: capture, outcome: outcome))
        }
        return results
    }

    public func pendingCaptures() throws -> [CaptureRequest] {
        try store.load()
    }

    private func send(_ capture: CaptureRequest) async throws -> CaptureOutcome {
        let userID = try await account.userID()
        let busy = await deviceBusyIntervals()
        let submission: CaptureSubmission
        do {
            submission = try await api.submitCapture(userID: userID, capture, busyIntervals: busy)
        } catch SchedulerAPIError.conflict(let detail) {
            return .rejected(detail)
        } catch SchedulerAPIError.notUnderstood(let detail) {
            return .rejected(detail)
        }

        guard let event = submission.result.event else {
            return .rejected("El servidor no devolvió ningún evento.")
        }
        await mirror?.mirror(event)
        return .scheduled(event)
    }

    private func deviceBusyIntervals() async -> [BusyInterval] {
        guard let busyTimes else { return [] }
        let start = now()
        let intervals = await busyTimes.busyIntervals(from: start, to: start.addingTimeInterval(Self.busyHorizon))
        // Merged and sorted, so trimming to the backend limit drops only the far future.
        return Array(BusyInterval.merged(intervals).prefix(BusyInterval.maxPerCapture))
    }

    private func enqueue(_ capture: CaptureRequest) throws {
        var pending = try store.load()
        pending.append(capture)
        try store.save(pending)
    }

    private func remove(_ capture: CaptureRequest) throws {
        try store.save(try store.load().filter { $0.localId != capture.localId })
    }
}
