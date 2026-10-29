import Foundation
import Observation
import OSLog
import SmartSchedulerKit
#if canImport(BackgroundTasks)
import BackgroundTasks
#endif

enum AppTab: Hashable {
    case capture, agenda, settings
}

/// What the user last saw happen to a capture.
enum CaptureBanner: Equatable {
    case scheduled(ScheduledEvent)
    case queued
    case rejected(String)
    case failed(String)
}

@MainActor
@Observable
final class AppModel {
    static let shared = AppModel()
    static let agendaHorizon: TimeInterval = 7 * 24 * 60 * 60

    var selectedTab: AppTab = .capture
    var typedNote = ""
    private(set) var isSubmitting = false
    private(set) var banner: CaptureBanner?
    private(set) var pendingCaptures: [CaptureRequest] = []
    private(set) var upcoming: [ScheduledEvent] = []
    private(set) var agendaError: String?
    private(set) var isLoadingAgenda = false
    /// Set by `DictateCaptureIntent`; consumed once the scene is active.
    private(set) var dictationRequested = false

    let transcriber = SpeechTranscriber()
    @ObservationIgnored private let services = AppServices.shared
    @ObservationIgnored private let logger = Logger(subsystem: "ai.smartscheduler", category: "app")
    @ObservationIgnored private var connectivityTask: Task<Void, Never>?

    private init() {}

    var serverURL: URL { services.serverURL }

    func start() async {
        if EventKitCalendar.access == .notDetermined {
            _ = await services.calendar.requestFullAccess()
        }
        if connectivityTask == nil {
            connectivityTask = Task { [weak self] in
                for await _ in ConnectivityMonitor.connectionRestored() {
                    await self?.flushPending()
                }
            }
        }
        await flushPending()
    }

    // MARK: Capture

    func requestDictation() {
        selectedTab = .capture
        dictationRequested = true
    }

    func consumeDictationRequest() {
        guard dictationRequested else { return }
        dictationRequested = false
        // Unstructured on purpose: the caller's view task is cancelled when the
        // flag above changes, and cancellation would abort the capture request.
        Task { await dictate() }
    }

    func toggleDictation() async {
        if transcriber.isListening {
            transcriber.stop()
        } else {
            await dictate()
        }
    }

    func dictate() async {
        guard !transcriber.isListening else { return }
        do {
            let text = try await transcriber.listen()
            await submit(text, channel: .voice, sttEngine: transcriber.engineName)
        } catch is CancellationError {
            return
        } catch {
            banner = .failed(error.localizedDescription)
        }
    }

    func submitTypedNote() async {
        let text = typedNote
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        await submit(text, channel: .text, sttEngine: nil)
        if case .failed = banner { return }
        typedNote = ""
    }

    @discardableResult
    func submit(_ text: String, channel: CaptureChannel, sttEngine: String?) async -> CaptureBanner {
        isSubmitting = true
        defer { isSubmitting = false }

        let result: CaptureBanner
        do {
            switch try await services.coordinator.submit(text: text, channel: channel, sttEngine: sttEngine) {
            case .scheduled(let event):
                result = .scheduled(event)
                insertUpcoming(event)
            case .queued:
                result = .queued
                scheduleBackgroundFlush()
            case .rejected(let reason):
                result = .rejected(reason)
            }
        } catch {
            logger.error("Capture failed: \(error.localizedDescription)")
            result = .failed(error.localizedDescription)
        }
        banner = result
        await reloadPending()
        return result
    }

    func dismissBanner() {
        banner = nil
    }

    // MARK: Offline queue

    func flushPending() async {
        do {
            let flushed = try await services.coordinator.flushPending()
            for case .scheduled(let event) in flushed.map(\.outcome) {
                insertUpcoming(event)
            }
        } catch {
            logger.error("Flushing queued captures failed: \(error.localizedDescription)")
        }
        await reloadPending()
        if !pendingCaptures.isEmpty {
            scheduleBackgroundFlush()
        }
    }

    private func reloadPending() async {
        pendingCaptures = (try? await services.coordinator.pendingCaptures()) ?? []
    }

    /// Asks iOS to wake the app later to send queued captures (RNF03).
    private func scheduleBackgroundFlush() {
        #if os(iOS)
        let request = BGAppRefreshTaskRequest(identifier: AppServices.backgroundFlushTaskID)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            logger.debug("Background flush not scheduled: \(error.localizedDescription)")
        }
        #endif
    }

    // MARK: Agenda

    func refreshAgenda() async {
        isLoadingAgenda = true
        defer { isLoadingAgenda = false }
        do {
            let userID = try await services.account.userID()
            let now = Date.now
            upcoming = try await services.api
                .events(userID: userID, from: now, to: now.addingTimeInterval(Self.agendaHorizon))
                .filter { $0.status != .cancelled }
            agendaError = nil
        } catch {
            agendaError = error.localizedDescription
        }
    }

    private func insertUpcoming(_ event: ScheduledEvent) {
        upcoming.removeAll { $0.id == event.id }
        upcoming.append(event)
        upcoming.sort { $0.start < $1.start }
    }

    // MARK: Settings

    func setServerURL(_ url: URL) async {
        await services.setServerURL(url)
        upcoming = []
        await flushPending()
        await refreshAgenda()
    }
}
