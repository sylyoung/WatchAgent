import AppIntents

struct StartMorningBriefIntent: AppIntent {
    static let title: LocalizedStringResource = "启动晨间简报"
    static let description = IntentDescription("通过Siri短语启动晨间Skill。")
    static let openAppWhenRun = true

    func perform() async throws -> some IntentResult & ProvidesDialog {
        NotificationCenter.default.post(name: .triggerSkill, object: "morning_brief")
        return .result(dialog: "正在启动晨间简报。")
    }
}

struct StartWorkProgressIntent: AppIntent {
    static let title: LocalizedStringResource = "启动工作进展"
    static let description = IntentDescription("通过Siri短语启动工作进展Skill。")
    static let openAppWhenRun = true

    func perform() async throws -> some IntentResult & ProvidesDialog {
        NotificationCenter.default.post(name: .triggerSkill, object: "work_progress")
        return .result(dialog: "正在启动工作进展。")
    }
}

struct StartMyMessagesIntent: AppIntent {
    static let title: LocalizedStringResource = "查看我的消息"
    static let description = IntentDescription("通过Siri短语查看待回复消息。")
    static let openAppWhenRun = true

    func perform() async throws -> some IntentResult & ProvidesDialog {
        NotificationCenter.default.post(name: .triggerSkill, object: "message_inbox")
        return .result(dialog: "正在查看消息。")
    }
}

struct StartPackageTrackingIntent: AppIntent {
    static let title: LocalizedStringResource = "查看快递"
    static let description = IntentDescription("通过Siri短语查看淘宝京东快递物流。")
    static let openAppWhenRun = true

    func perform() async throws -> some IntentResult & ProvidesDialog {
        NotificationCenter.default.post(name: .triggerSkill, object: "package_tracking")
        return .result(dialog: "正在查看快递物流。")
    }
}

struct StartHealthManagerIntent: AppIntent {
    static let title: LocalizedStringResource = "健康管理"
    static let description = IntentDescription("通过Siri短语启动健康管理Skill。")
    static let openAppWhenRun = true

    func perform() async throws -> some IntentResult & ProvidesDialog {
        NotificationCenter.default.post(name: .triggerSkill, object: "health_manager")
        return .result(dialog: "正在启动健康管理。")
    }
}

struct WatchAgentShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: StartMorningBriefIntent(),
            phrases: [
                "用 \(.applicationName) 启动晨间简报",
                "开始今天简报 using \(.applicationName)",
                "Ask \(.applicationName) for morning brief"
            ],
            shortTitle: "晨间简报",
            systemImageName: "sun.max"
        )
        AppShortcut(
            intent: StartWorkProgressIntent(),
            phrases: [
                "用 \(.applicationName) 启动工作进展",
                "查看工作进展 using \(.applicationName)",
                "Ask \(.applicationName) for work progress"
            ],
            shortTitle: "工作进展",
            systemImageName: "list.bullet.rectangle.portrait"
        )
        AppShortcut(
            intent: StartMyMessagesIntent(),
            phrases: [
                "用 \(.applicationName) 查看我的消息",
                "查看待回复消息 using \(.applicationName)",
                "Ask \(.applicationName) for my messages"
            ],
            shortTitle: "我的消息",
            systemImageName: "message"
        )
        AppShortcut(
            intent: StartPackageTrackingIntent(),
            phrases: [
                "用 \(.applicationName) 查看快递",
                "我的快递 using \(.applicationName)",
                "Ask \(.applicationName) for package tracking"
            ],
            shortTitle: "查看快递",
            systemImageName: "shippingbox"
        )
        AppShortcut(
            intent: StartHealthManagerIntent(),
            phrases: [
                "用 \(.applicationName) 健康管理",
                "查看健康状况 using \(.applicationName)",
                "Ask \(.applicationName) for health"
            ],
            shortTitle: "健康管理",
            systemImageName: "heart.fill"
        )
    }
}
