import AppIntents
import SmartSchedulerKit

/// Schedules a note without opening the app (RF01). Bound to Back Tap or the
/// Action Button through a shortcut; when run without a note, the system asks
/// for it and the user dictates the answer.
struct ScheduleNoteIntent: AppIntent {
    static let title: LocalizedStringResource = "Agendar nota"
    static let description = IntentDescription(
        "Convierte una nota dictada en un bloque de tiempo en tu agenda.",
        categoryName: "Captura"
    )

    @Parameter(
        title: "Nota",
        requestValueDialog: IntentDialog("¿Qué quieres agendar?")
    )
    var note: String

    static var parameterSummary: some ParameterSummary {
        Summary("Agendar \(\.$note)")
    }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let banner = await AppModel.shared.submit(note, channel: .voice, sttEngine: "siri_dictation")
        let message: String = switch banner {
        case .scheduled(let event): "Listo: \(event.title), \(event.summary)."
        case .queued: "Sin conexión. Lo agendaré en cuanto vuelva la red."
        case .rejected(let reason): "No pude agendarlo: \(reason)"
        case .failed(let reason): "Algo falló: \(reason)"
        }
        return .result(dialog: "\(message)")
    }
}

/// Opens the app already listening, for longer notes dictated with on-device
/// speech recognition instead of the system prompt.
struct DictateCaptureIntent: AppIntent {
    static let title: LocalizedStringResource = "Dictar en Smart Scheduler"
    static let description = IntentDescription(
        "Abre Smart Scheduler escuchando tu nota.",
        categoryName: "Captura"
    )
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        AppModel.shared.requestDictation()
        return .result()
    }
}

struct SmartSchedulerShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: ScheduleNoteIntent(),
            phrases: [
                "Agendar en \(.applicationName)",
                "Agenda algo en \(.applicationName)",
                "Anota en \(.applicationName)",
            ],
            shortTitle: "Agendar nota",
            systemImageName: "calendar.badge.plus"
        )
        AppShortcut(
            intent: DictateCaptureIntent(),
            phrases: [
                "Dictar en \(.applicationName)",
                "Escucha en \(.applicationName)",
            ],
            shortTitle: "Dictar",
            systemImageName: "mic.fill"
        )
    }
}
