import Foundation
import Testing
@testable import SmartSchedulerKit

@Suite struct WeeklyScheduleTests {
    private func rule(_ weekdays: [Int], _ start: String, _ end: String, active: Bool = true) -> WorkingHoursRule {
        WorkingHoursRule(id: UUID(), name: nil, weekdays: weekdays, startTime: start, endTime: end, active: active)
    }

    @Test func groupsDaysWithTheSameHoursIntoOneRule() {
        var schedule = WeeklySchedule.workweek
        schedule.days[5] = .init(start: 9 * 60, end: 14 * 60 + 30)
        schedule.days[6] = .init(startHour: 10, endHour: 13)

        #expect(schedule.rules == [
            WorkingHoursRuleRequest(name: "Horario laboral", weekdays: [1, 2, 3, 4], startTime: "09:00", endTime: "18:00"),
            WorkingHoursRuleRequest(name: "Horario laboral", weekdays: [5], startTime: "09:00", endTime: "14:30"),
            WorkingHoursRuleRequest(name: "Horario laboral", weekdays: [6], startTime: "10:00", endTime: "13:00"),
        ])
    }

    @Test func readsBackendRulesAndMergesSplitDays() {
        let schedule = WeeklySchedule(rules: [
            rule([1, 2], "09:00:00", "13:00:00"),
            rule([1], "14:00:00", "18:00:00"),
            rule([7], "10:00:00", "12:00:00", active: false),
        ])

        #expect(schedule.days == [
            1: .init(startHour: 9, endHour: 18),
            2: .init(startHour: 9, endHour: 13),
        ])
    }

    @Test func roundTripsThroughBackendRules() {
        let schedule = WeeklySchedule.workweek
        let rules = schedule.rules.map {
            rule($0.weekdays, $0.startTime + ":00", $0.endTime + ":00")
        }

        #expect(WeeklySchedule(rules: rules) == schedule)
    }

    @Test func validatesRanges() {
        #expect(WeeklySchedule.workweek.isValid)
        #expect(!WeeklySchedule(days: [:]).isValid)
        #expect(!WeeklySchedule(days: [1: .init(startHour: 18, endHour: 9)]).isValid)
        #expect(WeeklySchedule.clock(24 * 60) == "23:59")
    }

    @Test func replacesWorkingHoursWithPut() async throws {
        let transport = FakeTransport { _ in (200, "[]") }
        let api = SchedulerAPI(baseURL: baseURL, transport: transport)

        _ = try await api.replaceWorkingHours(userID: userID, WeeklySchedule.workweek.rules)

        let request = try #require(transport.requests.first)
        #expect(request.httpMethod == "PUT")
        #expect(request.url?.path == "/api/v1/users/\(userID.uuidString)/working-hours")
        let rules = try #require(jsonBody(request)["rules"] as? [[String: Any]])
        #expect(rules.first?["weekdays"] as? [Int] == [1, 2, 3, 4, 5])
        #expect(rules.first?["start_time"] as? String == "09:00")
    }
}
