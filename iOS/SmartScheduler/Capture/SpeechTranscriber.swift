import AVFoundation
import Foundation
import Observation
import Speech

enum TranscriberError: LocalizedError {
    case notAuthorized
    case unavailable
    case noSpeech

    var errorDescription: String? {
        switch self {
        case .notAuthorized:
            "Permite el acceso al micrófono y al reconocimiento de voz en Ajustes."
        case .unavailable:
            "El reconocimiento de voz no está disponible en este momento."
        case .noSpeech:
            "No se escuchó ninguna nota."
        }
    }
}

/// Streams microphone audio into Apple's Speech framework (RF02).
///
/// Recognition runs on the device whenever the language model is installed,
/// so audio never leaves the phone, and it is never written to disk (RNF02).
/// Listening ends by itself after a short silence, so a capture needs no tap.
@MainActor
@Observable
final class SpeechTranscriber {
    static let silenceTimeout: Duration = .milliseconds(1_500)
    static let initialSilenceTimeout: Duration = .seconds(6)

    private(set) var transcript = ""
    private(set) var isListening = false
    private(set) var isOnDevice = false

    @ObservationIgnored private let recognizer: SFSpeechRecognizer?
    @ObservationIgnored private let audioEngine = AVAudioEngine()
    @ObservationIgnored private var request: SFSpeechAudioBufferRecognitionRequest?
    @ObservationIgnored private var recognitionTask: SFSpeechRecognitionTask?
    @ObservationIgnored private var silenceTimer: Task<Void, Never>?
    @ObservationIgnored private var continuation: CheckedContinuation<String, any Error>?

    init(locale: Locale = .current) {
        recognizer = SFSpeechRecognizer(locale: locale) ?? SFSpeechRecognizer(locale: Locale(identifier: "es-ES"))
    }

    /// Value stored in `capturas.motor_stt`.
    var engineName: String {
        isOnDevice ? "apple_speech" : "apple_speech_server"
    }

    /// Listens until the user stops talking (or calls `stop()`) and returns the text.
    func listen() async throws -> String {
        guard await Self.requestPermissions() else { throw TranscriberError.notAuthorized }
        guard let recognizer, recognizer.isAvailable else { throw TranscriberError.unavailable }
        cancel()

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.addsPunctuation = true
        request.taskHint = .dictation
        isOnDevice = recognizer.supportsOnDeviceRecognition
        request.requiresOnDeviceRecognition = isOnDevice

        try Self.activateAudioSession()
        Self.installTap(on: audioEngine.inputNode, feeding: request)
        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            audioEngine.inputNode.removeTap(onBus: 0)
            Self.deactivateAudioSession()
            throw error
        }

        self.request = request
        transcript = ""
        isListening = true
        recognitionTask = Self.startRecognition(recognizer, request) { [weak self] text, isFinal, error in
            Task { @MainActor in self?.handle(text: text, isFinal: isFinal, error: error) }
        }
        restartSilenceTimer(after: Self.initialSilenceTimeout)

        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
        }
    }

    /// Ends listening now and delivers what was heard so far.
    func stop() {
        guard isListening else { return }
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        tearDown()
        if text.isEmpty {
            continuation?.resume(throwing: TranscriberError.noSpeech)
        } else {
            continuation?.resume(returning: text)
        }
        continuation = nil
    }

    func cancel() {
        guard isListening else { return }
        tearDown()
        continuation?.resume(throwing: CancellationError())
        continuation = nil
    }

    private func handle(text: String?, isFinal: Bool, error: (any Error)?) {
        guard isListening else { return }
        if let text, text != transcript {
            transcript = text
            restartSilenceTimer(after: Self.silenceTimeout)
        }
        if isFinal || error != nil {
            stop()
        }
    }

    private func restartSilenceTimer(after timeout: Duration) {
        silenceTimer?.cancel()
        silenceTimer = Task { [weak self] in
            try? await Task.sleep(for: timeout)
            guard !Task.isCancelled else { return }
            self?.stop()
        }
    }

    private func tearDown() {
        silenceTimer?.cancel()
        silenceTimer = nil
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        // The partial transcript is used as is: waiting for the final result
        // would add latency against the 3 s budget (RNF01).
        recognitionTask?.cancel()
        request = nil
        recognitionTask = nil
        isListening = false
        Self.deactivateAudioSession()
    }

    // The audio tap and the recognition handler run on background threads, so
    // they are created outside the main actor to avoid isolation traps.

    nonisolated private static func installTap(
        on node: AVAudioInputNode,
        feeding request: SFSpeechAudioBufferRecognitionRequest
    ) {
        node.installTap(onBus: 0, bufferSize: 1_024, format: node.outputFormat(forBus: 0)) { buffer, _ in
            request.append(buffer)
        }
    }

    nonisolated private static func startRecognition(
        _ recognizer: SFSpeechRecognizer,
        _ request: SFSpeechAudioBufferRecognitionRequest,
        handler: @escaping @Sendable (String?, Bool, (any Error)?) -> Void
    ) -> SFSpeechRecognitionTask {
        recognizer.recognitionTask(with: request) { result, error in
            handler(result?.bestTranscription.formattedString, result?.isFinal ?? false, error)
        }
    }

    nonisolated private static func requestPermissions() async -> Bool {
        let speechStatus = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard speechStatus == .authorized else { return false }
        return await AVAudioApplication.requestRecordPermission()
    }

    private static func activateAudioSession() throws {
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: .duckOthers)
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        #endif
    }

    private static func deactivateAudioSession() {
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
    }
}
