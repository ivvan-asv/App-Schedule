import Foundation

/// Captures waiting to reach the backend (RNF03: offline capture and queueing).
///
/// Synchronous on purpose: `CaptureCoordinator` reads, changes and writes the
/// queue without suspending, so a flush can never overwrite a capture that was
/// queued in the meantime.
public protocol PendingCaptureStore: Sendable {
    func load() throws -> [CaptureRequest]
    func save(_ captures: [CaptureRequest]) throws
}

/// Keeps the queue in a JSON file protected by iOS Data Protection, which
/// encrypts it with the device's AES-256 hardware key while it is at rest (RNF02).
public struct FilePendingCaptureStore: PendingCaptureStore {
    public let fileURL: URL

    public init(fileURL: URL) {
        self.fileURL = fileURL
    }

    public static func inApplicationSupport(fileName: String = "pending-captures.json") throws -> FilePendingCaptureStore {
        let directory = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return FilePendingCaptureStore(fileURL: directory.appending(path: fileName))
    }

    public func load() throws -> [CaptureRequest] {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return [] }
        let data = try Data(contentsOf: fileURL)
        return try SchedulerJSON.decoder().decode([CaptureRequest].self, from: data)
    }

    public func save(_ captures: [CaptureRequest]) throws {
        if captures.isEmpty {
            if FileManager.default.fileExists(atPath: fileURL.path) {
                try FileManager.default.removeItem(at: fileURL)
            }
            return
        }
        let data = try SchedulerJSON.encoder().encode(captures)
        // "Until first authentication" so background refresh can read the
        // queue while the phone is locked.
        try data.write(to: fileURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }
}

public final class InMemoryPendingCaptureStore: PendingCaptureStore, @unchecked Sendable {
    private let lock = NSLock()
    private var captures: [CaptureRequest]

    public init(_ captures: [CaptureRequest] = []) {
        self.captures = captures
    }

    public func load() -> [CaptureRequest] {
        lock.withLock { captures }
    }

    public func save(_ captures: [CaptureRequest]) {
        lock.withLock { self.captures = captures }
    }
}
