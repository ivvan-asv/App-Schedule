import Foundation
import Testing
@testable import SmartSchedulerKit

@Suite struct FilePendingCaptureStoreTests {
    @Test func roundTripsAndRemovesFileWhenEmpty() throws {
        let fileURL = FileManager.default.temporaryDirectory
            .appending(path: "pending-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: fileURL) }
        let store = FilePendingCaptureStore(fileURL: fileURL)
        let capture = CaptureRequest(
            text: "llamar al banco",
            channel: .voice,
            capturedAt: Date(timeIntervalSince1970: 1_793_621_700.25),
            createdOffline: true,
            sttEngine: "apple_speech"
        )

        #expect(try store.load().isEmpty)
        try store.save([capture])
        #expect(try store.load() == [capture])

        try store.save([])
        #expect(!FileManager.default.fileExists(atPath: fileURL.path))
        #expect(try store.load().isEmpty)
    }
}
