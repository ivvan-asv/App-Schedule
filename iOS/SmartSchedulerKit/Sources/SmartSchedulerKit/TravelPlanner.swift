import Foundation

public struct ResolvedPlace: Sendable, Equatable {
    public let name: String
    public let address: String?
    public let coordinate: Coordinate
    public let placeId: String?

    public init(name: String, address: String?, coordinate: Coordinate, placeId: String?) {
        self.name = name
        self.address = address
        self.coordinate = coordinate
        self.placeId = placeId
    }
}

public struct RouteEstimate: Sendable, Equatable {
    public let seconds: Int
    public let meters: Int?

    public init(seconds: Int, meters: Int?) {
        self.seconds = seconds
        self.meters = meters
    }
}

/// Map search on the device (MapKit `MKLocalSearch`).
public protocol PlaceSearching: Sendable {
    func searchPlace(_ query: String, near: Coordinate?) async -> ResolvedPlace?
}

/// Travel times on the device (MapKit `MKDirections`, traffic-aware).
public protocol RouteEstimating: Sendable {
    func estimateRoute(from origin: Coordinate, to destination: Coordinate, arrivingAt arrival: Date) async -> RouteEstimate?
}

public protocol CurrentLocationProviding: Sendable {
    func currentCoordinate() async -> Coordinate?
}

/// Decides where an event happens and how long the trip there takes (RF04).
///
/// - Destination: a saved place whose alias the note names ("la oficina"),
///   otherwise the first map search result near home or the user.
/// - Origin: the previous event with a place that day; otherwise the current
///   position for events in the next few hours; otherwise "Casa".
public struct TravelPlanner: Sendable {
    /// Saved aliases treated as the user's home when no other origin is known.
    public static let homeAliases: Set<String> = ["casa", "hogar", "home"]
    /// Events starting within this time leave from wherever the user is now.
    public static let currentLocationWindow: TimeInterval = 3 * 60 * 60
    /// Origin and destination closer than this need no travel block.
    public static let samePlaceMeters = 150.0

    private let api: SchedulerAPI
    private let places: any PlaceSearching
    private let routes: any RouteEstimating
    private let currentLocation: any CurrentLocationProviding
    private let calendar: Calendar
    private let now: @Sendable () -> Date

    public init(
        api: SchedulerAPI,
        places: any PlaceSearching,
        routes: any RouteEstimating,
        currentLocation: any CurrentLocationProviding,
        calendar: Calendar = .current,
        now: @escaping @Sendable () -> Date = Date.init
    ) {
        self.api = api
        self.places = places
        self.routes = routes
        self.currentLocation = currentLocation
        self.calendar = calendar
        self.now = now
    }

    /// The update to send for `event`, or nil when the place cannot be found.
    public func plan(for event: ScheduledEvent, query: String, userID: UUID) async throws -> EventLocationUpdate? {
        let saved = try await api.locations(userID: userID)
        let home = saved.first { Self.isHome($0) }

        var update = EventLocationUpdate()
        let destination: Coordinate
        if let match = Self.savedPlace(matching: query, in: saved) {
            update.locationId = match.id
            destination = match.coordinate
        } else {
            let near: Coordinate? = if let home { home.coordinate } else { await currentLocation.currentCoordinate() }
            guard let place = await places.searchPlace(query, near: near) else { return nil }
            update.location = LocationInput(
                alias: place.name,
                address: place.address,
                coordinate: place.coordinate,
                placeId: place.placeId
            )
            destination = place.coordinate
        }

        guard let origin = try await origin(for: event, userID: userID, saved: saved, home: home),
              origin.coordinate.distance(to: destination) >= Self.samePlaceMeters,
              let route = await routes.estimateRoute(from: origin.coordinate, to: destination, arrivingAt: event.start)
        else { return update }

        update.travel = TravelInput(
            originLocationId: origin.locationId,
            durationSeconds: route.seconds,
            distanceMeters: route.meters
        )
        return update
    }

    private struct Origin {
        let coordinate: Coordinate
        let locationId: UUID?
    }

    private func origin(
        for event: ScheduledEvent,
        userID: UUID,
        saved: [SavedLocation],
        home: SavedLocation?
    ) async throws -> Origin? {
        let dayStart = calendar.startOfDay(for: event.start)
        if dayStart < event.start {
            let earlier = try await api.events(userID: userID, from: dayStart, to: event.start)
            let previous = earlier
                .filter {
                    $0.id != event.id && $0.parentId == nil && $0.status != .cancelled
                        && ($0.type == .task || $0.type == .meeting)
                        && $0.locationId != nil && $0.end <= event.start
                }
                .max { $0.end < $1.end }
            if let previous, let place = saved.first(where: { $0.id == previous.locationId }) {
                return Origin(coordinate: place.coordinate, locationId: place.id)
            }
        }

        if event.start.timeIntervalSince(now()) <= Self.currentLocationWindow,
           let here = await currentLocation.currentCoordinate() {
            return Origin(coordinate: here, locationId: nil)
        }
        return home.map { Origin(coordinate: $0.coordinate, locationId: $0.id) }
    }

    // MARK: Matching saved places

    private static let fillerWords: Set<String> = [
        "a", "al", "de", "del", "el", "en", "la", "las", "lo", "los", "mi", "mis", "the", "to",
    ]

    private static func words(_ text: String) -> Set<String> {
        let folded = text.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "es"))
        return Set(
            folded.components(separatedBy: CharacterSet.alphanumerics.inverted)
                .filter { !$0.isEmpty && !fillerWords.contains($0) }
        )
    }

    static func isHome(_ location: SavedLocation) -> Bool {
        guard let alias = location.alias else { return false }
        return words(alias).count == 1 && !words(alias).isDisjoint(with: homeAliases)
    }

    /// "la oficina" matches a place saved as "Oficina", but "casa de mi mamá"
    /// does not match "Casa": every meaningful word must agree.
    static func savedPlace(matching query: String, in saved: [SavedLocation]) -> SavedLocation? {
        let queryWords = words(query)
        guard !queryWords.isEmpty else { return nil }
        return saved.first { location in
            guard let alias = location.alias else { return false }
            return words(alias) == queryWords
        }
    }
}
