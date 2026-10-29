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
    case scheduled(ScheduledCapture)
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
    private(set) var workingHours: WeeklySchedule?
    private(set) var workingHoursError: String?
    private(set) var calendarAccounts: [CalendarAccount] = []
    private(set) var calendarProviders: [CalendarProviderStatus] = []
    private(set) var calendarMessage: String?
    private(set) var savedPlaces: [SavedLocation] = []
    private(set) var placesError: String?
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
        DeviceLocation.requestAuthorization()
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
            case .scheduled(let scheduled):
                result = .scheduled(scheduled)
                insertUpcoming(scheduled)
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
            for case .scheduled(let scheduled) in flushed.map(\.outcome) {
                insertUpcoming(scheduled)
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

    private func insertUpcoming(_ scheduled: ScheduledCapture) {
        let events = [scheduled.event] + (scheduled.travel.map { [$0] } ?? [])
        let ids = Set(events.map(\.id))
        // A retried trip replaces the previous travel block of the same event.
        upcoming.removeAll { ids.contains($0.id) || ($0.type == .travel && $0.parentId == scheduled.event.id) }
        upcoming.append(contentsOf: events)
        upcoming.sort { $0.start < $1.start }
    }

    // MARK: Working hours

    func loadWorkingHours() async {
        do {
            let userID = try await services.account.userID()
            workingHours = WeeklySchedule(rules: try await services.api.workingHoursRules(userID: userID))
            workingHoursError = nil
        } catch {
            workingHoursError = error.localizedDescription
        }
    }

    func saveWorkingHours(_ schedule: WeeklySchedule) async -> Bool {
        do {
            let userID = try await services.account.userID()
            let rules = try await services.api.replaceWorkingHours(userID: userID, schedule.rules)
            workingHours = WeeklySchedule(rules: rules)
            workingHoursError = nil
            return true
        } catch {
            workingHoursError = error.localizedDescription
            return false
        }
    }

    // MARK: Connected calendars

    func loadCalendars() async {
        do {
            let userID = try await services.account.userID()
            async let providers = services.api.calendarProviders()
            async let accounts = services.api.calendarAccounts(userID: userID)
            (calendarProviders, calendarAccounts) = try await (providers, accounts)
            if calendarAccounts.contains(where: { $0.status != .active }) {
                calendarMessage = "Una cuenta perdió el acceso. Toca «Reconectar»."
            }
        } catch {
            calendarMessage = error.localizedDescription
        }
    }

    func calendarAuthorizationURL(for provider: ExternalCalendarProvider) async -> URL? {
        do {
            let userID = try await services.account.userID()
            calendarMessage = nil
            return try await services.api.calendarAuthorizationURL(userID: userID, provider: provider)
        } catch {
            // 503 names the .env variables still missing on the backend.
            calendarMessage = error.localizedDescription
            return nil
        }
    }

    func finishCalendarConnection(_ result: CalendarConnectionResult) async {
        switch result {
        case .connected(let provider, let email):
            calendarMessage = "Conectado: \(email ?? provider?.displayName ?? "cuenta")."
        case .failed(let message):
            calendarMessage = message
        }
        await loadCalendars()
    }

    func disconnectCalendar(_ account: CalendarAccount) async {
        do {
            let userID = try await services.account.userID()
            try await services.api.disconnectCalendar(userID: userID, accountID: account.id)
            calendarAccounts.removeAll { $0.id == account.id }
        } catch {
            calendarMessage = error.localizedDescription
        }
    }

    // MARK: Places

    func loadPlaces() async {
        do {
            let userID = try await services.account.userID()
            savedPlaces = try await services.api.locations(userID: userID)
                .filter { $0.isFrequent }
            placesError = nil
        } catch {
            placesError = error.localizedDescription
        }
    }

    /// Saves where the user is now as "Casa", "Oficina"…, used as trip origin
    /// and matched when a note names it.
    func saveCurrentPlace(as alias: String) async {
        let alias = alias.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !alias.isEmpty else { return }
        guard let here = await DeviceLocation().currentCoordinate() else {
            placesError = "No se pudo obtener tu ubicación. Revisa el permiso de ubicación en Ajustes."
            return
        }
        do {
            let userID = try await services.account.userID()
            _ = try await services.api.saveLocation(
                userID: userID,
                LocationInput(alias: alias, coordinate: here, isFrequent: true)
            )
            await loadPlaces()
        } catch {
            placesError = error.localizedDescription
        }
    }

    func deletePlace(_ place: SavedLocation) async {
        do {
            let userID = try await services.account.userID()
            try await services.api.deleteLocation(userID: userID, locationID: place.id)
            savedPlaces.removeAll { $0.id == place.id }
        } catch {
            placesError = error.localizedDescription
        }
    }

    // MARK: Settings

    func setServerURL(_ url: URL) async {
        await services.setServerURL(url)
        upcoming = []
        await flushPending()
        await refreshAgenda()
    }
}
