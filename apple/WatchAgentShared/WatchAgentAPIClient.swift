import Foundation

public final class WatchAgentAPIClient: @unchecked Sendable {
    public enum APIError: LocalizedError {
        case invalidResponse
        case serverError(Int, Data)

        public var errorDescription: String? {
            switch self {
            case .invalidResponse:
                return "Invalid response (not HTTP)"
            case .serverError(let code, let data):
                let body = String(data: data.prefix(200), encoding: .utf8) ?? "<binary>"
                return "HTTP \(code): \(body)"
            }
        }
    }

    private let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder
    private let apiKey: String?

    public init(baseURL: URL, session: URLSession = .shared, apiKey: String? = nil) {
        self.apiKey = apiKey
        self.baseURL = baseURL
        self.session = session

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder

        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder
    }

    public func sendCommand(_ payload: WatchCommandRequest) async throws -> WatchReply {
        try await post(path: "/v1/watch/command", payload: payload)
    }

    public func sendConfirmation(_ payload: WatchConfirmRequest) async throws -> WatchConfirmResponse {
        try await post(path: "/v1/watch/confirm", payload: payload)
    }

    public func fetchSkillEvents(sessionId: String, afterEventId: Int = 0, limit: Int = 100) async throws -> SkillEventsResponse {
        try await get(path: "/v1/skills/\(sessionId)/events?after_event_id=\(afterEventId)&limit=\(limit)")
    }

    public func fetchSkillState(sessionId: String) async throws -> SkillStateResponse {
        try await get(path: "/v1/skills/\(sessionId)/state")
    }

    public func fetchCodexQueue(onlyPending: Bool = true) async throws -> CodexQueueResponse {
        try await get(path: "/v1/codex/queue?only_pending=\(onlyPending ? "true" : "false")")
    }

    public func submitCodexDecision(_ payload: ApprovalDecisionRequest) async throws -> ApprovalDecisionResponse {
        try await post(path: "/v1/codex/decision", payload: payload)
    }

    public func fetchOpenClawEvidence() async throws -> OpenClawEvidenceResponse {
        try await get(path: "/v1/openclaw/evidence")
    }

    /// Synthesize text to MP3 audio via Volcano Engine TTS. Returns raw audio bytes.
    public func fetchTTS(text: String, voiceType: String, speedRatio: Double) async throws -> Data {
        let normalizedPath = "v1/tts"
        let url = baseURL.appendingPathComponent(normalizedPath)
        print("[API DEBUG] POST \(url.absoluteString)")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.addValue("application/json", forHTTPHeaderField: "Content-Type")
        if let apiKey { request.addValue(apiKey, forHTTPHeaderField: "X-Api-Key") }

        let body: [String: Any] = ["text": text, "voice_type": voiceType, "speed_ratio": speedRatio]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: request)
        print("[API DEBUG] TTS response type: \(type(of: response)), url: \(response.url?.absoluteString ?? "nil")")
        guard let http = response as? HTTPURLResponse else {
            print("[API DEBUG] TTS response is NOT HTTPURLResponse!")
            throw APIError.invalidResponse
        }
        print("[API DEBUG] TTS HTTP \(http.statusCode), bytes: \(data.count)")
        guard (200 ... 299).contains(http.statusCode) else {
            throw APIError.serverError(http.statusCode, data)
        }
        return data
    }

    private func get<T: Decodable>(path: String) async throws -> T {
        let normalizedPath = path.hasPrefix("/") ? String(path.dropFirst()) : path
        // Split path and query to use appendingPathComponent (same as post)
        let parts = normalizedPath.split(separator: "?", maxSplits: 1)
        var url = baseURL.appendingPathComponent(String(parts[0]))
        if parts.count > 1, var components = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            components.query = String(parts[1])
            url = components.url ?? url
        }
        print("[API DEBUG] GET \(url.absoluteString)")

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        if let apiKey { request.addValue(apiKey, forHTTPHeaderField: "X-Api-Key") }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200 ... 299).contains(http.statusCode) else {
            throw APIError.serverError(http.statusCode, data)
        }

        return try decoder.decode(T.self, from: data)
    }

    private func post<T: Decodable, U: Encodable>(path: String, payload: U) async throws -> T {
        let normalizedPath = path.hasPrefix("/") ? String(path.dropFirst()) : path
        let url = baseURL.appendingPathComponent(normalizedPath)
        print("[API DEBUG] POST \(url.absoluteString)")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.addValue("application/json", forHTTPHeaderField: "Content-Type")
        if let apiKey { request.addValue(apiKey, forHTTPHeaderField: "X-Api-Key") }
        request.httpBody = try encoder.encode(payload)

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200 ... 299).contains(http.statusCode) else {
            throw APIError.serverError(http.statusCode, data)
        }

        return try decoder.decode(T.self, from: data)
    }
}
