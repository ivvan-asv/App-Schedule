import SmartSchedulerKit
import SwiftUI

struct CaptureView: View {
    @Environment(AppModel.self) private var model
    @FocusState private var isTyping: Bool

    var body: some View {
        @Bindable var model = model
        NavigationStack {
            VStack(spacing: 24) {
                Spacer(minLength: 0)
                transcript
                MicrophoneButton(
                    isListening: model.transcriber.isListening,
                    isBusy: model.isSubmitting
                ) {
                    isTyping = false
                    Task { await model.toggleDictation() }
                }
                Text(model.transcriber.isListening ? "Te escucho… haz una pausa para terminar" : "Toca y dicta lo que quieres agendar")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
                if let banner = model.banner {
                    BannerView(banner: banner) { model.dismissBanner() }
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                typedNoteField
            }
            .padding()
            .animation(.snappy, value: model.banner)
            .navigationTitle("Smart Scheduler")
            .toolbar {
                if !model.pendingCaptures.isEmpty {
                    ToolbarItem {
                        Label("\(model.pendingCaptures.count) en cola", systemImage: "icloud.and.arrow.up")
                            .labelStyle(.titleAndIcon)
                            .font(.footnote)
                            .foregroundStyle(.orange)
                    }
                }
            }
            // Confirmation haptic at the end of the capture (flujo 3.1, paso 6).
            .sensoryFeedback(trigger: model.banner) { _, banner in
                switch banner {
                case .scheduled, .queued: .success
                case .rejected: .warning
                case .failed: .error
                case nil: nil
                }
            }
            .sensoryFeedback(.start, trigger: model.transcriber.isListening) { _, listening in listening }
        }
    }

    @ViewBuilder
    private var transcript: some View {
        let text = model.transcriber.transcript
        Text(text.isEmpty ? "“Mañana a las tres, dentista una hora”" : text)
            .font(.title3)
            .multilineTextAlignment(.center)
            .foregroundStyle(text.isEmpty ? .tertiary : .primary)
            .frame(maxWidth: .infinity, minHeight: 80)
            .contentTransition(.opacity)
    }

    private var typedNoteField: some View {
        @Bindable var model = model
        return HStack {
            TextField("O escribe tu nota…", text: $model.typedNote, axis: .vertical)
                .lineLimit(1...3)
                .focused($isTyping)
                .submitLabel(.send)
                .onSubmit { Task { await model.submitTypedNote() } }
            Button {
                Task { await model.submitTypedNote() }
            } label: {
                Image(systemName: "arrow.up.circle.fill").font(.title2)
            }
            .disabled(model.typedNote.trimmingCharacters(in: .whitespaces).isEmpty || model.isSubmitting)
            .accessibilityLabel("Enviar nota")
        }
        .padding(12)
        .background(.quaternary.opacity(0.5), in: .rect(cornerRadius: 16))
    }
}

private struct MicrophoneButton: View {
    let isListening: Bool
    let isBusy: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .fill(isListening ? Color.red : Color.accentColor)
                    .frame(width: 120, height: 120)
                    .shadow(color: (isListening ? Color.red : Color.accentColor).opacity(0.35), radius: isListening ? 24 : 8)
                if isBusy {
                    ProgressView().tint(.white).controlSize(.large)
                } else {
                    Image(systemName: isListening ? "stop.fill" : "mic.fill")
                        .font(.system(size: 44, weight: .semibold))
                        .foregroundStyle(.white)
                        .symbolEffect(.pulse, isActive: isListening)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(isBusy)
        .accessibilityLabel(isListening ? "Terminar dictado" : "Dictar nota")
    }
}

struct BannerView: View {
    let banner: CaptureBanner
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.title2)
                .foregroundStyle(tint)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(detail).font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            Button(action: onDismiss) {
                Image(systemName: "xmark").font(.footnote.bold()).foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Cerrar")
        }
        .padding()
        .background(tint.opacity(0.12), in: .rect(cornerRadius: 16))
    }

    private var icon: String {
        switch banner {
        case .scheduled: "checkmark.circle.fill"
        case .queued: "tray.and.arrow.up.fill"
        case .rejected: "exclamationmark.triangle.fill"
        case .failed: "xmark.octagon.fill"
        }
    }

    private var tint: Color {
        switch banner {
        case .scheduled: .green
        case .queued: .orange
        case .rejected: .yellow
        case .failed: .red
        }
    }

    private var title: String {
        switch banner {
        case .scheduled(let scheduled): scheduled.event.title
        case .queued: "Guardado sin conexión"
        case .rejected: "No se pudo agendar"
        case .failed: "Error"
        }
    }

    private var detail: String {
        switch banner {
        case .scheduled(let scheduled): scheduled.summary
        case .queued: "Se agendará cuando vuelva la conexión."
        case .rejected(let reason), .failed(let reason): reason
        }
    }
}

extension ScheduledCapture {
    /// "mar 3 nov, 15:00–16:00 · Clínica Dental · 25 min de traslado".
    var summary: String {
        var parts = [event.summary]
        if let location {
            parts.append(location.displayName)
        }
        if let travel {
            let minutes = Int(travel.end.timeIntervalSince(travel.start) / 60)
            parts.append("\(minutes) min de traslado")
        }
        var text = parts.joined(separator: " · ")
        if moved {
            text += "\nSe movió para que llegues a tiempo."
        }
        if travelOverlaps {
            text += "\nOjo: el traslado se cruza con otro compromiso."
        }
        return text
    }
}

extension ScheduledEvent {
    /// "mar 3 nov, 15:00–16:00", plus a note when the app picked the time.
    var summary: String {
        let day = start.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))
        let hours = "\(start.formatted(date: .omitted, time: .shortened))–\(end.formatted(date: .omitted, time: .shortened))"
        return flexible ? "\(day), \(hours) · hueco libre elegido" : "\(day), \(hours)"
    }
}
