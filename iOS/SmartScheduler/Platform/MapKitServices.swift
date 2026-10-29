import CoreLocation
import MapKit
import SmartSchedulerKit

private extension CLLocationCoordinate2D {
    init(_ coordinate: Coordinate) {
        self.init(latitude: coordinate.latitude, longitude: coordinate.longitude)
    }
}

/// Finds the place a note names with Apple Maps search. Free, no API key.
struct MapKitPlaceSearch: PlaceSearching {
    /// Results are looked for within this distance of home or the user.
    static let searchRadiusMeters: CLLocationDistance = 30_000

    func searchPlace(_ query: String, near: Coordinate?) async -> ResolvedPlace? {
        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = query
        request.resultTypes = [.pointOfInterest, .address]
        if let near {
            request.region = MKCoordinateRegion(
                center: CLLocationCoordinate2D(near),
                latitudinalMeters: Self.searchRadiusMeters,
                longitudinalMeters: Self.searchRadiusMeters
            )
        }
        guard let response = try? await MKLocalSearch(request: request).start(),
              let item = response.mapItems.first
        else { return nil }

        let placemark = item.placemark
        var placeID: String?
        if #available(iOS 18, macOS 15, *) {
            placeID = item.identifier?.rawValue
        }
        return ResolvedPlace(
            name: item.name ?? query,
            address: placemark.title,
            coordinate: Coordinate(
                latitude: placemark.coordinate.latitude,
                longitude: placemark.coordinate.longitude
            ),
            placeId: placeID
        )
    }
}

/// Driving time with Apple Maps, including expected traffic at arrival time.
struct MapKitRouteEstimator: RouteEstimating {
    func estimateRoute(from origin: Coordinate, to destination: Coordinate, arrivingAt arrival: Date) async -> RouteEstimate? {
        let request = MKDirections.Request()
        request.source = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(origin)))
        request.destination = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(destination)))
        request.transportType = .automobile
        if arrival > .now {
            request.arrivalDate = arrival
        }
        guard let eta = try? await MKDirections(request: request).calculateETA() else { return nil }
        return RouteEstimate(seconds: Int(eta.expectedTravelTime.rounded()), meters: Int(eta.distance.rounded()))
    }
}

/// The user's position, for trips to events in the next few hours.
///
/// Uses the last fix the system already has when it is recent, and otherwise
/// asks for one with a short timeout: one fix per capture and no continuous
/// tracking, so the battery cost stays negligible (RNF04).
struct DeviceLocation: CurrentLocationProviding {
    static let recentFixAge: TimeInterval = 10 * 60
    static let fixTimeout: Duration = .seconds(3)

    @MainActor private static let manager = CLLocationManager()

    @MainActor static func requestAuthorization() {
        if manager.authorizationStatus == .notDetermined {
            manager.requestWhenInUseAuthorization()
        }
    }

    @MainActor static var isAuthorized: Bool {
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse: true
        default: false
        }
    }

    func currentCoordinate() async -> Coordinate? {
        guard await Self.isAuthorized else { return nil }
        if let recent = await Self.recentFix() {
            return recent
        }
        return await Self.freshFix()
    }

    @MainActor private static func recentFix() -> Coordinate? {
        guard let location = manager.location,
              -location.timestamp.timeIntervalSinceNow < recentFixAge
        else { return nil }
        return Coordinate(latitude: location.coordinate.latitude, longitude: location.coordinate.longitude)
    }

    private static func freshFix() async -> Coordinate? {
        await withTaskGroup(of: Coordinate?.self) { group in
            group.addTask {
                do {
                    for try await update in CLLocationUpdate.liveUpdates() {
                        if let location = update.location {
                            return Coordinate(
                                latitude: location.coordinate.latitude,
                                longitude: location.coordinate.longitude
                            )
                        }
                    }
                } catch {}
                return nil
            }
            group.addTask {
                try? await Task.sleep(for: fixTimeout)
                return nil
            }
            let first = await group.next() ?? nil
            group.cancelAll()
            return first
        }
    }
}
