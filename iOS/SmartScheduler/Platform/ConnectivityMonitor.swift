import Network

/// Reports when the network comes back, so queued captures are sent right away
/// (RNF03). NWPathMonitor is event-driven and does not poll, which keeps the
/// passive battery cost negligible (RNF04).
enum ConnectivityMonitor {
    static func connectionRestored() -> AsyncStream<Void> {
        AsyncStream { continuation in
            let monitor = NWPathMonitor()
            let state = ConnectionState()
            monitor.pathUpdateHandler = { path in
                if state.update(isConnected: path.status == .satisfied) {
                    continuation.yield()
                }
            }
            continuation.onTermination = { _ in monitor.cancel() }
            monitor.start(queue: DispatchQueue(label: "ai.smartscheduler.connectivity"))
        }
    }
}

/// Only touched from the monitor's serial queue.
private final class ConnectionState: @unchecked Sendable {
    private var wasConnected: Bool?

    /// Returns true when the path changes from offline to online.
    func update(isConnected: Bool) -> Bool {
        defer { wasConnected = isConnected }
        return isConnected && wasConnected == false
    }
}
