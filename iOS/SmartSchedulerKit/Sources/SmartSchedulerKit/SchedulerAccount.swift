import Foundation

public protocol AccountProviding: Sendable {
    /// The backend user for this device, created on first use.
    func userID() async throws -> UUID
}

/// Small key-value persistence so the account can be tested without UserDefaults.
public protocol KeyValueStore: Sendable {
    func string(forKey key: String) -> String?
    func set(_ value: String?, forKey key: String)
}

public struct UserDefaultsStore: KeyValueStore, @unchecked Sendable {
    // UserDefaults is thread-safe; it is only missing the Sendable annotation.
    private let defaults: UserDefaults

    public init(_ defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    public func string(forKey key: String) -> String? {
        defaults.string(forKey: key)
    }

    public func set(_ value: String?, forKey key: String) {
        defaults.set(value, forKey: key)
    }
}

/// Links this device to a backend user.
///
/// Until authentication exists the backend exposes a single demo user. On the
/// first successful bootstrap the account also sends the device timezone (used
/// to resolve "mañana a las 3") and creates a default working-hours rule, which
/// the backend needs before it can place captures without a clock time.
public actor SchedulerAccount: AccountProviding {
    static let userIDKey = "scheduler.userID"
    static let timezoneKey = "scheduler.syncedTimezone"

    private let api: SchedulerAPI
    private let store: any KeyValueStore
    private let currentTimezone: @Sendable () -> String
    private var bootstrap: Task<UUID, any Error>?

    public init(
        api: SchedulerAPI,
        store: any KeyValueStore,
        currentTimezone: @escaping @Sendable () -> String = { TimeZone.current.identifier }
    ) {
        self.api = api
        self.store = store
        self.currentTimezone = currentTimezone
    }

    public func userID() async throws -> UUID {
        if let cached = store.string(forKey: Self.userIDKey).flatMap(UUID.init(uuidString:)) {
            try await syncTimezoneIfNeeded(cached)
            return cached
        }

        // Concurrent callers (an App Intent and the UI) share one bootstrap.
        if let bootstrap {
            return try await bootstrap.value
        }
        let task = Task { try await createAccount() }
        bootstrap = task
        defer { bootstrap = nil }
        return try await task.value
    }

    /// Forgets the linked user, e.g. after pointing the app at another server.
    public func reset() {
        store.set(nil, forKey: Self.userIDKey)
        store.set(nil, forKey: Self.timezoneKey)
    }

    private func createAccount() async throws -> UUID {
        let user = try await api.createDemoUser()
        let timezone = currentTimezone()
        if user.timezone != timezone {
            _ = try await api.updateUser(user.id, UserUpdate(timezone: timezone))
        }
        if try await api.workingHoursRules(userID: user.id).isEmpty {
            _ = try await api.createWorkingHoursRule(userID: user.id, .defaultWorkweek)
        }

        // Stored last, so an interrupted bootstrap is retried from the start;
        // every step above is idempotent.
        store.set(timezone, forKey: Self.timezoneKey)
        store.set(user.id.uuidString, forKey: Self.userIDKey)
        return user.id
    }

    private func syncTimezoneIfNeeded(_ userID: UUID) async throws {
        let timezone = currentTimezone()
        guard store.string(forKey: Self.timezoneKey) != timezone else { return }
        do {
            _ = try await api.updateUser(userID, UserUpdate(timezone: timezone))
            store.set(timezone, forKey: Self.timezoneKey)
        } catch let error as SchedulerAPIError where error.isRetryable {
            // Travelling without coverage: keep the old timezone and retry next time.
        }
    }
}
