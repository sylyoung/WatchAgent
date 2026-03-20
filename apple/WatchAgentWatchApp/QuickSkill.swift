import Foundation

enum QuickSkill: String, CaseIterable, Identifiable {
    case morningBrief = "晨间简报"
    case workProgress = "工作进展"
    case ride = "出行叫车"
    case message = "我的消息"
    case packageTracking = "查看快递"
    case healthManager = "健康管理"

    var id: String { rawValue }

    var spokenCommand: String {
        switch self {
        case .morningBrief: return "今日日程"
        case .workProgress: return "工作进展"
        case .ride: return "叫车"
        case .message: return "我的消息"
        case .packageTracking: return "查看快递"
        case .healthManager: return "健康管理"
        }
    }

    var hint: String {
        switch self {
        case .morningBrief: return "morning_brief"
        case .workProgress: return "work_progress"
        case .ride: return "ride_hailing"
        case .message: return "message_inbox"
        case .packageTracking: return "package_tracking"
        case .healthManager: return "health_manager"
        }
    }
}
