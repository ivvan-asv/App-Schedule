import Foundation

/// Working hours as the settings screen edits them: one range per weekday.
///
/// The backend stores them as rules that share a range across several days;
/// `rules` groups equal days back into as few rules as possible.
public struct WeeklySchedule: Sendable, Equatable {
    public struct Hours: Sendable, Equatable, Hashable {
        /// Minutes after midnight, local wall-clock time.
        public var start: Int
        public var end: Int

        public init(start: Int, end: Int) {
            self.start = start
            self.end = end
        }

        public init(startHour: Int, endHour: Int) {
            self.init(start: startHour * 60, end: endHour * 60)
        }

        public var isValid: Bool {
            0 <= start && start < end && end <= 24 * 60
        }
    }

    /// ISO weekday (1 = Monday … 7 = Sunday) → hours. Missing days are free.
    public var days: [Int: Hours]

    public init(days: [Int: Hours]) {
        self.days = days
    }

    public static let workweek = WeeklySchedule(
        days: Dictionary(uniqueKeysWithValues: (1...5).map { ($0, Hours(startHour: 9, endHour: 18)) })
    )

    /// Reads backend rules. A day covered by several rules keeps the earliest
    /// start and latest end, since this editor shows one range per day.
    public init(rules: [WorkingHoursRule]) {
        var days: [Int: Hours] = [:]
        for rule in rules where rule.active {
            guard let start = rule.startTime.flatMap(Self.minutes),
                  let end = rule.endTime.flatMap(Self.minutes)
            else { continue }
            for day in rule.weekdays where (1...7).contains(day) {
                if let existing = days[day] {
                    days[day] = Hours(start: min(existing.start, start), end: max(existing.end, end))
                } else {
                    days[day] = Hours(start: start, end: end)
                }
            }
        }
        self.days = days
    }

    public var isValid: Bool {
        !days.isEmpty && days.values.allSatisfy(\.isValid)
    }

    public var rules: [WorkingHoursRuleRequest] {
        let grouped = Dictionary(grouping: days.keys.sorted()) { days[$0]! }
        return grouped
            .map { hours, weekdays in
                WorkingHoursRuleRequest(
                    name: "Horario laboral",
                    weekdays: weekdays.sorted(),
                    startTime: Self.clock(hours.start),
                    endTime: Self.clock(hours.end)
                )
            }
            .sorted { $0.weekdays[0] < $1.weekdays[0] }
    }

    /// "09:00" or "09:00:00" → 540.
    static func minutes(_ clock: String) -> Int? {
        let parts = clock.split(separator: ":").compactMap { Int($0) }
        guard parts.count >= 2, (0...24).contains(parts[0]), (0..<60).contains(parts[1]) else { return nil }
        return parts[0] * 60 + parts[1]
    }

    /// 540 → "09:00". The backend's TIME type has no 24:00, so midnight ends at 23:59.
    static func clock(_ minutes: Int) -> String {
        let capped = min(minutes, 24 * 60 - 1)
        return String(format: "%02d:%02d", capped / 60, capped % 60)
    }
}
