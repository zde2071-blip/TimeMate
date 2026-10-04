import EventKit
import Foundation

struct CalendarRequest: Decodable {
    let title: String
    let start: String
    let end: String
    let location: String
    let notes: String
    let allDay: Bool
}

func output(_ data: [String: String]) {
    if let encoded = try? JSONSerialization.data(withJSONObject: data),
       let line = String(data: encoded, encoding: .utf8) {
        print(line)
    }
}

@main
struct CalendarBridge {
    static func main() async {
        if CommandLine.arguments.contains("--status") {
            let status = EKEventStore.authorizationStatus(for: .event)
            output(["status": String(describing: status)])
            return
        }
        do {
            guard let line = readLine(), let data = line.data(using: .utf8) else {
                throw NSError(domain: "MailAssistant", code: 1, userInfo: [NSLocalizedDescriptionKey: "没有收到日程数据"])
            }
            let request = try JSONDecoder().decode(CalendarRequest.self, from: data)
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = .current
            formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            guard let start = formatter.date(from: request.start),
                  let end = formatter.date(from: request.end), end > start else {
                throw NSError(domain: "MailAssistant", code: 2, userInfo: [NSLocalizedDescriptionKey: "日程时间无效"])
            }
            let store = EKEventStore()
            let granted = try await store.requestWriteOnlyAccessToEvents()
            guard granted else {
                throw NSError(domain: "MailAssistant", code: 3, userInfo: [NSLocalizedDescriptionKey: "尚未允许写入 Apple 日历"])
            }
            guard let calendar = store.defaultCalendarForNewEvents else {
                throw NSError(domain: "MailAssistant", code: 4, userInfo: [NSLocalizedDescriptionKey: "没有可写入的默认日历"])
            }
            let event = EKEvent(eventStore: store)
            event.calendar = calendar
            event.title = request.title
            event.startDate = start
            event.endDate = end
            event.isAllDay = request.allDay
            event.location = request.location
            event.notes = request.notes
            try store.save(event, span: .thisEvent, commit: true)
            output(["status": "saved", "eventId": event.eventIdentifier ?? "", "calendar": calendar.title])
        } catch {
            output(["status": "error", "message": error.localizedDescription])
        }
    }
}
