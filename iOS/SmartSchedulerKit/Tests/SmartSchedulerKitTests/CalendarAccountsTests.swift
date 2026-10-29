import Foundation
import Testing
@testable import SmartSchedulerKit

@Suite struct CalendarAccountsTests {
    @Test func parsesSuccessfulCallback() throws {
        let url = try #require(URL(string: "smartscheduler://calendar-connected?provider=google&status=ok&email=ana%40gmail.com"))

        #expect(CalendarConnectionResult(callbackURL: url) == .connected(provider: .google, email: "ana@gmail.com"))
    }

    @Test func parsesFailedCallbackWithMessage() throws {
        let url = try #require(URL(string: "smartscheduler://calendar-connected?provider=microsoft&status=error&message=La%20conexi%C3%B3n%20caduc%C3%B3."))

        #expect(CalendarConnectionResult(callbackURL: url) == .failed("La conexión caducó."))
        #expect(CalendarConnectionResult(callbackURL: URL(string: "smartscheduler://x")!) == .failed("No se completó la conexión."))
    }

    @Test func startsAuthorizationAndListsAccounts() async throws {
        let transport = FakeTransport { request in
            switch (request.httpMethod, request.url?.lastPathComponent) {
            case ("POST", "authorize"):
                (200, #"{"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?state=abc"}"#)
            case ("GET", "calendar-accounts"):
                (200, """
                [{"id": "\(UUID().uuidString)", "provider": "google", "external_email": "ana@gmail.com",
                  "status": "token_expirado", "created_at": "2026-10-29T05:00:00.123456Z"}]
                """)
            case ("GET", "calendar-providers"):
                (200, """
                [{"provider": "microsoft", "configured": false, "missing_settings": ["MICROSOFT_CLIENT_ID"],
                  "redirect_uri": "http://localhost:8000/api/v1/oauth/microsoft/callback"}]
                """)
            case ("DELETE", _):
                (204, "")
            default:
                (500, "")
            }
        }
        let api = SchedulerAPI(baseURL: baseURL, transport: transport)

        let url = try await api.calendarAuthorizationURL(userID: userID, provider: .google)
        let accounts = try await api.calendarAccounts(userID: userID)
        let providers = try await api.calendarProviders()
        try await api.disconnectCalendar(userID: userID, accountID: accounts[0].id)

        #expect(url.host() == "accounts.google.com")
        #expect(transport.requests[0].url?.path == "/api/v1/users/\(userID.uuidString)/calendar-accounts/google/authorize")
        #expect(accounts.first?.status == .tokenExpired)
        #expect(providers.first?.missingSettings == ["MICROSOFT_CLIENT_ID"])
        #expect(transport.requests.last?.httpMethod == "DELETE")
    }
}
