import SmartSchedulerKit
import SwiftUI

/// Edits the hours in which notes without a time can be placed.
struct WorkingHoursView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var schedule: WeeklySchedule?
    @State private var isSaving = false

    private static let weekdayNames = [
        1: "Lunes", 2: "Martes", 3: "Miércoles", 4: "Jueves",
        5: "Viernes", 6: "Sábado", 7: "Domingo",
    ]

    var body: some View {
        Form {
            if let schedule {
                Section {
                    ForEach(1...7, id: \.self) { day in
                        DayRow(
                            name: Self.weekdayNames[day]!,
                            hours: binding(for: day, in: schedule)
                        )
                    }
                } footer: {
                    Text("Las notas sin hora («esta semana», «el jueves») se colocan dentro de este horario. Las notas con hora se respetan aunque caigan fuera.")
                }
                if !schedule.isValid {
                    Text(schedule.days.isEmpty ? "Activa al menos un día." : "Cada día debe terminar después de empezar.")
                        .foregroundStyle(.red)
                }
                if let error = model.workingHoursError {
                    Text(error).foregroundStyle(.red)
                }
            } else if let error = model.workingHoursError {
                Label(error, systemImage: "wifi.exclamationmark")
            } else {
                ProgressView()
            }
        }
        .navigationTitle("Horario laboral")
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button(isSaving ? "Guardando…" : "Guardar") {
                    guard let schedule else { return }
                    Task {
                        isSaving = true
                        let saved = await model.saveWorkingHours(schedule)
                        isSaving = false
                        if saved { dismiss() }
                    }
                }
                .disabled(isSaving || !(schedule?.isValid ?? false))
            }
        }
        .task {
            await model.loadWorkingHours()
            schedule = model.workingHours
        }
    }

    private func binding(for day: Int, in schedule: WeeklySchedule) -> Binding<WeeklySchedule.Hours?> {
        Binding(
            get: { self.schedule?.days[day] },
            set: { self.schedule?.days[day] = $0 }
        )
    }
}

private struct DayRow: View {
    let name: String
    @Binding var hours: WeeklySchedule.Hours?
    /// Remembered so switching a day off and on again restores its hours.
    @State private var lastHours = WeeklySchedule.Hours(startHour: 9, endHour: 18)

    var body: some View {
        VStack(alignment: .leading) {
            Toggle(name, isOn: Binding(
                get: { hours != nil },
                set: { hours = $0 ? lastHours : nil }
            ))
            if let current = hours {
                HStack {
                    DatePicker("Desde", selection: time(\.start, current), displayedComponents: .hourAndMinute)
                    DatePicker("Hasta", selection: time(\.end, current), displayedComponents: .hourAndMinute)
                }
                .labelsHidden()
                .onChange(of: current) { _, new in lastHours = new }
            }
        }
    }

    private func time(_ keyPath: WritableKeyPath<WeeklySchedule.Hours, Int>, _ current: WeeklySchedule.Hours) -> Binding<Date> {
        let midnight = Calendar.current.startOfDay(for: .now)
        return Binding(
            get: { midnight.addingTimeInterval(TimeInterval(current[keyPath: keyPath] * 60)) },
            set: { date in
                let parts = Calendar.current.dateComponents([.hour, .minute], from: date)
                var updated = current
                updated[keyPath: keyPath] = (parts.hour ?? 0) * 60 + (parts.minute ?? 0)
                hours = updated
            }
        )
    }
}
