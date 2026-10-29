import Foundation
import Testing
@testable import SmartSchedulerKit

@Suite struct TravelPlannerTests {
    private let homeID = UUID()
    private let officeID = UUID()
    // 2026-11-03 18:00 UTC; "now" is the day before, so the current position is not used.
    private let event = ScheduledEvent(
        id: UUID(),
        title: "Dentista",
        start: Date(timeIntervalSince1970: 1_793_728_800),
        end: Date(timeIntervalSince1970: 1_793_732_400)
    )
    private let dayBefore = Date(timeIntervalSince1970: 1_793_728_800 - 86_400)

    private func backend(earlierEvents: String = "[]") -> FakeTransport {
        let saved = "[\(locationJSON(id: homeID, alias: "Casa", home)), \(locationJSON(id: officeID, alias: "Oficina", office))]"
        return FakeTransport { request in
            switch request.url?.lastPathComponent {
            case "locations": (200, saved)
            case "events": (200, earlierEvents)
            default: (500, "")
            }
        }
    }

    private func planner(
        _ transport: FakeTransport,
        places: FakePlaces = FakePlaces(ResolvedPlace(name: "Clínica Dental", address: "Av. Providencia 1234", coordinate: dentist, placeId: "mk-1")),
        routes: FakeRoutes = FakeRoutes(RouteEstimate(seconds: 1_320, meters: 5_400)),
        here: Coordinate? = nil,
        now: Date? = nil
    ) -> TravelPlanner {
        let reference = now ?? dayBefore
        return TravelPlanner(
            api: SchedulerAPI(baseURL: baseURL, transport: transport),
            places: places,
            routes: routes,
            currentLocation: FixedLocation(coordinate: here),
            calendar: utcCalendar,
            now: { reference }
        )
    }

    @Test(arguments: [("la oficina", true), ("Oficina", true), ("OFICINA central", false), ("casa de mi mamá", false)])
    func matchesSavedPlacesByEveryMeaningfulWord(query: String, matches: Bool) {
        let saved = [
            SavedLocation(id: homeID, alias: "Casa", latitude: 0, longitude: 0),
            SavedLocation(id: officeID, alias: "Oficina", latitude: 0, longitude: 0),
        ]
        #expect((TravelPlanner.savedPlace(matching: query, in: saved)?.id == officeID) == matches)
    }

    @Test func searchesThePlaceNearHomeAndLeavesFromHome() async throws {
        let places = FakePlaces(ResolvedPlace(name: "Clínica Dental", address: "Av. Providencia 1234", coordinate: dentist, placeId: "mk-1"))
        let routes = FakeRoutes(RouteEstimate(seconds: 1_320, meters: 5_400))

        let update = try #require(
            try await planner(backend(), places: places, routes: routes)
                .plan(for: event, query: "dentista en Providencia", userID: userID)
        )

        #expect(places.queries.first?.0 == "dentista en Providencia")
        #expect(places.queries.first?.1 == home)
        #expect(update.locationId == nil)
        #expect(update.location == LocationInput(alias: "Clínica Dental", address: "Av. Providencia 1234", coordinate: dentist, placeId: "mk-1"))
        #expect(update.travel == TravelInput(originLocationId: homeID, durationSeconds: 1_320, distanceMeters: 5_400))
        #expect(routes.requests.first?.0 == home)
        #expect(routes.requests.first?.2 == event.start)
    }

    @Test func savedPlaceIsUsedWithoutSearching() async throws {
        let places = FakePlaces(nil)

        let update = try #require(
            try await planner(backend(), places: places).plan(for: event, query: "la oficina", userID: userID)
        )

        #expect(places.queries.isEmpty)
        #expect(update.locationId == officeID)
        #expect(update.location == nil)
    }

    @Test func previousEventWithAPlaceThatDayIsTheOrigin() async throws {
        let earlier = """
        [\(eventJSON(title: "Trabajo", start: "2026-11-03T13:00:00Z", end: "2026-11-03T17:00:00Z", locationId: officeID)),
         \(eventJSON(title: "Traslado", type: "traslado", start: "2026-11-03T12:30:00Z", end: "2026-11-03T13:00:00Z", locationId: homeID, parentId: UUID())),
         \(eventJSON(title: "Llamada", start: "2026-11-03T17:00:00Z", end: "2026-11-03T17:30:00Z"))]
        """
        let routes = FakeRoutes(RouteEstimate(seconds: 900, meters: nil))

        let update = try await planner(backend(earlierEvents: earlier), routes: routes)
            .plan(for: event, query: "dentista", userID: userID)

        #expect(update?.travel?.originLocationId == officeID)
        #expect(routes.requests.first?.0 == office)
    }

    @Test func soonEventsLeaveFromTheCurrentPosition() async throws {
        let here = Coordinate(latitude: -33.45, longitude: -70.60)
        let routes = FakeRoutes(RouteEstimate(seconds: 600, meters: 2_000))

        let update = try await planner(backend(), routes: routes, here: here, now: event.start.addingTimeInterval(-3_600))
            .plan(for: event, query: "dentista", userID: userID)

        #expect(update?.travel?.originLocationId == nil)
        #expect(update?.travel?.durationSeconds == 600)
        #expect(routes.requests.first?.0 == here)
    }

    @Test func unknownPlaceGivesNoUpdate() async throws {
        let update = try await planner(backend(), places: FakePlaces(nil)).plan(for: event, query: "lugar raro", userID: userID)

        #expect(update == nil)
    }

    @Test func noRouteOrSamePlaceKeepsThePlaceWithoutTravel() async throws {
        let noRoute = try await planner(backend(), routes: FakeRoutes(nil)).plan(for: event, query: "dentista", userID: userID)
        #expect(noRoute?.location != nil)
        #expect(noRoute?.travel == nil)

        let routes = FakeRoutes(RouteEstimate(seconds: 60, meters: 10))
        let atHome = try await planner(
            backend(),
            places: FakePlaces(ResolvedPlace(name: "Edificio", address: nil, coordinate: home, placeId: nil)),
            routes: routes
        ).plan(for: event, query: "conserjería", userID: userID)
        #expect(atHome?.travel == nil)
        #expect(routes.requests.isEmpty)
    }
}

@Suite struct CaptureTravelTests {
    @Test func placeAndTripAreSetBeforeMirroring() async throws {
        let eventID = UUID()
        let locationID = UUID()
        let travelID = UUID()
        let transport = FakeTransport { request in
            switch (request.httpMethod, request.url?.lastPathComponent) {
            case ("POST", "captures"):
                (201, captureJSON(event: eventJSON(id: eventID), locationQuery: "dentista en Providencia"))
            case ("GET", "locations"):
                (200, "[]")
            case ("GET", "events"):
                (200, "[]")
            case ("PUT", "location"):
                (200, """
                {"event": \(eventJSON(id: eventID, start: "2026-11-03T18:30:00Z", end: "2026-11-03T19:30:00Z", locationId: locationID)),
                 "location": \(locationJSON(id: locationID, alias: "Clínica Dental", dentist)),
                 "travel": \(eventJSON(id: travelID, title: "Traslado a Clínica Dental", type: "traslado", start: "2026-11-03T18:05:00Z", end: "2026-11-03T18:30:00Z", parentId: eventID)),
                 "moved": true, "travel_overlaps": false}
                """)
            default:
                (500, "")
            }
        }
        let api = SchedulerAPI(baseURL: baseURL, transport: transport)
        let mirror = RecordingMirror()
        let coordinator = CaptureCoordinator(
            api: api,
            account: FixedAccount(id: userID),
            store: InMemoryPendingCaptureStore(),
            mirror: mirror,
            busyTimes: FakeBusyTimes([busy(1, 2)]),
            travelPlanner: TravelPlanner(
                api: api,
                places: FakePlaces(ResolvedPlace(name: "Clínica Dental", address: nil, coordinate: dentist, placeId: nil)),
                routes: FakeRoutes(RouteEstimate(seconds: 1_320, meters: 5_400)),
                currentLocation: FixedLocation(coordinate: home),
                calendar: utcCalendar,
                // An hour before the event, so the trip leaves from the current position.
                now: { Date(timeIntervalSince1970: 1_793_728_800 - 3_600) }
            )
        )

        let outcome = try await coordinator.submit(text: "mañana dentista en Providencia", channel: .voice)

        guard case .scheduled(let scheduled) = outcome else {
            Issue.record("expected a scheduled event, got \(outcome)")
            return
        }
        #expect(scheduled.moved)
        #expect(scheduled.location?.id == locationID)
        #expect(scheduled.travel?.id == travelID)
        // The moved time is what reaches the device calendar, followed by the trip.
        #expect(mirror.mirrored.map(\.id) == [eventID, travelID])
        #expect(mirror.mirrored.first?.start == SchedulerJSON.date(from: "2026-11-03T18:30:00Z"))

        let put = try #require(transport.requests.first { $0.httpMethod == "PUT" })
        let body = jsonBody(put)
        #expect((body["travel"] as? [String: Any])?["duration_seconds"] as? Int == 1_320)
        #expect((body["busy_intervals"] as? [Any])?.count == 1)
    }

    @Test func failedTripKeepsTheEventAsPlaced() async throws {
        let eventID = UUID()
        let transport = FakeTransport { request in
            request.url?.lastPathComponent == "captures"
                ? (201, captureJSON(event: eventJSON(id: eventID), locationQuery: "dentista"))
                : (500, "")
        }
        let api = SchedulerAPI(baseURL: baseURL, transport: transport)
        let mirror = RecordingMirror()
        let coordinator = CaptureCoordinator(
            api: api,
            account: FixedAccount(id: userID),
            store: InMemoryPendingCaptureStore(),
            mirror: mirror,
            travelPlanner: TravelPlanner(
                api: api,
                places: FakePlaces(nil),
                routes: FakeRoutes(nil),
                currentLocation: FixedLocation(coordinate: nil)
            )
        )

        let outcome = try await coordinator.submit(text: "dentista", channel: .voice)

        #expect(outcome == .scheduled(ScheduledCapture(event: try #require(mirror.mirrored.first))))
        #expect(mirror.mirrored.map(\.id) == [eventID])
    }
}
