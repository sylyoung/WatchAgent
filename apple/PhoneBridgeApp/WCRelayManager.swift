import Foundation
import WatchConnectivity

final class WCRelayManager: NSObject, WCSessionDelegate {
    typealias Update = (_ state: String, _ event: String) -> Void

    private let apiClient: WatchAgentAPIClient
    private let baseURLString: String
    private let onUpdate: Update

    init(baseURL: URL, onUpdate: @escaping Update) {
        self.apiClient = WatchAgentAPIClient(baseURL: baseURL)
        self.baseURLString = baseURL.absoluteString
        self.onUpdate = onUpdate
        super.init()
    }

    func activate() {
        guard WCSession.isSupported() else {
            onUpdate("unsupported", "WCSession unavailable")
            return
        }

        let session = WCSession.default
        session.delegate = self
        if session.activationState == .activated {
            onUpdate("active", "ready · \(baseURLString)")
        } else {
            session.activate()
            onUpdate("activating", "relay activating")
        }
    }

    func deactivate() {
        onUpdate("inactive", "relay deactivated")
    }

    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        let state = activationState == .activated ? "active" : "inactive"
        onUpdate(state, error?.localizedDescription ?? "session ready")
    }

    func sessionDidBecomeInactive(_ session: WCSession) {
        _ = session
        onUpdate("inactive", "session became inactive")
    }

    func sessionDidDeactivate(_ session: WCSession) {
        _ = session
        onUpdate("deactivated", "session deactivated")
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        _ = session
        Task { @MainActor [weak self] in
            await self?.handleIncomingMessage(message, replyHandler: nil)
        }
    }

    func session(
        _ session: WCSession,
        didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        _ = session
        Task { @MainActor [weak self] in
            await self?.handleIncomingMessage(message, replyHandler: replyHandler)
        }
    }

    private func handleIncomingMessage(_ message: [String: Any], replyHandler: (([String: Any]) -> Void)?) async {
        let kind = (message["kind"] as? String) ?? "command"

        do {
            if kind == "tts" {
                let text = (message["text"] as? String) ?? ""
                let voiceType = (message["voice_type"] as? String) ?? "zh_female_vv_uranus_bigtts"
                let speedRatio = (message["speed_ratio"] as? Double) ?? 1.0
                print("[WCRelay] TTS request: text=\(text.prefix(30)), voice=\(voiceType), speed=\(speedRatio), baseURL=\(baseURLString)")
                do {
                    let audioData = try await apiClient.fetchTTS(text: text, voiceType: voiceType, speedRatio: speedRatio)
                    let base64String = audioData.base64EncodedString()
                    onUpdate("active", "forwarded TTS (\(audioData.count) bytes)")
                    print("[WCRelay] TTS success: \(audioData.count) bytes")
                    replyHandler?(["audio_base64": base64String])
                } catch {
                    print("[WCRelay] TTS error: \(error)")
                    replyHandler?(["error": "TTS failed: \(error.localizedDescription)"])
                }
                return
            }

            if kind == "get_events" {
                let sessionId = (message["session_id"] as? String) ?? ""
                let afterEventId = (message["after_event_id"] as? Int) ?? 0
                let limit = (message["limit"] as? Int) ?? 100
                let response = try await apiClient.fetchSkillEvents(sessionId: sessionId, afterEventId: afterEventId, limit: limit)
                replyHandler?(encodableToDict(response))
                return
            }

            if kind == "confirm" {
                let confirm = WatchConfirmRequest(
                    sessionId: (message["session_id"] as? String) ?? UUID().uuidString,
                    confirmToken: (message["confirm_token"] as? String) ?? "",
                    decision: ((message["decision"] as? String) == "reject") ? .reject : .approve,
                    inputMode: .voice,
                    followupText: message["followup_text"] as? String
                )
                let response = try await apiClient.sendConfirmation(confirm)
                onUpdate("active", "forwarded watch confirm")
                replyHandler?(encodableToDict(response))
                return
            }

            guard let utterance = message["utterance"] as? String else {
                onUpdate("active", "received malformed command")
                replyHandler?(["error": "malformed message"])
                return
            }

            let lat = message["latitude"] as? Double
            let lon = message["longitude"] as? Double
            let command = WatchCommandRequest(
                sessionId: (message["session_id"] as? String) ?? UUID().uuidString,
                utterance: utterance,
                skillHint: message["skill_hint"] as? String,
                inputMode: .voice,
                entryMode: ((message["entry_mode"] as? String) == "siri") ? .siri : .tap,
                intentId: message["intent_id"] as? String,
                traceId: UUID().uuidString,
                deviceContext: DeviceContext(watchModel: "watch-via-iphone", latitude: lat, longitude: lon)
            )

            let response = try await apiClient.sendCommand(command)
            onUpdate("active", "forwarded watch command: \(utterance)")
            replyHandler?(encodableToDict(response))
        } catch {
            onUpdate("active", "relay error [\(baseURLString)]: \(error.localizedDescription)")
            replyHandler?(["error": error.localizedDescription])
        }
    }

    private func encodableToDict<T: Encodable>(_ value: T) -> [String: Any] {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .iso8601

        guard let data = try? encoder.encode(value) else { return [:] }
        guard let object = try? JSONSerialization.jsonObject(with: data) else { return [:] }
        guard var dict = object as? [String: Any] else { return [:] }
        // WatchConnectivity reply limit is ~65 KB. Truncate large fields.
        if let speech = dict["speech_text"] as? String, speech.count > 800 {
            dict["speech_text"] = String(speech.prefix(800)) + "…"
        }
        if let lines = dict["stream_lines"] as? [Any], lines.count > 6 {
            dict["stream_lines"] = Array(lines.suffix(6))
        }
        return sanitizeForWC(dict) as? [String: Any] ?? [:]
    }

    // WatchConnectivity does not support NSNull — strip it recursively.
    private func sanitizeForWC(_ value: Any) -> Any {
        if value is NSNull { return "<null>" }
        if let dict = value as? [String: Any] {
            return dict.compactMapValues { v -> Any? in
                let s = sanitizeForWC(v)
                return (s is NSNull) ? nil : s
            }
        }
        if let arr = value as? [Any] {
            return arr.map { sanitizeForWC($0) }
        }
        return value
    }
}
