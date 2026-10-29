import Foundation
import SmartSchedulerKit

/// Process-wide dependencies, shared by the SwiftUI scenes and the App Intents
/// (which can run without any UI, e.g. from Back Tap).
@MainActor
final class AppServices {
    static let shared = AppServices()

    static let backgroundFlushTaskID = "ai.smartscheduler.flush-captures"
    private static let serverURLKey = "scheduler.serverURL"
    #if targetEnvironment(simulator)
    static let defaultServerURL = URL(string: "http://localhost:8000")!
    #else
    // A device cannot reach the Mac's localhost; set the Mac's LAN address in Ajustes.
    static let defaultServerURL = URL(string: "http://smart-scheduler.local:8000")!
    #endif

    let calendar = EventKitCalendar()
    private let defaults = UserDefaultsStore()
    private let pendingStore: any PendingCaptureStore
    private(set) var serverURL: URL
    private(set) var api: SchedulerAPI
    private(set) var account: SchedulerAccount
    private(set) var coordinator: CaptureCoordinator

    private init() {
        pendingStore = (try? FilePendingCaptureStore.inApplicationSupport())
            ?? FilePendingCaptureStore(
                fileURL: FileManager.default.temporaryDirectory.appending(path: "pending-captures.json")
            )
        serverURL = defaults.string(forKey: Self.serverURLKey).flatMap(URL.init(string:))
            ?? Self.defaultServerURL
        (api, account, coordinator) = Self.makeClients(serverURL, defaults, pendingStore, calendar)
    }

    /// Points the app at another backend. The linked user belongs to the old
    /// server, so it is forgotten; queued captures are kept and go to the new one.
    func setServerURL(_ url: URL) async {
        guard url != serverURL else { return }
        await account.reset()
        defaults.set(url.absoluteString, forKey: Self.serverURLKey)
        serverURL = url
        (api, account, coordinator) = Self.makeClients(url, defaults, pendingStore, calendar)
    }

    private static func makeClients(
        _ url: URL,
        _ defaults: UserDefaultsStore,
        _ store: any PendingCaptureStore,
        _ calendar: EventKitCalendar
    ) -> (SchedulerAPI, SchedulerAccount, CaptureCoordinator) {
        let api = SchedulerAPI(baseURL: url)
        let account = SchedulerAccount(api: api, store: defaults)
        let coordinator = CaptureCoordinator(
            api: api,
            account: account,
            store: store,
            mirror: calendar,
            busyTimes: calendar
        )
        return (api, account, coordinator)
    }
}
