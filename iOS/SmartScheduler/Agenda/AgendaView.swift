import SmartSchedulerKit
import SwiftUI

struct AgendaView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        NavigationStack {
            List {
                if let error = model.agendaError {
                    Label(error, systemImage: "wifi.exclamationmark")
                        .foregroundStyle(.secondary)
                }
                ForEach(days, id: \.day) { group in
                    Section(group.day.formatted(.dateTime.weekday(.wide).day().month(.wide))) {
                        ForEach(group.events) { EventRow(event: $0) }
                    }
                }
            }
            .overlay {
                if model.upcoming.isEmpty && model.agendaError == nil && !model.isLoadingAgenda {
                    ContentUnavailableView(
                        "Sin eventos",
                        systemImage: "calendar",
                        description: Text("Lo que dictes aparecerá aquí durante los próximos 7 días.")
                    )
                }
            }
            .navigationTitle("Agenda")
            .refreshable { await model.refreshAgenda() }
            .task { await model.refreshAgenda() }
        }
    }

    private var days: [(day: Date, events: [ScheduledEvent])] {
        let calendar = Calendar.current
        return Dictionary(grouping: model.upcoming) { calendar.startOfDay(for: $0.start) }
            .sorted { $0.key < $1.key }
            .map { (day: $0.key, events: $0.value.sorted { $0.start < $1.start }) }
    }
}

private struct EventRow: View {
    let event: ScheduledEvent

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .trailing) {
                Text(event.start, style: .time)
                Text(event.end, style: .time).foregroundStyle(.secondary)
            }
            .font(.footnote.monospacedDigit())
            .frame(width: 56, alignment: .trailing)

            RoundedRectangle(cornerRadius: 2)
                .fill(color)
                .frame(width: 4)

            VStack(alignment: .leading, spacing: 2) {
                Text(event.title).font(.body)
                HStack(spacing: 8) {
                    Label(typeName, systemImage: typeIcon)
                    if event.flexible {
                        Label("Flexible", systemImage: "wand.and.stars")
                    }
                    if event.status == .tentative {
                        Label("Tentativo", systemImage: "questionmark.circle")
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .labelStyle(.titleAndIcon)
            }
        }
        .padding(.vertical, 2)
    }

    private var typeName: String {
        switch event.type {
        case .task: "Tarea"
        case .meeting: "Reunión"
        case .travel: "Traslado"
        case .buffer: "Margen"
        }
    }

    private var typeIcon: String {
        switch event.type {
        case .task: "checkmark.circle"
        case .meeting: "person.2"
        case .travel: "car"
        case .buffer: "hourglass"
        }
    }

    private var color: Color {
        switch event.priority {
        case .urgent: .red
        case .high: .orange
        case .medium: .accentColor
        case .low: .gray
        }
    }
}
