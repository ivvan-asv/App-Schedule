import Foundation

/// External calendars the backend can connect to (RF07).
public enum ExternalCalendarProvider: String, Codable, Sendable, CaseIterable, Identifiable {
    case google
    case microsoft

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .google: "Google Calendar"
        case .microsoft: "Outlook"
        }
    }
}

public enum CalendarAccountStatus: String, Codable, Sendable {
    case active = "activa"
    /// The user revoked access or the grant expired; connect again.
    case tokenExpired = "token_expirado"
    case revoked = "revocada"
}

public struct CalendarAccount: Codable, Sendable, Equatable, Identifiable {
    public let id: UUID
    public let provider: ExternalCalendarProvider
    public let externalEmail: String?
    public let status: CalendarAccountStatus
    public let createdAt: Date
}

/// Whether the backend has credentials for a provider (`GET /calendar-providers`).
public struct CalendarProviderStatus: Codable, Sendable, Equatable {
    public let provider: ExternalCalendarProvider
    public let configured: Bool
    /// Variables still empty in the backend's .env.
    public let missingSettings: [String]
    /// The URI to register in the provider's console.
    public let redirectUri: String
}

/// What the backend reports when the browser returns to the app.
public enum CalendarConnectionResult: Sendable, Equatable {
    case connected(provider: ExternalCalendarProvider?, email: String?)
    case failed(String)

    /// The scheme the backend redirects to (`APP_OAUTH_CALLBACK_URL`).
    public static let callbackScheme = "smartscheduler"

    /// Parses `smartscheduler://calendar-connected?provider=google&status=ok&email=…`.
    public init(callbackURL: URL) {
        let items = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func value(_ name: String) -> String? {
            items.first { $0.name == name }?.value.flatMap { $0.isEmpty ? nil : $0 }
        }
        if value("status") == "ok" {
            self = .connected(
                provider: value("provider").flatMap(ExternalCalendarProvider.init(rawValue:)),
                email: value("email")
            )
        } else {
            self = .failed(value("message") ?? "No se completó la conexión.")
        }
    }
}

private struct AuthorizationStart: Decodable {
    let authorizationUrl: URL
}

extension SchedulerAPI {
    public func calendarProviders() async throws -> [CalendarProviderStatus] {
        try await get("calendar-providers")
    }

    public func calendarAccounts(userID: UUID) async throws -> [CalendarAccount] {
        try await get("users/\(userID.uuidString)/calendar-accounts")
    }

    /// The provider consent page to open in `ASWebAuthenticationSession`.
    public func calendarAuthorizationURL(
        userID: UUID,
        provider: ExternalCalendarProvider
    ) async throws -> URL {
        let start: AuthorizationStart = try await post(
            "users/\(userID.uuidString)/calendar-accounts/\(provider.rawValue)/authorize"
        )
        return start.authorizationUrl
    }

    public func disconnectCalendar(userID: UUID, accountID: UUID) async throws {
        try await delete("users/\(userID.uuidString)/calendar-accounts/\(accountID.uuidString)")
    }
}
