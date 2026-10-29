import EventKit
import Foundation
import OSLog
import SmartSchedulerKit

enum CalendarAccess {
    case notDetermined
    /// Events can be added but the calendar cannot be read, so busy times are not sent.
    case writeOnly
    case full
    case denied
}

/// The device calendar, through EventKit:
/// - writes the events the backend schedules (Phase 1), and
/// - reads busy times so the backend does not schedule on top of them (Phase 2).
///
/// Only start and end times leave this type; titles, notes and attendees of the
/// user's events are never sent to the backend.
actor EventKitCalendar: CalendarMirror, BusyTimeProvider {
    private static let ledgerPrefix = "calendar.mirrored."
    private let eventStore = EKEventStore()
    private let ledger: any KeyValueStore
    private let logger = Logger(subsystem: "ai.smartscheduler", category: "calendar")

    init(ledger: any KeyValueStore = UserDefaultsStore()) {
        self.ledger = ledger
    }

    nonisolated static var access: CalendarAccess {
        switch EKEventStore.authorizationStatus(for: .event) {
        case .notDetermined: .notDetermined
        case .writeOnly: .writeOnly
        case .fullAccess: .full
        default: .denied
        }
    }

    func requestFullAccess() async -> CalendarAccess {
        do {
            _ = try await eventStore.requestFullAccessToEvents()
        } catch {
            logger.error("Calendar access request failed: \(error.localizedDescription)")
        }
        return Self.access
    }

    // MARK: CalendarMirror

    /// A ledger of mirrored backend ids prevents duplicates when a queued
    /// capture is resent and the backend returns the same event again.
    func mirror(_ event: ScheduledEvent) async {
        let key = Self.ledgerPrefix + event.id.uuidString
        guard ledger.string(forKey: key) == nil, event.status != .cancelled else { return }
        guard [.writeOnly, .full].contains(Self.access) else { return }

        let calendarEvent = EKEvent(eventStore: eventStore)
        calendarEvent.title = event.title
        calendarEvent.startDate = event.start
        calendarEvent.endDate = event.end
        calendarEvent.notes = event.description ?? "Agendado con Smart Scheduler"
        calendarEvent.availability = event.status == .tentative ? .tentative : .busy
        calendarEvent.calendar = eventStore.defaultCalendarForNewEvents

        do {
            try eventStore.save(calendarEvent, span: .thisEvent)
            ledger.set(calendarEvent.eventIdentifier ?? "", forKey: key)
        } catch {
            logger.error("Could not save event to the calendar: \(error.localizedDescription)")
        }
    }

    // MARK: BusyTimeProvider

    func busyIntervals(from start: Date, to end: Date) async -> [BusyInterval] {
        guard Self.access == .full else { return [] }
        let predicate = eventStore.predicateForEvents(withStart: start, end: end, calendars: nil)
        return eventStore.events(matching: predicate)
            .filter(Self.blocksTime)
            .map { BusyInterval(start: $0.startDate, end: $0.endDate) }
    }

    /// All-day entries (birthdays, holidays), events marked free, cancelled
    /// events and invitations the user declined do not make the user busy.
    private static func blocksTime(_ event: EKEvent) -> Bool {
        guard !event.isAllDay, event.availability != .free, event.status != .canceled else {
            return false
        }
        let declined = event.attendees?.contains { $0.isCurrentUser && $0.participantStatus == .declined } ?? false
        return !declined
    }
}
