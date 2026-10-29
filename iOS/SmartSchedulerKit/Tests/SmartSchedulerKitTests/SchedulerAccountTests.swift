import Foundation
import Testing
@testable import SmartSchedulerKit

@Suite struct SchedulerAccountTests {
    private func backend(rules: String = "[]") -> FakeTransport {
        FakeTransport { request in
            switch (request.httpMethod, request.url?.path) {
            case ("POST", "/api/v1/users/demo"):
                (200, userJSON())
            case ("PATCH", _):
                (200, userJSON(timezone: "Europe/Madrid"))
            case ("GET", _):
                (200, rules)
            case ("POST", _):
                (201, """
                {"id": "\(UUID().uuidString)", "name": "Horario laboral", "weekdays": [1,2,3,4,5],
                 "start_time": "09:00:00", "end_time": "18:00:00", "active": true}
                """)
            default:
                (500, "")
            }
        }
    }

    private func calls(_ transport: FakeTransport) -> [String] {
        transport.requests.map { "\($0.httpMethod!) \($0.url!.lastPathComponent)" }
    }

    @Test func firstBootstrapSyncsTimezoneAndCreatesWorkingHours() async throws {
        let transport = backend()
        let store = MemoryKeyValueStore()
        let account = SchedulerAccount(
            api: SchedulerAPI(baseURL: baseURL, transport: transport),
            store: store,
            currentTimezone: { "Europe/Madrid" }
        )

        let id = try await account.userID()

        #expect(id == userID)
        #expect(calls(transport) == [
            "POST demo",
            "PATCH \(userID.uuidString)",
            "GET availability-rules",
            "POST availability-rules",
        ])
        #expect(jsonBody(transport.requests[3])["start_time"] as? String == "09:00")
        #expect(store.string(forKey: SchedulerAccount.userIDKey) == userID.uuidString)
    }

    @Test func keepsExistingRulesAndMatchingTimezone() async throws {
        let transport = backend(rules: """
        [{"id": "\(UUID().uuidString)", "name": null, "weekdays": [1], "start_time": "08:00:00",
          "end_time": "12:00:00", "active": true}]
        """)
        let account = SchedulerAccount(
            api: SchedulerAPI(baseURL: baseURL, transport: transport),
            store: MemoryKeyValueStore(),
            currentTimezone: { "America/Santiago" }
        )

        _ = try await account.userID()

        #expect(calls(transport) == ["POST demo", "GET availability-rules"])
    }

    @Test func cachedUserMakesNoRequests() async throws {
        let transport = backend()
        let account = SchedulerAccount(
            api: SchedulerAPI(baseURL: baseURL, transport: transport),
            store: MemoryKeyValueStore(),
            currentTimezone: { "Europe/Madrid" }
        )

        _ = try await account.userID()
        let requestsAfterBootstrap = transport.requests.count
        _ = try await account.userID()

        #expect(transport.requests.count == requestsAfterBootstrap)
    }

    @Test func concurrentCallersShareOneBootstrap() async throws {
        let transport = backend()
        let account = SchedulerAccount(
            api: SchedulerAPI(baseURL: baseURL, transport: transport),
            store: MemoryKeyValueStore(),
            currentTimezone: { "America/Santiago" }
        )

        async let first = account.userID()
        async let second = account.userID()
        let ids = try await [first, second]

        #expect(ids == [userID, userID])
        #expect(calls(transport).filter { $0 == "POST demo" }.count == 1)
    }

    @Test func travelUpdatesTimezoneOfCachedUser() async throws {
        let transport = backend()
        let store = MemoryKeyValueStore()
        store.set(userID.uuidString, forKey: SchedulerAccount.userIDKey)
        store.set("America/Santiago", forKey: SchedulerAccount.timezoneKey)
        let account = SchedulerAccount(
            api: SchedulerAPI(baseURL: baseURL, transport: transport),
            store: store,
            currentTimezone: { "Europe/Madrid" }
        )

        _ = try await account.userID()

        #expect(calls(transport) == ["PATCH \(userID.uuidString)"])
        #expect(store.string(forKey: SchedulerAccount.timezoneKey) == "Europe/Madrid")
    }

    @Test func offlineTimezoneSyncStillReturnsCachedUser() async throws {
        let transport = FakeTransport { _ in throw URLError(.notConnectedToInternet) }
        let store = MemoryKeyValueStore()
        store.set(userID.uuidString, forKey: SchedulerAccount.userIDKey)
        store.set("America/Santiago", forKey: SchedulerAccount.timezoneKey)
        let account = SchedulerAccount(
            api: SchedulerAPI(baseURL: baseURL, transport: transport),
            store: store,
            currentTimezone: { "Europe/Madrid" }
        )

        #expect(try await account.userID() == userID)
        #expect(store.string(forKey: SchedulerAccount.timezoneKey) == "America/Santiago")
    }
}
