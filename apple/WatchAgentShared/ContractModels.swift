import Foundation

public enum InputMode: String, Codable, Sendable {
    case voice
    case gesture
    case tap
}

public enum EntryMode: String, Codable, Sendable {
    case complication
    case siri
    case tap
}

public enum Decision: String, Codable, Sendable {
    case approve
    case reject
}

public enum ApprovalStatus: String, Codable, Sendable {
    case pending
    case approved
    case rejected
}

public struct WeatherSnapshotPayload: Codable, Sendable {
    public let locationName: String?
    public let tempC: Double?
    public let feelsLikeC: Double?
    public let humidity: Double?
    public let conditionDescription: String?
    public let todayMaxC: Double?
    public let todayMinC: Double?
    public let windSpeedKmh: Double?
    public let uvIndex: Int?

    public init(
        locationName: String? = nil,
        tempC: Double? = nil,
        feelsLikeC: Double? = nil,
        humidity: Double? = nil,
        conditionDescription: String? = nil,
        todayMaxC: Double? = nil,
        todayMinC: Double? = nil,
        windSpeedKmh: Double? = nil,
        uvIndex: Int? = nil
    ) {
        self.locationName = locationName
        self.tempC = tempC
        self.feelsLikeC = feelsLikeC
        self.humidity = humidity
        self.conditionDescription = conditionDescription
        self.todayMaxC = todayMaxC
        self.todayMinC = todayMinC
        self.windSpeedKmh = windSpeedKmh
        self.uvIndex = uvIndex
    }
}

public struct HealthSnapshotPayload: Codable, Sendable {
    public let heartRate: Double?
    public let restingHeartRate: Double?
    public let steps: Int?
    public let activeCalories: Double?
    public let bloodOxygen: Double?
    public let sleepHours: Double?
    public let sleepDeepMinutes: Int?
    public let sleepRemMinutes: Int?

    public init(
        heartRate: Double? = nil,
        restingHeartRate: Double? = nil,
        steps: Int? = nil,
        activeCalories: Double? = nil,
        bloodOxygen: Double? = nil,
        sleepHours: Double? = nil,
        sleepDeepMinutes: Int? = nil,
        sleepRemMinutes: Int? = nil
    ) {
        self.heartRate = heartRate
        self.restingHeartRate = restingHeartRate
        self.steps = steps
        self.activeCalories = activeCalories
        self.bloodOxygen = bloodOxygen
        self.sleepHours = sleepHours
        self.sleepDeepMinutes = sleepDeepMinutes
        self.sleepRemMinutes = sleepRemMinutes
    }
}

public struct DeviceContext: Codable, Sendable {
    public let watchModel: String?
    public let locale: String?
    public let timezone: String?
    public let batteryLevel: Double?
    public let connectivity: String?
    public let healthSnapshot: HealthSnapshotPayload?
    public let weatherSnapshot: WeatherSnapshotPayload?
    public let latitude: Double?
    public let longitude: Double?

    public init(
        watchModel: String? = nil,
        locale: String? = "zh-CN",
        timezone: String? = "Asia/Shanghai",
        batteryLevel: Double? = nil,
        connectivity: String? = "wifi",
        healthSnapshot: HealthSnapshotPayload? = nil,
        weatherSnapshot: WeatherSnapshotPayload? = nil,
        latitude: Double? = nil,
        longitude: Double? = nil
    ) {
        self.watchModel = watchModel
        self.locale = locale
        self.timezone = timezone
        self.batteryLevel = batteryLevel
        self.connectivity = connectivity
        self.healthSnapshot = healthSnapshot
        self.weatherSnapshot = weatherSnapshot
        self.latitude = latitude
        self.longitude = longitude
    }
}

public struct WatchCommandRequest: Codable, Sendable {
    public let sessionId: String
    public let utterance: String
    public let skillHint: String?
    public let inputMode: InputMode
    public let entryMode: EntryMode
    public let intentId: String?
    public let traceId: String
    public let deviceContext: DeviceContext
    public let timestamp: Date

    public init(
        sessionId: String,
        utterance: String,
        skillHint: String? = nil,
        inputMode: InputMode = .voice,
        entryMode: EntryMode = .tap,
        intentId: String? = nil,
        traceId: String = UUID().uuidString,
        deviceContext: DeviceContext,
        timestamp: Date = Date()
    ) {
        self.sessionId = sessionId
        self.utterance = utterance
        self.skillHint = skillHint
        self.inputMode = inputMode
        self.entryMode = entryMode
        self.intentId = intentId
        self.traceId = traceId
        self.deviceContext = deviceContext
        self.timestamp = timestamp
    }
}

public struct ActionCard: Codable, Identifiable, Hashable, Sendable {
    public var id: String { cardId }
    public let cardId: String
    public let title: String
    public let detail: String
    public let actionType: String
    public let actionPayload: [String: String]?
    public let requiresConfirmation: Bool
    public let executionMode: String
    public let priority: Int
    public let confirmToken: String?
    public let ctaApprove: String
    public let ctaReject: String
    public let primaryAction: String?
    public let rejectMode: String?

    public var isVoiceRejectOnly: Bool {
        actionType == "codex_decision" && (rejectMode ?? "") == "voice_only"
    }

    public var approvalId: String? {
        actionPayload?["approval_id"]
    }

    public var acpThreadId: String? {
        actionPayload?["acp_thread_id"]
    }

    public var openclawSessionId: String? {
        actionPayload?["openclaw_session_id"]
    }
}

public struct WatchReplyDebug: Codable, Sendable {
    public let skill: String?
    public let skillRunId: String?
    public let traceId: String?
    public let intentId: String?
    public let streamPath: String?
    public let firstResponseMs: Int?
    public let latencyTargetMs: Int?
    public let entryMode: String?
}

public struct WatchReply: Codable, Sendable {
    public let requestId: String
    public let sessionId: String
    public let speechText: String
    public let cards: [ActionCard]
    public let requiresConfirmation: Bool
    public let confirmToken: String?
    public let priority: Int
    public let createdAt: Date
    public let debug: WatchReplyDebug?
}

public struct WatchConfirmRequest: Codable, Sendable {
    public let sessionId: String
    public let confirmToken: String
    public let decision: Decision
    public let inputMode: InputMode
    public let followupText: String?
    public let timestamp: Date

    public init(
        sessionId: String,
        confirmToken: String,
        decision: Decision,
        inputMode: InputMode,
        followupText: String? = nil,
        timestamp: Date = Date()
    ) {
        self.sessionId = sessionId
        self.confirmToken = confirmToken
        self.decision = decision
        self.inputMode = inputMode
        self.followupText = followupText
        self.timestamp = timestamp
    }
}

public struct WatchConfirmResponse: Codable, Sendable {
    public let requestId: String
    public let sessionId: String
    public let speechText: String
    public let result: String
    public let createdAt: Date
}

public struct SkillStreamEvent: Codable, Identifiable {
    public let eventId: Int
    public let sessionId: String
    public let runId: String
    public let traceId: String
    public let eventType: String
    public let step: String
    public let payload: [String: AnyCodable]
    public let createdAt: Date

    public var id: Int { eventId }
}

public struct SkillEventsResponse: Codable {
    public let events: [SkillStreamEvent]
}

public struct SkillStateResponse: Codable {
    public let state: SkillRunState?
}

public struct SkillRunState: Codable {
    public let runId: String
    public let sessionId: String
    public let traceId: String
    public let intentId: String
    public let skillName: String
    public let state: String
    public let firstResponseMs: Int?
}

public struct ApprovalItem: Codable, Identifiable, Sendable {
    public var id: String { approvalId }
    public let approvalId: String
    public let title: String
    public let question: String
    public let suggestedAction: String?
    public let openclawSessionId: String
    public let acpThreadId: String
    public let status: ApprovalStatus
    public let priority: Int
}

public struct CodexQueueResponse: Codable, Sendable {
    public let items: [ApprovalItem]
}

public struct ApprovalDecisionRequest: Codable, Sendable {
    public let sessionId: String
    public let approvalId: String
    public let decision: Decision
    public let followupText: String?
    public let inputMode: InputMode
}

public struct ApprovalDecisionResponse: Codable, Sendable {
    public let approvalId: String
    public let status: ApprovalStatus
    public let speechText: String
    public let openclawSessionId: String
}

public struct OpenClawEvidenceResponse: Codable, Sendable {
    public let gatewayStatus: String
    public let telegramChannel: String
    public let latestOpenclawSessionIds: [String]
    public let evidenceNotes: [String]
}

// Simple AnyCodable for decoding dynamic payload fields in stream events.
public struct AnyCodable: Codable {
    public let value: Any

    public init(_ value: Any) {
        self.value = value
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let bool = try? container.decode(Bool.self) {
            self.value = bool
        } else if let int = try? container.decode(Int.self) {
            self.value = int
        } else if let double = try? container.decode(Double.self) {
            self.value = double
        } else if let string = try? container.decode(String.self) {
            self.value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            self.value = array.map { $0.value }
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            self.value = dict.mapValues { $0.value }
        } else if container.decodeNil() {
            self.value = NSNull()
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported payload")
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case let bool as Bool:
            try container.encode(bool)
        case let int as Int:
            try container.encode(int)
        case let double as Double:
            try container.encode(double)
        case let string as String:
            try container.encode(string)
        case let array as [Any]:
            try container.encode(array.map(AnyCodable.init))
        case let dict as [String: Any]:
            try container.encode(dict.mapValues(AnyCodable.init))
        default:
            try container.encodeNil()
        }
    }
}
