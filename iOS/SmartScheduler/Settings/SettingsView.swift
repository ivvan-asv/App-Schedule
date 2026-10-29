import SmartSchedulerKit
import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var serverAddress = ""
    @State private var calendarAccess = EventKitCalendar.access
    @State private var isFlushing = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://mi-mac.local:8000", text: $serverAddress)
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        #endif
                    Button("Guardar servidor") {
                        guard let url = serverURL else { return }
                        Task { await model.setServerURL(url) }
                    }
                    .disabled(serverURL == nil || serverURL == model.serverURL)
                } header: {
                    Text("Servidor")
                } footer: {
                    Text("Dirección del backend FastAPI. En un iPhone usa el nombre del Mac en la red local (scutil --get LocalHostName) terminado en .local.")
                }

                Section {
                    LabeledContent("Acceso", value: calendarAccessDescription)
                    if calendarAccess != .full {
                        Button("Permitir acceso completo") {
                            Task {
                                if calendarAccess == .notDetermined {
                                    calendarAccess = await AppServices.shared.calendar.requestFullAccess()
                                } else {
                                    openSystemSettings()
                                }
                            }
                        }
                    }
                } header: {
                    Text("Calendario del dispositivo")
                } footer: {
                    Text("Con acceso completo, Smart Scheduler evita tus otros compromisos al elegir hora. Solo se envían al servidor las horas de inicio y fin, nunca los títulos ni los asistentes.")
                }

                Section {
                    LabeledContent("Capturas en cola", value: "\(model.pendingCaptures.count)")
                    ForEach(model.pendingCaptures) { capture in
                        VStack(alignment: .leading) {
                            Text(capture.text).lineLimit(2)
                            Text(capture.capturedAt, format: .dateTime.day().month().hour().minute())
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    if !model.pendingCaptures.isEmpty {
                        Button(isFlushing ? "Enviando…" : "Enviar ahora") {
                            Task {
                                isFlushing = true
                                await model.flushPending()
                                isFlushing = false
                            }
                        }
                        .disabled(isFlushing)
                    }
                } header: {
                    Text("Sin conexión")
                } footer: {
                    Text("Las notas dictadas sin conexión se guardan cifradas en el dispositivo y se envían solas al recuperar la red.")
                }

                Section {
                    Text("""
                    1. Abre Atajos y crea un atajo con la acción «Agendar nota» de Smart Scheduler.
                    2. En Ajustes › Accesibilidad › Tocar › Toque atrás, asigna ese atajo a «Doble toque» o «Triple toque».
                    3. En iPhone 15 Pro o posterior también puedes asignarlo al botón de Acción.
                    """)
                    .font(.callout)
                    Text("Usa «Dictar en Smart Scheduler» si prefieres que se abra la app escuchando.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                } header: {
                    Text("Back Tap y botón de Acción")
                }
            }
            .navigationTitle("Ajustes")
            .onAppear {
                serverAddress = model.serverURL.absoluteString
                calendarAccess = EventKitCalendar.access
            }
        }
    }

    private var calendarAccessDescription: String {
        switch calendarAccess {
        case .full: "Completo"
        case .writeOnly: "Solo añadir eventos"
        case .notDetermined: "Sin configurar"
        case .denied: "No permitido"
        }
    }

    private var serverURL: URL? {
        let trimmed = serverAddress.trimmingCharacters(in: .whitespaces)
        guard let url = URL(string: trimmed), let scheme = url.scheme,
              ["http", "https"].contains(scheme), url.host() != nil
        else { return nil }
        return url
    }

    private func openSystemSettings() {
        #if os(iOS)
        if let url = URL(string: UIApplication.openSettingsURLString) {
            UIApplication.shared.open(url)
        }
        #endif
    }
}
